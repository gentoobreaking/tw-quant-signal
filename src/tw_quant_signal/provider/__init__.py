"""DataProvider 抽象層套件 — T020。

對外匯出：
- ``DataProvider``        : 抽象基底類別
- ``TwseDirectProvider``  : 現有 HTTP 直連實作（內含 yfinance 補充）
- ``YfinanceProvider``    : yfinance 財務/股利補充提供者
- ``McpDataProvider``     : tw-quant-mcp 骨架（T021/T022）
- ``create_data_provider``: 工廠函式（依模式決定實作）

切換資料來源：環境變數 ``TW_QUANT_DATA_PROVIDER=direct|mcp``。
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
    "create_data_provider",
]

_DEFAULT_MODE = "direct"


def create_data_provider(mode: str | None = None) -> DataProvider:
    """依模式回傳 DataProvider 實例。

    Args:
        mode: ``"direct"`` (現有 HTTP 直連) 或 ``"mcp"`` (tw-quant-mcp，預留)。
              省略時讀取環境變數 ``TW_QUANT_DATA_PROVIDER``，預設 ``"direct"``。
    """
    if mode is None:
        mode = os.getenv("TW_QUANT_DATA_PROVIDER", _DEFAULT_MODE)

    if mode == "direct":
        return TwseDirectProvider()
    if mode == "mcp":
        return McpDataProvider(
            base_url=os.getenv("TW_QUANT_MCP_URL") or None
        )
    raise ValueError(
        f"Unknown data provider mode: {mode!r} (expected 'direct' or 'mcp')"
    )
