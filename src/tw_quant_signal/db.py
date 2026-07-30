import sqlite3
from contextlib import contextmanager
from datetime import date
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
            signal_date  TEXT NOT NULL,
            stock_id     TEXT NOT NULL DEFAULT '^TWII',
            signal_type  TEXT NOT NULL,
            signal_value TEXT NOT NULL,
            score        REAL,
            details      TEXT,
            created_at   TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            PRIMARY KEY (signal_date, stock_id, signal_type)
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
