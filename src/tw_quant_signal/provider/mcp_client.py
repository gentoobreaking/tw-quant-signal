"""McpClient — 輕量 MCP stdio JSON-RPC 2.0 客戶端（T021）。

透過 subprocess 啟動 tw-quant-mcp 執行檔，以 stdio JSON-RPC 2.0 通訊。
僅實作本專案需要的最小集合：initialize / tools/call。

設計要點：
- 單一子行程生命週期：lazy 啟動，首次呼叫時 spawn；連線中斷自動重啟。
- 執行檔路徑：環境變數 ``MCP_SERVER_PATH`` 指定；未設定時依賴 PATH 中的
  ``tw-quant-mcp``。
- 連線失敗重試：``_call`` 在連線層失敗（啟動失敗 / 寫入失敗 / 逾時）時
  重試 2 次，間隔 1s backoff（任務書 S1 規格）。
- 工具層錯誤（server 回傳 error / isError）不重試，交由呼叫端（
  McpDataProvider）降級處理。
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time

logger = logging.getLogger(__name__)

DEFAULT_SERVER_CMD = "tw-quant-mcp"  # 依賴 PATH
INIT_TIMEOUT_S = 10
CALL_TIMEOUT_S = 30
CONNECT_RETRIES = 2  # 連線層重試次數（S1 規格）
RETRY_BACKOFF_S = 1.0
_JSONRPC_VERSION = "2.0"
_PROTOCOL_VERSION = "2024-11-05"


class McpConnectionError(RuntimeError):
    """MCP 連線層錯誤（啟動失敗 / 通訊失敗 / 逾時）。"""


class McpToolError(RuntimeError):
    """MCP 工具層錯誤（server 回傳 error 或 isError）。"""


class McpClient:
    """管理 tw-quant-mcp 子行程的 JSON-RPC 2.0 stdio 客戶端。"""

    def __init__(
        self,
        server_path: str | None = None,
        call_timeout: float = CALL_TIMEOUT_S,
        connect_retries: int = CONNECT_RETRIES,
        retry_backoff: float = RETRY_BACKOFF_S,
    ):
        self.server_path = server_path or os.getenv("MCP_SERVER_PATH") or DEFAULT_SERVER_CMD
        self.call_timeout = call_timeout
        self.connect_retries = connect_retries
        self.retry_backoff = retry_backoff

        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()  # stdio 寫入 + _id 分配
        self._id = 0
        self._server_version: str | None = None
        self._closed = False

    # ------------------------------------------------------------------ #
    # 生命週期
    # ------------------------------------------------------------------ #
    @property
    def server_version(self) -> str | None:
        return self._server_version

    def start(self) -> str:
        """啟動（或重啟）子行程並完成 initialize 握手。回傳 server 版本號。"""
        self._stop_proc()
        logger.info("MCP server 啟動: %s", self.server_path)
        try:
            self._proc = subprocess.Popen(
                [self.server_path],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError as exc:
            raise McpConnectionError(
                f"找不到 MCP server 執行檔: {self.server_path}（可設定 MCP_SERVER_PATH）"
            ) from exc

        result = self._read_response(self._next_id(), "initialize", {
            "protocolVersion": _PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "tw-quant-signal", "version": "1.0"},
        }, timeout=INIT_TIMEOUT_S)
        info = (result or {}).get("serverInfo") or {}
        self._server_version = info.get("version")
        logger.info("MCP server 握手完成: %s v%s", info.get("name"), self._server_version)
        return self._server_version or ""

    def _stop_proc(self) -> None:
        if self._proc is not None:
            try:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
            except Exception as exc:  # 關閉時清理失敗不影響主流程
                logger.debug("stop mcp subprocess: %s", exc)
            self._proc = None

    def close(self) -> None:
        self._closed = True
        self._stop_proc()

    def __enter__(self) -> McpClient:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------------ #
    # 通訊
    # ------------------------------------------------------------------ #
    def _next_id(self) -> int:
        self._id += 1
        return self._id

    def ping(self) -> str:
        """健康檢查：確認子行程存活並回傳 server 版本（S1）。"""
        if self._proc is None or self._proc.poll() is not None:
            self.start()
        return self.server_version or ""

    def _read_response(self, req_id: int, method: str, params: dict, timeout: float) -> dict:
        """寫入一筆 request 並讀取對應 id 的回應（含 Notification 跳過）。"""
        if self._proc is None or self._proc.stdout is None or self._proc.stdin is None:
            raise McpConnectionError("MCP server 未啟動")
        payload = json.dumps({
            "jsonrpc": _JSONRPC_VERSION,
            "id": req_id,
            "method": method,
            "params": params,
        }, ensure_ascii=False)
        try:
            self._proc.stdin.write(payload + "\n")
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise McpConnectionError(f"MCP 寫入失敗: {exc}") from exc

        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise McpConnectionError(f"MCP 呼叫逾時 ({method}, {timeout}s)")
            line = self._proc.stdout.readline()
            if not line:
                raise McpConnectionError(f"MCP server 已關閉 stdout（{method}）")
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue  # 跳過非 JSON 行
            if msg.get("id") != req_id:
                continue  # 跳過 notification / 其他 id
            if "error" in msg and msg.get("error"):
                err = msg["error"]
                code = err.get("code", -1)
                message = err.get("message", "unknown error")
                if code in (-32002, -32001, -32000) and "timeout" in str(message).lower():
                    raise McpConnectionError(f"MCP 工具逾時: {message}")
                raise McpToolError(f"MCP {method} 錯誤 ({code}): {message}")
            result = msg.get("result") or {}
            if method == "tools/call":
                return self._unwrap_tool_result(result)
            return result

    @staticmethod
    def _unwrap_tool_result(result: dict) -> dict:
        """tools/call 的 result 包 content[] 文字 JSON，解出實際資料。"""
        content = result.get("content") or []
        is_error = result.get("isError", False)
        texts = [c.get("text", "") for c in content if c.get("type") == "text"]
        if not texts:
            if is_error:
                raise McpToolError("MCP 工具回傳錯誤（無內容）")
            return {}
        raw = "\n".join(texts)
        if is_error:
            raise McpToolError(f"MCP 工具回傳 isError: {raw[:500]}")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # 非 JSON 的純文字回傳：包成 dict 讓呼叫端可讀
            return {"_raw_text": raw}
        return data

    # ------------------------------------------------------------------ #
    # 對外 API
    # ------------------------------------------------------------------ #
    def call_tool(self, name: str, arguments: dict | None = None) -> dict:
        """呼叫 MCP tool（含連線層重試）。回傳解包後的 dict（data / _lineage 等）。

        重試僅涵蓋連線層失敗（McpConnectionError）；工具層錯誤
        （McpToolError）不重試，直接拋出供上層降級。
        """
        if self._closed:
            raise McpConnectionError("McpClient 已關閉")
        if self._proc is None or self._proc.poll() is not None:
            self.start()
        last_exc: Exception | None = None
        for attempt in range(self.connect_retries + 1):
            try:
                return self._read_response(
                    self._next_id(), "tools/call",
                    {"name": name, "arguments": arguments or {}},
                    timeout=self.call_timeout,
                )
            except McpConnectionError as exc:
                last_exc = exc
                logger.warning("MCP 連線失敗（%s, attempt %d/%d）: %s",
                               name, attempt + 1, self.connect_retries + 1, exc)
                if attempt < self.connect_retries:
                    time.sleep(self.retry_backoff)
                    try:
                        self.start()
                    except McpConnectionError as restart_exc:
                        last_exc = restart_exc
        raise McpConnectionError(f"MCP 連線失敗（已重試 {self.connect_retries} 次）: {last_exc}")
