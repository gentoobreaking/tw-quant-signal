import json
import os
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from tw_quant_signal.db import SignalDB
from tw_quant_signal.twse_client import WATCH_STOCKS
from tw_quant_signal.market_state import detect_market_state

STATE_WEIGHTS = {
    "bull": {"bullish": 1.5, "bearish": 1.0, "neutral": 1.0},
    "bear": {"bullish": 1.0, "bearish": 1.5, "neutral": 1.0},
    "range": {"bullish": 1.0, "bearish": 1.0, "neutral": 1.0},
    "unknown": {"bullish": 1.0, "bearish": 1.0, "neutral": 1.0},
}


def _load_rules() -> list[dict]:
    config_dir = Path(__file__).parent.parent.parent / "configs"
    files = ["rules_bearish.yaml", "rules_bullish.yaml", "rules_neutral.yaml"]
    rules = []
    for fname in files:
        path = config_dir / fname
        if path.exists():
            with open(path) as f:
                data = yaml.safe_load(f)
                rules.extend(data.get("rules", []))
    return rules


def evaluate_rule(rule: dict, stock_features: dict, all_stock_features: dict[str, dict], index_features: dict, breadth_features: dict) -> bool:
    conditions = rule.get("conditions", {})
    scope = rule.get("scope", "stock")

    if scope == "market":
        feat = {**index_features, **breadth_features}
    else:
        feat = dict(stock_features)
        feat["index_vs_ma20"] = index_features.get("index_vs_ma20")
        feat["index_vs_ma60"] = index_features.get("index_vs_ma60")
        feat["market_breadth"] = breadth_features.get("breadth_signal")

    feature_names = _all_condition_features(conditions)
    for fn in feature_names:
        if fn.startswith("stock_"):
            parts = fn.split("_", 2)
            if len(parts) >= 3:
                ref_sid = parts[1]
                ref_feat_name = parts[2]
                ref_feats = all_stock_features.get(ref_sid, {})
                feat[fn] = ref_feats.get(ref_feat_name)

    return _eval_conditions(conditions, feat)


def _all_condition_features(conditions: dict) -> set[str]:
    features = set()
    for key in ("all", "any"):
        for cond in conditions.get(key, []):
            features.add(cond.get("feature", ""))
    return features


def _eval_conditions(conditions: dict, feat: dict) -> bool:
    if "all" in conditions:
        return all(_eval_condition(c, feat) for c in conditions["all"])
    if "any" in conditions:
        return any(_eval_condition(c, feat) for c in conditions["any"])
    return False


def _eval_condition(cond: dict, feat: dict) -> bool:
    feature = cond.get("feature", "")
    operator = cond.get("operator", "eq")
    value = cond.get("value")
    actual = feat.get(feature)
    if actual is None:
        return False

    if operator == "eq":
        return actual == value
    if operator == "neq":
        return actual != value
    if operator == "gt":
        return _to_num(actual) > _to_num(value)
    if operator == "gte":
        return _to_num(actual) >= _to_num(value)
    if operator == "lt":
        return _to_num(actual) < _to_num(value)
    if operator == "lte":
        return _to_num(actual) <= _to_num(value)
    if operator == "in":
        return actual in value
    if operator == "not_in":
        return actual not in value
    return False


def _to_num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def compute_rule_signals(db: SignalDB, trade_date: str | None = None) -> list[dict]:
    trade_date = trade_date or date.today().isoformat()
    rules = _load_rules()

    # T016 §1：以指定 trade_date 載入特徵，避免取到最新（可能跨日）特徵造成 stale
    features = _load_features(db, trade_date=trade_date)
    if not features:
        return []

    index_feat = features.get("^TWII", {})
    breadth_feat = features.get("BREADTH", {})

    market_state = detect_market_state(db, trade_date)["state"]

    results = []
    for sid in WATCH_STOCKS:
        stock_feat = features.get(sid, {})
        triggered = []
        for rule in rules:
            try:
                matched = evaluate_rule(rule, stock_feat, features, index_feat, breadth_feat)
            except Exception:
                matched = False
            if matched:
                triggered.append({
                    "rule_id": rule["id"],
                    "rule_name": rule["name"],
                    "type": rule.get("type", "neutral"),
                    "failure": rule.get("failure_condition", ""),
                })

        agg_signal, agg_score = _aggregate_rules(triggered, market_state)

        results.append({
            "stock_id": sid,
            "trade_date": trade_date,
            "triggered_rules": triggered,
            "triggered_count": len(triggered),
            "signal": agg_signal,
            "total_score": agg_score,
        })

    return results


def _aggregate_rules(triggered: list[dict], market_state: str = "range") -> tuple[str, int]:
    weights = STATE_WEIGHTS.get(market_state, STATE_WEIGHTS["range"])
    score = 0.0
    for r in triggered:
        t = r["type"]
        w = weights.get(t, 1.0)
        if t == "bearish":
            score -= 1 * w
        elif t == "bullish":
            score += 1 * w
        else:
            score += 0
    score_int = int(round(score))
    if score_int > 0:
        return "bullish", score_int
    if score_int < 0:
        return "bearish", score_int
    return "neutral", score_int


def store_rule_signals(db: SignalDB, signals: list[dict]):
    if not signals:
        return
    with db.connect() as conn:
        for s in signals:
            conn.execute("DELETE FROM rule_signals WHERE trade_date=? AND stock_id=?", [s["trade_date"], s["stock_id"]])
            conn.execute(
                """INSERT INTO rule_signals
                (trade_date, stock_id, triggered_rules, triggered_count, signal, total_score)
                VALUES (?, ?, ?, ?, ?, ?)""",
                [
                    s["trade_date"], s["stock_id"],
                    json.dumps(s["triggered_rules"], ensure_ascii=False),
                    s["triggered_count"], s["signal"], s["total_score"],
                ],
            )


def compute_rule_stats(db: SignalDB, days: int = 30) -> dict[str, dict]:
    """Compute historical trigger stats per rule over the last N days."""
    rules = _load_rules()
    stats = {r["id"]: {"name": r["name"], "type": r["type"], "triggers": 0, "by_stock": {}} for r in rules}
    # add 0 for all known rule_ids
    for rule in rules:
        rid = rule["id"]
        stats.setdefault(rid, {"name": rule["name"], "type": rule.get("type", ""), "triggers": 0, "by_stock": {}})
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT stock_id, triggered_rules FROM rule_signals ORDER BY trade_date DESC LIMIT ?",
            [days * 3],
        ).fetchall()
    for sid, raw in rows:
        triggered = json.loads(raw)
        for tr in triggered:
            rid = tr.get("rule_id", "")
            if rid in stats:
                stats[rid]["triggers"] += 1
                stats[rid]["by_stock"][sid] = stats[rid]["by_stock"].get(sid, 0) + 1
    return stats


def _load_features(db: SignalDB, trade_date: str | None = None) -> dict[str, dict]:
    """載入特徵 map（stock_id -> data）。

    T016 §1：以 GROUP BY stock_id + MAX(trade_date) 取每檔最新特徵，並支援
    trade_date 過濾（<= 指定日），避免一次 ORDER BY 全域排序 + 去重。
    """
    params: list = []
    where = ""
    if trade_date:
        where = "WHERE fe.trade_date <= ?"
        params.append(trade_date)
    sql = f"""
        SELECT f.stock_id, f.data
        FROM features f
        JOIN (
            SELECT fe.stock_id, MAX(fe.trade_date) AS max_d
            FROM features fe
            {where}
            GROUP BY fe.stock_id
        ) g ON g.stock_id = f.stock_id AND f.trade_date = g.max_d
    """
    with db.connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return {sid: json.loads(raw) for sid, raw in rows}
