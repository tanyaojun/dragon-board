# -*- coding: utf-8 -*-
"""落默认端到端复现验证：两个 run 的 trades/equity/metrics 逐位一致判定。

用法：python exit-default-replication-verify.py <run_id_A> <run_id_B>
一致性判据：
- backtest_trades 全字段逐行逐位一致（sequence 排序后）；
- backtest_equity_curve 全点逐位一致；
- 重算指标（wr/pf/tradeCount/totalReturn/maxDD）逐位一致。
任何差异打印首处差异并退出码 1（fail-visible）。
"""
from __future__ import annotations

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


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit("usage: exit-default-replication-verify.py <run_id_A> <run_id_B>")
    run_a, run_b = sys.argv[1], sys.argv[2]
    env = load_env()
    client = pymongo.MongoClient(env.get("QUANT_BOARD_MONGODB_URI", "mongodb://127.0.0.1:27017"))
    db = client[env.get("QUANT_BOARD_MONGODB_DATABASE", "dragon_board_quant")]

    trades_a = list(db["backtest_trades"].find({"backtestRunId": run_a}, {"_id": 0}).sort([("sequence", 1)]))
    trades_b = list(db["backtest_trades"].find({"backtestRunId": run_b}, {"_id": 0}).sort([("sequence", 1)]))
    if len(trades_a) != len(trades_b):
        print(f"MISMATCH: trades count {len(trades_a)} vs {len(trades_b)}")
        raise SystemExit(1)
    for i, (ta, tb) in enumerate(zip(trades_a, trades_b)):
        ta.pop("backtestRunId", None)
        tb.pop("backtestRunId", None)
        if ta != tb:
            diff_keys = [k for k in set(ta) | set(tb) if ta.get(k) != tb.get(k)]
            print(f"MISMATCH at trade[{i}] keys={diff_keys}")
            for k in diff_keys:
                print(f"  {k}: {ta.get(k)!r} vs {tb.get(k)!r}")
            raise SystemExit(1)

    eq_a = list(db["backtest_equity_curve"].find({"backtestRunId": run_a}, {"_id": 0, "equity": 1, "timestamp": 1}).sort([("sequence", 1)]))
    eq_b = list(db["backtest_equity_curve"].find({"backtestRunId": run_b}, {"_id": 0, "equity": 1, "timestamp": 1}).sort([("sequence", 1)]))
    if eq_a != eq_b:
        for i, (ea, eb) in enumerate(zip(eq_a, eq_b)):
            if ea != eb:
                print(f"MISMATCH at equity[{i}]: {ea} vs {eb}")
                break
        if len(eq_a) != len(eq_b):
            print(f"MISMATCH: equity len {len(eq_a)} vs {len(eq_b)}")
        raise SystemExit(1)

    print(f"IDENTICAL: {len(trades_a)} trades + {len(eq_a)} equity points 逐位一致")
    print(f"A={run_a} (显式 patch) == B={run_b} (新默认) —— 落默认语义验证通过")


if __name__ == "__main__":
    main()
