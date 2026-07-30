"""每日盤後資料管線 — 主入口"""
import sys
from datetime import date, datetime

from tw_quant_signal.db import SignalDB
from tw_quant_signal.ingestion import IngestionEngine
from tw_quant_signal.alerter import send_health_alert


def main():
    db = SignalDB()
    db.init_db()

    engine = IngestionEngine(db)
    run_date = date.today().isoformat()

    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] 開始執行管線 — {run_date}")

    status = engine.run_daily(run_date)

    index_data = None
    for k, v in status.items():
        icon = "✓" if v == "ok" else ("–" if v == "skip" else "✗")
        print(f"  [{icon}] {k}: {v}")

    all_ok = all(v == "ok" for v in status.values())
    db.log_pipeline(run_date, "pipeline", "ok" if all_ok else "partial",
                    f"index={status['index']},stocks={status['stocks']},"
                    f"inst={status['institutional']},ind={status['indicators']}")

    # Send health alert
    send_health_alert(status, index_data)

    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] 管線完成")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
