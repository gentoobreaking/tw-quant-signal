"""T021 McpDataProvider 單元測試。

覆蓋：
- mcp 模式建構與 fallback 注入
- 降級機制（連線失敗 → direct fallback）
- mcp 成功路徑（fake client 回傳 envelope）
- mcp 不支援項目（ETF/指數）自動降級
"""

import pytest
from unittest import mock

from tw_quant_signal.provider.mcp_provider import McpDataProvider
from tw_quant_signal.provider.mcp_client import McpConnectionError


class _FakeClient:
    """可設定的 fake McpClient。

    results[name] 若為 {symbol: envelope} 字典，則依 arguments 的
    symbol 分派回傳；否則直接回傳該結果。
    """

    def __init__(self, results: dict | None = None, fail_tools: set | None = None):
        self.results = results or {}
        self.fail_tools = fail_tools or set()
        self.calls: list[tuple] = []
        self.version = "2.1.0"

    def call_tool(self, name: str, arguments: dict | None = None):
        self.calls.append((name, arguments or {}))
        if name in self.fail_tools:
            raise McpConnectionError(f"fake failure for {name}")
        if name not in self.results:
            return {}
        r = self.results[name]
        sym = (arguments or {}).get("symbol", "")
        # 依 symbol 分派：{symbol: envelope}
        if isinstance(r, dict) and sym and sym in r:
            return r[sym]
        return r


class _FakeFallback:
    """記錄呼叫的 fake fallback provider。"""

    def __init__(self):
        self.calls = []

    def fetch_watch_stocks_prices(self):
        self.calls.append("fetch_watch_stocks_prices")
        return [{"stock_id": "0050", "trade_date": "2026-08-10", "close": 104.25,
                 "open": 103.9, "high": 104.75, "low": 103.5, "volume": 82086387,
                 "amount": 8557758998.0}]

    def fetch_market_index(self):
        self.calls.append("fetch_market_index")
        return {"trade_date": "2026-08-10", "close": 44928.76, "change_pct": 1.59}

    def fetch_institutional_flows(self, trade_date=None):
        self.calls.append(("fetch_institutional_flows", trade_date))
        return [{"stock_id": "2330", "trade_date": "2026-08-10", "market": "TSE",
                 "foreign_investors_net": 1, "sity_investors_net": 2, "dealer_net": 3,
                 "dealer_proprietary_net": 4, "dealer_hedge_net": 5, "total_net": 6}]

    def fetch_valuations(self, stock_ids=None):
        self.calls.append(("fetch_valuations", stock_ids))
        return {"2330": {"stock_id": "2330", "trade_date": "2026-08-10",
                         "pe_ratio": 32.0, "pb_ratio": 10.48, "dividend_yield": 0.0092}}

    def fetch_margin_trading_detailed(self, trade_date=None):
        self.calls.append(("fetch_margin_trading_detailed", trade_date))
        return []

    def fetch_historical_daily_prices(self, stock_id, start_date, end_date):
        self.calls.append(("fetch_historical_daily_prices", stock_id, start_date, end_date))
        return [{"stock_id": stock_id, "trade_date": start_date, "open": 1.0,
                 "high": 2.0, "low": 0.5, "close": 1.5, "volume": 100}]

    def fetch_historical_index(self, years=5):
        self.calls.append(("fetch_historical_index", years))
        return [{"trade_date": "2026-08-10", "close": 44928.76, "change_pct": None}]

    def fetch_monthly_revenue_batch(self, stock_id, months=36, incremental=False, db=None):
        self.calls.append(("fetch_monthly_revenue_batch", stock_id))
        return [{"stock_id": stock_id, "year_month": "2026-07", "revenue": 100,
                 "mom_change": 1.0, "yoy_change": 2.0}]

    def fetch_quarterly_financials_batch(self, stock_id, max_quarters=20):
        self.calls.append(("fetch_quarterly_financials_batch", stock_id))
        return [{"stock_id": stock_id, "fiscal_quarter": "2026Q2", "eps": 5.0}]

    def fetch_dividends(self, stock_id):
        self.calls.append(("fetch_dividends", stock_id))
        return [{"stock_id": stock_id, "year": 2025, "cash_dividend": 3.0}]


class TestMcpDataProviderT021:
    def _make(self, results=None, fail_tools=None):
        fb = _FakeFallback()
        from tw_quant_signal.provider.mcp_client import McpConnectionError, McpToolError
        p = McpDataProvider.__new__(McpDataProvider)
        p._McpConnectionError = McpConnectionError
        p._McpToolError = McpToolError
        results = dict(results or {})
        # 預設 Symbol Registry：2330/2308 上市，0050 不在（ETF）
        results.setdefault("get_symbol_list",
            {"data": [{"code": "2330"}, {"code": "2308"}]})
        p._client = _FakeClient(results, fail_tools)
        p._fallback = fb
        p._last_source = None
        p._last_fallback_reason = None
        p._symbols = None
        # 直接寫 instance dict 覆蓋唯讀 property（測試用）
        vars(p)["watch_stocks"] = ["2330", "0050", "2308"]
        return p, fb

    # ---- 成功路徑（mcp 原生） ----
    def test_quote_success(self):
        p, fb = self._make(results={
            "get_stock_daily_quote": {
                "2330": {"data": {"symbol": "2330", "name": "台積電",
                    "date": "2026-08-11", "open": 2390, "high": 2405, "low": 2375,
                    "close": 2395, "volume": 18247582, "amount": 43667182348}},
                "2308": {"data": {"symbol": "2308", "name": "台達電",
                    "date": "2026-08-11", "open": 1835, "high": 1865, "low": 1785,
                    "close": 1805, "volume": 18963715, "amount": 34503930330}},
            },
        })
        rows = p.fetch_watch_stocks_prices()
        assert len(rows) == 3  # 2330 + 0050（降級）+ 2308
        assert rows[0]["stock_id"] == "2330"
        assert rows[1]["stock_id"] == "0050"  # ETF 降級 direct
        assert rows[1]["close"] == 104.25
        assert rows[2]["stock_id"] == "2308"
        assert p.last_source == "mcp"

    def test_valuation_success(self):
        p, fb = self._make(results={
            "get_valuation_ratios": {"data": {"symbol": "2330", "name": "台積電",
                "date": "2026-08-10", "pe": 32.0, "pb": 10.48, "dividend_yield_pct": 0.92}},
        })
        val = p.fetch_valuations(["2330"])
        assert val["2330"]["pe_ratio"] == 32.0
        assert val["2330"]["dividend_yield"] == 0.0092  # 百分比轉小數
        assert p.last_source == "mcp"

    def test_institutional_success(self):
        p, fb = self._make(results={
            "get_institutional_investors": {"data": {"market": "tse", "date": "2026-08-11",
                "rows": [{"code": "2330", "foreign_net": 100, "investment_net": -20,
                          "dealer_net": 5, "dealer_self_net": 1, "dealer_hedge_net": 4,
                          "total_net": 85}]}},
        })
        rows = p.fetch_institutional_flows()
        assert len(rows) == 1
        assert rows[0]["stock_id"] == "2330"
        assert rows[0]["foreign_investors_net"] == 100
        assert rows[0]["sity_investors_net"] == -20
        assert p.last_source == "mcp"

    def test_margin_success(self):
        p, fb = self._make(results={
            "get_margin_trading": {
                "2330": {"data": {"code": "2330", "margin_buy": 179000,
                    "margin_sell": 862000, "margin_balance": 29070000, "short_sell": 0,
                    "short_buy": 2000, "short_balance": 30000},
                    "_lineage": {"data_date": "2026-08-11"}},
                "2308": {"data": {"code": "2308", "margin_buy": 968000,
                    "margin_sell": 797000, "margin_balance": 9053000, "short_sell": 4000,
                    "short_buy": 8000, "short_balance": 47000},
                    "_lineage": {"data_date": "2026-08-11"}},
            },
        })
        rows = p.fetch_margin_trading_detailed()
        assert len(rows) == 2  # 2330 + 2308（0050 降級）
        assert rows[0]["trade_date"] == "2026-08-11"  # 從 lineage 補
        assert rows[0]["margin_balance"] == 29070000
        assert p.last_source == "mcp"

    # ---- 降級路徑（連線失敗 → fallback） ----
    def test_fallback_on_connection_error(self):
        p, fb = self._make(fail_tools={"get_valuation_ratios"})
        val = p.fetch_valuations(["2330"])
        assert val["2330"]["pe_ratio"] == 32.0  # fallback 資料
        assert p.last_source == "direct(fallback)"
        assert "get_valuation_ratios" in (p.last_fallback_reason or "")

    def test_etf_auto_fallback(self):
        """0050（ETF）非 mcp Symbol Registry → 自動降級 direct。"""
        p, fb = self._make()
        rows = p.fetch_watch_stocks_prices()
        # 0050 走 fallback（fake 回傳 0050 列）；2330/2308 mcp 無結果不產生列
        assert len(rows) == 1 and rows[0]["stock_id"] == "0050"
        assert "fetch_watch_stocks_prices" in fb.calls
        # 2330/2308 無 mcp 資料（fake 空結果）不產生列；0050 降級有資料
        assert p.last_source == "direct(fallback)"

    def test_index_always_fallback(self):
        p, fb = self._make()
        idx = p.fetch_market_index()
        assert idx["close"] == 44928.76
        assert p.last_source == "direct(fallback)"

    def test_hist_index_always_fallback(self):
        p, fb = self._make()
        rows = p.fetch_historical_index(years=1)
        assert rows[0]["trade_date"] == "2026-08-10"
        assert p.last_source == "direct(fallback)"

    def test_hist_daily_fallback(self):
        p, fb = self._make(fail_tools={"get_stock_daily_kline"})
        rows = p.fetch_historical_daily_prices("2330", "2026-08-01", "2026-08-05")
        assert rows[0]["stock_id"] == "2330"
        assert p.last_source == "direct(fallback)"

    # ---- 歷史 kline 逐月 + 過濾 ----
    def test_hist_daily_monthly_calls(self):
        p, fb = self._make(results={
            "get_stock_daily_kline": {"data": [
                {"timestamp": "2026-07-01", "open": 1, "high": 2, "low": 0.5,
                 "close": 1.5, "volume": 100, "amount": 10000},
                {"timestamp": "2026-07-02", "open": 1.2, "high": 2.2, "low": 0.6,
                 "close": 1.7, "volume": 120, "amount": 12000},
            ]},
        })
        rows = p.fetch_historical_daily_prices("2330", "2026-07-01", "2026-07-01")
        assert len(rows) == 1  # 只留 07-01
        assert rows[0]["trade_date"] == "2026-07-01"
        tools = [c[0] for c in p._client.calls]
        assert tools.count("get_stock_daily_kline") == 1

    # ---- MOPS（T022 預留） ----
    def test_monthly_revenue_mcp(self):
        p, fb = self._make(results={
            "get_monthly_revenue": {"data": [
                {"year_month": "2026-07", "revenue": 100, "mom_change": 1.0, "yoy_change": 2.0}]},
        })
        rows = p.fetch_monthly_revenue_batch("2330", months=36)
        assert rows[0]["year_month"] == "2026-07"
        assert rows[0]["revenue"] == 100

    def test_dividends_mcp(self):
        p, fb = self._make(results={
            "get_dividend_history": {"data": [
                {"year": 2025, "ex_date": "2025-07-01", "cash_dividend": 3.0}]},
        })
        rows = p.fetch_dividends("2330")
        assert rows[0]["year"] == 2025
        assert rows[0]["cash_dividend"] == 3.0

    def test_quarterly_financials_mcp(self):
        p, fb = self._make(results={
            "get_financial_statements": {"data": [
                {"fiscal_quarter": "2026Q2", "eps": 5.0}]},
        })
        rows = p.fetch_quarterly_financials_batch("2330", max_quarters=20)
        assert rows[0]["fiscal_quarter"] == "2026Q2"
        assert rows[0]["eps"] == 5.0


class TestMcpClientUnit:
    """McpClient 純邏輯測試（不需真實 server）。"""

    def test_unwrap_tool_result(self):
        from tw_quant_signal.provider.mcp_client import McpClient
        result = {"content": [{"type": "text", "text": '{"data": {"close": 1}}'}]}
        assert McpClient._unwrap_tool_result(result) == {"data": {"close": 1}}

    def test_unwrap_is_error(self):
        from tw_quant_signal.provider.mcp_client import McpClient, McpToolError
        result = {"content": [{"type": "text", "text": "boom"}], "isError": True}
        with pytest.raises(McpToolError):
            McpClient._unwrap_tool_result(result)

    def test_unwrap_non_json(self):
        from tw_quant_signal.provider.mcp_client import McpClient
        result = {"content": [{"type": "text", "text": "plain text"}]}
        out = McpClient._unwrap_tool_result(result)
        assert out["_raw_text"] == "plain text"
