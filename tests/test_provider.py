"""T020 — DataProvider 抽象層單元測試。

驗證：
- DataProvider 為抽象類別（無法直接實例化，含全部 fetch_* 簽名）
- create_data_provider 工廠（direct / mcp / 非法模式 / 環境變數）
- TwseDirectProvider 觀察清單與 yfinance 委派
- YfinanceProvider 作為補充提供者（TWSE 方法不支援）
"""

import os
from unittest import mock

import pytest

from tw_quant_signal.provider import (
    DataProvider,
    TwseDirectProvider,
    YfinanceProvider,
    McpDataProvider,
    create_data_provider,
)
from tw_quant_signal.config import WATCH_STOCKS


REQUIRED_METHODS = [
    "fetch_watch_stocks_prices",
    "fetch_market_index",
    "fetch_institutional_flows",
    "fetch_valuations",
    "fetch_margin_trading_detailed",
    "fetch_monthly_revenue_batch",
    "fetch_quarterly_financials_batch",
    "fetch_dividends",
    "fetch_historical_index",
    "fetch_historical_daily_prices",
]


class TestDataProviderBase:
    def test_is_abstract(self):
        with pytest.raises(TypeError):
            DataProvider()  # abstract class cannot be instantiated

    def test_all_required_signatures_declared(self):
        abstracts = set(DataProvider.__abstractmethods__)
        assert set(REQUIRED_METHODS) <= abstracts

    def test_watch_stocks_default_from_config(self):
        class _Impl(DataProvider):
            def fetch_watch_stocks_prices(self): return []
            def fetch_market_index(self): return None
            def fetch_institutional_flows(self, trade_date=None): return []
            def fetch_valuations(self, stock_ids=None): return {}
            def fetch_margin_trading_detailed(self, trade_date=None): return []
            def fetch_monthly_revenue_batch(self, stock_id, months=36, incremental=False, db=None): return []
            def fetch_quarterly_financials_batch(self, stock_id, max_quarters=20): return []
            def fetch_dividends(self, stock_id): return []
            def fetch_historical_index(self, years=5): return []
            def fetch_historical_daily_prices(self, stock_id, start_date, end_date): return []
        assert _Impl().watch_stocks == WATCH_STOCKS


class TestCreateDataProvider:
    def test_direct_mode(self):
        assert isinstance(create_data_provider("direct"), TwseDirectProvider)

    def test_mcp_mode(self):
        assert isinstance(create_data_provider("mcp"), McpDataProvider)

    def test_invalid_mode(self):
        with pytest.raises(ValueError):
            create_data_provider("bogus")

    def test_env_var_switch(self):
        with mock.patch.dict(os.environ, {"TW_QUANT_DATA_PROVIDER": "mcp"}, clear=False):
            assert isinstance(create_data_provider(), McpDataProvider)
        with mock.patch.dict(os.environ, {"TW_QUANT_DATA_PROVIDER": "direct"}, clear=False):
            assert isinstance(create_data_provider(), TwseDirectProvider)

    def test_default_mode_is_direct(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            if "TW_QUANT_DATA_PROVIDER" in os.environ:
                del os.environ["TW_QUANT_DATA_PROVIDER"]
            assert isinstance(create_data_provider(), TwseDirectProvider)


class TestTwseDirectProvider:
    def test_watch_stocks(self):
        p = TwseDirectProvider()
        assert p.watch_stocks == WATCH_STOCKS

    def test_custom_watch_stocks(self):
        p = TwseDirectProvider(watch_stocks=["2330"])
        assert p.watch_stocks == ["2330"]

    def test_delegates_yfinance_financials(self):
        p = TwseDirectProvider()
        with mock.patch(
            "tw_quant_signal.provider.yfinance_provider.YfinanceProvider"
            ".fetch_quarterly_financials_batch",
            return_value=[{"stock_id": "2330"}],
        ) as m:
            out = p.fetch_quarterly_financials_batch("2330")
        assert out == [{"stock_id": "2330"}]
        m.assert_called_once_with("2330", max_quarters=20)


class TestYfinanceProvider:
    def test_supplementary_only(self):
        p = YfinanceProvider()
        with pytest.raises(NotImplementedError):
            p.fetch_market_index()
        with pytest.raises(NotImplementedError):
            p.fetch_valuations()

    def test_dividends_empty_when_yfinance_missing(self):
        p = YfinanceProvider()
        with mock.patch.dict("sys.modules", {"yfinance": None}):
            # simulate missing optional dependency gracefully
            with mock.patch("builtins.__import__", side_effect=ImportError):
                assert p.fetch_dividends("2330") == []


class TestMcpDataProvider:
    def test_skeleton_raises(self):
        p = McpDataProvider()
        with pytest.raises(NotImplementedError):
            p.fetch_market_index()
