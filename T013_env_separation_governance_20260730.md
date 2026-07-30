# T013 環境分離與操作治理 — 實作完成

## 已交付檔案

```
新增 configs/environments.yaml              ← 模式設定 + 白名單 + 晉升門檻
新增 src/tw_quant_signal/env_manager.py     ← 環境管理核心 (約100行)
新增 src/tw_quant_signal/operation_log.py   ← 操作日誌 + 合規報告 (約200行)
新增 GOVERNANCE.md                          ← 完整治理文件 (法規邊界/免責/操作流程)

修改 src/tw_quant_signal/db.py              ← + operation_log 表
修改 src/tw_quant_signal/pipeline.py        ← + production 規則過濾 + 日誌寫入 + 免責附加
修改 src/tw_quant_signal/api/app.py         ← + 4 個 API 端點
修改 知識庫 README.md                        ← ✅ done: 12
修改 專案 README.md                          ← 已同步
```

## 功能實現

| 需求 | 實現方式 |
|------|---------|
| 研究環境自由調整 | `research: true` (YAML) 或 `TW_QUANT_MODE=research` (env) |
| 實戰白名單鎖定 | `filter_rules_for_production()` 過濾規則引擎產出 |
| 規則晉升審核 | `check_promotion_eligibility()` — 交易數30+/勝率55%+/Sharpe 1.0+ |
| 操作日誌 | 5 類：管線執行/訊號產出/規則變更/設定變更/模式切換 |
| 免責聲明 | 自動附加於每日 Telegram/Discord 報告 |
| 法規文件 | `GOVERNANCE.md` 完整說明個人定位、非投顧業務、對外服務風險提示 |
| API | `/api/environment`, `/api/compliance-statement`, `/api/compliance-report`, `/api/operation-log` |

## 模式切換用法

```bash
# 研究模式（預設）
export TW_QUANT_MODE=research   # 或 configs/environments.yaml research: true

# 實戰模式
export TW_QUANT_MODE=production  # 或 configs/environments.yaml research: false
```

## Phase 3 全完成

T011 (多時間框架) + T012 (結構變化) + T013 (環境治理) 已全部 ✅ done。
剩餘 T010 (個股池訊號) 為附屬功能，不影響核心管線完整性。
