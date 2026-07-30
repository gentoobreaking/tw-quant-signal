import json
import math
from datetime import date, timedelta
from typing import Optional

import pandas as pd
import yfinance as yf

from tw_quant_signal.db import SignalDB
from tw_quant_signal.twse_client import (
    WATCH_STOCKS, fetch_valuations, fetch_margin_data, fetch_yf_financials,
)
from tw_quant_signal.market_state import detect_market_state

LIGHT_GREEN = "🟢"
LIGHT_YELLOW_GREEN = "🟢🔴"
LIGHT_YELLOW = "🟡"
LIGHT_RED_GREEN = "🔴🟢"
LIGHT_RED = "🔴"


def _sub_light(score: float) -> str:
    if score >= 70:
        return LIGHT_GREEN
    if score >= 30:
        return LIGHT_YELLOW
    return LIGHT_RED


def _total_light(score: float) -> str:
    if score >= 80:
        return LIGHT_GREEN
    if score >= 60:
        return LIGHT_YELLOW_GREEN
    if score >= 40:
        return LIGHT_YELLOW
    if score >= 20:
        return LIGHT_RED_GREEN
    return LIGHT_RED


def _clamp(v: float, lo: float = 0, hi: float = 100) -> float:
    return max(lo, min(hi, v))


def _safe(val: Optional[float]) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _get_latest_features(db: SignalDB, stock_id: str) -> Optional[dict]:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT data FROM features WHERE stock_id=? ORDER BY trade_date DESC LIMIT 1",
            [stock_id],
        ).fetchone()
        if not row:
            return None
        return json.loads(row[0])


def _get_latest_indicators(db: SignalDB, stock_id: str) -> Optional[dict]:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT ma5, ma20, ma60, rsi14, bb_upper, bb_middle, bb_lower, "
            "volume_ma5, volume_ma20 FROM tech_indicators "
            "WHERE stock_id=? ORDER BY trade_date DESC LIMIT 1",
            [stock_id],
        ).fetchone()
        if not row:
            return None
        keys = ["ma5", "ma20", "ma60", "rsi14", "bb_upper", "bb_middle", "bb_lower",
                "volume_ma5", "volume_ma20"]
        return dict(zip(keys, row))


def _get_institutional_5d(db: SignalDB, stock_id: str) -> Optional[dict]:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT foreign_investors_net, sity_investors_net FROM institutional_flows "
            "WHERE stock_id=? ORDER BY trade_date DESC LIMIT 5",
            [stock_id],
        ).fetchall()
        if not rows or len(rows) < 5:
            return None
        foreign_5d = sum(r[0] or 0 for r in rows)
        sity_5d = sum(r[1] or 0 for r in rows)
        vol_ma20_row = conn.execute(
            "SELECT volume_ma20 FROM tech_indicators WHERE stock_id=? ORDER BY trade_date DESC LIMIT 1",
            [stock_id],
        ).fetchone()
        vol_ma20 = (vol_ma20_row[0] or 1) if vol_ma20_row else 1
        return {
            "foreign_5d_sum": foreign_5d,
            "sity_5d_sum": sity_5d,
            "volume_ma20": vol_ma20,
        }


def _get_historical_eps(db: SignalDB, stock_id: str, lookback: int = 252) -> list[float]:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT data FROM features WHERE stock_id=? ORDER BY trade_date DESC LIMIT ?",
            [stock_id, lookback + 10],
        ).fetchall()
        eps_values = []
        for (raw,) in rows:
            d = json.loads(raw)
            pe = _safe(d.get("pe_ratio"))
            close = _safe(d.get("close"))
            if pe and close and pe > 0:
                eps_values.append(close / pe)
    return eps_values


def _get_yf_quarterly_snapshot(stock_id: str) -> Optional[dict]:
    """Fetch quarterly financials from yfinance and compute YoY changes.

    Returns:
      {
        "latest_date": "2026-03-31",
        "latest_eps": 7.9,
        "prev_eps": 3.93,
        "eps_growth": 1.01,
        "latest_revenue": 124035086000.0,
        "prev_revenue": 118919406000.0,
        "revenue_growth": 0.043,
        "latest_gross_margin": 35.51,
        "prev_gross_margin": 31.77,
        "margin_change": 3.74,
      }
    """
    try:
        ticker = yf.Ticker(f"{stock_id}.TW")
        qf = ticker.quarterly_financials
    except Exception:
        return None
    if qf is None or qf.empty:
        return None

    def _get_series(name: str):
        if name not in qf.index:
            return None
        s = qf.loc[name]
        return [(d, v) for d, v in s.items() if v is not None and (isinstance(v, float) and not math.isnan(v))]

    def _find_yoy(series, get_quarter_fn):
        sorted_vals = sorted(series, key=lambda x: x[0], reverse=True)
        for i, (d, v) in enumerate(sorted_vals):
            q = get_quarter_fn(d)
            for d2, v2 in sorted_vals[i + 1:]:
                if get_quarter_fn(d2) == q and d2.year == d.year - 1:
                    return v, v2, d
        return None

    def _quarter(d):
        return d.quarter

    result = {}

    # EPS
    eps_series = _get_series("Diluted EPS")
    if eps_series and len(eps_series) >= 2:
        eps_yoy = _find_yoy(eps_series, _quarter)
        if eps_yoy:
            latest_eps, prev_eps, latest_date = eps_yoy
            result["latest_date"] = str(latest_date.date())
            result["latest_eps"] = latest_eps
            result["prev_eps"] = prev_eps
            result["eps_growth"] = (latest_eps - prev_eps) / prev_eps

    # Revenue — prefer MOPS monthly revenue over yfinance quarterly
    mops_rev = None
    try:
        from tw_quant_signal.twse_client import fetch_monthly_revenue
        today = date.today()
        mops_rev = fetch_monthly_revenue(stock_id, month=today.month - 1)
        if not mops_rev:
            mops_rev = fetch_monthly_revenue(stock_id, month=today.month - 2)
    except Exception:
        pass
    if mops_rev and mops_rev.get("revenue"):
        result["latest_revenue"] = mops_rev["revenue"] * 1000  # 千元 → 元
        result["prev_revenue"] = mops_rev["prev_year_revenue"] * 1000
        result["revenue_growth"] = mops_rev["yoy_pct"] / 100.0
        result["revenue_source"] = "mops_monthly"
    else:
        rev_series = _get_series("Total Revenue")
        if rev_series and len(rev_series) >= 2:
            rev_yoy = _find_yoy(rev_series, _quarter)
            if rev_yoy:
                latest_rev, prev_rev, _ = rev_yoy
                result["latest_revenue"] = latest_rev
                result["prev_revenue"] = prev_rev
                result["revenue_growth"] = (latest_rev - prev_rev) / prev_rev if prev_rev else None
                result["revenue_source"] = "yfinance_quarterly"

    # Gross Profit
    gp_series = _get_series("Gross Profit")
    rev2 = _get_series("Total Revenue")
    if gp_series and rev2 and len(gp_series) >= 2 and len(rev2) >= 2:
        gp_map = {d.date(): v for d, v in gp_series}
        rev_map = {d.date(): v for d, v in rev2}
        common_dates = sorted(set(gp_map.keys()) & set(rev_map.keys()), reverse=True)
        margins = [(d, gp_map[d] / rev_map[d] * 100) for d in common_dates]
        if len(margins) >= 2:
            result["latest_gross_margin"] = round(margins[0][1], 2)
            result["prev_gross_margin"] = round(margins[1][1], 2)
            result["margin_change"] = round(margins[0][1] - margins[1][1], 2)

    return result if result else None


def _fetch_and_store_financials(db: SignalDB, stock_id: str) -> Optional[dict]:
    existing = db.get_latest_financial_data(stock_id)
    if existing and existing.get("revenue") is not None:
        return existing
    yf_data = fetch_yf_financials(stock_id)
    if yf_data:
        db.upsert_financial_data([yf_data])
    return yf_data


def _fetch_margin_ratio(db: SignalDB, stock_id: str) -> Optional[float]:
    ratio = db.get_latest_margin_ratio(stock_id)
    if ratio is not None:
        return ratio
    all_data = fetch_margin_data()
    if not all_data or not all_data.get(stock_id):
        all_data = fetch_margin_data((date.today() - timedelta(days=1)).isoformat())
    if all_data:
        rows = list(all_data.values())
        db.upsert_margin_data(rows)
    return db.get_latest_margin_ratio(stock_id)


def _score_fundamental(db: SignalDB, stock_id: str) -> dict:
    fin = _fetch_and_store_financials(db, stock_id)
    yf_snap = _get_yf_quarterly_snapshot(stock_id)
    feat = _get_latest_features(db, stock_id)
    close = _safe(feat.get("close")) if feat else None

    # EPS growth
    if yf_snap and "eps_growth" in yf_snap:
        eps_growth = yf_snap["eps_growth"]
        latest_eps = yf_snap["latest_eps"]
        prev_eps = yf_snap["prev_eps"]
    else:
        eps_growth = None
        latest_eps = None
        prev_eps = None
    eps_score = _clamp(50 + (eps_growth or 0) * 100) if eps_growth is not None else 50

    # Revenue YoY
    if yf_snap and "revenue_growth" in yf_snap:
        rev_growth = yf_snap["revenue_growth"]
        latest_rev = yf_snap["latest_revenue"]
        prev_rev = yf_snap["prev_revenue"]
        rev_score = _clamp(50 + (rev_growth or 0) * 100)
    else:
        rev_growth = None
        latest_rev = fin.get("revenue") if fin else None
        prev_rev = None
        raw_rev = latest_rev
        rev_score = _clamp(40 + (raw_rev or 0) / 1e10) if raw_rev is not None else 50

    # Gross margin
    if yf_snap and "margin_change" in yf_snap:
        gross_margin_val = yf_snap["latest_gross_margin"]
        prev_gm = yf_snap["prev_gross_margin"]
        gm_change = yf_snap["margin_change"]
        if gm_change > 3:
            mg_score = 100
        elif gm_change > 0:
            mg_score = 70
        elif gm_change > -3:
            mg_score = 50
        else:
            mg_score = 0
    elif fin:
        gross_margin_val = fin.get("gross_margin")
        prev_gm = None
        gm_change = None
        mg_score = _clamp((gross_margin_val - 15) * 2) if gross_margin_val is not None else 50
    else:
        gross_margin_val = None
        prev_gm = None
        gm_change = None
        mg_score = 50

    weighted = eps_score * 0.40 + rev_score * 0.30 + mg_score * 0.30
    return {
        "score": round(weighted, 2),
        "light": _sub_light(weighted),
        "sub": {
            "eps_growth": {
                "score": round(eps_score, 2), "light": _sub_light(eps_score),
                "value": round(eps_growth * 100, 2) if eps_growth is not None else None,
                "inputs": {
                    "latest_eps": latest_eps,
                    "prev_eps": prev_eps,
                } if latest_eps is not None else None,
            },
            "revenue_yoy": {
                "score": round(rev_score, 2), "light": _sub_light(rev_score),
                "value": round(rev_growth * 100, 2) if rev_growth is not None else (latest_rev if latest_rev else None),
                "inputs": {
                    "latest_revenue": latest_rev,
                    "prev_revenue": prev_rev,
                    "source": yf_snap.get("revenue_source", "yfinance") if yf_snap else "yfinance",
                } if latest_rev is not None else None,
            },
            "gross_margin": {
                "score": round(mg_score, 2), "light": _sub_light(mg_score),
                "value": gross_margin_val,
                "inputs": {
                    "latest_gm": gross_margin_val,
                    "prev_gm": prev_gm,
                } if gross_margin_val is not None else None,
            },
        },
    }


def _score_institutional(db: SignalDB, stock_id: str) -> dict:
    inst = _get_institutional_5d(db, stock_id)
    margin_raw = db.get_latest_margin_raw(stock_id)
    if margin_raw is None:
        margin_ratio = _fetch_margin_ratio(db, stock_id)
    else:
        margin_ratio = margin_raw["margin_ratio"]

    if not inst:
        return {
            "score": 50.0,
            "light": LIGHT_YELLOW,
            "sub": {
                "foreign_ratio": {"score": 50.0, "light": LIGHT_YELLOW, "value": None, "note": "no data"},
                "sity_ratio": {"score": 50.0, "light": LIGHT_YELLOW, "value": None, "note": "no data"},
                "margin_ratio": {"score": _margin_score(margin_ratio), "light": _sub_light(_margin_score(margin_ratio)),
                                 "value": margin_ratio},
            },
        }

    vol_ma20 = inst["volume_ma20"] or 1
    total_vol_5d = vol_ma20 * 5

    foreign_5d_sum = inst["foreign_5d_sum"] or 0
    sity_5d_sum = inst["sity_5d_sum"] or 0
    foreign_ratio = foreign_5d_sum / total_vol_5d if total_vol_5d > 0 else 0
    sity_ratio = sity_5d_sum / total_vol_5d if total_vol_5d > 0 else 0

    if foreign_ratio > 0.10:
        foreign_score = 90
    elif foreign_ratio > 0.05:
        foreign_score = 75
    elif foreign_ratio > 0:
        foreign_score = 55
    elif foreign_ratio > -0.05:
        foreign_score = 40
    else:
        foreign_score = 20

    if sity_ratio > 0.05:
        sity_score = 90
    elif sity_ratio > 0.02:
        sity_score = 75
    elif sity_ratio > 0:
        sity_score = 55
    elif sity_ratio > -0.02:
        sity_score = 40
    else:
        sity_score = 20

    margin_score_val = _margin_score(margin_ratio)

    weighted = foreign_score * 0.40 + sity_score * 0.30 + margin_score_val * 0.30
    return {
        "score": round(weighted, 2),
        "light": _sub_light(weighted),
        "sub": {
            "foreign_ratio": {
                "score": foreign_score, "light": _sub_light(foreign_score),
                "value": round(foreign_ratio * 100, 2),
                "inputs": {"buy_5d": int(foreign_5d_sum), "vol_ma20": int(vol_ma20)},
            },
            "sity_ratio": {
                "score": sity_score, "light": _sub_light(sity_score),
                "value": round(sity_ratio * 100, 2),
                "inputs": {"buy_5d": int(sity_5d_sum), "vol_ma20": int(vol_ma20)},
            },
            "margin_ratio": {
                "score": margin_score_val, "light": _sub_light(margin_score_val),
                "value": margin_ratio,
                "inputs": {
                    "margin_balance": margin_raw["margin_balance"],
                    "short_balance": margin_raw["short_balance"],
                    "margin_balance_unit": "張",
                    "short_balance_unit": "股",
                } if margin_raw else None,
            },
        },
    }


def _margin_score(ratio: Optional[float]) -> float:
    if ratio is None:
        return 50.0
    if ratio < 3:
        return 80
    if ratio < 8:
        return 65
    if ratio < 15:
        return 50
    if ratio < 30:
        return 35
    return 20


def _score_technical(db: SignalDB, stock_id: str, weekly: bool = False) -> dict:
    feat = _get_latest_features(db, stock_id)
    ind = _get_latest_weekly_indicators(db, stock_id) if weekly else _get_latest_indicators(db, stock_id)
    if not ind:
        return {"score": 50.0, "light": LIGHT_YELLOW, "sub": {}}

    if weekly:
        ma5 = _safe(ind.get("ma5"))
        ma20 = _safe(ind.get("ma20"))
        ma60 = _safe(ind.get("ma60"))
        if ma5 is not None and ma20 is not None and ma60 is not None:
            if ma5 > ma20 > ma60:
                ma_align = "bullish"
            elif ma5 < ma20 < ma60:
                ma_align = "bearish"
            else:
                ma_align = "neutral"
        else:
            ma_align = "neutral"
        close = _safe(ind.get("close")) or _safe(feat.get("close")) if feat else None
        bb_lower = _safe(ind.get("bb_lower"))
        bb_upper = _safe(ind.get("bb_upper"))
        bb_mid = _safe(ind.get("bb_middle"))
        if close is not None and bb_lower is not None and bb_mid is not None and bb_upper is not None:
            if close >= bb_upper:
                bb_pos = "above_upper"
            elif close <= bb_lower:
                bb_pos = "below_lower"
            elif close >= bb_mid:
                bb_pos = "above_mid"
            else:
                bb_pos = "below_mid"
        else:
            bb_pos = "mid"
    else:
        if not feat:
            return {"score": 50.0, "light": LIGHT_YELLOW, "sub": {}}
        ma_align = feat.get("ma_alignment", "neutral")
        bb_pos = feat.get("bb_position", "above_mid")
        close = _safe(feat.get("close"))

    ma_align = ma_align or "neutral"
    if ma_align == "bullish":
        ma_score = 85
    elif ma_align == "bearish":
        ma_score = 20
    else:
        ma_score = 50

    rsi = _safe(ind.get("rsi14"))
    if rsi is not None:
        if rsi <= 25:
            rsi_score = 90
        elif rsi <= 35:
            rsi_score = 75
        elif rsi <= 45:
            rsi_score = 45
        elif rsi <= 55:
            rsi_score = 55
        elif rsi <= 65:
            rsi_score = 65
        elif rsi <= 75:
            rsi_score = 35
        else:
            rsi_score = 15
    else:
        rsi_score = 50

    if bb_pos == "below_lower":
        bb_score = 85
    elif bb_pos == "below_mid":
        bb_score = 40
    elif bb_pos in ("above_mid", "mid"):
        bb_score = 60
    elif bb_pos == "above_upper":
        bb_score = 25
    else:
        bb_score = 50

    weighted = ma_score * 0.40 + rsi_score * 0.30 + bb_score * 0.30
    return {
        "score": round(weighted, 2),
        "light": _sub_light(weighted),
        "sub": {
            "ma_alignment": {
                "score": ma_score, "light": _sub_light(ma_score),
                "value": ma_align,
                "inputs": {
                    "ma5": round(_safe(ind.get("ma5")), 2) if ind.get("ma5") else None,
                    "ma20": round(_safe(ind.get("ma20")), 2) if ind.get("ma20") else None,
                    "ma60": round(_safe(ind.get("ma60")), 2) if ind.get("ma60") else None,
                },
            },
            "rsi14": {
                "score": rsi_score, "light": _sub_light(rsi_score),
                "value": rsi,
                "inputs": {"rsi": rsi} if rsi is not None else None,
            },
            "bb_position": {
                "score": bb_score, "light": _sub_light(bb_score),
                "value": bb_pos,
                "inputs": {
                    "close": round(close, 2) if close is not None else None,
                    "bb_upper": round(bb_upper, 2) if bb_upper is not None else None,
                    "bb_middle": round(bb_mid, 2) if bb_mid is not None else None,
                    "bb_lower": round(bb_lower, 2) if bb_lower is not None else None,
                },
            },
        },
    }


def _score_valuation(db: SignalDB, stock_id: str) -> dict:
    feat = _get_latest_features(db, stock_id)
    if not feat:
        return {"score": 50.0, "light": LIGHT_YELLOW, "sub": {}}

    pe_river = feat.get("pe_river", "mid")
    pb_river = feat.get("pb_river", "mid")
    dy = _safe(feat.get("dividend_yield"))
    close = _safe(feat.get("close"))

    if pe_river == "low":
        pe_score = 80
    elif pe_river == "high":
        pe_score = 25
    else:
        pe_score = 50

    if pb_river == "low":
        pb_score = 80
    elif pb_river == "high":
        pb_score = 25
    else:
        pb_score = 50

    if dy is not None:
        if dy >= 0.05:
            dy_score = 80
        elif dy >= 0.03:
            dy_score = 65
        elif dy >= 0.02:
            dy_score = 50
        else:
            dy_score = 30
    else:
        dy_score = 50

    weighted = pe_score * 0.40 + pb_score * 0.30 + dy_score * 0.30
    return {
        "score": round(weighted, 2),
        "light": _sub_light(weighted),
        "sub": {
            "pe_river": {"score": pe_score, "light": _sub_light(pe_score),
                         "value": pe_river},
            "pb_river": {"score": pb_score, "light": _sub_light(pb_score),
                         "value": pb_river},
            "dividend_yield": {
                "score": dy_score, "light": _sub_light(dy_score),
                "value": round(dy * 100, 2) if dy is not None else None,
                "inputs": {"dividend_yield": dy, "close": close} if dy is not None else None,
            },
        },
    }


def _get_latest_weekly_indicators(db: SignalDB, stock_id: str) -> Optional[dict]:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT ma5, ma20, ma60, rsi14, bb_upper, bb_middle, bb_lower, "
            "volume_ma5, volume_ma20 FROM weekly_indicators "
            "WHERE stock_id=? ORDER BY trade_date DESC LIMIT 1",
            [stock_id],
        ).fetchone()
        if not row:
            return None
        keys = ["ma5", "ma20", "ma60", "rsi14", "bb_upper", "bb_middle", "bb_lower",
                "volume_ma5", "volume_ma20"]
        return dict(zip(keys, row))


def _get_latest_monthly_indicators(db: SignalDB, stock_id: str) -> Optional[dict]:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT ma3, ma6, ma12, rsi9, bb_upper, bb_middle, bb_lower, "
            "volume_ma3, volume_ma6 FROM monthly_indicators "
            "WHERE stock_id=? ORDER BY trade_date DESC LIMIT 1",
            [stock_id],
        ).fetchone()
        if not row:
            return None
        keys = ["ma3", "ma6", "ma12", "rsi9", "bb_upper", "bb_middle", "bb_lower",
                "volume_ma3", "volume_ma6"]
        return dict(zip(keys, row))


def compute_health_check_weekly(db: SignalDB, trade_date: Optional[str] = None) -> list[dict]:
    """Weekly-level health check using weekly indicators. Same scoring logic as daily."""
    trade_date = trade_date or date.today().isoformat()
    results = []
    for sid in WATCH_STOCKS:
        fundamental = _score_fundamental(db, sid)
        institutional = _score_institutional(db, sid)
        technical = _score_technical(db, sid, weekly=True)
        valuation = _score_valuation(db, sid)

        total = (fundamental["score"] * 0.25 + institutional["score"] * 0.25 +
                 technical["score"] * 0.25 + valuation["score"] * 0.25)

        results.append({
            "stock_id": sid,
            "trade_date": trade_date,
            "fundamental_score": fundamental["score"],
            "fundamental_light": fundamental["light"],
            "institutional_score": institutional["score"],
            "institutional_light": institutional["light"],
            "technical_score": technical["score"],
            "technical_light": technical["light"],
            "valuation_score": valuation["score"],
            "valuation_light": valuation["light"],
            "total_score": round(total, 2),
            "total_light": _total_light(total),
            "details": {
                "fundamental": fundamental,
                "institutional": institutional,
                "technical": technical,
                "valuation": valuation,
            },
        })
    return results


def _score_technical_monthly(db: SignalDB, stock_id: str) -> dict:
    """Monthly-level technical scoring using monthly indicators.

    Uses MA3 (3 months), MA6 (6 months), MA12 (12 months) for alignment,
    RSI(9) for monthly momentum, BB(6) for position.
    """
    ind = _get_latest_monthly_indicators(db, stock_id)
    if not ind:
        return {"score": 50.0, "light": LIGHT_YELLOW, "sub": {}}

    ma3 = _safe(ind.get("ma3"))
    ma6 = _safe(ind.get("ma6"))
    ma12 = _safe(ind.get("ma12"))
    if ma3 is not None and ma6 is not None and ma12 is not None:
        if ma3 > ma6 > ma12:
            ma_align = "bullish"
        elif ma3 < ma6 < ma12:
            ma_align = "bearish"
        else:
            ma_align = "neutral"
    else:
        ma_align = "neutral"

    close = _safe(ind.get("close"))
    bb_lower = _safe(ind.get("bb_lower"))
    bb_upper = _safe(ind.get("bb_upper"))
    bb_mid = _safe(ind.get("bb_middle"))
    if close is not None and bb_lower is not None and bb_mid is not None and bb_upper is not None:
        if close >= bb_upper:
            bb_pos = "above_upper"
        elif close <= bb_lower:
            bb_pos = "below_lower"
        elif close >= bb_mid:
            bb_pos = "above_mid"
        else:
            bb_pos = "below_mid"
    else:
        bb_pos = "mid"

    if ma_align == "bullish":
        ma_score = 85
    elif ma_align == "bearish":
        ma_score = 20
    else:
        ma_score = 50

    rsi = _safe(ind.get("rsi9"))
    if rsi is not None:
        if rsi <= 25:
            rsi_score = 90
        elif rsi <= 35:
            rsi_score = 75
        elif rsi <= 45:
            rsi_score = 45
        elif rsi <= 55:
            rsi_score = 55
        elif rsi <= 65:
            rsi_score = 65
        elif rsi <= 75:
            rsi_score = 35
        else:
            rsi_score = 15
    else:
        rsi_score = 50

    if bb_pos == "below_lower":
        bb_score = 85
    elif bb_pos == "below_mid":
        bb_score = 40
    elif bb_pos in ("above_mid", "mid"):
        bb_score = 60
    elif bb_pos == "above_upper":
        bb_score = 25
    else:
        bb_score = 50

    weighted = ma_score * 0.40 + rsi_score * 0.30 + bb_score * 0.30
    return {
        "score": round(weighted, 2),
        "light": _sub_light(weighted),
        "sub": {
            "ma_alignment": {
                "score": ma_score, "light": _sub_light(ma_score),
                "value": ma_align,
                "inputs": {
                    "ma3": round(_safe(ind.get("ma3")), 2) if ind.get("ma3") else None,
                    "ma6": round(_safe(ind.get("ma6")), 2) if ind.get("ma6") else None,
                    "ma12": round(_safe(ind.get("ma12")), 2) if ind.get("ma12") else None,
                },
            },
            "rsi9": {
                "score": rsi_score, "light": _sub_light(rsi_score),
                "value": rsi,
                "inputs": {"rsi9": rsi} if rsi is not None else None,
            },
            "bb_position": {
                "score": bb_score, "light": _sub_light(bb_score),
                "value": bb_pos,
                "inputs": {
                    "close": round(close, 2) if close is not None else None,
                    "bb_upper": round(bb_upper, 2) if bb_upper is not None else None,
                    "bb_middle": round(bb_mid, 2) if bb_mid is not None else None,
                    "bb_lower": round(bb_lower, 2) if bb_lower is not None else None,
                },
            },
        },
    }


def compute_health_check_monthly(db: SignalDB, trade_date: Optional[str] = None) -> list[dict]:
    """Monthly-level health check using monthly indicators.

    Fundametal (quarterly same across timeframes) and institutional (daily) data
    remain unchanged; technical aspect uses monthly MA3/6/12, BB(6), RSI(9).
    """
    trade_date = trade_date or date.today().isoformat()
    results = []
    for sid in WATCH_STOCKS:
        fundamental = _score_fundamental(db, sid)
        institutional = _score_institutional(db, sid)
        technical = _score_technical_monthly(db, sid)
        valuation = _score_valuation(db, sid)

        total = (fundamental["score"] * 0.25 + institutional["score"] * 0.25 +
                 technical["score"] * 0.25 + valuation["score"] * 0.25)

        results.append({
            "stock_id": sid,
            "trade_date": trade_date,
            "fundamental_score": fundamental["score"],
            "fundamental_light": fundamental["light"],
            "institutional_score": institutional["score"],
            "institutional_light": institutional["light"],
            "technical_score": technical["score"],
            "technical_light": technical["light"],
            "valuation_score": valuation["score"],
            "valuation_light": valuation["light"],
            "total_score": round(total, 2),
            "total_light": _total_light(total),
            "details": {
                "fundamental": fundamental,
                "institutional": institutional,
                "technical": technical,
                "valuation": valuation,
            },
        })
    return results


def compute_health_check(db: SignalDB, trade_date: Optional[str] = None, weekly: bool = False) -> list[dict]:
    trade_date = trade_date or date.today().isoformat()
    mstate = detect_market_state(db, trade_date)["state"]
    results = []
    for sid in WATCH_STOCKS:
        fundamental = _score_fundamental(db, sid)
        institutional = _score_institutional(db, sid)
        technical = _score_technical(db, sid)
        valuation = _score_valuation(db, sid)

        total = (fundamental["score"] * 0.25 + institutional["score"] * 0.25 +
                 technical["score"] * 0.25 + valuation["score"] * 0.25)
        if mstate == "bull":
            total = total * 0.9 + max(total, fundamental["score"]) * 0.1
        elif mstate == "bear":
            total = total * 0.9 + max(total, valuation["score"]) * 0.1

        results.append({
            "stock_id": sid,
            "trade_date": trade_date,
            "fundamental_score": fundamental["score"],
            "fundamental_light": fundamental["light"],
            "institutional_score": institutional["score"],
            "institutional_light": institutional["light"],
            "technical_score": technical["score"],
            "technical_light": technical["light"],
            "valuation_score": valuation["score"],
            "valuation_light": valuation["light"],
            "total_score": round(total, 2),
            "total_light": _total_light(total),
            "details": {
                "fundamental": fundamental,
                "institutional": institutional,
                "technical": technical,
                "valuation": valuation,
            },
        })
    return results
