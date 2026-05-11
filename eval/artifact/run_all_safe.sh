#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")

"$SCRIPT_DIR/00_check_env.sh" "$@"
"$SCRIPT_DIR/01_fio_filebacked_incr_tenants.sh" "$@"
"$SCRIPT_DIR/02_filebench_mailserver_filebacked.sh" "$@"
"$SCRIPT_DIR/03_ionice_freq_filebacked.sh" "$@"

if [[ "${ARTIFACT_RUN_YCSB:-0}" == "1" ]]; then
	"$SCRIPT_DIR/04_rocksdb_ycsb_filebacked.sh" "$@"
else
	echo "Skipping RocksDB/YCSB by default. Set ARTIFACT_RUN_YCSB=1 after YCSB is built."
fi

