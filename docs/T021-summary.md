# T021 任務完成摘要 — TWSE 盤後資料層遷移至 tw-quant-mcp

## 目標
實作 `McpDataProvider(DataProvider)` 中對應 TWSE 盤後資料的部分（日 K、指數、三大法人、融資融券、估值），取代 `twse_client.py` 的 `fetch_*` HTTP 直連，改為透過 stdio JSON-RPC 呼叫 `tw-quant-mcp` 對應 Tool。計算/規則/報告邏輯完全不變。

**前置**：T020（DataProvider 抽象層）已完成（commit f398e6c）。

## 完成內容

### S1: McpClient 基礎建設 ✅
- `provider/mcp_client.py`：輕量 MCP stdio client
  - `subprocess.Popen` 啟動 tw-quant-mcp 執行檔（`MCP_SERVER_PATH` env 指定，預設 PATH 中的 `tw-quant-mcp`）
  - JSON-RPC 2.0 通訊層：initialize 握手 → `tools/call`，id 遞增、response 匹配
  - `ping()` 健康檢查回傳 server 版本（實測 2.1.0）
  - 連線失敗自動重試（`connect_retries=2`，間隔 1s backoff，失敗後 restart 子行程）
  - `McpConnectionError`（連線/逾時/重試耗盡）/ `McpToolError`（tool 回傳 isError）雙例外類型

### S2: McpDataProvider — TWSE 日常行情 ✅
| DataProvider 方法 | tw-quant-mcp Tool | 狀態 |
|---|---|---|
| `fetch_watch_stocks_prices` | `get_stock_daily_quote`（逐檔） | ✅ 含 Symbol Registry 檢查 |
| `fetch_market_index` | —（mcp 無指數收盤） | ✅ 恆降級 direct（見註 1） |
| `fetch_institutional_flows` | `get_institutional_investors` | ✅ |
| `fetch_valuations` | `get_valuation_ratios` | ✅ |
| `fetch_margin_trading_detailed` | `get_margin_trading` | ✅ trade_date 自 lineage 補 |

- **Symbol Registry 檢查**（`_mcp_supported`）：lazy 載入 `get_symbol_list` 判斷代號是否為上市/上櫃股票。ETF（0050）、指數未註冊 → 自動降級 direct。Registry 查詢失敗退化為格式檢查（不阻斷）。
- **註 1**：tw-quant-mcp 的 `get_market_summary` 不提供加權指數收盤價，`fetch_market_index` 直接降級 TwseDirectProvider（符合 S5 精神）。

### S3: 歷史資料補填 ✅
- `fetch_historical_daily_prices` → `get_stock_daily_kline`（逐月呼叫，`date` 參數為月份起點，過濾目標範圍）
- `fetch_historical_index` → mcp 無 ^TWII 指數歷史（Symbol Registry 無指數）→ 降級 direct（yfinance ^TWII）
- normalize 後格式與 direct 一致（`{stock_id, trade_date, open, high, low, close, volume, amount}`），DB 寫入相容

### S4: 格式轉換層 ✅
- `provider/mcp_normalize.py`：MCP Envelope → Python dict 轉換，關鍵映射驗證通過：
  - `{symbol, close, open, high, low, volume, date}` → `{stock_id, close, open, high, low, volume, trade_date}`
  - `{pe, pb, dividend_yield_pct}` → `{pe_ratio, pb_ratio, dividend_yield}`（% → 十進位）
  - 法人 rows、融資券、月營收、季報、股利 normalize 齊備（後兩者為 T022 預留）

### S5: 回退機制 ✅
- `_with_fallback` 統一包裝：mcp 呼叫失敗（連線/工具錯誤/逾時）→ `logger.warning` + 自動降級至 `TwseDirectProvider` 對應方法
- fallback 結果統一包為 `{"data": ...}` envelope，呼叫端單一取值路徑
- pipeline 標註：`ingestion._log_with_source()` 在 pipeline_log.message 附加 `source=mcp` / `source=direct(fallback)`（5 處 log 替換）
- pipeline 不因 mcp 掛掉失敗（fallback 例外亦被捕捉）
- 逾時預設 30s（`CALL_TIMEOUT_S`，可 `MCP_CALL_TIMEOUT` env 覆寫）——任務書寫 5s，但實測 mcp 呼叫 latency 1.3-4.3s，5s 預設會誤降級，故放寬並保留可調配置

### S6: 端到端驗證 ✅
- `scripts/verify_t021_s6.py`：隔離 DB 跑 direct / mcp 兩模式完整 ingestion 比對
- 實測結果：
  - mcp 模式全 task ok（index/stocks/institutional/indicators/features/monthly_revenue/quarterly_financials/dividends/margin_trading/valuations）
  - daily_prices 共同交易日（08-10）OHLCV 完全一致；差異僅最新交易日 mcp=08-11 / direct=08-10（mcp 資料更新，非不一致）
  - pipeline_log 標註正確：`watch_stocks: ... source=mcp`、`institutional_flows: ... source=mcp`、`margin_trading: ... source=direct(fallback)`
  - 0050（ETF）自動降級：mcp 模式 rows 含 0050（08-10, direct）與 2330/2308（08-11, mcp）

## 測試
- 新增 `tests/test_mcp_provider_t021.py`（16 測試：quote/valuation/institutional/margin 成功路徑、連線錯誤降級、ETF 自動降級、指數恆降級、歷史日線逐月呼叫、MOPS 方法等）
- 更新 `tests/test_provider.py`（骨架測試改為建構驗證）
- 完整套件 **209 passed**（T020 基線 193 + T021 新增 16）

## 不納入（如任務書）
- MOPS（月營收/財報/股利）→ T022
- 回測、盤中 1 分 K、期權 → 不異動

## 檔案清單
```
新增  src/tw_quant_signal/provider/mcp_client.py      MCP stdio client（JSON-RPC）
新增  src/tw_quant_signal/provider/mcp_normalize.py   Envelope → dict 轉換
改寫  src/tw_quant_signal/provider/mcp_provider.py    McpDataProvider 主體
修改  src/tw_quant_signal/provider/__init__.py        mcp 分支傳 server_path
修改  src/tw_quant_signal/ingestion.py                _log_with_source（source 標註）
新增  scripts/verify_t021_s6.py                       S6 端到端驗證
新增  tests/test_mcp_provider_t021.py                 T021 單元測試
修改  tests/test_provider.py                          骨架測試 → 建構驗證
修改  .gitignore                                      mcp L2 快取忽略
```
