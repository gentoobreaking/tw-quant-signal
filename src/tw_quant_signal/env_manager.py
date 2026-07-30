"""環境管理 — 研究/實戰分離與規則治理。

讀取 configs/environments.yaml，決定執行模式：
- research mode: 自由調整參數、測試新規則、獨立回測
- production mode: 僅使用 production_rule_ids 白名單中的穩定規則

環境切換方式（優先順序）：
1. 環境變數 TW_QUANT_MODE=research|production
2. configs/environments.yaml 中的 research: true|false
"""

import hashlib
import os
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import yaml

ENV_CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs" / "environments.yaml"


def _load_env_config() -> dict:
    if ENV_CONFIG_PATH.exists():
        with open(ENV_CONFIG_PATH) as f:
            return yaml.safe_load(f) or {}
    return {}


def is_research_mode() -> bool:
    """判斷當前是否為研究模式。環境變數優先，次之讀 config。"""
    env_var = os.getenv("TW_QUANT_MODE")
    if env_var:
        return env_var == "research"
    cfg = _load_env_config()
    return cfg.get("research", True)


def is_production_mode() -> bool:
    return not is_research_mode()


def get_production_rule_ids() -> list[str]:
    """取得實戰規則白名單。"""
    cfg = _load_env_config()
    return cfg.get("production_rule_ids", [])


def get_disclaimer() -> str:
    cfg = _load_env_config()
    return cfg.get("disclaimer", "")


def get_promotion_criteria() -> dict:
    cfg = _load_env_config()
    return cfg.get("promotion", {})


def filter_rules_for_production(rules: list[dict]) -> list[dict]:
    """production mode 下，過濾出白名單內的規則。"""
    allowed = set(get_production_rule_ids())
    if not allowed:
        return []
    return [r for r in rules if (r.get("id") or "") in allowed]


def check_promotion_eligibility(
    rule_id: str,
    rule_name: str,
    total_trades: int,
    win_rate: float,
    sharpe: float,
) -> dict:
    """檢查一條規則是否符合晉升至實戰的門檻。"""
    criteria = get_promotion_criteria()
    checks = {
        "min_backtest_trades": {
            "passed": total_trades >= criteria.get("min_backtest_trades", 30),
            "required": criteria.get("min_backtest_trades", 30),
            "actual": total_trades,
        },
        "min_win_rate": {
            "passed": win_rate >= criteria.get("min_win_rate", 0.55),
            "required": criteria.get("min_win_rate", 0.55),
            "actual": round(win_rate, 4),
        },
        "min_sharpe": {
            "passed": sharpe >= criteria.get("min_sharpe", 1.0),
            "required": criteria.get("min_sharpe", 1.0),
            "actual": round(sharpe, 2),
        },
    }
    all_passed = all(c["passed"] for c in checks.values())
    return {
        "rule_id": rule_id,
        "rule_name": rule_name,
        "eligible": all_passed,
        "approval_required": criteria.get("approval_required", True),
        "checks": checks,
        "checked_at": datetime.now().isoformat(),
    }


def snapshot_rule_versions() -> str:
    """對所有規則 YAML 計算 SHA256，用於版本追蹤。"""
    rules_dir = Path(__file__).resolve().parents[2] / "configs"
    hasher = hashlib.sha256()
    for fname in ["rules_bullish.yaml", "rules_bearish.yaml", "rules_neutral.yaml"]:
        fpath = rules_dir / fname
        if fpath.exists():
            hasher.update(fpath.read_bytes())
    return hasher.hexdigest()[:12]


def get_summary() -> dict:
    """回傳環境狀態摘要（供 API / 報告使用）。"""
    mode = "research" if is_research_mode() else "production"
    white = get_production_rule_ids()
    cfg = _load_env_config()
    return {
        "mode": mode,
        "production_rule_count": len(white),
        "production_rule_ids": white,
        "promotion_thresholds": cfg.get("promotion", {}),
        "logging_enabled": cfg.get("logging", {}).get("enabled", True),
        "disclaimer": get_disclaimer(),
        "rule_version_hash": snapshot_rule_versions(),
    }
