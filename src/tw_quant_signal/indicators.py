import numpy as np
import pandas as pd


def compute_indicators(prices: list[dict], stock_id: str = "2330") -> list[dict]:
    if not prices:
        return []
    df = pd.DataFrame(prices)
    df = df.sort_values("trade_date").reset_index(drop=True)

    close = df["close"].astype(float)
    volume = df["volume"].astype(float)

    df["ma5"] = _ma(close, 5)
    df["ma20"] = _ma(close, 20)
    df["ma60"] = _ma(close, 60)

    bb = _bollinger(close, 20)
    df["bb_upper"] = bb[0]
    df["bb_middle"] = bb[1]
    df["bb_lower"] = bb[2]

    df["rsi14"] = _rsi(close, 14)

    df["volume_ma5"] = _ma(volume, 5)
    df["volume_ma20"] = _ma(volume, 20)

    df["stock_id"] = stock_id
    df["trade_date"] = df["trade_date"].astype(str)

    cols = ["stock_id", "trade_date", "ma5", "ma20", "ma60",
            "bb_upper", "bb_middle", "bb_lower", "rsi14",
            "volume_ma5", "volume_ma20"]
    return df[cols].to_dict(orient="records")


def _ma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window, min_periods=window).mean()


def _bollinger(series: pd.Series, window: int) -> tuple[pd.Series, pd.Series, pd.Series]:
    ma = series.rolling(window=window, min_periods=window).mean()
    std = series.rolling(window=window, min_periods=window).std(ddof=0)
    upper = ma + 2 * std
    lower = ma - 2 * std
    return upper, ma, lower


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi


def ma_alignment(ma5: float, ma20: float, ma60: float) -> str:
    if ma5 is None or ma20 is None or ma60 is None:
        return "unknown"
    if ma5 > ma20 > ma60:
        return "bullish"
    elif ma5 < ma20 < ma60:
        return "bearish"
    else:
        return "neutral"


def bb_position(close: float, bb_upper: float, bb_lower: float, bb_middle: float) -> str:
    if close is None or bb_upper is None or bb_lower is None or bb_middle is None:
        return "unknown"
    if close >= bb_upper:
        return "above_upper"
    elif close <= bb_lower:
        return "below_lower"
    elif close >= bb_middle:
        return "above_mid"
    else:
        return "below_mid"


def rsi_signal(rsi_val: float) -> str:
    if rsi_val is None:
        return "unknown"
    if rsi_val >= 70:
        return "overbought"
    elif rsi_val <= 30:
        return "oversold"
    elif 50 <= rsi_val < 70:
        return "bullish"
    elif 30 < rsi_val < 50:
        return "bearish"
    return "neutral"
