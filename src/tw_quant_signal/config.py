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

    @property
    def mcp_timeout_sec(self) -> int:
        """MCP 呼叫逾時（秒），環境變數 MCP_CALL_TIMEOUT 優先，其次 config.json，預設 60 秒。"""
        env_val = os.getenv("MCP_CALL_TIMEOUT")
        if env_val is not None:
            try:
                return int(env_val)
            except ValueError:
                pass
        return self._data.get("data_provider", {}).get("mcp_timeout_sec", 60)

    @property
    def mcp_init_timeout_sec(self) -> int:
        """MCP 初始化握手逾時（秒），預設 10 秒。"""
        return self._data.get("data_provider", {}).get("mcp_init_timeout_sec", 10)


settings = Settings()

# T020: WATCH_STOCKS 的規範定義移至此處（twse_client 及各模組由此 re-import）。
WATCH_STOCKS: list[str] = settings.watch_stocks
