"""操作日誌 — 運維軌跡與合規紀錄。

記錄項目：
- 每次管線執行（任務、耗時、狀態）
- 規則版本變更（YAML hash 快照）
- 設定變更（config.json 修改）
- 環境模式切換（research ↔ production）
- 決策責任聲明紀錄

使用情境：
- 操作回溯：需要調閱歷史時可追查當日規則版本
- 法規留底：個人工具定位之免責紀錄
- 審計軌跡：提供規則晉升至實戰的證據

資料表：operation_log (pipeline_log 的擴充層)
"""

import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import yaml

from tw_quant_signal.db import SignalDB
from tw_quant_signal.env_manager import snapshot_rule_versions, is_research_mode, is_production_mode


DISCLAIMER_TEXT = (
    "本系統為個人研究工具，產出之所有訊號與建議僅供參考，不構成任何投資建議、要約或勸誘。"
    "使用者應獨立判斷，並對其投資決策負完全責任。"
    "本系統不涉及證券投資顧問業務，亦未經主管機關核准。"
    "若未來計劃對外提供訊號服務，應另行委任合格之證券投資顧問或取得相關執照。"
)


def _get_rule_version_hash() -> str:
    """計算目前規則 YAML 的 hash。"""
    return snapshot_rule_versions()


def log_signal_output(db: SignalDB, run_date: str, stock_id: str, signal: str, score: int, triggered_rules: list[dict]):
    """紀錄每次訊號產出（含當時規則版本 hash 與環境模式）。"""
    rule_hash = _get_rule_version_hash()
    mode = "research" if is_research_mode() else "production"
    detail = json.dumps({
        "rule_version_hash": rule_hash,
        "mode": mode,
        "triggered_rules": triggered_rules,
        "disclaimer_applied": True,
    }, ensure_ascii=False)
    with db.connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO operation_log "
            "(log_date, stock_id, action, signal, score, mode, rule_version_hash, details) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [run_date, stock_id, "signal_output", signal, score, mode, rule_hash, detail],
        )


def log_pipeline_run(db: SignalDB, run_date: str, steps: dict[str, str], elapsed_seconds: int):
    """紀錄管線執行摘要。"""
    mode = "research" if is_research_mode() else "production"
    rule_hash = _get_rule_version_hash()
    detail = json.dumps({
        "steps": steps,
        "elapsed_seconds": elapsed_seconds,
        "mode": mode,
        "rule_version_hash": rule_hash,
    }, ensure_ascii=False)
    with db.connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO operation_log "
            "(log_date, stock_id, action, mode, rule_version_hash, details) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [run_date, None, "pipeline_run", mode, rule_hash, detail],
        )


def log_rule_change(db: SignalDB, change_type: str, rule_id: str, description: str):
    """紀錄規則變更（新增/修改/刪除/晉升/降級）。"""
    prev_hash = _get_rule_version_hash()
    detail = json.dumps({
        "change_type": change_type,
        "rule_id": rule_id,
        "description": description,
        "prev_rule_hash": prev_hash,
    }, ensure_ascii=False)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO operation_log "
            "(log_date, stock_id, action, rule_version_hash, details) "
            "VALUES (?, ?, ?, ?, ?)",
            [date.today().isoformat(), None, f"rule_{change_type}", prev_hash, detail],
        )


def log_mode_switch(db: SignalDB, from_mode: str, to_mode: str, reason: str = ""):
    """紀錄 research / production 模式切換。"""
    detail = json.dumps({
        "from": from_mode,
        "to": to_mode,
        "reason": reason,
    }, ensure_ascii=False)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO operation_log "
            "(log_date, stock_id, action, mode, rule_version_hash, details) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [date.today().isoformat(), None, "mode_switch", to_mode,
             _get_rule_version_hash(), detail],
        )


def log_config_change(db: SignalDB, config_file: str, changed_fields: list[str]):
    """紀錄設定檔案變更。"""
    detail = json.dumps({
        "config_file": config_file,
        "changed_fields": changed_fields,
        "rule_hash_at_change": _get_rule_version_hash(),
    }, ensure_ascii=False)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO operation_log "
            "(log_date, stock_id, action, mode, rule_version_hash, details) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [date.today().isoformat(), None, "config_change", "production" if is_production_mode() else "research",
             _get_rule_version_hash(), detail],
        )


def get_operation_log(db: SignalDB, days: int = 30) -> list[dict]:
    """查詢近期操作日誌。"""
    lookback = (date.today().isoformat(),)
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT log_date, stock_id, action, signal, score, mode, "
            "rule_version_hash, details, created_at "
            "FROM operation_log "
            "ORDER BY created_at DESC LIMIT ?",
            [days * 20],  # safe upper bound
        ).fetchall()
    result = []
    for r in rows:
        d = {
            "log_date": r[0],
            "stock_id": r[1],
            "action": r[2],
            "signal": r[3],
            "score": r[4],
            "mode": r[5],
            "rule_version_hash": r[6],
            "created_at": r[8],
        }
        if r[7] and isinstance(r[7], str):
            try:
                d["details"] = json.loads(r[7])
            except json.JSONDecodeError:
                pass
        result.append(d)
    return result


def get_compliance_statement() -> str:
    """回傳法規邊界聲明。"""
    return DISCLAIMER_TEXT


def build_compliance_report(db: SignalDB) -> str:
    """產生合規報告（含操作軌跡摘要與免責聲明）。"""
    today = date.today().isoformat()
    log = get_operation_log(db, days=7)
    mode = "研究環境" if is_research_mode() else "實戰環境"

    lines = [
        f"# 合規與操作治理報告 — {today}",
        "",
        f"**當前模式**: {mode}",
        f"**規則版本 hash**: `{_get_rule_version_hash()}`",
        "",
    ]

    recent = [l for l in log if l["log_date"] >= (date.today().isoformat())]
    if recent:
        lines.append("## 當日操作紀錄\n")
        lines.append("| 時間 | 操作 | 標的 | 模式 |")
        lines.append("|------|------|------|------|")
        for l in recent:
            lines.append(f"| {l.get('created_at','')[:16]} | {l['action']} | {l.get('stock_id','-')} | {l.get('mode','-')} |")
        lines.append("")

    lines.append("## 決策責任聲明")
    lines.append("")
    lines.append(DISCLAIMER_TEXT)
    lines.append("")

    lines.append("## 法規注意事項")
    lines.append("")
    lines.append("1. **個人定位**: 本系統為個人量化研究與輔助決策工具，不向第三人提供投資建議。")
    lines.append("2. **非投顧業務**: 系統未申請、也未取得證券投資顧問執照，不適用《證券投資信託及顧問法》。")
    lines.append("3. **訊號僅供參考**: 所有訊號、評分、建議均為參考資訊，不構成買賣要約或建議。")
    lines.append("4. **人為最終決定**: 任何交易決定應由使用者自行判斷、自行負責。")
    lines.append("5. **未來對外服務**: 若日後計畫對外提供付費/免費訊號服務，")
    lines.append("   應先諮詢法律專業意見，評估是否需要證券投資顧問執照或其他法規許可。")
    lines.append("")

    return "\n".join(lines)
