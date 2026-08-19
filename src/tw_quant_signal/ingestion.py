from datetime import date, timedelta

from tw_quant_signal.db import SignalDB
from tw_quant_signal.features import compute_all_features, compute_indicators_for_stock
from tw_quant_signal.provider import DataProvider, create_data_provider


class IngestionEngine:
    def __init__(
        self,
        db: SignalDB,
        provider: DataProvider | None = None,
    ):
        """T020: 資料來源改由 DataProvider 抽象層提供。

        Args:
            db: SignalDB 實例。
            provider: DataProvider 實例；省略時依
                TW_QUANT_DATA_PROVIDER（預設 direct）建立。
        """
        self.db = db
        self.provider = provider or create_data_provider()
        self._latest_indicators: dict = {}
        self._latest_valuations: dict = {}
        self._watch_stocks: list[str] = list(self.provider.watch_stocks)

    def _get_previous_trading_day(self, run_date: str) -> str:
        """獲取給定日期的前一交易日（跳過週末）。
        
        簡單實作：向前推進直到找到非週末的日期。
        實際生產環境建議查詢行事曆表。
        """
        d = date.fromisoformat(run_date)
        for _ in range(7):  # 最多往前找 7 天
            d -= timedelta(days=1)
            if d.weekday() < 5:  # 週一到週五
                return d.isoformat()
        # 兜底：回傳前一天
        return (date.fromisoformat(run_date) - timedelta(days=1)).isoformat()

    def _is_data_available(self, run_date: str, data_type: str) -> bool:
        """檢查指定日期的特定類型資料是否已可用。
        
        簡單實作：檢查資料庫中是否已有該日期的資料。
        """
        try:
            if data_type == "margin_trading":
                with self.db.connect() as conn:
                    row = conn.execute(
                        "SELECT 1 FROM margin_trading WHERE trade_date=? LIMIT 1",
                        [run_date]
                    ).fetchone()
                    return row is not None
            elif data_type == "institutional":
                with self.db.connect() as conn:
                    row = conn.execute(
                        "SELECT 1 FROM institutional_flows WHERE trade_date=? LIMIT 1",
                        [run_date]
                    ).fetchone()
                    return row is not None
        except Exception:
            pass
        return False

    def _log_source(self, run_date: str, task: str, status: str, message: str = None) -> None:
        """log_pipeline 並標註資料來源（T021 S5）。

        mcp 模式降級時，pipeline_log.message 會附上 source=direct(fallback)
        供事後追溯資料來源。direct 模式則為 source=direct。
        """
        source = getattr(self.provider, "last_source", None)
        if source:
            message = f"{message or ''} source={source}".strip()
        self.db.log_pipeline(run_date, task, status, message)

    def run_daily(self, run_date: str = None) -> dict:
        run_date = run_date or date.today().isoformat()
        results = {"index": "skip", "stocks": "skip", "institutional": "skip", "indicators": "skip", "features": "skip", "monthly_revenue": "skip", "quarterly_financials": "skip", "dividends": "skip", "margin_trading": "skip", "valuations": "skip"}

        results["index"] = self._ingest_index(run_date)
        results["stocks"] = self._ingest_watch_stocks(run_date)
        results["institutional"] = self._ingest_institutional(run_date)
        results["margin_trading"] = self._ingest_margin_trading(run_date)
        results["monthly_revenue"] = self._ingest_monthly_revenue(run_date)
        results["quarterly_financials"] = self._ingest_quarterly_financials(run_date)
        results["dividends"] = self._ingest_dividends(run_date)
        results["valuations"] = self._ingest_valuations()
        results["indicators"] = self._ingest_indicators()
        results["features"] = self._ingest_features()
        return results

    def backfill_prices(self, stock_id: str, start_date: str, end_date: str = None) -> int:
        end_date = end_date or date.today().isoformat()
        rows = self.provider.fetch_historical_daily_prices(stock_id, start_date, end_date)
        if rows:
            self.db.upsert_daily_prices(rows)
        return len(rows)

    def _ingest_index(self, run_date: str) -> str:
        try:
            index_data = self.provider.fetch_market_index()
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
            rows = self.provider.fetch_watch_stocks_prices()
            if rows:
                self.db.upsert_daily_prices(rows)
                for r in rows:
                    self.db.compute_adj_close(r["stock_id"])
                ids = [r["stock_id"] for r in rows]
                self._log_source(run_date, "watch_stocks", "ok", f"stocks={','.join(ids)}")
                return "ok"
            self._log_source(run_date, "watch_stocks", "fail", "empty response")
            return "fail"
        except Exception as e:
            self._log_source(run_date, "watch_stocks", "fail", str(e))
            return "fail"

    def _ingest_institutional(self, run_date: str) -> str:
        # T028: 當日盤後資料尚未出爐時，回退到前一交易日
        target_date = run_date
        today = date.today().isoformat()
        if run_date == today and not self._is_data_available(run_date, "institutional"):
            target_date = self._get_previous_trading_day(run_date)
            self._log_source(run_date, "institutional_flows", "skip", f"當日資料未就緒，回退至 {target_date}")
        
        try:
            rows = self.provider.fetch_institutional_flows(target_date)
            if rows:
                self.db.upsert_institutional_flows(rows)
                self._log_source(run_date, "institutional_flows", "ok", f"records={len(rows)} date={target_date}")
                return "ok"
            self._log_source(run_date, "institutional_flows", "skip", f"no data (weekend/holiday?) date={target_date}")
            return "skip"
        except Exception as e:
            self._log_source(run_date, "institutional_flows", "fail", str(e))
            return "fail"

    def _ingest_indicators(self) -> str:
        today = date.today().isoformat()
        try:
            indicators_map = {}
            for sid in self._watch_stocks:
                ind_rows = compute_indicators_for_stock(self.db, sid, lookback=120)
                if ind_rows:
                    self.db.upsert_tech_indicators(ind_rows)
                    indicators_map[sid] = ind_rows
            # 暫存供 _ingest_features 使用，避免二次計算
            self._latest_indicators = indicators_map
            self.db.log_pipeline(today, "tech_indicators", "ok")
            return "ok"
        except Exception as e:
            self.db.log_pipeline(today, "tech_indicators", "fail", str(e))
            return "fail"

    def _ingest_monthly_revenue(self, run_date: str) -> str:
        """T016 §3：月營收批次改為 async 併發（單一股票內部月份平行）。

        注意：不跨股票平行（MOPS 反爬對總併發數敏感，曾因 3 股×併發
        同時請求觸發封鎖）。每檔股票依序處理，批次內部以 _MOPS_CONCURRENCY
        平行抓取。
        增量：僅抓取 DB 中缺少的月份（正常每日運行只會新增 1–2 個月），
        大幅降低請求數與反爬風險。
        """
        total = 0
        errors = []
        for sid in self._watch_stocks:
            if sid == "0050":  # ETF, no MOPS monthly revenue
                continue
            try:
                rows = self.provider.fetch_monthly_revenue_batch(sid, months=36, incremental=True, db=self.db)
                if rows:
                    self.db.upsert_monthly_revenue(rows)
                    total += len(rows)
                # rows=[] 屬正常（最新月份尚未公告），非錯誤
            except Exception as e:
                errors.append(f"{sid}:{e}")
        status = "fail" if errors and total == 0 else "ok"
        msg = f"records={total}"
        if errors:
            msg += f" errors={';'.join(errors)}"
        self.db.log_pipeline(run_date, "monthly_revenue", status, msg)
        return status

    def _ingest_valuations(self) -> str:
        """T016 §2：一次拉取全體觀察股票 valuations，供 features 階段使用。

        估值為 BWIBBU_ALL 全體資料（一次 HTTP），本方法拉取後以
        `self._latest_valuations` 暫存屬性供 _ingest_features 取用。
        """
        today = date.today().isoformat()
        try:
            val_map = self.provider.fetch_valuations()
            if not val_map:
                self._log_source(today, "valuations", "skip", "empty response")
                return "skip"
            self._latest_valuations = val_map
            self._log_source(today, "valuations", "ok", f"stocks={len(val_map)}")
            return "ok"
        except Exception as e:
            self._log_source(today, "valuations", "fail", str(e))
            return "fail"

    def _ingest_quarterly_financials(self, run_date: str) -> str:
        try:
            total = 0
            for sid in self._watch_stocks:
                rows = self.provider.fetch_quarterly_financials_batch(sid, max_quarters=20)
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
            for sid in self._watch_stocks:
                rows = self.provider.fetch_dividends(sid)
                if rows:
                    self.db.upsert_dividends(rows)
                    total += len(rows)
            self.db.log_pipeline(run_date, "dividends", "ok", f"records={total}")
            return "ok"
        except Exception as e:
            self.db.log_pipeline(run_date, "dividends", "fail", str(e))
            return "fail"

    def _ingest_margin_trading(self, run_date: str) -> str:
        # T028: 當日盤後資料尚未出爐時，回退到前一交易日
        target_date = run_date
        today = date.today().isoformat()
        if run_date == today and not self._is_data_available(run_date, "margin_trading"):
            target_date = self._get_previous_trading_day(run_date)
            self._log_source(run_date, "margin_trading", "skip", f"當日資料未就緒，回退至 {target_date}")
        
        try:
            rows = self.provider.fetch_margin_trading_detailed(target_date)
            watch_set = set(self._watch_stocks)
            filtered = [r for r in rows if r["stock_id"] in watch_set]
            if filtered:
                self.db.upsert_margin_trading(filtered)
            self._log_source(run_date, "margin_trading", "ok", f"records={len(filtered)} date={target_date}")
            return "ok"
        except Exception as e:
            self._log_source(run_date, "margin_trading", "fail", str(e))
            return "fail"

    def _ingest_features(self) -> str:
        today = date.today().isoformat()
        try:
            val_map = getattr(self, "_latest_valuations", None)
            indicators_map = getattr(self, "_latest_indicators", None)
            features = compute_all_features(self.db, val_map=val_map, indicators_map=indicators_map)
            if features:
                self.db.upsert_features(features)
            self.db.log_pipeline(today, "features", "ok", f"count={len(features)}")
            return "ok"
        except Exception as e:
            self.db.log_pipeline(today, "features", "fail", str(e))
            return "fail"
