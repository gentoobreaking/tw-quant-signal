import sqlite3
from contextlib import contextmanager
from datetime import date
from typing import Optional
from pathlib import Path

from tw_quant_signal.config import settings

DB_PATH = settings.db_path


def _init_schema(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS pipeline_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            run_date    TEXT NOT NULL,
            task        TEXT NOT NULL,
            status      TEXT NOT NULL CHECK(status IN ('ok','fail','skip')),
            message     TEXT,
            created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );

        CREATE INDEX IF NOT EXISTS idx_pipeline_run ON pipeline_log(run_date, task);

        CREATE TABLE IF NOT EXISTS daily_prices (
            stock_id    TEXT NOT NULL,
            trade_date  TEXT NOT NULL,
            open        REAL,
            high        REAL,
            low         REAL,
            close       REAL,
            volume      INTEGER,
            amount      REAL,
            adj_factor  REAL DEFAULT 1.0,
            adj_close   REAL,
            PRIMARY KEY (stock_id, trade_date)
        );

        CREATE TABLE IF NOT EXISTS market_index (
            trade_date  TEXT PRIMARY KEY,
            close       REAL,
            change_pct  REAL
        );

        CREATE TABLE IF NOT EXISTS institutional_flows (
            stock_id   TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            market     TEXT NOT NULL DEFAULT 'TSE',
            foreign_investors_net  INTEGER,
            sity_investors_net     INTEGER,
            dealer_net             INTEGER,
            dealer_proprietary_net INTEGER,
            dealer_hedge_net       INTEGER,
            total_net              INTEGER,
            PRIMARY KEY (stock_id, trade_date)
        );

        CREATE TABLE IF NOT EXISTS signals (
            trade_date   TEXT NOT NULL,
            stock_id     TEXT NOT NULL,
            d1_score     INTEGER DEFAULT 0,
            d1_signal    TEXT,
            d2_score     INTEGER DEFAULT 0,
            d2_signal    TEXT,
            d3_score     INTEGER DEFAULT 0,
            d3_signal    TEXT,
            d4_score     INTEGER DEFAULT 0,
            d4_signal    TEXT,
            total_score  INTEGER DEFAULT 0,
            signal       TEXT,
            PRIMARY KEY (trade_date, stock_id)
        );

        CREATE TABLE IF NOT EXISTS rule_signals (
            trade_date      TEXT NOT NULL,
            stock_id        TEXT NOT NULL,
            triggered_rules TEXT,
            triggered_count INTEGER DEFAULT 0,
            signal          TEXT,
            total_score     INTEGER DEFAULT 0,
            PRIMARY KEY (trade_date, stock_id)
        );

        CREATE TABLE IF NOT EXISTS features (
            trade_date TEXT NOT NULL,
            stock_id   TEXT NOT NULL,
            data       TEXT NOT NULL,
            PRIMARY KEY (trade_date, stock_id)
        );

        CREATE TABLE IF NOT EXISTS tech_indicators (
            stock_id       TEXT NOT NULL,
            trade_date     TEXT NOT NULL,
            ma5            REAL,
            ma20           REAL,
            ma60           REAL,
            bb_upper       REAL,
            bb_middle      REAL,
            bb_lower       REAL,
            rsi14          REAL,
            volume_ma5     REAL,
            volume_ma20    REAL,
            PRIMARY KEY (stock_id, trade_date)
        );

        CREATE TABLE IF NOT EXISTS financial_data (
            stock_id        TEXT NOT NULL,
            fiscal_quarter  TEXT NOT NULL,
            eps             REAL,
            revenue         REAL,
            gross_margin    REAL,
            updated_at      TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            PRIMARY KEY (stock_id, fiscal_quarter)
        );

        CREATE TABLE IF NOT EXISTS margin_data (
            stock_id        TEXT NOT NULL,
            trade_date      TEXT NOT NULL,
            margin_balance  INTEGER,
            short_balance   INTEGER,
            margin_ratio    REAL,
            PRIMARY KEY (stock_id, trade_date)
        );

        CREATE TABLE IF NOT EXISTS risk_metrics (
            trade_date      TEXT NOT NULL,
            stock_id        TEXT NOT NULL,
            volatility_20d  REAL,
            volatility_avg  REAL,
            vol_ratio       REAL,
            atr_14d         REAL,
            atr_pct         REAL,
            max_drawdown    REAL,
            signal_conflict INTEGER DEFAULT 0,
            stop_loss_atr   REAL,
            stop_loss_ma    REAL,
            risk_level      TEXT,
            risk_score      INTEGER DEFAULT 0,
            details         TEXT,
            PRIMARY KEY (trade_date, stock_id)
        );

        CREATE TABLE IF NOT EXISTS health_scores (
            trade_date          TEXT NOT NULL,
            stock_id            TEXT NOT NULL,
            fundamental_score   REAL,
            fundamental_light   TEXT,
            institutional_score REAL,
            institutional_light TEXT,
            technical_score     REAL,
            technical_light     TEXT,
            valuation_score     REAL,
            valuation_light     TEXT,
            total_score         REAL,
            total_light         TEXT,
            details             TEXT,
            PRIMARY KEY (trade_date, stock_id)
        );

        CREATE TABLE IF NOT EXISTS weekly_indicators (
            stock_id       TEXT NOT NULL,
            trade_date     TEXT NOT NULL,
            close          REAL,
            ma5            REAL,
            ma20           REAL,
            ma60           REAL,
            bb_upper       REAL,
            bb_middle      REAL,
            bb_lower       REAL,
            rsi14          REAL,
            volume_ma5     REAL,
            volume_ma20    REAL,
            PRIMARY KEY (stock_id, trade_date)
        );

        CREATE TABLE IF NOT EXISTS weekly_health_scores (
            trade_date          TEXT NOT NULL,
            stock_id            TEXT NOT NULL,
            fundamental_score   REAL,
            fundamental_light   TEXT,
            institutional_score REAL,
            institutional_light TEXT,
            technical_score     REAL,
            technical_light     TEXT,
            valuation_score     REAL,
            valuation_light     TEXT,
            total_score         REAL,
            total_light         TEXT,
            details             TEXT,
            PRIMARY KEY (trade_date, stock_id)
        );

        CREATE TABLE IF NOT EXISTS multi_timeframe_consensus (
            trade_date       TEXT NOT NULL,
            stock_id         TEXT NOT NULL,
            daily_light      TEXT,
            weekly_light     TEXT,
            consensus        TEXT NOT NULL,
            consensus_label  TEXT NOT NULL,
            signal_type      TEXT NOT NULL,
            details          TEXT,
            PRIMARY KEY (trade_date, stock_id)
        );
    """)


class SignalDB:
    def __init__(self, db_path: str = DB_PATH):
        self._path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_db(self):
        with self.connect() as conn:
            _init_schema(conn)

    def log_pipeline(self, run_date: str, task: str, status: str, message: str = None):
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO pipeline_log (run_date, task, status, message) VALUES (?, ?, ?, ?)",
                [run_date, task, status, message],
            )

    def get_pipeline_status(self, run_date: str) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT task, status, message, created_at FROM pipeline_log WHERE run_date=? ORDER BY id",
                [run_date],
            ).fetchall()
            return [dict(r) for r in rows]

    def upsert_daily_prices(self, rows: list[dict]):
        with self.connect() as conn:
            for r in rows:
                close = r.get("close")
                adj_close = r.get("adj_close", close)
                adj_factor = r.get("adj_factor", 1.0)
                conn.execute(
                    """INSERT OR REPLACE INTO daily_prices
                       (stock_id, trade_date, open, high, low, close, volume, amount, adj_factor, adj_close)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [r["stock_id"], r["trade_date"], r.get("open"), r.get("high"),
                     r.get("low"), close, r.get("volume"), r.get("amount"),
                     adj_factor, adj_close],
                )

    def upsert_market_index(self, row: dict):
        with self.connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO market_index
                   (trade_date, close, change_pct)
                   VALUES (?, ?, ?)""",
                [row["trade_date"], row.get("close"), row.get("change_pct")],
            )

    def upsert_institutional_flows(self, rows: list[dict]):
        with self.connect() as conn:
            for r in rows:
                conn.execute(
                    """INSERT OR REPLACE INTO institutional_flows
                       (stock_id, trade_date, market, foreign_investors_net, sity_investors_net,
                        dealer_net, dealer_proprietary_net, dealer_hedge_net, total_net)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [r["stock_id"], r["trade_date"], r.get("market", "TSE"),
                     r.get("foreign_investors_net"), r.get("sity_investors_net"),
                     r.get("dealer_net"), r.get("dealer_proprietary_net"),
                     r.get("dealer_hedge_net"), r.get("total_net")],
                )

    def upsert_features(self, rows: list[dict]):
        import json
        if not rows:
            return
        with self.connect() as conn:
            for r in rows:
                trade_date = r.get("trade_date")
                stock_id = r.get("stock_id")
                if not trade_date or not stock_id:
                    continue
                conn.execute("DELETE FROM features WHERE trade_date=? AND stock_id=?", [trade_date, stock_id])
                conn.execute(
                    "INSERT INTO features (trade_date, stock_id, data) VALUES (?, ?, ?)",
                    [trade_date, stock_id, json.dumps(r, ensure_ascii=False)],
                )

    def upsert_financial_data(self, rows: list[dict]):
        if not rows:
            return
        with self.connect() as conn:
            for r in rows:
                conn.execute(
                    """INSERT OR REPLACE INTO financial_data
                    (stock_id, fiscal_quarter, eps, revenue, gross_margin)
                    VALUES (?, ?, ?, ?, ?)""",
                    [r["stock_id"], r.get("fiscal_quarter"),
                     r.get("eps"), r.get("revenue"), r.get("gross_margin")],
                )

    def get_latest_financial_data(self, stock_id: str) -> Optional[dict]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM financial_data WHERE stock_id=? ORDER BY fiscal_quarter DESC LIMIT 1",
                [stock_id],
            ).fetchone()
            return dict(row) if row else None

    def upsert_margin_data(self, rows: list[dict]):
        if not rows:
            return
        with self.connect() as conn:
            for r in rows:
                conn.execute(
                    """INSERT OR REPLACE INTO margin_data
                    (stock_id, trade_date, margin_balance, short_balance, margin_ratio)
                    VALUES (?, ?, ?, ?, ?)""",
                    [r["stock_id"], r.get("trade_date"),
                     r.get("margin_balance"), r.get("short_balance"), r.get("margin_ratio")],
                )

    def get_latest_margin_ratio(self, stock_id: str) -> Optional[float]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT margin_ratio FROM margin_data WHERE stock_id=? ORDER BY trade_date DESC LIMIT 1",
                [stock_id],
            ).fetchone()
            return row[0] if row else None

    def get_latest_margin_raw(self, stock_id: str) -> Optional[dict]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT margin_balance, short_balance, margin_ratio FROM margin_data "
                "WHERE stock_id=? ORDER BY trade_date DESC LIMIT 1",
                [stock_id],
            ).fetchone()
            if not row:
                return None
            return {"margin_balance": row[0], "short_balance": row[1], "margin_ratio": row[2]}

    def upsert_risk_metrics(self, rows: list[dict]):
        import json
        if not rows:
            return
        with self.connect() as conn:
            for r in rows:
                conn.execute("DELETE FROM risk_metrics WHERE trade_date=? AND stock_id=?",
                             [r["trade_date"], r["stock_id"]])
                conn.execute(
                    """INSERT INTO risk_metrics
                    (trade_date, stock_id, volatility_20d, volatility_avg, vol_ratio,
                     atr_14d, atr_pct, max_drawdown, signal_conflict,
                     stop_loss_atr, stop_loss_ma, risk_level, risk_score, details)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [
                        r["trade_date"], r["stock_id"],
                        r.get("volatility_20d"), r.get("volatility_avg"), r.get("vol_ratio"),
                        r.get("atr_14d"), r.get("atr_pct"), r.get("max_drawdown"),
                        1 if r.get("signal_conflict") else 0,
                        r.get("stop_loss_atr"), r.get("stop_loss_ma"),
                        r.get("risk_level"), r.get("risk_score"),
                        json.dumps(r.get("details", {}), ensure_ascii=False),
                    ],
                )

    def get_rule_signals_for_date(self, trade_date: str, stock_id: str) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT triggered_rules FROM rule_signals WHERE trade_date=? AND stock_id=?",
                [trade_date, stock_id],
            ).fetchall()
        return [dict(r) for r in rows]

    def get_risk_metrics(self, trade_date: str, stock_id: str = None) -> list[dict]:
        with self.connect() as conn:
            if stock_id:
                rows = conn.execute(
                    "SELECT * FROM risk_metrics WHERE trade_date=? AND stock_id=?",
                    [trade_date, stock_id],
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM risk_metrics WHERE trade_date=?", [trade_date]
                ).fetchall()
        return [dict(r) for r in rows]

    def get_health_scores(self, trade_date: str, stock_id: str = None) -> list[dict]:
        with self.connect() as conn:
            import json
            cols = [
                "stock_id", "fundamental_score", "fundamental_light",
                "institutional_score", "institutional_light",
                "technical_score", "technical_light",
                "valuation_score", "valuation_light",
                "total_score", "total_light", "details",
            ]
            if stock_id:
                rows = conn.execute(
                    f"SELECT {','.join(cols)} FROM health_scores WHERE trade_date=? AND stock_id=?",
                    [trade_date, stock_id],
                ).fetchall()
            else:
                rows = conn.execute(
                    f"SELECT {','.join(cols)} FROM health_scores WHERE trade_date=?",
                    [trade_date],
                ).fetchall()
        result = []
        for r in rows:
            d = dict(zip(cols, r))
            if isinstance(d.get("details"), str):
                d["details"] = json.loads(d["details"])
            result.append(d)
        return result

    def upsert_health_scores(self, rows: list[dict]):
        import json
        if not rows:
            return
        with self.connect() as conn:
            for r in rows:
                conn.execute("DELETE FROM health_scores WHERE trade_date=? AND stock_id=?",
                             [r["trade_date"], r["stock_id"]])
                conn.execute(
                    """INSERT INTO health_scores
                    (trade_date, stock_id, fundamental_score, fundamental_light,
                     institutional_score, institutional_light,
                     technical_score, technical_light,
                     valuation_score, valuation_light,
                     total_score, total_light, details)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [
                        r["trade_date"], r["stock_id"],
                        r.get("fundamental_score"), r.get("fundamental_light"),
                        r.get("institutional_score"), r.get("institutional_light"),
                        r.get("technical_score"), r.get("technical_light"),
                        r.get("valuation_score"), r.get("valuation_light"),
                        r.get("total_score"), r.get("total_light"),
                        json.dumps(r.get("details", {}), ensure_ascii=False),
                    ],
                )

    def compute_adj_close(self, stock_id: str):
        """Compute adj_close = close * adj_factor for all rows of a stock.
        Uses cumulative adj_factor product from most recent to oldest.
        """
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT trade_date, close, adj_factor FROM daily_prices WHERE stock_id=? ORDER BY trade_date DESC",
                [stock_id],
            ).fetchall()
            if not rows:
                return
            factor = 1.0
            for r in rows:
                af = r["adj_factor"]
                if af and af != 0:
                    factor *= af
                adj_close = (r["close"] or 0) * factor
                conn.execute(
                    "UPDATE daily_prices SET adj_close=? WHERE stock_id=? AND trade_date=?",
                    [round(adj_close, 2), stock_id, r["trade_date"]],
                )

    def upsert_tech_indicators(self, rows: list[dict]):
        with self.connect() as conn:
            for r in rows:
                conn.execute(
                    """INSERT OR REPLACE INTO tech_indicators
                       (stock_id, trade_date, ma5, ma20, ma60, bb_upper, bb_middle, bb_lower, rsi14, volume_ma5, volume_ma20)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [r["stock_id"], r["trade_date"], r.get("ma5"), r.get("ma20"),
                     r.get("ma60"), r.get("bb_upper"), r.get("bb_middle"),
                     r.get("bb_lower"), r.get("rsi14"), r.get("volume_ma5"),
                     r.get("volume_ma20")],
                )

    def upsert_weekly_indicators(self, rows: list[dict]):
        with self.connect() as conn:
            for r in rows:
                conn.execute(
                    """INSERT OR REPLACE INTO weekly_indicators
                       (stock_id, trade_date, close, ma5, ma20, ma60, bb_upper, bb_middle, bb_lower, rsi14, volume_ma5, volume_ma20)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [r["stock_id"], r["trade_date"], r.get("close"),
                     r.get("ma5"), r.get("ma20"),
                     r.get("ma60"), r.get("bb_upper"), r.get("bb_middle"),
                     r.get("bb_lower"), r.get("rsi14"), r.get("volume_ma5"),
                     r.get("volume_ma20")],
                )

    def get_weekly_indicators(self, stock_id: str) -> Optional[dict]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT ma5, ma20, ma60, rsi14, bb_upper, bb_middle, bb_lower, "
                "volume_ma5, volume_ma20 FROM weekly_indicators "
                "WHERE stock_id=? ORDER BY trade_date DESC LIMIT 1",
                [stock_id],
            ).fetchone()
            if not row:
                return None
            keys = ["ma5", "ma20", "ma60", "rsi14", "bb_upper", "bb_middle", "bb_lower",
                    "volume_ma5", "volume_ma20"]
            return dict(zip(keys, row))

    def upsert_weekly_health_scores(self, rows: list[dict]):
        import json
        if not rows:
            return
        with self.connect() as conn:
            for r in rows:
                conn.execute("DELETE FROM weekly_health_scores WHERE trade_date=? AND stock_id=?",
                             [r["trade_date"], r["stock_id"]])
                conn.execute(
                    """INSERT INTO weekly_health_scores
                    (trade_date, stock_id, fundamental_score, fundamental_light,
                     institutional_score, institutional_light,
                     technical_score, technical_light,
                     valuation_score, valuation_light,
                     total_score, total_light, details)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [
                        r["trade_date"], r["stock_id"],
                        r.get("fundamental_score"), r.get("fundamental_light"),
                        r.get("institutional_score"), r.get("institutional_light"),
                        r.get("technical_score"), r.get("technical_light"),
                        r.get("valuation_score"), r.get("valuation_light"),
                        r.get("total_score"), r.get("total_light"),
                        json.dumps(r.get("details", {}), ensure_ascii=False),
                    ],
                )

    def get_weekly_health_scores(self, trade_date: str, stock_id: str = None) -> list[dict]:
        with self.connect() as conn:
            import json
            cols = [
                "stock_id", "fundamental_score", "fundamental_light",
                "institutional_score", "institutional_light",
                "technical_score", "technical_light",
                "valuation_score", "valuation_light",
                "total_score", "total_light", "details",
            ]
            if stock_id:
                rows = conn.execute(
                    f"SELECT {','.join(cols)} FROM weekly_health_scores WHERE trade_date=? AND stock_id=?",
                    [trade_date, stock_id],
                ).fetchall()
            else:
                rows = conn.execute(
                    f"SELECT {','.join(cols)} FROM weekly_health_scores WHERE trade_date=?",
                    [trade_date],
                ).fetchall()
        result = []
        for r in rows:
            d = dict(zip(cols, r))
            if isinstance(d.get("details"), str):
                d["details"] = json.loads(d["details"])
            result.append(d)
        return result

    def upsert_multi_timeframe_consensus(self, rows: list[dict]):
        import json
        if not rows:
            return
        with self.connect() as conn:
            for r in rows:
                conn.execute("DELETE FROM multi_timeframe_consensus WHERE trade_date=? AND stock_id=?",
                             [r["trade_date"], r["stock_id"]])
                conn.execute(
                    """INSERT INTO multi_timeframe_consensus
                    (trade_date, stock_id, daily_light, weekly_light, consensus, consensus_label, signal_type, details)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    [
                        r["trade_date"], r["stock_id"],
                        r.get("daily_light"), r.get("weekly_light"),
                        r.get("consensus"), r.get("consensus_label"),
                        r.get("signal_type"),
                        json.dumps(r.get("details", {}), ensure_ascii=False),
                    ],
                )

    def get_multi_timeframe_consensus(self, trade_date: str, stock_id: str = None) -> list[dict]:
        with self.connect() as conn:
            import json
            if stock_id:
                rows = conn.execute(
                    "SELECT * FROM multi_timeframe_consensus WHERE trade_date=? AND stock_id=?",
                    [trade_date, stock_id],
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM multi_timeframe_consensus WHERE trade_date=?",
                    [trade_date],
                ).fetchall()
        result = [dict(r) for r in rows]
        for d in result:
            if isinstance(d.get("details"), str):
                d["details"] = json.loads(d["details"])
        return result

    def get_stock_prices(self, stock_id: str, limit: int = 365) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT * FROM daily_prices WHERE stock_id=? ORDER BY trade_date DESC LIMIT ?""",
                [stock_id, limit],
            ).fetchall()
            return [dict(r) for r in rows]

    def get_institutional_flows(self, stock_id: str, limit: int = 20) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT * FROM institutional_flows WHERE stock_id=? ORDER BY trade_date DESC LIMIT ?""",
                [stock_id, limit],
            ).fetchall()
            return [dict(r) for r in rows]
