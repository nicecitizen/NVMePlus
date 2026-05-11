#!/usr/bin/env bash
set -euo pipefail

source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/common.sh"
parse_common_args "$@"
prepare_dirs
require_cmd fio
require_cmd filebench
require_sudo

OUT_DIR="$ARTIFACT_OUT_DIR/$ARTIFACT_SYS/filebench-mailserver"
BENCH_DIR="$ARTIFACT_MNT_DIR/filebench-mailserver"
FIO_DIR="$ARTIFACT_MNT_DIR/fio-tenants"
WML="$ARTIFACT_MNT_DIR/workloads/filebench-mailserver-artifact.f"
FILEBENCH_RUNTIME=${ARTIFACT_FILEBENCH_RUNTIME:-600}
FILEBENCH_NFILES=${ARTIFACT_FILEBENCH_NFILES:-64000}
FILEBENCH_NTHREADS=${ARTIFACT_FILEBENCH_NTHREADS:-16}
mkdir -p "$OUT_DIR" "$BENCH_DIR" "$FIO_DIR" "$(dirname "$WML")"

run_sudo_cmd() {
	printf "%s\n" "$ARTIFACT_SUDO_PASSWORD" | sudo -S "$@"
}

sed \
	-e 's#set \$dir=.*#set $dir='"$BENCH_DIR"'#g' \
	-e 's#set \$runtime=.*#set $runtime='"$FILEBENCH_RUNTIME"'#g' \
	-e 's#set \$nfiles=.*#set $nfiles='"$FILEBENCH_NFILES"'#g' \
	-e 's#set \$nthreads=.*#set $nthreads='"$FILEBENCH_NTHREADS"'#g' \
	"$EVAL_DIR/scripts/filebench-mailserver.f" > "$WML"

echo "Running Filebench mailserver with file-backed FIO tenants: sys=$ARTIFACT_SYS cpus=$ARTIFACT_CPUS runtime=$FILEBENCH_RUNTIME nfiles=$FILEBENCH_NFILES nthreads=$FILEBENCH_NTHREADS"
rm -f "$FIO_DIR"/mailserver-fio-*.dat

ARTIFACT_RUNTIME="$FILEBENCH_RUNTIME"
start_monitors "$OUT_DIR/monitor"

run_sudo_cmd timeout "$((ARTIFACT_RUNTIME + 120))" taskset --cpu-list "$ARTIFACT_CPUS" ionice -c 1 \
	filebench -f "$WML" > "$OUT_DIR/filebench.out" &
FILEBENCH_PID=$!

fio --name=global \
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
	--filename="$FIO_DIR/mailserver-fio-\$jobnum.dat" \
	--rw=write \
	--bs=256k \
	--iodepth=32 \
	--prioclass=0 \
	--numjobs=8 \
	--output="$OUT_DIR/fio-background.out" &
FIO_PID=$!

wait "$FILEBENCH_PID"
wait "$FIO_PID" || true
stop_monitors
