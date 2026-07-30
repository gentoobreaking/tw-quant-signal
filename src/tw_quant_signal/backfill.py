"""歷史資料回填 — 從 TWSE RWD API 補齊個股歷史日線"""
import sys
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta

from tw_quant_signal.db import SignalDB
from tw_quant_signal.twse_client import (
    fetch_historical_daily_prices,
    fetch_institutional_flows,
    fetch_market_index,
    WATCH_STOCKS,
)
from tw_quant_signal.indicators import compute_indicators


def backfill_prices(stock_id: str, years: int = 5):
    db = SignalDB()
    end_date = date.today().isoformat()
    start_date = (date.today() - relativedelta(years=years)).isoformat()
    print(f"回填 {stock_id} 從 {start_date} 到 {end_date} ...")
    rows = fetch_historical_daily_prices(stock_id, start_date, end_date)
    if rows:
        db.upsert_daily_prices(rows)
    print(f"  → {len(rows)} 筆寫入")
    return len(rows)


def backfill_indicators(stock_id: str):
    db = SignalDB()
    prices = db.get_stock_prices(stock_id, limit=365)
    if len(prices) < 60:
        print(f"  ⚠ 資料不足 ({len(prices)} 筆，需 ≥60), 跳過指標計算")
        return 0
    indicators = compute_indicators(prices, stock_id=stock_id)
    if indicators:
        db.upsert_tech_indicators(indicators)
    print(f"  → {len(indicators)} 筆技術指標寫入")
    return len(indicators)


def main():
    db = SignalDB()
    db.init_db()

    # 1. Backfill 2330 for 5 years
    total = 0
    for sid in WATCH_STOCKS:
        total += backfill_prices(sid, years=5)
    print(f"\n共回填 {total} 筆價格資料")

    # 2. Compute indicators
    for sid in WATCH_STOCKS:
        backfill_indicators(sid)

    # 3. Fetch latest institutional flows (current month should have data)
    print("\n取得近期法人買賣超...")
    today = date.today()
    for i in range(10):
        d = (today - timedelta(days=i)).isoformat()
        rows = fetch_institutional_flows(d)
        if rows:
            db.upsert_institutional_flows(rows)
            print(f"  {d}: {len(rows)} 筆")
            break
    else:
        print("  ⚠ 未能取得法人資料")

    print("\n回填完成!")


if __name__ == "__main__":
    sys.exit(main())
