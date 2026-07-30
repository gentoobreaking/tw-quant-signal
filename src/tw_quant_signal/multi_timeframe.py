import json
from typing import Optional

import numpy as np

from tw_quant_signal.db import SignalDB
from tw_quant_signal.twse_client import WATCH_STOCKS

LIGHT_ORDER = {
    "🟢": 5,
    "🟢🔴": 4,
    "🟡": 3,
    "🔴🟢": 2,
    "🔴": 1,
}
LIGHT_LABEL = {
    "🟢": "強勢多頭",
    "🟢🔴": "偏多",
    "🟡": "中立",
    "🔴🟢": "偏空",
    "🔴": "強勢空頭",
}
CONSENSUS_MAP = {
    (5, 5): ("strong_bullish", "強烈偏多"),
    (5, 4): ("strong_bullish", "強烈偏多"),
    (4, 5): ("strong_bullish", "強烈偏多"),
    (5, 3): ("mild_bullish", "溫和偏多"),
    (3, 5): ("mild_bullish", "溫和偏多"),
    (4, 4): ("mild_bullish", "溫和偏多"),
    (4, 3): ("mild_bullish", "溫和偏多"),
    (3, 4): ("mild_bullish", "溫和偏多"),
    (3, 3): ("neutral", "中立"),
    (3, 2): ("mild_bearish", "溫和偏空"),
    (2, 3): ("mild_bearish", "溫和偏空"),
    (2, 2): ("mild_bearish", "溫和偏空"),
    (2, 1): ("strong_bearish", "強烈偏空"),
    (1, 2): ("strong_bearish", "強烈偏空"),
    (1, 1): ("strong_bearish", "強烈偏空"),
    (1, 3): ("mild_bearish", "溫和偏空"),
    (3, 1): ("mild_bearish", "溫和偏空"),
    (5, 2): ("mild_bullish", "溫和偏多"),
    (2, 5): ("mild_bullish", "溫和偏多"),
    (4, 2): ("mild_bullish", "溫和偏多"),
    (2, 4): ("mild_bullish", "溫和偏多"),
    (5, 1): ("conflicting", "方向衝突"),
    (1, 5): ("conflicting", "方向衝突"),
    (4, 1): ("conflicting", "方向衝突"),
    (1, 4): ("conflicting", "方向衝突"),
}


def _light_to_int(light: Optional[str]) -> int:
    return LIGHT_ORDER.get(light or "", 3)


def _signal_type(daily_int: int, weekly_int: int) -> str:
    """Classify signal horizon.

    - Short-term (1-5 days): daily has signal but weekly doesn't align
    - Swing (1-4 weeks): weekly has strong signal, daily confirming
    - Both: both aligned in same direction
    - Conflicting: daily and weekly point in opposite directions
    - Neutral: neither timeframe has clear signal
    """
    # Conflicting: strongly opposing directions
    if (daily_int >= 4 and weekly_int <= 2) or (daily_int <= 2 and weekly_int >= 4):
        return "conflicting"
    # Both aligned bullish or both aligned bearish
    if (daily_int >= 4 and weekly_int >= 4) or (daily_int <= 2 and weekly_int <= 2):
        return "both"
    # Weekly dominant signal
    if weekly_int >= 4 or weekly_int <= 2:
        return "swing"
    # Daily dominant signal
    if daily_int >= 4 or daily_int <= 2:
        return "short"
    return "neutral"


def compute_multi_timeframe(
    db: SignalDB,
    trade_date: Optional[str] = None,
) -> list[dict]:
    """Compute multi-timeframe consensus from daily and weekly health scores.

    Extension point: add monthly_health to the comparison for mid-term (1-3 month)
    framework support. Monthly health scores follow the same schema as weekly.
    """
    from datetime import date

    trade_date = trade_date or date.today().isoformat()

    daily_scores = db.get_health_scores(trade_date)
    weekly_scores = db.get_weekly_health_scores(trade_date)
    # --- Mid-term extension point ---
    # monthly_scores = db.get_monthly_health_scores(trade_date)
    # For now, only daily + weekly are active.

    daily_map = {s["stock_id"]: s for s in daily_scores}
    weekly_map = {s["stock_id"]: s for s in weekly_scores}

    results = []
    for sid in WATCH_STOCKS:
        ds = daily_map.get(sid)
        ws = weekly_map.get(sid)

        daily_light = ds["total_light"] if ds else None
        weekly_light = ws["total_light"] if ws else None

        daily_int = _light_to_int(daily_light)
        weekly_int = _light_to_int(weekly_light)

        consensus_key = CONSENSUS_MAP.get((daily_int, weekly_int), ("neutral", "中立"))
        consensus = consensus_key[0]
        consensus_label_str = consensus_key[1]

        signal_type = _signal_type(daily_int, weekly_int)

        results.append({
            "trade_date": trade_date,
            "stock_id": sid,
            "daily_light": daily_light,
            "weekly_light": weekly_light,
            "consensus": consensus,
            "consensus_label": consensus_label_str,
            "signal_type": signal_type,
            "details": {
                "daily_score": ds["total_score"] if ds else None,
                "weekly_score": ws["total_score"] if ws else None,
                "daily_fundamental": ds["fundamental_score"] if ds else None,
                "weekly_fundamental": ws["fundamental_score"] if ws else None,
                "daily_technical": ds["technical_score"] if ds else None,
                "weekly_technical": ws["technical_score"] if ws else None,
            },
        })

    return results


def compute_weekly_indicators_pipeline(db: SignalDB) -> None:
    """Pipeline step: compute weekly indicators for all watched stocks."""
    from tw_quant_signal.indicators import compute_weekly_indicators

    for sid in WATCHLIST:
        prices = db.get_stock_prices(sid, limit=1500)
        if not prices:
            continue
        daily_prices = [dict(p) for p in prices]
        daily_prices.sort(key=lambda p: p["trade_date"])
        weekly_rows = compute_weekly_indicators(daily_prices, sid)
        if weekly_rows:
            db.upsert_weekly_indicators(weekly_rows)


WATCHLIST = WATCH_STOCKS