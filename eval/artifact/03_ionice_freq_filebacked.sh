#!/usr/bin/env bash
set -euo pipefail

source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/common.sh"
parse_common_args "$@"
prepare_dirs
require_cmd fio
require_cmd ionice
require_sudo

OUT_DIR="$ARTIFACT_OUT_DIR/$ARTIFACT_SYS/ionice-freq"
FIO_DIR="$ARTIFACT_MNT_DIR/fio-tenants"
TARGET_FILE="$FIO_DIR/ionice-target.dat"
mkdir -p "$OUT_DIR" "$FIO_DIR"

run_fio() {
	printf "%s\n" "$ARTIFACT_SUDO_PASSWORD" | sudo -S fio "$@"
}

run_sudo_cmd() {
	printf "%s\n" "$ARTIFACT_SUDO_PASSWORD" | sudo -S "$@"
}

echo "Preparing file-backed ionice target at $TARGET_FILE"
run_fio --name=prepare-ionice-file \
	--filename="$TARGET_FILE" \
	--rw=write \
	--bs=256k \
	--iodepth=16 \
	--ioengine=libaio \
	--direct=1 \
	--size="$ARTIFACT_FILE_SIZE" \
	--output="$OUT_DIR/prepare-ionice-file.fio"

for freq in 60 120 240 600 1200; do
	echo "Running ionice frequency test: sys=$ARTIFACT_SYS freq_per_min=$freq runtime=$ARTIFACT_RUNTIME"
	run_fio --name=global \
		--gtod_reduce=0 \
		--group_reporting=0 \
		--time_based=1 \
		--direct=1 \
		--ioengine=libaio \
		--filename="$TARGET_FILE" \
		--size="$ARTIFACT_FILE_SIZE" \
		--runtime="$ARTIFACT_RUNTIME" \
		--name=ionice-change-single \
		--rw=randread \
		--bs=4k \
		--iodepth=1 \
		--numjobs=1 \
		--cpus_allowed="$ARTIFACT_CPUS" \
		--output="$OUT_DIR/fio-ionice-freq-$freq.fio" &

	FIO_PARENT_PID=$!
	sleep 2
	TARGET_PID=$(pgrep -P "$FIO_PARENT_PID" | head -n 1 || true)
	if [[ -z "$TARGET_PID" ]]; then
		TARGET_PID=$FIO_PARENT_PID
	fi

	SLEEP_SECS=$(awk -v f="$freq" 'BEGIN { printf "%.6f", 60 / f }')
	ITERS=$((freq * ARTIFACT_RUNTIME / 60))
	if ((ITERS < 1)); then
		ITERS=1
	fi

	for ((i = 0; i < ITERS; i++)); do
		if ps -p "$TARGET_PID" >/dev/null 2>&1; then
			run_sudo_cmd ionice -c $((i % 2)) -p "$TARGET_PID" || true
			sleep "$SLEEP_SECS"
		else
			break
		fi
	done

	wait "$FIO_PARENT_PID" || true
done
