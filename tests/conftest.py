import json
import sqlite3
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"
import sys
sys.path.insert(0, str(SRC))

from tw_quant_signal.db import _init_schema


@contextmanager
def temp_db_conn():
    """Create an in-memory SQLite database with the full schema."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    _init_schema(conn)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@pytest.fixture
def db_conn():
    """Yield an in-memory SQLite connection with full schema."""
    with temp_db_conn() as conn:
        yield conn


def generate_prices(stock_id="2330", days=260, start_date=None):
    """Generate synthetic OHLCV data."""
    if start_date is None:
        start_date = date(2026, 1, 5)
    rows = []
    price = 500.0
    count = 0
    while len(rows) < days:
        d = start_date + timedelta(days=count)
        count += 1
        if d.weekday() >= 5:
            continue
        chg = ((hash(f"{d}:{len(rows)}") % 100) - 50) / 250
        price = max(100, price + chg * 5)
        o = round(price - chg, 2)
        h = round(max(o, price) * 1.02, 2)
        l = round(min(o, price) * 0.98, 2)
        vol = abs(hash(f"v{d}")) % 1_000_000 + 100_000
        rows.append({
            "stock_id": stock_id,
            "trade_date": d.isoformat(),
            "open": o,
            "high": h,
            "low": l,
            "close": round(price, 2),
            "volume": vol,
            "amount": round(price * vol / 10000, 2),
            "adj_factor": 1.0,
            "adj_close": round(price, 2),
        })
    return rows


def generate_small_prices(stock_id="2330", size=20):
    """Small price set with known values for indicator/feature tests."""
    closes = [
        500.0, 502.5, 505.0, 503.0, 501.0, 498.0, 495.0, 492.0,
        496.0, 500.0, 505.0, 510.0, 508.0, 512.0, 515.0, 520.0,
        518.0, 522.0, 525.0, 530.0,
    ]
    rows = []
    for i, c in enumerate(closes[:size]):
        rows.append({
            "stock_id": stock_id,
            "trade_date": f"2026-08-{i+1:02d}",
            "open": c - 1.0,
            "high": c + 2.0,
            "low": c - 2.0,
            "close": c,
            "volume": 1_000_000 + i * 50000,
            "amount": round(c * (1_000_000 + i * 50000) / 10000, 2),
            "adj_factor": 1.0,
            "adj_close": c,
        })
    return rows


def generate_inst_flows(stock_id="2330", days=10, start_date=None):
    """Generate institutional flow records."""
    if start_date is None:
        start_date = date(2026, 7, 1)
    rows = []
    count = 0
    while len(rows) < days:
        d = start_date + timedelta(days=count)
        count += 1
        if d.weekday() >= 5:
            continue
        rows.append({
            "stock_id": stock_id,
            "trade_date": d.isoformat(),
            "market": "TSE",
            "foreign_investors_net": 1000 + len(rows) * 200,
            "sity_investors_net": 500 + len(rows) * 50,
            "dealer_net": 100 + len(rows) * 30,
            "dealer_proprietary_net": 0,
            "dealer_hedge_net": 0,
            "total_net": 1600 + len(rows) * 280,
        })
    return rows


def generate_index_data(days=120, start_date=None):
    if start_date is None:
        start_date = date(2026, 1, 5)
    rows = []
    idx = 18000.0
    count = 0
    while len(rows) < days:
        d = start_date + timedelta(days=count)
        count += 1
        if d.weekday() >= 5:
            continue
        chg = (hash(f"idx:{d}") % 200 - 100) * 0.5
        prev = idx
        idx = max(15000, idx + chg)
        pct = round((idx - prev) / prev * 100, 4)
        rows.append({
            "trade_date": d.isoformat(),
            "close": idx,
            "change_pct": pct,
        })
    return rows


def populate_db(conn: sqlite3.Connection,
                prices: list[dict] = None,
                inst_rows: list[dict] = None,
                indicators: list[dict] = None,
                features: list[dict] = None,
                monthly_rev: list[dict] = None,
                index_rows: list[dict] = None):
    """Batch insert sample data into the in-memory DB."""
    if prices:
        for r in prices:
            conn.execute(
                """INSERT OR REPLACE INTO daily_prices
                   (stock_id, trade_date, open, high, low, close, volume, amount)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                [r.get("stock_id", "2330"), r["trade_date"], r.get("open"), r.get("high"),
                 r.get("low"), r.get("close"), r.get("volume"), r.get("amount")],
            )
    if inst_rows:
        for r in inst_rows:
            conn.execute(
                """INSERT OR REPLACE INTO institutional_flows
                   (stock_id, trade_date, market, foreign_investors_net, sity_investors_net,
                    dealer_net, dealer_proprietary_net, dealer_hedge_net, total_net)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [r.get("stock_id", "2330"), r["trade_date"], r.get("market", "TSE"),
                 r.get("foreign_investors_net"), r.get("sity_investors_net"),
                 r.get("dealer_net"), r.get("dealer_proprietary_net"),
                 r.get("dealer_hedge_net"), r.get("total_net")],
            )
    if indicators:
        for r in indicators:
            conn.execute(
                """INSERT OR REPLACE INTO tech_indicators
                   (stock_id, trade_date, ma5, ma20, ma60, bb_upper, bb_middle,
                    bb_lower, rsi14, volume_ma5, volume_ma20)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [r["stock_id"], r["trade_date"], r.get("ma5"), r.get("ma20"),
                 r.get("ma60"), r.get("bb_upper"), r.get("bb_middle"),
                 r.get("bb_lower"), r.get("rsi14"), r.get("volume_ma5"),
                 r.get("volume_ma20")],
            )
    if features:
        for f in features:
            conn.execute("DELETE FROM features WHERE trade_date=? AND stock_id=?",
                         [f["trade_date"], f["stock_id"]])
            conn.execute(
                "INSERT INTO features (trade_date, stock_id, data) VALUES (?, ?, ?)",
                [f["trade_date"], f["stock_id"], json.dumps(f, ensure_ascii=False)],
            )
    if monthly_rev:
        for r in monthly_rev:
            conn.execute(
                """INSERT OR REPLACE INTO monthly_revenue
                   (stock_id, year_month, revenue, mom_change, yoy_change)
                   VALUES (?, ?, ?, ?, ?)""",
                [r["stock_id"], r["year_month"],
                 r.get("revenue"), r.get("mom_change"), r.get("yoy_change")],
            )
    if index_rows:
        for r in index_rows:
            conn.execute(
                """INSERT OR REPLACE INTO market_index
                   (trade_date, close, change_pct)
                   VALUES (?, ?, ?)""",
                [r["trade_date"], r.get("close"), r.get("change_pct")],
            )
    conn.commit()