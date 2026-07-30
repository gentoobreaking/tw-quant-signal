import sys
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
import pandas as pd

from tw_quant_signal.db import SignalDB
from tw_quant_signal.twse_client import (
    fetch_historical_daily_prices,
    fetch_institutional_flows,
    WATCH_STOCKS,
)
from tw_quant_signal.indicators import compute_indicators


def backfill_via_yahoo(stock_id: str, years: int = 5) -> int:
    """Use Yahoo Finance as primary historical source."""
    try:
        import yfinance as yf
    except ImportError:
        print("  ⚠ yfinance not installed. Install with: pip install tw-quant-signal[backfill]")
        return 0

    twse_id = f"{stock_id}.TW"
    end_date = date.today()
    start_date = end_date - relativedelta(years=years)
    print(f"  Yahoo Finance: {twse_id} ({start_date} ~ {end_date})")

    ticker = yf.Ticker(twse_id)
    df = ticker.history(start=start_date.isoformat(), end=end_date.isoformat())
    if df.empty:
        print("  ⚠ yfinance returned empty")
        return 0

    rows = []
    for dt_idx, row in df.iterrows():
        trade_date = dt_idx.strftime("%Y-%m-%d") if hasattr(dt_idx, "strftime") else str(dt_idx)[:10]
        close = float(row["Close"]) if pd.notna(row["Close"]) else None
        rows.append({
            "stock_id": stock_id,
            "trade_date": trade_date,
            "open": float(row["Open"]) if pd.notna(row["Open"]) else None,
            "high": float(row["High"]) if pd.notna(row["High"]) else None,
            "low": float(row["Low"]) if pd.notna(row["Low"]) else None,
            "close": close,
            "adj_close": close,
            "adj_factor": 1.0,
            "volume": int(row["Volume"]) if pd.notna(row["Volume"]) else None,
            "amount": None,
        })

    if rows:
        db = SignalDB()
        db.upsert_daily_prices(rows)
    print(f"  → {len(rows)} 筆寫入")
    return len(rows)


def backfill_via_twse_current_month(stock_id: str) -> int:
    """Fallback: get current month from TWSE per-stock API."""
    today = date.today()
    start = today.replace(day=1)
    rows = fetch_historical_daily_prices(stock_id, start.isoformat(), today.isoformat())
    if rows:
        db = SignalDB()
        db.upsert_daily_prices(rows)
    print(f"  → {len(rows)} 筆寫入 (TWSE 當月)")
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

    total = 0
    for sid in WATCH_STOCKS:
        n = backfill_via_yahoo(sid, years=5)
        if n == 0:
            n = backfill_via_twse_current_month(sid)
        total += n
    print(f"\n共回填 {total} 筆價格資料")

    for sid in WATCH_STOCKS:
        backfill_indicators(sid)

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
