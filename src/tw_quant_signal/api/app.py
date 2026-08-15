import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import yaml
from fastapi import FastAPI, HTTPException, Query, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from tw_quant_signal.db import SignalDB
from tw_quant_signal.config import settings
from tw_quant_signal.multi_timeframe import compute_multi_timeframe

app = FastAPI(title="tw-quant-signal API", version="1.0.0", on_startup=[lambda: _get_db().init_db()])

@app.websocket("/ws/alerts")
async def ws_alerts(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            await websocket.receive_text()
    except Exception:
        pass

@app.websocket("/ws/quotes")
async def ws_quotes(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            await websocket.receive_text()
    except Exception:
        pass

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"
CONFIG_PATH = PROJECT_ROOT / "config.json"
RULES_DIR = PROJECT_ROOT / "configs"
STOCK_NAMES = {"2330": "台積電", "0050": "元大台灣50", "2308": "台達電"}


def _get_db():
    return SignalDB()


# ---- Stock endpoints ----

@app.get("/api/stocks")
def list_stocks():
    db = _get_db()
    stocks = []
    for sid in settings.watch_stocks:
        with db.connect() as conn:
            row = conn.execute(
                "SELECT dp.trade_date, dp.close, "
                "(dp.close - prev.close) / prev.close * 100 AS change_pct "
                "FROM daily_prices dp "
                "LEFT JOIN daily_prices prev ON prev.stock_id=dp.stock_id AND prev.trade_date=("
                "  SELECT MAX(trade_date) FROM daily_prices WHERE stock_id=dp.stock_id AND trade_date<dp.trade_date"
                ") WHERE dp.stock_id=? ORDER BY dp.trade_date DESC LIMIT 1",
                [sid],
            ).fetchone()
        h = db.get_health_scores(date.today().isoformat(), sid)
        r = db.get_risk_metrics(date.today().isoformat(), sid)
        hs = h[0] if h else {}
        rs = r[0] if r else {}
        stocks.append({
            "id": sid,
            "name": STOCK_NAMES.get(sid, sid),
            "close": row[1] if row else None,
            "change_pct": row[2] if row else None,
            "health_score": hs.get("total_score"),
            "health_light": hs.get("total_light"),
            "risk_score": rs.get("risk_score"),
            "risk_level": rs.get("risk_level"),
        })
    return {"data": stocks}


@app.get("/api/stocks/{stock_id}/detail")
def stock_detail(stock_id: str):
    db = _get_db()
    today = date.today().isoformat()

    with db.connect() as conn:
        prices = conn.execute(
            "SELECT dp.trade_date, dp.close, dp.high, dp.low, dp.volume, dp.adj_close, "
            "(dp.close - prev.close) / prev.close * 100 AS change_pct "
            "FROM daily_prices dp "
            "LEFT JOIN daily_prices prev ON prev.stock_id=dp.stock_id AND prev.trade_date=("
            "  SELECT MAX(trade_date) FROM daily_prices WHERE stock_id=dp.stock_id AND trade_date<dp.trade_date"
            ") WHERE dp.stock_id=? ORDER BY dp.trade_date DESC LIMIT 120",
            [stock_id],
        ).fetchall()

        ind = conn.execute(
            "SELECT trade_date, ma5, ma20, ma60, bb_upper, bb_middle, bb_lower, rsi14, volume_ma5, volume_ma20 "
            "FROM tech_indicators WHERE stock_id=? ORDER BY trade_date DESC LIMIT 120",
            [stock_id],
        ).fetchall()

        inst = conn.execute(
            "SELECT trade_date, foreign_investors_net, sity_investors_net, dealer_net "
            "FROM institutional_flows WHERE stock_id=? ORDER BY trade_date DESC LIMIT 60",
            [stock_id],
        ).fetchall()

        feat = conn.execute(
            "SELECT data FROM features WHERE stock_id=? AND trade_date=?",
            [stock_id, today],
        ).fetchone()

        fin = conn.execute(
            "SELECT fiscal_quarter, eps, revenue, gross_margin FROM financial_data WHERE stock_id=? ORDER BY fiscal_quarter DESC LIMIT 8",
            [stock_id],
        ).fetchall()

        ind = conn.execute(
            "SELECT trade_date, ma5, ma20, ma60, bb_upper, bb_middle, bb_lower, rsi14, volume_ma5, volume_ma20 "
            "FROM tech_indicators WHERE stock_id=? ORDER BY trade_date DESC LIMIT 120",
            [stock_id],
        ).fetchall()

        inst = conn.execute(
            "SELECT trade_date, foreign_investors_net, sity_investors_net, dealer_net "
            "FROM institutional_flows WHERE stock_id=? ORDER BY trade_date DESC LIMIT 60",
            [stock_id],
        ).fetchall()

        feat = conn.execute(
            "SELECT data FROM features WHERE stock_id=? AND trade_date=?",
            [stock_id, today],
        ).fetchone()

        fin = conn.execute(
            "SELECT fiscal_quarter, eps, revenue, gross_margin FROM financial_data WHERE stock_id=? ORDER BY fiscal_quarter DESC LIMIT 8",
            [stock_id],
        ).fetchall()

    health = db.get_health_scores(today, stock_id)
    weekly_health = db.get_weekly_health_scores(today, stock_id)
    monthly_health = db.get_monthly_health_scores(today, stock_id)
    risk = db.get_risk_metrics(today, stock_id)
    signals = db.get_rule_signals_for_date(today, stock_id)
    ms = _get_market_state(db, today)
    tf_consensus = db.get_multi_timeframe_consensus(today, stock_id)

    return {
        "data": {
            "stock_id": stock_id,
            "name": STOCK_NAMES.get(stock_id, stock_id),
            "prices": [
                {"date": r[0], "close": r[1], "high": r[2], "low": r[3],
                 "volume": r[4], "adj_close": r[5], "change_pct": r[6]}
                for r in prices
            ],
            "indicators": [
                {"date": r[0], "ma5": r[1], "ma20": r[2], "ma60": r[3],
                 "bb_upper": r[4], "bb_middle": r[5], "bb_lower": r[6],
                 "rsi14": r[7], "volume_ma5": r[8], "volume_ma20": r[9]}
                for r in ind
            ],
            "institutional": [
                {"date": r[0], "foreign": r[1], "sity": r[2], "dealer": r[3]}
                for r in inst
            ],
            "features": json.loads(feat[0]) if feat else None,
            "financials": [
                {"quarter": r[0], "eps": r[1], "revenue": r[2], "gross_margin": r[3]}
                for r in fin
            ],
            "health": health[0] if health else None,
            "weekly_health": weekly_health[0] if weekly_health else None,
            "monthly_health": monthly_health[0] if monthly_health else None,
            "risk": risk[0] if risk else None,
            "signals": signals,
            "market_state": ms,
            "multi_timeframe": tf_consensus[0] if tf_consensus else None,
        }
    }


@app.get("/api/market-state")
def market_state():
    db = _get_db()
    return {"data": _get_market_state(db, date.today().isoformat())}


def _get_market_state(db, run_date: str):
    with db.connect() as conn:
        row = conn.execute(
            "SELECT message FROM pipeline_log WHERE run_date=? AND task='market_state' ORDER BY id DESC LIMIT 1",
            [run_date],
        ).fetchone()
    if not row:
        return None
    parts = dict(p.split("=") for p in row[0].split(",") if "=" in p)
    return {
        "state": parts.get("state"),
        "close": float(parts.get("close", 0)),
        "ma60": float(parts.get("ma60", 0)),
        "rsi": float(parts.get("rsi", 0)),
    }


# ---- Rules endpoints ----

@app.get("/api/rules")
def get_rules():
    rules = []
    for fname in ["rules_bullish.yaml", "rules_bearish.yaml", "rules_neutral.yaml"]:
        fpath = RULES_DIR / fname
        if not fpath.exists():
            continue
        with open(fpath) as f:
            data = yaml.safe_load(f)
        for r in (data or {}).get("rules", []):
            r["_source"] = fname
            rules.append(r)
    return {"data": rules}


@app.put("/api/rules")
def update_rules(body: dict):
    rules_by_file = {}
    for r in body.get("rules", []):
        fname = r.pop("_source", "rules_neutral.yaml")
        rules_by_file.setdefault(fname, []).append(r)

    for fname, rules_list in rules_by_file.items():
        fpath = RULES_DIR / fname
        with open(fpath, "w") as f:
            yaml.dump({"rules": rules_list}, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    return {"status": "ok", "files": list(rules_by_file.keys())}


# ---- Config endpoints ----

@app.get("/api/config")
def get_config():
    with open(CONFIG_PATH) as f:
        cfg = json.load(f)
    cfg.pop("notification", None)
    return {"data": cfg}


@app.put("/api/config")
def update_config(body: dict):
    with open(CONFIG_PATH) as f:
        cfg = json.load(f)
    if "watch_stocks" in body:
        cfg["watch_stocks"] = body["watch_stocks"]
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=4, ensure_ascii=False)
        f.write("\n")
    return {"status": "ok"}


# ---- Health check config endpoints ----

HEALTH_CHECK_CONFIG_PATH = RULES_DIR / "health_check.yaml"


@app.get("/api/health-check-config")
def get_health_check_config():
    with open(HEALTH_CHECK_CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)
    return {"data": cfg or {}}


@app.put("/api/health-check-config")
def update_health_check_config(body: dict):
    with open(HEALTH_CHECK_CONFIG_PATH, "w") as f:
        yaml.dump(body, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    return {"status": "ok"}


# ---- Health & Dashboard ----

@app.get("/api/health")
def health_check_all():
    db = _get_db()
    today = date.today().isoformat()
    rows = db.get_health_scores(today)
    return {"data": rows}


@app.get("/api/weekly-health")
def weekly_health():
    db = _get_db()
    today = date.today().isoformat()
    rows = db.get_weekly_health_scores(today)
    return {"data": rows}


@app.get("/api/monthly-health")
def monthly_health():
    db = _get_db()
    today = date.today().isoformat()
    rows = db.get_monthly_health_scores(today)
    return {"data": rows}


@app.get("/api/stocks/{stock_id}/dividends")
def stock_dividends(stock_id: str):
    db = _get_db()
    rows = db.get_dividends(stock_id)
    return {"data": rows}


@app.get("/api/stocks/{stock_id}/margin-trading")
def stock_margin_trading(stock_id: str):
    db = _get_db()
    rows = db.get_margin_trading(stock_id, limit=20)
    return {"data": rows}


@app.get("/api/stocks/{stock_id}/institutional-flows")
def stock_institutional_flows(stock_id: str):
    db = _get_db()
    rows = db.get_institutional_flows(stock_id, limit=60)
    return {"data": rows}


@app.get("/api/stocks/{stock_id}/institutional-trades")
def stock_institutional_trades(stock_id: str):
    """Alias of /institutional-flows, matching T014-5 task spec naming."""
    db = _get_db()
    rows = db.get_institutional_flows(stock_id, limit=60)
    return {"data": rows}


SECTOR_MAP: dict[str, str] = {
    "2330": "半導體",
    "2308": "半導體",
    "0050": "ETF",
}


@app.get("/api/stocks/{stock_id}/sector-ranking")
def stock_sector_ranking(stock_id: str):
    """T014-4: return stock's sector and EPS/ROE/ROA percentile within sector.

    Percentile: rank / total * 100, smaller = better (前 N%).
    """
    db = _get_db()
    sector = SECTOR_MAP.get(stock_id)
    if not sector:
        return {"data": {"stock_id": stock_id, "stock_name": STOCK_NAMES.get(stock_id, stock_id), "sector": None, "percentiles": {}, "members": []}}

    sector_members = [sid for sid, sec in SECTOR_MAP.items() if sec == sector]
    latest: dict[str, dict] = {}
    for sid in sector_members:
        rows = db.get_quarterly_financials(sid, limit=1)
        if rows:
            latest[sid] = rows[0]

    def percentile(metric: str) -> float | None:
        vals = sorted(r[metric] for r in latest.values() if r.get(metric) is not None)
        if not vals:
            return None
        cur = latest.get(stock_id, {}).get(metric)
        if cur is None:
            return None
        above = sum(1 for v in vals if v > cur)
        return round(above / len(vals) * 100, 1)

    members = [
        {
            "stock_id": sid,
            "stock_name": STOCK_NAMES.get(sid, sid),
            "eps": latest[sid].get("eps"),
            "roe": latest[sid].get("roe"),
            "roa": latest[sid].get("roa"),
            "fiscal_quarter": latest[sid].get("fiscal_quarter"),
        }
        for sid in latest
    ]
    members.sort(key=lambda m: (m["roe"] if m["roe"] is not None else -1e18), reverse=True)

    return {"data": {
        "stock_id": stock_id,
        "stock_name": STOCK_NAMES.get(stock_id, stock_id),
        "sector": sector,
        "member_count": len(latest),
        "percentiles": {
            "eps": percentile("eps"),
            "roe": percentile("roe"),
            "roa": percentile("roa"),
        },
        "members": members,
    }}


@app.get("/api/sector-ranking")
def sector_ranking_endpoint():
    """Aggregate health scores by sector and rank."""
    db = _get_db()
    latest = db.get_latest_health_date()
    if not latest:
        return {"data": []}
    scores = db.get_health_scores(latest)
    
    sector_scores: dict[str, list[dict]] = {}
    for s in scores:
        sec = SECTOR_MAP.get(s["stock_id"], "其他")
        sector_scores.setdefault(sec, []).append(s)
    
    ranking = []
    for sec, members in sorted(sector_scores.items()):
        avg_score = round(sum(m["total_score"] for m in members) / len(members), 1) if members else 0
        ranking.append({
            "sector": sec,
            "count": len(members),
            "avg_score": avg_score,
            "members": sorted(members, key=lambda x: x["total_score"], reverse=True),
        })
    
    ranking.sort(key=lambda x: x["avg_score"], reverse=True)
    return {"data": ranking}


@app.get("/api/stocks/{stock_id}/quarterly-financials")
def stock_quarterly_financials(stock_id: str):
    db = _get_db()
    rows = db.get_quarterly_financials(stock_id, limit=20)
    return {"data": rows}


@app.get("/api/stocks/{stock_id}/monthly-revenue")
def stock_monthly_revenue(stock_id: str):
    db = _get_db()
    rows = db.get_monthly_revenue(stock_id, limit=36)
    return {"data": rows}


@app.get("/api/structural-drift")
def structural_drift(today_only: bool = True):
    db = _get_db()
    if today_only:
        rows = db.get_structural_drift(trade_date=date.today().isoformat())
    else:
        rows = db.get_structural_drift()
    return {"data": rows}


@app.get("/api/drift-report")
def drift_report():
    from tw_quant_signal.structural_change import generate_structural_change_report
    db = _get_db()
    report = generate_structural_change_report(db)
    if report:
        return {"data": {"report": report}}
    return {"data": {"report": "無足夠資料產生結構變化偵測報告"}}


# ---- Environment & Governance endpoints ----

@app.get("/api/environment")
def get_environment():
    from tw_quant_signal.env_manager import get_summary
    return {"data": get_summary()}


@app.get("/api/compliance-statement")
def compliance_statement():
    from tw_quant_signal.operation_log import get_compliance_statement
    return {"data": {"statement": get_compliance_statement()}}


@app.get("/api/compliance-report")
def compliance_report():
    from tw_quant_signal.operation_log import build_compliance_report
    db = _get_db()
    report = build_compliance_report(db)
    return {"data": {"report": report}}


@app.get("/api/operation-log")
def operation_log(days: int = Query(default=7, ge=1, le=90)):
    from tw_quant_signal.operation_log import get_operation_log
    db = _get_db()
    log = get_operation_log(db, days=days)
    return {"data": log}


@app.get("/api/multi-timeframe")
def multi_timeframe():
    db = _get_db()
    today = date.today().isoformat()
    rows = db.get_multi_timeframe_consensus(today)
    return {"data": rows}


@app.get("/api/dashboard")
def dashboard():
    db = _get_db()
    stocks = list_stocks()["data"]
    ms = _get_market_state(db, date.today().isoformat())
    report_path = PROJECT_ROOT / "data" / "reports" / f"report_{date.today().isoformat()}.md"
    report_text = ""
    if report_path.exists():
        report_text = report_path.read_text()
    return {
        "data": {
            "stocks": stocks,
            "market_state": ms,
            "report": report_text,
        }
    }


# ---- T015: 11 大指標計分卡 ----

@app.get("/api/signals/all/scorecard")
def all_scorecards():
    """T015: 全標的計分卡一次輸出（最近一筆）。"""
    db = _get_db()
    rows = db.get_latest_scorecards(limit=20)
    out = []
    for r in rows:
        out.append({
            "stock_id": r["stock_id"],
            "trade_date": r["trade_date"],
            "bullish": dict(r["bullish_detail"], count=r["bullish_score"], ratio=f"{r['bullish_score']}/11"),
            "bearish": dict(r["bearish_detail"], count=r["bearish_score"], ratio=f"{r['bearish_score']}/11"),
        })
    return {"data": out}


@app.get("/api/signals/{stock_id}/scorecard")
def stock_scorecard(stock_id: str):
    """T015: 單一標的 11 大指標多空計分卡。

    回傳 bullish / bearish 各 11 項 boolean + count + ratio。
    """
    db = _get_db()
    rows = db.get_latest_scorecards(stock_id=stock_id, limit=1)
    if not rows:
        # Fallback: compute on the fly
        from tw_quant_signal.signal_scorecard import compute_scorecard
        sc = compute_scorecard(db, stock_id)
        if not sc.get("trade_date"):
            return {"data": None, "error": "無資料"}
        return {"data": sc}
    r = rows[0]
    sc = {
        "stock_id": r["stock_id"],
        "trade_date": r["trade_date"],
        "bullish": dict(r["bullish_detail"], count=r["bullish_score"], ratio=f"{r['bullish_score']}/11"),
        "bearish": dict(r["bearish_detail"], count=r["bearish_score"], ratio=f"{r['bearish_score']}/11"),
    }
    return {"data": sc}


# ---- T019: 績效追蹤 ----

@app.get("/api/performance/rules")
def performance_rules(days: int = Query(default=30, ge=1, le=365),
                     horizon: int = Query(default=5, ge=1, le=10),
                     market_state: str = Query(default=None, pattern="^(bull|bear|range|unknown)$")):
    """T019: 每條規則的胜率/均酬/貲損比/最大DD/連違虧損 Markdown 表格。"""
    from datetime import date as _date, timedelta as _timedelta
    from tw_quant_signal.performance_tracker import compute_agg_stats
    db = _get_db()
    if days:
        cutoff = (_date.today() - _timedelta(days=days)).isoformat()
    else:
        cutoff = None
    stats = compute_agg_stats(db, from_date=cutoff, horizon=horizon)
    filtered = stats
    if market_state:
        filtered = {
            **stats,
            "rules": {
                rid: info for rid, info in stats["rules"].items()
                if market_state in info["by_state"]
            },
        }
    return {"data": filtered}


@app.get("/api/performance/overview")
def performance_overview(days: int = Query(default=30, ge=1, le=365),
                         horizon: int = Query(default=5, ge=1, le=10)):
    """T019: 整體系統績效概。"""
    from datetime import date as _date, timedelta as _timedelta
    from tw_quant_signal.performance_tracker import compute_agg_stats
    db = _get_db()
    cutoff = (_date.today() - _timedelta(days=days)).isoformat()
    stats = compute_agg_stats(db, from_date=cutoff, horizon=horizon)
    overview = stats["overview"]
    return {"data": {
        "horizon": horizon,
        "days": days,
        "from_date": stats["from_date"],
        "to_date": stats["to_date"],
        "total_triggers": overview["triggers"],
        "win_rate": overview["win_rate"],
        "avg_return": overview["avg_return"],
        "avg_win": overview["avg_win"],
        "avg_loss": overview["avg_loss"],
        "profit_ratio": overview["profit_ratio"],
        "max_dd": overview["max_dd"],
        "consecutive_losses": overview["max_consecutive_losses"],
        "expectancy": overview["expectancy"],
        "by_state": overview["by_state"],
    }}


@app.get("/api/performance/logs")
def performance_logs(days: int = Query(default=30, ge=1, le=365),
                     rule_id: str = Query(default=None),
                     stock_id: str = Query(default=None),
                     market_state: str = Query(default=None, pattern="^(bull|bear|range|unknown)$")):
    """T019: 原始 performance_log 記錄明細 (供前端表格使用)。"""
    from datetime import date as _date, timedelta as _timedelta
    db = _get_db()
    cutoff = (_date.today() - _timedelta(days=days)).isoformat()
    rows = db.get_performance_logs(
        from_date=cutoff,
        rule_id=rule_id,
        stock_id=stock_id,
        market_state=market_state,
    )
    rows.reverse()  # 由近至遠
    return {"data": rows}


# ---- Serve frontend ----

if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="assets")

    @app.get("/{full_path:path}")
    def serve_frontend(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(404)
        index = FRONTEND_DIST / "index.html"
        if index.exists():
            return FileResponse(str(index))
        return {"error": "frontend not built"}
else:
    @app.get("/")
    def root():
        return {"message": "tw-quant-signal API - build frontend with `cd frontend && npm run build`"}
