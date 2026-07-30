import json
import os
from pathlib import Path
from typing import Optional

CONFIG_PATH = os.getenv("TW_QUANT_CONFIG", str(Path(__file__).parent.parent.parent / "config.json"))


class Settings:
    def __init__(self, path: str = CONFIG_PATH):
        self._path = Path(path)
        self._data = self._load()

    def _load(self) -> dict:
        if self._path.exists():
            with open(self._path) as f:
                return json.load(f)
        return {}

    @property
    def watch_stocks(self) -> list[str]:
        return self._data.get("watch_stocks", ["2330"])

    @property
    def telegram_bot_token(self) -> str:
        return os.getenv("TELEGRAM_BOT_TOKEN") or self._data.get("notification", {}).get("telegram_bot_token", "")

    @property
    def telegram_chat_id(self) -> str:
        return os.getenv("TELEGRAM_CHAT_ID") or self._data.get("notification", {}).get("telegram_chat_id", "")

    @property
    def discord_webhook_url(self) -> str:
        return os.getenv("DISCORD_WEBHOOK_URL") or self._data.get("notification", {}).get("discord_webhook_url", "")

    @property
    def db_path(self) -> str:
        env_path = os.getenv("TW_QUANT_DB")
        if env_path:
            return env_path
        rel_path = self._data.get("database", {}).get("path", "data/signal.db")
        return str(self._path.parent / rel_path)


settings = Settings()
