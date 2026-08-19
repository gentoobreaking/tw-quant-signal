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

# PID 文件管理，防止重複執行
PID_FILE="$LOG_DIR/pipeline.pid"
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE" 2>/dev/null)
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        echo "[$(date)] 管線已在運行 (PID: $OLD_PID)，跳過本次執行" | tee -a "$LOG_FILE"
        exit 0
    fi
fi
echo $$ > "$PID_FILE"

# 清理函數
cleanup() {
    rm -f "$PID_FILE"
}
trap cleanup EXIT INT TERM

# 狀態記錄函數
log_status() {
    local status="$1"
    local message="$2"
    echo "[$(date)] $status: $message" | tee -a "$LOG_FILE"
}

# 錯誤處理
handle_error() {
    local exit_code=$?
    log_status "ERROR" "管線執行失敗 (exit code: $exit_code)"
    exit $exit_code
}
trap 'handle_error' ERR

# 開始執行
log_status "START" "開始執行每日管線"

LOG_DIR="data/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/pipeline_$(date +\%Y\%m\%d).log"

# Activate venv if exists
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

export TW_QUANT_DB="${TW_QUANT_DB:-$PWD/data/signal.db}"

# 執行管線並記錄時間
START_TIME=$(date +%s)
log_status "INFO" "開始執行 pipeline.py"

if python -m tw_quant_signal.pipeline >> "$LOG_FILE" 2>&1; then
    END_TIME=$(date +%s)
    DURATION=$((END_TIME - START_TIME))
    log_status "SUCCESS" "管線執行成功，耗時 ${DURATION} 秒"
else
    END_TIME=$(date +%s)
    DURATION=$((END_TIME - START_TIME))
    log_status "ERROR" "管線執行失敗，耗時 ${DURATION} 秒"
    exit 1
fi

# 執行時間超過預期告警 (預設 30 分鐘 = 1800 秒)
MAX_DURATION=${MAX_PIPELINE_DURATION:-1800}
if [ $DURATION -gt $MAX_DURATION ]; then
    log_status "WARN" "管線執行時間過長 (${DURATION} 秒 > ${MAX_DURATION} 秒)"
fi

# Rotate logs older than 30 days
find "$LOG_DIR" -name "pipeline_*.log" -mtime +30 -delete

log_status "END" "管線執行結束"
