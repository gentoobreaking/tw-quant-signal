"""T017 — Unit tests for technical indicators (indicators.py)."""

import numpy as np
import pandas as pd
import pytest
from datetime import date, timedelta

from tw_quant_signal.indicators import (
    compute_indicators,
    compute_weekly_indicators,
    compute_monthly_indicators,
    ma_alignment,
    bb_position,
    rsi_signal,
)


def _build_price_list(closes):
    """Build price dicts with sequential dates for compute_indicators."""
    rows = []
    for i, c in enumerate(closes):
        d = (date(2026, 1, 5) + timedelta(days=i)).isoformat()
        rows.append({
            "trade_date": d,
            "close": c,
            "volume": 1_000_000 + i * 10000,
        })
    return rows


class TestComputeIndicators:
    def test_empty_input(self):
        assert compute_indicators([]) == []

    def test_basic_output_structure(self):
        closes = [500.0 + i * 0.5 for i in range(120)]
        prices = _build_price_list(closes)
        result = compute_indicators(prices, stock_id="2330")
        assert len(result) > 0
        for r in result:
            assert "stock_id" in r
            assert "trade_date" in r
            assert "ma5" in r
            assert "ma20" in r
            assert "ma60" in r
            assert "bb_upper" in r
            assert "bb_middle" in r
            assert "bb_lower" in r
            assert "rsi14" in r
            assert "volume_ma5" in r
            assert "volume_ma20" in r

    def test_ma_values_nan_at_start_then_valid(self):
        prices = _build_price_list([100.0 + i * 0.5 for i in range(120)])
        result = compute_indicators(prices, stock_id="2330")
        # First few rows should have NaN for longer windows
        rows = result
        for i in range(59):
            assert rows[i].get("ma60") is None or np.isnan(rows[i].get("ma60", np.nan))
        # Row 60+ should have values
        latest = rows[-1]
        assert latest["ma5"] is not None and not np.isnan(latest["ma5"])

    def test_known_values_constant_prices(self):
        # Constant closes -> all MAs equal to close, BB middle = close, RSI is NaN
        closes = [100.0] * 80
        prices = _build_price_list(closes)
        result = compute_indicators(prices, stock_id="2330")
        latest = result[-1]
        assert latest["ma5"] == 100.0
        assert latest["ma20"] == 100.0
        assert latest["ma60"] == 100.0
        assert latest["bb_middle"] == 100.0
        # volume_ma5 = average of last 5 volumes = (5,000,000 + 10000*385)/5 = 1,770,000
        assert latest["volume_ma5"] == 1_770_000.0
        assert latest["rsi14"] is None or np.isnan(latest["rsi14"])

    def test_known_values_linear_prices(self):
        # Linear uptrend: MA5 of last 5 closes is (close-8 + close-6 + close-4 + close-2 + close)/5
        closes = [100.0 + i * 2.0 for i in range(80)]
        prices = _build_price_list(closes)
        result = compute_indicators(prices, stock_id="2330")
        latest = result[-1]
        last5 = closes[-5:]
        assert latest["ma5"] == round(sum(last5) / 5, 2)

    def test_bb_bands_monotonic_price(self):
        closes = [100.0 + i * 0.5 for i in range(120)]
        prices = _build_price_list(closes)
        result = compute_indicators(prices, stock_id="2330")
        latest = result[-1]
        assert latest["bb_upper"] > latest["bb_middle"] > latest["bb_lower"]

    def test_rsi_between_0_100(self):
        closes = [100.0 + i * 0.5 for i in range(120)]
        prices = _build_price_list(closes)
        result = compute_indicators(prices, stock_id="2330")
        for r in result:
            if r["rsi14"] is not None and not np.isnan(r["rsi14"]):
                assert 0 <= r["rsi14"] <= 100


class TestComputeWeeklyIndicators:
    def test_empty_input(self):
        assert compute_weekly_indicators([]) == []

    def test_weekly_aggregation(self):
        # 8 weeks of daily data (Mon-Fri), constant close 100
        prices = []
        i = 0
        d = date(2026, 1, 5)
        while len(prices) < 40:
            if d.weekday() < 5:
                prices.append({
                    "trade_date": d.isoformat(),
                    "close": 100.0 + len(prices) * 0.1,
                    "high": 105.0,
                    "low": 95.0,
                    "volume": 1_000_000 + len(prices) * 1000,
                })
                i += 1
            d += timedelta(days=1)

        result = compute_weekly_indicators(prices, stock_id="2330")
        assert len(result) > 0
        for r in result:
            assert "stock_id" in r and r["stock_id"] == "2330"
            assert "close" in r
            assert "ma5" in r
            assert "ma20" in r
            assert "ma60" in r
            assert "bb_upper" in r and "bb_middle" in r and "bb_lower" in r
            assert "rsi14" in r
        # Weekly close = last daily close of the week
        assert result[0]["close"] == prices[4]["close"]

    def test_weekly_volume_is_sum(self):
        prices = []
        d = date(2026, 1, 5)
        while len(prices) < 45:
            if d.weekday() < 5:
                prices.append({
                    "trade_date": d.isoformat(),
                    "close": 100.0,
                    "high": 105.0,
                    "low": 95.0,
                    "volume": 10_000,
                })
            d += timedelta(days=1)
        result = compute_weekly_indicators(prices, stock_id="2330")
        # Last week: volume_ma5 over 5 weeks of constant 50k volume = 50k
        assert result[-1]["volume_ma5"] == 50_000
        assert result[0]["close"] == 100.0


class TestComputeMonthlyIndicators:
    def test_empty_input(self):
        assert compute_monthly_indicators([]) == []

    def test_monthly_aggregation(self):
        # ~7 months of daily data
        prices = []
        d = date(2026, 1, 5)
        while len(prices) < 150:
            if d.weekday() < 5:
                prices.append({
                    "trade_date": d.isoformat(),
                    "close": 100.0 + len(prices) * 0.1,
                    "high": 105.0,
                    "low": 95.0,
                    "volume": 1_000_000 + len(prices) * 1000,
                })
            d += timedelta(days=1)

        result = compute_monthly_indicators(prices, stock_id="2330")
        assert len(result) > 0
        for r in result:
            assert "ma3" in r
            assert "ma6" in r
            assert "ma12" in r
            assert "bb_upper" in r and "bb_middle" in r and "bb_lower" in r
            assert "rsi9" in r
            assert "volume_ma3" in r
            assert "volume_ma6" in r

    def test_monthly_close_last_of_month(self):
        prices = [
            {"trade_date": "2026-01-05", "close": 100.0, "high": 105.0, "low": 95.0, "volume": 10_000},
            {"trade_date": "2026-01-15", "close": 110.0, "high": 115.0, "low": 105.0, "volume": 20_000},
            {"trade_date": "2026-01-30", "close": 120.0, "high": 125.0, "low": 115.0, "volume": 30_000},
            {"trade_date": "2026-02-05", "close": 125.0, "high": 130.0, "low": 120.0, "volume": 40_000},
            {"trade_date": "2026-02-27", "close": 115.0, "high": 130.0, "low": 110.0, "volume": 50_000},
            {"trade_date": "2026-03-10", "close": 118.0, "high": 122.0, "low": 112.0, "volume": 60_000},
            {"trade_date": "2026-03-31", "close": 122.0, "high": 126.0, "low": 116.0, "volume": 70_000},
        ]
        result = compute_monthly_indicators(prices, stock_id="2330")
        assert result[0]["trade_date"] == "2026-01-30"
        assert result[0]["close"] == 120.0
        assert result[1]["trade_date"] == "2026-02-27"
        assert result[1]["close"] == 115.0
        # volume_ma3 at 3rd month = avg of monthly sums (60k, 90k, 130k)
        assert result[2]["volume_ma3"] == pytest.approx((60_000 + 90_000 + 130_000) / 3, rel=1e-6)


class TestMaAlignment:
    def test_bullish(self):
        assert ma_alignment(20, 19, 18) == "bullish"

    def test_bearish(self):
        assert ma_alignment(18, 19, 20) == "bearish"

    def test_neutral(self):
        assert ma_alignment(20, 18, 19) == "neutral"

    def test_none_returns_unknown(self):
        assert ma_alignment(None, 19, 18) == "unknown"
        assert ma_alignment(20, None, 18) == "unknown"


class TestBbPosition:
    def test_above_upper(self):
        assert bb_position(110, 105, 95, 100) == "above_upper"
        assert bb_position(105, 105, 95, 100) == "above_upper"

    def test_below_lower(self):
        assert bb_position(90, 105, 95, 100) == "below_lower"

    def test_above_mid(self):
        assert bb_position(102, 105, 95, 100) == "above_mid"

    def test_below_mid(self):
        assert bb_position(98, 105, 95, 100) == "below_mid"

    def test_none_returns_unknown(self):
        assert bb_position(None, 105, 95, 100) == "unknown"


class TestRsiSignal:
    def test_overbought(self):
        assert rsi_signal(70) == "overbought"
        assert rsi_signal(85) == "overbought"

    def test_oversold(self):
        assert rsi_signal(30) == "oversold"
        assert rsi_signal(15) == "oversold"

    def test_bullish(self):
        assert rsi_signal(55) == "bullish"
        assert rsi_signal(65) == "bullish"

    def test_bearish(self):
        assert rsi_signal(35) == "bearish"
        assert rsi_signal(45) == "bearish"

    def test_unknown(self):
        assert rsi_signal(None) == "unknown"