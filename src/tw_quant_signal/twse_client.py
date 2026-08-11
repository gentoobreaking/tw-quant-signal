import asyncio
import os
import re
import time
from datetime import date, datetime, timedelta
from typing import Optional

import pandas as pd
import httpx

from tw_quant_signal.config import settings
# T020: WATCH_STOCKS 規範定義已移至 config.py，此處 re-export 維持向後相容。
from tw_quant_signal.config import WATCH_STOCKS  # noqa: F401

TWSE_OPENAPI = os.getenv("TWSE_BASE_URL", "https://openapi.twse.com.tw/v1")
TWSE_RWD = "https://www.twse.com.tw/rwd/zh"
_ROC_EPOCH = 1911

# WATCH_STOCKS 來自 config.py（見上 import），不再於此重新定義。

# HTTP 重試（T016 §5）：max 3 retry、指數 backoff
RETRY_MAX = 3
RETRY_BACKOFF_BASE = 0.8
RETRY_BACKOFF_MAX = 5.0
_RETRYABLE = (httpx.TimeoutException, httpx.NetworkError, httpx.TransportError, httpx.HTTPStatusError)


def _should_retry(exc: Exception) -> bool:
    """判斷例外是否值得重試（連線/逾時/5xx）。"""
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.NetworkError):
        return True
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return False


def _backoff_delay(attempt: int) -> float:
    return min(RETRY_BACKOFF_BASE * (2 ** attempt), RETRY_BACKOFF_MAX)


def _retry(fn, *args, retries: int = RETRY_MAX, **kwargs):
    """同步 HTTP 重試包裝：最多 retries 次，指數 backoff。"""
    last_exc = None
    for attempt in range(retries):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - 重試層需攔截所有連線例外
            last_exc = exc
            if attempt < retries - 1 and _should_retry(exc):
                time.sleep(_backoff_delay(attempt))
                continue
            raise
    raise last_exc


async def _retry_async(fn, *args, retries: int = RETRY_MAX, **kwargs):
    """非同步 HTTP 重試包裝：最多 retries 次，指數 backoff。"""
    last_exc = None
    for attempt in range(retries):
        try:
            return await fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < retries - 1 and _should_retry(exc):
                await asyncio.sleep(_backoff_delay(attempt))
                continue
            raise
    raise last_exc


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


def _request_json(client: httpx.Client, method: str, url: str, **kwargs) -> dict:
    """以重試包裝執行 HTTP 請求並回傳 JSON。"""
    def _do():
        resp = client.request(method, url, **kwargs)
        resp.raise_for_status()
        return resp.json()
    return _retry(_do)


async def _request_json_async(client: httpx.AsyncClient, method: str, url: str, **kwargs) -> dict:
    """非同步版 _request_json（重試包裝）。"""
    async def _do():
        resp = await client.request(method, url, **kwargs)
        resp.raise_for_status()
        return resp.json()
    return await _retry_async(_do)


def fetch_daily_prices_all() -> list[dict]:
    url = f"{TWSE_OPENAPI}/exchangeReport/STOCK_DAY_ALL"
    with httpx.Client(timeout=60) as client:
        rows = _request_json(client, "GET", url)
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
        data = _request_json(client, "GET", url)

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
        payload = _request_json(client, "GET", url)
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
    """Fetch PE, PB, dividend yield from TWSE BWIBBU_ALL.

    僅回傳指定股票（或全體）之估值，供保留相容性（T016 §2 已將
    管線內重複呼叫抽至 ingestion 層一次拉取）。
    """
    with httpx.Client(timeout=30) as client:
        rows = _request_json(client, "GET", f"{TWSE_OPENAPI}/exchangeReport/BWIBBU_ALL")
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


def fetch_valuations_all() -> dict[str, dict]:
    """一次拉取全體上市股票估值（T016 §2：消除 per-stock 重複呼叫）。"""
    return fetch_valuations(stock_ids=None)


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
        payload = _request_json(client, "GET", url)
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


def fetch_margin_trading_detailed(trade_date: str = None) -> list[dict]:
    """Fetch detailed margin trading (融資融券買賣明細) from TWSE TWT93U.

    Returns list with per-stock detail:
      {stock_id, trade_date, margin_buy, margin_sell, margin_balance,
       short_sell, short_buy, short_balance}
    """
    raw = (trade_date or date.today().isoformat()).replace("-", "")
    url = f"{TWSE_RWD.replace('/rwd/zh', '/zh')}/exchangeReport/TWT93U?date={raw}&response=json"
    with httpx.Client(timeout=30) as client:
        payload = _request_json(client, "GET", url)
    if payload.get("stat") != "OK":
        return []
    rows = payload.get("data", [])
    trade_date_str = raw[:4] + "-" + raw[4:6] + "-" + raw[6:8]
    result = []
    for r in rows:
        if len(r) < 15:
            continue
        code = r[0].strip()
        if not code:
            continue
        result.append({
            "stock_id": code,
            "trade_date": trade_date_str,
            "margin_buy": _safe_int_stripped(r[2]),
            "margin_sell": _safe_int_stripped(r[3]),
            "margin_balance": _safe_int_stripped(r[6]),
            "short_sell": _safe_int_stripped(r[9]),
            "short_buy": _safe_int_stripped(r[8]),
            "short_balance": _safe_int(r[12]),
        })
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


_MOPS_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    "Referer": "https://mopsov.twse.com.tw/mops/web/t05st10_ifrs",
}
_MOPS_ENTRY = "https://mopsov.twse.com.tw/mops/web/t05st10_ifrs"
_MOPS_AJAX = "https://mopsov.twse.com.tw/mops/web/ajax_t05st10_ifrs"
_MOPS_CONCURRENCY = 3  # T016 §3：並行度 3（規範 3–5），單股票批次內併發；不跨股票平行


def _monthly_rev_months(months: int, ref: date = None) -> list[tuple[int, int, int]]:
    """回傳 [(roc_year, ad_year, month), ...] 由近至遠，共 months 個月。"""
    ref = ref or date.today()
    out = []
    seen = set()
    for offset in range(months):
        m = ref.month - offset
        y = ref.year
        while m < 1:
            m += 12
            y -= 1
        roc_year = y - 1911
        if roc_year < 100:
            continue
        key = (y, m)
        if key in seen:
            continue
        seen.add(key)
        out.append((roc_year, y, m))
    return out


def _parse_mops_monthly_table(soup) -> Optional[dict]:
    """從 MOPS 回應解析單月營收（revenue / prev_year_revenue / yoy_pct）。"""
    tables = soup.find_all("table")
    if len(tables) < 4:
        return None
    trs = tables[3].find_all("tr")
    if len(trs) < 5:
        return None

    def _get_val(row_idx):
        vals = [c.get_text(strip=True).replace(",", "") for c in trs[row_idx].find_all(["td", "th"])]
        return vals[-1] if vals else None

    try:
        revenue = int(_get_val(1))
        prev_revenue = int(_get_val(2))
        yoy_pct = float(_get_val(4))
    except (ValueError, TypeError, IndexError):
        return None
    if not revenue:
        return None
    return {"revenue": revenue, "prev_year_revenue": prev_revenue, "yoy_pct": yoy_pct}


async def _fetch_mops_month_async(
    client: httpx.AsyncClient,
    stock_id: str,
    roc_year: int,
    y: int,
    m: int,
) -> Optional[dict]:
    """非同步抓取單月營收（含防反爬 session 重建重試）。"""
    from bs4 import BeautifulSoup as _BS
    data = {
        "step": "1", "firstin": "true", "off": "1",
        "TYPEK": "sii", "year": str(roc_year), "month": f"{m:02d}", "co_id": stock_id,
    }

    async def _do():
        resp = await client.post(_MOPS_AJAX, data=data)
        resp.encoding = "utf-8"
        return resp

    resp = await _retry_async(_do)
    text = resp.text
    if "FOR SECURITY REASONS" in text or "安全性考量" in text:
        # 反爬封鎖：重建 session 後重試一次
        try:
            await client.get(_MOPS_ENTRY)
        except Exception:
            pass
        await asyncio.sleep(1.5)
        resp = await _retry_async(_do)
        text = resp.text
    # 二次封鎖：再次重建 session（原始同步版亦採多重 session 重建策略）
    if "FOR SECURITY REASONS" in text or "安全性考量" in text:
        try:
            await client.get(_MOPS_ENTRY)
        except Exception:
            pass
        await asyncio.sleep(1.5)
        resp = await _retry_async(_do)
        text = resp.text
    soup = _BS(text, "html.parser")
    parsed = _parse_mops_monthly_table(soup)
    if not parsed:
        return None
    return {
        "stock_id": stock_id,
        "year_month": f"{y}-{m:02d}",
        "revenue": parsed["revenue"],
        "yoy_change": parsed["yoy_pct"],
    }


def fetch_monthly_revenue_batch(stock_id: str, months: int = 36, incremental: bool = False, db=None) -> list[dict]:
    """Fetch up to `months` of monthly revenue for a stock, computing mom_change.

    T016 §3：以 httpx.AsyncClient 將逐月 sequential 請求改為批量併發
    （並行度 _MOPS_CONCURRENCY=3，規範 3–5，兼顧速度與 MOPS 反爬耐受度）。
    使用持久 session（先打 entry 頁取 cookie，再 ajax POST）避免反爬封鎖。
    incremental=True 時僅抓取 DB 中缺少的月份（回傳 0 個月=資料已最新）。
    回傳依 year_month 升冪排序之 [{stock_id, year_month, revenue, mom_change, yoy_change}, ...]
    """
    today = date.today()
    months_list = _monthly_rev_months(months, today)
    if not months_list:
        return []

    if incremental and db is not None:
        with db.connect() as conn:
            existing = {
                r[0] for r in conn.execute(
                    "SELECT year_month FROM monthly_revenue WHERE stock_id=?", [stock_id]
                ).fetchall()
            }
        # MOPS 每月約 10 日公告上月營收；當月（未結束）與上月（可能未公告）
        # 不納入增量目標，避免每次運行都對未公告月份發請求
        pub_cutoff = (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
        months_list = [
            (y, yy, m) for (y, yy, m) in months_list
            if f"{yy}-{m:02d}" not in existing and f"{yy}-{m:02d}" <= pub_cutoff
        ]
        if not months_list:
            return []

    async def _run() -> list[dict]:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers=_MOPS_HEADERS) as client:
            try:
                await client.get(_MOPS_ENTRY)
            except Exception:
                pass
            await asyncio.sleep(0.4)

            sem = asyncio.Semaphore(_MOPS_CONCURRENCY)

            async def _wrapped(roc_year: int, y: int, m: int):
                async with sem:
                    return await _fetch_mops_month_async(client, stock_id, roc_year, y, m)

            results = await asyncio.gather(
                *[_wrapped(roc_year, y, m) for roc_year, y, m in months_list]
            )
            return [r for r in results if r]

    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = None
    if loop is not None and loop.is_running():
        results = asyncio.run_coroutine_threadsafe(_run(), loop).result()
    else:
        results = asyncio.run(_run())

    # Sort ascending to compute mom_change
    results.sort(key=lambda r: r["year_month"])
    for i in range(1, len(results)):
        prev_rev = results[i - 1]["revenue"]
        if prev_rev and prev_rev > 0:
            results[i]["mom_change"] = round((results[i]["revenue"] - prev_rev) / prev_rev * 100, 2)
        else:
            results[i]["mom_change"] = None
    if results:
        results[0]["mom_change"] = None

    return results


def fetch_yf_quarterly_financials_batch(stock_id: str, max_quarters: int = 20) -> list[dict]:
    """Fetch quarterly financials (eps, revenue, gross_margin, roe, roa) via yfinance.

    Returns list sorted by fiscal_quarter ascending (oldest first).
    ROE = Net Income / Total Stockholder Equity; ROA = Net Income / Total Assets.
    """
    try:
        import yfinance as yf
        import pandas as pd
    except ImportError:
        return []
    try:
        ticker = yf.Ticker(f"{stock_id}.TW")
    except Exception:
        return []

    fs = ticker.quarterly_financials
    bs = ticker.quarterly_balance_sheet
    if fs is None or fs.empty:
        return []

    results = []
    for col in fs.columns:
        # fiscal_quarter label like "2025Q1"
        q_ts = pd.Timestamp(col)
        q_num = (q_ts.month - 1) // 3 + 1
        q_label = f"{q_ts.year}Q{q_num}"

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

        net_income = None
        if "Net Income" in fs.index:
            v = fs.loc["Net Income", col]
            net_income = float(v) if not pd.isna(v) else None

        gross_margin = round(gp / rev * 100, 2) if rev and gp and rev > 0 else None

        # ROE / ROA from balance sheet
        roe = None
        roa = None
        if bs is not None and not bs.empty and col in bs.columns:
            total_equity = None
            total_assets = None
            # yfinance field names vary; try multiple candidates
            equity_candidates = ["Total Stockholder Equity", "Stockholders Equity", "Common Stock Equity", "Total Equity Gross Minority Interest"]
            asset_candidates = ["Total Assets"]
            for c in equity_candidates:
                if c in bs.index:
                    v = bs.loc[c, col]
                    total_equity = float(v) if not pd.isna(v) else None
                    break
            for c in asset_candidates:
                if c in bs.index:
                    v = bs.loc[c, col]
                    total_assets = float(v) if not pd.isna(v) else None
                    break

            if net_income and total_equity and total_equity > 0:
                roe = round(net_income / total_equity * 100, 2)
            if net_income and total_assets and total_assets > 0:
                roa = round(net_income / total_assets * 100, 2)

        results.append({
            "stock_id": stock_id,
            "fiscal_quarter": q_label,
            "eps": round(eps, 2) if eps else None,
            "revenue": rev,
            "gross_margin": gross_margin,
            "roe": roe,
            "roa": roa,
        })
        if len(results) >= max_quarters:
            break

    results.sort(key=lambda r: r["fiscal_quarter"])
    return results


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
                payload = _request_json(client, "GET", url)
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
