
import numpy as np
import pandas as pd

from tw_quant_signal.config import WATCH_STOCKS
from tw_quant_signal.db import SignalDB
from tw_quant_signal.indicators import compute_indicators
from tw_quant_signal.provider import create_data_provider


def compute_all_features(db: SignalDB, val_map: dict[str, dict] | None = None, indicators_map: dict[str, list[dict]] | None = None) -> list[dict]:
    """計算全部觀察標的之特徵（T016 §2：valuation 由外部一次拉取傳入）。

    Args:
        db: SignalDB
        val_map: 全體股票估值 map（stock_id -> {pe_ratio, pb_ratio, dividend_yield}）
        indicators_map: 已算好的技術指標 map（stock_id -> compute_indicators 輸出列表）
    """
    if val_map is None:
        # T020: 估值資料改由 DataProvider 抽象層取得（替代 inline import twse_client）
        val_map = create_data_provider().fetch_valuations()
    features = []
    for sid in WATCH_STOCKS:
        row = _stock_features(db, sid, val=val_map.get(sid, {}), indicators=indicators_map.get(sid) if indicators_map else None)
        if row:
            features.append(row)
    row = _index_features(db)
    if row:
        features.append(row)
    row = _market_breadth(db)
    if row:
        features.append(row)
    return features


def compute_indicators_for_stock(db: SignalDB, stock_id: str, lookback: int = 120, full: bool = False) -> list[dict]:
    """T016 §4：集中計算單一標的之技術指標（供 ingestion 一次批次計算並
    傳入 _stock_features，避免 features 層重複查詢/計算）。

    incremental 日增量：lookback=120 天即可（MA60+BB20+RSI14 均需 <120 天），
    比 365 天可節省約 67% 運算時間。full=True 時強制使用 365 天（backfill 場景）。
    """
    limit = 365 if full else lookback
    prices = db.get_stock_prices(stock_id, limit=limit)
    if len(prices) < 60:
        return []
    prices = [dict(p) for p in prices]
    prices.sort(key=lambda p: p["trade_date"])
    return compute_indicators(prices, stock_id=stock_id)


def _stock_features(db: SignalDB, stock_id: str, val: dict | None = None, indicators: list[dict] | None = None) -> dict | None:
    with db.connect() as conn:
        prices = conn.execute(
            "SELECT trade_date, close, volume FROM daily_prices WHERE stock_id=? ORDER BY trade_date DESC LIMIT 365",
            [stock_id],
        ).fetchall()
        if len(prices) < 60:
            return None
        latest = prices[0]
        trade_date = latest[0]
        close = latest[1]

        if indicators is None:
            ind = conn.execute(
                "SELECT ma5, ma20, ma60, rsi14, bb_upper, bb_middle, bb_lower, volume_ma5, volume_ma20 "
                "FROM tech_indicators WHERE stock_id=? ORDER BY trade_date DESC LIMIT 1",
                [stock_id],
            ).fetchone()
            if not ind:
                return None
        else:
            latest_ind = indicators[-1] if indicators else None
            if not latest_ind:
                return None
            ind = {
                "ma5": latest_ind.get("ma5"), "ma20": latest_ind.get("ma20"),
                "ma60": latest_ind.get("ma60"), "rsi14": latest_ind.get("rsi14"),
                "bb_upper": latest_ind.get("bb_upper"), "bb_middle": latest_ind.get("bb_middle"),
                "bb_lower": latest_ind.get("bb_lower"), "volume_ma5": latest_ind.get("volume_ma5"),
                "volume_ma20": latest_ind.get("volume_ma20"),
            }

        inst = conn.execute(
            "SELECT foreign_investors_net, sity_investors_net, dealer_net "
            "FROM institutional_flows WHERE stock_id=? ORDER BY trade_date DESC LIMIT 1",
            [stock_id],
        ).fetchone()

        inst_5d = conn.execute(
            "SELECT foreign_investors_net, sity_investors_net FROM institutional_flows "
            "WHERE stock_id=? ORDER BY trade_date DESC LIMIT 5",
            [stock_id],
        ).fetchall()

    val = val or {}

    df = pd.DataFrame([{"close": r[1], "volume": r[2]} for r in prices])
    returns = df["close"].pct_change()

    index_prices = _get_index_prices(db)
    index_df = pd.DataFrame([{"close": r["close"]} for r in index_prices]) if index_prices else pd.DataFrame()
    stock_rets = pd.Series([r[1] for r in prices]).pct_change()
    index_rets = pd.Series(index_df["close"]).pct_change() if not index_df.empty else pd.Series()

    beta_5d = None
    if len(stock_rets) >= 5 and len(index_rets) >= 5:
        s = stock_rets.iloc[-5:].dropna()
        i = index_rets.iloc[-5:].dropna()
        if len(s) == len(i) > 2:
            with np.errstate(divide="ignore", invalid="ignore"):
                beta_5d = float(np.cov(s, i)[0, 1] / np.var(i)) if np.var(i) > 0 else None

    volume = latest[2] or 0
    vol_ma5 = ind["volume_ma5"] or 1
    vol_ratio = round(volume / vol_ma5, 2) if vol_ma5 > 0 else None

    price_ma5 = ind["ma5"] or close
    ma_position_pct = round((close - price_ma5) / price_ma5 * 100, 2)

    inst_3d_sum = sum(r[0] or 0 for r in inst_5d[:3]) if inst_5d else None
    inst_5d_sum = sum(r[0] or 0 for r in inst_5d) if inst_5d else None
    sity_5d = [r[1] for r in inst_5d] if inst_5d else []
    sity_5d_sum = sum(sity_5d) if sity_5d else None

    inst_3d_signal = _inst_signal(inst_3d_sum) if inst_3d_sum is not None else None
    inst_5d_signal = _inst_signal(inst_5d_sum) if inst_5d_sum is not None else None
    foreign_5d_trend = _trend_direction(inst_5d_sum)
    sity_5d_trend = _trend_direction(sity_5d_sum)

    pe = val.get("pe_ratio")
    pb = val.get("pb_ratio")
    dy = val.get("dividend_yield")

    close_vs_ma20 = _relative_position(close, ind["ma20"])
    close_vs_ma60 = _relative_position(close, ind["ma60"])

    pe_percentile = _historical_percentile(db, stock_id, "pe_ratio", pe)
    pb_percentile = _historical_percentile(db, stock_id, "pb_ratio", pb)
    pe_river = "high" if pe_percentile and pe_percentile > 0.8 else ("low" if pe_percentile and pe_percentile < 0.2 else "mid")
    pb_river = "high" if pb_percentile and pb_percentile > 0.8 else ("low" if pb_percentile and pb_percentile < 0.2 else "mid")

    row = {
        "stock_id": stock_id,
        "trade_date": trade_date,
        "close": close,
        "ma5": ind["ma5"],
        "ma20": ind["ma20"],
        "ma60": ind["ma60"],
        "ma_alignment": _signal_ma(ind["ma5"], ind["ma20"], ind["ma60"]),
        "rsi14": ind["rsi14"],
        "rsi_signal": _signal_rsi(ind["rsi14"]),
        "bb_position": _signal_bb(close, ind["bb_upper"], ind["bb_lower"], ind["bb_middle"]),
        "volume_ratio": vol_ratio,
        "volume_ma5": ind["volume_ma5"],
        "ma_position_pct": ma_position_pct,
        "beta_5d": beta_5d,
        "foreign_net_1d": inst[0] if inst else None,
        "sity_net_1d": inst[1] if inst else None,
        "dealer_net_1d": inst[2] if inst else None,
        "foreign_net_3d_sum": inst_3d_sum,
        "foreign_net_5d_sum": inst_5d_sum,
        "foreign_3d_signal": inst_3d_signal,
        "foreign_5d_signal": inst_5d_signal,
        "foreign_5d_trend": foreign_5d_trend,
        "sity_5d_trend": sity_5d_trend,
        "close_vs_ma20": close_vs_ma20,
        "close_vs_ma60": close_vs_ma60,
        "pe_ratio": pe,
        "pb_ratio": pb,
        "dividend_yield": dy,
        "pe_signal": _signal_pe(pe) if pe else None,
        "pb_signal": _signal_pb(pb) if pb else None,
        "dy_signal": _signal_dy(dy) if dy is not None else None,
        "pe_percentile": pe_percentile,
        "pb_percentile": pb_percentile,
        "pe_river": pe_river,
        "pb_river": pb_river,
    }
    return row


def _index_features(db: SignalDB) -> dict | None:
    prices = _get_index_prices(db)
    if len(prices) < 60:
        return None
    latest = prices[-1]
    closes = [r["close"] for r in prices]
    s = pd.Series(closes)
    ma20 = float(s.rolling(20).mean().iloc[-1])
    ma60 = float(s.rolling(60).mean().iloc[-1])

    with db.connect() as conn:
        latest_idx = conn.execute(
            "SELECT trade_date, close, change_pct FROM market_index ORDER BY trade_date DESC LIMIT 1"
        ).fetchone()

    trade_date = latest_idx[0] if latest_idx else latest["trade_date"]
    close = latest_idx[1] if latest_idx else latest["close"]
    change_pct = latest_idx[2] if latest_idx else None

    pos = "above" if close > ma20 else ("below" if close < ma20 else "at")

    rs_2330_vs_index = _relative_strength_2330(db, prices)

    return {
        "stock_id": "^TWII",
        "trade_date": str(trade_date),
        "close": close,
        "change_pct": change_pct,
        "index_ma20": ma20,
        "index_ma60": ma60,
        "index_vs_ma20": pos,
        "index_vs_ma60": "above" if close > ma60 else ("below" if close < ma60 else "at"),
        "rs_2330_vs_index": rs_2330_vs_index,
    }


def _market_breadth(db: SignalDB) -> dict | None:
    with db.connect() as conn:
        latest_inst = conn.execute(
            "SELECT trade_date FROM institutional_flows ORDER BY trade_date DESC LIMIT 1"
        ).fetchone()
        if not latest_inst:
            return None
        inst_date = latest_inst[0]

        inst_count = conn.execute(
            "SELECT COUNT(DISTINCT stock_id) FROM institutional_flows WHERE trade_date=?", [inst_date]
        ).fetchone()[0]

        pos_count = conn.execute(
            "SELECT COUNT(*) FROM institutional_flows WHERE trade_date=? AND foreign_investors_net > 0",
            [inst_date],
        ).fetchone()[0]

    breadth_ratio = round(pos_count / inst_count, 4) if inst_count else None
    return {
        "stock_id": "BREADTH",
        "trade_date": str(inst_date),
        "total_stocks": inst_count,
        "foreign_buy_count": pos_count,
        "foreign_buy_ratio": breadth_ratio,
        "breadth_signal": "broad" if breadth_ratio and breadth_ratio > 0.5 else ("narrow" if breadth_ratio else None),
    }


def _get_index_prices(db: SignalDB) -> list[dict]:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT trade_date, close FROM market_index ORDER BY trade_date ASC"
        ).fetchall()
    return [{"trade_date": r[0], "close": r[1]} for r in rows if r[1] is not None]


def _signal_ma(ma5, ma20, ma60) -> str:
    if ma5 is None or ma20 is None or ma60 is None:
        return "unknown"
    if ma5 > ma20 > ma60:
        return "bullish"
    if ma5 < ma20 < ma60:
        return "bearish"
    return "neutral"


def _signal_rsi(val) -> str:
    if val is None:
        return "unknown"
    if val >= 70:
        return "overbought"
    if val <= 30:
        return "oversold"
    if 50 <= val < 70:
        return "bullish"
    return "bearish"


def _signal_bb(close, upper, lower, mid) -> str:
    if close is None or upper is None or lower is None:
        return "unknown"
    if close >= upper:
        return "above_upper"
    if close <= lower:
        return "below_lower"
    if close >= mid:
        return "above_mid"
    return "below_mid"


def _inst_signal(total: int) -> str:
    """Categorize institutional flow magnitude."""
    if total is None:
        return "unknown"
    abs_val = abs(total)
    if abs_val > 5_000_000:
        return "strong"
    if abs_val > 1_000_000:
        return "moderate"
    return "weak"


def _signal_pe(pe: float) -> str:
    if pe is None:
        return "unknown"
    if pe < 15:
        return "low"
    if pe > 25:
        return "high"
    return "fair"


def _signal_pb(pb: float) -> str:
    if pb is None:
        return "unknown"
    if pb < 1.5:
        return "low"
    if pb > 3:
        return "high"
    return "fair"


def _signal_dy(dy: float) -> str:
    if dy is None:
        return "unknown"
    if dy > 0.05:
        return "high"
    if dy > 0.02:
        return "fair"
    return "low"


def _trend_direction(net: int | None) -> str | None:
    if net is None:
        return None
    if net > 1_000_000:
        return "strong_buy"
    if net > 200_000:
        return "buy"
    if net < -1_000_000:
        return "strong_sell"
    if net < -200_000:
        return "sell"
    return "neutral"


def _relative_position(close: float | None, ma: float | None) -> str | None:
    if close is None or ma is None:
        return None
    if close > ma * 1.01:
        return "above"
    if close < ma * 0.99:
        return "below"
    return "at"


def _historical_percentile(db: SignalDB, stock_id: str, field: str, current_value: float | None) -> float | None:
    if current_value is None:
        return None
    import json
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT data FROM features WHERE stock_id=? ORDER BY trade_date DESC LIMIT 252",
            [stock_id],
        ).fetchall()
    values = []
    for (raw,) in rows:
        d = json.loads(raw)
        v = d.get(field)
        if v is not None:
            values.append(v)
    if len(values) < 10:
        return None
    count_below = sum(1 for v in values if v <= current_value)
    return round(count_below / len(values), 4)


def _relative_strength_2330(db: SignalDB, index_prices: list[dict]) -> float | None:
    with db.connect() as conn:
        p2330 = conn.execute(
            "SELECT close FROM daily_prices WHERE stock_id='2330' ORDER BY trade_date DESC LIMIT 5"
        ).fetchall()
    if len(p2330) < 5 or len(index_prices) < 5:
        return None
    stock_ret = (p2330[0][0] - p2330[-1][0]) / p2330[-1][0]
    index_close = [r["close"] for r in index_prices[-5:]]
    idx_ret = (index_close[-1] - index_close[0]) / index_close[0]
    if idx_ret == 0:
        return None
    return round(stock_ret - idx_ret, 4)


def features_to_report_rows(features: list[dict]) -> list[dict]:
    rows = []
    for f in features:
        if f["stock_id"] in WATCH_STOCKS:
            rows.append({
                "trade_date": f["trade_date"],
                "stock_id": f["stock_id"],
                "close": f["close"],
                "ma_alignment": f["ma_alignment"],
                "rsi_signal": f["rsi_signal"],
                "bb_position": f["bb_position"],
                "volume_ratio": f["volume_ratio"],
                "foreign_3d_signal": f["foreign_3d_signal"],
                "foreign_5d_signal": f["foreign_5d_signal"],
                "pe_signal": f["pe_signal"],
                "pb_signal": f["pb_signal"],
                "dy_signal": f["dy_signal"],
            })
    return rows
