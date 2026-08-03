"""T017 — Unit tests for backtest framework (backtest.py)."""

import os
import tempfile
from datetime import date, timedelta

from tw_quant_signal.backtest import (
    CostModel,
    _forward_return,
    _market_state,
    run_backtest,
    _compute_stats,
)
from tw_quant_signal.db import SignalDB

from tests.conftest import (
    populate_db,
    generate_prices,
    generate_index_data,
    generate_inst_flows,
)


def _make_temp_signal_db() -> SignalDB:
    fd, tmppath = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = SignalDB(tmppath)
    db.init_db()
    return db


class TestCostModel:
    def test_default_params(self):
        cm = CostModel()
        assert cm.tax_sell == 0.003
        assert cm.tax_daytrade == 0.0015
        assert cm.commission == 0.001425 * 0.6

    def test_round_trip_cost_non_daytrade(self):
        cm = CostModel(tax_sell=0.003, commission=0.001425, discount=0.6)
        cost = cm.round_trip_cost()
        expected = 0.001425 * 0.6 + 0.001425 * 0.6 + 0.003
        assert abs(cost - expected) < 1e-8

    def test_round_trip_cost_daytrade(self):
        cm = CostModel(tax_sell=0.003, tax_daytrade=0.0015, commission=0.001425, discount=0.6)
        cost = cm.round_trip_cost(is_daytrade=True)
        expected = 0.001425 * 0.6 + 0.001425 * 0.6 + 0.0015
        assert abs(cost - expected) < 1e-8

    def test_net_return(self):
        cm = CostModel(tax_sell=0.003, commission=0.001425, discount=0.6)
        gross = 0.01
        net = cm.net_return(gross)
        assert net == gross - cm.round_trip_cost()

    def test_net_return_negative_gross(self):
        cm = CostModel(tax_sell=0.003, commission=0.001425, discount=0.6)
        net = cm.net_return(-0.01)
        assert net < -0.01

    def test_custom_params(self):
        cm = CostModel(tax_sell=0.005, commission=0.002, discount=0.5)
        expected = 0.002 * 0.5 * 2 + 0.005
        assert abs(cm.round_trip_cost() - expected) < 1e-8


class TestForwardReturn:
    def test_returns_ratio_with_data(self):
        db = _make_temp_signal_db()
        try:
            today = date(2026, 8, 1)
            prices = []
            for i in range(30):
                d = today + timedelta(days=i)
                if d.weekday() >= 5:
                    continue
                prices.append({
                    "stock_id": "2330",
                    "trade_date": d.isoformat(),
                    "close": 500.0 + len(prices) * 1.0,
                    "open": 499.0,
                    "high": 505.0,
                    "low": 498.0,
                    "volume": 1_000_000,
                    "amount": 500_000.0,
                })
            with db.connect() as conn:
                populate_db(conn, prices=prices)

            from_date = prices[0]["trade_date"]
            # Forward returns: buy at first close after from_date, sell at (days-1)-th
            # forward close, i.e. rows[days-1] where buy=rows[0].
            with db.connect() as conn:
                rows = conn.execute(
                    "SELECT close FROM daily_prices WHERE stock_id='2330' AND trade_date>? "
                    "ORDER BY trade_date LIMIT ?",
                    [from_date, 10],
                ).fetchall()
            assert len(rows) >= 5
            expected = (rows[4][0] - rows[0][0]) / rows[0][0]
            ret = _forward_return(db, "2330", from_date, days=5)
            assert ret is not None
            assert abs(ret - expected) < 1e-9

        finally:
            if os.path.exists(db._path):
                os.unlink(db._path)

    def test_insufficient_data_returns_none(self):
        db = _make_temp_signal_db()
        try:
            ret = _forward_return(db, "2330", "2026-08-01", days=5)
            assert ret is None
        finally:
            if os.path.exists(db._path):
                os.unlink(db._path)

    def test_not_enough_forward_days_returns_none(self):
        db = _make_temp_signal_db()
        try:
            prices = [
                {"stock_id": "2330", "trade_date": f"2026-08-{i+1:02d}",
                 "close": 500.0, "volume": 1_000_000}
                for i in range(3)
            ]
            with db.connect() as conn:
                populate_db(conn, prices=prices)
            ret = _forward_return(db, "2330", "2026-08-01", days=5)
            assert ret is None
        finally:
            if os.path.exists(db._path):
                os.unlink(db._path)


class TestMarketState:
    def test_bull(self):
        feat = {"index_vs_ma20": "above", "index_vs_ma60": "above"}
        assert _market_state(feat) == "bull"

    def test_bear(self):
        feat = {"index_vs_ma20": "below", "index_vs_ma60": "below"}
        assert _market_state(feat) == "bear"

    def test_range_mixed(self):
        assert _market_state({"index_vs_ma20": "above", "index_vs_ma60": "below"}) == "range"

    def test_range_at(self):
        assert _market_state({"index_vs_ma20": "at", "index_vs_ma60": "at"}) == "range"


class TestComputeStats:
    def _rule_stats_fixture(self):
        rules = [
            {"id": "U001", "name": "Rule A", "type": "bullish"},
            {"id": "B001", "name": "Rule B", "type": "bearish"},
        ]
        stats = {
            "U001": {
                "id": "U001", "name": "Rule A", "type": "bullish",
                "triggers": 4, "wins": 3, "losses": 1,
                "returns": [0.02, -0.01, 0.03, 0.01],
                "drawdowns": [], "by_state": {"bull": 2, "bear": 0, "range": 2},
                "states_triggered": ["bull", "bull", "range", "range"],
                "returns_by_state": {"bull": [0.02, -0.01], "bear": [], "range": [0.03, 0.01]},
            },
            "B001": {
                "id": "B001", "name": "Rule B", "type": "bearish",
                "triggers": 2, "wins": 1, "losses": 1,
                "returns": [0.01, -0.02],
                "drawdowns": [], "by_state": {"bull": 1, "bear": 0, "range": 1},
                "states_triggered": ["bull", "range"],
                "returns_by_state": {"bull": [0.01], "bear": [], "range": [-0.02]},
            },
        }
        return stats, rules

    def test_stats_structure(self):
        stats, rules = self._rule_stats_fixture()
        results = _compute_stats(stats, rules, total_tested=6)
        assert len(results) == 2
        r = results[0]
        assert r["rule_id"] == "U001"
        assert r["win_rate"] == 0.75  # 3/4
        assert r["avg_return"] == round((0.02 - 0.01 + 0.03 + 0.01) / 4, 4)
        assert r["triggers"] == 4
        assert r["max_drawdown"] > 0
        assert r["profit_ratio"] > 0
        assert r["total_rules_tested"] == 6
        assert r["state_win_rate"]["bull"] == 0.5
        assert r["state_win_rate"]["range"] == 1.0
        assert r["max_consecutive_losses"] == 1

    def test_stats_empty(self):
        rules = [
            {"id": "U001", "name": "Rule A", "type": "bullish"},
            {"id": "B001", "name": "Rule B", "type": "bearish"},
        ]
        stats = {
            rid: {
                "id": rid, "name": r["name"], "type": r["type"],
                "triggers": 0, "wins": 0, "losses": 0,
                "returns": [], "drawdowns": [],
                "by_state": {"bull": 0, "bear": 0, "range": 0},
                "states_triggered": [],
                "returns_by_state": {"bull": [], "bear": [], "range": []},
            }
            for rid, r in zip(["U001", "B001"], rules)
        }
        results = _compute_stats(stats, rules, total_tested=0)
        for r in results:
            assert r["win_rate"] == 0
            assert r["avg_return"] == 0
            assert r["profit_ratio"] == 0
            assert r["max_drawdown"] == 0
            assert r["max_consecutive_losses"] == 0
            assert r["state_win_rate"] == {"bull": 0, "bear": 0, "range": 0}


class TestRunBacktest:
    def test_run_backtest_small_sample(self):
        db = _make_temp_signal_db()
        try:
            prices = generate_prices("2330", days=260, start_date=date(2025, 1, 5))
            inst = generate_inst_flows("2330", days=120, start_date=date(2025, 6, 1))
            idx_data = generate_index_data(days=260, start_date=date(2025, 1, 5))

            prices_sorted = sorted(prices, key=lambda x: x["trade_date"])
            from tw_quant_signal.indicators import compute_indicators
            price_dicts = [{"trade_date": p["trade_date"], "close": p["close"], "volume": p["volume"]} for p in prices_sorted]
            inds = compute_indicators(price_dicts, stock_id="2330")

            with db.connect() as conn:
                populate_db(conn, prices=prices, inst_rows=inst, indicators=inds, index_rows=idx_data)

            # Build features for dates using data already in DB
            from tw_quant_signal.backtest import _compute_features_as_of
            features = []
            for p in prices_sorted[-80:]:
                row = _compute_features_as_of(db, "2330", p["trade_date"])
                if row:
                    features.append(row)
            if features:
                with db.connect() as conn:
                    for f in features:
                        conn.execute("DELETE FROM features WHERE trade_date=? AND stock_id=?",
                                     [f["trade_date"], f["stock_id"]])
                        conn.execute(
                            "INSERT INTO features (trade_date, stock_id, data) VALUES (?, ?, ?)",
                            [f["trade_date"], f["stock_id"],
                             __import__("json").dumps(f, ensure_ascii=False)],
                        )

            cost = CostModel()
            results = run_backtest(db, stocks=["2330"], start="2026-01-01",
                                   forward_days=5, cost_model=cost)

            assert isinstance(results, list)
            assert len(results) == 30  # 30 rules
            for r in results:
                assert "rule_id" in r
                assert "rule_name" in r
                assert "type" in r
                assert "triggers" in r
                assert "signals_with_return" in r
                assert "win_rate" in r
                assert "avg_return" in r
                assert "profit_ratio" in r
                assert "max_drawdown" in r
                assert "by_state" in r
                assert "state_win_rate" in r
                for state in ["bull", "bear", "range"]:
                    assert state in r["state_win_rate"]
                    assert state in r["by_state"]
                assert 0 <= r["win_rate"] <= 1

        finally:
            if os.path.exists(db._path):
                os.unlink(db._path)
