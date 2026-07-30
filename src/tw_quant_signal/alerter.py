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


def build_daily_report(status: dict, index_data: Optional[dict] = None) -> str:
    run_date = date.today().isoformat()
    lines = [
        f"📊 *台股訊號管線 — {run_date}*",
        "",
        "```",
        f"大盤指數 : {'OK' if status.get('index')=='ok' else '❌ '+str(status.get('index'))}  "
        f"{'('+str(index_data.get('close','-'))+')' if index_data else ''}",
        f"權值股   : {'OK' if status.get('stocks')=='ok' else '❌ '+str(status.get('stocks'))}",
        f"法人買賣 : {'OK' if status.get('institutional')=='ok' else str(status.get('institutional'))}",
        f"技術指標 : {'OK' if status.get('indicators')=='ok' else '❌ '+str(status.get('indicators'))}",
        "```",
    ]
    if any(v == "fail" for v in status.values()):
        failed = [k for k, v in status.items() if v == "fail"]
        lines.append(f"\n⚠️ *異常任務：* {', '.join(failed)}")
    return "\n".join(lines)


def send_health_alert(status: dict, index_data: Optional[dict] = None):
    report = build_daily_report(status, index_data)
    return send_alert(report)
