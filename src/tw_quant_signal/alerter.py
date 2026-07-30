from datetime import date
from typing import Optional

import httpx

from tw_quant_signal.config import settings

TELEGRAM_BOT_TOKEN = settings.telegram_bot_token
TELEGRAM_CHAT_ID = settings.telegram_chat_id
DISCORD_WEBHOOK_URL = settings.discord_webhook_url


def _send_telegram(message: str) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.post(url, json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "Markdown",
            })
        return resp.status_code == 200
    except Exception:
        return False


def _send_discord(message: str) -> bool:
    if not DISCORD_WEBHOOK_URL:
        return False
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.post(DISCORD_WEBHOOK_URL, json={"content": message})
        return resp.status_code == 200 or resp.status_code == 204
    except Exception:
        return False


def send_alert(message: str) -> bool:
    sent = _send_telegram(message)
    if not sent:
        sent = _send_discord(message)
    return sent


STOCK_NAMES = {"2330": "台積電", "0050": "元大台灣50", "2308": "台達電"}


def _fmt(v, decimals=0):
    if v is None:
        return "-"
    if decimals == 0:
        return f"{int(v):,}"
    return f"{v:,.{decimals}f}"


def _ma_signal(ma5, ma20, ma60):
    if ma5 is None or ma20 is None or ma60 is None:
        return "", ""
    if ma5 > ma20 > ma60:
        return "📈多頭", "🟢"
    if ma5 < ma20 < ma60:
        return "📉空頭", "🔴"
    return "➡️整理", "🟡"


def _rsi_signal(val):
    if val is None:
        return "", ""
    if val >= 70:
        return "過熱", "🔴"
    if val <= 30:
        return "超賣", "🔵"
    if 50 <= val < 70:
        return "偏多", "🟢"
    return "偏空", "🟡"


def _bb_signal(close, upper, lower):
    if close is None or upper is None or lower is None:
        return ""
    if close >= upper:
        return " 📈觸上軌"
    if close <= lower:
        return " 📉破下軌"
    return ""


def build_daily_report(status: dict, report_data: Optional[dict] = None) -> str:
    run_date = date.today()
    lines = [f"📊 *台股訊號 — {run_date.month:02d}/{run_date.day:02d}*", ""]

    idx = (report_data or {}).get("index")
    if idx:
        arrow = "📈" if idx.get("change_pct") and idx["change_pct"] >= 0 else "📉"
        lines.append(f"🏛 大盤 {_fmt(idx['close'], 2)}  ({_fmt(idx['change_pct'], 2)}%) {arrow}")

    stocks = (report_data or {}).get("stocks", [])
    for s in stocks:
        name = STOCK_NAMES.get(s["id"], s["id"])
        lines.append("")
        lines.append(f"*{s['id']} {name}*　{_fmt(s['close'], 2)}")
        if s.get("ma5"):
            ma_label, ma_color = _ma_signal(s["ma5"], s["ma20"], s["ma60"])
            _, rsi_color = _rsi_signal(s["rsi14"])
            bb = _bb_signal(s.get("adj_close"), s.get("bb_upper"), s.get("bb_lower"))

            lines.append(
                f"  {ma_color}均線 {ma_label}  "
                f"{rsi_color}RSI {_fmt(s['rsi14'], 1)}  "
                f"{bb}"
            )
            lines.append(
                f"    MA5 {_fmt(s['ma5'], 1)}  MA20 {_fmt(s['ma20'], 1)}  MA60 {_fmt(s['ma60'], 1)}"
            )

            if s.get("foreign") is not None:
                f = s["foreign"] / 1000
                st = s.get("sity", 0) / 1000
                d = s.get("dealer", 0) / 1000
                f_color = "🔴" if f < -500 else ("🟢" if f > 500 else "⚪")
                st_color = "🔴" if st < -200 else ("🟢" if st > 200 else "⚪")
                d_color = "🔴" if d < -200 else ("🟢" if d > 200 else "⚪")
                lines.append(
                    f"  外資 {f_color}{_fmt(f)}k  "
                    f"投信 {st_color}{_fmt(st)}k  "
                    f"自營 {d_color}{_fmt(d)}k"
                )
        else:
            status_icon = "✓" if status.get("stocks") == "ok" else "✗"
            lines.append(f"  [{status_icon}]")

    if any(v == "fail" for v in status.values()):
        failed = [k for k, v in status.items() if v == "fail"]
        lines.append(f"\n⚠️ *異常：* {', '.join(failed)}")

    return "\n".join(lines)


def send_health_alert(status: dict, report_data: Optional[dict] = None):
    report = build_daily_report(status, report_data)
    return send_alert(report)


def build_signals_report(signals: list[dict]) -> str:
    run_date = date.today()
    lines = [f"🔦 *四大燈號 — {run_date.month:02d}/{run_date.day:02d}*", ""]

    ICONS = {"bullish": "🟢", "neutral": "🟡", "bearish": "🔴"}
    LABELS = {"bullish": "偏多", "neutral": "中立", "bearish": "偏空"}

    for row in signals:
        sid = row["stock_id"]
        name = STOCK_NAMES.get(sid, sid)
        total_icon = ICONS.get(row["signal"], "⚪")
        total_label = LABELS.get(row["signal"], "")
        lines.append(f"{total_icon} *{sid} {name}*　{total_label} ({row['total_score']:+d})")

        for tag, label in [("D1", "動能"), ("D2", "籌碼"), ("D3", "價值"), ("D4", "大盤")]:
            k = f"d{tag[-1]}_signal"
            score_key = f"d{tag[-1]}_score"
            icon = ICONS.get(row[k], "⚪")
            lbl = LABELS.get(row[k], "")
            lines.append(f"  {icon} {tag} {label} {lbl} ({row[score_key]:+d})")

        lines.append("")

    return "\n".join(lines)


def send_signals_report(signals: list[dict]) -> bool:
    report = build_signals_report(signals)
    return send_alert(report)


def build_rules_report(rule_results: list[dict]) -> str:
    run_date = date.today()
    lines = [f"⚙ *規則引擎 — {run_date.month:02d}/{run_date.day:02d}*", ""]
    ICONS = {"bullish": "🟢", "neutral": "🟡", "bearish": "🔴"}
    LABELS = {"bullish": "偏多", "neutral": "中立", "bearish": "偏空"}

    for row in rule_results:
        sid = row["stock_id"]
        name = STOCK_NAMES.get(sid, sid)
        icon = ICONS.get(row["signal"], "⚪")
        lbl = LABELS.get(row["signal"], "")
        lines.append(f"{icon} *{sid} {name}*　{lbl} ({row['total_score']:+d})")

        for tr in row.get("triggered_rules", []):
            t = tr["type"]
            ticon = ICONS.get(t, "⚪")
            lines.append(f"  {ticon} {tr['rule_id']} {tr['rule_name']}")
            if tr.get("failure"):
                lines.append(f"    📋 失效條件: {tr['failure']}")

        if not row.get("triggered_rules"):
            lines.append("  ⚪ 無規則觸發")

        lines.append("")

    return "\n".join(lines)


def send_rules_report(rule_results: list[dict]) -> bool:
    report = build_rules_report(rule_results)
    return send_alert(report)


def build_health_check_report(health_scores: list[dict]) -> str:
    run_date = date.today()
    lines = [f"🩺 *四燈號健診 — {run_date.month:02d}/{run_date.day:02d}*", ""]
    ASPECT = {
        "fundamental": ("📈基本面", 25),
        "institutional": ("👁籌碼面", 25),
        "technical": ("📊技術面", 25),
        "valuation": ("💰估值面", 25),
    }
    for row in health_scores:
        sid = row["stock_id"]
        name = STOCK_NAMES.get(sid, sid)
        lines.append(f"{row['total_light']} *{sid} {name}*　{row['total_score']:.0f}/100")
        for key, (label, _) in ASPECT.items():
            s = row.get(f"{key}_score", 0) or 0
            l = row.get(f"{key}_light", "⚪")
            lines.append(f"  {l} {label} {s:.0f}")
        lines.append("")
    return "\n".join(lines)


def send_health_check_report(health_scores: list[dict]) -> bool:
    report = build_health_check_report(health_scores)
    return send_alert(report)
