# Evaluation Procedure

This flow is for the artifact evaluation environment where there is only one
NVMe disk. It does not issue raw FIO to `/dev/nvme0n1` and does not create,
delete, or format NVMe namespaces. All generated I/O uses regular files under
`eval/mnt/`.

## 1. Clean Temporary Installation Files

```bash
cd /home/ljhss03/Daredevil
rm -rf eval/linux-6.1.53.tar.gz eval/linux-vanilla eval/linux-blkswitch eval/blkswitch/.config
git status --short
```

## 2. Boot One Target Kernel

Boot one of the target kernels and label the run with the matching `--sys`
value:

- `daredevil`
- `blkswitch`
- `vanilla`

Record the running kernel:

```bash
uname -a
```

For Daredevil, the real module path is `blk_blex`, not `blex`:

```bash
ls /sys/module/blk_blex/parameters
ls /sys/module/nvme/parameters
```

## 3. Run the Safe Artifact Scripts

The runnable scripts are in `eval/artifact/`.

Use the short default run:

```bash
cd /home/ljhss03/Daredevil
eval/artifact/run_all_safe.sh --sys daredevil
```

For another kernel, reboot into that kernel and run:

```bash
cd /home/ljhss03/Daredevil
eval/artifact/run_all_safe.sh --sys blkswitch
eval/artifact/run_all_safe.sh --sys vanilla
```

The default runtime is 60 seconds per benchmark section. To run longer:

```bash
ARTIFACT_RUNTIME=600 ARTIFACT_FILE_SIZE=32G eval/artifact/run_all_safe.sh --sys daredevil
```

To use a different CPU set:

```bash
ARTIFACT_CPUS=0-7 eval/artifact/run_all_safe.sh --sys daredevil
```

## 4. Individual Script Commands

Environment check:

```bash
eval/artifact/00_check_env.sh --sys daredevil
```

File-backed FIO increasing T-tenants:

```bash
eval/artifact/01_fio_filebacked_incr_tenants.sh --sys daredevil
```

Filebench mailserver with file-backed background FIO tenants:

```bash
eval/artifact/02_filebench_mailserver_filebacked.sh --sys daredevil
```

Ionice frequency overhead with file-backed FIO:

```bash
eval/artifact/03_ionice_freq_filebacked.sh --sys daredevil
```

RocksDB/YCSB is optional because it requires the YCSB/RocksDB Java binding to
be built first:

```bash
ARTIFACT_RUN_YCSB=1 eval/artifact/run_all_safe.sh --sys daredevil
```

Or run it directly:

```bash
eval/artifact/04_rocksdb_ycsb_filebacked.sh --sys daredevil
```

## 5. Output Locations

Scratch files are created under:

```bash
eval/mnt/
```

Results are written under:

```bash
eval/results-artifact/daredevil/
eval/results-artifact/blkswitch/
eval/results-artifact/vanilla/
```

## 6. Commands to Avoid in the One-NVMe Environment

Do not run the original raw-device or namespace scripts in this environment:

```bash
eval/scripts/eval_single_ns_incr_T_tenant.sh
eval/scripts/eval_multi_ns_incr_T_tenant.sh
eval/manage_nvme_ns.sh
eval/reset_nvme_ns.sh
```

Those scripts assume a disposable NVMe target and may write directly to the only
SSD or recreate its namespaces.
