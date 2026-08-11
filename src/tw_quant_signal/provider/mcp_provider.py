"""McpDataProvider — 透過 tw-quant-mcp 取得資料（T021 TWSE 盤後 / T022 MOPS）。

實作 DataProvider 抽象介面，所有資料改由 tw-quant-mcp 的 stdio JSON-RPC
提供（取代 twse_client 的 HTTP 直連）。上層模組（IngestionEngine /
features / backtest / backfill）無需任何變更——介面與 TwseDirectProvider
完全一致（零行為變更）。

降級機制（S5）：任何 mcp 呼叫失敗（連線錯誤 / 工具錯誤 / 逾時）時，
自動降級至 TwseDirectProvider 的對應方法，並回傳降級資訊供 pipeline log
記錄資料來源。pipeline 不會因 mcp 掛掉而失敗。

架構：
- 單一 McpClient 共享實例（lazy 建立）
- 對應 tool 名稱與 normalize 轉換集中在 mcp_normalize.py
- 本類別只管「呼叫 + 降級」，不做計算邏輯
"""

from __future__ import annotations

import logging
import os
from datetime import date

from . import mcp_normalize as norm
from .base import DataProvider

logger = logging.getLogger(__name__)

_DEFAULT_CALL_TIMEOUT = float(os.getenv("MCP_CALL_TIMEOUT", "30"))


class McpDataProvider(DataProvider):
    """對接 tw-quant-mcp 的資料提供者。

    Parameters
    ----------
    server_path:
        tw-quant-mcp 執行檔路徑；None 時依 ``MCP_SERVER_PATH`` env 或 PATH。
    call_timeout:
        單次 tool 呼叫逾時（秒）；超過視為連線失敗並降級。
    fallback_provider:
        降級目標；預設 TwseDirectProvider。測試可注入 fake。
    """

    def __init__(
        self,
        server_path: str | None = None,
        call_timeout: float = _DEFAULT_CALL_TIMEOUT,
        fallback_provider: DataProvider | None = None,
    ):
        from .mcp_client import McpClient, McpConnectionError, McpToolError  # lazy

        self._McpConnectionError = McpConnectionError
        self._McpToolError = McpToolError
        self._client = McpClient(
            server_path=server_path,
            call_timeout=call_timeout,
        )
        if fallback_provider is None:
            from .twse_direct import TwseDirectProvider

            fallback_provider = TwseDirectProvider()
        self._fallback = fallback_provider
        self._last_source: str | None = None  # "mcp" / "direct(fallback)"
        self._last_fallback_reason: str | None = None
        self._symbols: set[str] | None = None  # lazy 載入 Symbol Registry

    # ------------------------------------------------------------------ #
    # 內部工具
    # ------------------------------------------------------------------ #
    @property
    def client(self):
        """暴露 McpClient（供測試 / 健康檢查）。"""
        return self._client

    @property
    def last_source(self) -> str | None:
        return self._last_source

    @property
    def last_fallback_reason(self) -> str | None:
        return self._last_fallback_reason

    def _call(self, tool: str, arguments: dict | None = None) -> dict:
        """呼叫 mcp tool；連線層失敗時重試，最終拋 McpConnectionError。"""
        return self._client.call_tool(tool, arguments or {})

    def _with_fallback(self, tool: str, arguments: dict, fb):
        """嘗試 mcp；失敗自動降級至 fallback（S5）。

        fb: callable(fallback_provider) → 回傳值
        回傳值統一為 mcp envelope 結構（含 "data" key），
        呼叫端一律以 data.get("data") 取值。
        """
        try:
            out = self._call(tool, arguments)
            self._last_source = "mcp"
            self._last_fallback_reason = None
            return out
        except (self._McpConnectionError, self._McpToolError) as exc:
            logger.warning("MCP %s 失敗，降級至 direct: %s", tool, exc)
            self._last_source = "direct(fallback)"
            self._last_fallback_reason = f"{tool}: {exc}"
            return {"data": fb(self._fallback)}

    # ------------------------------------------------------------------ #
    # TWSE 盤後（T021 S2）
    # ------------------------------------------------------------------ #
    def _mcp_supported(self, sid: str) -> bool:
        """tw-quant-mcp 是否支援該代號。

        上市/上櫃股票（4-6 位數字代號）且已註冊於 Symbol Registry；
        ETF（如 0050）、指數（^TWII）未註冊，需降級 TwseDirectProvider（S5）。
        Registry 查詢失敗時退化為格式檢查（不阻斷降級機制）。
        """
        if not (sid.isdigit() and 4 <= len(sid) <= 6):
            return False
        if self._symbols is None:
            try:
                out = self._call("get_symbol_list", {})
                payload = out.get("data") if isinstance(out, dict) else out
                if isinstance(payload, list):
                    self._symbols = {str(r.get("code", "")) for r in payload}
                elif isinstance(payload, dict):
                    # 部分版本回傳 {tse: [...], otc: [...]}
                    self._symbols = {
                        str(r.get("code", ""))
                        for r in payload.get("tse", []) + payload.get("otc", [])
                    }
                else:
                    self._symbols = set()
            except Exception as exc:  # registry 查詢失敗不阻斷
                logger.warning("get_symbol_list 失敗，退化为格式檢查: %s", exc)
                self._symbols = set()
        return sid in self._symbols

    def fetch_watch_stocks_prices(self) -> list[dict]:
        results = []
        for sid in self.watch_stocks:
            if not self._mcp_supported(sid):
                # ETF/非上市代號 → 降級 direct（mcp 無此資料）
                self._last_source = "direct(fallback)"
                self._last_fallback_reason = f"get_stock_daily_quote: symbol {sid} 非上市/上櫃，mcp 不支援"
                row = self._fallback_fetch_one(sid)
                if row:
                    results.append(row)
                continue
            try:
                out = self._call("get_stock_daily_quote", {"symbol": sid})
                payload = out.get("data") if isinstance(out.get("data"), dict) else out
                row = norm.normalize_daily_quote(payload, sid)
                if row.get("trade_date") and row.get("close") is not None:
                    results.append(row)
                    self._last_source = "mcp"
                    self._last_fallback_reason = None
            except (self._McpConnectionError, self._McpToolError) as exc:
                logger.warning("MCP get_stock_daily_quote(%s) 失敗，降級至 direct: %s", sid, exc)
                self._last_source = "direct(fallback)"
                self._last_fallback_reason = f"get_stock_daily_quote: {exc}"
                row = self._fallback_fetch_one(sid)
                if row:
                    results.append(row)
        return results

    def _fallback_fetch_one(self, sid: str) -> dict | None:
        """從 direct provider 抓單一股票當日行情（用 fetch_watch_stocks_prices 篩選）。"""
        try:
            rows = self._fallback.fetch_watch_stocks_prices()
        except Exception as exc:  # fallback 失敗不能拖垮 pipeline
            logger.error("direct fallback fetch_watch_stocks_prices 失敗: %s", exc)
            return None
        for r in rows:
            if r.get("stock_id") == sid:
                return r
        return None

    def fetch_market_index(self) -> dict | None:
        # 指數未註冊於 mcp Symbol Registry → 一律降級 direct
        # （mcp 的 get_market_summary 無指數收盤價欄位）
        self._last_source = "direct(fallback)"
        self._last_fallback_reason = "get_stock_daily_quote: symbol ^TWII 非上市/上櫃，mcp 不支援"
        return self._fallback.fetch_market_index()

    def fetch_institutional_flows(self, trade_date: str | None = None) -> list[dict]:
        args = {"market": "tse"}
        if trade_date:
            args["date"] = trade_date
        data = self._with_fallback(
            "get_institutional_investors", args,
            lambda p: p.fetch_institutional_flows(trade_date),
        )
        payload = data.get("data") if isinstance(data, dict) else data
        if isinstance(payload, dict) and payload.get("rows"):
            # mcp envelope：rows 列表
            return norm.normalize_institutional_rows(payload)
        if isinstance(payload, list) and payload and "code" in payload[0]:
            # mcp envelope rows（部分版本直接列 rows）
            return norm.normalize_institutional_rows({"rows": payload})
        # fallback 已 normalized list（含 stock_id）
        return list(payload) if isinstance(payload, list) else []

    def fetch_valuations(self, stock_ids: list[str] | None = None) -> dict[str, dict]:
        ids = stock_ids or self.watch_stocks
        result: dict[str, dict] = {}
        for sid in ids:
            data = self._with_fallback(
                "get_valuation_ratios", {"symbol": sid},
                lambda p, s=sid: p.fetch_valuations([s]),
            )
            payload = data.get("data") if isinstance(data, dict) else data
            if isinstance(payload, dict) and payload.get("symbol"):
                # mcp envelope：需 normalize
                row = norm.normalize_valuation(payload, sid)
                result[sid] = row
            elif isinstance(payload, dict) and sid in payload:
                # fallback 已 normalized dict（{sid: {...}}）
                result[sid] = payload[sid]
        return result

    def fetch_margin_trading_detailed(
        self, trade_date: str | None = None
    ) -> list[dict]:
        rows = []
        for sid in self.watch_stocks:
            if not self._mcp_supported(sid):
                self._last_source = "direct(fallback)"
                self._last_fallback_reason = f"get_margin_trading: symbol {sid} 非上市/上櫃，mcp 不支援"
                rows.extend(
                    r for r in self._fallback.fetch_margin_trading_detailed(trade_date)
                    if r.get("stock_id") == sid
                )
                continue
            args = {"symbol": sid}
            if trade_date:
                args["date"] = trade_date
            try:
                out = self._call("get_margin_trading", args)
                payload = out.get("data") if isinstance(out.get("data"), dict) else out
                if isinstance(payload, dict) and payload.get("code"):
                    # mcp 回傳無 date 欄位 → 從 lineage data_date 補
                    mcp_date = payload.get("date") or out.get("_lineage", {}).get("data_date", "")
                    rows.append(norm.normalize_margin_trading(payload, sid, mcp_date))
                    self._last_source = "mcp"
                    self._last_fallback_reason = None
            except (self._McpConnectionError, self._McpToolError) as exc:
                logger.warning("MCP get_margin_trading(%s) 失敗，降級至 direct: %s", sid, exc)
                self._last_source = "direct(fallback)"
                self._last_fallback_reason = f"get_margin_trading: {exc}"
                rows.extend(
                    r for r in self._fallback.fetch_margin_trading_detailed(trade_date)
                    if r.get("stock_id") == sid
                )
        return rows

    # ------------------------------------------------------------------ #
    # 歷史資料（T021 S3）
    # ------------------------------------------------------------------ #
    def fetch_historical_daily_prices(
        self, stock_id: str, start_date: str, end_date: str
    ) -> list[dict]:
        """逐月呼叫 get_stock_daily_kline（mcp 的 date 為月份起點），再過濾日期範圍。"""
        rows: list[dict] = []
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
        cursor = start.replace(day=1)
        while cursor <= end:
            month_start = cursor.isoformat()
            try:
                out = self._call(
                    "get_stock_daily_kline",
                    {"symbol": stock_id, "period": "day", "date": month_start},
                )
                self._last_source = "mcp"
                self._last_fallback_reason = None
            except (self._McpConnectionError, self._McpToolError) as exc:
                logger.warning("MCP get_stock_daily_kline(%s) 失敗，降級至 direct: %s", stock_id, exc)
                self._last_source = "direct(fallback)"
                self._last_fallback_reason = f"get_stock_daily_kline: {exc}"
                return self._fallback.fetch_historical_daily_prices(
                    stock_id, start_date, end_date
                )
            payload = out.get("data") if isinstance(out, dict) else out
            rows.extend(
                r for r in norm.normalize_daily_kline(payload, stock_id)
                if start_date <= r.get("trade_date", "") <= end_date
            )
            # 下個月
            next_month = cursor.month + 1
            cursor = cursor.replace(
                year=cursor.year + next_month // 12,
                month=(next_month - 1) % 12 + 1,
            )
        return rows

    def fetch_historical_index(self, years: int = 5) -> list[dict]:
        # 指數未註冊於 mcp Symbol Registry → 一律降級 direct
        self._last_source = "direct(fallback)"
        self._last_fallback_reason = "get_stock_daily_kline: symbol ^TWII 非上市/上櫃，mcp 不支援"
        return self._fallback.fetch_historical_index(years=years)

    # ------------------------------------------------------------------ #
    # MOPS（T022 S2）
    # ------------------------------------------------------------------ #
    def fetch_monthly_revenue_batch(
        self,
        stock_id: str,
        months: int = 36,
        incremental: bool = False,
        db=None,
    ) -> list[dict]:
        data = self._with_fallback(
            "get_monthly_revenue", {"symbol": stock_id},
            lambda p: p.fetch_monthly_revenue_batch(
                stock_id, months=months, incremental=incremental, db=db
            ),
        )
        payload = data.get("data") if isinstance(data, dict) else data
        rows = norm.normalize_monthly_revenue(payload, stock_id) if isinstance(payload, list) else []
        if months:
            rows = rows[:months]
        return rows

    def fetch_quarterly_financials_batch(
        self, stock_id: str, max_quarters: int = 20
    ) -> list[dict]:
        data = self._with_fallback(
            "get_financial_statements", {"symbol": stock_id},
            lambda p: p.fetch_quarterly_financials_batch(stock_id, max_quarters=max_quarters),
        )
        payload = data.get("data") if isinstance(data, dict) else data
        rows = norm.normalize_financials(payload, stock_id) if isinstance(payload, list) else []
        return rows[:max_quarters] if max_quarters else rows

    def fetch_dividends(self, stock_id: str) -> list[dict]:
        data = self._with_fallback(
            "get_dividend_history", {"symbol": stock_id},
            lambda p: p.fetch_dividends(stock_id),
        )
        payload = data.get("data") if isinstance(data, dict) else data
        return norm.normalize_dividends(payload, stock_id) if isinstance(payload, list) else []
