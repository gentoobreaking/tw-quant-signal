# T012 結構變化偵測 — 實作完成

**目標**: 監控規則與模型隨時間的衰退，透過滾動勝率、觸發頻率、特徵分布等指標偵測偏移。

## 交付檔案

| 檔案 | 說明 |
|------|------|
| `src/tw_quant_signal/structural_change.py` | 核心模組 (600+ 行) — 4 類偵測 + 報告 + 儲存 |
| `src/tw_quant_signal/db.py` | + `structural_drift` 表 + `get_structural_drift()` 查詢 |
| `src/tw_quant_signal/pipeline.py` | + 結構變化偵測步驟 (含通知推送) |
| `src/tw_quant_signal/api/app.py` | + `GET /api/structural-drift`, `GET /api/drift-report` |

## 偵測項目

| 偵測 | 方法 | 閾值 |
|------|------|------|
| 規則觸發頻率漂移 | 近 20 日觸發率 vs 歷史觸發率 | 偏移 50%+ → 偏移 |
| 規則滾動勝率衰退 | 次日漲跌驗證訊號方向 | 勝率下降 30%+ → 衰退 |
| 特徵分布偏移 | 11 項數值特徵均值變化率 | 均值變化 30%+ → 漂移 |
| 健診評分系統性偏移 | 整體評分均值對比 | 偏移分數標準化 |

## 警報機制

- **watch**(30%), **warning**(50%), **critical**(70%) 三級
- pipeline 自動推送 critical/warning 到 Telegram/Discord
- 每日 Markdown 報告寫入 `data/reports/drift_{date}.md`
- 衰退規則標記 `drift_status`，不自動停用

## 狀態更新

- T012 task → ✅ done
- 知識庫 README → ✅ done: 11 | pending: 2
- 專案 README → 已同步
