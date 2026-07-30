"""Generate daily report files (Markdown/CSV) for signal output."""

import csv
import os
from datetime import date
from pathlib import Path

from tw_quant_signal.db import SignalDB
from tw_quant_signal.config import settings

REPORT_DIR = Path(settings._path.parent) / "data" / "reports"


def _ensure_dir():
    REPORT_DIR.mkdir(parents=True, exist_ok=True)


def generate_markdown_report(db: SignalDB, run_date: str | None = None) -> str:
    run_date = run_date or date.today().isoformat()
    _ensure_dir()

    md = []
    md.append(f"# 台股 AI 訊號報告 — {run_date}")
    md.append("")

    with db.connect() as conn:
        sigs = conn.execute(
            "SELECT * FROM signals WHERE trade_date=? ORDER BY signal",
            [run_date],
        ).fetchall()

    if sigs:
        md.append("## 四大燈號")
        md.append("")
        md.append("| 標的 | 訊號 | D1 動能 | D2 籌碼 | D3 價值 | D4 大盤 |")
        md.append("|------|------|---------|---------|---------|---------|")
        for r in sigs:
            md.append(f"| {r[1]} | {r[11]} ({r[10]:+d}) | {r[3]} ({r[2]:+d}) | {r[5]} ({r[4]:+d}) | {r[7]} ({r[6]:+d}) | {r[9]} ({r[8]:+d}) |")
        md.append("")

    with db.connect() as conn:
        rule_rows = conn.execute(
            "SELECT stock_id, triggered_rules, signal, total_score FROM rule_signals WHERE trade_date=?",
            [run_date],
        ).fetchall()

    if rule_rows:
        md.append("## 規則觸發")
        md.append("")
        for sid, triggered_raw, signal, score in rule_rows:
            md.append(f"### {sid} — {signal} ({score:+d})")
            import json
            triggered = json.loads(triggered_raw)
            for tr in triggered:
                md.append(f"- {tr['rule_id']} {tr['rule_name']}")
            md.append("")

    with db.connect() as conn:
        idx = conn.execute(
            "SELECT trade_date, close, change_pct FROM market_index ORDER BY trade_date DESC LIMIT 1"
        ).fetchone()

    if idx:
        md.append(f"## 大盤概況")
        md.append(f"- 收盤: {idx[1]:,.0f}")
        md.append(f"- 漲跌: {idx[2]:+.2f}%" if idx[2] else "- 漲跌: -")
        md.append("")

    report = "\n".join(md)
    path = REPORT_DIR / f"report_{run_date}.md"
    path.write_text(report, encoding="utf-8")
    return str(path)


def generate_csv_report(db: SignalDB, run_date: str | None = None) -> str:
    run_date = run_date or date.today().isoformat()
    _ensure_dir()

    path = REPORT_DIR / f"signals_{run_date}.csv"
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["stock_id", "trade_date", "signal", "total_score",
                         "d1_score", "d1_signal", "d2_score", "d2_signal",
                         "d3_score", "d3_signal", "d4_score", "d4_signal"])
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM signals WHERE trade_date=?", [run_date]
            ).fetchall()
        for r in rows:
            writer.writerow([r[1], r[0], r[11], r[10],
                             r[2], r[3], r[4], r[5],
                             r[6], r[7], r[8], r[9]])

    return str(path)
