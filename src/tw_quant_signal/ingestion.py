from datetime import date, timedelta
from typing import Optional

from tw_quant_signal.db import SignalDB
from tw_quant_signal.twse_client import (
    fetch_watch_stocks_prices,
    fetch_market_index,
    fetch_institutional_flows,
    fetch_monthly_revenue_batch,
    fetch_yf_quarterly_financials_batch,
    fetch_historical_daily_prices,
    fetch_margin_trading_detailed,
    WATCH_STOCKS,
)
from tw_quant_signal.indicators import compute_indicators
from tw_quant_signal.features import compute_all_features


def _fetch_dividends_yf(stock_id: str) -> list[dict]:
    """Fetch dividend history from yfinance for a Taiwan stock."""
    try:
        import yfinance as yf
        import pandas as pd
    except ImportError:
        return []
    try:
        ticker = yf.Ticker(f"{stock_id}.TW")
        div = ticker.dividends
    except Exception:
        return []
    if div is None or div.empty:
        return []
    results = []
    price_cache: dict[str, float] = {}
    for dt_idx, amount in div.items():
        year = dt_idx.year
        ex_date = dt_idx.strftime("%Y-%m-%d")
        cash_yield = None
        close_before = None
        # Try to get close price before ex-date
        import httpx
        try:
            from datetime import timedelta
            lookback = (dt_idx - timedelta(days=5)).strftime("%Y%m%d")
            resp = httpx.get(
                f"https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date={lookback}&stockNo={stock_id.replace('.TW','')}&response=json",
                timeout=10,
            )
            payload = resp.json()
            if payload.get("stat") == "OK":
                for row in payload.get("data", []):
                    parts = row[0].split("/")
                    if len(parts) == 3:
                        ad = f"{int(parts[0])+1911}-{parts[1]}-{parts[2]}"
                        if ad == ex_date:
                            close_before = float(row[6]) if row[6].replace(",", "").replace(".", "", 1).lstrip("-").isdigit() else None
                            break
                if close_before and amount:
                    cash_yield = round(amount / close_before * 100, 2)
        except Exception:
            pass
        results.append({
            "stock_id": stock_id,
            "year": year,
            "ex_date": ex_date,
            "close_before_ex": close_before,
            "cash_dividend": round(float(amount), 2) if not pd.isna(amount) else None,
            "cash_pay_date": None,
            "cash_yield": cash_yield,
            "stock_dividend": None,
        })
    return sorted(results, key=lambda r: r["year"], reverse=True)[:5]


class IngestionEngine:
    def __init__(self, db: SignalDB):
        self.db = db

    def run_daily(self, run_date: str = None) -> dict:
        run_date = run_date or date.today().isoformat()
        results = {"index": "skip", "stocks": "skip", "institutional": "skip", "indicators": "skip", "features": "skip", "monthly_revenue": "skip", "quarterly_financials": "skip", "dividends": "skip", "margin_trading": "skip"}

        results["index"] = self._ingest_index(run_date)
        results["stocks"] = self._ingest_watch_stocks(run_date)
        results["institutional"] = self._ingest_institutional(run_date)
        results["margin_trading"] = self._ingest_margin_trading(run_date)
        results["monthly_revenue"] = self._ingest_monthly_revenue(run_date)
        results["quarterly_financials"] = self._ingest_quarterly_financials(run_date)
        results["dividends"] = self._ingest_dividends(run_date)
        results["indicators"] = self._ingest_indicators()
        results["features"] = self._ingest_features()
        return results

    def backfill_prices(self, stock_id: str, start_date: str, end_date: str = None) -> int:
        end_date = end_date or date.today().isoformat()
        rows = fetch_historical_daily_prices(stock_id, start_date, end_date)
        if rows:
            self.db.upsert_daily_prices(rows)
        return len(rows)

    def _ingest_index(self, run_date: str) -> str:
        try:
            index_data = fetch_market_index()
            if index_data:
                self.db.upsert_market_index(index_data)
                self.db.log_pipeline(run_date, "market_index", "ok")
                return "ok"
            self.db.log_pipeline(run_date, "market_index", "fail", "empty response")
            return "fail"
        except Exception as e:
            self.db.log_pipeline(run_date, "market_index", "fail", str(e))
            return "fail"

    def _ingest_watch_stocks(self, run_date: str) -> str:
        try:
            rows = fetch_watch_stocks_prices()
            if rows:
                self.db.upsert_daily_prices(rows)
                for r in rows:
                    self.db.compute_adj_close(r["stock_id"])
                ids = [r["stock_id"] for r in rows]
                self.db.log_pipeline(run_date, "watch_stocks", "ok", f"stocks={','.join(ids)}")
                return "ok"
            self.db.log_pipeline(run_date, "watch_stocks", "fail", "empty response")
            return "fail"
        except Exception as e:
            self.db.log_pipeline(run_date, "watch_stocks", "fail", str(e))
            return "fail"

    def _ingest_institutional(self, run_date: str) -> str:
        try:
            rows = fetch_institutional_flows()
            if rows:
                self.db.upsert_institutional_flows(rows)
                self.db.log_pipeline(run_date, "institutional_flows", "ok", f"records={len(rows)}")
                return "ok"
            self.db.log_pipeline(run_date, "institutional_flows", "skip", "no data (weekend/holiday?)")
            return "skip"
        except Exception as e:
            self.db.log_pipeline(run_date, "institutional_flows", "fail", str(e))
            return "fail"

    def _ingest_indicators(self) -> str:
        today = date.today().isoformat()
        try:
            for sid in WATCH_STOCKS:
                prices = self.db.get_stock_prices(sid, limit=365)
                if len(prices) < 60:
                    continue
                indicators = compute_indicators(prices, stock_id=sid)
                if indicators:
                    self.db.upsert_tech_indicators(indicators)
            self.db.log_pipeline(today, "tech_indicators", "ok")
            return "ok"
        except Exception as e:
            self.db.log_pipeline(today, "tech_indicators", "fail", str(e))
            return "fail"

    def _ingest_monthly_revenue(self, run_date: str) -> str:
        try:
            total = 0
            for sid in WATCH_STOCKS:
                rows = fetch_monthly_revenue_batch(sid, months=36)
                if rows:
                    self.db.upsert_monthly_revenue(rows)
                    total += len(rows)
            self.db.log_pipeline(run_date, "monthly_revenue", "ok", f"records={total}")
            return "ok"
        except Exception as e:
            self.db.log_pipeline(run_date, "monthly_revenue", "fail", str(e))
            return "fail"

    def _ingest_quarterly_financials(self, run_date: str) -> str:
        try:
            total = 0
            for sid in WATCH_STOCKS:
                rows = fetch_yf_quarterly_financials_batch(sid, max_quarters=20)
                if rows:
                    self.db.upsert_quarterly_financials(rows)
                    total += len(rows)
            self.db.log_pipeline(run_date, "quarterly_financials", "ok", f"records={total}")
            return "ok"
        except Exception as e:
            self.db.log_pipeline(run_date, "quarterly_financials", "fail", str(e))
            return "fail"

    def _ingest_dividends(self, run_date: str) -> str:
        try:
            total = 0
            for sid in WATCH_STOCKS:
                rows = _fetch_dividends_yf(sid)
                if rows:
                    self.db.upsert_dividends(rows)
                    total += len(rows)
            self.db.log_pipeline(run_date, "dividends", "ok", f"records={total}")
            return "ok"
        except Exception as e:
            self.db.log_pipeline(run_date, "dividends", "fail", str(e))
            return "fail"

    def _ingest_margin_trading(self, run_date: str) -> str:
        try:
            rows = fetch_margin_trading_detailed(run_date)
            watch_set = set(WATCH_STOCKS)
            filtered = [r for r in rows if r["stock_id"] in watch_set]
            if filtered:
                self.db.upsert_margin_trading(filtered)
            self.db.log_pipeline(run_date, "margin_trading", "ok", f"records={len(filtered)}")
            return "ok"
        except Exception as e:
            self.db.log_pipeline(run_date, "margin_trading", "fail", str(e))
            return "fail"

    def _ingest_features(self) -> str:
        today = date.today().isoformat()
        try:
            features = compute_all_features(self.db)
            if features:
                self.db.upsert_features(features)
            self.db.log_pipeline(today, "features", "ok", f"count={len(features)}")
            return "ok"
        except Exception as e:
            self.db.log_pipeline(today, "features", "fail", str(e))
            return "fail"
