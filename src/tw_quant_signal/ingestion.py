from datetime import date, timedelta
from typing import Optional

from tw_quant_signal.db import SignalDB
from tw_quant_signal.twse_client import (
    fetch_watch_stocks_prices,
    fetch_market_index,
    fetch_institutional_flows,
    fetch_historical_daily_prices,
    WATCH_STOCKS,
)
from tw_quant_signal.indicators import compute_indicators


class IngestionEngine:
    def __init__(self, db: SignalDB):
        self.db = db

    def run_daily(self, run_date: str = None) -> dict:
        run_date = run_date or date.today().isoformat()
        results = {"index": "skip", "stocks": "skip", "institutional": "skip", "indicators": "skip"}

        results["index"] = self._ingest_index(run_date)
        results["stocks"] = self._ingest_watch_stocks(run_date)
        results["institutional"] = self._ingest_institutional(run_date)
        results["indicators"] = self._ingest_indicators()
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
