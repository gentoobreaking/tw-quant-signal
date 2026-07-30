import json
from datetime import date, timedelta
from typing import Optional

import pandas as pd

from tw_quant_signal.db import SignalDB
from tw_quant_signal.twse_client import WATCH_STOCKS

RISK_LEVELS = [
    (80, "severe", "🔴 嚴重"),
    (60, "warning", "🟠 警告"),
    (30, "caution", "🟡 注意"),
    (0, "normal", "🟢 正常"),
]


def _risk_label(score: int) -> tuple[str, str]:
    for threshold, key, label in RISK_LEVELS:
        if score >= threshold:
            return key, label
    return "normal", "🟢 正常"


def compute_risk_metrics(db: SignalDB, trade_date: Optional[str] = None) -> list[dict]:
    trade_date = trade_date or date.today().isoformat()
    results = []
    for sid in WATCH_STOCKS:
        r = _stock_risk(db, sid, trade_date)
        if r:
            results.append(r)
    return results


def _stock_risk(db: SignalDB, stock_id: str, trade_date: str) -> Optional[dict]:
    with db.connect() as conn:
        prices = conn.execute(
            "SELECT trade_date, close, high, low FROM daily_prices WHERE stock_id=? AND trade_date<=? ORDER BY trade_date DESC LIMIT 260",
            [stock_id, trade_date],
        ).fetchall()
        if len(prices) < 60:
            return None

        feat = conn.execute(
            "SELECT data FROM features WHERE stock_id=? AND trade_date=?",
            [stock_id, trade_date],
        ).fetchone()

    closes = pd.Series([r[1] for r in reversed(prices)]).dropna()
    returns = closes.pct_change().dropna()

    vol_20d = float(returns.tail(20).std()) if len(returns) >= 20 else None
    vol_60d = float(returns.tail(60).std()) if len(returns) >= 60 else None
    vol_ratio = round(vol_20d / vol_60d, 2) if vol_20d and vol_60d and vol_60d > 0 else None

    atr = _compute_atr(prices, period=14)

    high_52w = max(r[2] or 0 for r in prices[:252])
    current_close = prices[0][1] or 0
    max_dd = round((high_52w - current_close) / high_52w, 4) if high_52w > 0 else None

    signal_conflict = False
    rule_rows = db.get_rule_signals_for_date(trade_date, stock_id)
    if rule_rows:
        triggered = json.loads(rule_rows[0].get("triggered_rules", "[]"))
        types = [tr.get("type") for tr in triggered]
        signal_conflict = "bullish" in types and "bearish" in types

    atr_val = atr[-1] if atr else None
    stop_loss_atr = round(current_close - 2 * atr_val, 2) if atr_val and current_close else None

    ma20_val = None
    ma60_val = None
    with db.connect() as conn:
        ind = conn.execute(
            "SELECT ma20, ma60 FROM tech_indicators WHERE stock_id=? AND trade_date<=? ORDER BY trade_date DESC LIMIT 1",
            [stock_id, trade_date],
        ).fetchone()
        if ind:
            ma20_val = ind[0]
            ma60_val = ind[1]
    if ma20_val and ma60_val:
        if current_close > ma20_val:
            stop_loss_ma = ma20_val
        elif current_close > ma60_val:
            stop_loss_ma = ma60_val
        else:
            recent_lows = [r[1] for r in prices[1:21] if r[1] is not None]
            stop_loss_ma = min(recent_lows) if recent_lows else current_close * 0.95
    else:
        stop_loss_ma = None

    details = {}

    score = 0
    if vol_ratio and vol_ratio > 1.5:
        score += 30
        details["volatility_spike"] = True
    elif vol_ratio and vol_ratio > 1.2:
        score += 15
        details["volatility_elevated"] = True

    if max_dd and max_dd > 0.2:
        score += 25
    elif max_dd and max_dd > 0.1:
        score += 10
        details["drawdown_noted"] = True

    if signal_conflict:
        score += 20

    if atr_val and current_close:
        atr_pct = atr_val / current_close
        if atr_pct > 0.05:
            score += 25
        elif atr_pct > 0.03:
            score += 10
    else:
        atr_pct = None

    risk_key, risk_label = _risk_label(score)

    return {
        "stock_id": stock_id,
        "trade_date": trade_date,
        "volatility_20d": round(vol_20d, 4) if vol_20d else None,
        "volatility_avg": round(vol_60d, 4) if vol_60d else None,
        "vol_ratio": vol_ratio,
        "atr_14d": round(atr_val, 2) if atr_val else None,
        "atr_pct": round(atr_pct, 4) if atr_pct else None,
        "max_drawdown": max_dd,
        "signal_conflict": signal_conflict,
        "stop_loss_atr": stop_loss_atr,
        "stop_loss_ma": stop_loss_ma,
        "risk_level": risk_key,
        "risk_score": score,
        "details": details,
    }


def _compute_atr(prices: list, period: int = 14) -> list:
    if len(prices) < period + 1:
        return []
    df = pd.DataFrame(
        [{"high": r[2], "low": r[3], "close": r[1]} for r in reversed(prices)]
    ).dropna()
    df["prev_close"] = df["close"].shift(1)
    df["tr"] = pd.concat([
        (df["high"] - df["low"]).abs(),
        (df["high"] - df["prev_close"]).abs(),
        (df["low"] - df["prev_close"]).abs(),
    ], axis=1).max(axis=1)
    atr = df["tr"].rolling(period).mean().dropna().tolist()
    return atr
