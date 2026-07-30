import json
import os
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from tw_quant_signal.db import SignalDB
from tw_quant_signal.twse_client import WATCH_STOCKS


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

    features = _load_features(db)
    if not features:
        return []

    index_feat = features.get("^TWII", {})
    breadth_feat = features.get("BREADTH", {})

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

        agg_signal, agg_score = _aggregate_rules(triggered)

        results.append({
            "stock_id": sid,
            "trade_date": trade_date,
            "triggered_rules": triggered,
            "triggered_count": len(triggered),
            "signal": agg_signal,
            "total_score": agg_score,
        })

    return results


def _aggregate_rules(triggered: list[dict]) -> tuple[str, int]:
    score = 0
    for r in triggered:
        t = r["type"]
        if t == "bearish":
            score -= 1
        elif t == "bullish":
            score += 1
    if score > 0:
        return "bullish", score
    if score < 0:
        return "bearish", score
    return "neutral", score


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


def _load_features(db: SignalDB) -> dict[str, dict]:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT stock_id, data FROM features ORDER BY trade_date DESC"
        ).fetchall()
    grouped: dict[str, dict] = {}
    for sid, raw in rows:
        if sid not in grouped:
            grouped[sid] = json.loads(raw)
    return grouped
