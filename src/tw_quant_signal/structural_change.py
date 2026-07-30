"""結構變化偵測 — 規則衰退監控、特徵漂移偵測

功能：
1. 規則觸發頻率偏移 — 比較近期 vs 歷史觸發率
2. 規則滾動勝率衰退 — 以次日漲跌驗證訊號方向
3. 特徵分布偏移 — 比較近期 vs 參考期的數值特徵均值
4. 健康評分系統性偏移 — 整體評分分布的動向

使用方式：
    from tw_quant_signal.structural_change import compute_all_drift, generate_structural_change_report

    result = compute_all_drift(db)
    report = generate_structural_change_report(db)

輸出至 DB table structural_drift，支援 API 查詢與每日 Markdown 報告。
"""

import json
import statistics
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import yaml

from tw_quant_signal.db import SignalDB

# ─── 閾值設定 ──────────────────────────────────────────────────────────────

TRIGGER_DRIFT_THRESHOLD = 0.50  # 50% 偏離 → 偏移
WIN_RATE_DROP_THRESHOLD = 0.30  # 勝率下降 30% → 衰退
FEATURE_SHIFT_THRESHOLD = 0.30  # 均值變化 30% → 漂移

WATCH_THRESHOLD = 0.30
WARNING_THRESHOLD = 0.50
CRITICAL_THRESHOLD = 0.70

WINDOW_DAYS = 20       # 近期窗口（約一個月交易天數）
LOOKBACK_DAYS = 252    # 參考窗口（約一年交易天數）

# 納入監控的數值特徵（來自 features 表的 data JSON）
NUMERIC_FEATURES = [
    "close", "ma5", "ma20", "ma60", "rsi14", "volume_ratio", "ma_position_pct",
    "beta_5d", "pe_ratio", "pb_ratio", "dividend_yield",
]

FEATURE_LABELS = {
    "close": "收盤價", "ma5": "5日均線", "ma20": "20日均線", "ma60": "60日均線",
    "rsi14": "RSI(14)", "volume_ratio": "成交量比率",
    "ma_position_pct": "均線位置 %", "beta_5d": "Beta(5日)",
    "pe_ratio": "本益比", "pb_ratio": "股價淨值比", "dividend_yield": "殖利率",
}


# ─── 工具函數 ───────────────────────────────────────────────────────────────

def _drift_status(score: float) -> str:
    if score >= CRITICAL_THRESHOLD:
        return "critical"
    if score >= WARNING_THRESHOLD:
        return "warning"
    if score >= WATCH_THRESHOLD:
        return "watch"
    return "normal"


def _load_all_rules() -> list[dict]:
    """從 YAML 設定檔載入所有規則定義。"""
    config_dir = Path(__file__).resolve().parents[2] / "configs"
    rules = []
    for fname in ["rules_bullish.yaml", "rules_bearish.yaml", "rules_neutral.yaml"]:
        fpath = config_dir / fname
        if fpath.exists():
            with open(fpath) as f:
                data = yaml.safe_load(f)
                for r in (data or {}).get("rules", []):
                    r["_source"] = fname
                    rules.append(r)
    return rules


def _rule_id(r: dict) -> str:
    return r.get("id") or f"{r.get('_source', '?')}/{r.get('name', '?')}"


def _load_rules_by_id() -> dict:
    return {_rule_id(r): r for r in _load_all_rules()}


# ─── 1. 規則觸發頻率偏移 ──────────────────────────────────────────────────

def compute_trigger_drift(
    db: SignalDB,
    lookback_days: int = LOOKBACK_DAYS,
    window_days: int = WINDOW_DAYS,
) -> list[dict]:
    """比較近期規則觸發頻率 vs 歷史基準線。

    對每條規則計算：
    - 歷史觸發率：觸發天數 / 總交易天數
    - 近期觸發率：近 window_days 觸發天數 / 窗口天數
    - 偏移分數：abs(近期率 - 歷史率) / max(歷史率, 0.01)
    """
    buffer = int(lookback_days * 1.4)
    lookback_date = (date.today() - timedelta(days=buffer)).isoformat()
    window_date = (date.today() - timedelta(days=int(window_days * 1.4))).isoformat()

    with db.connect() as conn:
        all_dates = conn.execute(
            "SELECT DISTINCT trade_date FROM rule_signals WHERE trade_date >= ? ORDER BY trade_date",
            [lookback_date],
        ).fetchall()
    all_dates = [r[0] for r in all_dates]

    if len(all_dates) < 10:
        return []

    with db.connect() as conn:
        rows = conn.execute(
            "SELECT trade_date, triggered_rules FROM rule_signals WHERE trade_date >= ?",
            [lookback_date],
        ).fetchall()

    total_dates = len(all_dates)
    window_dates = {d for d in all_dates if d >= window_date}
    window_count = len(window_dates)

    hist_trigger = defaultdict(int)   # rule_id → trigger count (all time)
    recent_trigger = defaultdict(int)  # rule_id → trigger count (recent)

    for r in rows:
        td = r["trade_date"]
        try:
            triggered = json.loads(r["triggered_rules"]) if isinstance(r["triggered_rules"], str) else r["triggered_rules"] or []
        except (json.JSONDecodeError, TypeError):
            continue
        is_recent = td in window_dates
        for tr in triggered:
            rid = tr.get("rule_id") or tr.get("name", "unknown")
            hist_trigger[rid] += 1
            if is_recent:
                recent_trigger[rid] += 1

    rules_def = _load_rules_by_id()
    results = []
    for rid in hist_trigger:
        hist_rate = hist_trigger[rid] / total_dates
        recent_rate = recent_trigger[rid] / window_count if window_count > 0 else 0

        base = max(hist_rate, 0.01)
        deviation = abs(recent_rate - hist_rate) / base
        drift_score = min(deviation, 1.0)

        results.append({
            "rule_id": rid,
            "rule_name": rules_def.get(rid, {}).get("name", rid),
            "rule_type": rules_def.get(rid, {}).get("type", ""),
            "hist_trigger_count": hist_trigger[rid],
            "hist_rate": round(hist_rate, 4),
            "recent_trigger_count": recent_trigger[rid],
            "recent_rate": round(recent_rate, 4),
            "drift_score": round(drift_score, 4),
            "drift_status": _drift_status(drift_score),
            "direction": "increase" if recent_rate > hist_rate else "decrease",
        })

    return sorted(results, key=lambda x: x["drift_score"], reverse=True)


# ─── 2. 規則滾動勝率衰退 ──────────────────────────────────────────────────

def compute_win_rate_drift(
    db: SignalDB,
    lookback_days: int = LOOKBACK_DAYS,
    window_days: int = WINDOW_DAYS,
) -> list[dict]:
    """計算每條規則的滾動勝率衰退。

    多頭規則觸發 → 預期隔天上漲
    空頭規則觸發 → 預期隔天下跌
    比較近期勝率 vs 歷史勝率。
    """
    buffer = int(lookback_days * 1.4)
    lookback_date = (date.today() - timedelta(days=buffer)).isoformat()
    window_date = (date.today() - timedelta(days=int(window_days * 1.4))).isoformat()

    with db.connect() as conn:
        signals = conn.execute(
            "SELECT trade_date, stock_id, triggered_rules, signal FROM rule_signals WHERE trade_date >= ?",
            [lookback_date],
        ).fetchall()

        prices = conn.execute(
            "SELECT stock_id, trade_date, close FROM daily_prices WHERE trade_date >= ? ORDER BY trade_date",
            [lookback_date],
        ).fetchall()

    # 建立價格查詢表與次日報酬
    price_map = defaultdict(list)
    for p in prices:
        price_map[p["stock_id"]].append((p["trade_date"], p["close"]))

    next_day_ret = {}  # (stock_id, trade_date) → return pct
    for sid, plist in price_map.items():
        plist.sort(key=lambda x: x[0])
        for i in range(len(plist) - 1):
            if plist[i][1] and plist[i + 1][1]:
                next_day_ret[(sid, plist[i][0])] = (plist[i + 1][1] - plist[i][1]) / plist[i][1]

    # 逐條規則統計
    total_win = defaultdict(int)
    total_cnt = defaultdict(int)
    recent_win = defaultdict(int)
    recent_cnt = defaultdict(int)

    for sig in signals:
        td = sig["trade_date"]
        sid = sig["stock_id"]
        is_recent = td >= window_date

        ret = next_day_ret.get((sid, td))
        if ret is None:
            continue

        try:
            triggered = json.loads(sig["triggered_rules"]) if isinstance(sig["triggered_rules"], str) else sig["triggered_rules"] or []
        except (json.JSONDecodeError, TypeError):
            continue

        for tr in triggered:
            rid = tr.get("rule_id") or tr.get("name", "unknown")
            rtype = tr.get("type", sig.get("signal", "neutral"))
            if rtype not in ("bullish", "bearish"):
                continue

            correct = (rtype == "bullish" and ret > 0) or (rtype == "bearish" and ret < 0)
            total_cnt[rid] += 1
            if correct:
                total_win[rid] += 1
            if is_recent:
                recent_cnt[rid] += 1
                if correct:
                    recent_win[rid] += 1

    rules_def = _load_rules_by_id()
    results = []
    for rid in total_cnt:
        hist_wr = total_win[rid] / total_cnt[rid]
        recent_wr = recent_win[rid] / recent_cnt[rid] if recent_cnt[rid] > 0 else None

        drift_score = 0.0
        if recent_wr is not None and recent_cnt[rid] >= 3 and recent_wr < hist_wr:
            base = max(hist_wr, 0.01)
            drop = (hist_wr - recent_wr) / base
            drift_score = min(drop, 1.0)

        results.append({
            "rule_id": rid,
            "rule_name": rules_def.get(rid, {}).get("name", rid),
            "rule_type": rules_def.get(rid, {}).get("type", ""),
            "total_trades": total_cnt[rid],
            "historical_win_rate": round(hist_wr, 4),
            "recent_trades": recent_cnt[rid],
            "recent_win_rate": round(recent_wr, 4) if recent_wr is not None else None,
            "drift_score": round(drift_score, 4),
            "drift_status": _drift_status(drift_score),
        })

    return sorted(results, key=lambda x: x["drift_score"], reverse=True)


# ─── 3. 特徵分布偏移 ──────────────────────────────────────────────────────

def compute_feature_drift(
    db: SignalDB,
    lookback_days: int = LOOKBACK_DAYS,
    window_days: int = WINDOW_DAYS,
) -> list[dict]:
    """比對近期 vs 參考期的特徵均值，偵測分布位移。

    從 features 表讀取所有股票的特徵 JSON，分為參考期與近期兩組。
    計算均值變化比率作為漂移分數。
    """
    lookback_date = (date.today() - timedelta(days=lookback_days)).isoformat()
    window_date = (date.today() - timedelta(days=window_days)).isoformat()

    with db.connect() as conn:
        rows = conn.execute(
            "SELECT trade_date, data FROM features WHERE trade_date >= ?",
            [lookback_date],
        ).fetchall()

    ref_vals = defaultdict(list)
    recent_vals = defaultdict(list)

    for r in rows:
        try:
            data = json.loads(r["data"]) if isinstance(r["data"], str) else r["data"]
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(data, dict):
            continue

        target = recent_vals if r["trade_date"] >= window_date else ref_vals
        for feat in NUMERIC_FEATURES:
            val = data.get(feat)
            if val is not None and isinstance(val, (int, float)):
                target[feat].append(val)

    results = []
    for feat in NUMERIC_FEATURES:
        rv = ref_vals.get(feat, [])
        nv = recent_vals.get(feat, [])
        if len(rv) < 10 or len(nv) < 5:
            continue

        ref_mu = sum(rv) / len(rv)
        recent_mu = sum(nv) / len(nv)

        if abs(ref_mu) > 0.001:
            change_ratio = abs(recent_mu - ref_mu) / abs(ref_mu)
        else:
            change_ratio = abs(recent_mu - ref_mu) * 10
        drift_score = min(change_ratio, 1.0)

        ref_sd = statistics.stdev(rv) if len(rv) > 1 else 0
        recent_sd = statistics.stdev(nv) if len(nv) > 1 else 0

        results.append({
            "feature_name": feat,
            "feature_label": FEATURE_LABELS.get(feat, feat),
            "ref_sample_size": len(rv),
            "recent_sample_size": len(nv),
            "reference_mean": round(ref_mu, 4),
            "recent_mean": round(recent_mu, 4),
            "reference_std": round(ref_sd, 4),
            "recent_std": round(recent_sd, 4),
            "mean_change_pct": round((recent_mu - ref_mu) / abs(ref_mu) * 100 if abs(ref_mu) > 0.001 else 0, 2),
            "drift_score": round(drift_score, 4),
            "drift_status": _drift_status(drift_score),
        })

    return sorted(results, key=lambda x: x["drift_score"], reverse=True)


# ─── 4. 健診評分系統性偏移 ──────────────────────────────────────────────

def compute_health_score_drift(
    db: SignalDB,
    lookback_days: int = LOOKBACK_DAYS,
    window_days: int = WINDOW_DAYS,
) -> list[dict]:
    """偵測整體健診評分是否出現系統性偏移。

    若全市場評分均值顯著下降或上升，可能代表指標設定需要調整。
    """
    lookback_date = (date.today() - timedelta(days=lookback_days)).isoformat()
    window_date = (date.today() - timedelta(days=window_days)).isoformat()

    with db.connect() as conn:
        rows = conn.execute(
            "SELECT trade_date, total_score FROM health_scores WHERE trade_date >= ?",
            [lookback_date],
        ).fetchall()

    ref_s, recent_s = [], []
    for r in rows:
        if r["total_score"] is None:
            continue
        (recent_s if r["trade_date"] >= window_date else ref_s).append(r["total_score"])

    if len(ref_s) < 10:
        return []

    ref_mu = sum(ref_s) / len(ref_s)
    recent_mu = sum(recent_s) / len(recent_s) if recent_s else ref_mu
    drift_score = min(abs(recent_mu - ref_mu) / 50, 1.0)

    ref_sd = statistics.stdev(ref_s) if len(ref_s) > 1 else 0

    return [{
        "drift_type": "health_score",
        "ref_sample_size": len(ref_s),
        "recent_sample_size": len(recent_s),
        "reference_mean": round(ref_mu, 2),
        "recent_mean": round(recent_mu, 2),
        "reference_std": round(ref_sd, 2) if len(ref_s) > 1 else None,
        "drift_score": round(drift_score, 4),
        "drift_status": _drift_status(drift_score),
        "direction": "down" if recent_mu < ref_mu else "up",
    }]


# ─── 5. 聚合 ──────────────────────────────────────────────────────────────

def compute_all_drift(db: SignalDB) -> dict:
    """執行所有漂移偵測分析，返回聚合結果。"""
    trigger = compute_trigger_drift(db)
    winrate = compute_win_rate_drift(db)
    features = compute_feature_drift(db)
    health = compute_health_score_drift(db)

    summary = defaultdict(int)
    for items in [trigger, winrate, features, health]:
        for item in items:
            s = item.get("drift_status", "normal")
            if s in ("critical", "warning", "watch"):
                summary[s] += 1

    return {
        "trade_date": date.today().isoformat(),
        "trigger_drift": trigger,
        "win_rate_drift": winrate,
        "feature_drift": features,
        "health_score_drift": health,
        "alert_summary": dict(summary),
    }


# ─── 6. 報表產生 ──────────────────────────────────────────────────────────

def generate_structural_change_report(db: SignalDB) -> Optional[str]:
    """產生結構變化偵測的 Markdown 報告。"""
    result = compute_all_drift(db)
    today = date.today().isoformat()

    lines = [f"# 結構變化偵測報告 — {today}", ""]
    summary = result["alert_summary"]
    total_alerts = sum(summary.values())
    lines.append(f"**偵測摘要**: {total_alerts} 項異常\n")
    for level in ("critical", "warning", "watch"):
        if level in summary:
            icon = {"critical": "🔴", "warning": "🟠", "watch": "🟡"}[level]
            lines.append(f"- {icon} **{level.upper()}**: {summary[level]}")
    lines.append("")

    # 觸發頻率偏移
    alarm_t = [t for t in result["trigger_drift"] if t["drift_status"] != "normal"]
    lines.append("## 📊 規則觸發頻率偏移\n")
    if alarm_t:
        lines.append("| 規則 | 類型 | 歷史率 | 近20日率 | 偏移 | 狀態 |")
        lines.append("|------|------|--------|---------|------|------|")
        for t in alarm_t[:10]:
            ic = {"critical": "🔴", "warning": "🟠", "watch": "🟡"}.get(t["drift_status"], "⚪")
            lines.append(f"| {t['rule_name']}(`{t['rule_id']}`) | {t['rule_type']} | {t['hist_rate']*100:.1f}% | {t['recent_rate']*100:.1f}% | {t['drift_score']:.2f} | {ic} {t['drift_status']} |")
    else:
        lines.append("✅ 無明顯偏移\n")

    # 勝率衰退
    alarm_w = [w for w in result["win_rate_drift"] if w["drift_status"] != "normal"]
    lines.append("\n## 🎯 規則滾動勝率衰退\n")
    if alarm_w:
        lines.append("| 規則 | 類型 | 歷史勝率 | 近20日勝率 | 偏移 | 狀態 |")
        lines.append("|------|------|---------|-----------|------|------|")
        for w in alarm_w[:10]:
            ic = {"critical": "🔴", "warning": "🟠", "watch": "🟡"}.get(w["drift_status"], "⚪")
            rw = f"{w['recent_win_rate']*100:.1f}%" if w["recent_win_rate"] is not None else "N/A"
            lines.append(f"| {w['rule_name']}(`{w['rule_id']}`) | {w['rule_type']} | {w['historical_win_rate']*100:.1f}% | {rw} | {w['drift_score']:.2f} | {ic} {w['drift_status']} |")
    else:
        lines.append("✅ 無明顯衰退\n")

    # 特徵分布偏移
    alarm_f = [f for f in result["feature_drift"] if f["drift_status"] != "normal"]
    lines.append("\n## 📈 特徵分布偏移\n")
    if alarm_f:
        lines.append("| 特徵 | 參考均值 | 近期均值 | 變化% | 偏移 | 狀態 |")
        lines.append("|------|---------|---------|------|------|------|")
        for f in alarm_f[:10]:
            ic = {"critical": "🔴", "warning": "🟠", "watch": "🟡"}.get(f["drift_status"], "⚪")
            lines.append(f"| {f['feature_label']} | {f['reference_mean']} | {f['recent_mean']} | {f['mean_change_pct']:+.1f}% | {f['drift_score']:.2f} | {ic} {f['drift_status']} |")
    else:
        lines.append("✅ 無明顯偏移\n")

    # 健診評分偏移
    hs = result["health_score_drift"]
    lines.append("\n## 🩺 健診評分系統性偏移\n")
    if hs and hs[0]["drift_status"] != "normal":
        h = hs[0]
        ic = {"critical": "🔴", "warning": "🟠", "watch": "🟡"}.get(h["drift_status"], "⚪")
        lines.append(f"- 參考均值: {h['reference_mean']} → 近期均值: {h['recent_mean']} ({h['direction']})")
        lines.append(f"- 偏移分數: {h['drift_score']:.2f} {ic}\n")
    else:
        lines.append("✅ 評分分布穩定\n")

    return "\n".join(lines)


# ─── 7. 儲存 ──────────────────────────────────────────────────────────────

def store_drift_results(db: SignalDB, result: dict):
    """將漂移偵測結果寫入 structural_drift 表。"""
    today = date.today().isoformat()
    with db.connect() as conn:
        conn.execute("DELETE FROM structural_drift WHERE trade_date=?", [today])

        for item in result.get("trigger_drift", []):
            conn.execute(
                "INSERT INTO structural_drift (trade_date, drift_type, rule_id, feature_name, "
                "reference_value, recent_value, drift_score, drift_status, direction, details) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [today, "trigger_rate", item["rule_id"], None,
                 item["hist_rate"], item["recent_rate"],
                 item["drift_score"], item["drift_status"], item["direction"],
                 json.dumps(item, ensure_ascii=False)])

        for item in result.get("win_rate_drift", []):
            conn.execute(
                "INSERT INTO structural_drift (trade_date, drift_type, rule_id, feature_name, "
                "reference_value, recent_value, drift_score, drift_status, direction, details) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [today, "win_rate", item["rule_id"], None,
                 item["historical_win_rate"], item.get("recent_win_rate"),
                 item["drift_score"], item["drift_status"],
                 "down" if item.get("recent_win_rate") is not None and item["recent_win_rate"] < item["historical_win_rate"] else "stable",
                 json.dumps(item, ensure_ascii=False)])

        for item in result.get("feature_drift", []):
            conn.execute(
                "INSERT INTO structural_drift (trade_date, drift_type, rule_id, feature_name, "
                "reference_value, recent_value, drift_score, drift_status, direction, details) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [today, "feature_dist", None, item["feature_name"],
                 item["reference_mean"], item["recent_mean"],
                 item["drift_score"], item["drift_status"],
                 "up" if item["recent_mean"] > item["reference_mean"] else "down",
                 json.dumps(item, ensure_ascii=False)])

        for item in result.get("health_score_drift", []):
            conn.execute(
                "INSERT INTO structural_drift (trade_date, drift_type, rule_id, feature_name, "
                "reference_value, recent_value, drift_score, drift_status, direction, details) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [today, "health_score", None, None,
                 item["reference_mean"], item["recent_mean"],
                 item["drift_score"], item["drift_status"], item.get("direction", "stable"),
                 json.dumps(item, ensure_ascii=False)])
