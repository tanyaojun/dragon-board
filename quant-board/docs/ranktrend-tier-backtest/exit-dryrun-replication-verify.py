# -*- coding: utf-8 -*-
"""dry-run 全窗复现验证：--dry-run 响应摘要 vs 已落库锚 run 的 trades/equity 逐位一致判定。

背景（2026-09-23 引擎提速立项）：全窗持久化 run 在内存紧张时会死在 result_json
大序列化（MemoryError 实证），因此优化后全窗比对改用 dry-run 响应体（全量
trades/equityCurve 随响应返回，无 120 条截断）对照 Mongo 锚 run 明细。

用法：python exit-dryrun-replication-verify.py <summary.json> <anchor_run_id>
一致性判据：
- dry trades[i] 与 backtest_trades 锚文档（去 backtestRunId/sequence，sequence 排序）全字段逐位一致；
- dry equityCurve[i] 与 backtest_equity_curve 锚文档（去 backtestRunId/sequence）全字段逐位一致。
任何差异打印首处差异并退出码 1（fail-visible）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

QB_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(QB_ROOT))

import pymongo  # noqa: E402


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for line in (QB_ROOT / ".env.local").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip()
    return env


def first_diff(a, b, prefix="$"):
    # Mongo bson Int64 与 JSON int 数值相等视为一致（同值同宽）；bool 除外
    if isinstance(a, bool) or isinstance(b, bool):
        if type(a) is not type(b) or a != b:
            return f"{prefix}: dry={a!r} vs anchor={b!r}"
        return None
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return None if a == b else f"{prefix}: dry={a!r} vs anchor={b!r}"
    if type(a) is not type(b):
        return f"{prefix}: type {type(a).__name__} vs {type(b).__name__}"
    if isinstance(a, dict):
        for key in sorted(set(a) | set(b)):
            if key not in a:
                return f"{prefix}.{key}: dry 缺键"
            if key not in b:
                return f"{prefix}.{key}: 锚缺键"
            sub = first_diff(a[key], b[key], f"{prefix}.{key}")
            if sub:
                return sub
        return None
    if isinstance(a, list):
        if len(a) != len(b):
            return f"{prefix}: len {len(a)} vs {len(b)}"
        for idx, (x, y) in enumerate(zip(a, b)):
            sub = first_diff(x, y, f"{prefix}[{idx}]")
            if sub:
                return sub
        return None
    return None if a == b else f"{prefix}: dry={a!r} vs anchor={b!r}"


def main() -> None:
    summary_path, run_anchor = sys.argv[1], sys.argv[2]
    summary = json.loads(Path(summary_path).read_text(encoding="utf-8"))
    if not summary.get("dryRun"):
        print("MISMATCH: 传入的 summary 缺少 dryRun=true 标记——请用 --dry-run runner 产出的摘要文件")
        raise SystemExit(1)
    env = load_env()
    client = pymongo.MongoClient(env.get("QUANT_BOARD_MONGODB_URI", "mongodb://127.0.0.1:27017"))
    db = client[env.get("QUANT_BOARD_MONGODB_DATABASE", "dragon_board_quant")]

    trades_anchor = [
        {k: v for k, v in row.items() if k not in ("backtestRunId", "sequence")}
        for row in db["backtest_trades"].find({"backtestRunId": run_anchor}, {"_id": 0}).sort([("sequence", 1)])
    ]
    trades_dry = summary.get("trades") or []
    if len(trades_anchor) != len(trades_dry):
        print(f"MISMATCH: trades count anchor={len(trades_anchor)} dry={len(trades_dry)}")
        raise SystemExit(1)
    for i, (ta, td) in enumerate(zip(trades_anchor, trades_dry)):
        diff = first_diff(ta, td, f"trades[{i}]")
        if diff:
            print(f"MISMATCH {diff}")
            raise SystemExit(1)

    equity_anchor = [
        {k: v for k, v in row.items() if k not in ("backtestRunId", "sequence")}
        for row in db["backtest_equity_curve"].find({"backtestRunId": run_anchor}, {"_id": 0}).sort([("sequence", 1)])
    ]
    equity_dry = summary.get("equityCurve") or []
    if len(equity_anchor) != len(equity_dry):
        print(f"MISMATCH: equity count anchor={len(equity_anchor)} dry={len(equity_dry)}")
        raise SystemExit(1)
    for i, (ea, ed) in enumerate(zip(equity_anchor, equity_dry)):
        diff = first_diff(ea, ed, f"equity[{i}]")
        if diff:
            print(f"MISMATCH {diff}")
            raise SystemExit(1)

    print(f"IDENTICAL: {len(trades_dry)} trades + {len(equity_dry)} equity points 逐位一致（dry-run 响应 vs 锚 run）")
    print(f"summary={summary_path} == anchor={run_anchor} —— 优化后全窗复现验证通过")


if __name__ == "__main__":
    main()
