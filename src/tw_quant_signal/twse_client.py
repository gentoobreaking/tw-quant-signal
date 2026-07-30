import os
import re
import time
from datetime import date, datetime, timedelta
from typing import Optional

import pandas as pd
import httpx

from tw_quant_signal.config import settings

TWSE_OPENAPI = os.getenv("TWSE_BASE_URL", "https://openapi.twse.com.tw/v1")
TWSE_RWD = "https://www.twse.com.tw/rwd/zh"
_ROC_EPOCH = 1911

WATCH_STOCKS = settings.watch_stocks


def _roc_to_ad(roc_date: str) -> str:
    year = int(roc_date[:3]) + _ROC_EPOCH
    return f"{year}-{roc_date[3:5]}-{roc_date[5:7]}"


def _safe_float(v) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, str):
        v = v.replace(",", "")
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _safe_int(v) -> Optional[int]:
    if v is None:
        return None
    if isinstance(v, str):
        v = v.replace(",", "")
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


def fetch_daily_prices_all() -> list[dict]:
    url = f"{TWSE_OPENAPI}/exchangeReport/STOCK_DAY_ALL"
    with httpx.Client(timeout=60) as client:
        resp = client.get(url)
        resp.raise_for_status()
        rows = resp.json()
    results = []
    for r in rows:
        code = r.get("Code", "")
        date_str = r.get("Date", "")
        if not code or not date_str:
            continue
        try:
            trade_date = _roc_to_ad(date_str)
        except (ValueError, IndexError):
            continue
        results.append({
            "stock_id": code,
            "trade_date": trade_date,
            "open": _safe_float(r.get("OpeningPrice")),
            "high": _safe_float(r.get("HighestPrice")),
            "low": _safe_float(r.get("LowestPrice")),
            "close": _safe_float(r.get("ClosingPrice")),
            "volume": _safe_int(r.get("TradeVolume")),
            "amount": _safe_float(r.get("TradeValue")),
        })
    return results


def fetch_watch_stocks_prices() -> list[dict]:
    all_data = fetch_daily_prices_all()
    watch_set = set(WATCH_STOCKS)
    return [r for r in all_data if r["stock_id"] in watch_set]


def fetch_market_index() -> Optional[dict]:
    url = f"{TWSE_OPENAPI}/exchangeReport/MI_INDEX"
    with httpx.Client(timeout=30) as client:
        resp = client.get(url)
        resp.raise_for_status()
        data = resp.json()

    if not isinstance(data, list):
        return None

    INDEX_NAME = "發行量加權股價指數"
    row = None
    for r in data:
        if r.get("指數") == INDEX_NAME:
            row = r
            break
    if not row:
        row = data[0] if data else None
    if not row:
        return None

    date_roc = row.get("日期", "")
    trade_date = _roc_to_ad(date_roc) if date_roc and len(date_roc) == 7 else date.today().isoformat()

    close = _safe_float(row.get("收盤指數", "").replace(",", ""))
    change_pct_str = row.get("漲跌百分比", "0").strip()
    change_pct = _safe_float(change_pct_str) if change_pct_str != "-" else None

    return {
        "trade_date": trade_date,
        "close": close,
        "change_pct": change_pct,
    }


def fetch_institutional_flows(trade_date: Optional[str] = None) -> list[dict]:
    raw = trade_date or date.today().isoformat()
    _date = raw.replace("-", "")
    url = f"{TWSE_RWD}/fund/T86?date={_date}&selectType=ALLBUT0999"
    with httpx.Client(timeout=60) as client:
        resp = client.get(url)
        resp.raise_for_status()
        payload = resp.json()
    if payload.get("stat") != "OK":
        return []
    raw_date = payload.get("date", "")
    ad_date = (
        f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}"
        if raw_date and len(raw_date) == 8
        else (trade_date or date.today().isoformat())
    )
    results = []
    for row in payload.get("data", []):
        if not row or len(row) < 19:
            continue
        code = row[0].strip()
        if not code:
            continue
        results.append({
            "stock_id": code,
            "trade_date": ad_date,
            "market": "TSE",
            "foreign_investors_net": _safe_int(row[4].replace(",", "")),
            "sity_investors_net": _safe_int(row[10].replace(",", "")),
            "dealer_net": _safe_int(row[11].replace(",", "")),
            "dealer_proprietary_net": _safe_int(row[14].replace(",", "")),
            "dealer_hedge_net": _safe_int(row[17].replace(",", "")),
            "total_net": _safe_int(row[18].replace(",", "")),
        })
    return results


def fetch_valuations(stock_ids: list[str] = None) -> dict[str, dict]:
    """Fetch PE, PB, dividend yield from TWSE BWIBBU_ALL."""
    url = f"{TWSE_OPENAPI}/exchangeReport/BWIBBU_ALL"
    with httpx.Client(timeout=30) as client:
        resp = client.get(url)
        resp.raise_for_status()
        rows = resp.json()
    result = {}
    for r in rows:
        code = r.get("Code", "")
        date_str = r.get("Date", "")
        if not code or not date_str:
            continue
        try:
            trade_date = _roc_to_ad(date_str)
        except (ValueError, IndexError):
            continue
        if stock_ids and code not in stock_ids:
            continue
        dy = _safe_float(r.get("DividendYield"))
        result[code] = {
            "stock_id": code,
            "trade_date": trade_date,
            "pe_ratio": _safe_float(r.get("PEratio")),
            "pb_ratio": _safe_float(r.get("PBratio")),
            "dividend_yield": dy / 100 if dy else None,
        }
    return result


def _safe_int_stripped(v) -> Optional[int]:
    if v is None:
        return None
    if isinstance(v, str):
        v = v.replace(",", "")
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return None


def fetch_margin_data(trade_date: str = None) -> dict[str, dict]:
    """Fetch margin trading data (融資/融券) from TWSE TWT93U.

    Returns dict keyed by stock_id:
      {stock_id: {"margin_balance": int, "short_balance": int, "margin_ratio": float}}
    Data is T-1 (previous trading day).
    """
    raw = (trade_date or date.today().isoformat()).replace("-", "")
    url = f"{TWSE_RWD.replace('/rwd/zh', '/zh')}/exchangeReport/TWT93U?date={raw}&response=json"
    with httpx.Client(timeout=30) as client:
        resp = client.get(url)
        resp.raise_for_status()
        payload = resp.json()
    if payload.get("stat") != "OK":
        return {}
    rows = payload.get("data", [])
    result = {}
    for r in rows:
        if len(r) < 15:
            continue
        code = r[0].strip()
        if not code:
            continue
        margin_balance = _safe_int_stripped(r[6])  # 今日餘額(融資) in 張
        short_balance = _safe_int_stripped(r[12])  # 當日餘額(融券) in 股
        ratio = None
        if margin_balance and margin_balance > 0 and short_balance is not None:
            ratio = round(short_balance / (margin_balance * 1000) * 100, 2)
        result[code] = {
            "stock_id": code,
            "trade_date": raw[:4] + "-" + raw[4:6] + "-" + raw[6:8],
            "margin_balance": margin_balance,
            "short_balance": short_balance,
            "margin_ratio": ratio,
        }
    return result


def fetch_monthly_revenue(stock_id: str, year: int = None, month: int = None) -> Optional[dict]:
    """Fetch monthly revenue from MOPS ajax_t05st10_ifrs.

    Returns:
      {"revenue": int (千元), "prev_year_revenue": int, "yoy_pct": float, "year": int, "month": int}
    """
    from bs4 import BeautifulSoup
    today = date.today()
    year = year or (today.year - 1911)  # ROC year
    month = month or (today.month - 1) or 12
    if month < 1 or month > 12:
        month = today.month - 1 if today.month > 1 else 12
    url = "https://mopsov.twse.com.tw/mops/web/ajax_t05st10_ifrs"
    data = {
        "step": "1", "firstin": "true", "off": "1",
        "TYPEK": "sii", "year": str(year), "month": f"{month:02d}", "co_id": stock_id,
    }
    with httpx.Client(timeout=15) as client:
        resp = client.post(url, data=data)
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")
    tables = soup.find_all("table")
    if len(tables) < 4:
        return None
    rows = tables[3].find_all("tr")
    if len(rows) < 5:
        return None
    def _get_val(row_idx):
        vals = [c.get_text(strip=True).replace(",", "") for c in rows[row_idx].find_all(["td", "th"])]
        return vals[-1] if vals else None  # value is always the last cell
    try:
        revenue = int(_get_val(1))
        prev_revenue = int(_get_val(2))
        yoy_pct = float(_get_val(4))
    except (ValueError, TypeError, IndexError):
        return None
    if not revenue:
        return None
    return {
        "revenue": revenue,
        "prev_year_revenue": prev_revenue,
        "yoy_pct": yoy_pct,
        "year": year + 1911,
        "month": month,
    }


def fetch_yf_financials(stock_id: str) -> Optional[dict]:
    """Fetch quarterly financials from yfinance.

    Returns latest available quarter's data:
      {eps: float, revenue: float, gross_margin: float, fiscal_quarter: str}
    ETFs (e.g. 0050) return None.
    """
    try:
        import yfinance as yf
    except ImportError:
        return None
    try:
        ticker = yf.Ticker(f"{stock_id}.TW")
        fs = ticker.quarterly_financials
        if fs is None or fs.empty:
            return None
        best = None
        best_score = -1
        for col in fs.columns:
            rev = None
            if "Total Revenue" in fs.index:
                v = fs.loc["Total Revenue", col]
                rev = float(v) if not pd.isna(v) else None
            gp = None
            if "Gross Profit" in fs.index:
                v = fs.loc["Gross Profit", col]
                gp = float(v) if not pd.isna(v) else None
            eps = None
            if "Diluted EPS" in fs.index:
                v = fs.loc["Diluted EPS", col]
                eps = float(v) if not pd.isna(v) else None
            score = (1 if rev is not None else 0) + (1 if gp is not None else 0) + (1 if eps is not None else 0)
            if score > best_score:
                best_score = score
                gross_margin = round(gp / rev * 100, 2) if rev and gp and rev > 0 else None
                best = {
                    "stock_id": stock_id,
                    "eps": eps,
                    "revenue": rev,
                    "gross_margin": gross_margin,
                    "fiscal_quarter": str(col)[:7],
                }
            if score == 3:
                break
        return best
    except Exception:
        return None


def fetch_historical_index(years: int = 5) -> list[dict]:
    """Fetch historical TAIEX daily data from Yahoo Finance."""
    try:
        import yfinance as yf
    except ImportError:
        return []
    end = date.today()
    start = end - timedelta(days=years * 365)
    ticker = yf.Ticker("^TWII")
    df = ticker.history(start=start.isoformat(), end=end.isoformat())
    if df.empty:
        return []
    rows = []
    for dt_idx, row in df.iterrows():
        trade_date = dt_idx.strftime("%Y-%m-%d") if hasattr(dt_idx, "strftime") else str(dt_idx)[:10]
        close = float(row["Close"]) if pd.notna(row["Close"]) else None
        rows.append({
            "trade_date": trade_date,
            "close": close,
            "change_pct": None,
        })
    return rows


def fetch_historical_daily_prices(stock_id: str, start_date: str, end_date: str) -> list[dict]:
    """Fetch per-stock historical daily prices from TWSE RWD API.

    Uses: https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY
    Note: date format in URL is ROC calendar (e.g., 1150101 for 2026-01-01)
    """
    results = []
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    cursor = start.replace(day=1)
    while cursor <= end:
        roc_year = cursor.year - _ROC_EPOCH
        month_str = f"{cursor.month:02d}"
        url = f"https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date={roc_year}{month_str}01&stockNo={stock_id}&response=json"
        with httpx.Client(timeout=30) as client:
            try:
                resp = client.get(url)
                resp.raise_for_status()
                payload = resp.json()
            except Exception:
                break
        if payload.get("stat") != "OK":
            break
        for row in payload.get("data", []):
            if len(row) < 8:
                continue
            roc_date = row[0].replace("/", "")
            ad_date = _roc_to_ad(roc_date)
            if ad_date < start_date or ad_date > end_date:
                continue
            results.append({
                "stock_id": stock_id,
                "trade_date": ad_date,
                "volume": _safe_int(row[1].replace(",", "")),
                "amount": _safe_float(row[2].replace(",", "")),
                "open": _safe_float(row[3]),
                "high": _safe_float(row[4]),
                "low": _safe_float(row[5]),
                "close": _safe_float(row[6]),
            })
        next_month = cursor.month + 1
        cursor = cursor.replace(year=cursor.year + next_month // 12, month=(next_month - 1) % 12 + 1)
        time.sleep(0.3)
    return results
