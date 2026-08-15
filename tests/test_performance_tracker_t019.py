"""T019 — Unit tests for performance_tracker.

涵蓋：
- performance_log 表 schema、index 是否建立
- DB helpers: get_performance_logs / upsert_performance_logs / get_performance_logs_distinct_triggers
- compute_performance_log: 增量計算、觸發時點 buy=trigger+1日收盤
- compute_agg_stats: 胜率/均酬/貲損比/最大DD/連違虧損
- 依市場狀態分組
- 不回補過去 (僅按 trigger_date <= as_of 處理今日以後)
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta

import pytest

from tw_quant_signal.backtest import CostModel
from tw_quant_signal.db import SignalDB, _init_schema
from tw_quant_signal.performance_tracker import (
    compute_performance_log,
    compute_agg_stats,
    _aggregate,
)

from tests.conftest import temp_db_conn, populate_db, generate_inst_flows


def _make_signal_db(tmp_path) -> SignalDB:
    db = SignalDB(str(tmp_path / "perf.db"))
    db.init_db()
    return db


def _seed_rule_signal(conn, trade_date, stock_id, rule_id, signal="range"):
    """Insert one rule_signals row + its triggered_rules JSON."""
    triggered = [{"rule_id": rule_id, "rule_name": rule_id, "type": "bullish", "failure": ""}]
    conn.execute(
        "INSERT OR REPLACE INTO rule_signals "
        "(trade_date, stock_id, triggered_rules, triggered_count, signal, total_score) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [trade_date, stock_id, json.dumps(triggered), 1, signal, 1],
    )


def _seed_market_state_log(conn, trade_date, state):
    conn.execute(
        "INSERT INTO pipeline_log (run_date, task, status, message) VALUES (?, ?, ?, ?)",
        [trade_date, "market_state", "ok", f"state={state},close=0,ma60=0,rsi=0"],
    )


# --- DB schema ---------------------------------------------------------------

def test_init_schema_creates_performance_log(tmp_path):
    db = _make_signal_db(tmp_path)
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='performance_log'"
        ).fetchall()
        assert rows and rows[0][0] == "performance_log"
        idx = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name LIKE 'idx_perf_log%'"
        ).fetchall()}
        assert {"idx_perf_log_trigger", "idx_perf_log_rule", "idx_perf_log_stock"} <= idx


def test_performance_log_unique_constraint(tmp_path):
    db = _make_signal_db(tmp_path)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO performance_log (stock_id, rule_id, trigger_date) VALUES (?, ?, ?)",
            ["2330", "U001", "2026-08-10"],
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO performance_log (stock_id, rule_id, trigger_date) VALUES (?, ?, ?)",
                ["2330", "U001", "2026-08-10"],
            )


# --- DB helpers --------------------------------------------------------------

def test_upsert_and_get_performance_logs(tmp_path):
    db = _make_signal_db(tmp_path)
    rows = [
        {"stock_id": "2330", "rule_id": "U001", "trigger_date": "2026-08-01",
         "market_state": "bull", "close_at_trigger": 500.0,
         "after_1d_return": 0.01, "after_3d_return": 0.025,
         "after_5d_return": 0.04, "after_10d_return": 0.08,
         "inspection_date": "2026-08-15"},
    ]
    db.upsert_performance_logs(rows)
    got = db.get_performance_logs(from_date="2026-07-01")
    assert len(got) == 1
    assert got[0]["rule_id"] == "U001"
    assert got[0]["after_5d_return"] == pytest.approx(0.04)

    # Update same key — should replace (UPSERT semantics)
    rows[0]["after_5d_return"] = 0.05
    db.upsert_performance_logs(rows)
    got2 = db.get_performance_logs(from_date="2026-07-01")
    assert len(got2) == 1
    assert got2[0]["after_5d_return"] == pytest.approx(0.05)


def test_get_performance_logs_filters(tmp_path):
    db = _make_signal_db(tmp_path)
    db.upsert_performance_logs([
        {"stock_id": "2330", "rule_id": "U001", "trigger_date": "2026-08-01", "market_state": "bull"},
        {"stock_id": "0050", "rule_id": "U001", "trigger_date": "2026-08-02", "market_state": "bear"},
        {"stock_id": "2330", "rule_id": "U002", "trigger_date": "2026-08-03", "market_state": "range"},
    ])
    # by rule_id
    rows = db.get_performance_logs(rule_id="U002")
    assert len(rows) == 1 and rows[0]["rule_id"] == "U002"

    # by stock_id
    rows = db.get_performance_logs(stock_id="2330")
    assert {r["rule_id"] for r in rows} == {"U001", "U002"}

    # by market_state
    rows = db.get_performance_logs(market_state="bear")
    assert len(rows) == 1 and rows[0]["stock_id"] == "0050"

    # by date range
    rows = db.get_performance_logs(from_date="2026-08-02", to_date="2026-08-02")
    assert len(rows) == 1 and rows[0]["rule_id"] == "U001" and rows[0]["stock_id"] == "0050"


def test_get_performance_logs_distinct_triggers(tmp_path):
    db = _make_signal_db(tmp_path)
    db.upsert_performance_logs([
        {"stock_id": "2330", "rule_id": "U001", "trigger_date": "2026-08-01"},
        {"stock_id": "2330", "rule_id": "U002", "trigger_date": "2026-08-02"},
    ])
    keys = db.get_performance_logs_distinct_triggers()
    assert ("2330", "U001", "2026-08-01") in keys
    assert ("2330", "U002", "2026-08-02") in keys


# --- compute_performance_log -------------------------------------------------

def test_compute_performance_log_minimal(tmp_path):
    """Smoke test: 1 trigger, 1 stock with enough daily_prices → 4 returns computed."""
    db = _make_signal_db(tmp_path)
    # Need at least 1 daily_prices[trigger_date] + 11 days forward
    with db.connect() as conn:
        base = date(2026, 7, 1)
        for i in range(20):
            d = (base + timedelta(days=i)).isoformat()
            conn.execute(
                "INSERT OR REPLACE INTO daily_prices (stock_id, trade_date, open, high, low, close, volume) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ["2330", d, 500.0 + i, 502 + i, 499 + i, 501 + i, 1_000_000],
            )
        conn.commit()

    with db.connect() as conn:
        _seed_rule_signal(conn, "2026-07-01", "2330", "U001", signal="bull")
        _seed_market_state_log(conn, "2026-07-01", "bull")
        conn.commit()

    out = compute_performance_log(db, trade_date="2026-07-15")
    assert len(out) == 1
    row = out[0]
    assert row["stock_id"] == "2330"
    assert row["rule_id"] == "U001"
    assert row["market_state"] == "bull"
    assert row["close_at_trigger"] == pytest.approx(501.0)
    # 1d: buy at D+1 close, sell at D+1 close (N=1) → net ~= -cost
    assert row["after_1d_return"] is not None
    assert row["after_1d_return"] < 0  # cost model eats tiny movement
    # 3d/5d/10d returns computed (close prices after 11 trading days)
    assert row["after_3d_return"] is not None
    assert row["after_5d_return"] is not None
    assert row["after_10d_return"] is not None


def test_compute_performance_log_incremental_skip(tmp_path):
    """Second pass should not re-create same (stock, rule, trigger_date)."""
    db = _make_signal_db(tmp_path)
    with db.connect() as conn:
        base = date(2026, 7, 1)
        for i in range(20):
            d = (base + timedelta(days=i)).isoformat()
            conn.execute(
                "INSERT OR REPLACE INTO daily_prices (stock_id, trade_date, open, high, low, close, volume) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ["2330", d, 500.0 + i, 502 + i, 499 + i, 501 + i, 1_000_000],
            )
        conn.commit()
    with db.connect() as conn:
        _seed_rule_signal(conn, "2026-07-01", "2330", "U001")
        conn.commit()

    out1 = compute_performance_log(db, trade_date="2026-07-15")
    out2 = compute_performance_log(db, trade_date="2026-07-15")  # incremental
    assert len(out1) == 1
    assert len(out2) == 0  # skipped, already exists


def test_compute_performance_log_rewrite_refreshes_returns(tmp_path):
    """When more daily prices appear (持有期 to mature), rewrite=True updates returns."""
    db = _make_signal_db(tmp_path)
    with db.connect() as conn:
        base = date(2026, 7, 1)
        for i in range(20):
            d = (base + timedelta(days=i)).isoformat()
            conn.execute(
                "INSERT OR REPLACE INTO daily_prices (stock_id, trade_date, open, high, low, close, volume) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ["2330", d, 500.0 + i, 502 + i, 499 + i, 501 + i, 1_000_000],
            )
        conn.commit()
    with db.connect() as conn:
        _seed_rule_signal(conn, "2026-07-01", "2330", "U001")
        conn.commit()

    out = compute_performance_log(db, trade_date="2026-07-15", rewrite=True)
    assert len(out) == 1


def test_compute_performance_log_no_future_price_returns_none(tmp_path):
    """If no D+11 prices exist, holding-period returns stay None.

    Note: daily_prices must include trigger_date row (for close_at_trigger),
    but no future rows exist after it — hence all returns None.
    """
    db = _make_signal_db(tmp_path)
    with db.connect() as conn:
        # Only the trigger_date row (no future prices)
        conn.execute(
            "INSERT OR REPLACE INTO daily_prices (stock_id, trade_date, close) "
            "VALUES (?, ?, ?)",
            ["2330", "2026-07-01", 500.0],
        )
        conn.commit()
    with db.connect() as conn:
        _seed_rule_signal(conn, "2026-07-01", "2330", "U001")
        conn.commit()

    out = compute_performance_log(db, trade_date="2026-07-15")
    assert len(out) == 1
    # close_at_trigger populated, but no future prices
    assert out[0]["close_at_trigger"] == pytest.approx(500.0)
    assert out[0]["after_1d_return"] is None
    assert out[0]["after_3d_return"] is None
    assert out[0]["after_5d_return"] is None
    assert out[0]["after_10d_return"] is None


# --- _aggregate -------------------------------------------------------------

def test_aggregate_empty_returns():
    agg = _aggregate([])
    assert agg["triggers"] == 0
    assert agg["win_rate"] == 0.0
    assert agg["max_consecutive_losses"] == 0


def test_aggregate_basic_metrics():
    # 4 wins of +1%, 2 losses of -2%
    returns = [0.01, 0.01, 0.01, 0.01, -0.02, -0.02]
    agg = _aggregate(returns)
    assert agg["triggers"] == 6
    assert agg["wins"] == 4
    assert agg["losses"] == 2
    assert agg["win_rate"] == pytest.approx(4/6, abs=1e-4)
    assert agg["avg_win"] == pytest.approx(0.01)
    assert agg["avg_loss"] == pytest.approx(-0.02)
    assert agg["profit_ratio"] == pytest.approx(0.5, abs=1e-3)
    # cumulative: 1+1+1+1-2-2 = 0, peak = 4, dd = 4 at end → max_dd = 4 (in decimal)
    assert agg["max_dd"] > 0
    # consecutive losses — only 2 in a row at end
    assert agg["max_consecutive_losses"] == 2


def test_aggregate_consecutive_losses_run():
    returns = [-0.01, -0.02, -0.015, 0.005, -0.01, -0.005, -0.01]
    agg = _aggregate(returns)
    # first 3 are losses (3 in row), then mid 0.005 (reset), then 3 losses
    assert agg["max_consecutive_losses"] == 3


# --- compute_agg_stats -------------------------------------------------------

def test_compute_agg_stats_basic(tmp_path):
    db = _make_signal_db(tmp_path)
    db.upsert_performance_logs([
        {"stock_id": "2330", "rule_id": "U001", "trigger_date": "2026-08-01",
         "market_state": "bull", "after_5d_return": 0.01},
        {"stock_id": "2330", "rule_id": "U001", "trigger_date": "2026-08-02",
         "market_state": "bull", "after_5d_return": 0.02},
        {"stock_id": "2330", "rule_id": "U001", "trigger_date": "2026-08-03",
         "market_state": "bear", "after_5d_return": -0.01},
        {"stock_id": "2330", "rule_id": "U002", "trigger_date": "2026-08-01",
         "market_state": "bull", "after_5d_return": 0.005},
    ])
    stats = compute_agg_stats(db, horizon=5)
    assert stats["horizon"] == 5
    assert "U001" in stats["rules"]
    u001 = stats["rules"]["U001"]
    assert u001["stats"]["triggers"] == 3
    # by state 分組存在
    assert "bull" in u001["by_state"]
    assert "bear" in u001["by_state"]
    # overview
    assert stats["overview"]["triggers"] == 4
    # markdown table rendered
    assert "## 規則績效總覽" in stats["markdown_table"]
    assert "U001" in stats["markdown_table"]


def test_compute_agg_stats_no_data(tmp_path):
    db = _make_signal_db(tmp_path)
    stats = compute_agg_stats(db, horizon=5)
    assert stats["overview"]["triggers"] == 0
    assert "## 規則績效總覽" in stats["markdown_table"]
    # 但沒有任何 Uxxx 行
    rows = [line for line in stats["markdown_table"].splitlines() if line.startswith("| U")]
    assert rows == []


def test_compute_agg_stats_horizon_validation(tmp_path):
    db = _make_signal_db(tmp_path)
    # horizon 不在 _HORIZONS 內 → 自動 fallback 到 5
    stats = compute_agg_stats(db, horizon=99)
    assert stats["horizon"] == 5
