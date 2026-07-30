import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import yaml
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from tw_quant_signal.db import SignalDB
from tw_quant_signal.config import settings

app = FastAPI(title="tw-quant-signal API", version="1.0.0")

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
    risk = db.get_risk_metrics(today, stock_id)
    signals = db.get_rule_signals_for_date(today, stock_id)
    ms = _get_market_state(db, today)

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
            "risk": risk[0] if risk else None,
            "signals": signals,
            "market_state": ms,
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
