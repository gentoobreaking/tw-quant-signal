"""T021 S6 端到端驗證腳本。

對比 direct / mcp 兩種 DataProvider 模式的 ingestion 結果：
1. 各自用獨立隔離 DB 跑完整 ingestion
2. 比對 daily_prices 內容一致性（同交易日同價）
3. 驗證 pipeline_log 的 source 標註
"""
import os
import sys
import tempfile
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from tw_quant_signal.db import SignalDB
from tw_quant_signal.ingestion import IngestionEngine
from tw_quant_signal.provider import create_data_provider


def run_ingestion(db_path: str, provider_mode: str) -> dict:
    os.environ["TW_QUANT_DB"] = db_path
    os.environ["TW_QUANT_DATA_PROVIDER"] = provider_mode
    # 重新載入 config（避免 module 級快取）
    import importlib
    import tw_quant_signal.config as config_mod
    importlib.reload(config_mod)
    import tw_quant_signal.db as db_mod
    importlib.reload(db_mod)

    db = db_mod.SignalDB(db_path)
    db.init_db()
    engine = IngestionEngine(db)
    status = engine.run_daily(date.today().isoformat())
    return {"db": db, "status": status, "engine": engine}


def main():
    print("=== T021 S6 端到端驗證 ===")
    results = {}
    for mode in ["direct", "mcp"]:
        tmp = tempfile.mktemp(suffix=".db")
        print(f"\n--- {mode} 模式 ---")
        res = run_ingestion(tmp, mode)
        results[mode] = res
        for k, v in res["status"].items():
            print(f"  [{v}] {k}")

    # 比對 daily_prices（同日期同價）
    db_d = results["direct"]["db"]
    db_m = results["mcp"]["db"]
    print("\n=== daily_prices 比對 ===")
    with db_d.connect() as conn:
        d_rows = conn.execute(
            "SELECT stock_id, trade_date, open, high, low, close, volume FROM daily_prices"
        ).fetchall()
    with db_m.connect() as conn:
        m_rows = conn.execute(
            "SELECT stock_id, trade_date, open, high, low, close, volume FROM daily_prices"
        ).fetchall()
    d_map = {(r[0], r[1]): r[2:] for r in d_rows}
    m_map = {(r[0], r[1]): r[2:] for r in m_rows}
    print(f"direct {len(d_rows)} 筆, mcp {len(m_rows)} 筆")

    # 補齊：mcp 用歷史 kline 抓 direct 有的交易日，確保共同交易日可比
    m_engine = results["mcp"]["engine"]
    with db_d.connect() as conn:
        d_dates = {r[0] for r in conn.execute(
            "SELECT stock_id, trade_date FROM daily_prices"
        ).fetchall()}
    with db_m.connect() as conn:
        m_dates = {r[0] for r in conn.execute(
            "SELECT stock_id, trade_date FROM daily_prices"
        ).fetchall()}
    missing = d_dates - m_dates
    if missing:
        print(f"補齊 {len(missing)} 個 direct 交易日至 mcp DB（歷史 kline）...")
        for sid, tdate in sorted(missing):
            if sid == "0050":  # ETF mcp 不支援，跳過
                continue
            rows = m_engine.provider.fetch_historical_daily_prices(sid, tdate, tdate)
            if rows:
                db_m.upsert_daily_prices(rows)
        with db_m.connect() as conn:
            m_rows = conn.execute(
                "SELECT stock_id, trade_date, open, high, low, close, volume FROM daily_prices"
            ).fetchall()
        m_map = {(r[0], r[1]): r[2:] for r in m_rows}

    common = set(d_map) & set(m_map)
    diff = [k for k in common if d_map[k] != m_map[k]]
    print(f"共同交易日: {len(common)}, 價格不一致: {len(diff)}")
    for k in sorted(diff)[:10]:
        print(f"  DIFF {k}: direct={d_map[k]} mcp={m_map[k]}")
    only_d = set(d_map) - set(m_map)
    only_m = set(m_map) - set(d_map)
    if only_d:
        print(f"  僅 direct 有: {sorted(only_d)[:5]}")
    if only_m:
        print(f"  僅 mcp 有: {sorted(only_m)[:5]}")

    # pipeline_log source 標註
    print("\n=== pipeline_log source 標註 ===")
    for mode, res in results.items():
        with res["db"].connect() as conn:
            rows = conn.execute(
                "SELECT task, status, message FROM pipeline_log WHERE task IN ('watch_stocks','institutional_flows','margin_trading','valuations') ORDER BY id"
            ).fetchall()
        print(f"[{mode}]")
        for r in rows:
            print(f"  {r[0]}: {r[1]} | {r[2] or ''}")

    print("\n=== 驗證結果 ===")
    ok = len(diff) == 0
    print("daily_prices 一致性:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
