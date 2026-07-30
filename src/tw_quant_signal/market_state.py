from datetime import date, timedelta
from typing import Optional

import pandas as pd

from tw_quant_signal.db import SignalDB


def detect_market_state(db: SignalDB, trade_date: Optional[str] = None) -> dict:
    trade_date = trade_date or date.today().isoformat()
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT trade_date, close FROM market_index WHERE trade_date<=? ORDER BY trade_date ASC",
            [trade_date],
        ).fetchall()
    if len(rows) < 120:
        return {"state": "unknown", "close": None, "ma60": None, "ma60_trend": None, "rsi14": None}

    closes = pd.Series([r[1] for r in rows if r[1] is not None])
    close = float(closes.iloc[-1])
    ma60 = float(closes.rolling(60).mean().iloc[-1])
    ma60_20d = float(closes.rolling(60).mean().iloc[-21]) if len(closes) >= 80 else ma60
    ma60_trend = ma60 - ma60_20d

    rsi14 = _rsi(closes)
    rsi_val = float(rsi14.iloc[-1]) if rsi14 is not None and not rsi14.empty else None

    above_ma60 = close > ma60 * 1.01
    below_ma60 = close < ma60 * 0.99
    trend_up = ma60_trend > 0
    trend_down = ma60_trend < 0

    if above_ma60 and trend_up and rsi_val is not None and rsi_val > 55:
        state = "bull"
    elif below_ma60 and trend_down and rsi_val is not None and rsi_val < 45:
        state = "bear"
    else:
        state = "range"

    return {
        "state": state,
        "close": round(close, 2),
        "ma60": round(ma60, 2),
        "ma60_trend": round(ma60_trend, 2),
        "rsi14": round(rsi_val, 2) if rsi_val is not None else None,
    }


def _rsi(series: pd.Series, period: int = 14) -> Optional[pd.Series]:
    if len(series) < period + 1:
        return None
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    return 100 - (100 / (1 + rs))


LABELS = {"bull": "多頭 📈", "bear": "空頭 📉", "range": "盤整 ➡️", "unknown": "未知"}
