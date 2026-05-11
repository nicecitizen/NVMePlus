#!/usr/bin/env bash
set -euo pipefail

source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/common.sh"
parse_common_args "$@"
prepare_dirs
require_cmd fio
require_sudo

OUT_DIR="$ARTIFACT_OUT_DIR/$ARTIFACT_SYS/fio-filebacked-incr-tenants"
FIO_DIR="$ARTIFACT_MNT_DIR/fio-tenants"
mkdir -p "$OUT_DIR" "$FIO_DIR"

run_fio() {
	printf "%s\n" "$ARTIFACT_SUDO_PASSWORD" | sudo -S fio "$@"
}
L_PRIOC=1
T_PRIOC=0

LAT_FILE="$FIO_DIR/latency-tenant.dat"
echo "Preparing file-backed latency tenant data at $LAT_FILE"
run_fio --name=prepare-latency-file \
	--filename="$LAT_FILE" \
	--rw=write \
	--bs=256k \
	--iodepth=16 \
	--ioengine=libaio \
	--direct=1 \
	--size="$ARTIFACT_FILE_SIZE" \
	--output="$OUT_DIR/prepare-latency-file.fio"

for nr_tenants in 4 8 12 16; do
	RUN_DIR="$OUT_DIR/t-tenants-$nr_tenants"
	mkdir -p "$RUN_DIR"
	echo "Running file-backed FIO: sys=$ARTIFACT_SYS t_tenants=$nr_tenants cpus=$ARTIFACT_CPUS runtime=$ARTIFACT_RUNTIME"

	start_monitors "$RUN_DIR/monitor"

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
		--name=l-tenants \
		--filename="$LAT_FILE" \
		--rw=randread \
		--bs=4k \
		--iodepth=1 \
		--prioclass="$L_PRIOC" \
		--numjobs=4 \
		--name=t-tenants \
		--filename="$FIO_DIR/t-tenant-$nr_tenants.\$jobnum.dat" \
		--rw=randwrite \
		--bs=128k \
		--iodepth=32 \
		--prioclass="$T_PRIOC" \
		--numjobs="$nr_tenants" \
		--output="$RUN_DIR/fio.out"

	stop_monitors
done
