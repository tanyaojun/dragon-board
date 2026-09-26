"""Phase R3：轮动补涨策略变体对照回测 runner（设计文档 §6.1，第四轮裁决口径）。

三变体同一回测窗（theme_rotation 基线 / theme_rotation_chase SG 驱动 /
theme_state_hybrid 状态门控）逐个调用 BacktestService.run_theme_trend（串行、
单进程、无参数扫描），输出：
  - 三变体回测指标对照（totalReturn/maxDrawdown/winRate/tradeCount/profitFactor）
  - SG 触发分布（sg1/sg2/sg3 触发日数与高频题材）
  - hybrid 门控日分布（引擎 mainline 日 vs 补涨日）
  - trades 按 market_phase × Top1 rotationState × headStable 分层收益
    （regime 上下文消费 rotation/regime.py 引擎权威口径 + top1_streaks）

fail-visible：状态组样本不足（n<3）如实输出 insufficient；trades 为空输出空组
计数 0（真实 0 笔交易，非伪装缺失）；不写业务库（回测 run 记录属回测主链正常产物）。

用法（非交易时段运行）：
  cd quant-board
  .\\.venv\\Scripts\\python.exe -m backend.operations.diagnose_theme_r3_variants
      [--dataset dragonboard_live] [--start 2026-07-06] [--end 2026-09-24]
      [--seed 20260430] [--out data/reports/theme-r3-variants.json]
"""

from __future__ import annotations

import argparse
import gc
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.analysis.theme.rotation.regime import (
    DEFAULT_HEAD_STABLE_MIN_DAYS,
    rotation_state_context,
    top1_streaks,
)
from backend.data.repositories.repository_factory import create_repository
from backend.services import BacktestService
from backend.services.backtest_service import _close_slot_rows_by_day

VARIANTS = ("theme_rotation", "theme_rotation_chase", "theme_state_hybrid")


def load_close_rank_top1(repo: Any, dataset_id: str, start: str, end: str) -> dict[str, str | None]:
    """daily 收盘横截面 rank Top1 题材序列（R1 锚点口径，缺失日 None）。"""
    res = repo.list_snapshot_sector_rows(
        dataset_id, start_date=start, end_date=end,
        snapshot_type="daily", entity_type="hot_theme", sort="asc",
    )
    by_day: dict[str, list[dict[str, Any]]] = {}
    for d, rows in _close_slot_rows_by_day(res.get("rows") or []).items():
        by_day[d] = rows
    top1: dict[str, str | None] = {}
    for d, rows in by_day.items():
        ranked = sorted(
            (r for r in rows if isinstance(r.get("rank"), int)),
            key=lambda r: r["rank"],
        )
        top1[d] = str(ranked[0].get("entityName") or "") or None if ranked else None
    return top1


def load_regime_inputs(
    repo: Any, dataset_id: str, start: str, end: str, days: list[str]
) -> tuple[dict[str, str | None], dict[str, str | None], dict[str, str | None], list[str]]:
    """half_hour 15:00 帧 → (Top1 rotationState 序列, marketPhase 序列, mainLines 有无, qualityFlags)。"""
    frames = repo.load_frame_bundles(dataset_id, snapshot_type="half_hour", start_date=start, end_date=end)
    top1_state: dict[str, str | None] = {}
    phase_by_day: dict[str, str | None] = {}
    mainlines_nonempty: dict[str, str | None] = {}
    quality_flags: list[str] = []
    for frame in frames:
        if str(frame.get("slotTime")) != "15:00":
            continue
        d = str(frame.get("tradingDate") or "")
        rs = frame.get("rotationSummary") or {}
        phase_by_day[d] = str(rs.get("marketPhase") or "") or None
        ml = rs.get("mainLines")
        mainlines_nonempty[d] = "nonempty" if isinstance(ml, list) and ml else ("empty" if isinstance(ml, list) else None)
        for row in frame.get("entities") or []:
            if not isinstance(row, dict) or str(row.get("entityType") or "") == "rotation_main_line":
                continue
            state = str(row.get("rotationState") or "") or None
            if state is None:
                continue
            top1_state.setdefault(d, {})[str(row.get("entityName") or "")] = state
    missing = [d for d in days if d not in phase_by_day]
    if missing:
        quality_flags.append(f"missing_15h_frame_days:{len(missing)}")
    return top1_state, phase_by_day, mainlines_nonempty, quality_flags


def _collect(trades: list[dict[str, Any]], key_fn, bucket: dict[str, dict[str, Any]]) -> None:
    for trade in trades:
        ret = trade.get("netReturn")
        if not isinstance(ret, (int, float)):
            continue
        key = key_fn(trade)
        item = bucket.setdefault(
            str(key),
            {"n": 0, "netReturnSum": 0.0, "wins": 0, "returns": []},
        )
        item["n"] += 1
        item["netReturnSum"] += float(ret)
        item["wins"] += 1 if float(ret) > 0 else 0
        item["returns"].append(round(float(ret), 6))


def _finalize_bucket(bucket: dict[str, dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, item in bucket.items():
        n = item["n"]
        mean = item["netReturnSum"] / n if n else 0.0
        out[key] = {
            "n": n,
            "avgNetReturn": round(mean, 6),
            "winRate": round(item["wins"] / n, 4) if n else None,
            "status": "ok" if n >= 3 else "insufficient_sample",
        }
    return out


def summarize_trades(
    trades: list[dict[str, Any]],
    phase_by_day: dict[str, str | None],
    ctx_by_day: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if not trades:
        return {"status": "no_trades", "byMarketPhase": {}, "byTop1RotationState": {}, "byHeadStable": {}}
    phase_bucket: dict[str, dict[str, Any]] = {}
    state_bucket: dict[str, dict[str, Any]] = {}
    stable_bucket: dict[str, dict[str, Any]] = {}
    _collect(trades, lambda t: phase_by_day.get(str(t.get("entryTradingDate") or "")), phase_bucket)
    _collect(
        trades,
        lambda t: (ctx_by_day.get(str(t.get("entryTradingDate") or "")) or {}).get("rotationState"),
        state_bucket,
    )
    _collect(
        trades,
        lambda t: (ctx_by_day.get(str(t.get("entryTradingDate") or "")) or {}).get("headStable"),
        stable_bucket,
    )
    return {
        "status": "ok",
        "tradeCount": len(trades),
        "byMarketPhase": _finalize_bucket(phase_bucket),
        "byTop1RotationState": _finalize_bucket(state_bucket),
        "byHeadStable": _finalize_bucket(stable_bucket),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase R3 变体对照回测 runner")
    parser.add_argument("--dataset", default="dragonboard_live")
    parser.add_argument("--start", default="2026-07-06")
    parser.add_argument("--end", default="2026-09-24")
    parser.add_argument("--seed", type=int, default=20260430)
    parser.add_argument(
        "--out", default="data/reports/theme-r3-variants.json",
    )
    args = parser.parse_args()

    repo = create_repository(None)
    svc = BacktestService(None)

    report: dict[str, Any] = {
        "meta": {
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "dataset": args.dataset,
            "window": {"start": args.start, "end": args.end},
            "randomSeed": args.seed,
            "variants": list(VARIANTS),
            "headStableMinDays": DEFAULT_HEAD_STABLE_MIN_DAYS,
            "mainlineSource": "rotationSummary.mainLines (half_hour 15:00, engine mainline口径, 2026-09-26 裁决)",
        },
        "variants": {},
        "sgTriggerStats": {},
        "hybridGateStats": {},
        "tradeRegimeSummary": {},
        "qualityFlags": [],
    }

    top1_by_day = load_close_rank_top1(repo, args.dataset, args.start, args.end)
    streaks = top1_streaks(top1_by_day)
    top1_state, phase_by_day, mainlines_nonempty, quality_flags = load_regime_inputs(
        repo, args.dataset, args.start, args.end, sorted(top1_by_day)
    )
    report["qualityFlags"].extend(quality_flags)
    ctx_by_day: dict[str, dict[str, Any]] = {}
    for d in sorted(top1_by_day):
        name = top1_by_day.get(d)
        ctx = rotation_state_context(
            (top1_state.get(d) or {}).get(name) if name else None,
            phase_by_day.get(d),
            streaks.get(d),
        )
        if name is None:
            ctx["qualityFlags"].append("missing_top1_theme")
        ctx_by_day[d] = ctx
    report["regimeDays"] = {
        d: {**ctx, "top1Theme": top1_by_day.get(d)} for d, ctx in sorted(ctx_by_day.items())
    }

    for variant in VARIANTS:
        gc.collect()
        payload = {
            "dataset_id": args.dataset,
            "snapshot_type": "half_hour",
            "strategy_name": variant,
            "random_seed": args.seed,
        }
        try:
            result = svc.run_theme_trend(payload)
        except Exception as exc:  # noqa: BLE001 —— 变体失败不阻断其余变体（fail-visible）
            report["variants"][variant] = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
            continue
        simulation = result.get("tradeSimulation") or {}
        metrics = {
            "status": "ok",
            "runId": result.get("runId"),
            "totalReturn": result.get("totalReturn"),
            "realizedReturn": result.get("realizedReturn"),
            "maxDrawdown": result.get("maxDrawdown"),
            "winRate": result.get("winRate"),
            "tradeCount": result.get("tradeCount"),
            "profitFactor": simulation.get("profitFactor"),
            "executionSignalCount": result.get("executionSignalCount"),
        }
        report["variants"][variant] = metrics
        trades = simulation.get("roundTripTrades") or []
        report["tradeRegimeSummary"][variant] = summarize_trades(trades, phase_by_day, ctx_by_day)

    # SG 触发分布与 hybrid 门控统计（复用 service 同一预计算实现，避免第二事实源）
    frames = repo.load_frame_bundles(args.dataset, snapshot_type="half_hour", start_date=args.start, end_date=args.end)
    gc.collect()
    sg_inputs = svc._theme_sg_inputs(args.dataset, frames)  # noqa: SLF001 —— 诊断 runner 消费同一实现
    report["qualityFlags"].extend(sg_inputs.get("qualityFlags") or [])
    trigger_days: dict[str, set[str]] = {"sg1": set(), "sg2": set(), "sg3": set()}
    theme_hits: dict[str, Counter] = {name: Counter() for name in trigger_days}
    for theme, per_day in (sg_inputs.get("sgFlags") or {}).items():
        for d, entry in per_day.items():
            for name in trigger_days:
                if entry.get(name) is True:
                    trigger_days[name].add(d)
                    theme_hits[name][theme] += 1
    report["sgTriggerStats"] = {
        name: {
            "triggerDayCount": len(days),
            "topThemes": [{"theme": t, "hits": n} for t, n in theme_hits[name].most_common(10)],
        }
        for name, days in trigger_days.items()
    }
    gate_counter = Counter(mainlines_nonempty.get(d) for d in sorted(top1_by_day))
    report["hybridGateStats"] = {
        "mainlineNonemptyDays": gate_counter.get("nonempty", 0),
        "mainlineEmptyDays": gate_counter.get("empty", 0),
        "mainlineMissingDays": gate_counter.get(None, 0),
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    print(f"report written: {out_path}")
    for variant in VARIANTS:
        v = report["variants"].get(variant) or {}
        if v.get("status") == "ok":
            print(
                f"{variant}: total={v.get('totalReturn')} mdd={v.get('maxDrawdown')} "
                f"win={v.get('winRate')} trades={v.get('tradeCount')} pf={v.get('profitFactor')}"
            )
        else:
            print(f"{variant}: {v.get('status')} {v.get('error', '')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
