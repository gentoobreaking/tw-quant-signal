import sys
from datetime import date, datetime

from tw_quant_signal.db import SignalDB
from tw_quant_signal.twse_client import WATCH_STOCKS
from tw_quant_signal.ingestion import IngestionEngine
from tw_quant_signal.rules import compute_rule_signals, store_rule_signals, _aggregate_rules
from tw_quant_signal.alerter import send_alert, send_rules_report, build_daily_report
from tw_quant_signal.reporter import generate_markdown_report, generate_csv_report


def _gather_report_data(db):
    data = {}
    with db.connect() as conn:
        idx = conn.execute(
            "SELECT trade_date, close, change_pct FROM market_index ORDER BY trade_date DESC LIMIT 1"
        ).fetchone()
        if idx:
            data["index"] = {"date": idx[0], "close": idx[1], "change_pct": idx[2]}

        stocks = []
        for sid in ["2330", "0050", "2308"]:
            r = conn.execute(
                "SELECT trade_date, close, adj_close FROM daily_prices WHERE stock_id=? ORDER BY trade_date DESC LIMIT 1",
                [sid],
            ).fetchone()
            if r:
                stocks.append({"id": sid, "date": r[0], "close": r[1], "adj_close": r[2]})
                inst = conn.execute(
                    "SELECT foreign_investors_net, sity_investors_net, dealer_net FROM institutional_flows WHERE stock_id=? ORDER BY trade_date DESC LIMIT 1",
                    [sid],
                ).fetchone()
                if inst:
                    stocks[-1]["foreign"] = inst[0]
                    stocks[-1]["sity"] = inst[1]
                    stocks[-1]["dealer"] = inst[2]
                ind = conn.execute(
                    "SELECT ma5, ma20, ma60, rsi14, bb_upper, bb_middle, bb_lower FROM tech_indicators WHERE stock_id=? ORDER BY trade_date DESC LIMIT 1",
                    [sid],
                ).fetchone()
                if ind:
                    stocks[-1]["ma5"] = ind[0]
                    stocks[-1]["ma20"] = ind[1]
                    stocks[-1]["ma60"] = ind[2]
                    stocks[-1]["rsi14"] = ind[3]
                    stocks[-1]["bb_upper"] = ind[4]
                    stocks[-1]["bb_middle"] = ind[5]
                    stocks[-1]["bb_lower"] = ind[6]
        data["stocks"] = stocks
    return data


def main():
    db = SignalDB()
    db.init_db()

    engine = IngestionEngine(db)
    run_date = date.today().isoformat()

    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] 開始執行管線 — {run_date}")

    status = engine.run_daily(run_date)

    for k, v in status.items():
        icon = "✓" if v == "ok" else ("–" if v == "skip" else "✗")
        print(f"  [{icon}] {k}: {v}")

    all_ok = all(v == "ok" for v in status.values())

    # Anomaly detection
    anomalies = []
    for k, v in status.items():
        if v == "fail":
            anomalies.append(f"{k} 失敗")
    if status.get("stocks") == "ok":
        with db.connect() as conn:
            cnt = conn.execute("SELECT COUNT(*) FROM daily_prices WHERE trade_date=?", [run_date]).fetchone()[0]
        if cnt < len(WATCH_STOCKS) * 0.5:
            anomalies.append(f"股價筆數異常 ({cnt})")
    if status.get("features") == "ok":
        with db.connect() as conn:
            feat_cnt = conn.execute("SELECT COUNT(*) FROM features WHERE trade_date=?", [run_date]).fetchone()[0]
            sig_cnt = conn.execute("SELECT COUNT(*) FROM rule_signals WHERE trade_date=?", [run_date]).fetchone()[0]
        if feat_cnt == 0:
            anomalies.append("無特徵資料")
        if sig_cnt == 0:
            anomalies.append("無訊號產出")

    db.log_pipeline(run_date, "pipeline", "ok" if all_ok else "fail",
                    f"index={status['index']},stocks={status['stocks']},"
                    f"inst={status['institutional']},ind={status['indicators']},"
                    f"features={status['features']}")

    rules_result = compute_rule_signals(db, run_date)
    triggered_total = sum(r["triggered_count"] for r in rules_result)
    if rules_result:
        store_rule_signals(db, rules_result)
        print(f"  → {len(rules_result)} 筆規則訊號 ({triggered_total} 條觸發)")
        send_rules_report(rules_result)
    else:
        print("  ⚠ 無規則訊號產出")

    # Generate report files
    md_path = generate_markdown_report(db, run_date)
    csv_path = generate_csv_report(db, run_date)
    print(f"  → 報告: {md_path}")
    print(f"  → CSV: {csv_path}")

    # Anomaly alert
    if anomalies:
        msg = f"⚠️ *管線異常 — {run_date}*\n" + "\n".join(f"- {a}" for a in anomalies)
        send_alert(msg)

    report_data = _gather_report_data(db)
    send_alert(build_daily_report(status, report_data))

    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] 管線完成")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
