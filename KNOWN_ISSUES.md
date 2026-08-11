# KNOWN_ISSUES

## T022 — MOPS 遷移至 tw-quant-mcp 已知問題與決策記錄

### 1. 季報（financials）mcp 覆蓋缺口 → YfinanceProvider 保留（S3 結論）

`get_financial_statements`（tw-quant-mcp，MOPS 來源）實測：
- **有資料**：2308（2026Q2 income/profit_ratios/balance_sheet 完整）
- **無資料（isError「無損益表摘要資料」）**：2330、1101、2317 等——推測為 tw-quant-mcp 端 T014 MOPS 財報快取對部分公司缺失（非 signal 側問題）

**結論**：mcp 無法完全取代 yfinance 的季報來源。
- `McpDataProvider.fetch_quarterly_financials_batch` 對 mcp 失敗公司自動降級至 `direct(fallback)`（YfinanceProvider）
- **YfinanceProvider 不標記 deprecated**，保留為季報 fallback
- 已記錄於 mcp_provider.py docstring 與本文件

### 2. 股利（dividends）兩來源口徑差異

- **mcp（MOPS 官方）**：`dividend_year` 為民國年（如 115 → 2026），語意為「股利所屬年度（盈餘年度）」，僅提供官方現行 2 年，無 ex_date/cash_yield
- **yfinance**：以除息實際日期歸年（ex_date 2026-03-17 → 2026 年），提供 5 年歷史 + ex_date/close_before_ex/cash_yield
- 範例：2330 民國 115 年（mcp）現金股利 7 元 vs yfinance 2026 年（除息年）12 元——**兩者數值不同因歸屬年度定義不同，非資料錯誤**
- dividends 表 PK(stock_id, year)：mcp 寫入後再以 yfinance 補充 ex_date/yield 時，同 year 會覆寫（upsert），需注意口徑混用風險

### 3. 月營收 mom_change 補算

mcp `get_monthly_revenue` 直接提供 MOPS 官方 `mom_change_pct/yoy_change_pct`，與 direct 版自行由前月相減計算的 `mom_change` 可能差 0.01~0.02（四捨五入差異），非錯誤。

### 4. MOPS 限流（S4）

- tw-quant-mcp 已實作 Per-Source Token Bucket 限流（`RATE_LIMIT_ENABLED`、`RATE_LIMIT_<HOST>_EVERY`，見 tw-quant-mcp README §4.4/§5.3）
- mcp 模式由 tw-quant-mcp 統一限流與 L2 快取（同 symbol 重複呼叫為 cache hit，無額外 HTTP）
- signal 在 mcp 模式下不再直接打 MOPS → 無雙倍流量風險
- direct 模式（未遷移路徑）維持原 twse_client 限流策略（`_MOPS_CONCURRENCY=3` 併發 + cookie session）

### 5. bs4 依賴

遷移後 twse_client 的 MOPS HTML 解析路徑仍在（direct 模式使用），**bs4 暫不移除**。
僅當後續 direct 模式完全移除時可考慮移除依賴。
