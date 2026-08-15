"""T019 — 績效追蹤模組。

目標：
- 計算每個規則觸發後的 1/3/5/10 日淨報酬（扣除交易成本）。
- 統計每條規則的勝率、盈虧比、最大回撤、連續虧損次數。
- 區分市場狀態（多頭/空頭/盤整）以利分析。

設計重點：
- 增量計算：僅處理尚未在 performance_log 中的 (stock_id, rule_id, trigger_date)。
- 不回補歷史（依任務書備註），所以起算日 = 模組部署後的 rule_signals。
- 使用 backtest.CostModel 計算淨報酬，並以「買進價 = 隔日開盤，賣出價 = N 日後收盤」之
  簡化模型以避免 look-ahead bias（trigger 日收盤價僅用於記錄，不作為買進價）。
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from tw_quant_signal.backtest import CostModel
from tw_quant_signal.db import SignalDB


# --- 內部資料結構 ---

@dataclass
class ForwardReturn:
    """單一觸發事件於特定持有期下的淨報酬。"""
    trigger_date: str
    stock_id: str
    rule_id: str
    market_state: str | None
    close_at_trigger: float | None
    after_1d_return: float | None
    after_3d_return: float | None
    after_5d_return: float | None
    after_10d_return: float | None
    inspection_date: str | None  # 此筆資料最近一次檢查/更新的日期


_HORIZONS = (1, 3, 5, 10)


# --- DB 讀寫輔助 ---

def _fetch_rule_signals(db: SignalDB, since: str | None = None) -> list[dict]:
    """讀取 rule_signals 並展平為每個觸發一筆 (stock, rule, trigger_date)。"""
    with db.connect() as conn:
        if since:
            rows = conn.execute(
                "SELECT trade_date, stock_id, triggered_rules, signal "
                "FROM rule_signals WHERE trade_date>=? "
                "ORDER BY trade_date ASC, stock_id",
                [since],
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT trade_date, stock_id, triggered_rules, signal "
                "FROM rule_signals ORDER BY trade_date ASC, stock_id"
            ).fetchall()

    triggers: list[dict] = []
    for trade_date, stock_id, raw, signal in rows:
        if not raw:
            continue
        try:
            rs = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if not rs:
            continue
        for r in rs:
            rid = r.get("rule_id")
            if not rid:
                continue
            triggers.append({
                "trigger_date": trade_date,
                "stock_id": stock_id,
                "rule_id": rid,
                "market_state": signal,  # 暫存 signal 標記，作為日後接市況注入的 placeholder
            })
    return triggers


def _fetch_close_at(db: SignalDB, stock_id: str, trade_date: str) -> float | None:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT close FROM daily_prices WHERE stock_id=? AND trade_date=?",
            [stock_id, trade_date],
        ).fetchone()
    return row[0] if row and row[0] else None


def _forward_close(db: SignalDB, stock_id: str, from_date: str, days: int) -> tuple[float | None, str | None]:
    """取得 from_date 之後第 days 個交易日的 (close, trade_date)。

    為避免 look-ahead：買進價採取 D+1 的收盤，持有 N 日後以 D+1+N 收盤作為賣出。
    """
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT trade_date, close FROM daily_prices "
            "WHERE stock_id=? AND trade_date>? "
            "ORDER BY trade_date ASC LIMIT ?",
            [stock_id, from_date, days * 2 + 5],
        ).fetchall()
    if len(rows) < days:
        return None, None
    return rows[days - 1][1], rows[days - 1][0]


def _market_state_lookup(db: SignalDB, trigger_date: str) -> str | None:
    """由 pipeline_log 取出 trigger_date 的市場狀態。"""
    with db.connect() as conn:
        row = conn.execute(
            "SELECT message FROM pipeline_log WHERE run_date=? AND task='market_state' "
            "ORDER BY id DESC LIMIT 1",
            [trigger_date],
        ).fetchone()
    if not row:
        return None
    parts = dict(p.split("=", 1) for p in row[0].split(",") if "=" in p)
    return parts.get("state")


# --- 計算 ---

def compute_performance_log(
    db: SignalDB,
    trade_date: str | None = None,
    cost_model: CostModel | None = None,
    rewrite: bool = False,
) -> list[dict]:
    """為每個 rule_signals 觸發產生 1/3/5/10 日淨報酬記錄。

    Parameters
    ----------
    db : SignalDB
    trade_date : str | None
        限定計算當日新增的觸發；若 None 則處理全部 trade_date 之前的紀錄。
        注意：持有期資料（1/3/5/10 日）需等到未來收盤日才會完整，所以此函式會
        對每筆觸發重新計算並覆寫 — 這樣當未來收盤出現時可立即補上 N 日數值，
        且不會重複插入。
    cost_model : CostModel | None
    rewrite : bool
        True 時將重新處理所有 trigger（即使已存在於 performance_log）；
        預設 False 為增量模式。

    Returns
    -------
    list[dict]
        寫入的 performance_log 列。

    Notes
    -----
    - 「買進」採 D+1 收盤、「賣出」採 D+1+N 收盤（避免 trigger 日洩漏）。
    - 淨報酬 = (sell - buy) / buy - 來回成本（使用 cost_model.net_return）。
    """
    cost_model = cost_model or CostModel()
    trade_date = trade_date or date.today().isoformat()

    triggers = _fetch_rule_signals(db, since=None)
    if trade_date:
        triggers = [t for t in triggers if t["trigger_date"] <= trade_date]

    if not rewrite:
        existing = db.get_performance_logs_distinct_triggers()
    else:
        existing = set()

    # 為加速，先取一次市場狀態（只有 trigger_date 在 pipeline_log 內才能查到）
    out_rows: list[dict] = []
    for trig in triggers:
        sid = trig["stock_id"]
        rid = trig["rule_id"]
        tdate = trig["trigger_date"]
        if not rewrite and (sid, rid, tdate) in existing:
            continue

        close_t = _fetch_close_at(db, sid, tdate)
        row: dict[str, Any] = {
            "stock_id": sid, "rule_id": rid, "trigger_date": tdate,
            "market_state": _market_state_lookup(db, tdate),
            "close_at_trigger": close_t,
            "after_1d_return": None, "after_3d_return": None,
            "after_5d_return": None, "after_10d_return": None,
            "inspection_date": date.today().isoformat(),
        }

        # 計算未來持有期
        for n in _HORIZONS:
            buy_price, _buy_date = _forward_close(db, sid, tdate, 1)
            sell_price, sell_date = _forward_close(db, sid, tdate, n)
            if not buy_price or not sell_price:
                continue
            gross = (sell_price - buy_price) / buy_price
            row[f"after_{n}d_return"] = round(cost_model.net_return(gross), 6)

        out_rows.append(row)

    if out_rows:
        db.upsert_performance_logs(out_rows)
    return out_rows


# --- 聚合統計 ---

def _aggregate(returns: list[float]) -> dict[str, float]:
    """對一組淨報酬序列計算 KPI。"""
    if not returns:
        return {
            "triggers": 0, "wins": 0, "losses": 0, "win_rate": 0.0,
            "avg_return": 0.0, "avg_win": 0.0, "avg_loss": 0.0,
            "profit_ratio": 0.0, "max_dd": 0.0,
            "max_consecutive_losses": 0, "expectancy": 0.0,
        }

    triggers = len(returns)
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r < 0]
    wins_n = len(wins)
    losses_n = len(losses)
    win_rate = round(wins_n / triggers, 4)
    avg_return = round(sum(returns) / triggers, 4)
    avg_win = round(sum(wins) / wins_n, 4) if wins_n else 0.0
    avg_loss = round(sum(losses) / losses_n, 4) if losses_n else 0.0
    profit_ratio = round(abs(avg_win / avg_loss), 4) if avg_loss else 0.0

    # 最大回撤（累積報酬曲線）
    cum = 0.0
    peak = 0.0
    max_dd = 0.0
    for r in returns:
        cum += r
        if cum > peak:
            peak = cum
        dd = peak - cum
        if dd > max_dd:
            max_dd = dd
    max_dd = round(max_dd, 4)

    # 最長連續虧損
    max_cons = 0
    cur = 0
    for r in returns:
        if r < 0:
            cur += 1
            if cur > max_cons:
                max_cons = cur
        else:
            cur = 0

    # 期望值（per trigger）
    expectancy = round(win_rate * avg_win - (1 - win_rate) * abs(avg_loss), 4) if triggers else 0.0

    return {
        "triggers": triggers,
        "wins": wins_n,
        "losses": losses_n,
        "win_rate": win_rate,
        "avg_return": avg_return,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_ratio": profit_ratio,
        "max_dd": max_dd,
        "max_consecutive_losses": max_cons,
        "expectancy": expectancy,
    }


def _classify_relative(value: float) -> str:
    if value <= 0:
        return "zero"
    if value >= 0.01:
        return "strong_up"
    return "up"


def compute_agg_stats(
    db: SignalDB,
    from_date: str | None = None,
    to_date: str | None = None,
    horizon: int = 5,
) -> dict[str, Any]:
    """聚合 performance_log 為規則 KPI 與市場狀態分組統計。

    Parameters
    ----------
    db : SignalDB
    from_date, to_date : str | None
        過濾 performance_log.trigger_date 區間。
    horizon : int
        以哪個持有期報酬作為 KPI 計算依據。預設 5（依任務書「5 日表現」）。

    Returns
    -------
    dict with:
        - horizon: 使用的持有期
        - from_date / to_date: 實際使用的區間
        - rules: { rule_id: { name, type, stats, by_state } }
        - overview: 整體 KPI 與 by_state
        - markdown_table: 規則總表（Markdown）
    """
    if horizon not in _HORIZONS:
        horizon = 5

    ret_col = f"after_{horizon}d_return"
    logs = db.get_performance_logs(from_date=from_date, to_date=to_date)

    # 群組：rule_id -> list[(date, market_state, return)]
    by_rule: dict[tuple[str, str], list[dict]] = defaultdict(list)
    by_state: dict[str | None, list[float]] = defaultdict(list)
    all_returns: list[float] = []

    # 用來補規則名稱/類型：讀 rules YAML
    rule_meta = _load_rules_meta()

    for log in logs:
        rv = log.get(ret_col)
        if rv is None:
            continue
        all_returns.append(rv)
        by_state[log.get("market_state")].append(rv)
        by_rule[(log["rule_id"], log["stock_id"])].append({
            "trigger_date": log["trigger_date"],
            "stock_id": log["stock_id"],
            "return": rv,
            "market_state": log.get("market_state"),
        })

    rules_out: dict[str, dict] = {}
    for (rid, _sid), seq in by_rule.items():
        returns = [s["return"] for s in seq]
        agg = _aggregate(returns)
        meta = rule_meta.get(rid, {"name": rid, "type": "unknown"})
        rules_out[rid] = {
            "name": meta["name"],
            "type": meta["type"],
            "stats": agg,
            "by_state": {
                state or "unknown": _aggregate([s["return"] for s in seq if s["market_state"] == state])
                for state in sorted({s["market_state"] for s in seq})
            },
        }

    overview = _aggregate(all_returns)
    by_state_out = {
        state or "unknown": _aggregate(returns)
        for state, returns in sorted(by_state.items(), key=lambda x: (x[0] is None, x[0]))
    }
    overview["by_state"] = by_state_out

    md = _render_markdown(rules_out, overview, horizon)

    return {
        "horizon": horizon,
        "from_date": from_date,
        "to_date": to_date,
        "rules": rules_out,
        "overview": overview,
        "markdown_table": md,
    }


def _load_rules_meta() -> dict[str, dict]:
    """從 configs/*.yaml 讀取規則名稱與類型。"""
    from pathlib import Path
    import yaml
    config_dir = Path(__file__).parent.parent.parent / "configs"
    meta: dict[str, dict] = {}
    for fname in ("rules_bullish.yaml", "rules_bearish.yaml", "rules_neutral.yaml"):
        path = config_dir / fname
        if not path.exists():
            continue
        with open(path) as f:
            data = yaml.safe_load(f)
        for r in (data or {}).get("rules", []):
            rid = r.get("id")
            if rid:
                meta[rid] = {"name": r.get("name", rid), "type": r.get("type", "neutral")}
    return meta


def _render_markdown(rules_out: dict, overview: dict, horizon: int) -> str:
    """產生規則 KPI Markdown 表格。"""
    lines = [f"## 規則績效總覽（持有期 {horizon} 日）", ""]
    lines.append("| 規則 ID | 名稱 | 類型 | 觸發 | 勝率 | 平均淨報酬 | 盈虧比 | 最大 DD | 最長連虧 |")
    lines.append("| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for rid, info in sorted(rules_out.items()):
        s = info["stats"]
        lines.append(
            f"| {rid} | {info['name']} | {info['type']} | {s['triggers']} | "
            f"{s['win_rate']*100:.1f}% | {s['avg_return']*100:+.2f}% | "
            f"{s['profit_ratio']:.2f} | {s['max_dd']*100:.2f}% | {s['max_consecutive_losses']} |"
        )
    lines.append("")
    lines.append(f"### 整體：觸發 {overview['triggers']}、勝率 {overview['win_rate']*100:.1f}%、"
                 f"平均報酬 {overview['avg_return']*100:+.2f}%、最大 DD {overview['max_dd']*100:.2f}%、"
                 f"最長連虧 {overview['max_consecutive_losses']}")
    return "\n".join(lines)


# --- 報表輔助（供 alerter / reporter 使用） ---

def recent_performance_summary(db: SignalDB, horizon: int = 5, days: int = 30) -> dict | None:
    """供 pipeline/daily report 使用的最近 N 日績效摘要。"""
    from datetime import date
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    stats = compute_agg_stats(db, from_date=cutoff, horizon=horizon)
    if stats["overview"]["triggers"] == 0:
        return None
    return stats
