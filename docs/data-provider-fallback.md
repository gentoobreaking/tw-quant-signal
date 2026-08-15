# 資料源降級機制說明（DataProvider Fallback）

> 適用版本：T020/T021/T022 完成後（commit f398e6c / fe023c8 / 568342d）
> 摘要：mcp 模式（`TW_QUANT_DATA_PROVIDER=mcp`）下，tw-quant-mcp 無法提供的資料由 `McpDataProvider._with_fallback` 自動降級至 `TwseDirectProvider` / `YfinanceProvider`，pipeline 不中斷，且每次降級皆在 `pipeline_log` 標註 `source=direct(fallback)` 並輸出 warning log。

---

## 一、必然降級（結構性：mcp 架構上不支援，寫死在程式碼）

mcp 的 Symbol Registry 僅收錄**上市/上櫃股票（代碼 1101-9999）**，無 ETF、無指數。以下方法一律走 fallback，與 mcp 健康狀態無關：

| 資料 | 方法 | 降級原因 | 降級至 |
|------|------|---------|--------|
| 加權指數收盤 | `fetch_market_index` | 指數 `^TWII` 不在 Symbol Registry；`get_market_summary` 亦無指數收盤價欄位 | direct（TWSE MI_INDEX） |
| 歷史指數 | `fetch_historical_index` | 同上（`get_stock_daily_kline` 亦無指數） | direct（yfinance `^TWII`） |
| ETF 個股行情（0050） | `fetch_watch_stocks_prices` | 0050 不在 registry（非上市/上櫃代號） | direct（TWSE STOCK_DAY_ALL） |
| ETF 融資融券（0050） | `fetch_margin_trading_detailed` | 同上 | direct（TWSE TWT93U） |

> 註：0050 為 WATCH_STOCKS 預設成員（`['2330','0050','2308']`），故日常 ingestion 中必然觸發此降級。

## 二、條件降級（資料缺口/呼叫失敗：mcp 有提供但本次失敗或無資料）

### 2.1 連線/呼叫失敗（逾時、isError、連線中斷）→ direct

| 資料 | 方法 | 觸發條件 | 降級至 |
|------|------|---------|--------|
| 法人買賣超 | `fetch_institutional_flows` | `get_institutional_investors` 報錯/逾時 | direct（TWSE T86） |
| 估值 PE/PB/殖利率 | `fetch_valuations` | `get_valuation_ratios` 報錯/逾時 | direct（BWIBBU_ALL） |
| 歷史日K | `fetch_historical_daily_prices` | `get_stock_daily_kline` 報錯/逾時 | direct（RWD STOCK_DAY，逐月） |
| 月營收 | `fetch_monthly_revenue_batch` | `get_monthly_revenue` 報錯/逾時 | direct（MOPS t187ap05_L） |

### 2.2 資料缺口（mcp 端無該股資料）→ yfinance

| 資料 | 方法 | 觸發條件 | 降級至 |
|------|------|---------|--------|
| 季報三表 | `fetch_quarterly_financials_batch` | **mcp 對該股無損益表資料**（2330/1101/2317 實測「無損益表摘要資料」；2308 正常） | **YfinanceProvider** |
| 股利歷史 | `fetch_dividends` | mcp 報錯/無資料 | **YfinanceProvider**（補 ex_date/cash_yield） |

> 背景：tw-quant-mcp 端 `get_financial_statements` 對部分公司無資料（T014 快取缺口，見 KNOWN_ISSUES.md）。yfinance 的股利含 ex_date/close_before_ex/cash_yield，為 mcp 無之欄位，屬互補而非劣化。

---

## 三、降級判定流程

```
McpDataProvider.fetch_xxx()
  ├─ 非上市/上櫃代號（0050、^TWII）→ 直接 fallback（必然降級）
  ├─ mcp 呼叫成功且有資料 → normalize 後回傳（source=mcp）
  └─ 呼叫失敗（McpConnectionError / McpToolError）
      或 mcp 回傳空/無該股資料 → fallback provider（source=direct(fallback)）
         並記錄 _last_fallback_reason
```

實作細節：
- `_mcp_supported(sid)`：lazy 載入 `get_symbol_list`（上市+上櫃），快取於 `self._symbols`；查詢失敗時退化為格式檢查（4-6 位數字）不阻斷
- fallback 結果一律包成 `{"data": <結果>}`，呼叫端統一 `data.get("data")`；MOPS 三方法另以 payload 結構區分 mcp envelope（含 rows/years/income key）與已 normalized 的 fallback list，避免民國年雙重轉換（曾致 2026→3937，T022 修復）

---

## 四、實跑佐證（T022 S5，隔離 DB + mcp 模式，2026-08-11/12）

```
pipeline_log source 標註：
  watch_stocks         source=mcp（2330/2308）+ direct(fallback)（0050）
  institutional_flows  source=mcp（8 筆）
  margin_trading       source=direct(fallback)（該次 mcp 無回傳）
  valuations           source=mcp（2 筆）
  monthly_revenue      source=mcp（2330/2308 2026-07）
  quarterly_financials 2308 → mcp（2026Q2）；2330 → yfinance fallback（2025Q1-2026Q2）
  dividends            0050 → yfinance fallback（2022-2026 含 ex_date/yield）
                       2330/2308 → mcp（官方股利年度）
```

單檔驗證（T021 S6）：0050 走 direct 回 08-10 收盤 104.25；2330/2308 走 mcp 回 08-11（mcp 比 direct 新一天，為 mcp 優勢非不一致）。

---

## 五、降級可審計性

- **pipeline_log**：每 task 的 message 含 `source=mcp` 或 `source=direct(fallback)`（T021 新增 `_log_with_source`）
- **logger.warning**：每次降級輸出 `MCP <tool>(<sid>) 失敗，降級至 direct: <reason>`
- **McpDataProvider 狀態**：`last_source` / `last_fallback_reason` 記錄最近一次呼叫來源與原因（單元測試覆蓋）

---

## 六、若希望 ETF/指數也走 mcp

屬 tw-quant-mcp 端擴充工作（Symbol Registry 加入 ETF/指數代碼 + 對應資料源），不在 tw-quant-signal 範圍內。現行架構已以降級機制完整兜底，pipeline 不中斷。
