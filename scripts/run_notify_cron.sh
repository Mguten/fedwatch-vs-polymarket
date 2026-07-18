#!/usr/bin/env bash
# Wrapper för cron -- cron-processer ärver inte din interaktiva shells
# miljövariabler, så vi läser .env explicit här. Loggar till output/notify.log
# (roterar inte -- städa manuellt om filen växer sig stor).
set -euo pipefail

PROJECT_DIR="/home/mguten/venvs/main/Projects/FF_rates"
PYTHON_BIN="/home/mguten/venvs/main/bin/python3"
LOG_FILE="$PROJECT_DIR/output/notify.log"

cd "$PROJECT_DIR"
mkdir -p output
set -a
source .env
set +a

{
  echo "=== $(date -Iseconds) ==="
  "$PYTHON_BIN" scripts/run_notify.py
} >> "$LOG_FILE" 2>&1
