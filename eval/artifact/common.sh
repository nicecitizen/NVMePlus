#!/usr/bin/env bash
set -euo pipefail

ARTIFACT_DIR=$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")
EVAL_DIR=$(dirname "$ARTIFACT_DIR")
REPO_DIR=$(dirname "$EVAL_DIR")

ARTIFACT_SYS=${ARTIFACT_SYS:-daredevil}
ARTIFACT_CPUS=${ARTIFACT_CPUS:-0-3}
ARTIFACT_RUNTIME=${ARTIFACT_RUNTIME:-60}
ARTIFACT_FILE_SIZE=${ARTIFACT_FILE_SIZE:-1G}
ARTIFACT_OUT_DIR=${ARTIFACT_OUT_DIR:-"$EVAL_DIR/results-artifact"}
ARTIFACT_MNT_DIR=${ARTIFACT_MNT_DIR:-"$EVAL_DIR/mnt"}

usage_sys() {
	printf 'Usage: %s [--sys daredevil|blkswitch|vanilla] [--cpus CPU_LIST] [--runtime SEC]\n' "$1"
}

parse_common_args() {
	while (($#)); do
		case "$1" in
			--sys)
				ARTIFACT_SYS="$2"
				shift 2
				;;
			--cpus)
				ARTIFACT_CPUS="$2"
				shift 2
				;;
			--runtime)
				ARTIFACT_RUNTIME="$2"
				shift 2
				;;
			-h|--help)
				usage_sys "$0"
				exit 0
				;;
			*)
				echo "Unknown argument: $1" >&2
				usage_sys "$0" >&2
				exit 1
				;;
		esac
	done

	case "$ARTIFACT_SYS" in
		daredevil|blkswitch|vanilla) ;;
		*)
			echo "--sys must be one of: daredevil, blkswitch, vanilla" >&2
			exit 1
			;;
	esac
}

require_cmd() {
	if ! command -v "$1" >/dev/null 2>&1; then
		echo "Missing required command: $1" >&2
		exit 1
	fi
}

require_sudo() {
	if ! command -v sudo >/dev/null 2>&1; then
		echo "Missing required command: sudo" >&2
		exit 1
	fi

	if [[ -n "${ARTIFACT_SUDO_PASSWORD:-}" ]]; then
		if ! printf "%s\n" "$ARTIFACT_SUDO_PASSWORD" | sudo -S -p '' -v >/dev/null 2>&1; then
			echo "sudo is required for this evaluation flow and could not be initialized" >&2
			exit 1
		fi
	else
		if ! sudo -n -v >/dev/null 2>&1; then
			echo "sudo is required for this evaluation flow and is not available without a password" >&2
			exit 1
		fi
	fi
}

prepare_dirs() {
	mkdir -p \
		"$ARTIFACT_MNT_DIR/fio-tenants" \
		"$ARTIFACT_MNT_DIR/filebench-mailserver" \
		"$ARTIFACT_MNT_DIR/rocksdb" \
		"$ARTIFACT_MNT_DIR/workloads" \
		"$ARTIFACT_OUT_DIR/$ARTIFACT_SYS"
}

start_monitors() {
	local out_prefix=$1
	IOSTAT_PID=''
	MPSTAT_PID=''

	if command -v iostat >/dev/null 2>&1; then
		iostat -x -o JSON 1 "$ARTIFACT_RUNTIME" > "$out_prefix.io" &
		IOSTAT_PID=$!
	fi

	if command -v mpstat >/dev/null 2>&1; then
		mpstat -I SUM -o JSON -P ALL -u 1 "$ARTIFACT_RUNTIME" > "$out_prefix.cpu" &
		MPSTAT_PID=$!
	fi
}

stop_monitors() {
	if [[ -n "${IOSTAT_PID:-}" ]]; then
		wait "$IOSTAT_PID" 2>/dev/null || true
	fi
	if [[ -n "${MPSTAT_PID:-}" ]]; then
		wait "$MPSTAT_PID" 2>/dev/null || true
	fi
}
