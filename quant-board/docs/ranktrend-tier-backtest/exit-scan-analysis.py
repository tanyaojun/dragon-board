# -*- coding: utf-8 -*-
"""卖点扫描批次分析（阶段 A2/A4 归因 + 三窗判定卡读数）。

离线直读 MongoDB 轻量集合（backtest_trades / backtest_equity_curve），不经过
uvicorn 大 JSON 接口，也不解压 result 大 JSON——指标按 execution.py 生产口径
从 trades 精确重算：
- round-trip 分组 key=(entrySignalSnapshotId or entrySnapshotId, code)；
- winRate = round-trip netReturn>0 占比（share 4 位）；
- profitFactor = sum(profit>0)/abs(sum(profit<0))，无亏损 → None；
- tradeCount = round-trip 数；
- totalReturn/maxDrawdown 从 equity 曲线重算。
基线校验锚（阶段 0 冻结值）内建于脚本：重算与冻结值偏差超容差即报错退出，
不落盘误导性数字（harness 已知答案校验范式）。

输出（写本目录）：
- exit-scan-batch1-metrics.tsv         run 级指标 + wrxpf
- exit-scan-batch1-reason-buckets.tsv  run × 卖出 reason 分桶
- exit-scan-batch1-window-buckets.tsv  run × 标准窗口分桶
窗口边界 import backend.optimization.data_windows（B-202610 口径）：
FINAL(08-01~08-14) 冻结只报告不决策；oos2u 为未消费裁决读数（M3）。
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent
QB_ROOT = ROOT.parent.parent  # quant-board/
sys.path.insert(0, str(QB_ROOT))

from backend.optimization.data_windows import WINDOWS  # noqa: E402

import pymongo  # noqa: E402

# 用法：exit-scan-analysis.py [batch]  batch 默认 1；决定读哪个 manifest 与输出前缀
BATCH = sys.argv[1] if len(sys.argv) > 1 else "1"
MANIFEST = ROOT / f"exit-scan-batch{BATCH}-manifest.tsv"
OUT_METRICS = ROOT / f"exit-scan-batch{BATCH}-metrics.tsv"
OUT_REASON = ROOT / f"exit-scan-batch{BATCH}-reason-buckets.tsv"
OUT_WINDOW = ROOT / f"exit-scan-batch{BATCH}-window-buckets.tsv"

BASELINE_RUN_ID = "bt_8d451aab2e834c7e"
# 阶段 0 冻结基线（exit-rules-scan-plan.md 阶段 0 验收）
BASELINE_FROZEN = {
    "winRate": 0.3256,
    "profitFactor": 1.4818,
    "tradeCount": 43,
    "totalReturn": 0.0646,
    "maxDrawdown": -0.0846,
}
TOLERANCE = 0.002
INITIAL_CAPITAL = 1_000_000.0  # config 默认 initialCapital（见 config.py）
TRADE_PROJECTION = {
    "_id": 0,
    "code": 1,
    "name": 1,
    "reason": 1,
    "profit": 1,
    "netReturn": 1,
    "grossReturn": 1,
    "quantity": 1,
    "exitPrice": 1,
    "entryPrice": 1,
    "entryCostBasis": 1,
    "entrySignalSnapshotId": 1,
    "entrySnapshotId": 1,
    "entryTradingDate": 1,
    "exitTradingDate": 1,
    "holdingBars": 1,
    "candidateTier": 1,
}


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for line in (QB_ROOT / ".env.local").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip()
    return env


def read_manifest() -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    for line in MANIFEST.read_text(encoding="utf-8").splitlines()[1:]:
        parts = line.strip().split("\t")
        if len(parts) >= 3 and parts[2].startswith("bt_"):
            rows.append((parts[0], parts[1], parts[2]))
    return rows


def round_trips(trades: list[dict]) -> list[dict]:
    groups: dict[tuple[str, str], list[dict]] = {}
    for t in trades:
        key = (str(t.get("entrySignalSnapshotId") or t.get("entrySnapshotId") or ""), str(t.get("code") or ""))
        groups.setdefault(key, []).append(t)
    result = []
    for rows in groups.values():
        profit = sum(float(r.get("profit") or 0) for r in rows)
        entry_cost = sum(float(r.get("entryCostBasis") or 0) for r in rows)
        quantity = sum(int(r.get("quantity") or 0) for r in rows)
        exit_amount = sum(float(r.get("exitPrice") or 0) * int(r.get("quantity") or 0) for r in rows)
        net_return = profit / entry_cost if entry_cost else 0
        first, last = rows[0], rows[-1]
        exit_price = exit_amount / quantity if quantity else float(last.get("exitPrice") or 0)
        result.append({
            "code": first.get("code"),
            "name": first.get("name"),
            "reason": last.get("reason"),
            "profit": profit,
            "netReturn": net_return,
            "grossReturn": (exit_price - float(first.get("entryPrice") or 0)) / float(first.get("entryPrice") or 1),
            "entryTradingDate": first.get("entryTradingDate"),
            "holdingBars": max(int(r.get("holdingBars") or 0) for r in rows),
            "candidateTier": first.get("candidateTier"),
        })
    return result


def compute_metrics(trades: list[dict], equity: list[dict]) -> dict:
    rts = round_trips(trades)
    wins = [r for r in rts if r["netReturn"] > 0]
    profits = [r["profit"] for r in rts]
    gross_profit = sum(p for p in profits if p > 0)
    gross_loss = abs(sum(p for p in profits if p < 0))
    peak = equity[0]["equity"] if equity else 0
    drawdown = 0.0
    for point in equity:
        peak = max(peak, float(point["equity"]))
        if peak > 0:
            drawdown = min(drawdown, (float(point["equity"]) - peak) / peak)
    final_equity = float(equity[-1]["equity"]) if equity else INITIAL_CAPITAL
    return {
        "winRate": round(len(wins) / len(rts), 4) if rts else 0.0,
        "profitFactor": round(gross_profit / gross_loss, 4) if gross_loss > 0 else None,
        "tradeCount": len(rts),
        "exitSliceCount": len(trades),
        "totalReturn": round((final_equity - INITIAL_CAPITAL) / INITIAL_CAPITAL, 4) if equity else None,
        "maxDrawdown": round(drawdown, 4),
        "wrxpf": round((len(wins) / len(rts)) * (gross_profit / gross_loss), 4)
        if rts and gross_loss > 0 else None,
    }


def window_of(trading_date: str) -> str:
    d = str(trading_date or "")
    for name in ("decision", "final", "oos1", "oos2"):
        start, end = WINDOWS[name]
        if start <= d <= end:
            return name
    return "warmup" if d and d < WINDOWS["decision"][0] else "outside"


def bucket_rows(run_rows: list[tuple[str, str, str]], db) -> tuple[list[str], list[str], list[str], list[dict]]:
    metric_lines = ["param\tvalue\trun_id\twr\tpf\twrxpf\ttrades\texitSlices\ttotalReturn\tmaxDD"]
    reason_lines = ["run_id\tparam\tvalue\treason\tn\twinRate\tnetSum\tavgNet\tavgHold"]
    window_lines = ["run_id\tparam\tvalue\twindow\tn\twinRate\tpf\twrxpf\tnetSum\tnote"]
    checks: list[dict] = []
    for param, value, run_id in run_rows:
        trades = list(
            db["backtest_trades"].find({"backtestRunId": run_id}, TRADE_PROJECTION).sort([("sequence", 1)])
        )
        equity = list(
            db["backtest_equity_curve"].find({"backtestRunId": run_id}, {"_id": 0, "equity": 1}).sort([("sequence", 1)])
        )
        if not trades:
            raise SystemExit(f"no trades stored for {run_id}（fail-visible：拒绝以空数据出报告）")
        m = compute_metrics(trades, equity)
        metric_lines.append(
            f"{param}\t{value}\t{run_id}\t{m['winRate']}\t{m['profitFactor']}\t{m['wrxpf']}\t"
            f"{m['tradeCount']}\t{m['exitSliceCount']}\t{m['totalReturn']}\t{m['maxDrawdown']}"
        )
        if run_id == BASELINE_RUN_ID:
            checks = [
                {"metric": k, "recomputed": m[k], "frozen": v}
                for k, v in BASELINE_FROZEN.items()
                if m[k] is None or abs(float(m[k]) - float(v)) > TOLERANCE
            ]
            if checks:
                print("BASELINE MISMATCH (fail-visible):", checks)
                raise SystemExit(2)

        # reason 分桶（按卖出片段逐笔，reason 是片段级触发原因）
        by_reason: dict[str, dict] = defaultdict(lambda: {"n": 0, "win": 0, "net": 0.0, "hold": 0})
        # 窗口分桶（round-trip 级，netReturn 与 win 判定同生产口径）
        by_window: dict[str, dict] = defaultdict(lambda: {"n": 0, "win": 0, "gp": 0.0, "gl": 0.0, "net": 0.0})
        for t in trades:
            reason = str(t.get("reason") or "unknown")
            net = float(t.get("netReturn") or 0)
            b = by_reason[reason]
            b["n"] += 1
            b["win"] += 1 if net > 0 else 0
            b["net"] += net
            b["hold"] += int(t.get("holdingBars") or 0)
        for r in round_trips(trades):
            w = window_of(r["entryTradingDate"])
            wb = by_window[w]
            wb["n"] += 1
            wb["win"] += 1 if r["netReturn"] > 0 else 0
            wb["net"] += r["netReturn"]
            if r["profit"] > 0:
                wb["gp"] += r["profit"]
            else:
                wb["gl"] += abs(r["profit"])
        for reason, b in sorted(by_reason.items(), key=lambda kv: -kv[1]["n"]):
            n = b["n"]
            reason_lines.append(
                f"{run_id}\t{param}\t{value}\t{reason}\t{n}\t{b['win'] / n:.4f}\t{b['net']:.4f}\t"
                f"{b['net'] / n:.4f}\t{b['hold'] / n:.2f}"
            )
        for wname, b in sorted(by_window.items()):
            n = b["n"]
            pf_w = round(b["gp"] / b["gl"], 4) if b["gl"] > 0 else None
            wr_w = b["win"] / n
            note = "insufficient<30" if n < 30 else "n>=30"
            if wname == "final":
                note += "; frozen-report-only"
            if wname == "oos2":
                note += "; consumed-frames-discount"
            if wname == "warmup":
                note += "; pre-decision-warmup"
            window_lines.append(
                f"{run_id}\t{param}\t{value}\t{wname}\t{n}\t{wr_w:.4f}\t{'' if pf_w is None else pf_w}\t"
                f"{'' if pf_w is None else round(wr_w * pf_w, 4)}\t{b['net']:.4f}\t{note}"
            )
        print(f"analyzed: {param}={value} {run_id} trades={len(trades)} rts={m['tradeCount']}")
    return metric_lines, reason_lines, window_lines, checks


def main() -> None:
    env = load_env()
    client = pymongo.MongoClient(
        env.get("QUANT_BOARD_MONGODB_URI", "mongodb://127.0.0.1:27017"),
        serverSelectionTimeoutMS=5000,
    )
    db = client[env.get("QUANT_BOARD_MONGODB_DATABASE", "dragon_board_quant")]

    rows = read_manifest()
    if BASELINE_RUN_ID not in {r for _, _, r in rows}:
        rows.insert(0, ("baseline", "default", BASELINE_RUN_ID))

    metric_lines, reason_lines, window_lines, _ = bucket_rows(rows, db)
    OUT_METRICS.write_text("\n".join(metric_lines) + "\n", encoding="utf-8")
    OUT_REASON.write_text("\n".join(reason_lines) + "\n", encoding="utf-8")
    OUT_WINDOW.write_text("\n".join(window_lines) + "\n", encoding="utf-8")
    print(f"written: {OUT_METRICS.name}, {OUT_REASON.name}, {OUT_WINDOW.name}")


if __name__ == "__main__":
    main()
