#!/usr/bin/env python3
"""Generate Daredevil artifact figures from safe evaluation outputs.

The paper's main figures were produced on raw NVMe namespaces and longer,
larger workloads. This parser intentionally works on the safe artifact flow in
eval/results-artifact, where all I/O is file-backed for a single-NVMe machine.
"""

from __future__ import annotations

import argparse
import math
import os
import re
from pathlib import Path
from typing import Iterable

os.environ.setdefault(
    "MPLCONFIGDIR",
    str(Path(__file__).resolve().parents[1] / ".mplconfig"),
)

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns


SYSTEM_ORDER = ["vanilla", "blkswitch", "daredevil"]
SYSTEM_LABELS = {
    "vanilla": "Vanilla",
    "blkswitch": "Blk-switch",
    "daredevil": "Daredevil",
}
SYSTEM_COLORS = {
    "vanilla": "#555555",
    "blkswitch": "#2a6fbb",
    "daredevil": "#c43c39",
}


def read_text(path: Path) -> str:
    return path.read_text(errors="replace")


def parse_scaled_number(text: str) -> float:
    match = re.fullmatch(r"\s*([0-9]*\.?[0-9]+)\s*([kKmMgG]?)\s*", text)
    if not match:
        raise ValueError(f"cannot parse scaled number: {text!r}")
    value = float(match.group(1))
    suffix = match.group(2).lower()
    if suffix == "k":
        return value * 1_000
    if suffix == "m":
        return value * 1_000_000
    if suffix == "g":
        return value * 1_000_000_000
    return value


def parse_bw_to_mib_s(value: str, unit: str) -> float:
    value_f = float(value)
    unit = unit.lower()
    if unit == "b/s":
        return value_f / 1024 / 1024
    if unit == "kib/s":
        return value_f / 1024
    if unit == "mib/s":
        return value_f
    if unit == "gib/s":
        return value_f * 1024
    if unit == "kb/s":
        return value_f * 1000 / 1024 / 1024
    if unit == "mb/s":
        return value_f * 1000 * 1000 / 1024 / 1024
    if unit == "gb/s":
        return value_f * 1000 * 1000 * 1000 / 1024 / 1024
    raise ValueError(f"unknown bandwidth unit: {unit}")


def split_fio_section(text: str, op: str) -> str:
    start = re.search(rf"^\s+{op}:\s+IOPS=.*$", text, re.MULTILINE)
    if not start:
        return ""
    next_op = re.search(r"^\s+(read|write|trim):\s+IOPS=.*$", text[start.end() :], re.MULTILINE)
    end = start.end() + next_op.start() if next_op else len(text)
    return text[start.start() : end]


def parse_fio_op(text: str, op: str) -> dict[str, float]:
    section = split_fio_section(text, op)
    if not section:
        return {}

    header = re.search(
        rf"^\s+{op}:\s+IOPS=([^,]+),\s+BW=([0-9.]+)([A-Za-z/]+)",
        section,
        re.MULTILINE,
    )
    result: dict[str, float] = {}
    if header:
        result["iops"] = parse_scaled_number(header.group(1))
        result["bw_mib_s"] = parse_bw_to_mib_s(header.group(2), header.group(3))

    lat = re.search(
        r"^\s+lat \((usec|msec)\):.*?avg=\s*([0-9.]+)",
        section,
        re.MULTILINE,
    )
    if lat:
        divisor = 1000 if lat.group(1) == "usec" else 1
        result["lat_avg_ms"] = float(lat.group(2)) / divisor

    clat_unit = None
    percentile_block = re.search(
        r"clat percentiles \((usec|msec)\):(?P<body>(?:\n\s+\|.*)+)",
        section,
    )
    if percentile_block:
        clat_unit = percentile_block.group(1)
        body = percentile_block.group("body")
        p999 = re.search(r"99\.90th=\[\s*([0-9.]+)\]", body)
        if p999:
            divisor = 1000 if clat_unit == "usec" else 1
            result["clat_p999_ms"] = float(p999.group(1)) / divisor

    return result


def parse_fio_incremental(results_dir: Path) -> pd.DataFrame:
    rows = []
    for system_dir in results_dir.iterdir():
        if not system_dir.is_dir():
            continue
        system = system_dir.name
        base = system_dir / "fio-filebacked-incr-tenants"
        for fio_file in sorted(base.glob("t-tenants-*/fio.out")):
            match = re.search(r"t-tenants-(\d+)", str(fio_file))
            if not match:
                continue
            text = read_text(fio_file)
            read_metrics = parse_fio_op(text, "read")
            write_metrics = parse_fio_op(text, "write")
            if not read_metrics:
                continue
            rows.append(
                {
                    "system": system,
                    "t_tenants": int(match.group(1)),
                    "l_iops": read_metrics.get("iops", math.nan),
                    "l_bw_mib_s": read_metrics.get("bw_mib_s", math.nan),
                    "l_avg_latency_ms": read_metrics.get("lat_avg_ms", math.nan),
                    "l_p999_clat_ms": read_metrics.get("clat_p999_ms", math.nan),
                    "t_iops": write_metrics.get("iops", math.nan),
                    "t_bw_mib_s": write_metrics.get("bw_mib_s", math.nan),
                    "t_avg_latency_ms": write_metrics.get("lat_avg_ms", math.nan),
                    "t_p999_clat_ms": write_metrics.get("clat_p999_ms", math.nan),
                }
            )
    return sort_systems(pd.DataFrame(rows))


def parse_ionice(results_dir: Path) -> pd.DataFrame:
    rows = []
    for system_dir in results_dir.iterdir():
        if not system_dir.is_dir():
            continue
        system = system_dir.name
        for fio_file in sorted((system_dir / "ionice-freq").glob("fio-ionice-freq-*.fio")):
            match = re.search(r"freq-(\d+)\.fio$", fio_file.name)
            if not match:
                continue
            text = read_text(fio_file)
            read_metrics = parse_fio_op(text, "read")
            if not read_metrics:
                continue
            rows.append(
                {
                    "system": system,
                    "changes_per_min": int(match.group(1)),
                    "iops": read_metrics.get("iops", math.nan),
                    "bw_mib_s": read_metrics.get("bw_mib_s", math.nan),
                    "avg_latency_ms": read_metrics.get("lat_avg_ms", math.nan),
                    "p999_clat_ms": read_metrics.get("clat_p999_ms", math.nan),
                }
            )
    return sort_systems(pd.DataFrame(rows))


def parse_filebench(results_dir: Path) -> pd.DataFrame:
    rows = []
    summary_re = re.compile(
        r"IO Summary:\s+([0-9]+)\s+ops\s+([0-9.]+)\s+ops/s.*?\s+([0-9.]+)ms/op"
    )
    op_re = re.compile(
        r"^(fsyncfile[23]|deletefile1)\s+([0-9]+)ops\s+([0-9.]+)ops/s.*?\s+([0-9.]+)ms/op",
        re.MULTILINE,
    )
    for system_dir in results_dir.iterdir():
        out = system_dir / "filebench-mailserver" / "filebench.out"
        if not out.exists():
            continue
        text = read_text(out)
        summary = summary_re.search(text)
        if not summary:
            continue
        row = {
            "system": system_dir.name,
            "ops": int(summary.group(1)),
            "ops_s": float(summary.group(2)),
            "avg_ms_op": float(summary.group(3)),
        }
        for match in op_re.finditer(text):
            op = match.group(1)
            row[f"{op}_ops_s"] = float(match.group(3))
            row[f"{op}_avg_ms"] = float(match.group(4))
        rows.append(row)
    return sort_systems(pd.DataFrame(rows))


def parse_ycsb_file(path: Path, phase: str, system: str) -> dict[str, float | str]:
    text = read_text(path)
    row: dict[str, float | str] = {"system": system, "phase": phase}
    for line in text.splitlines():
        match = re.match(r"\[([^]]+)\],\s*([^,]+),\s*([0-9.]+)", line)
        if not match:
            continue
        section, metric, value = match.groups()
        key = f"{section.lower()}_{metric.strip().lower().replace('(', '_').replace(')', '').replace('/', '_').replace('%', 'pct').replace(' ', '_')}"
        row[key] = float(value)

    for op in ["READ", "UPDATE", "INSERT"]:
        interval = re.search(
            rf"\[{op}:\s+Count=[0-9]+,.*?99\.9=([0-9.]+)",
            text,
        )
        if interval:
            row[f"{op.lower()}_p999_latency_us_interval"] = float(interval.group(1))
    return row


def parse_ycsb(results_dir: Path) -> pd.DataFrame:
    rows = []
    for system_dir in results_dir.iterdir():
        base = system_dir / "rocksdb-ycsb"
        if not base.exists():
            continue
        for phase, name in [("load", "ycsb.load"), ("run", "ycsb.run")]:
            path = base / name
            if path.exists():
                rows.append(parse_ycsb_file(path, phase, system_dir.name))
    return sort_systems(pd.DataFrame(rows))


def sort_systems(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "system" not in df:
        return df
    order = {name: idx for idx, name in enumerate(SYSTEM_ORDER)}
    sort_cols = [
        c
        for c in ["system_order", "t_tenants", "changes_per_min", "phase"]
        if c == "system_order" or c in df.columns
    ]
    return (
        df.assign(system_order=df["system"].map(order).fillna(999))
        .sort_values(sort_cols)
        .drop(columns=["system_order"])
        .reset_index(drop=True)
    )


def lineplot(
    df: pd.DataFrame,
    x: str,
    y: str,
    ax: plt.Axes,
    ylabel: str,
    xlabel: str,
    title: str,
    logx: bool = False,
) -> None:
    sns.lineplot(
        data=df,
        x=x,
        y=y,
        hue="system",
        hue_order=[s for s in SYSTEM_ORDER if s in set(df["system"])],
        palette=SYSTEM_COLORS,
        marker="o",
        ax=ax,
    )
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    if logx:
        ax.set_xscale("log")
    handles, labels = ax.get_legend_handles_labels()
    ax.legend(handles, [SYSTEM_LABELS.get(label, label) for label in labels], frameon=False)
    ax.grid(True, alpha=0.25)


def barplot(df: pd.DataFrame, x: str, y: str, ax: plt.Axes, ylabel: str, title: str) -> None:
    sns.barplot(
        data=df,
        x=x,
        y=y,
        hue="system",
        hue_order=[s for s in SYSTEM_ORDER if s in set(df["system"])],
        palette=SYSTEM_COLORS,
        ax=ax,
    )
    ax.set_title(title)
    ax.set_xlabel("")
    ax.set_ylabel(ylabel)
    handles, labels = ax.get_legend_handles_labels()
    ax.legend(handles, [SYSTEM_LABELS.get(label, label) for label in labels], frameon=False)
    ax.grid(True, axis="y", alpha=0.25)


def save_figure(fig: plt.Figure, stem: str, plots_dir: Path) -> None:
    fig.tight_layout()
    for ext in ["png", "svg"]:
        fig.savefig(plots_dir / f"{stem}.{ext}", dpi=180, bbox_inches="tight")
    plt.close(fig)


def write_csvs(datasets: dict[str, pd.DataFrame], summary_dir: Path) -> None:
    for name, df in datasets.items():
        if not df.empty:
            df.to_csv(summary_dir / f"{name}.csv", index=False)


def generate_plots(datasets: dict[str, pd.DataFrame], plots_dir: Path) -> list[str]:
    generated = []
    fio = datasets["fio_incremental"]
    if not fio.empty:
        fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
        lineplot(
            fio,
            "t_tenants",
            "l_p999_clat_ms",
            axes[0],
            "L-tenant 99.9th clat (ms)",
            "T-tenants",
            "Fig. 6 approx: L tail latency",
        )
        lineplot(
            fio,
            "t_tenants",
            "l_avg_latency_ms",
            axes[1],
            "L-tenant avg latency (ms)",
            "T-tenants",
            "Fig. 6 approx: L avg latency",
        )
        save_figure(fig, "fig6_approx_latency", plots_dir)
        generated.append("fig6_approx_latency")

        fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
        lineplot(
            fio,
            "t_tenants",
            "l_iops",
            axes[0],
            "L-tenant IOPS",
            "T-tenants",
            "Fig. 6 approx: L I/O rate",
        )
        lineplot(
            fio,
            "t_tenants",
            "t_bw_mib_s",
            axes[1],
            "T-tenant write BW (MiB/s)",
            "T-tenants",
            "Fig. 6 approx: T throughput",
        )
        save_figure(fig, "fig6_approx_throughput", plots_dir)
        generated.append("fig6_approx_throughput")

    ycsb = datasets["ycsb"]
    filebench = datasets["filebench"]
    if not ycsb.empty or not filebench.empty:
        fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
        if not ycsb.empty:
            y = ycsb.rename(
                columns={"overall_throughput_ops_sec": "throughput_ops_s"}
            )
            barplot(
                y,
                "phase",
                "throughput_ops_s",
                axes[0],
                "YCSB throughput (ops/s)",
                "Fig. 12 approx: RocksDB/YCSB",
            )
        else:
            axes[0].axis("off")
        if not filebench.empty:
            barplot(
                filebench,
                "system",
                "ops_s",
                axes[1],
                "Filebench ops/s",
                "Fig. 12 approx: Mailserver",
            )
            axes[1].get_legend().remove()
            axes[1].set_xticklabels([SYSTEM_LABELS.get(t.get_text(), t.get_text()) for t in axes[1].get_xticklabels()])
        else:
            axes[1].axis("off")
        save_figure(fig, "fig12_approx_real_workloads", plots_dir)
        generated.append("fig12_approx_real_workloads")

    ionice = datasets["ionice"]
    if not ionice.empty:
        fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
        lineplot(
            ionice,
            "changes_per_min",
            "iops",
            axes[0],
            "IOPS",
            "ionice changes/min",
            "Fig. 14 approx: I/O rate",
            logx=True,
        )
        lineplot(
            ionice,
            "changes_per_min",
            "p999_clat_ms",
            axes[1],
            "99.9th clat (ms)",
            "ionice changes/min",
            "Fig. 14 approx: tail latency",
            logx=True,
        )
        save_figure(fig, "fig14_approx_ionice_frequency", plots_dir)
        generated.append("fig14_approx_ionice_frequency")

    return generated


def md_table(df: pd.DataFrame, columns: Iterable[str], max_rows: int = 30) -> str:
    if df.empty:
        return "_No data found._"
    view = df.loc[:, [c for c in columns if c in df.columns]].head(max_rows)
    if view.empty:
        return "_No selected columns found._"

    def fmt(value: object) -> str:
        if pd.isna(value):
            return ""
        if isinstance(value, float):
            return f"{value:.4g}"
        return str(value)

    header = [str(c) for c in view.columns]
    rows = [[fmt(value) for value in row] for row in view.itertuples(index=False, name=None)]
    widths = [
        max(len(header[idx]), *(len(row[idx]) for row in rows))
        for idx in range(len(header))
    ]
    lines = [
        "| " + " | ".join(header[idx].ljust(widths[idx]) for idx in range(len(header))) + " |",
        "| " + " | ".join("-" * widths[idx] for idx in range(len(header))) + " |",
    ]
    lines.extend(
        "| " + " | ".join(row[idx].ljust(widths[idx]) for idx in range(len(header))) + " |"
        for row in rows
    )
    return "\n".join(lines)


def write_report(datasets: dict[str, pd.DataFrame], generated: list[str], summary_dir: Path, plots_dir: Path) -> None:
    fio = datasets["fio_incremental"]
    ycsb = datasets["ycsb"]
    filebench = datasets["filebench"]
    ionice = datasets["ionice"]

    lines = [
        "# Daredevil Artifact Figure Summary",
        "",
        "Generated from `eval/results-artifact/*` using the safe single-NVMe artifact workflow.",
        "",
        "## Scope",
        "",
        "- Fig. 6 is approximated with file-backed FIO, one filesystem namespace, L-tenants as 4 KiB random reads and T-tenants as 128 KiB random writes.",
        "- Fig. 12 is approximated with the reduced RocksDB/YCSB `workloada` run and Filebench mailserver run available in the artifact results.",
        "- Fig. 14 is approximated with the safe ionice update-frequency experiment.",
        "- Paper figures requiring raw namespaces, multiple NVMe namespaces, BCC tracing, WS-M traces, or Daredevil subsystem ablations are not generated from this result set.",
        "",
        "## Generated Figures",
        "",
    ]
    if generated:
        lines.extend([f"- `eval/plots/{name}.png` and `.svg`" for name in generated])
    else:
        lines.append("- No figures generated; expected result files were missing or unparsable.")

    lines.extend(
        [
            "",
            "## Fig. 6 Approximation Data",
            "",
            md_table(
                fio,
                [
                    "system",
                    "t_tenants",
                    "l_iops",
                    "l_avg_latency_ms",
                    "l_p999_clat_ms",
                    "t_bw_mib_s",
                ],
            ),
            "",
            "## Fig. 12 Approximation Data",
            "",
            "### RocksDB/YCSB",
            "",
            md_table(
                ycsb,
                [
                    "system",
                    "phase",
                    "overall_throughput_ops_sec",
                    "read_averagelatency_us",
                    "read_99thpercentilelatency_us",
                    "read_p999_latency_us_interval",
                    "update_averagelatency_us",
                    "update_99thpercentilelatency_us",
                    "update_p999_latency_us_interval",
                    "insert_averagelatency_us",
                    "insert_99thpercentilelatency_us",
                    "insert_p999_latency_us_interval",
                ],
            ),
            "",
            "### Filebench Mailserver",
            "",
            md_table(
                filebench,
                [
                    "system",
                    "ops",
                    "ops_s",
                    "avg_ms_op",
                    "fsyncfile2_avg_ms",
                    "fsyncfile3_avg_ms",
                    "deletefile1_avg_ms",
                ],
            ),
            "",
            "## Fig. 14 Approximation Data",
            "",
            md_table(
                ionice,
                [
                    "system",
                    "changes_per_min",
                    "iops",
                    "avg_latency_ms",
                    "p999_clat_ms",
                ],
            ),
            "",
            "## Not Reproduced From Current Artifacts",
            "",
            "- Fig. 7 and Fig. 8: require WS-M/time-series workload traces not present in this safe run.",
            "- Fig. 9: requires rerunning the FIO scenario with controlled CPU-core counts.",
            "- Fig. 10: requires multiple raw NVMe namespaces, disallowed in the single-NVMe environment.",
            "- Fig. 11: requires Daredevil ablation runs with subsystem toggles.",
            "- Fig. 13: requires BCC tracepoint-overhead instrumentation.",
        ]
    )
    (summary_dir / "artifact_figure_summary.md").write_text("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-dir", type=Path, default=Path("eval/results-artifact"))
    parser.add_argument("--summary-dir", type=Path, default=Path("eval/summary"))
    parser.add_argument("--plots-dir", type=Path, default=Path("eval/plots"))
    args = parser.parse_args()

    args.summary_dir.mkdir(parents=True, exist_ok=True)
    args.plots_dir.mkdir(parents=True, exist_ok=True)

    sns.set_theme(style="whitegrid", context="paper", font_scale=1.1)
    datasets = {
        "fio_incremental": parse_fio_incremental(args.results_dir),
        "ionice": parse_ionice(args.results_dir),
        "filebench": parse_filebench(args.results_dir),
        "ycsb": parse_ycsb(args.results_dir),
    }
    write_csvs(datasets, args.summary_dir)
    generated = generate_plots(datasets, args.plots_dir)
    write_report(datasets, generated, args.summary_dir, args.plots_dir)

    print("Generated CSVs:")
    for name in datasets:
        path = args.summary_dir / f"{name}.csv"
        if path.exists():
            print(f"  {path}")
    print("Generated figures:")
    for name in generated:
        print(f"  {args.plots_dir / (name + '.png')}")
        print(f"  {args.plots_dir / (name + '.svg')}")
    print(f"Generated report: {args.summary_dir / 'artifact_figure_summary.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
