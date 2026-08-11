"""YfinanceProvider — T020。

將 twse_client / ingestion 中的 yfinance 相關資料來源封裝為 DataProvider。
僅在「財務/股利」等直連 TWSE/MOPS 無法取得之欄位上使用，作為
TwseDirectProvider 的補充提供者。yfinance 為選用相依（pip install backfill），
未安裝時 gracefully 回傳空清單，與既有 twse_client 行為一致。
"""

from datetime import timedelta

import httpx

from .base import DataProvider


class YfinanceProvider(DataProvider):
    """透過 yfinance 擷取財務/股利資料的提供者。

    因 yfinance 僅能補充取得少數財務欄位，故僅實作財務/股利方法；
    其他 TWSE 直連方法由 TwseDirectProvider 負責（呼叫端應透過
    create_data_provider("direct") 取得綜合提供者，不直接使用本類）。
    """

    # ---- yfinance-backed methods ----
    def fetch_quarterly_financials_batch(
        self, stock_id: str, max_quarters: int = 20
    ) -> list[dict]:
        """委派 twse_client 的 yfinance 季報實作（零行為變更）。"""
        from tw_quant_signal.twse_client import fetch_yf_quarterly_financials_batch

        return fetch_yf_quarterly_financials_batch(stock_id, max_quarters=max_quarters)

    def fetch_yf_financials(self, stock_id: str) -> dict | None:
        """委派 twse_client 的 yfinance 年報實作。"""
        from tw_quant_signal.twse_client import fetch_yf_financials as _fetch

        return _fetch(stock_id)

    def fetch_dividends(self, stock_id: str) -> list[dict]:
        """抓取台股股票股利發放歷史（依年集計，最多 5 年）。

        原實作位於 ingestion._fetch_dividends_yf，於此搬至 provider 內，
        保持行為不變。
        """
        try:
            import pandas as pd
            import yfinance as yf
        except ImportError:
            return []
        try:
            ticker = yf.Ticker(f"{stock_id}.TW")
            div = ticker.dividends
        except Exception:
            return []
        if div is None or div.empty:
            return []

        div_df = div.reset_index()
        div_df.columns = ["date", "amount"]
        div_df["year"] = div_df["date"].dt.year
        yearly_div = div_df.groupby("year").agg(
            {"amount": "sum", "date": "first"}
        ).reset_index()

        results: list[dict] = []
        for _, row in yearly_div.iterrows():
            year = int(row["year"])
            ex_date = row["date"].strftime("%Y-%m-%d")
            cash_dividend = (
                round(float(row["amount"]), 2) if not pd.isna(row["amount"]) else None
            )

            cash_yield: float | None = None
            close_before: float | None = None
            try:
                lookback = (row["date"] - timedelta(days=5)).strftime("%Y%m%d")
                resp = httpx.get(
                    f"https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY"
                    f"?date={lookback}&stockNo={stock_id}&response=json",
                    timeout=10,
                )
                payload = resp.json()
                if payload.get("stat") == "OK":
                    for r in payload.get("data", []):
                        parts = r[0].split("/")
                        if len(parts) == 3:
                            ad = f"{int(parts[0])+1911}-{parts[1]}-{parts[2]}"
                            if ad == ex_date:
                                raw = r[6].replace(",", "")
                                if raw.replace(".", "").lstrip("-").isdigit():
                                    close_before = float(raw)
                                break
                if close_before and cash_dividend:
                    cash_yield = round(cash_dividend / close_before * 100, 2)
            except Exception:
                pass

            results.append({
                "stock_id": stock_id,
                "year": year,
                "ex_date": ex_date,
                "close_before_ex": close_before,
                "cash_dividend": cash_dividend,
                "cash_pay_date": None,
                "cash_yield": cash_yield,
                "stock_dividend": None,
            })

        return sorted(results, key=lambda r: r["year"], reverse=True)[:5]

    # ---- TWSE-backed methods (not provided by yfinance) ----
    def _not_supported(self):
        raise NotImplementedError(
            "YfinanceProvider is a supplementary provider for financial/dividend "
            "data only; use TwseDirectProvider for TWSE/MOPS sources (T021/T022)."
        )

    def fetch_watch_stocks_prices(self) -> list[dict]:
        self._not_supported()

    def fetch_market_index(self) -> dict | None:
        self._not_supported()

    def fetch_institutional_flows(self, trade_date: str | None = None) -> list[dict]:
        self._not_supported()

    def fetch_valuations(self, stock_ids: list[str] | None = None) -> dict[str, dict]:
        self._not_supported()

    def fetch_margin_trading_detailed(
        self, trade_date: str | None = None
    ) -> list[dict]:
        self._not_supported()

    def fetch_monthly_revenue_batch(
        self, stock_id: str, months: int = 36, incremental: bool = False, db=None
    ) -> list[dict]:
        self._not_supported()

    def fetch_historical_index(self, years: int = 5) -> list[dict]:
        self._not_supported()

    def fetch_historical_daily_prices(
        self, stock_id: str, start_date: str, end_date: str
    ) -> list[dict]:
        self._not_supported()
