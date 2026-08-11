# T020 任務完成摘要 — DataProvider 抽象層設計

## 目標
建立統一 `DataProvider` 抽象層，封裝所有市場/法人/估值/財務資料的取得方式，使上層模組（pipeline / features / backtest / scorecard）不依賴具體資料來源實現，為後續遷移至 tw-quant-mcp（T021/T022）奠定介面契約。

**性質**：零行為變更的純重構。tw-quant-signal 保留決策層（規則引擎 / 四燈號 / 回測框架 / 11 大指標），資料層透過抽象介面存取。

## 完成內容

### S1: DataProvider 基底介面 ✅
- 建立 `src/tw_quant_signal/provider/` 目錄（`base.py` / `twse_direct.py` / `yfinance_provider.py` / `mcp_provider.py` / `__init__.py`）
- `DataProvider(ABC)` 定義 10 個 `fetch_*` 抽象方法簽名（行情/指數/法人/估值/融資融券/月營收/季報/股利/歷史指數/歷史日線）
- 新增 `watch_stocks` property（預設自 config，子類可覆寫注入）

### S2: TwseDirectProvider ✅
- `twse_client.py` 的 `fetch_*` 函式群封裝為 `TwseDirectProvider(DataProvider)`，內部以 lazy import 委派至 twse_client（零行為變更）
- `twse_client.py` 保留為內部實作（函式仍在，供 provider 呼叫；WATCH_STOCKS re-export 維持向後相容）
- `WATCH_STOCKS` 常數移置 `config.py`（規範定義位置），`provider/__init__.py` 與 `twse_client.py` re-export

### S3: YfinanceProvider ✅
- yfinance 相關（`fetch_yf_quarterly_financials_batch` / `fetch_yf_financials` / 股利）封裝為 `YfinanceProvider(DataProvider)`
- 作為 TwseDirectProvider 的補充提供者；TWSE 方法拋 NotImplementedError（避免誤用）
- ingestion 原 `_fetch_dividends_yf` 搬遷至 provider（行為不變，yfinance 缺省時 graceful 回傳 []）

### S4: Provider 註冊與工廠 ✅
- `create_data_provider(mode=None)` 支援 `"direct"`（TwseDirect+Yfinance）/ `"mcp"`（McpDataProvider 骨架，T021/T022 實作）
- 環境變數 `TW_QUANT_DATA_PROVIDER=direct|mcp` 切換；非法模式拋 ValueError
- `McpDataProvider` 各方法拋 NotImplementedError 明確標示未實作

### S5: 上游模組遷移 ✅
- `ingestion.py:IngestionEngine(db, provider=None)` 改接收 DataProvider 實例；所有 fetch 呼叫改為 `self.provider.*`；觀察清單改由 `provider.watch_stocks` 取得
- `features.py`：`compute_all_features` 的估值兜底改為 `create_data_provider().fetch_valuations()`
- `backtest.py`：`_watch_stocks()` 改由 `create_data_provider().watch_stocks` 提供
- `backfill.py`：模組級 `_provider = create_data_provider()`，歷史/法人抓取全走 provider

### S6: 向後相容 ✅
- git worktree 對比：HEAD（e53cc27）179 passed = 新版 193 passed（direct 模式行為一致）
- 新增 `tests/test_provider.py`（14 個測試）：抽象類別、工廠模式、env 切換、委派、補充提供者限制、mcp 骨架

## 驗證結果
- 全部單元測試：**193 passed**（含新增 14 個 provider 測試）
- `TW_QUANT_DATA_PROVIDER=direct` 環境變數切換驗證通過（direct→TwseDirectProvider / mcp→McpDataProvider / 非法→ValueError）
- `IngestionEngine(db)` 舊呼叫方式相容（預設 direct provider）；自訂 watch_stocks 注入可行
- ruff 自動修復已完成（import 排序 / PEP 604 型別），殘餘為既有程式碼風格問題（DTZ/BLE001 等，非本次引入）

## 備註
- T021/T022 可於本介面契約上直接實作 McpDataProvider（替換資料層不需改動上層）
- T016「valuation 重複呼叫消除」模式已可套用：provider 層快取全國估值一次
- 未改動：health_check.py 仍直接使用 twse_client 特殊函式（fetch_monthly_revenue / fetch_margin_data 不在 DataProvider 介面內，屬既有用途保留）
