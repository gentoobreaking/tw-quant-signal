"""DataProvider 抽象層套件 — T020。

對外匯出：
- ``DataProvider``        : 抽象基底類別
- ``TwseDirectProvider``  : 現有 HTTP 直連實作（內含 yfinance 補充）
- ``YfinanceProvider``    : yfinance 財務/股利補充提供者
- ``McpDataProvider``     : tw-quant-mcp 骨架（T021/T022）
- ``HybridDataProvider``  : TWSE 走 mcp、MOPS/yfinance 走 direct（T023 S1）
- ``create_data_provider``: 工廠函式（依模式決定實作）

切換資料來源：環境變數 ``TW_QUANT_DATA_PROVIDER=direct|mcp|hybrid``。
"""

import os

from tw_quant_signal.config import (
    WATCH_STOCKS,
)

from .base import DataProvider
from .mcp_provider import McpDataProvider
from .twse_direct import TwseDirectProvider
from .yfinance_provider import YfinanceProvider

__all__ = [
    "WATCH_STOCKS",
    "DataProvider",
    "McpDataProvider",
    "TwseDirectProvider",
    "YfinanceProvider",
    "HybridDataProvider",
    "create_data_provider",
]

_DEFAULT_MODE = "direct"


class HybridDataProvider(DataProvider):
    """Hybrid 模式：TWSE/法人/估值/融資 走 mcp；MOPS/季報/股利/歷史 走 direct。

    - MCP 端點：get_stock_daily_quote, get_market_summary, get_institutional_investors,
      get_valuation_ratios, get_margin_trading, get_stock_daily_kline
    - Direct 端點：monthly_revenue, quarterly_financials, dividends,
      yfinance 補充（季報/股利）
    """

    def __init__(
        self,
        server_path: str | None = None,
        call_timeout: float = 30.0,
    ):
        self._mcp = McpDataProvider(
            server_path=server_path,
            call_timeout=call_timeout,
            fallback_provider=None,  # fallback 由 Hybrid 控制
        )
        self._direct = TwseDirectProvider()
        # 確保兩者 watch_stocks 一致
        self._mcp._fallback = self._direct

    @property
    def watch_stocks(self) -> list[str]:
        return self._direct.watch_stocks

    # ---- TWSE 類（走 mcp）----
    def fetch_watch_stocks_prices(self) -> list[dict]:
        return self._mcp.fetch_watch_stocks_prices()

    def fetch_market_index(self) -> dict | None:
        return self._mcp.fetch_market_index()

    def fetch_institutional_flows(self, trade_date: str | None = None) -> list[dict]:
        return self._mcp.fetch_institutional_flows(trade_date)

    def fetch_valuations(self, stock_ids: list[str] | None = None) -> dict[str, dict]:
        return self._mcp.fetch_valuations(stock_ids)

    def fetch_margin_trading_detailed(
        self, trade_date: str | None = None
    ) -> list[dict]:
        return self._mcp.fetch_margin_trading_detailed(trade_date)

    # ---- 歷史（走 mcp）----
    def fetch_historical_index(self, years: int = 5) -> list[dict]:
        return self._mcp.fetch_historical_index(years)

    def fetch_historical_daily_prices(
        self, stock_id: str, start_date: str, end_date: str
    ) -> list[dict]:
        return self._mcp.fetch_historical_daily_prices(stock_id, start_date, end_date)

    # ---- MOPS / yfinance（走 direct）----
    def fetch_monthly_revenue_batch(
        self,
        stock_id: str,
        months: int = 36,
        incremental: bool = False,
        db=None,
    ) -> list[dict]:
        return self._direct.fetch_monthly_revenue_batch(
            stock_id, months=months, incremental=incremental, db=db
        )

    def fetch_quarterly_financials_batch(
        self, stock_id: str, max_quarters: int = 20
    ) -> list[dict]:
        return self._direct.fetch_quarterly_financials_batch(
            stock_id, max_quarters=max_quarters
        )

    def fetch_dividends(self, stock_id: str) -> list[dict]:
        return self._direct.fetch_dividends(stock_id)


def create_data_provider(mode: str | None = None) -> DataProvider:
    """依模式回傳 DataProvider 實例。

    Args:
        mode: ``"direct"`` (現有 HTTP 直連) 或 ``"mcp"`` (tw-quant-mcp) 或
              ``"hybrid"`` (TWSE 走 mcp、MOPS/yfinance 走 direct)。
              省略時讀取環境變數 ``TW_QUANT_DATA_PROVIDER``，預設 ``"direct"``。
    """
    if mode is None:
        mode = os.getenv("TW_QUANT_DATA_PROVIDER", _DEFAULT_MODE)

    if mode == "direct":
        return TwseDirectProvider()
    if mode == "mcp":
        return McpDataProvider(
            server_path=os.getenv("MCP_SERVER_PATH") or None,
            call_timeout=float(os.getenv("MCP_CALL_TIMEOUT", "30")),
        )
    if mode == "hybrid":
        return HybridDataProvider(
            server_path=os.getenv("MCP_SERVER_PATH") or None,
            call_timeout=float(os.getenv("MCP_CALL_TIMEOUT", "30")),
        )
    raise ValueError(
        f"Unknown data provider mode: {mode!r} (expected 'direct', 'mcp', or 'hybrid')"
    )
