"""DataProvider 抽象基底類別 — T020。

定義市場/法人/估值/財務/歷史資料等資料擷取的統一介面。
上游模組（IngestionEngine / features / backtest / backfill）僅依賴此介面，
不綁定具體來源實作；交換為 McpDataProvider（T021/T022）時無需修改上層。
"""

from abc import ABC, abstractmethod

from tw_quant_signal.config import WATCH_STOCKS


class DataProvider(ABC):
    """資料擷取抽象介面。"""

    @property
    def watch_stocks(self) -> list[str]:
        """觀察標的清單（預設來自 config；子類可覆寫注入）。"""
        if hasattr(self, "_watch_stocks") and self._watch_stocks is not None:
            return list(self._watch_stocks)
        return list(WATCH_STOCKS)

    @abstractmethod
    def fetch_watch_stocks_prices(self) -> list[dict]:
        """抓取所有觀察標的當日成交行情。"""

    @abstractmethod
    def fetch_market_index(self) -> dict | None:
        """抓取加權指數當日行情。"""

    @abstractmethod
    def fetch_institutional_flows(self, trade_date: str | None = None) -> list[dict]:
        """抓取指定日期（預設今日）法人買賣超。"""

    @abstractmethod
    def fetch_valuations(self, stock_ids: list[str] | None = None) -> dict[str, dict]:
        """抓取本益率/淨值比/殖利率。stock_ids=None 時代表全體。"""

    @abstractmethod
    def fetch_margin_trading_detailed(self, trade_date: str | None = None) -> list[dict]:
        """抓取融資融券買賣明細。"""

    @abstractmethod
    def fetch_monthly_revenue_batch(
        self,
        stock_id: str,
        months: int = 36,
        incremental: bool = False,
        db=None,
    ) -> list[dict]:
        """抓取單一股票月營收歷史。

        db/incremental 供直接連線模式下沿用 T016 增量回補行為（零行為變更）。
        """

    @abstractmethod
    def fetch_quarterly_financials_batch(
        self, stock_id: str, max_quarters: int = 20
    ) -> list[dict]:
        """抓取單一股票季報財務數據。"""

    @abstractmethod
    def fetch_dividends(self, stock_id: str) -> list[dict]:
        """抓取單一股票股利發放歷史。"""

    @abstractmethod
    def fetch_historical_index(self, years: int = 5) -> list[dict]:
        """抓取歷史加權指數。"""

    @abstractmethod
    def fetch_historical_daily_prices(
        self, stock_id: str, start_date: str, end_date: str
    ) -> list[dict]:
        """抓取單一股票歷史日資料。"""
