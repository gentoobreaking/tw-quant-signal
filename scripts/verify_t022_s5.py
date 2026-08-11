#!/usr/bin/env python3
"""T022 S5 — mcp 模式 ingestion 驗證（月營收/季報/股利三表寫入）。

以隔離 DB 跑完整 ingestion（mcp 模式），確認 monthly_revenue /
quarterly_financials / dividends 三表正常寫入且 pipeline_log source 標註正確。

用法：
  MCP_SERVER_PATH=~/Projects/tw-quant-mcp/bin/tw-quant-mcp \
    .venv/bin/python scripts/verify_t022_s5.py
"""
import os
import sys
import tempfile
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from tw_quant_signal.ingestion import IngestionEngine


def main() -> int:
    print("=== T022 S5 — mcp 模式三表寫入驗證 ===")
    os.environ["TW_QUANT_DATA_PROVIDER"] = "mcp"
    db_path = tempfile.mktemp(suffix=".db")

    import importlib

    import tw_quant_signal.config as config_mod
    importlib.reload(config_mod)
    import tw_quant_signal.db as db_mod
    importlib.reload(db_mod)

    db = db_mod.SignalDB(db_path)
    db.init_db()
    engine = IngestionEngine(db)
    status = engine.run_daily(date.today().isoformat())
    for k, v in status.items():
        print(f"  [{v}] {k}")

    # 檢查三表
    print("\n=== 三表寫入檢查 ===")
    with db.connect() as conn:
        for table in ["monthly_revenue", "quarterly_financials", "dividends"]:
            n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"  {table}: {n} rows")
        print("\n--- pipeline_log (source 標註) ---")
        rows = conn.execute(
            "SELECT task, status, message FROM pipeline_log WHERE task IN "
            "('monthly_revenue','quarterly_financials','dividends') ORDER BY id"
        ).fetchall()
        for task, status_, msg in rows:
            print(f"  {task}: {status_} {msg}")

    # 內容樣本
    print("\n--- monthly_revenue 樣本 ---")
    with db.connect() as conn:
        for r in conn.execute(
            "SELECT stock_id, year_month, revenue, mom_change, yoy_change "
            "FROM monthly_revenue ORDER BY year_month DESC LIMIT 4"
        ).fetchall():
            print("  ", r)
    print("--- dividends 樣本 ---")
    with db.connect() as conn:
        for r in conn.execute(
            "SELECT stock_id, year, cash_dividend, stock_dividend FROM dividends "
            "ORDER BY year DESC LIMIT 4"
        ).fetchall():
            print("  ", r)
    print("--- quarterly_financials 樣本 ---")
    with db.connect() as conn:
        for r in conn.execute(
            "SELECT stock_id, fiscal_quarter, eps, revenue, gross_margin, roe, roa "
            "FROM quarterly_financials ORDER BY fiscal_quarter DESC LIMIT 4"
        ).fetchall():
            print("  ", r)

    # 判定：三表皆有資料即 PASS（無資料可能因 watch stocks 全 fallback）
    with db.connect() as conn:
        n_mr = conn.execute("SELECT COUNT(*) FROM monthly_revenue").fetchone()[0]
        n_qf = conn.execute("SELECT COUNT(*) FROM quarterly_financials").fetchone()[0]
        n_dv = conn.execute("SELECT COUNT(*) FROM dividends").fetchone()[0]
    ok = n_mr > 0 and n_qf > 0 and n_dv > 0
    print(f"\n{'PASS' if ok else 'FAIL'} (monthly={n_mr}, financials={n_qf}, dividends={n_dv})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
