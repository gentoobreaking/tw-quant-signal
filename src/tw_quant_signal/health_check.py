import json
from datetime import date, timedelta
from typing import Optional

import pandas as pd

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


def _compute_eps_yoy_growth(db: SignalDB, stock_id: str) -> Optional[float]:
    eps_hist = _get_historical_eps(db, stock_id, lookback=365)
    if len(eps_hist) < 60:
        return None
    current_eps = eps_hist[0]
    target_idx = min(251, len(eps_hist) - 1)
    year_ago_eps = eps_hist[target_idx]
    if not year_ago_eps or year_ago_eps <= 0:
        return None
    return (current_eps - year_ago_eps) / year_ago_eps


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
    eps_growth = _compute_eps_yoy_growth(db, stock_id)
    fin = _fetch_and_store_financials(db, stock_id)

    gross_margin_val = None
    rev = None
    if fin:
        gross_margin_val = fin.get("gross_margin")
        rev = fin.get("revenue")
        eps_fin = fin.get("eps")
        if eps_fin is not None and eps_growth is None:
            eps_growth = (eps_fin / 8.0 - 1) if eps_fin else None

    eps_score = _clamp(50 + (eps_growth or 0) * 100) if eps_growth is not None else 50

    if rev is not None:
        rev_score = _clamp(40 + rev / 1e10)
    else:
        rev_score = 50

    if gross_margin_val is not None:
        mg_score = _clamp((gross_margin_val - 15) * 2)
    else:
        mg_score = 50

    weighted = eps_score * 0.40 + rev_score * 0.30 + mg_score * 0.30
    return {
        "score": round(weighted, 2),
        "light": _sub_light(weighted),
        "sub": {
            "eps_growth": {"score": round(eps_score, 2), "light": _sub_light(eps_score),
                           "value": round(eps_growth * 100, 2) if eps_growth is not None else None},
            "revenue_yoy": {"score": round(rev_score, 2), "light": _sub_light(rev_score),
                            "value": rev, "note": "yfinance quarterly"},
            "gross_margin": {"score": round(mg_score, 2), "light": _sub_light(mg_score),
                             "value": gross_margin_val, "note": "yfinance quarterly"},
        },
    }


def _score_institutional(db: SignalDB, stock_id: str) -> dict:
    inst = _get_institutional_5d(db, stock_id)
    margin_ratio = _fetch_margin_ratio(db, stock_id)

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

    foreign_ratio = (inst["foreign_5d_sum"] or 0) / total_vol_5d if total_vol_5d > 0 else 0
    sity_ratio = (inst["sity_5d_sum"] or 0) / total_vol_5d if total_vol_5d > 0 else 0

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
            "foreign_ratio": {"score": foreign_score, "light": _sub_light(foreign_score),
                              "value": round(foreign_ratio * 100, 2)},
            "sity_ratio": {"score": sity_score, "light": _sub_light(sity_score),
                           "value": round(sity_ratio * 100, 2)},
            "margin_ratio": {"score": margin_score_val, "light": _sub_light(margin_score_val),
                             "value": margin_ratio},
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


def _score_technical(db: SignalDB, stock_id: str) -> dict:
    feat = _get_latest_features(db, stock_id)
    ind = _get_latest_indicators(db, stock_id)
    if not feat or not ind:
        return {"score": 50.0, "light": LIGHT_YELLOW, "sub": {}}

    ma_align = feat.get("ma_alignment", "neutral")
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

    bb_pos = feat.get("bb_position", "above_mid")
    close = _safe(feat.get("close"))
    bb_lower = _safe(ind.get("bb_lower"))
    bb_upper = _safe(ind.get("bb_upper"))
    bb_mid = _safe(ind.get("bb_middle"))
    if close is not None and bb_lower is not None and bb_mid is not None and bb_upper is not None:
        if close <= bb_lower:
            bb_score = 85
        elif close <= bb_mid:
            bb_score = 40
        elif close <= bb_upper:
            bb_score = 60
        else:
            bb_score = 25
    else:
        bb_score = 50

    weighted = ma_score * 0.40 + rsi_score * 0.30 + bb_score * 0.30
    return {
        "score": round(weighted, 2),
        "light": _sub_light(weighted),
        "sub": {
            "ma_alignment": {"score": ma_score, "light": _sub_light(ma_score),
                             "value": ma_align},
            "rsi14": {"score": rsi_score, "light": _sub_light(rsi_score),
                      "value": rsi},
            "bb_position": {"score": bb_score, "light": _sub_light(bb_score),
                            "value": bb_pos},
        },
    }


def _score_valuation(db: SignalDB, stock_id: str) -> dict:
    feat = _get_latest_features(db, stock_id)
    if not feat:
        return {"score": 50.0, "light": LIGHT_YELLOW, "sub": {}}

    pe_river = feat.get("pe_river", "mid")
    pb_river = feat.get("pb_river", "mid")
    dy = _safe(feat.get("dividend_yield"))

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
            "dividend_yield": {"score": dy_score, "light": _sub_light(dy_score),
                               "value": round(dy * 100, 2) if dy is not None else None},
        },
    }


def compute_health_check(db: SignalDB, trade_date: Optional[str] = None) -> list[dict]:
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
