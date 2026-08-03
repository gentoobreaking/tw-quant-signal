"""T017 — Integration tests: pipeline end-to-end with in-memory SQLite."""

import json
import os
import sqlite3
import tempfile
from datetime import date, timedelta

from tw_quant_signal.db import SignalDB, _init_schema
from tw_quant_signal.indicators import compute_indicators
from tw_quant_signal.rules import compute_rule_signals, store_rule_signals, _load_features
from tw_quant_signal.signal_scorecard import compute_scorecard, build_scorecard_rows

from tests.conftest import (
    populate_db,
    generate_prices,
    generate_inst_flows,
    generate_index_data,
)


def _make_temp_signal_db() -> SignalDB:
    fd, tmppath = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.environ["TW_QUANT_DB"] = tmppath
    db = SignalDB(tmppath)
    db.init_db()
    return db


class TestPipelineIntegration:
    def test_full_60_day_pipeline(self):
        """Simulate a full pipeline run with 60+ days of data across 3 watch stocks."""
        db = _make_temp_signal_db()
        db_path = db._path

        today = date(2026, 6, 30)
        stocks = ["2330", "0050", "2308"]

        all_features = []

        with db.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")

            # Insert index data (needed for features and backtest)
            idx_data = generate_index_data(days=200, start_date=date(2025, 6, 1))
            populate_db(conn, index_rows=idx_data)

            for sid in stocks:
                prices = generate_prices(sid, days=200, start_date=date(2025, 6, 1))
                inst = generate_inst_flows(sid, days=100, start_date=date(2025, 12, 1))

                # Compute indicators
                prices_sorted = sorted(prices, key=lambda x: x["trade_date"])
                price_dicts = [{"trade_date": p["trade_date"], "close": p["close"], "volume": p["volume"]} for p in prices_sorted]
                inds = compute_indicators(price_dicts, stock_id=sid)

                # Insert data
                populate_db(conn, prices=prices, inst_rows=inst, indicators=inds)

                # Monthly revenue for scorecard
                monthly_rev = [
                    {"stock_id": sid, "year_month": "202608", "revenue": 1000000, "mom_change": 5.0, "yoy_change": 12.0},
                    {"stock_id": sid, "year_month": "202607", "revenue": 950000, "mom_change": 3.0, "yoy_change": 8.0},
                    {"stock_id": sid, "year_month": "202606", "revenue": 920000, "mom_change": 2.0, "yoy_change": 5.0},
                ]
                populate_db(conn, monthly_rev=monthly_rev)

                # Build features for each date
                from tw_quant_signal.backtest import _compute_features_as_of
                for p in prices_sorted[-60:]:
                    row = _compute_features_as_of(db, sid, p["trade_date"])
                    if row:
                        all_features.append(row)

            # Also insert breadth institutional flows (all stocks need inst on same date)
            for sid in stocks:
                inst_more = generate_inst_flows(sid, days=100, start_date=date(2025, 12, 1))
                for r in inst_more:
                    try:
                        conn.execute(
                            """INSERT OR IGNORE INTO institutional_flows
                               (stock_id, trade_date, market, foreign_investors_net, sity_investors_net,
                                dealer_net, dealer_proprietary_net, dealer_hedge_net, total_net)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            [r.get("stock_id", sid), r["trade_date"], r.get("market", "TSE"),
                             r.get("foreign_investors_net"), r.get("sity_investors_net"),
                             r.get("dealer_net"), r.get("dealer_proprietary_net"),
                             r.get("dealer_hedge_net"), r.get("total_net")],
                        )
                    except Exception:
                        pass

        # Insert features
        features_db = []
        for f in all_features:
            features_db.append(f)
        with db.connect() as conn:
            for f_ in features_db:
                sid_ = f_.get("stock_id", f_.get("stock_id"))
                td = f_.get("trade_date")
                if sid_ and td:
                    conn.execute("DELETE FROM features WHERE trade_date=? AND stock_id=?", [td, sid_])
                    conn.execute(
                        "INSERT INTO features (trade_date, stock_id, data) VALUES (?, ?, ?)",
                        [td, sid_, json.dumps(f_, ensure_ascii=False)],
                    )

        # Step 1: Compute rule signals
        db = SignalDB(db_path)  # re-create after conn.close
        os.environ["TW_QUANT_DB"] = db_path
        
        try:
            signals = compute_rule_signals(db, trade_date=today.isoformat())
            assert isinstance(signals, list)

            # Step 2: Store rule signals
            store_rule_signals(db, signals)

            # Step 3: Verify rule_signals table
            with db.connect() as conn:
                rows = conn.execute("SELECT * FROM rule_signals").fetchall()
                assert len(rows) > 0
                for r in rows:
                    rd = dict(r)
                    assert rd["stock_id"] in stocks
                    assert rd["trade_date"] == today.isoformat()
                    assert rd["signal"] in ("bullish", "bearish", "neutral")

            # Step 4: Compute scorecards
            scorecards = []
            for sid in stocks:
                sc = compute_scorecard(db, sid)
                if sc.get("trade_date"):
                    scorecards.append(sc)

            for sc in scorecards:
                assert "bullish" in sc
                assert "bearish" in sc
                assert "count" in sc["bullish"]
                assert "ratio" in sc["bullish"]
                assert sc["bullish"]["count"] >= 0
                assert sc["bearish"]["count"] >= 0

            # Step 5: Store scorecard
            if scorecards:
                rows = build_scorecard_rows(scorecards)
                db.upsert_scorecard(rows)
                with db.connect() as conn:
                    stored = conn.execute("SELECT COUNT(*) FROM scorecard").fetchone()[0]
                    assert stored > 0

        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)


class TestRuleSignalsFlow:
    def test_compute_and_store_roundtrip(self):
        db = _make_temp_signal_db()
        db_path = db._path
        os.environ["TW_QUANT_DB"] = db_path

        try:
            today = date(2026, 6, 30)

            # Populate all necessary tables for 3 watch stocks
            with db.connect() as conn:
                idx_data = generate_index_data(days=200, start_date=date(2025, 6, 1))
                populate_db(conn, index_rows=idx_data)

            for sid in ["2330", "0050", "2308"]:
                prices = generate_prices(sid, days=200, start_date=date(2025, 6, 1))
                inst = generate_inst_flows(sid, days=100, start_date=date(2025, 12, 1))
                prices_sorted = sorted(prices, key=lambda x: x["trade_date"])
                price_dicts = [{"trade_date": p["trade_date"], "close": p["close"], "volume": p["volume"]} for p in prices_sorted]
                inds = compute_indicators(price_dicts, stock_id=sid)
                with db.connect() as conn:
                    populate_db(conn, prices=prices, inst_rows=inst, indicators=inds)

                # Build features
                from tw_quant_signal.backtest import _compute_features_as_of
                for p in prices_sorted[-60:]:
                    row = _compute_features_as_of(db, sid, p["trade_date"])
                    if row:
                        with db.connect() as conn:
                            conn.execute("DELETE FROM features WHERE trade_date=? AND stock_id=?",
                                         [p["trade_date"], sid])
                            conn.execute(
                                "INSERT INTO features (trade_date, stock_id, data) VALUES (?, ?, ?)",
                                [p["trade_date"], sid, json.dumps(row, ensure_ascii=False)],
                            )

            db = SignalDB(db_path)
            signals = compute_rule_signals(db, trade_date=today.isoformat())
            store_rule_signals(db, signals)

            with db.connect() as conn:
                rs = conn.execute("SELECT stock_id, signal, total_score, triggered_count FROM rule_signals WHERE trade_date=?",
                                  [today.isoformat()]).fetchall()
                assert len(rs) <= 3
                for r in rs:
                    assert r[0] in ["2330", "0050", "2308"]
                    assert r[1] in ("bullish", "bearish", "neutral")

            # Compute stats
            from tw_quant_signal.rules import compute_rule_stats
            stats = compute_rule_stats(db, days=30)
            assert isinstance(stats, dict)
            assert len(stats) > 0

        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)