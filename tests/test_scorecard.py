"""T017 — Unit tests for 11-indicator scorecard (signal_scorecard.py)."""

import json
import os
import tempfile

import pytest

from tw_quant_signal.signal_scorecard import (
    _check_high_240d,
    _check_low_240d,
    _check_inst_3d_buy,
    _check_inst_3d_sell,
    _check_foreign_buy_500,
    _check_foreign_sell_500,
    _check_foreign_3d_buy,
    _check_foreign_3d_sell,
    _check_sity_buy_500,
    _check_sity_sell_500,
    _check_sity_3d_buy,
    _check_sity_3d_sell,
    _check_proprietary_3d_buy,
    _check_proprietary_3d_sell,
    _check_red_3d,
    _check_black_3d,
    _check_above_ma20,
    _check_below_ma20,
    _check_revenue_yoy_up,
    _check_revenue_yoy_down,
    _check_revenue_mom_up2,
    _check_revenue_mom_down2,
    compute_scorecard,
    build_scorecard_rows,
    BULLISH_META,
    BEARISH_META,
    BULLISH_KEYS,
    BEARISH_KEYS,
)
from tw_quant_signal.db import SignalDB
from tw_quant_signal.indicators import compute_indicators

from tests.conftest import populate_db, generate_prices, generate_inst_flows


def _make_temp_signal_db() -> SignalDB:
    fd, tmppath = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = SignalDB(tmppath)
    db.init_db()
    return db


class TestMetaDefinitions:
    def test_bullish_has_11_items(self):
        assert len(BULLISH_META) == 11
        assert len(BULLISH_KEYS) == 11

    def test_bearish_has_11_items(self):
        assert len(BEARISH_META) == 11
        assert len(BEARISH_KEYS) == 11


class TestBullishPriceIndicators:
    def test_high_240d_true(self):
        latest = {"close": 550.0, "open": 548.0, "low": 547.0, "high": 552.0}
        history = [{"close": c, "open": c - 1, "low": c - 2, "high": c + 2} for c in range(200, 400)]
        assert _check_high_240d([latest] + history) is True

    def test_high_240d_false(self):
        latest = {"close": 300.0, "open": 299.0, "low": 298.0, "high": 302.0}
        history = [{"close": c, "open": c - 1, "low": c - 2, "high": c + 2} for c in range(350, 360)]
        assert _check_high_240d([latest] + history) is False

    def test_high_240d_insufficient_data(self):
        assert _check_high_240d([{"close": 500, "high": 500}]) is False
        assert _check_high_240d([]) is False

    def test_red_3d_true(self):
        prices = [
            {"close": 600, "open": 590},
            {"close": 505, "open": 500},
            {"close": 506, "open": 504},
        ]
        assert _check_red_3d(prices) is True

    def test_red_3d_false_with_black(self):
        prices = [
            {"close": 500, "open": 510},
            {"close": 505, "open": 500},
            {"close": 506, "open": 504},
        ]
        assert _check_red_3d(prices) is False

    def test_red_3d_false_equal(self):
        prices = [
            {"close": 500, "open": 500},
            {"close": 505, "open": 500},
            {"close": 506, "open": 504},
        ]
        assert _check_red_3d(prices) is False

    def test_red_3d_insufficient_data(self):
        assert _check_red_3d([{"close": 500, "open": 400}]) is False


class TestBullishInstIndicators:
    def _rows(self, foreign, sity, dealer):
        return [
            {"foreign_investors_net": foreign, "sity_investors_net": sity, "dealer_net": dealer},
            {"foreign_investors_net": foreign, "sity_investors_net": sity, "dealer_net": dealer},
            {"foreign_investors_net": foreign, "sity_investors_net": sity, "dealer_net": dealer},
        ]

    def test_inst_3d_buy_true(self):
        assert _check_inst_3d_buy(self._rows(100, 50, 30)) is True

    def test_inst_3d_buy_false_when_sity_sells(self):
        assert _check_inst_3d_buy(self._rows(100, -10, 30)) is False

    def test_inst_3d_buy_false_when_dealer_sells(self):
        assert _check_inst_3d_buy(self._rows(100, 50, -30)) is False

    def test_inst_3d_buy_insufficient_data(self):
        assert _check_inst_3d_buy([{"foreign_investors_net": 100, "sity_investors_net": 50, "dealer_net": 30}]) is False

    def test_foreign_buy_500_true(self):
        assert _check_foreign_buy_500([{"foreign_investors_net": 600}]) is True
        assert _check_foreign_buy_500([{"foreign_investors_net": 501}]) is True

    def test_foreign_buy_500_false(self):
        assert _check_foreign_buy_500([{"foreign_investors_net": 500}]) is False
        assert _check_foreign_buy_500([{"foreign_investors_net": -100}]) is False
        assert _check_foreign_buy_500([]) is False
        assert _check_foreign_buy_500([{"foreign_investors_net": None}]) is False

    def test_foreign_3d_buy_true(self):
        rows = [{"foreign_investors_net": 100}, {"foreign_investors_net": 200}, {"foreign_investors_net": 1}]
        assert _check_foreign_3d_buy(rows) is True

    def test_foreign_3d_buy_false(self):
        rows = [{"foreign_investors_net": 100}, {"foreign_investors_net": -50}, {"foreign_investors_net": 1}]
        assert _check_foreign_3d_buy(rows) is False

    def test_sity_buy_500(self):
        assert _check_sity_buy_500([{"sity_investors_net": 600}]) is True
        assert _check_sity_buy_500([{"sity_investors_net": 400}]) is False

    def test_sity_3d_buy(self):
        assert _check_sity_3d_buy(self._rows(0, 100, 0)) is True

    def test_proprietary_3d_buy(self):
        assert _check_proprietary_3d_buy(self._rows(0, 0, 100)) is True


class TestBearishPriceIndicators:
    def test_low_240d_true(self):
        latest = {"close": 100.0, "high": 102.0, "low": 98.0}
        history = [{"close": c, "open": c - 1, "low": c - 2, "high": c + 2} for c in range(200, 300)]
        assert _check_low_240d([latest] + history) is True

    def test_low_240d_false(self):
        latest = {"close": 500.0, "low": 498.0}
        history = [{"close": c, "open": c - 1, "low": c - 2, "high": c + 2} for c in range(200, 300)]
        assert _check_low_240d([latest] + history) is False

    def test_low_240d_insufficient_data(self):
        assert _check_low_240d([{"close": 500, "low": 498}]) is False

    def test_black_3d_true(self):
        prices = [
            {"close": 500, "open": 510},
            {"close": 498, "open": 505},
            {"close": 490, "open": 495},
        ]
        assert _check_black_3d(prices) is True

    def test_black_3d_false(self):
        prices = [
            {"close": 500, "open": 510},
            {"close": 505, "open": 500},
            {"close": 490, "open": 495},
        ]
        assert _check_black_3d(prices) is False


class TestBearishInstIndicators:
    def test_inst_3d_sell_true(self):
        rows = [
            {"foreign_investors_net": -100, "sity_investors_net": -50, "dealer_net": -30},
            {"foreign_investors_net": -200, "sity_investors_net": -60, "dealer_net": -40},
            {"foreign_investors_net": -300, "sity_investors_net": -70, "dealer_net": -50},
        ]
        assert _check_inst_3d_sell(rows) is True

    def test_inst_3d_sell_false(self):
        rows = [
            {"foreign_investors_net": -100, "sity_investors_net": -50, "dealer_net": -30},
            {"foreign_investors_net": 200, "sity_investors_net": -60, "dealer_net": -40},
            {"foreign_investors_net": -300, "sity_investors_net": -70, "dealer_net": -50},
        ]
        assert _check_inst_3d_sell(rows) is False

    def test_foreign_sell_500(self):
        assert _check_foreign_sell_500([{"foreign_investors_net": -600}]) is True
        assert _check_foreign_sell_500([{"foreign_investors_net": -500}]) is False
        assert _check_foreign_sell_500([{"foreign_investors_net": 100}]) is False
        assert _check_foreign_sell_500([]) is False

    def test_foreign_3d_sell(self):
        rows = [{"foreign_investors_net": -1} for _ in range(3)]
        assert _check_foreign_3d_sell(rows) is True
        rows_bad = [{"foreign_investors_net": -1}, {"foreign_investors_net": 1}, {"foreign_investors_net": -1}]
        assert _check_foreign_3d_sell(rows_bad) is False

    def test_sity_sell_500(self):
        assert _check_sity_sell_500([{"sity_investors_net": -600}]) is True
        assert _check_sity_sell_500([{"sity_investors_net": 100}]) is False

    def test_sity_3d_sell(self):
        assert _check_sity_3d_sell([{"sity_investors_net": -1} for _ in range(3)]) is True

    def test_proprietary_3d_sell(self):
        assert _check_proprietary_3d_sell([{"dealer_net": -1} for _ in range(3)]) is True


class TestMa20Indicators:
    def test_above_ma20_true(self):
        assert _check_above_ma20([{"close": 105}], 100) is True

    def test_above_ma20_false(self):
        assert _check_above_ma20([{"close": 95}], 100) is False

    def test_above_ma20_none_ma(self):
        assert _check_above_ma20([{"close": 105}], None) is False

    def test_below_ma20_true(self):
        assert _check_below_ma20([{"close": 95}], 100) is True

    def test_below_ma20_false(self):
        assert _check_below_ma20([{"close": 105}], 100) is False

    def test_equal_not_above_or_below(self):
        assert _check_above_ma20([{"close": 100}], 100) is False
        assert _check_below_ma20([{"close": 100}], 100) is False


class TestRevenueIndicators:
    def test_yoy_up_true(self):
        assert _check_revenue_yoy_up([{"yoy_change": 15.0}]) is True
        assert _check_revenue_yoy_up([{"yoy_change": 10.1}]) is True

    def test_yoy_up_false(self):
        assert _check_revenue_yoy_up([{"yoy_change": 10.0}]) is False
        assert _check_revenue_yoy_up([{"yoy_change": -5.0}]) is False
        assert _check_revenue_yoy_up([]) is False

    def test_yoy_down_true(self):
        assert _check_revenue_yoy_down([{"yoy_change": -15.0}]) is True
        assert _check_revenue_yoy_down([{"yoy_change": -10.1}]) is True

    def test_yoy_down_false(self):
        assert _check_revenue_yoy_down([{"yoy_change": -5.0}]) is False
        assert _check_revenue_yoy_down([{"yoy_change": 10.0}]) is False

    def test_mom_up2_true(self):
        assert _check_revenue_mom_up2([{"mom_change": 5.0}, {"mom_change": 3.0}]) is True

    def test_mom_up2_false(self):
        assert _check_revenue_mom_up2([{"mom_change": 5.0}, {"mom_change": -1.0}]) is False
        assert _check_revenue_mom_up2([{"mom_change": -5.0}, {"mom_change": -3.0}]) is False
        assert _check_revenue_mom_up2([{"mom_change": 5.0}]) is False

    def test_mom_down2_true(self):
        assert _check_revenue_mom_down2([{"mom_change": -5.0}, {"mom_change": -3.0}]) is True

    def test_mom_down2_false(self):
        assert _check_revenue_mom_down2([{"mom_change": -5.0}, {"mom_change": 1.0}]) is False
        assert _check_revenue_mom_down2([{"mom_change": -5.0}]) is False


class TestComputeScorecard:
    def test_no_data_returns_default(self):
        db = _make_temp_signal_db()
        try:
            result = compute_scorecard(db, "2330")
            assert result["stock_id"] == "2330"
            assert result["trade_date"] is None
            assert result["bullish"]["count"] == 0
            assert result["bullish"]["ratio"] == "0/11"
            assert result["bearish"]["count"] == 0
        finally:
            if os.path.exists(db._path):
                os.unlink(db._path)

    def test_full_scorecard_with_data(self):
        db = _make_temp_signal_db()
        try:
            prices = generate_prices("2330", days=260)
            inst = generate_inst_flows("2330", days=10)
            prices_sorted = sorted(prices, key=lambda x: x["trade_date"])
            price_dicts = [{"trade_date": p["trade_date"], "close": p["close"], "volume": p["volume"]} for p in prices_sorted]
            inds = compute_indicators(price_dicts, stock_id="2330")
            monthly_rev = [
                {"stock_id": "2330", "year_month": "202608", "revenue": 1000000, "mom_change": 5.0, "yoy_change": 12.0},
                {"stock_id": "2330", "year_month": "202607", "revenue": 950000, "mom_change": 3.0, "yoy_change": 8.0},
                {"stock_id": "2330", "year_month": "202606", "revenue": 920000, "mom_change": 2.0, "yoy_change": 5.0},
            ]
            with db.connect() as conn:
                populate_db(conn, prices=prices_sorted, inst_rows=inst,
                            indicators=inds, monthly_rev=monthly_rev)

            trade_date = prices_sorted[-1]["trade_date"]
            result = compute_scorecard(db, "2330", trade_date=trade_date)

            assert result["stock_id"] == "2330"
            assert result["trade_date"] == trade_date
            assert "bullish" in result and "bearish" in result
            # All 11 bullish keys present as booleans
            for key in BULLISH_KEYS:
                assert key in result["bullish"], f"missing bullish key {key}"
                assert isinstance(result["bullish"][key], bool)
            for key in BEARISH_KEYS:
                assert key in result["bearish"]
                assert isinstance(result["bearish"][key], bool)
            # count = sum of booleans
            assert result["bullish"]["count"] == sum(
                1 for k in BULLISH_KEYS if result["bullish"][k]
            )
            assert result["bullish"]["ratio"] == f"{result['bullish']['count']}/11"
            assert result["bearish"]["count"] == sum(
                1 for k in BEARISH_KEYS if result["bearish"][k]
            )
            # revenue indicators should be true (yoy 12% > 10, mom both positive)
            assert result["bullish"]["revenue_yoy_up"] is True
            assert result["bullish"]["revenue_mom_up2"] is True
        finally:
            if os.path.exists(db._path):
                os.unlink(db._path)

    def test_bearish_scenario(self):
        db = _make_temp_signal_db()
        try:
            # Downtrend prices: latest close below all previous lows
            closes = [500.0 - i * 2.0 for i in range(260)]
            prices = []
            for i, c in enumerate(closes):
                prices.append({
                    "stock_id": "2330",
                    "trade_date": f"2026-{(i // 28) + 1:02d}-{(i % 28 + 1):02d}",
                    "open": c + 3.0,
                    "high": c + 5.0,
                    "low": c - 2.0,
                    "close": c,
                    "volume": 1_000_000,
                    "amount": c * 1000.0,
                })
            # Institutional flows all negative
            inst = []
            for i in range(10):
                inst.append({
                    "stock_id": "2330",
                    "trade_date": f"2026-08-{i+1:02d}",
                    "market": "TSE",
                    "foreign_investors_net": -1000 - i * 100,
                    "sity_investors_net": -500 - i * 50,
                    "dealer_net": -100 - i * 10,
                })
            prices_sorted = sorted(prices, key=lambda x: x["trade_date"])
            price_dicts = [{"trade_date": p["trade_date"], "close": p["close"], "volume": p["volume"]} for p in prices_sorted]
            inds = compute_indicators(price_dicts, stock_id="2330")
            monthly_rev = [
                {"stock_id": "2330", "year_month": "202608", "revenue": 1000000, "mom_change": -5.0, "yoy_change": -12.0},
                {"stock_id": "2330", "year_month": "202607", "revenue": 1050000, "mom_change": -3.0, "yoy_change": -8.0},
            ]
            with db.connect() as conn:
                populate_db(conn, prices=prices_sorted, inst_rows=inst,
                            indicators=inds, monthly_rev=monthly_rev)

            trade_date = prices_sorted[-1]["trade_date"]
            result = compute_scorecard(db, "2330", trade_date=trade_date)

            # Bearish indicators should dominate
            assert result["bearish"]["low_240d"] is True
            assert result["bearish"]["inst_3d_sell"] is True
            assert result["bearish"]["foreign_sell_500"] is True
            assert result["bearish"]["foreign_3d_sell"] is True
            assert result["bearish"]["sity_3d_sell"] is True
            assert result["bearish"]["proprietary_3d_sell"] is True
            assert result["bearish"]["black_3d"] is True
            assert result["bearish"]["revenue_yoy_down"] is True
            assert result["bearish"]["revenue_mom_down2"] is True
            assert result["bearish"]["count"] > 0
        finally:
            if os.path.exists(db._path):
                os.unlink(db._path)


class TestBuildScorecardRows:
    def test_build_scorecard_rows(self):
        result = {
            "trade_date": "2026-08-01",
            "stock_id": "2330",
            "bullish": {
                "count": 5, "ratio": "5/11",
                "high_240d": True, "inst_3d_buy": False, "foreign_buy_500": True,
                "foreign_3d_buy": True, "sity_buy_500": False, "sity_3d_buy": False,
                "proprietary_3d_buy": True, "red_3d": True, "above_ma20": True,
                "revenue_yoy_up": False, "revenue_mom_up2": False,
            },
            "bearish": {
                "count": 1, "ratio": "1/11",
                "low_240d": False, "inst_3d_sell": False, "foreign_sell_500": False,
                "foreign_3d_sell": False, "sity_sell_500": False, "sity_3d_sell": False,
                "proprietary_3d_sell": False, "black_3d": True, "below_ma20": False,
                "revenue_yoy_down": False, "revenue_mom_down2": False,
            },
        }
        rows = build_scorecard_rows([result])
        assert len(rows) == 1
        row = rows[0]
        assert row["trade_date"] == "2026-08-01"
        assert row["stock_id"] == "2330"
        assert row["bullish_score"] == 5
        assert row["bearish_score"] == 1
        assert row["bullish_detail"]["high_240d"] is True
        assert row["bullish_detail"]["inst_3d_buy"] is False
        assert row["bearish_detail"]["black_3d"] is True
        # detail should contain exactly the 11 keys
        assert set(row["bullish_detail"].keys()) == set(BULLISH_KEYS)
        assert set(row["bearish_detail"].keys()) == set(BEARISH_KEYS)
