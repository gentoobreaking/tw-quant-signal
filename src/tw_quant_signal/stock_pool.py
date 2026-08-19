"""T010 — 個股池訊號 (Stock Pool Signals)。

整合：
- 個股健康度燈號（health_check）
- 多空訊號計分卡（signal_scorecard）
- 多時間框架共識（multi_timeframe）
- 相對大盤強弱 (relative_strength) ← T010 新增
- 大盤訊號交叉比對 ← T010 新增
- 族群/產業分組 ← T010 擴充 SECTOR_MAP

存活者偏誤處理：
- watchlist_history 表追蹤觀察清單變更時點（含被剔除的標的）
- 在「曾經納入觀察清單」的標的上保留四燈號記錄，避免只算現有清單的偏差
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from datetime import date
from typing import Any

from tw_quant_signal.db import SignalDB
from tw_quant_signal.health_check import compute_health_check
from tw_quant_signal.signal_scorecard import compute_all_scorecards
from tw_quant_signal.multi_timeframe import compute_multi_timeframe
from tw_quant_signal.relative_strength import (
    RelativeStrength,
    compute_relative_strength,
    compute_relative_strength_for_pool,
)
from tw_quant_signal.market_state import detect_market_state


# ------------------------------------------------------------------
# T010 擴充：族群/產業分組
# 涵蓋 watch_stocks 全 11 檔，依 TWSE TW50 與市場分類作為基準
# ------------------------------------------------------------------
SECTOR_MAP: dict[str, str] = {
    # 半導體
    "2330": "半導體",
    "2303": "半導體",
    # 電子零組件 / 機構
    "2308": "電子零組件",
    "2317": "電子零組件",
    "2454": "半導體",
    # 記憶體 / IC 設計
    "3008": "半導體",
    # 金融
    "2881": "金融",
    "2882": "金融",
    # 傳產 / 塑化（示例預留）
    "6505": "傳產",
    "6518": "傳產",
    # ETF (大盤基準)
    "0050": "ETF",
}

STOCK_NAMES: dict[str, str] = {
    "0050": "元大台灣50",
    "2330": "台積電",
    "2303": "聯電",
    "2308": "台達電",
    "2317": "鴻海",
    "2454": "聯發科",
    "3008": "大立光",
    "2881": "富邦金",
    "2882": "國泰金",
    "6505": "台塑化",
    "6518": "長春",
}


@dataclass
class StockPoolRow:
    stock_id: str
    name: str
    sector: str | None
    total_score: int | None
    bullish_count: int | None
    bearish_count: int | None
    health_light: str | None
    technical_light: str | None
    consensus: str | None
    rs_5d: float | None
    rs_20d: float | None
    rs_60d: float | None
    rs_composite: float | None
    rs_label: str | None
    # 大盤交叉比對
    market_state: str | None
    market_consistent: bool | None     # 個股多空方向是否與大盤一致
    # 四燈號解構
    fundamental_light: str | None
    institutional_light: str | None
    valuation_light: str | None


@dataclass
class StockPoolSnapshot:
    as_of: str
    market_state: str | None
    pool_size: int
    rows: list[StockPoolRow] = field(default_factory=list)
    by_sector: dict[str, list[str]] = field(default_factory=dict)
    cross_compare: dict[str, Any] = field(default_factory=dict)


# ------------------------------------------------------------------
# 個股池快照
# ------------------------------------------------------------------

def build_stock_pool_snapshot(
    db: SignalDB,
    trade_date: str | None = None,
    pool: list[str] | None = None,
    benchmark_id: str = "0050",
) -> StockPoolSnapshot:
    """產生觀察清單的全景快照。"""
    from tw_quant_signal.config import WATCH_STOCKS
    if trade_date is None:
        # 今日尚無資料時，預設抓資料庫中最新的健康分資料交易日（而非行事曆今日），
        # 否則 multi_timeframe/scorecard 會因無對應日期而回傳 neutral。
        # 優先用 health_scores 最新日期，才能對齊 _fetch_latest_health 的資料。
        with _connect(db) as conn:
            latest = conn.execute(
                "SELECT MAX(trade_date) FROM health_scores"
            ).fetchone()
        as_of = latest[0] if latest and latest[0] else date.today().isoformat()
    else:
        as_of = trade_date
    pool = pool or WATCH_STOCKS

    # 1. 個股訊號來源（允許部分失敗 — 測試/初始環境可未必有完整 scorecard 資料）
    scorecards: dict = {}
    try:
        scorecards = {s["stock_id"]: s for s in compute_all_scorecards(db, trade_date=as_of)}
    except Exception as e:
        print(f"[stock_pool] scorecard 查詢失敗: {e}")
    health = _fetch_latest_health(db, pool, as_of)
    mtf: dict = {}
    try:
        mtf = {m["stock_id"]: m for m in compute_multi_timeframe(db, as_of)}
    except Exception as e:
        print(f"[stock_pool] multi_timeframe 查詢失敗: {e}")

    # 2. 相對強弱
    rs_map = {rs.stock_id: rs for rs in compute_relative_strength_for_pool(db, pool, benchmark_id)}

    # 3. 大盤狀態
    market_state_str = _resolve_market_state(db, as_of)

    # 4. 個股池逐列
    rows: list[StockPoolRow] = []
    for sid in pool:
        sc = scorecards.get(sid) or {}
        h = health.get(sid)
        m = mtf.get(sid) or {}
        rs = rs_map.get(sid)
        row = StockPoolRow(
            stock_id=sid,
            name=STOCK_NAMES.get(sid, sid),
            sector=SECTOR_MAP.get(sid),
            total_score=h.get("total_score") if h else None,
            bullish_count=sc["bullish"]["count"] if sc else None,
            bearish_count=sc["bearish"]["count"] if sc else None,
            health_light=h.get("total_light") if h else None,
            technical_light=h.get("technical_light") if h else None,
            consensus=m.get("consensus") if m else None,
            rs_5d=rs.rs_5d if rs else None,
            rs_20d=rs.rs_20d if rs else None,
            rs_60d=rs.rs_60d if rs else None,
            rs_composite=rs.composite if rs else None,
            rs_label=rs.composite_label if rs else None,
            market_state=market_state_str,
            market_consistent=_check_consistency(sc, m, market_state_str) if (sc or m) else None,
            fundamental_light=h.get("fundamental_light") if h else None,
            institutional_light=h.get("institutional_light") if h else None,
            valuation_light=h.get("valuation_light") if h else None,
        )
        rows.append(row)

    # 5. 族群分組
    by_sector: dict[str, list[str]] = {}
    for row in rows:
        sec = row.sector or "其他"
        by_sector.setdefault(sec, []).append(row.stock_id)

    # 6. 大盤 vs 個股交叉比對
    cross = _build_cross_compare(rows, market_state_str, benchmark_id, db, as_of)

    return StockPoolSnapshot(
        as_of=as_of,
        market_state=market_state_str,
        pool_size=len(rows),
        rows=rows,
        by_sector=by_sector,
        cross_compare=cross,
    )


def _fetch_latest_health(db: SignalDB, pool: list[str], as_of: str):
    """逐股讀取最近一日 health_scores 結果（避免一次抓全市場浪費）。"""
    out: dict[str, Any] = {}
    with _connect(db) as conn:
        for sid in pool:
            row = conn.execute(
                "SELECT * FROM health_scores WHERE stock_id=? ORDER BY trade_date DESC LIMIT 1",
                [sid],
            ).fetchone()
            if row:
                cols = ["trade_date", "stock_id", "fundamental_score", "fundamental_light",
                        "institutional_score", "institutional_light",
                        "technical_score", "technical_light",
                        "valuation_score", "valuation_light",
                        "total_score", "total_light"]
                out[sid] = dict(zip(cols, row))
    return out


def _resolve_market_state(db: SignalDB, as_of: str) -> str | None:
    """從 market_index 計算出當日大盤狀態（bull/bear/range）。"""
    try:
        ms = detect_market_state(db, as_of)
        return ms.get("state") if isinstance(ms, dict) else ms.state
    except Exception:
        return None


def _check_consistency(sc, mtf, market_state_str: str | None) -> bool | None:
    """個股多空方向是否與大盤一致 (僅在有資料時回傳 bool)。"""
    if market_state_str is None:
        return None
    # 個股方向取 scorecard bull/bear 差 或 consensus (sc/mtf 可能為 dict 或 dataclass)
    direction = None
    if sc is not None:
        bull = sc["bullish"]["count"] if isinstance(sc, dict) else sc.bullish.count
        bear = sc["bearish"]["count"] if isinstance(sc, dict) else sc.bearish.count
        if bull > bear + 2:
            direction = "bull"
        elif bear > bull + 2:
            direction = "bear"
    if direction is None and mtf is not None:
        consensus = mtf.get("consensus") if isinstance(mtf, dict) else getattr(mtf, "consensus", None)
        if consensus == "bullish":
            direction = "bull"
        elif consensus == "bearish":
            direction = "bear"
    if direction is None:
        return None
    return direction == market_state_str


def _build_cross_compare(
    rows: list[StockPoolRow],
    market_state_str: str | None,
    benchmark_id: str,
    db: SignalDB,
    as_of: str,
) -> dict[str, Any]:
    """產生大盤 vs 個股的交叉比對摘要。"""
    consistent = [r for r in rows if r.market_consistent is True]
    inconsistent = [r for r in rows if r.market_consistent is False]
    no_data = [r for r in rows if r.market_consistent is None]

    # 找出「逆勢強勢」：大盤空頭但個股多頭
    if market_state_str == "bear":
        contrarian_strong = [r.stock_id for r in rows
                             if (r.rs_composite is not None and r.rs_composite >= 0.01)]
    elif market_state_str == "bull":
        # 大盤多頭但個股弱勢
        contrarian_strong = [r.stock_id for r in rows
                             if (r.rs_composite is not None and r.rs_composite <= -0.01)]
    else:
        contrarian_strong = []

    # 大盤強弱（用 benchmark_id 自身相對於其他股票的 RS）
    benchmark_rs = compute_relative_strength(db, benchmark_id, benchmark_id, as_of)
    return {
        "market_state": market_state_str,
        "consistent_count": len(consistent),
        "inconsistent_count": len(inconsistent),
        "no_data_count": len(no_data),
        "consistent_stocks": [r.stock_id for r in consistent],
        "inconsistent_stocks": [r.stock_id for r in inconsistent],
        "contrarian_stocks": contrarian_strong,
        "benchmark_id": benchmark_id,
        "as_of": as_of,
    }


# ------------------------------------------------------------------
# 存活者偏誤：watchlist_history
# ------------------------------------------------------------------

def _is_signal_db(obj) -> bool:
    return hasattr(obj, "connect") and callable(getattr(obj, "connect"))


@contextmanager
def _connect(db):
    """讓 helper 函式同時接受 SignalDB 與裸 sqlite3.Connection。"""
    if _is_signal_db(db):
        with db.connect() as conn:
            yield conn
    else:
        yield db


def record_watchlist_snapshot(db: SignalDB, pool: list[str], as_of: str | None = None):
    """將當前 pool 寫入 watchlist_history 表（供存活者偏誤分析）。"""
    as_of = as_of or date.today().isoformat()
    with _connect(db) as conn:
        for sid in pool:
            conn.execute(
                "INSERT OR REPLACE INTO watchlist_history (stock_id, since_date) "
                "VALUES (?, COALESCE((SELECT since_date FROM watchlist_history "
                "WHERE stock_id=? AND removed_date IS NULL), ?))",
                [sid, sid, as_of],
            )


def mark_removed(db: SignalDB, pool: list[str], as_of: str | None = None) -> int:
    """標記當前不再存在於 pool 中且還為 active 的歷史標的。"""
    as_of = as_of or date.today().isoformat()
    with _connect(db) as conn:
        current_set = set(pool)
        rows = conn.execute(
            "SELECT stock_id FROM watchlist_history WHERE removed_date IS NULL"
        ).fetchall()
        removed = 0
        for (sid,) in rows:
            if sid not in current_set:
                conn.execute(
                    "UPDATE watchlist_history SET removed_date=? WHERE stock_id=? AND removed_date IS NULL",
                    [as_of, sid],
                )
                removed += 1
        return removed


def get_watchlist_history(db: SignalDB, include_removed: bool = True) -> list[dict]:
    """回傳觀察清單歷史（含曾被剔除者），供存活者偏誤分析。"""
    with _connect(db) as conn:
        if include_removed:
            rows = conn.execute(
                "SELECT stock_id, since_date, removed_date FROM watchlist_history "
                "ORDER BY since_date ASC, stock_id"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT stock_id, since_date, removed_date FROM watchlist_history "
                "WHERE removed_date IS NULL "
                "ORDER BY since_date ASC, stock_id"
            ).fetchall()
        out = []
        for sid, since, removed in rows:
            out.append({
                "stock_id": sid,
                "name": STOCK_NAMES.get(sid, sid),
                "since_date": since,
                "removed_date": removed,
                "status": "active" if removed is None else "removed",
            })
        return out