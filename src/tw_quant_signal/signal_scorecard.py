"""T015 — 11 大指標多空訊號計分卡（signal scorecard）。

基於「條件符合計數」的個股多空訊號預覽：不依賴權重，純標記式
符合/不符合，計算 11 大多方指標與 11 大空方指標的符合數（x/11）。

對應規格：signal.md / tw-stock-ai-signal-spec-v1.2.md §3.4
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Optional

from tw_quant_signal.db import SignalDB


# ---------------------------------------------------------------------------
# 指標定義（顯示用 meta：名稱 + 類別）
# ---------------------------------------------------------------------------

BULLISH_META = [
    ("high_240d",        "創 240 日新高",       "價量面"),
    ("inst_3d_buy",      "三大法人連續 3 日買超", "籌碼面"),
    ("foreign_buy_500",  "外資買超 > 500 張",    "籌碼面"),
    ("foreign_3d_buy",   "外資連買 3 日",        "籌碼面"),
    ("sity_buy_500",     "投信買超 > 500 張",    "籌碼面"),
    ("sity_3d_buy",      "投信連買 3 日",        "籌碼面"),
    ("proprietary_3d_buy", "主力連買 3 日",      "籌碼面"),
    ("red_3d",           "連 3 日收紅 K 棒",     "技術面"),
    ("above_ma20",       "站上月線",            "技術面"),
    ("revenue_yoy_up",   "月營收成長 > 10%",     "財務面"),
    ("revenue_mom_up2",  "月營收連續成長",       "財務面"),
]

BEARISH_META = [
    ("low_240d",         "創 240 日新低",       "價量面"),
    ("inst_3d_sell",     "三大法人連續 3 日賣超", "籌碼面"),
    ("foreign_sell_500", "外資賣超 > 500 張",    "籌碼面"),
    ("foreign_3d_sell",  "外資連賣 3 日",        "籌碼面"),
    ("sity_sell_500",    "投信賣超 > 500 張",    "籌碼面"),
    ("sity_3d_sell",     "投信連賣 3 日",        "籌碼面"),
    ("proprietary_3d_sell", "主力連賣 3 日",     "籌碼面"),
    ("black_3d",         "連 3 日收黑 K 棒",     "技術面"),
    ("below_ma20",       "跌破月線",            "技術面"),
    ("revenue_yoy_down", "月營收負成長 > 10%",   "財務面"),
    ("revenue_mom_down2", "月營收連續負成長",    "財務面"),
]

BULLISH_KEYS = [k for k, _, _ in BULLISH_META]
BEARISH_KEYS = [k for k, _, _ in BEARISH_META]


# ---------------------------------------------------------------------------
# 資料輔助
# ---------------------------------------------------------------------------

def _latest_trade_date(db: SignalDB) -> Optional[str]:
    """取得 daily_prices 中最新交易日（預設回推日）。"""
    with db.connect() as conn:
        r = conn.execute(
            "SELECT MAX(trade_date) FROM daily_prices"
        ).fetchone()
    return r[0] if r and r[0] else None


def _get_recent_inst_flows(db: SignalDB, stock_id: str, limit: int = 5):
    """回傳最近 N 筆法人買賣超（由近至遠）。"""
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT trade_date, foreign_investors_net, sity_investors_net,
                      dealer_net
               FROM institutional_flows
               WHERE stock_id=? ORDER BY trade_date DESC LIMIT ?""",
            [stock_id, limit],
        ).fetchall()
    return [dict(r) for r in rows]


def _get_recent_prices(db: SignalDB, stock_id: str, limit: int = 260):
    """回傳最近 N 筆日 K（由近至遠，含 open/high/low/close）。"""
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT trade_date, open, high, low, close
               FROM daily_prices WHERE stock_id=?
               ORDER BY trade_date DESC LIMIT ?""",
            [stock_id, limit],
        ).fetchall()
    return [dict(r) for r in rows]


def _get_latest_ma20(db: SignalDB, stock_id: str, trade_date: str) -> Optional[float]:
    """取得指定交易日的 ma20（tech_indicators）。"""
    with db.connect() as conn:
        r = conn.execute(
            """SELECT ma20 FROM tech_indicators
               WHERE stock_id=? AND trade_date<=?
               ORDER BY trade_date DESC LIMIT 1""",
            [stock_id, trade_date],
        ).fetchone()
    return r[0] if r else None


def _get_recent_monthly_revenue(db: SignalDB, stock_id: str, limit: int = 3):
    """回傳最近 N 筆月營收（由近至遠）。"""
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT year_month, revenue, mom_change, yoy_change
               FROM monthly_revenue WHERE stock_id=?
               ORDER BY year_month DESC LIMIT ?""",
            [stock_id, limit],
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# 多方指標計算
# ---------------------------------------------------------------------------

def _check_high_240d(recent_prices: list[dict]) -> bool:
    """創 240 日新高：最新收盤 ≥ 過去 240 日最高價。"""
    if len(recent_prices) < 2:
        return False
    latest_close = recent_prices[0]["close"]
    if latest_close is None:
        return False
    prev_highs = [p["high"] for p in recent_prices[1:] if p["high"] is not None]
    if not prev_highs:
        return False
    return latest_close >= max(prev_highs)


def _check_inst_3d_buy(inst_rows: list[dict]) -> bool:
    """三大法人連續 3 日買超：過去 3 日外資/投信/自營皆 > 0。"""
    if len(inst_rows) < 3:
        return False
    return all(
        r["foreign_investors_net"] is not None and r["foreign_investors_net"] > 0
        and r["sity_investors_net"] is not None and r["sity_investors_net"] > 0
        and r["dealer_net"] is not None and r["dealer_net"] > 0
        for r in inst_rows[:3]
    )


def _check_foreign_buy_500(inst_rows: list[dict]) -> bool:
    """外資買超 > 500 張（當日）。"""
    if not inst_rows:
        return False
    v = inst_rows[0].get("foreign_investors_net")
    return v is not None and v > 500


def _check_foreign_3d_buy(inst_rows: list[dict]) -> bool:
    """外資連續 3 日買超。"""
    if len(inst_rows) < 3:
        return False
    return all(
        r["foreign_investors_net"] is not None and r["foreign_investors_net"] > 0
        for r in inst_rows[:3]
    )


def _check_sity_buy_500(inst_rows: list[dict]) -> bool:
    """投信買超 > 500 張（當日）。"""
    if not inst_rows:
        return False
    v = inst_rows[0].get("sity_investors_net")
    return v is not None and v > 500


def _check_sity_3d_buy(inst_rows: list[dict]) -> bool:
    """投信連續 3 日買超。"""
    if len(inst_rows) < 3:
        return False
    return all(
        r["sity_investors_net"] is not None and r["sity_investors_net"] > 0
        for r in inst_rows[:3]
    )


def _check_proprietary_3d_buy(inst_rows: list[dict]) -> bool:
    """主力（自營商）連續 3 日買超。"""
    if len(inst_rows) < 3:
        return False
    return all(
        r["dealer_net"] is not None and r["dealer_net"] > 0
        for r in inst_rows[:3]
    )


def _check_red_3d(recent_prices: list[dict]) -> bool:
    """連 3 日收紅 K：最近 3 日皆 close > open。"""
    if len(recent_prices) < 3:
        return False
    return all(
        p["close"] is not None and p["open"] is not None and p["close"] > p["open"]
        for p in recent_prices[:3]
    )


def _check_above_ma20(recent_prices: list[dict], ma20: Optional[float]) -> bool:
    """站上月線：最新收盤 > ma20。"""
    if not recent_prices or ma20 is None:
        return False
    close = recent_prices[0]["close"]
    return close is not None and close > ma20


def _check_revenue_yoy_up(rev_rows: list[dict]) -> bool:
    """月營收成長 > 10%：最新月 yoy_change > 10。"""
    if not rev_rows:
        return False
    yoy = rev_rows[0].get("yoy_change")
    return yoy is not None and yoy > 10


def _check_revenue_mom_up2(rev_rows: list[dict]) -> bool:
    """月營收連續成長：最近兩筆 mom_change 皆 > 0。"""
    if len(rev_rows) < 2:
        return False
    m1 = rev_rows[0].get("mom_change")
    m2 = rev_rows[1].get("mom_change")
    return m1 is not None and m2 is not None and m1 > 0 and m2 > 0


# ---------------------------------------------------------------------------
# 空方指標計算
# ---------------------------------------------------------------------------

def _check_low_240d(recent_prices: list[dict]) -> bool:
    """創 240 日新低：最新收盤 ≤ 過去 240 日最低價。"""
    if len(recent_prices) < 2:
        return False
    latest_close = recent_prices[0]["close"]
    if latest_close is None:
        return False
    prev_lows = [p["low"] for p in recent_prices[1:] if p["low"] is not None]
    if not prev_lows:
        return False
    return latest_close <= min(prev_lows)


def _check_inst_3d_sell(inst_rows: list[dict]) -> bool:
    """三大法人連續 3 日賣超。"""
    if len(inst_rows) < 3:
        return False
    return all(
        r["foreign_investors_net"] is not None and r["foreign_investors_net"] < 0
        and r["sity_investors_net"] is not None and r["sity_investors_net"] < 0
        and r["dealer_net"] is not None and r["dealer_net"] < 0
        for r in inst_rows[:3]
    )


def _check_foreign_sell_500(inst_rows: list[dict]) -> bool:
    """外資賣超 > 500 張（當日）。"""
    if not inst_rows:
        return False
    v = inst_rows[0].get("foreign_investors_net")
    return v is not None and v < -500


def _check_foreign_3d_sell(inst_rows: list[dict]) -> bool:
    """外資連續 3 日賣超。"""
    if len(inst_rows) < 3:
        return False
    return all(
        r["foreign_investors_net"] is not None and r["foreign_investors_net"] < 0
        for r in inst_rows[:3]
    )


def _check_sity_sell_500(inst_rows: list[dict]) -> bool:
    """投信賣超 > 500 張（當日）。"""
    if not inst_rows:
        return False
    v = inst_rows[0].get("sity_investors_net")
    return v is not None and v < -500


def _check_sity_3d_sell(inst_rows: list[dict]) -> bool:
    """投信連續 3 日賣超。"""
    if len(inst_rows) < 3:
        return False
    return all(
        r["sity_investors_net"] is not None and r["sity_investors_net"] < 0
        for r in inst_rows[:3]
    )


def _check_proprietary_3d_sell(inst_rows: list[dict]) -> bool:
    """主力（自營商）連續 3 日賣超。"""
    if len(inst_rows) < 3:
        return False
    return all(
        r["dealer_net"] is not None and r["dealer_net"] < 0
        for r in inst_rows[:3]
    )


def _check_black_3d(recent_prices: list[dict]) -> bool:
    """連 3 日收黑 K：最近 3 日皆 close < open。"""
    if len(recent_prices) < 3:
        return False
    return all(
        p["close"] is not None and p["open"] is not None and p["close"] < p["open"]
        for p in recent_prices[:3]
    )


def _check_below_ma20(recent_prices: list[dict], ma20: Optional[float]) -> bool:
    """跌破月線：最新收盤 < ma20。"""
    if not recent_prices or ma20 is None:
        return False
    close = recent_prices[0]["close"]
    return close is not None and close < ma20


def _check_revenue_yoy_down(rev_rows: list[dict]) -> bool:
    """月營收負成長 > 10%：最新月 yoy_change < -10。"""
    if not rev_rows:
        return False
    yoy = rev_rows[0].get("yoy_change")
    return yoy is not None and yoy < -10


def _check_revenue_mom_down2(rev_rows: list[dict]) -> bool:
    """月營收連續負成長：最近兩筆 mom_change 皆 < 0。"""
    if len(rev_rows) < 2:
        return False
    m1 = rev_rows[0].get("mom_change")
    m2 = rev_rows[1].get("mom_change")
    return m1 is not None and m2 is not None and m1 < 0 and m2 < 0


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def compute_scorecard(db: SignalDB, stock_id: str, trade_date: str = None) -> dict:
    """計算單一標的之多空計分卡。

    Args:
        db: SignalDB
        stock_id: 標的代號
        trade_date: 指定交易日（預設 daily_prices 最新日）

    Returns:
        dict:
        {
          "stock_id": ...,
          "trade_date": ...,
          "bullish": {11 個 boolean + count + ratio},
          "bearish": {11 個 boolean + count + ratio},
        }
    """
    if trade_date is None:
        trade_date = _latest_trade_date(db)
    if trade_date is None:
        return {"stock_id": stock_id, "trade_date": None,
                "bullish": {"count": 0, "ratio": "0/11"},
                "bearish": {"count": 0, "ratio": "0/11"}}

    # 資料擷取
    recent_prices = _get_recent_prices(db, stock_id, limit=260)
    inst_rows = _get_recent_inst_flows(db, stock_id, limit=5)
    ma20 = _get_latest_ma20(db, stock_id, trade_date)
    rev_rows = _get_recent_monthly_revenue(db, stock_id, limit=3)

    # 多方
    bullish = {
        "high_240d": _check_high_240d(recent_prices),
        "inst_3d_buy": _check_inst_3d_buy(inst_rows),
        "foreign_buy_500": _check_foreign_buy_500(inst_rows),
        "foreign_3d_buy": _check_foreign_3d_buy(inst_rows),
        "sity_buy_500": _check_sity_buy_500(inst_rows),
        "sity_3d_buy": _check_sity_3d_buy(inst_rows),
        "proprietary_3d_buy": _check_proprietary_3d_buy(inst_rows),
        "red_3d": _check_red_3d(recent_prices),
        "above_ma20": _check_above_ma20(recent_prices, ma20),
        "revenue_yoy_up": _check_revenue_yoy_up(rev_rows),
        "revenue_mom_up2": _check_revenue_mom_up2(rev_rows),
    }
    bull_count = sum(1 for v in bullish.values() if v)
    bullish["count"] = bull_count
    bullish["ratio"] = f"{bull_count}/11"

    # 空方
    bearish = {
        "low_240d": _check_low_240d(recent_prices),
        "inst_3d_sell": _check_inst_3d_sell(inst_rows),
        "foreign_sell_500": _check_foreign_sell_500(inst_rows),
        "foreign_3d_sell": _check_foreign_3d_sell(inst_rows),
        "sity_sell_500": _check_sity_sell_500(inst_rows),
        "sity_3d_sell": _check_sity_3d_sell(inst_rows),
        "proprietary_3d_sell": _check_proprietary_3d_sell(inst_rows),
        "black_3d": _check_black_3d(recent_prices),
        "below_ma20": _check_below_ma20(recent_prices, ma20),
        "revenue_yoy_down": _check_revenue_yoy_down(rev_rows),
        "revenue_mom_down2": _check_revenue_mom_down2(rev_rows),
    }
    bear_count = sum(1 for v in bearish.values() if v)
    bearish["count"] = bear_count
    bearish["ratio"] = f"{bear_count}/11"

    return {
        "stock_id": stock_id,
        "trade_date": trade_date,
        "bullish": bullish,
        "bearish": bearish,
    }


def compute_all_scorecards(db: SignalDB, trade_date: str = None) -> list[dict]:
    """計算所有 watch_stocks 的計分卡。"""
    from tw_quant_signal.twse_client import WATCH_STOCKS
    out = []
    for sid in WATCH_STOCKS:
        try:
            sc = compute_scorecard(db, sid, trade_date)
            if sc.get("trade_date"):
                out.append(sc)
        except Exception:
            continue
    return out


def build_scorecard_rows(results: list[dict]) -> list[dict]:
    """將 compute_scorecard 結果轉為 DB 寫入列。"""
    rows = []
    for r in results:
        rows.append({
            "trade_date": r["trade_date"],
            "stock_id": r["stock_id"],
            "bullish_score": r["bullish"]["count"],
            "bearish_score": r["bearish"]["count"],
            "bullish_detail": {k: r["bullish"][k] for k in BULLISH_KEYS},
            "bearish_detail": {k: r["bearish"][k] for k in BEARISH_KEYS},
        })
    return rows


def scorecard_to_markdown(results: list[dict]) -> str:
    """產生計分卡 Markdown 摘要（納入每日報告）。"""
    if not results:
        return ""
    lines = ["## 📊 11 大指標計分卡（x/11）", ""]
    lines.append("| 標的 | 多方 | 空方 | 方向 |")
    lines.append("|------|------|------|------|")
    for r in sorted(results, key=lambda x: x["stock_id"]):
        b = r["bullish"]["count"]
        s = r["bearish"]["count"]
        direction = "🟢 多方" if b > s else ("🔴 空方" if s > b else "⚪ 中性")
        lines.append(f"| {r['stock_id']} | {b}/11 | {s}/11 | {direction} |")
    lines.append("")
    return "\n".join(lines)
