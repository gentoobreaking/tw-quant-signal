#!/bin/bash
# 每日盤後 15:00 執行（週一至週五）
# 加入 crontab：
#    crontab -e
#    0 15 * * 1-5 /Users/david/Projects/tw-quant-signal/scripts/scheduler_cron.sh

set -euo pipefail
cd "$(dirname "$0")/.."
LOG_DIR="data/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/pipeline_$(date +\%Y\%m\%d).log"

# Activate venv if exists
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

export TW_QUANT_DB="${TW_QUANT_DB:-$PWD/data/signal.db}"

python -m tw_quant_signal.pipeline >> "$LOG_FILE" 2>&1

# Rotate logs older than 30 days
find "$LOG_DIR" -name "pipeline_*.log" -mtime +30 -delete
