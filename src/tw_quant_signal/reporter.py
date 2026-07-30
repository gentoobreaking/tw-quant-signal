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

    with db.connect() as conn:
        ms_row = conn.execute(
            "SELECT message FROM pipeline_log WHERE run_date=? AND task='market_state' ORDER BY id DESC LIMIT 1",
            [run_date],
        ).fetchone()
    ms_text = ""
    if ms_row:
        parts = dict(p.split("=") for p in ms_row[0].split(",") if "=" in p)
        state_map = {"bull": "📈多頭", "bear": "📉空頭", "range": "➡️盤整", "unknown": "❓"}
        ms_text = f"（{state_map.get(parts.get('state',''),'❓')}）"

    if idx:
        md.append(f"## 大盤概況{ms_text}")
        md.append(f"- 收盤: {idx[1]:,.0f}")
        md.append(f"- 漲跌: {idx[2]:+.2f}%" if idx[2] else "- 漲跌: -")
        md.append("")

    with db.connect() as conn:
        health_rows = conn.execute(
            "SELECT stock_id, fundamental_score, fundamental_light, "
            "institutional_score, institutional_light, "
            "technical_score, technical_light, "
            "valuation_score, valuation_light, "
            "total_score, total_light "
            "FROM health_scores WHERE trade_date=? ORDER BY stock_id",
            [run_date],
        ).fetchall()

    if health_rows:
        md.append("## 四燈號健診評分")
        md.append("")
        md.append("| 標的 | 總分 | 燈號 | 基本面 | 籌碼面 | 技術面 | 估值面 |")
        md.append("|------|------|------|--------|--------|--------|--------|")
        for r in health_rows:
            md.append(
                f"| {r[0]} | {r[9]:.0f} | {r[10]} | "
                f"{r[1]:.0f} {r[2]} | {r[3]:.0f} {r[4]} | "
                f"{r[5]:.0f} {r[6]} | {r[7]:.0f} {r[8]} |"
            )
        md.append("")

    md.append("## 燈號說明")
    md.append("")
    md.append("### 綜合總分（五級）")
    md.append("| 範圍 | 燈號 | 意義 |")
    md.append("|------|------|------|")
    md.append("| ≥80 | 🟢 | 強勢多頭 |")
    md.append("| 60–79 | 🟢🔴 | 偏多 |")
    md.append("| 40–59 | 🟡 | 中立 |")
    md.append("| 20–39 | 🔴🟢 | 偏空 |")
    md.append("| <20 | 🔴 | 強勢空頭 |")
    md.append("")
    md.append("### 子項（三分）")
    md.append("| 範圍 | 燈號 |")
    md.append("|------|------|")
    md.append("| ≥70 | 🟢 |")
    md.append("| 30–69 | 🟡 |")
    md.append("| <30 | 🔴 |")
    md.append("")
    md.append("### 四面向權重")
    md.append("- 📈 基本面（25%）：EPS成長40% · 營收30% · 毛利率30%")
    md.append("- 👁 籌碼面（25%）：外資佔比40% · 投信佔比30% · 券資比30%")
    md.append("- 📊 技術面（25%）：均線排列40% · RSI 30% · 布林通道30%")
    md.append("- 💰 估值面（25%）：PE河流40% · PB河流30% · 殖利率30%")
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
                         "triggered_rules", "triggered_count"])
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT stock_id, trade_date, signal, total_score, triggered_rules, triggered_count "
                "FROM rule_signals WHERE trade_date=?", [run_date]
            ).fetchall()
        for r in rows:
            writer.writerow(r)

    return str(path)
