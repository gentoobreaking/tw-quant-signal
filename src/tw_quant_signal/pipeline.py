import sys
from datetime import date, datetime
from pathlib import Path

from pathlib import Path

from tw_quant_signal.db import SignalDB
from tw_quant_signal.twse_client import WATCH_STOCKS
from tw_quant_signal.ingestion import IngestionEngine
from tw_quant_signal.rules import compute_rule_signals, store_rule_signals, _aggregate_rules
from tw_quant_signal.alerter import send_alert, send_rules_report, send_health_check_report, send_risk_report, build_daily_report
from tw_quant_signal.reporter import generate_markdown_report, generate_csv_report
from tw_quant_signal.health_check import compute_health_check, compute_health_check_weekly, compute_health_check_monthly
from tw_quant_signal.market_state import detect_market_state, LABELS as STATE_LABELS
from tw_quant_signal.risk_manager import compute_risk_metrics, RISK_LEVELS
from tw_quant_signal.indicators import compute_weekly_indicators, compute_monthly_indicators
from tw_quant_signal.multi_timeframe import compute_multi_timeframe
from tw_quant_signal.structural_change import compute_all_drift, store_drift_results, generate_structural_change_report
from tw_quant_signal.env_manager import is_production_mode, get_summary, filter_rules_for_production
from tw_quant_signal.operation_log import (
    log_pipeline_run, log_signal_output,
    build_compliance_report, get_compliance_statement,
)


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

    # Market state detection (before health check so state is available)
    mstate = None
    try:
        mstate = detect_market_state(db, run_date)
        state_label = STATE_LABELS.get(mstate["state"], mstate["state"])
        print(f"  → 市場狀態: {state_label} (收盤 {mstate['close']} MA60 {mstate['ma60']} RSI {mstate['rsi14']})")
        status["market_state"] = "ok"
        db.log_pipeline(run_date, "market_state", "ok",
                        f"state={mstate['state']},close={mstate['close']},ma60={mstate['ma60']},rsi={mstate['rsi14']}")
    except Exception as e:
        print(f"  ✗ 市場狀態偵測失敗: {e}")
        status["market_state"] = "fail"

    # Health check scoring
    try:
        health_scores = compute_health_check(db, run_date)
        if health_scores:
            db.upsert_health_scores(health_scores)
            send_health_check_report(health_scores, mstate["state"] if mstate else None)
            print(f"  → {len(health_scores)} 筆四燈號健診評分")
            status["health_check"] = "ok"
        else:
            print("  ⚠ 無健診評分產出")
            status["health_check"] = "skip"
    except Exception as e:
        print(f"  ✗ 健診評分失敗: {e}")
        status["health_check"] = "fail"

    # Weekly indicators
    try:
        for sid in WATCH_STOCKS:
            prices = db.get_stock_prices(sid, limit=1500)
            if prices:
                daily_prices = [dict(p) for p in prices]
                daily_prices.sort(key=lambda p: p["trade_date"])
                weekly_ind = compute_weekly_indicators(daily_prices, sid)
                if weekly_ind:
                    db.upsert_weekly_indicators(weekly_ind)
        print(f"  → 週線指標更新 (共 {len(WATCH_STOCKS)} 檔)")
        status["weekly_indicators"] = "ok"
    except Exception as e:
        print(f"  ✗ 週線指標失敗: {e}")
        status["weekly_indicators"] = "fail"

    # Weekly health check
    try:
        weekly_health = compute_health_check_weekly(db, run_date)
        if weekly_health:
            db.upsert_weekly_health_scores(weekly_health)
            print(f"  → {len(weekly_health)} 筆週線健診評分")
            status["weekly_health"] = "ok"
        else:
            status["weekly_health"] = "skip"
    except Exception as e:
        print(f"  ✗ 週線健診失敗: {e}")
        status["weekly_health"] = "fail"

    # Monthly indicators (mid-term extension point)
    try:
        for sid in WATCH_STOCKS:
            prices = db.get_stock_prices(sid, limit=3000)
            if prices:
                daily_prices = [dict(p) for p in prices]
                daily_prices.sort(key=lambda p: p["trade_date"])
                monthly_ind = compute_monthly_indicators(daily_prices, sid)
                if monthly_ind:
                    db.upsert_monthly_indicators(monthly_ind)
        print(f"  → 月線指標更新 (共 {len(WATCH_STOCKS)} 檔)")
        status["monthly_indicators"] = "ok"
    except Exception as e:
        print(f"  ✗ 月線指標失敗: {e}")
        status["monthly_indicators"] = "fail"

    # Monthly health check
    try:
        monthly_health = compute_health_check_monthly(db, run_date)
        if monthly_health:
            db.upsert_monthly_health_scores(monthly_health)
            print(f"  → {len(monthly_health)} 筆月線健診評分")
            status["monthly_health"] = "ok"
        else:
            status["monthly_health"] = "skip"
    except Exception as e:
        print(f"  ✗ 月線健診失敗: {e}")
        status["monthly_health"] = "fail"

    # Multi-timeframe consensus (daily + weekly; monthly extension point documented)
    try:
        consensus = compute_multi_timeframe(db, run_date)
        if consensus:
            db.upsert_multi_timeframe_consensus(consensus)
            for c in consensus:
                print(f"  → {c['stock_id']} 多時間框架: {c['consensus_label']} (日線 {c['daily_light']} + 週線 {c['weekly_light']})")
            status["multi_timeframe"] = "ok"
        else:
            status["multi_timeframe"] = "skip"
    except Exception as e:
        print(f"  ✗ 多時間框架失敗: {e}")
        status["multi_timeframe"] = "fail"

    # Risk metrics
    risk_metrics = None
    try:
        risk_metrics = compute_risk_metrics(db, run_date)
        if risk_metrics:
            db.upsert_risk_metrics(risk_metrics)
            max_risk = max(r["risk_score"] for r in risk_metrics)
            max_level = next((l for t, k, l in RISK_LEVELS if max_risk >= t), "🟢 正常")
            print(f"  → {len(risk_metrics)} 筆風險指標 (最高 {max_risk} {max_level})")
            status["risk"] = "ok"
        else:
            print("  ⚠ 無風險指標產出")
            status["risk"] = "skip"
    except Exception as e:
        print(f"  ✗ 風險指標失敗: {e}")
        status["risk"] = "fail"

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
                    f"features={status['features']},health={status.get('health_check','skip')}")

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

    # Production mode: filter rules if in production
    if is_production_mode():
        allowed_ids = get_summary()["production_rule_ids"]
        if not allowed_ids:
            print("  → 實戰模式無白名單規則，跳過規則訊號產出")
            rules_result = []
        else:
            rules_result = [r for r in rules_result if r.get("stock_id") in allowed_ids or any(
                tr.get("rule_id") in allowed_ids for tr in r.get("triggered_rules", []))]
            print(f"  → 實戰模式: 過濾後 {len(rules_result)} 筆 (白名單 {len(allowed_ids)} 條規則)")

    report_data = _gather_report_data(db)
    disclaimer = get_compliance_statement()
    daily_msg = build_daily_report(status, report_data, mstate["state"] if mstate else None)
    daily_msg += f"\n\n⚖️ {disclaimer.split('.')[0]}。"
    send_alert(daily_msg)

    if risk_metrics:
        send_risk_report(risk_metrics)

    # Log to operation log
    log_pipeline_run(db, run_date, status, 0)

    # Structural change detection
    try:
        drift_result = compute_all_drift(db)
        store_drift_results(db, drift_result)
        total_alerts = sum(drift_result["alert_summary"].values())
        if total_alerts > 0:
            icon_map = {"critical": "🔴", "warning": "🟠", "watch": "🟡"}
            alert_parts = []
            for level in ("critical", "warning", "watch"):
                cnt = drift_result["alert_summary"].get(level, 0)
                if cnt > 0:
                    alert_parts.append(f"{icon_map[level]} {level}={cnt}")
            print(f"  → 結構變化偵測完成: {total_alerts} 項異常 ({', '.join(alert_parts)})")
            # 衰退通知 — 僅 critical/warning 等級
            serious = drift_result["alert_summary"].get("critical", 0) + drift_result["alert_summary"].get("warning", 0)
            if serious > 0:
                drift_report = generate_structural_change_report(db)
                if drift_report:
                    report_path = Path("data/reports")
                    report_path.mkdir(parents=True, exist_ok=True)
                    (report_path / f"drift_{run_date}.md").write_text(drift_report)
                send_alert(f"⚠️ 結構變化偵測: {serious} 項中/高異常，見 data/reports/drift_{run_date}.md")
        else:
            print(f"  → 結構變化偵測完成: 無異常")
        status["structural_drift"] = "ok"
    except Exception as e:
        print(f"  ✗ 結構變化偵測失敗: {e}")
        import traceback
        traceback.print_exc()
        status["structural_drift"] = "fail"

    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] 管線完成")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
