"""T017 — Unit tests for feature signal functions (features.py)."""

import os
import tempfile

import pytest

from tw_quant_signal.db import SignalDB
from tw_quant_signal.indicators import compute_indicators
from tw_quant_signal.features import (
    _signal_ma,
    _signal_rsi,
    _signal_bb,
    _signal_pe,
    _signal_pb,
    _signal_dy,
    _inst_signal,
    _trend_direction,
    _relative_position,
    _stock_features,
    _index_features,
    _market_breadth,
    compute_all_features,
    compute_indicators_for_stock,
)

from tests.conftest import populate_db, generate_prices, generate_inst_flows, generate_index_data


class TestSignalMA:
    def test_bullish(self):
        assert _signal_ma(20, 19, 18) == "bullish"

    def test_bearish(self):
        assert _signal_ma(18, 19, 20) == "bearish"

    def test_neutral(self):
        assert _signal_ma(20, 18, 19) == "neutral"

    def test_none_returns_unknown(self):
        assert _signal_ma(None, 19, 18) == "unknown"


class TestSignalRSI:
    def test_overbought(self):
        assert _signal_rsi(70) == "overbought"

    def test_oversold(self):
        assert _signal_rsi(25) == "oversold"

    def test_bullish(self):
        assert _signal_rsi(60) == "bullish"

    def test_bearish(self):
        assert _signal_rsi(40) == "bearish"

    def test_none(self):
        assert _signal_rsi(None) == "unknown"


class TestSignalBB:
    def test_above_upper(self):
        assert _signal_bb(110, 105, 95, 100) == "above_upper"

    def test_below_lower(self):
        assert _signal_bb(90, 105, 95, 100) == "below_lower"

    def test_above_mid(self):
        assert _signal_bb(102, 105, 95, 100) == "above_mid"

    def test_below_mid(self):
        assert _signal_bb(98, 105, 95, 100) == "below_mid"

    def test_none_values(self):
        assert _signal_bb(None, 105, 95, 100) == "unknown"


class TestSignalPE:
    def test_low(self):
        assert _signal_pe(10) == "low"
        assert _signal_pe(14.9) == "low"

    def test_fair(self):
        assert _signal_pe(20) == "fair"

    def test_high(self):
        assert _signal_pe(26) == "high"

    def test_none(self):
        assert _signal_pe(None) == "unknown"


class TestSignalPB:
    def test_low(self):
        assert _signal_pb(1.0) == "low"

    def test_fair(self):
        assert _signal_pb(2.0) == "fair"

    def test_high(self):
        assert _signal_pb(4.0) == "high"

    def test_none(self):
        assert _signal_pb(None) == "unknown"


class TestSignalDY:
    def test_high(self):
        assert _signal_dy(0.06) == "high"

    def test_fair(self):
        assert _signal_dy(0.03) == "fair"

    def test_low(self):
        assert _signal_dy(0.01) == "low"

    def test_none(self):
        assert _signal_dy(None) == "unknown"


class TestInstSignal:
    def test_strong(self):
        assert _inst_signal(10_000_000) == "strong"

    def test_moderate(self):
        assert _inst_signal(2_000_000) == "moderate"

    def test_weak(self):
        assert _inst_signal(500_000) == "weak"

    def test_none(self):
        assert _inst_signal(None) == "unknown"


class TestTrendDirection:
    def test_strong_buy(self):
        assert _trend_direction(2_000_000) == "strong_buy"

    def test_buy(self):
        assert _trend_direction(500_000) == "buy"

    def test_neutral(self):
        assert _trend_direction(100_000) == "neutral"

    def test_sell(self):
        assert _trend_direction(-500_000) == "sell"

    def test_strong_sell(self):
        assert _trend_direction(-2_000_000) == "strong_sell"

    def test_none(self):
        assert _trend_direction(None) is None


class TestRelativePosition:
    def test_above(self):
        assert _relative_position(110, 100) == "above"

    def test_below(self):
        assert _relative_position(90, 100) == "below"

    def test_at(self):
        assert _relative_position(100.5, 100) == "at"

    def test_none(self):
        assert _relative_position(None, 100) is None
        assert _relative_position(100, None) is None


def _make_temp_signal_db() -> SignalDB:
    fd, tmppath = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = SignalDB(tmppath)
    db.init_db()
    return db


def _seed_full_db(db: SignalDB):
    """Populate prices/indicators/inst flows/index for 3 watch stocks."""
    import json

    with db.connect() as conn:
        idx = generate_index_data(days=260, start_date=__import__("datetime").date(2025, 1, 5))
        populate_db(conn, index_rows=idx)

    for sid in ["2330", "0050", "2308"]:
        prices = generate_prices(sid, days=260)
        inst = generate_inst_flows(sid, days=10)
        prices_sorted = sorted(prices, key=lambda x: x["trade_date"])
        price_dicts = [{"trade_date": p["trade_date"], "close": p["close"], "volume": p["volume"]} for p in prices_sorted]
        inds = compute_indicators(price_dicts, stock_id=sid)
        with db.connect() as conn:
            populate_db(conn, prices=prices_sorted, inst_rows=inst, indicators=inds)


class TestStockFeatures:
    def test_stock_features_full(self):
        db = _make_temp_signal_db()
        try:
            _seed_full_db(db)
            row = _stock_features(db, "2330", val={"pe_ratio": 20, "pb_ratio": 2.0, "dividend_yield": 0.03})
            assert row is not None
            assert row["stock_id"] == "2330"
            assert "trade_date" in row
            assert "close" in row
            assert row["ma_alignment"] in ("bullish", "bearish", "neutral", "unknown")
            assert row["rsi_signal"] in ("overbought", "oversold", "bullish", "bearish", "unknown")
            assert row["bb_position"] in ("above_upper", "below_lower", "above_mid", "below_mid", "unknown")
            assert row["pe_ratio"] == 20
            assert row["pb_ratio"] == 2.0
            assert row["dividend_yield"] == 0.03
            assert row["pe_signal"] == "fair"
            assert row["pb_signal"] == "fair"
            assert row["dy_signal"] == "fair"
        finally:
            if os.path.exists(db._path):
                os.unlink(db._path)

    def test_stock_features_with_indicators_map(self):
        db = _make_temp_signal_db()
        try:
            prices = generate_prices("2330", days=260)
            prices_sorted = sorted(prices, key=lambda x: x["trade_date"])
            with db.connect() as conn:
                populate_db(conn, prices=prices_sorted)
            price_dicts = [{"trade_date": p["trade_date"], "close": p["close"], "volume": p["volume"]} for p in prices_sorted]
            inds = compute_indicators(price_dicts, stock_id="2330")
            row = _stock_features(db, "2330", indicators=inds)
            assert row is not None
            assert row["stock_id"] == "2330"
        finally:
            if os.path.exists(db._path):
                os.unlink(db._path)

    def test_stock_features_insufficient_data(self):
        db = _make_temp_signal_db()
        try:
            # Only 10 days of prices -> returns None
            prices = generate_prices("2330", days=10)
            with db.connect() as conn:
                populate_db(conn, prices=prices)
            row = _stock_features(db, "2330")
            assert row is None
        finally:
            if os.path.exists(db._path):
                os.unlink(db._path)


class TestIndexFeatures:
    def test_index_features(self):
        db = _make_temp_signal_db()
        try:
            idx = generate_index_data(days=260)
            with db.connect() as conn:
                populate_db(conn, index_rows=idx)
            row = _index_features(db)
            assert row is not None
            assert row["stock_id"] == "^TWII"
            assert "index_ma20" in row
            assert "index_ma60" in row
            assert row["index_vs_ma20"] in ("above", "below", "at")
            assert row["index_vs_ma60"] in ("above", "below", "at")
            assert "change_pct" in row
        finally:
            if os.path.exists(db._path):
                os.unlink(db._path)

    def test_index_features_insufficient_data(self):
        db = _make_temp_signal_db()
        try:
            idx = generate_index_data(days=10)
            with db.connect() as conn:
                populate_db(conn, index_rows=idx)
            assert _index_features(db) is None
        finally:
            if os.path.exists(db._path):
                os.unlink(db._path)


class TestMarketBreadth:
    def test_breadth_signal(self):
        db = _make_temp_signal_db()
        try:
            # 3 stocks on same date: 2 buy, 1 sell -> ratio 0.667 -> broad
            flows = []
            for sid, net in [("2330", 1000), ("0050", 500), ("2308", -300)]:
                flows.append({
                    "stock_id": sid, "trade_date": "2026-08-03", "market": "TSE",
                    "foreign_investors_net": net, "sity_investors_net": 0, "dealer_net": 0,
                })
            with db.connect() as conn:
                populate_db(conn, inst_rows=flows)
            row = _market_breadth(db)
            assert row is not None
            assert row["stock_id"] == "BREADTH"
            assert row["total_stocks"] == 3
            assert row["foreign_buy_count"] == 2
            assert row["foreign_buy_ratio"] == pytest.approx(0.6667, abs=1e-3)
            assert row["breadth_signal"] == "broad"
        finally:
            if os.path.exists(db._path):
                os.unlink(db._path)

    def test_breadth_no_data(self):
        db = _make_temp_signal_db()
        try:
            assert _market_breadth(db) is None
        finally:
            if os.path.exists(db._path):
                os.unlink(db._path)


class TestComputeIndicatorsForStock:
    def test_computes_from_db(self):
        db = _make_temp_signal_db()
        try:
            prices = generate_prices("2330", days=260)
            with db.connect() as conn:
                populate_db(conn, prices=prices)
            inds = compute_indicators_for_stock(db, "2330")
            assert len(inds) > 0
            assert inds[-1]["stock_id"] == "2330"
        finally:
            if os.path.exists(db._path):
                os.unlink(db._path)

    def test_insufficient_data_returns_empty(self):
        db = _make_temp_signal_db()
        try:
            prices = generate_prices("2330", days=30)
            with db.connect() as conn:
                populate_db(conn, prices=prices)
            assert compute_indicators_for_stock(db, "2330") == []
        finally:
            if os.path.exists(db._path):
                os.unlink(db._path)


class TestComputeAllFeatures:
    def test_all_features_for_watchlist(self):
        db = _make_temp_signal_db()
        try:
            _seed_full_db(db)
            val_map = {
                "2330": {"pe_ratio": 20, "pb_ratio": 2.0, "dividend_yield": 0.03},
                "0050": {"pe_ratio": 18, "pb_ratio": 1.8, "dividend_yield": 0.04},
                "2308": {"pe_ratio": 22, "pb_ratio": 2.5, "dividend_yield": 0.02},
            }
            features = compute_all_features(db, val_map=val_map)
            assert isinstance(features, list)
            ids = [f["stock_id"] for f in features]
            # 3 stocks + index + breadth
            assert "2330" in ids and "0050" in ids and "2308" in ids
            assert "^TWII" in ids
            assert "BREADTH" in ids
        finally:
            if os.path.exists(db._path):
                os.unlink(db._path)