import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from tw_quant_signal.db import SignalDB
from tw_quant_signal.twse_client import WATCH_STOCKS
from tw_quant_signal.indicators import compute_indicators
from tw_quant_signal.rules import _load_rules, evaluate_rule


DEFAULT_COST = {
    "tax_sell": 0.003,
    "tax_daytrade": 0.0015,
    "commission": 0.001425,
    "commission_discount": 0.6,
}


def _load_rules_all() -> list[dict]:
    return _load_rules()


def _dates_in_range(db: SignalDB, start: str, end: str) -> list[str]:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT trade_date FROM daily_prices WHERE stock_id=? AND trade_date BETWEEN ? AND ? ORDER BY trade_date",
            [WATCH_STOCKS[0], start, end],
        ).fetchall()
    return [r[0] for r in rows]


def _compute_features_as_of(db: SignalDB, stock_id: str, as_of: str, lag_days: int = 365) -> dict:
    """Compute a feature dict using only data available on or before as_of."""
    with db.connect() as conn:
        prices = conn.execute(
            "SELECT trade_date, close, volume FROM daily_prices WHERE stock_id=? AND trade_date<=? ORDER BY trade_date DESC LIMIT ?",
            [stock_id, as_of, lag_days],
        ).fetchall()

        inst = conn.execute(
            "SELECT foreign_investors_net, sity_investors_net FROM institutional_flows "
            "WHERE stock_id=? AND trade_date<=? ORDER BY trade_date DESC LIMIT 5",
            [stock_id, as_of],
        ).fetchall()

    if len(prices) < 60:
        return {}

    price_dicts = [{"trade_date": r[0], "close": r[1], "volume": r[2] or 0} for r in reversed(prices)]
    ind_rows = compute_indicators(price_dicts, stock_id=stock_id)
    if not ind_rows:
        return {}

    latest = prices[0]
    close = latest[1]
    volume = latest[2] or 0

    latest_ind = ind_rows[-1]
    ma5 = latest_ind["ma5"]
    ma20 = latest_ind["ma20"]
    ma60 = latest_ind["ma60"]
    rsi14 = latest_ind["rsi14"]
    bb_u = latest_ind["bb_upper"]
    bb_m = latest_ind["bb_middle"]
    bb_l = latest_ind["bb_lower"]
    vol_ma5 = latest_ind["volume_ma5"]

    vol_ratio = round(volume / vol_ma5, 2) if vol_ma5 > 0 else None

    def _sig_ma(m5, m20, m60):
        if m5 is None or m20 is None or m60 is None:
            return "unknown"
        if m5 > m20 > m60:
            return "bullish"
        if m5 < m20 < m60:
            return "bearish"
        return "neutral"

    def _sig_rsi(v):
        if v is None:
            return "unknown"
        if v >= 70:
            return "overbought"
        if v <= 30:
            return "oversold"
        if 50 <= v < 70:
            return "bullish"
        return "bearish"

    def _sig_bb(c, u, l, m):
        if c is None or u is None or l is None:
            return "unknown"
        if c >= u:
            return "above_upper"
        if c <= l:
            return "below_lower"
        if c >= m:
            return "above_mid"
        return "below_mid"

    def _rel_pos(c, ma):
        if c is None or ma is None:
            return None
        if c > ma * 1.01:
            return "above"
        if c < ma * 0.99:
            return "below"
        return "at"

    inst_5d_sum = sum(r[0] or 0 for r in inst[:5]) if inst else None
    sity_5d_sum = sum(r[1] or 0 for r in inst[:5]) if inst else None

    def _trend_dir(net):
        if net is None:
            return None
        if net > 1_000_000:
            return "strong_buy"
        if net > 200_000:
            return "buy"
        if net < -1_000_000:
            return "strong_sell"
        if net < -200_000:
            return "sell"
        return "neutral"

    def _inst_signal(total):
        if total is None:
            return "unknown"
        a = abs(total)
        if a > 5_000_000:
            return "strong"
        if a > 1_000_000:
            return "moderate"
        return "weak"

    inst_3d_sum = sum(r[0] or 0 for r in inst[:3]) if inst else None

    with db.connect() as conn:
        feat_row = conn.execute(
            "SELECT data FROM features WHERE stock_id=? AND trade_date=?",
            [stock_id, as_of],
        ).fetchone()
    val = json.loads(feat_row[0]) if feat_row else {}

    row = {
        "stock_id": stock_id,
        "trade_date": as_of,
        "close": close,
        "ma5": ma5,
        "ma20": ma20,
        "ma60": ma60,
        "ma_alignment": _sig_ma(ma5, ma20, ma60),
        "rsi14": rsi14,
        "rsi_signal": _sig_rsi(rsi14),
        "bb_position": _sig_bb(close, bb_u, bb_l, bb_m),
        "volume_ratio": vol_ratio,
        "close_vs_ma20": _rel_pos(close, ma20),
        "close_vs_ma60": _rel_pos(close, ma60),
        "foreign_net_1d": inst[0][0] if inst else None,
        "sity_net_1d": inst[0][1] if inst else None,
        "foreign_net_3d_sum": inst_3d_sum,
        "foreign_net_5d_sum": inst_5d_sum,
        "foreign_5d_trend": _trend_dir(inst_5d_sum),
        "sity_5d_trend": _trend_dir(sity_5d_sum),
        "foreign_3d_signal": _inst_signal(inst_3d_sum),
        "foreign_5d_signal": _inst_signal(inst_5d_sum),
        "pe_ratio": val.get("pe_ratio"),
        "pb_ratio": val.get("pb_ratio"),
        "dividend_yield": val.get("dividend_yield"),
        "pe_signal": "high" if val.get("pe_ratio") and val["pe_ratio"] > 25 else ("low" if val.get("pe_ratio") and val["pe_ratio"] < 15 else "fair") if val.get("pe_ratio") else None,
        "pb_signal": "high" if val.get("pb_ratio") and val["pb_ratio"] > 3 else ("low" if val.get("pb_ratio") and val["pb_ratio"] < 1.5 else "fair") if val.get("pb_ratio") else None,
        "dy_signal": "high" if val.get("dividend_yield") and val["dividend_yield"] > 0.05 else ("fair" if val.get("dividend_yield") and val["dividend_yield"] > 0.02 else "low") if val.get("dividend_yield") is not None else None,
        "dealer_net_1d": None,
        "beta_5d": None,
        "ma_position_pct": 0,
        "volume_ma5": vol_ma5,
        "pe_percentile": val.get("pe_percentile"),
        "pb_percentile": val.get("pb_percentile"),
        "pe_river": val.get("pe_river", "mid"),
        "pb_river": val.get("pb_river", "mid"),
    }
    return row


def _get_index_features_as_of(db: SignalDB, as_of: str) -> dict:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT trade_date, close FROM market_index WHERE trade_date<=? ORDER BY trade_date ASC",
            [as_of],
        ).fetchall()
    if len(rows) < 60:
        return {}
    closes = [r[1] for r in rows if r[1] is not None]
    if len(closes) < 60:
        return {}
    s = pd.Series(closes)
    ma20 = float(s.rolling(20).mean().iloc[-1])
    ma60 = float(s.rolling(60).mean().iloc[-1])
    close = closes[-1]

    def _pos(c, ma):
        if c > ma * 1.01:
            return "above"
        if c < ma * 0.99:
            return "below"
        return "at"

    return {
        "index_vs_ma20": _pos(close, ma20),
        "index_vs_ma60": _pos(close, ma60),
        "close": close,
    }


def _get_breadth_as_of(db: SignalDB, as_of: str) -> dict:
    with db.connect() as conn:
        insts = conn.execute(
            "SELECT stock_id, foreign_investors_net FROM institutional_flows WHERE trade_date=?", [as_of]
        ).fetchall()
    total = len(insts)
    pos = sum(1 for r in insts if r[1] and r[1] > 0)
    ratio = round(pos / total, 4) if total else None
    return {
        "market_breadth": "broad" if ratio and ratio > 0.5 else ("narrow" if ratio else None),
        "total_stocks": total,
        "foreign_buy_count": pos,
        "foreign_buy_ratio": ratio,
    }


def _forward_return(db: SignalDB, stock_id: str, from_date: str, days: int) -> float | None:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT close FROM daily_prices WHERE stock_id=? AND trade_date>? ORDER BY trade_date LIMIT ?",
            [stock_id, from_date, max(days * 2, 20)],
        ).fetchall()
    target_idx = days - 1
    if len(rows) > target_idx:
        buy_price = rows[0][0]
        sell_price = rows[target_idx][0]
        if buy_price and sell_price:
            return (sell_price - buy_price) / buy_price
    return None


def _market_state(index_feat: dict) -> str:
    v20 = index_feat.get("index_vs_ma20")
    v60 = index_feat.get("index_vs_ma60")
    if v20 == "above" and v60 == "above":
        return "bull"
    if v20 == "below" and v60 == "below":
        return "bear"
    return "range"


class CostModel:
    def __init__(self, tax_sell=0.003, tax_daytrade=0.0015, commission=0.001425, discount=0.6):
        self.tax_sell = tax_sell
        self.tax_daytrade = tax_daytrade
        self.commission = commission * discount

    def round_trip_cost(self, is_daytrade: bool = False) -> float:
        buy_cost = self.commission
        sell_cost = self.commission + (self.tax_daytrade if is_daytrade else self.tax_sell)
        return buy_cost + sell_cost

    def net_return(self, gross_return: float, is_daytrade: bool = False) -> float:
        return gross_return - self.round_trip_cost(is_daytrade)


def run_backtest(
    db: SignalDB,
    stocks: list[str] = None,
    start: str = "2022-01-01",
    end: str | None = None,
    forward_days: int = 5,
    cost_model: CostModel = None,
) -> list[dict]:
    stocks = stocks or WATCH_STOCKS
    end = end or date.today().isoformat()
    cost_model = cost_model or CostModel()

    rules = _load_rules_all()
    dates = _dates_in_range(db, start, end)
    rule_ids = [r["id"] for r in rules]

    stats = {rid: {"id": rid, "name": r["name"], "type": r["type"], "triggers": 0, "wins": 0, "losses": 0, "returns": [], "drawdowns": [], "by_state": {"bull": 0, "bear": 0, "range": 0}, "states_triggered": []} for rid, r in zip(rule_ids, rules)}
    tested_count = 0

    print(f"Backtest: {len(dates)} days, {len(rules)} rules, {forward_days}d forward")

    for idx, td in enumerate(dates):
        if (idx + 1) % 200 == 0:
            print(f"  {idx+1}/{len(dates)} ({td})")

        index_feat = _get_index_features_as_of(db, td)
        if not index_feat:
            continue
        breadth_feat = _get_breadth_as_of(db, td)
        mstate = _market_state(index_feat)

        for sid in stocks:
            stock_feat = _compute_features_as_of(db, sid, td)
            if not stock_feat:
                continue

            all_stock_feats = {sid: stock_feat}
            
            # Get nearest available features for other stocks (for stock_2330_* references)
            for other in stocks:
                if other != sid:
                    with db.connect() as conn:
                        other_row = conn.execute(
                            "SELECT data FROM features WHERE stock_id=? AND trade_date<=? ORDER BY trade_date DESC LIMIT 1",
                            [other, td],
                        ).fetchone()
                    if other_row:
                        all_stock_feats[other] = json.loads(other_row[0])

            for rule in rules:
                try:
                    matched = evaluate_rule(rule, stock_feat, all_stock_feats, index_feat, breadth_feat)
                except Exception:
                    matched = False

                if matched:
                    tested_count += 1
                    s = stats[rule["id"]]
                    s["triggers"] += 1
                    s["by_state"][mstate] += 1

                    fwd_ret = _forward_return(db, sid, td, forward_days)
                    if fwd_ret is not None:
                        net = cost_model.net_return(fwd_ret)
                        s["returns"].append(net)
                        if net > 0:
                            s["wins"] += 1
                        else:
                            s["losses"] += 1
                        s["states_triggered"].append(mstate)

    return _compute_stats(stats, rules, tested_count)


def _compute_stats(stats: dict, rules: list[dict], total_tested: int) -> list[dict]:
    results = []
    for rule in rules:
        s = stats[rule["id"]]
        returns = s["returns"]
        total = len(returns)
        win_rate = round(s["wins"] / total, 4) if total else 0
        avg_ret = round(sum(returns) / total, 4) if total else 0

        cum = 0
        peak = 0
        max_dd = 0
        for r in returns:
            cum += r
            peak = max(peak, cum)
            dd = peak - cum
            max_dd = max(max_dd, dd)
        max_dd = round(max_dd, 4)

        wins = [r for r in returns if r > 0]
        losses = [r for r in returns if r < 0]
        avg_win = round(sum(wins) / len(wins), 4) if wins else 0
        avg_loss = round(sum(losses) / len(losses), 4) if losses else 0
        profit_ratio = round(abs(avg_win / avg_loss), 4) if avg_loss else 0

        cons_loss = 0
        max_cons_loss = 0
        for r in returns:
            if r < 0:
                cons_loss += 1
                max_cons_loss = max(max_cons_loss, cons_loss)
            else:
                cons_loss = 0

        results.append({
            "rule_id": rule["id"],
            "rule_name": rule["name"],
            "type": rule["type"],
            "triggers": s["triggers"],
            "signals_with_return": total,
            "win_rate": win_rate,
            "avg_return": avg_ret,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "profit_ratio": profit_ratio,
            "max_drawdown": max_dd,
            "max_consecutive_losses": max_cons_loss,
            "by_state": s["by_state"],
            "total_rules_tested": total_tested,
        })
    return results


def print_report(results: list[dict]):
    print("=" * 90)
    print(f"{'ID':<6} {'Type':<8} {'Triggers':<9} {'WinRate':<8} {'AvgRet':<8} {'ProfitR':<8} {'MaxDD':<8} {'MaxConsLoss':<11} Name")
    print("-" * 90)
    for r in sorted(results, key=lambda x: x["triggers"], reverse=True):
        rid = r["rule_id"]
        t = r["type"]
        trig = r["triggers"]
        wr = f"{r['win_rate']:.1%}" if r["signals_with_return"] else "-"
        ar = f"{r['avg_return']:.2%}" if r["avg_return"] else "-"
        pr = f"{r['profit_ratio']:.2f}" if r["profit_ratio"] else "-"
        dd = f"{r['max_drawdown']:.2%}" if r["max_drawdown"] else "-"
        cl = str(r["max_consecutive_losses"]) if r["max_consecutive_losses"] else "-"
        name = r["rule_name"][:45]
        print(f"{rid:<6} {t:<8} {trig:<9} {wr:<8} {ar:<8} {pr:<8} {dd:<8} {cl:<11} {name}")

    print("=" * 90)
    print(f"Total rules tested (including repeats): {results[0]['total_rules_tested'] if results else 0}")

    # by state summary
    tv = sum(r["triggers"] for r in results)
    print(f"\n三種市場狀態分布:")
    for state in ["bull", "bear", "range"]:
        cnt = sum(r["by_state"].get(state, 0) for r in results)
        pct = cnt / tv if tv else 0
        state_label = {"bull": "多頭", "bear": "空頭", "range": "盤整"}[state]
        print(f"  {state_label}: {cnt} 次 ({pct:.1%})")


def main():
    db = SignalDB()
    db.init_db()

    cost = CostModel(tax_sell=0.003, commission=0.001425, discount=0.6)

    # Full period
    print("\n" + "█" * 60)
    print("█  完整期間回測 (2022-2026)")
    print("█" * 60)
    results = run_backtest(db, forward_days=5, cost_model=cost, start="2022-01-01")
    print_report(results)

    # In-sample: 2022-2024
    print("\n" + "█" * 60)
    print("█  樣本內 (In-Sample / 規則設計期): 2022-2024")
    print("█" * 60)
    is_results = run_backtest(db, forward_days=5, cost_model=cost, start="2022-01-01", end="2024-12-31")
    print_report(is_results)

    # Out-of-sample: 2025-2026
    print("\n" + "█" * 60)
    print("█  樣本外 (Out-of-Sample / 驗證期): 2025-2026")
    print("█" * 60)
    oos_results = run_backtest(db, forward_days=5, cost_model=cost, start="2025-01-01")
    print_report(oos_results)


if __name__ == "__main__":
    sys.exit(main())
