"""Backfill historical PE/PB ratios into existing features JSON.

Since features already exist with full data, we update the JSON in-place
to add pe_ratio, pb_ratio, dividend_yield fields.
"""

import json
from datetime import date

from tw_quant_signal.db import SignalDB
from tw_quant_signal.twse_client import WATCH_STOCKS, fetch_valuations


def _get_current_eps_approx(stock_id: str, db: SignalDB) -> float | None:
    with db.connect() as conn:
        close = conn.execute(
            "SELECT close FROM daily_prices WHERE stock_id=? ORDER BY trade_date DESC LIMIT 1",
            [stock_id],
        ).fetchone()
    if not close or not close[0]:
        return None
    vals = fetch_valuations([stock_id])
    pe = vals.get(stock_id, {}).get("pe_ratio")
    if not pe:
        return None
    return round(close[0] / pe, 4)


def backfill_pe_pb_history():
    db = SignalDB()
    db.init_db()

    # Fetch latest PB/DY from API once
    vals = fetch_valuations(WATCH_STOCKS)

    for sid in WATCH_STOCKS:
        eps = _get_current_eps_approx(sid, db)
        if not eps:
            print(f"  ⚠ {sid}: cannot determine EPS, skip")
            continue

        val = vals.get(sid, {})
        latest_pb = val.get("pb_ratio")
        latest_dy = val.get("dividend_yield")

        with db.connect() as conn:
            closes = conn.execute(
                "SELECT trade_date, close FROM daily_prices WHERE stock_id=? ORDER BY trade_date ASC",
                [sid],
            ).fetchall()

        if len(closes) < 20:
            print(f"  ⚠ {sid}: only {len(closes)} price rows, skip")
            continue

        updated = 0
        with db.connect() as conn:
            for td, close in closes:
                if not close:
                    continue
                pe = round(close / eps, 2)
                existing = conn.execute(
                    "SELECT data FROM features WHERE stock_id=? AND trade_date=?",
                    [sid, td],
                ).fetchone()
                if existing:
                    data = json.loads(existing[0])
                    data["pe_ratio"] = pe
                    data["pb_ratio"] = latest_pb
                    data["dividend_yield"] = latest_dy
                    conn.execute(
                        "UPDATE features SET data=? WHERE stock_id=? AND trade_date=?",
                        [json.dumps(data, ensure_ascii=False), sid, td],
                    )
                else:
                    data = {
                        "stock_id": sid,
                        "trade_date": td,
                        "close": close,
                        "pe_ratio": pe,
                        "pb_ratio": latest_pb,
                        "dividend_yield": latest_dy,
                    }
                    conn.execute(
                        "INSERT OR IGNORE INTO features (trade_date, stock_id, data) VALUES (?, ?, ?)",
                        [td, sid, json.dumps(data, ensure_ascii=False)],
                    )
                updated += 1

        print(f"  {sid}: {updated} rows updated (EPS={eps})")

    print("Done!")


if __name__ == "__main__":
    backfill_pe_pb_history()
