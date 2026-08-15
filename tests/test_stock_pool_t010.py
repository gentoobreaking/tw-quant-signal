"""T010 — 個股池訊號測試。

涵蓋範圍：
- watchlist_history 表 schema + CRUD
- SECTOR_MAP 至少 5 檔並含預期族群
- relative_strength 計算（含 baseline 為 0、500 vs 1000、缺資料）
- stock_pool.build_stock_pool_snapshot 結構
- 大盤 vs 個股「一致性」標記
- 存活者偏誤處理（mark_removed 與 get_watchlist_history）
"""

from __future__ import annotations

import sqlite3
import sys
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

from tw_quant_signal.db import SignalDB, _init_schema  # noqa: E402
from tw_quant_signal.relative_strength import (  # noqa: E402
    compute_relative_strength,
    _classify,
)
from tw_quant_signal.stock_pool import (  # noqa: E402
    SECTOR_MAP,
    STOCK_NAMES,
    build_stock_pool_snapshot,
    record_watchlist_snapshot,
    mark_removed,
    get_watchlist_history,
)


# ---------------------------------------------------------------------
# 共用 fixtures
# ---------------------------------------------------------------------

class _SignalDBProxy:
    """裸 sqlite3.Connection 的 SignalDB 望製 proxy。

    使多個 helper 能彼此協作（ get_health_scores / 連接管理）。
    """
    def __init__(self, conn):
        self._conn = conn

    def connect(self):
        return _NullContextManager(self._conn)

    def get_health_scores(self, trade_date: str):
        return []


class _NullContextManager:
    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        return self._conn

    def __exit__(self, *args):
        return False


@contextmanager
def _make_db():
    """建立 in-memory SQLite 並 pre-populate 簡單 daily_prices。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _init_schema(conn)
    try:
        yield conn
    finally:
        conn.close()


def _seed_prices(conn, stock_id: str, days: int, start: date, base: float = 500.0):
    """簡單線性成長，方便計算超額報酬。"""
    rows = []
    d = start
    i = 0
    while len(rows) < days:
        if d.weekday() < 5:
            close = base + i * 0.5
            rows.append((d.isoformat(), close))
            i += 1
        d = d + timedelta(days=1)
    conn.executemany(
        "INSERT INTO daily_prices (stock_id, trade_date, open, high, low, close, volume, amount, adj_factor, adj_close) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(sid, dt, c, c + 1, c - 1, c, 1_000_000, c, 1.0, c) for (dt, c) in rows for sid in [stock_id]],
    )
    conn.commit()


@pytest.fixture
def dbsession():
    """Yield an in-memory SQLite connection with full schema."""
    with _make_db() as conn:
        yield conn


# ---------------------------------------------------------------------
# watchlist_history 表
# ---------------------------------------------------------------------

def test_watchlist_history_table_exists(tmp_path):
    """watchlist_history 表應在 schema 內。"""
    db_path = tmp_path / "test.db"
    db = SignalDB(str(db_path))
    db.init_db()
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='watchlist_history'"
        ).fetchall()
    assert rows, "watchlist_history 表未建立"
    db_path.unlink(missing_ok=True)


def test_record_watchlist_snapshot_inserts(dbsession):
    """記錄當前 pool 應為 active 狀態。"""
    record_watchlist_snapshot(dbsession, ["2330", "2308"], "2026-08-01")
    rows = get_watchlist_history(dbsession, include_removed=True)
    assert len(rows) == 2
    active = [r for r in rows if r["removed_date"] is None]
    assert {r["stock_id"] for r in active} == {"2330", "2308"}


def test_mark_removed_is_idempotent_and_records_date(dbsession):
    """標記後應可重複呼叫且不產生額外列。"""
    record_watchlist_snapshot(dbsession, ["2330", "2308", "2317"], "2026-08-01")
    removed = mark_removed(dbsession, ["2330"], "2026-08-05")
    assert removed == 2
    removed2 = mark_removed(dbsession, ["2330"], "2026-08-06")
    assert removed2 == 0
    rows = get_watchlist_history(dbsession, include_removed=True)
    active = {r["stock_id"] for r in rows if r["removed_date"] is None}
    assert active == {"2330"}
    gone = [r for r in rows if r["stock_id"] in {"2308", "2317"}]
    for r in gone:
        assert r["removed_date"] == "2026-08-05"


def test_record_snapshot_preserves_since_date(dbsession):
    """同一檔被記錄多次時，起始日應保留最早一次。"""
    record_watchlist_snapshot(dbsession, ["2330"], "2026-07-01")
    record_watchlist_snapshot(dbsession, ["2330"], "2026-08-01")
    rows = get_watchlist_history(dbsession, include_removed=False)
    assert len(rows) == 1
    assert rows[0]["since_date"] == "2026-07-01"


def test_get_watchlist_history_filter(dbsession):
    """include_removed=False 只回傳 active。"""
    record_watchlist_snapshot(dbsession, ["2330", "2308"], "2026-08-01")
    # mark_removed: 傳入當前 pool，將「不在 pool 內」的 active 標記為 removed
    mark_removed(dbsession, ["2330"], "2026-08-05")  # 2308 不在 pool 中 → 標記為 removed
    active = get_watchlist_history(dbsession, include_removed=False)
    all_h = get_watchlist_history(dbsession, include_removed=True)
    assert {r["stock_id"] for r in active} == {"2330"}
    assert {r["stock_id"] for r in all_h} == {"2330", "2308"}


# ---------------------------------------------------------------------
# SECTOR_MAP / STOCK_NAMES
# ---------------------------------------------------------------------

def test_sector_map_has_min_5_stocks():
    assert len(SECTOR_MAP) >= 5, "應至少 5 檔個股以滿足 §3.3.1"


def test_sector_map_includes_semiconductor_and_finance():
    """驗證至少涵蓋半導體 + 金融 + ETF 三大類。"""
    sectors = set(SECTOR_MAP.values())
    assert "半導體" in sectors
    assert "ETF" in sectors
    assert "金融" in sectors or "金融保險" in sectors


def test_all_known_stocks_have_names_and_sectors():
    """STOCK_NAMES 與 SECTOR_MAP 對齊常見 stock_id。"""
    for sid in ["2330", "0050", "2881"]:
        assert sid in SECTOR_MAP, f"{sid} 缺少族群定義"
        assert sid in STOCK_NAMES, f"{sid} 缺少中文名"


# ---------------------------------------------------------------------
# relative_strength
# ---------------------------------------------------------------------

def test_classify_thresholds():
    assert _classify(-0.10) == "very_weak"
    assert _classify(-0.015) == "weak"
    assert _classify(0.0) == "flat"
    assert _classify(0.012) == "strong"
    assert _classify(0.05) == "very_strong"
    assert _classify(None) is None


def test_relative_strength_self_returns_zero(dbsession):
    """基準與標的相同 → 全部為 0。"""
    start = date(2026, 1, 5)
    _seed_prices(dbsession, "0050", 60, start, base=500.0)
    rs = compute_relative_strength(dbsession, "0050", "0050")
    assert rs.rs_5d == 0
    assert rs.rs_20d == 0
    assert rs.rs_60d == 0
    assert rs.composite == 0
    assert rs.composite_label == "flat"


def test_relative_strength_no_data_returns_none(dbsession):
    """缺資料應回傳 None。"""
    rs = compute_relative_strength(dbsession, "NOTEXIST", "0050")
    assert rs.rs_5d is None
    assert rs.rs_20d is None
    assert rs.rs_60d is None
    assert rs.composite is None
    assert rs.composite_label is None


def test_relative_strong_stock_vs_market(dbsession):
    """個股漲 5% vs 大盤 0% → very_strong。"""
    start = date(2026, 1, 5)
    _seed_prices(dbsession, "0050", 60, start, base=500.0)
    # 2330 末端大幅拉升
    rows = dbsession.execute(
        "SELECT trade_date FROM daily_prices WHERE stock_id='0050' ORDER BY trade_date"
    ).fetchall()
    for i, (d,) in enumerate(rows):
        close = 500.0 + i * 10.0   # 跳升
        dbsession.execute(
            "INSERT INTO daily_prices (stock_id, trade_date, open, high, low, close, volume, amount, adj_factor, adj_close) "
            "VALUES ('2330', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [d, close, close, close, close, 1_000_000, close, 1.0, close],
        )
    dbsession.commit()
    rs = compute_relative_strength(dbsession, "2330", "0050")
    assert rs.rs_20d is not None
    assert rs.rs_20d > 0.02


def test_relative_strength_weak_stock(dbsession):
    """個股弱於大盤時 rs_5d 為負。"""
    start = date(2026, 1, 5)
    _seed_prices(dbsession, "0050", 60, start, base=500.0)
    # 2330 每天 0.5 → 500 + 0.1 = 500 + 60*0.1 ≈ 506
    _seed_prices(dbsession, "2330", 60, start, base=500.0)
    rows = dbsession.execute(
        "SELECT trade_date FROM daily_prices WHERE stock_id='2330' ORDER BY trade_date"
    ).fetchall()
    for i, (d,) in enumerate(rows):
        close = 500.0 + i * 0.1
        dbsession.execute(
            "UPDATE daily_prices SET close=?, adj_close=? WHERE stock_id='2330' AND trade_date=?",
            [close, close, d],
        )
    dbsession.commit()
    rs = compute_relative_strength(dbsession, "2330", "0050")
    assert rs.rs_5d is not None
    assert rs.rs_5d < 0, f"個股弱於大盤應為負: {rs.rs_5d}"


# ---------------------------------------------------------------------
# build_stock_pool_snapshot
# ---------------------------------------------------------------------

def test_build_snapshot_returns_expected_shape(dbsession):
    """snapshot 結構：rows / by_sector / cross_compare / market_state。"""
    start = date(2026, 1, 5)
    _seed_prices(dbsession, "0050", 60, start, base=500.0)
    for sid in ["2330", "2308", "2881"]:
        _seed_prices(dbsession, sid, 60, start, base=300.0)

    record_watchlist_snapshot(dbsession, ["2330", "2308", "2881", "0050"], "2026-08-01")
    snap = build_stock_pool_snapshot(dbsession, trade_date=None, pool=["2330", "2308", "2881", "0050"])
    assert snap.pool_size == 4
    assert snap.as_of is not None
    assert isinstance(snap.rows, list)
    assert isinstance(snap.by_sector, dict)
    assert "半導體" in snap.by_sector
    assert "金融" in snap.by_sector
    assert "ETF" in snap.by_sector
    for row in snap.rows:
        assert row.stock_id
        assert row.name


def test_build_snapshot_cross_compare_counts(dbsession):
    """交叉比對：列出 consistent / inconsistent / contrarian_stocks。"""
    start = date(2026, 1, 5)
    _seed_prices(dbsession, "0050", 60, start, base=500.0)
    _seed_prices(dbsession, "2330", 60, start, base=300.0)
    _seed_prices(dbsession, "2308", 60, start, base=300.0)

    record_watchlist_snapshot(dbsession, ["2330", "2308", "0050"], "2026-08-01")
    snap = build_stock_pool_snapshot(dbsession, trade_date=None, pool=["2330", "2308", "0050"])
    cc = snap.cross_compare
    assert "market_state" in cc
    assert "consistent_count" in cc
    assert "inconsistent_count" in cc
    assert "contrarian_stocks" in cc
    assert cc["consistent_count"] + cc["inconsistent_count"] + cc["no_data_count"] <= snap.pool_size


def test_build_snapshot_sector_grouping_complete(dbsession):
    """by_sector 必須包含所有 row 的 sector。"""
    start = date(2026, 1, 5)
    _seed_prices(dbsession, "0050", 60, start, base=500.0)
    for sid in ["2330", "2308", "2881"]:
        _seed_prices(dbsession, sid, 60, start, base=300.0)

    snap = build_stock_pool_snapshot(dbsession, trade_date=None, pool=["2330", "2308", "2881", "0050"])
    groupped = set()
    for sids in snap.by_sector.values():
        groupped.update(sids)
    assert groupped == {"2330", "2308", "2881", "0050"}


# ---------------------------------------------------------------------
# 存活者偏誤
# ---------------------------------------------------------------------

def test_survivorship_bias_history_with_real_db(tmp_path):
    """模擬：7 月放入 3 檔，8 月移除 1 檔，確認已移除標的仍可被查詢。"""
    db_path = tmp_path / "bias.db"
    db = SignalDB(str(db_path))
    db.init_db()
    record_watchlist_snapshot(db, ["2330", "2308", "2317"], "2026-07-01")
    removed = mark_removed(db, ["2330", "2308"], "2026-08-01")
    assert removed == 1
    all_history = get_watchlist_history(db, include_removed=True)
    sids = {r["stock_id"] for r in all_history}
    assert "2317" in sids
    assert any(r["stock_id"] == "2317" and r["removed_date"] == "2026-08-01" for r in all_history)
    db_path.unlink(missing_ok=True)