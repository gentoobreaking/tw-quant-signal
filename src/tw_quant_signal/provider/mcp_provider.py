"""McpDataProvider — T020 骨架。

預留給 T021/T022：將資料層遷移至 tw-quant-mcp。目前各方法僅拋出
NotImplementedError，以便在 TW_QUANT_DATA_PROVIDER=mcp 時明確指出尚未實作，
並讓 create_data_provider 工廠可回傳本類別。
"""


from .base import DataProvider

_NOT_IMPL_MSG = (
    "McpDataProvider 尚未實作 — 請見 T021/T022（資料層遷移至 tw-quant-mcp）。"
)


class McpDataProvider(DataProvider):
    """對接 tw-quant-mcp 的資料提供者（骨架）。"""

    def __init__(self, base_url: str | None = None):
        self.base_url = base_url or ""  # 供 T021/T022 填入 MCP endpoint

    def fetch_watch_stocks_prices(self) -> list[dict]:
        raise NotImplementedError(_NOT_IMPL_MSG)

    def fetch_market_index(self) -> dict | None:
        raise NotImplementedError(_NOT_IMPL_MSG)

    def fetch_institutional_flows(self, trade_date: str | None = None) -> list[dict]:
        raise NotImplementedError(_NOT_IMPL_MSG)

    def fetch_valuations(self, stock_ids: list[str] | None = None) -> dict[str, dict]:
        raise NotImplementedError(_NOT_IMPL_MSG)

    def fetch_margin_trading_detailed(
        self, trade_date: str | None = None
    ) -> list[dict]:
        raise NotImplementedError(_NOT_IMPL_MSG)

    def fetch_monthly_revenue_batch(
        self, stock_id: str, months: int = 36, incremental: bool = False, db=None
    ) -> list[dict]:
        raise NotImplementedError(_NOT_IMPL_MSG)

    def fetch_quarterly_financials_batch(
        self, stock_id: str, max_quarters: int = 20
    ) -> list[dict]:
        raise NotImplementedError(_NOT_IMPL_MSG)

    def fetch_dividends(self, stock_id: str) -> list[dict]:
        raise NotImplementedError(_NOT_IMPL_MSG)

    def fetch_historical_index(self, years: int = 5) -> list[dict]:
        raise NotImplementedError(_NOT_IMPL_MSG)

    def fetch_historical_daily_prices(
        self, stock_id: str, start_date: str, end_date: str
    ) -> list[dict]:
        raise NotImplementedError(_NOT_IMPL_MSG)
