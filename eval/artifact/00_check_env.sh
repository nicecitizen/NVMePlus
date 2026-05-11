#!/usr/bin/env bash
set -euo pipefail

source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/common.sh"
parse_common_args "$@"
prepare_dirs

require_cmd fio
require_cmd taskset
require_cmd ionice

echo "Repository: $REPO_DIR"
echo "Target label: $ARTIFACT_SYS"
echo "CPU list: $ARTIFACT_CPUS"
echo "Runtime: $ARTIFACT_RUNTIME seconds"
echo "File size: $ARTIFACT_FILE_SIZE"
echo "Output directory: $ARTIFACT_OUT_DIR/$ARTIFACT_SYS"
echo "Scratch directory: $ARTIFACT_MNT_DIR"
echo
echo "Kernel:"
uname -a
echo

if [[ "$ARTIFACT_SYS" == "daredevil" ]]; then
	if [[ -d /sys/module/blk_blex/parameters ]]; then
		echo "Daredevil blk_blex parameters:"
		ls /sys/module/blk_blex/parameters
	else
		echo "Warning: /sys/module/blk_blex/parameters is not present."
	fi

	if [[ -d /sys/module/nvme/parameters ]]; then
		echo
		echo "NVMe parameters:"
		ls /sys/module/nvme/parameters | grep -E 'daredevil|queue|poll|write' || true
	fi
fi

echo
echo "Tool versions:"
fio --version
if command -v filebench >/dev/null 2>&1; then
	filebench -h 2>&1 | head -n 1 || true
else
	echo "filebench: missing, filebench script will not run"
fi
if command -v iostat >/dev/null 2>&1; then
	iostat -V | head -n 1
else
	echo "iostat: missing, IO monitor files will be skipped"
fi
if command -v mpstat >/dev/null 2>&1; then
	mpstat -V | head -n 1
else
	echo "mpstat: missing, CPU monitor files will be skipped"
fi

