"""T010 — 相對大盤強弱 (Relative Strength)。

計算個股相對於大盤 (預設 0050 元大台灣50) 的「超額報酬」，並轉為
弱 → 強的等級標籤（-2/-1/0/+1/+2）。

設計重點：
- 採用簡單線性超額報酬，避免使用 alpha/beta 等需要歷史回歸的方法（資料量大、且容易在
  觀察清單變動時失真）。
- 大盤預設 = config.json watch_stocks 中第一個 ETF（0050），未來可改為指定 benchmark。
- 持有期：5 日 / 20 日 / 60 日三個視角，呼應 health_check 的週/月/季。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from tw_quant_signal.db import SignalDB


# 強弱分級門檻（超額報酬百分比）
# 對齊任務書「相對大盤強弱校正」精神：±2% 視為顯著
_THRESHOLDS = [-0.02, -0.005, 0.005, 0.02]


@dataclass
class RelativeStrength:
    stock_id: str
    benchmark_id: str
    rs_5d: float | None       # 5 日超額報酬（stock - benchmark）
    rs_20d: float | None
    rs_60d: float | None
    label_5d: str | None      # 'very_weak' / 'weak' / 'flat' / 'strong' / 'very_strong'
    label_20d: str | None
    label_60d: str | None
    composite: float | None   # 三期平均超額報酬
    composite_label: str | None
    as_of: str                # 計算日期


def _classify(value: float | None) -> str | None:
    if value is None:
        return None
    if value < _THRESHOLDS[0]:
        return "very_weak"
    if value < _THRESHOLDS[1]:
        return "weak"
    if value < _THRESHOLDS[2]:
        return "flat"
    if value < _THRESHOLDS[3]:
        return "strong"
    return "very_strong"


def _has_connect(obj) -> bool:
    return hasattr(obj, "connect") and callable(getattr(obj, "connect"))


def _safe_pct_return(db: SignalDB, stock_id: str, days: int) -> float | None:
    """計算 stock 在最近 `days` 個交易日的報酬率。

    同時支援 SignalDB 與裸 sqlite3.Connection。
    """
    if _has_connect(db):
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT trade_date, close FROM daily_prices WHERE stock_id=? "
                "ORDER BY trade_date DESC LIMIT ?",
                [stock_id, days + 1],
            ).fetchall()
    else:
        rows = db.execute(
            "SELECT trade_date, close FROM daily_prices WHERE stock_id=? "
            "ORDER BY trade_date DESC LIMIT ?",
            [stock_id, days + 1],
        ).fetchall()
    if len(rows) < 2:
        return None
    latest = rows[0][1]
    earliest = rows[-1][1]
    if not latest or not earliest or earliest == 0:
        return None
    return (latest - earliest) / earliest


def compute_relative_strength(
    db: SignalDB,
    stock_id: str,
    benchmark_id: str = "0050",
    as_of: str | None = None,
) -> RelativeStrength:
    """個股 vs 大盤 (0050) 的 5/20/60 日超額報酬。

    Parameters
    ----------
    db : SignalDB
    stock_id : str
    benchmark_id : str
        大盤替代指標，預設 0050 (元大台灣50 ETF)。
    as_of : str | None
        計算基準日 (YYYY-MM-DD)，預設今日。
    """
    as_of = as_of or date.today().isoformat()
    rs_5 = None
    rs_20 = None
    rs_60 = None
    if stock_id == benchmark_id:
        # 基準與標的相同 → 超額報酬 = 0
        rs_5 = 0.0
        rs_20 = 0.0
        rs_60 = 0.0
    else:
        s_5 = _safe_pct_return(db, stock_id, 5)
        b_5 = _safe_pct_return(db, benchmark_id, 5)
        rs_5 = (s_5 - b_5) if (s_5 is not None and b_5 is not None) else None

        s_20 = _safe_pct_return(db, stock_id, 20)
        b_20 = _safe_pct_return(db, benchmark_id, 20)
        rs_20 = (s_20 - b_20) if (s_20 is not None and b_20 is not None) else None

        s_60 = _safe_pct_return(db, stock_id, 60)
        b_60 = _safe_pct_return(db, benchmark_id, 60)
        rs_60 = (s_60 - b_60) if (s_60 is not None and b_60 is not None) else None

    composites = [v for v in (rs_5, rs_20, rs_60) if v is not None]
    composite = sum(composites) / len(composites) if composites else None

    return RelativeStrength(
        stock_id=stock_id,
        benchmark_id=benchmark_id,
        rs_5d=rs_5, rs_20d=rs_20, rs_60d=rs_60,
        label_5d=_classify(rs_5),
        label_20d=_classify(rs_20),
        label_60d=_classify(rs_60),
        composite=composite,
        composite_label=_classify(composite),
        as_of=as_of,
    )


def compute_relative_strength_for_pool(
    db: SignalDB,
    pool: list[str],
    benchmark_id: str = "0050",
) -> list[RelativeStrength]:
    """為整個觀察清單計算相對強弱。"""
    return [compute_relative_strength(db, sid, benchmark_id) for sid in pool]