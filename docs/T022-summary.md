# T022 摘要 — MOPS/基本面資料層遷移至 tw-quant-mcp

## 目標
將 MOPS（月營收、財報三表、股利）及 yfinance 補充（季度財報）的資料擷取遷移至 `tw-quant-mcp`，使 tw-quant-signal 原始資料層全數經過 DataProvider 抽象層，mcp 模式可全量運行。

## 實作內容

### S1: McpDataProvider — MOPS 三方法實作
- `fetch_monthly_revenue_batch` → `get_monthly_revenue`（MOPS t187ap05_L）
- `fetch_dividends` → `get_dividend_history`（官方股利年度，民國年）
- `fetch_quarterly_financials_batch` → `get_financial_statements`（income/profit_ratios/balance_sheet）

### S2: 格式轉換（mcp_normalize.py 擴充）
- `normalize_monthly_revenue`：`rows[].data_year_month`（民國/西元 6 位）→ `year_month`（YYYY-MM）；`mom_change_pct/yoy_change_pct` → `mom_change/yoy_change`
- `normalize_dividends`：`years[].dividend_year`（民國，如 "115"）→ `year`（西元 2026，+1911）；`cash_dividend/stock_dividend` 映射
- `normalize_financials`：`income[] + profit_ratios[] + balance_sheet{}` → `fiscal_quarter/eps/revenue/gross_margin/roe/roa`；ROE/ROA 自 net_income/total_equity/total_assets 計算（與 yfinance 同公式）
- 民國→西元年月轉換 helper：5 位數字（"11507"）→ 民國，6 位（"202607"）→ 西元

### S3: YfinanceProvider 保留（不 deprecated）
交叉比對結論（詳見 KNOWN_ISSUES.md）：
- mcp 月營收/股利為官方資料，優於 yfinance
- **但 `get_financial_statements` 對部分公司無資料**（2330/1101/2317 實測「無損益表摘要資料」；2308 正常）——tw-quant-mcp 端 T014 快取缺口
- yfinance 股利含 ex_date/close_before_ex/cash_yield（mcp 無），季報歷史較完整
- → **YfinanceProvider 保留為 fallback**，mcp 失敗自動降級 `direct(fallback)`

### S4: 限流相容
- tw-quant-mcp 內建 Per-Source Token Bucket 限流（`RATE_LIMIT_ENABLED`/`RATE_LIMIT_<HOST>_EVERY`）
- mcp 模式由 tw-quant-mcp 統一限流 + L2 快取，signal 不再直接打 MOPS → 無雙倍流量

### S5: Pipeline 驗證（scripts/verify_t022_s5.py）
隔離 DB + mcp 模式跑完整 ingestion：10 task 全 ok
- monthly_revenue: 2 筆（2330/2308 2026-07）
- quarterly_financials: 8 筆（2308 2026Q2 mcp + 2330 2025Q1-2026Q2 yfinance fallback）
- dividends: 8 筆（0050 yfinance 5 年含 ex_date/yield + 2330/2308 mcp 官方）

## 關鍵 Bug 修復
1. **民國年雙重轉換**：fallback（yfinance）已含西元年，mcp 路徑再 normalize 會 2026→3937。修復：三方法以 payload 結構區分（mcp envelope 有 rows/years/income key 才 normalize，fallback list 直接回傳）
2. **balance_sheet 為單期 dict 非 list**：normalize 需同時支援 dict/list（`_as_rows` helper）

## 測試
211 passed（209 + 2 新增：financials 降級、dividends 不重複 normalize）

## 收尾
- commit: 待填
- 任務書 T022 frontmatter status:done + checkbox 全勾
- README.md Phase 4 T022 段落
- KNOWN_ISSUES.md 已建（S3 結論 + 限流 + bs4 依賴評估）
