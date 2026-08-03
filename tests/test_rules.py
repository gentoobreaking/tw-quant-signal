"""T017 — Unit tests for rules engine (rules.py)."""

import sqlite3

from tw_quant_signal.rules import (
    _eval_condition,
    _eval_conditions,
    _to_num,
    _load_rules,
    _all_condition_features,
    evaluate_rule,
    _aggregate_rules,
    STATE_WEIGHTS,
)


class TestEvalCondition:
    def test_eq(self):
        assert _eval_condition({"feature": "x", "operator": "eq", "value": "abc"}, {"x": "abc"}) is True
        assert _eval_condition({"feature": "x", "operator": "eq", "value": "abc"}, {"x": "xyz"}) is False

    def test_neq(self):
        assert _eval_condition({"feature": "x", "operator": "neq", "value": "abc"}, {"x": "xyz"}) is True
        assert _eval_condition({"feature": "x", "operator": "neq", "value": "abc"}, {"x": "abc"}) is False

    def test_gt(self):
        assert _eval_condition({"feature": "v", "operator": "gt", "value": 1.0}, {"v": 2.0}) is True
        assert _eval_condition({"feature": "v", "operator": "gt", "value": 2.0}, {"v": 1.0}) is False

    def test_gte(self):
        assert _eval_condition({"feature": "v", "operator": "gte", "value": 2.0}, {"v": 2.0}) is True
        assert _eval_condition({"feature": "v", "operator": "gte", "value": 2.0}, {"v": 1.9}) is False

    def test_lt(self):
        assert _eval_condition({"feature": "v", "operator": "lt", "value": 2.0}, {"v": 1.0}) is True
        assert _eval_condition({"feature": "v", "operator": "lt", "value": 1.0}, {"v": 2.0}) is False

    def test_lte(self):
        assert _eval_condition({"feature": "v", "operator": "lte", "value": 2.0}, {"v": 2.0}) is True
        assert _eval_condition({"feature": "v", "operator": "lte", "value": 2.0}, {"v": 2.1}) is False

    def test_in(self):
        assert _eval_condition({"feature": "x", "operator": "in", "value": ["a", "b"]}, {"x": "a"}) is True
        assert _eval_condition({"feature": "x", "operator": "in", "value": ["a", "b"]}, {"x": "c"}) is False

    def test_not_in(self):
        assert _eval_condition({"feature": "x", "operator": "not_in", "value": ["a", "b"]}, {"x": "c"}) is True
        assert _eval_condition({"feature": "x", "operator": "not_in", "value": ["a", "b"]}, {"x": "a"}) is False

    def test_missing_feature_returns_false(self):
        assert _eval_condition({"feature": "nonexistent", "operator": "eq", "value": 1}, {"x": 1}) is False

    def test_unknown_operator_returns_false(self):
        assert _eval_condition({"feature": "x", "operator": "bogus", "value": 1}, {"x": 1}) is False


class TestToNum:
    def test_int(self):
        assert _to_num(42) == 42.0

    def test_float(self):
        assert _to_num(3.14) == 3.14

    def test_string_number(self):
        assert _to_num("5.5") == 5.5

    def test_invalid_returns_zero(self):
        assert _to_num("abc") == 0.0
        assert _to_num(None) == 0.0


class TestEvalConditions:
    def test_all_true(self):
        conds = {"all": [
            {"feature": "a", "operator": "eq", "value": 1},
            {"feature": "b", "operator": "eq", "value": 2},
        ]}
        assert _eval_conditions(conds, {"a": 1, "b": 2}) is True

    def test_all_false(self):
        conds = {"all": [
            {"feature": "a", "operator": "eq", "value": 1},
            {"feature": "b", "operator": "eq", "value": 99},
        ]}
        assert _eval_conditions(conds, {"a": 1, "b": 2}) is False

    def test_any_true(self):
        conds = {"any": [
            {"feature": "a", "operator": "eq", "value": 1},
            {"feature": "b", "operator": "eq", "value": 99},
        ]}
        assert _eval_conditions(conds, {"a": 1, "b": 2}) is True

    def test_any_false(self):
        conds = {"any": [
            {"feature": "a", "operator": "eq", "value": 99},
            {"feature": "b", "operator": "eq", "value": 99},
        ]}
        assert _eval_conditions(conds, {"a": 1, "b": 2}) is False

    def test_empty_conditions(self):
        assert _eval_conditions({}, {"a": 1}) is False


class TestAllConditionFeatures:
    def test_extracts_features(self):
        conds = {
            "all": [
                {"feature": "a"},
                {"feature": "b"},
            ],
            "any": [
                {"feature": "c"},
            ],
        }
        result = _all_condition_features(conds)
        assert result == {"a", "b", "c"}


class TestEvaluateRule:
    def test_scope_stock_single_rule(self):
        rule = {
            "id": "U001",
            "name": "Test",
            "type": "bullish",
            "scope": "stock",
            "conditions": {"all": [
                {"feature": "close_vs_ma20", "operator": "eq", "value": "above"},
            ]},
        }
        stock_feat = {"close_vs_ma20": "above"}
        all_feats = {"2330": stock_feat}
        idx_feat = {}
        breadth = {}
        assert evaluate_rule(rule, stock_feat, all_feats, idx_feat, breadth) is True

    def test_scope_stock_fails(self):
        rule = {
            "id": "U001",
            "name": "Test",
            "type": "bullish",
            "scope": "stock",
            "conditions": {"all": [
                {"feature": "close_vs_ma20", "operator": "eq", "value": "below"},
            ]},
        }
        stock_feat = {"close_vs_ma20": "above"}
        idx_feat = {}
        breadth_feat = {}
        assert evaluate_rule(rule, stock_feat, {}, idx_feat, breadth_feat) is False

    def test_stock_scope_injects_index_breadth(self):
        rule = {
            "id": "S001",
            "name": "Test Index",
            "type": "bullish",
            "scope": "stock",
            "conditions": {"all": [
                {"feature": "index_vs_ma20", "operator": "eq", "value": "above"},
                {"feature": "market_breadth", "operator": "eq", "value": "broad"},
            ]},
        }
        stock_feat = {"close": 500}
        idx_feat = {"index_vs_ma20": "above", "index_vs_ma60": "above"}
        breadth_feat = {"breadth_signal": "broad"}
        assert evaluate_rule(rule, stock_feat, {}, idx_feat, breadth_feat) is True

    def test_scope_market(self):
        rule = {
            "id": "M001",
            "name": "Test Market",
            "type": "bullish",
            "scope": "market",
            "conditions": {"all": [
                {"feature": "index_vs_ma20", "operator": "eq", "value": "above"},
            ]},
        }
        idx_feat = {"index_vs_ma20": "above"}
        breadth_feat = {}
        assert evaluate_rule(rule, {}, {}, idx_feat, breadth_feat) is True

    def test_stock_cross_reference(self):
        # Feature `stock_<sid>_<feat>` maps to the referenced stock's feature
        # dict under the remaining name (after "stock_<sid>_" prefix).
        rule = {
            "id": "X001",
            "name": "Cross Ref",
            "type": "bullish",
            "scope": "stock",
            "conditions": {"all": [
                {"feature": "stock_2330_vs_ma20", "operator": "eq", "value": "above"},
            ]},
        }
        stock_feat_2330 = {"close_vs_ma20": "above", "vs_ma20": "above"}
        all_feats = {"2330": stock_feat_2330}
        stock_feat_0050 = {"close": 100}
        assert evaluate_rule(rule, stock_feat_0050, all_feats, {}, {}) is True

    def test_stock_cross_reference_absent_stock_returns_false(self):
        rule = {
            "id": "X002",
            "name": "Cross Ref Absent",
            "type": "bullish",
            "scope": "stock",
            "conditions": {"all": [
                {"feature": "stock_9999_vs_ma20", "operator": "eq", "value": "above"},
            ]},
        }
        stock_feat = {"close": 100}
        assert evaluate_rule(rule, stock_feat, {"2330": {"vs_ma20": "above"}}, {}, {}) is False


class TestAggregateRules:
    def test_bullish_only(self):
        triggered = [
            {"rule_id": "U001", "type": "bullish"},
            {"rule_id": "U002", "type": "bullish"},
        ]
        sig, score = _aggregate_rules(triggered, "range")
        assert sig == "bullish"
        assert score == 2

    def test_bearish_only(self):
        triggered = [
            {"rule_id": "B001", "type": "bearish"},
            {"rule_id": "B002", "type": "bearish"},
        ]
        sig, score = _aggregate_rules(triggered, "range")
        assert sig == "bearish"
        assert score == -2

    def test_neutral(self):
        triggered = [
            {"rule_id": "N001", "type": "neutral"},
        ]
        sig, score = _aggregate_rules(triggered, "range")
        assert sig == "neutral"
        assert score == 0

    def test_balanced(self):
        triggered = [
            {"rule_id": "U001", "type": "bullish"},
            {"rule_id": "B001", "type": "bearish"},
        ]
        sig, score = _aggregate_rules(triggered, "range")
        assert sig == "neutral"
        assert score == 0

    def test_bull_market_boosts_bullish(self):
        triggered = [
            {"rule_id": "U001", "type": "bullish"},
            {"rule_id": "U002", "type": "bullish"},
            {"rule_id": "B001", "type": "bearish"},
        ]
        sig, score = _aggregate_rules(triggered, "bull")
        assert sig == "bullish"
        assert score == 2  # 2*1.5 - 1.0 = 2.0

    def test_bear_market_boosts_bearish(self):
        triggered = [
            {"rule_id": "U001", "type": "bullish"},
            {"rule_id": "B001", "type": "bearish"},
            {"rule_id": "B002", "type": "bearish"},
        ]
        sig, score = _aggregate_rules(triggered, "bear")
        assert sig == "bearish"
        assert score == -2  # 1.0 - 2*1.5 = -2.0

    def test_bull_market_balanced_tie_rounds_neutral(self):
        # 1 bullish (1.5) vs 1 bearish (1.0) -> 0.5 -> round(0.5) = 0 (banker's rounding)
        triggered = [
            {"rule_id": "U001", "type": "bullish"},
            {"rule_id": "B001", "type": "bearish"},
        ]
        sig, score = _aggregate_rules(triggered, "bull")
        assert sig == "neutral"
        assert score == 0


class TestLoadRules:
    def test_loads_rules_from_yaml(self):
        rules = _load_rules()
        assert isinstance(rules, list)
        assert len(rules) >= 30  # 10 bullish + 10 bearish + 10 neutral
        for r in rules:
            assert "id" in r
            assert "name" in r
            assert "type" in r
            assert "conditions" in r