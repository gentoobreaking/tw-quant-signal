"""T023 — MCP Validation & Fallback 測試腳本。

覆蓋：
- S1: 三種模式測試（direct / mcp / hybrid）
- S2: 資料一致性比對
- S3: MCP fallback 機制測試
- S4: 效能基準比對

輸出：data/reports/mcp_validation_{date}.md
"""

import os
import sys
import time
import json
import logging
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tw_quant_signal.db import SignalDB
from tw_quant_signal.provider import create_data_provider
from tw_quant_signal.ingestion import IngestionEngine
from tw_quant_signal.features import compute_all_features
from tw_quant_signal.rules import compute_rule_signals, _aggregate_rules
from tw_quant_signal.health_check import compute_health_check
from tw_quant_signal.risk_manager import compute_risk_metrics

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

REPORT_DIR = Path("data/reports")
REPORT_DIR.mkdir(parents=True, exist_ok=True)

RUN_DATE = date.today().isoformat()
REPORT_PATH = REPORT_DIR / f"mcp_validation_{RUN_DATE}.md"


def run_pipeline_with_provider(provider_mode: str) -> dict:
    """用指定 provider 執行完整 pipeline，回傳關鍵表格資料供比對。"""
    os.environ["TW_QUANT_DATA_PROVIDER"] = provider_mode

    db = SignalDB()
    db.init_db()

    engine = IngestionEngine(db, provider=create_data_provider())
    status = engine.run_daily(RUN_DATE)

    # 取得關鍵表格資料
    with db.connect() as conn:
        # daily_prices 最後 5 日
        prices = conn.execute(
            """SELECT stock_id, trade_date, open, high, low, close, volume, amount
               FROM daily_prices
               WHERE stock_id IN ('2330', '0050', '2308')
               ORDER BY trade_date DESC, stock_id
               LIMIT 15"""
        ).fetchall()

        # institutional_flows 最後 5 日
        inst = conn.execute(
            """SELECT stock_id, trade_date, foreign_investors_net, sity_investors_net,
                      dealer_net, dealer_proprietary_net, dealer_hedge_net, total_net
               FROM institutional_flows
               WHERE stock_id IN ('2330', '0050', '2308')
               ORDER BY trade_date DESC, stock_id
               LIMIT 15"""
        ).fetchall()

        # monthly_revenue 最後 3 筆
        revenue = conn.execute(
            """SELECT stock_id, year_month, revenue, mom_change, yoy_change
               FROM monthly_revenue
               WHERE stock_id IN ('2330', '0050', '2308')
               ORDER BY year_month DESC, stock_id
               LIMIT 9"""
        ).fetchall()

        # features 最後 1 筆
        features = conn.execute(
            """SELECT stock_id, trade_date, features_json
               FROM features
               WHERE stock_id IN ('2330', '0050', '2308')
               ORDER BY trade_date DESC, stock_id
               LIMIT 3"""
        ).fetchall()

        # rule_signals 最後 1 筆
        rules = conn.execute(
            """SELECT stock_id, trade_date, triggered_rules_json
               FROM rule_signals
               WHERE stock_id IN ('2330', '0050', '2308')
               ORDER BY trade_date DESC, stock_id
               LIMIT 3"""
        ).fetchall()

        # health_scores 最後 1 筆
        health = conn.execute(
            """SELECT stock_id, trade_date, d1, d2, d3, d4, total_score
               FROM health_scores
               WHERE stock_id IN ('2330', '0050', '2308')
               ORDER BY trade_date DESC, stock_id
               LIMIT 3"""
        ).fetchall()

    return {
        "status": status,
        "daily_prices": [dict(r) for r in prices],
        "institutional_flows": [dict(r) for r in inst],
        "monthly_revenue": [dict(r) for r in revenue],
        "features": [dict(r) for r in features],
        "rule_signals": [dict(r) for r in rules],
        "health_scores": [dict(r) for r in health],
    }


def compare_data(mode1: str, data1: dict, mode2: str, data2: dict) -> list[str]:
    """比對兩種模式的資料，回傳差異訊息列表。"""
    diffs = []

    for key in ["daily_prices", "institutional_flows", "monthly_revenue",
                "features", "rule_signals", "health_scores"]:
        d1 = data1.get(key, [])
        d2 = data2.get(key, [])

        if len(d1) != len(d2):
            diffs.append(f"  {key}: 筆數不同 ({mode1}={len(d1)} vs {mode2}={len(d2)})")
            continue

        for i, (r1, r2) in enumerate(zip(d1, d2)):
            # 移除不比對的欄位
            r1_clean = {k: v for k, v in r1.items() if k not in ("id", "_rowid")}
            r2_clean = {k: v for k, v in r2.items() if k not in ("id", "_rowid")}

            if r1_clean != r2_clean:
                diffs.append(f"  {key}[{i}]: {r1_clean} != {r2_clean}")

    return diffs


def test_fallback_scenarios() -> list[str]:
    """測試 S3: MCP fallback 機制。"""
    results = []

    # S3.1: MCP 完全連不上
    logger.info("Testing S3.1: MCP completely unavailable")
    try:
        from tw_quant_signal.provider.mcp_provider import McpDataProvider
        from tw_quant_signal.provider.mcp_client import McpConnectionError

        # 設定不存在的 server_path 強制失敗
        os.environ["MCP_SERVER_PATH"] = "/nonexistent/path/to/mcp"
        os.environ["TW_QUANT_DATA_PROVIDER"] = "mcp"

        db = SignalDB()
        db.init_db()
        engine = IngestionEngine(db, provider=create_data_provider())
        status = engine.run_daily(RUN_DATE)

        # 檢查 pipeline_log 是否有 fallback 記錄
        with db.connect() as conn:
            logs = conn.execute(
                "SELECT task, status, message FROM pipeline_log WHERE run_date=?",
                [RUN_DATE]
            ).fetchall()

        fallback_logged = any(
            "fallback" in (row[2] or "").lower() or "direct(fallback)" in (row[2] or "")
            for row in logs
        )
        # pipeline_ok 檢查所有任務是否都不是 fail（除了 skip）
        pipeline_ok = all(v != "fail" for v in status.values())

        if fallback_logged and pipeline_ok:
            results.append("✅ S3.1: MCP 完全連不上 → 自動降級 direct，pipeline status=ok")
        else:
            results.append(f"❌ S3.1: fallback_logged={fallback_logged}, pipeline_ok={pipeline_ok}")

    except Exception as e:
        results.append(f"❌ S3.1 測試異常: {e}")

    # S3.2: MCP 部分工具失敗（模擬 get_institutional_investors 失敗）
    logger.info("Testing S3.2: MCP partial tool failure")
    try:
        # 這裡需要 mock 或特殊設定，先記錄需實作
        results.append("⚠️ S3.2: 需在實際 mcp server 環境下測試部分工具失敗（目前標記需手動驗證）")
    except Exception as e:
        results.append(f"❌ S3.2 測試異常: {e}")

    # S3.3: MCP 慢回應（超時）
    logger.info("Testing S3.3: MCP timeout")
    try:
        os.environ["MCP_CALL_TIMEOUT"] = "1"  # 極短超時
        os.environ["TW_QUANT_DATA_PROVIDER"] = "mcp"

        db = SignalDB()
        db.init_db()
        engine = IngestionEngine(db, provider=create_data_provider())
        status = engine.run_daily(RUN_DATE)

        with db.connect() as conn:
            logs = conn.execute(
                "SELECT task, status, message FROM pipeline_log WHERE run_date=?",
                [RUN_DATE]
            ).fetchall()

        timeout_fallback = any(
            "timeout" in (row[2] or "").lower() or "fallback" in (row[2] or "").lower()
            for row in logs
        )
        pipeline_ok = all(v != "fail" for v in status.values())

        if timeout_fallback and pipeline_ok:
            results.append("✅ S3.3: MCP timeout → 自動降級，pipeline 未 crash")
        else:
            results.append(f"⚠️ S3.3: timeout_fallback={timeout_fallback}, pipeline_ok={pipeline_ok}")

    except Exception as e:
        results.append(f"❌ S3.3 測試異常: {e}")

    return results


def run_performance_benchmark() -> dict:
    """S4: 效能基準比對。"""
    results = {}

    for mode in ["direct", "mcp"]:
        logger.info(f"Benchmarking {mode} mode...")
        os.environ["TW_QUANT_DATA_PROVIDER"] = mode

        # 清理資料庫重新跑
        db_path = Path("data/signal_benchmark.db")
        if db_path.exists():
            db_path.unlink()

        os.environ["TW_QUANT_DB"] = str(db_path)

        start = time.time()
        db = SignalDB()
        db.init_db()
        engine = IngestionEngine(db, provider=create_data_provider())
        status = engine.run_daily(RUN_DATE)
        elapsed = time.time() - start

        results[mode] = {
            "total_time": round(elapsed, 2),
            "status": status,
        }
        logger.info(f"  {mode}: {elapsed:.2f}s")

    # 比對
    direct_time = results.get("direct", {}).get("total_time", 0)
    mcp_time = results.get("mcp", {}).get("total_time", 0)

    if direct_time > 0:
        ratio = mcp_time / direct_time
        results["comparison"] = {
            "ratio": round(ratio, 2),
            "target": "Ys ≤ Xs × 1.5",
            "pass": ratio <= 1.5,
        }
    else:
        results["comparison"] = {"error": "direct mode failed"}

    return results


def generate_report(
    mode_results: dict,
    diffs: list[str],
    fallback_results: list[str],
    perf_results: dict
) -> str:
    """產生驗證報告 Markdown。"""
    lines = [
        f"# T023 MCP Validation Report — {RUN_DATE}",
        "",
        "## 環境",
        f"- 日期: {RUN_DATE}",
        f"- 測試標的: 2330, 0050, 2308",
        "",
        "## S1: 三種模式 Pipeline 執行狀態",
        "",
        "| 模式 | Index | Stocks | Institutional | Indicators | Features | 總體 |",
        "|------|-------|--------|---------------|------------|----------|------|",
    ]

    for mode in ["direct", "mcp", "hybrid"]:
        if mode in mode_results:
            s = mode_results[mode]["status"]
            lines.append(
                f"| {mode} | {s.get('index','-')} | {s.get('stocks','-')} | "
                f"{s.get('institutional','-')} | {s.get('indicators','-')} | "
                f"{s.get('features','-')} | {'✅' if all(v=='ok' for v in s.values() if v!='skip') else '❌'} |"
            )
        else:
            lines.append(f"| {mode} | - | - | - | - | - | ❌ (未執行) |")

    lines.extend([
        "",
        "## S2: 資料一致性比對",
        "",
    ])

    if not diffs:
        lines.append("✅ **三種模式下所有關鍵表格資料完全一致**")
    else:
        lines.append("❌ **發現差異**：")
        for d in diffs:
            lines.append(f"- {d}")

    lines.extend([
        "",
        "## S3: MCP Fallback 機制測試",
        "",
    ])
    for r in fallback_results:
        lines.append(f"- {r}")

    lines.extend([
        "",
        "## S4: 效能基準比對",
        "",
        f"- direct 模式: {perf_results.get('direct', {}).get('total_time', 'N/A')}s",
        f"- mcp 模式: {perf_results.get('mcp', {}).get('total_time', 'N/A')}s",
    ])

    comp = perf_results.get("comparison", {})
    if "ratio" in comp:
        lines.append(f"- 比率 (mcp/direct): {comp['ratio']}x")
        lines.append(f"- 目標: {comp['target']}")
        lines.append(f"- 結果: {'✅ 通過' if comp['pass'] else '❌ 未達標'}")
    else:
        lines.append(f"- 比對: {comp.get('error', 'N/A')}")

    lines.extend([
        "",
        "## S5: Config 設定",
        "",
        "```json",
        json.dumps({
            "data_provider": {
                "mode": os.getenv("TW_QUANT_DATA_PROVIDER", "direct"),
                "mcp_server_path": os.getenv("MCP_SERVER_PATH", ""),
                "mcp_timeout_sec": float(os.getenv("MCP_CALL_TIMEOUT", "30")),
                "fallback_on_error": True
            }
        }, indent=2, ensure_ascii=False),
        "```",
        "",
        "## 結論",
        "",
        f"- 訊號輸出一致性: {'✅ 通過' if not diffs else '❌ 有差異'}",
        f"- Fallback 機制: {'✅ 通過' if all('✅' in r for r in fallback_results) else '⚠️ 部分需驗證'}",
        f"- 效能基準: {'✅ 通過' if comp.get('pass', False) else '❌ 未達標'}",
    ])

    return "\n".join(lines)


def main():
    """主程式：執行完整驗證流程。"""
    logger.info("=== T023 MCP Validation Started ===")

    mode_results = {}

    # S1: 三種模式測試
    for mode in ["direct", "mcp", "hybrid"]:
        logger.info(f"Running pipeline with {mode} mode...")
        try:
            mode_results[mode] = run_pipeline_with_provider(mode)
            logger.info(f"  {mode} completed: {mode_results[mode]['status']}")
        except Exception as e:
            logger.error(f"  {mode} failed: {e}")
            mode_results[mode] = {"status": {"error": str(e)}, "daily_prices": []}

    # S2: 資料一致性比對
    logger.info("Comparing data consistency...")
    diffs = []
    direct_data = mode_results.get("direct", {})
    mcp_data = mode_results.get("mcp", {})
    hybrid_data = mode_results.get("hybrid", {})

    if direct_data and mcp_data:
        diffs.extend(compare_data("direct", direct_data, "mcp", mcp_data))
    if direct_data and hybrid_data:
        diffs.extend(compare_data("direct", direct_data, "hybrid", hybrid_data))

    # S3: Fallback 測試
    logger.info("Testing fallback mechanisms...")
    fallback_results = test_fallback_scenarios()

    # S4: 效能基準
    logger.info("Running performance benchmark...")
    perf_results = run_performance_benchmark()

    # 產生報告
    report = generate_report(mode_results, diffs, fallback_results, perf_results)
    REPORT_PATH.write_text(report)
    logger.info(f"Report written to {REPORT_PATH}")

    # 印出摘要
    print("\n" + "="*60)
    print("T023 VALIDATION SUMMARY")
    print("="*60)
    print(f"Data consistency: {'PASS' if not diffs else 'FAIL'}")
    for d in diffs:
        print(f"  - {d}")
    print("\nFallback tests:")
    for r in fallback_results:
        print(f"  {r}")
    print(f"\nPerformance: mcp/direct = {perf_results.get('comparison', {}).get('ratio', 'N/A')}x")
    print(f"\nReport: {REPORT_PATH}")

    # 回傳退出碼
    all_pass = not diffs and all("✅" in r for r in fallback_results)
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())