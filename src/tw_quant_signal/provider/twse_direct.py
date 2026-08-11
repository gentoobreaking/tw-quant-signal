"""TwseDirectProvider — T020。

將 twse_client 的 HTTP 直連 fetch_* 包裝為 DataProvider。
為 provider 的內部實作，外部模組應透過 create_data_provider("direct")
取得本實例，而非直接 import twse_client 的函式。

yfinance 補充資料（季報/股利）委派至 YfinanceProvider，使本類別單一
物件即可滿足 IngestionEngine 全部資料需求（direct = TwseDirect + Yfinance）。
"""


from tw_quant_signal.config import WATCH_STOCKS

from .base import DataProvider
from .yfinance_provider import YfinanceProvider


class TwseDirectProvider(DataProvider):
    """直接 HTTP 連線 TWSE/MOPS 之提供者。"""

    def __init__(self, watch_stocks: list[str] | None = None):
        self._watch_stocks = (
            watch_stocks if watch_stocks is not None else WATCH_STOCKS
        )
        self._yf: YfinanceProvider | None = None

    @property
    def watch_stocks(self) -> list[str]:
        return self._watch_stocks

    def _yfinance(self) -> YfinanceProvider:
        if self._yf is None:
            self._yf = YfinanceProvider()
        return self._yf

    # ---- TWSE / MOPS HTTP 直連 ----
    def fetch_watch_stocks_prices(self) -> list[dict]:
        from tw_quant_signal.twse_client import fetch_watch_stocks_prices

        return fetch_watch_stocks_prices()

    def fetch_market_index(self) -> dict | None:
        from tw_quant_signal.twse_client import fetch_market_index

        return fetch_market_index()

    def fetch_institutional_flows(self, trade_date: str | None = None) -> list[dict]:
        from tw_quant_signal.twse_client import fetch_institutional_flows

        return fetch_institutional_flows(trade_date)

    def fetch_valuations(self, stock_ids: list[str] | None = None) -> dict[str, dict]:
        from tw_quant_signal.twse_client import fetch_valuations

        return fetch_valuations(stock_ids)

    def fetch_margin_trading_detailed(
        self, trade_date: str | None = None
    ) -> list[dict]:
        from tw_quant_signal.twse_client import fetch_margin_trading_detailed

        return fetch_margin_trading_detailed(trade_date)

    def fetch_monthly_revenue_batch(
        self,
        stock_id: str,
        months: int = 36,
        incremental: bool = False,
        db=None,
    ) -> list[dict]:
        from tw_quant_signal.twse_client import fetch_monthly_revenue_batch

        return fetch_monthly_revenue_batch(
            stock_id, months=months, incremental=incremental, db=db
        )

    def fetch_historical_index(self, years: int = 5) -> list[dict]:
        from tw_quant_signal.twse_client import fetch_historical_index

        return fetch_historical_index(years=years)

    def fetch_historical_daily_prices(
        self, stock_id: str, start_date: str, end_date: str
    ) -> list[dict]:
        from tw_quant_signal.twse_client import fetch_historical_daily_prices

        return fetch_historical_daily_prices(stock_id, start_date, end_date)

    # ---- yfinance 補充（季報/股利） ----
    def fetch_quarterly_financials_batch(
        self, stock_id: str, max_quarters: int = 20
    ) -> list[dict]:
        return self._yfinance().fetch_quarterly_financials_batch(
            stock_id, max_quarters=max_quarters
        )

    def fetch_dividends(self, stock_id: str) -> list[dict]:
        return self._yfinance().fetch_dividends(stock_id)

    def fetch_yf_financials(self, stock_id: str) -> dict | None:
        """yfinance 年報（補充供應者，非 ABC 方法）。"""
        return self._yfinance().fetch_yf_financials(stock_id)
