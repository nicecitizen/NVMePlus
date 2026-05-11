#!/usr/bin/env bash
set -euo pipefail

source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/common.sh"
parse_common_args "$@"
prepare_dirs
require_cmd fio
require_cmd java
require_sudo

YCSB_DIR="$EVAL_DIR/lib/YCSB"
OUT_DIR="$ARTIFACT_OUT_DIR/$ARTIFACT_SYS/rocksdb-ycsb"
FIO_DIR="$ARTIFACT_MNT_DIR/fio-tenants"
DB_DIR="$ARTIFACT_MNT_DIR/rocksdb"
mkdir -p "$OUT_DIR" "$DB_DIR" "$FIO_DIR"

run_ycsb() {
	printf "%s\n" "$ARTIFACT_SUDO_PASSWORD" | sudo -S "$@"
}

run_fio() {
	printf "%s\n" "$ARTIFACT_SUDO_PASSWORD" | sudo -S fio "$@"
}

if [[ ! -x "$YCSB_DIR/bin/ycsb.sh" ]]; then
	echo "Missing executable YCSB launcher: $YCSB_DIR/bin/ycsb.sh" >&2
	echo "Build eval/lib/YCSB first, then rerun this script." >&2
	exit 1
fi

if [[ ! -f "$YCSB_DIR/core/target/core-0.18.0-SNAPSHOT.jar" ]] ||
	[[ ! -f "$YCSB_DIR/core/target/dependency/htrace-core4-4.1.0-incubating.jar" ]] ||
	[[ ! -f "$YCSB_DIR/rocksdb/target/rocksdb-binding-0.18.0-SNAPSHOT.jar" ]] ||
	[[ ! -f "$YCSB_DIR/rocksdb/target/dependency/rocksdbjni-6.2.2.jar" ]]; then
	require_cmd mvn
	echo "Building/staging YCSB RocksDB runtime dependencies"
	mkdir -p "$EVAL_DIR/.m2/repository"
	(
		cd "$YCSB_DIR"
		mvn -pl site.ycsb:rocksdb-binding -am -DskipTests \
			-Dmaven.repo.local="$EVAL_DIR/.m2/repository" package
		mvn -pl site.ycsb:core -DskipTests \
			-Dmaven.repo.local="$EVAL_DIR/.m2/repository" dependency:copy-dependencies
	)
fi

WORKLOAD="$YCSB_DIR/workloads/workloada"
if [[ ! -f "$WORKLOAD" ]]; then
	echo "Missing YCSB workload: $WORKLOAD" >&2
	exit 1
fi

rm -rf "$DB_DIR"/*
rm -f "$FIO_DIR"/ycsb-fio-*.dat

echo "Loading YCSB RocksDB workload into $DB_DIR"
taskset --cpu-list "$ARTIFACT_CPUS" "$YCSB_DIR/bin/ycsb.sh" load rocksdb \
	-P "$WORKLOAD" \
	-p "rocksdb.dir=$DB_DIR" \
	-p max_background_jobs=4 \
	-s > "$OUT_DIR/ycsb.load" 2>&1

echo "Running YCSB RocksDB with file-backed FIO tenants: sys=$ARTIFACT_SYS cpus=$ARTIFACT_CPUS"
start_monitors "$OUT_DIR/monitor"

run_ycsb taskset --cpu-list "$ARTIFACT_CPUS" ionice -c 1 "$YCSB_DIR/bin/ycsb.sh" run rocksdb \
	-P "$WORKLOAD" \
	-p "rocksdb.dir=$DB_DIR" \
	-p max_background_jobs=4 \
	-s > "$OUT_DIR/ycsb.run" 2>&1 &
YCSB_PID=$!

run_fio --name=global \
	--gtod_reduce=0 \
	--group_reporting=1 \
	--time_based=1 \
	--direct=1 \
	--ioengine=libaio \
	--cpus_allowed="$ARTIFACT_CPUS" \
	--cpus_allowed_policy=split \
	--size="$ARTIFACT_FILE_SIZE" \
	--runtime="$ARTIFACT_RUNTIME" \
	--name=t-tenants \
	--filename="$FIO_DIR/ycsb-fio-\$jobnum.dat" \
	--rw=write \
	--bs=512k \
	--iodepth=16 \
	--prioclass=0 \
	--numjobs=8 \
	--output="$OUT_DIR/fio-background.out" &
FIO_PID=$!

wait "$YCSB_PID"
kill "$FIO_PID" 2>/dev/null || true
wait "$FIO_PID" 2>/dev/null || true
stop_monitors

if [[ -f "$DB_DIR/LOG" ]]; then
	cp "$DB_DIR/LOG" "$OUT_DIR/rocksdb.LOG"
fi
