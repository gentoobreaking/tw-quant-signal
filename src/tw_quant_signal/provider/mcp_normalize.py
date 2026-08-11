"""mcp_normalize — MCP Envelope → Python 預期 dict 格式轉換（T021 S4 / T022 S2）。

tw-quant-mcp 回傳的標準 Envelope 為:
    {"data": {...}, "_lineage": {...}, "_chart_meta": {...}, ...}

本模組將 ``data`` 區塊轉換為 tw-quant-signal 各模組預期的 dict 格式，
確保 ``McpDataProvider`` 回傳與 ``TwseDirectProvider`` 完全一致（零行為變更）。

欄位映射（任務書 S4）：
- mcp {symbol, close, open, high, low, volume, timestamp}
    → Python {stock_id, close, open, high, low, volume, trade_date}
- mcp {date, foreign_net_shares, investment_trust_net_shares, dealer_net_shares}
    → Python {trade_date, foreign_investors_net, sity_investors_net, dealer_net}
- mcp {pe, pb, dividend_yield_pct}
    → Python {pe_ratio, pb_ratio, dividend_yield}
"""

from __future__ import annotations


def _pick(data: dict, *keys, default=None):
    """依序嘗試取 key，全部缺失回傳 default。"""
    for k in keys:
        if k in data and data[k] is not None:
            return data[k]
    return default


# --------------------------------------------------------------------- #
# 行情（S2）
# --------------------------------------------------------------------- #
def normalize_daily_quote(data: dict, stock_id: str) -> dict:
    """get_stock_daily_quote 單檔 → daily_prices 列格式。"""
    return {
        "stock_id": stock_id,
        "trade_date": _pick(data, "date", "timestamp", default=""),
        "open": _pick(data, "open"),
        "high": _pick(data, "high"),
        "low": _pick(data, "low"),
        "close": _pick(data, "close"),
        "volume": _pick(data, "volume", "vol"),
        "amount": _pick(data, "amount"),
    }


def normalize_market_index(data: dict) -> dict | None:
    """get_stock_daily_quote("^TWII") / get_market_summary → market_index 列。"""
    if not data:
        return None
    close = _pick(data, "close")
    if close is None:
        return None
    return {
        "trade_date": _pick(data, "date", "timestamp", default=""),
        "close": close,
        "change_pct": _pick(data, "change_pct"),
    }


# --------------------------------------------------------------------- #
# 法人（S2）
# --------------------------------------------------------------------- #
def normalize_institutional_rows(data: dict) -> list[dict]:
    """get_institutional_investors rows → institutional_flows 列。"""
    rows = data.get("rows") or []
    trade_date = data.get("date", "")
    market = data.get("market", "TSE").upper()
    results = []
    for r in rows:
        code = r.get("code", "")
        if not code:
            continue
        results.append({
            "stock_id": code,
            "trade_date": trade_date,
            "market": market,
            "foreign_investors_net": _pick(r, "foreign_net"),
            "sity_investors_net": _pick(r, "investment_net"),
            "dealer_net": _pick(r, "dealer_net"),
            "dealer_proprietary_net": _pick(r, "dealer_self_net"),
            "dealer_hedge_net": _pick(r, "dealer_hedge_net"),
            "total_net": _pick(r, "total_net"),
        })
    return results


# --------------------------------------------------------------------- #
# 估值（S2）
# --------------------------------------------------------------------- #
def normalize_valuation(data: dict, stock_id: str) -> dict:
    """get_valuation_ratios → 估值 dict（與 fetch_valuations 一致）。"""
    dy = data.get("dividend_yield_pct")
    return {
        "stock_id": stock_id,
        "trade_date": _pick(data, "date", default=""),
        "pe_ratio": _pick(data, "pe"),
        "pb_ratio": _pick(data, "pb"),
        "dividend_yield": (dy / 100.0) if dy is not None else None,
    }


# --------------------------------------------------------------------- #
# 融資融券（S2）
# --------------------------------------------------------------------- #
def normalize_margin_trading(data: dict, stock_id: str, trade_date: str = "") -> dict:
    """get_margin_trading → margin_trading 列。"""
    return {
        "stock_id": stock_id,
        "trade_date": _pick(data, "date", default=trade_date),
        "margin_buy": _pick(data, "margin_buy"),
        "margin_sell": _pick(data, "margin_sell"),
        "margin_balance": _pick(data, "margin_balance"),
        "short_sell": _pick(data, "short_sell"),
        "short_buy": _pick(data, "short_buy"),
        "short_balance": _pick(data, "short_balance"),
    }


# --------------------------------------------------------------------- #
# 歷史（S3）
# --------------------------------------------------------------------- #
def normalize_daily_kline(data: list, stock_id: str) -> list[dict]:
    """get_stock_daily_kline Candle[] → daily_prices 列。"""
    results = []
    for c in data or []:
        results.append({
            "stock_id": stock_id,
            "trade_date": c.get("timestamp", ""),
            "open": c.get("open"),
            "high": c.get("high"),
            "low": c.get("low"),
            "close": c.get("close"),
            "volume": c.get("volume"),
            "amount": c.get("amount"),
        })
    return results


def normalize_historical_index(data: list) -> list[dict]:
    """get_stock_daily_kline("^TWII") Candle[] → market_index 列。"""
    results = []
    for c in data or []:
        results.append({
            "trade_date": c.get("timestamp", ""),
            "close": c.get("close"),
            "change_pct": None,
        })
    return results


# --------------------------------------------------------------------- #
# MOPS（T022 S2）
# --------------------------------------------------------------------- #
def normalize_monthly_revenue(data: list, stock_id: str) -> list[dict]:
    """get_monthly_revenue → monthly_revenue 列。"""
    results = []
    for r in data or []:
        results.append({
            "stock_id": stock_id,
            "year_month": r.get("year_month") or r.get("date") or "",
            "revenue": r.get("revenue"),
            "mom_change": r.get("mom_change"),
            "yoy_change": r.get("yoy_change"),
        })
    return results


def normalize_dividends(data: list, stock_id: str) -> list[dict]:
    """get_dividend_history → dividends 表列。"""
    results = []
    for r in data or []:
        year = r.get("year")
        if year is None:
            continue
        results.append({
            "stock_id": stock_id,
            "year": int(year),
            "ex_date": _pick(r, "ex_date", "ex_dividend_date"),
            "close_before_ex": _pick(r, "close_before_ex"),
            "cash_dividend": _pick(r, "cash_dividend", "cash_per_share"),
            "cash_pay_date": _pick(r, "cash_pay_date"),
            "cash_yield": _pick(r, "cash_yield", "yield_pct"),
            "stock_dividend": _pick(r, "stock_dividend", "stock_per_share"),
        })
    return results


def normalize_financials(data: list, stock_id: str) -> list[dict]:
    """get_financial_statements → quarterly_financials 列。"""
    results = []
    for r in data or []:
        fiscal_quarter = r.get("fiscal_quarter") or r.get("period") or r.get("year_month")
        if not fiscal_quarter:
            continue
        results.append({
            "stock_id": stock_id,
            "fiscal_quarter": str(fiscal_quarter),
            "eps": _pick(r, "eps"),
            "revenue": _pick(r, "revenue"),
            "gross_margin": _pick(r, "gross_margin"),
            "roe": _pick(r, "roe"),
            "roa": _pick(r, "roa"),
        })
    return results
