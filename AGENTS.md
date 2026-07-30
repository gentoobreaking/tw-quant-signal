# 台股 AI 訊號系統 — 進度 & 模組參考

## 整體專案目標
- Data → Features → Rules → Signals → Notification 五日內輕量產出 Taiwan stock AI signal system
- 四大燈號 D1/D2/D3/D4 每日打分，Telegram 推播

## 完成進度

### Phase 1 — 資料管線 (T001) ✅
- [x] SQLite schema (6 tables)
- [x] TWSE API 客戶端 (OHLCV, 指數, 法人, 估值)
- [x] yfinance 歷史補填
- [x] 技術指標 (MA/RSI/BB/Volume)
- [x] 四階段日管線 (index, stocks, institutional, indicators)
- [x] Telegram 健康報告
- [x] Config-driven (config.json)
- [x] Cron scheduler (15:00 weekdays)

### Phase 2 — 特徵工程 (T002) ✅
- [x] `features.py` 12+ 條件計算
- [x] MA alignment (bullish/neutral/bearish)
- [x] RSI signal (oversold/bearish/neutral/bullish/overbought)
- [x] BB position (above_upper / at_upper / middle / at_lower / below_lower)
- [x] Volume ratio (current / MA5)
- [x] Institutional flow signals (3d/5d)
- [x] Valuation signals (PE/PB/DY)
- [x] Market breadth (foreign buy ratio)
- [x] Index MA position
- [x] Beta 5d
- [x] Feature stored as JSON in features table
- [x] 週期管線整合

### Phase 3 — 規則引擎 (T003) ✅
- [x] 規則定義於 `configs/rules.yaml` (10 條: R001–R010)
- [x] 支援 AND/OR 條件組合 (`all` / `any`)
- [x] 涵蓋偏多 (R003/R004/R005/R008)、偏空 (R001/R002/R006/R007/R009)、中性 (R010)
- [x] 每條規則含明確觸發條件 + 失效條件
- [x] 歷史觸發統計 (`compute_rule_stats`, 儲存於 `rule_signals` 表)
- [x] 每日自動產出訊號 + 記錄
- [x] 可透過 YAML 設定檔動態調整規則，不需改程式碼

### Phase 4 — 通知 & 串接 (T004)
- [x] Telegram 規則引擎報告 (`send_rules_report` via `build_rules_report`)
- [ ] Token 設定 + 實際測試 Telegram 推播
- [ ] 每條規則歷史統計報告
- [ ] Recommended action text
