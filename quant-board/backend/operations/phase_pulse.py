# -*- coding: utf-8 -*-
"""M3 盘面脉拍（phase pulse）：当月至今相位×交易快照，挂账即数据不靠记忆。

用法（quant-board 目录，独立进程，资源纪律=隔离 CLI）：
  ./.venv/Scripts/python.exe -m backend.operations.phase_pulse --month 2026-10

流程：warmup 前导帧 + 当月 frames → BacktestService.run_ranktrend（dryRun，默认栈
gate OFF 基线）→ 按当月 EOD 同日定相切片（与时间线口径一致）→ 北极星机械线 →
phase_monitor 集合 kind=pulse（前端"本月至今"卡数据源）+ 本地 JSON。
样本纪律：月内笔数少（尤其月初），读数仅方向参考，报告携带 sampleNote。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.core.backtest.execution import BAND_TAGS, band_of_score
from backend.operations.phase_northstar import equity_phase_slices, evaluate_northstar, worst_drawdown
from backend.operations.phase_trade_slice import round_trips_of, slice_trades

PULSE_THRESHOLD = 60.0  # 口径源=phase_label_run CANDIDATES sentiment_2b（2026-10-01 章程 Q1：边界 50→60）

# 分带用户展示名（键=引擎 BAND_TAGS，只管展示名不管归类——归类一律走 band_of_score 单一事实源）
PULSE_BAND_LABELS = {
    "冷10-40": ("低温期", "10-40"),
    "弱势40-60": ("弱势期", "40-60"),
    "强60-80": ("高温期", "60-80"),
    "极热≥80": ("极热期", "≥80"),
}


def build_pulse_report(
    summary: dict,
    eod_scores: dict[str, float | None],
    month: str,
    *,
    full_window: dict | None = None,
) -> dict:
    """当月切片纯函数：roundTrip 交易 + equity 曲线按当月 EOD 同日定相切 northstar 读数。"""
    trades = [t for t in round_trips_of(summary)
              if str(t.get("entryTradingDate") or "").startswith(month)]
    equity = [pt for pt in (summary.get("equityCurve") or [])
              if str(pt.get("tradingDate") or "").startswith(month)]
    daily = {d: phase for d, s in eod_scores.items()
             if d.startswith(month)
             for phase in [_phase_of(s)]}
    by_phase = slice_trades(trades, daily, "phase")
    # 稳定键：空桶补零读数（前端月卡固定读 offense/defense 两键；evaluate 对空桶产 pass=False）
    for bucket in ("offense", "defense"):
        by_phase.setdefault(bucket, {
            "trades": 0, "missingNetReturn": 0, "winRate": None, "profitFactor": None,
            "wrxpf": None, "sumNetReturn": None, "maxSingleLoss": None,
        })
    slices = equity_phase_slices(equity, daily)
    full = full_window or {
        "maxDD": (lambda eq: round(worst_drawdown(eq), 4) if len(eq) >= 2 else None)(
            [float(pt.get("equity") or 0.0) for pt in equity]),
        "segReturn": (lambda eq: round(eq[-1] / eq[0] - 1, 4) if len(eq) >= 2 else None)(
            [float(pt.get("equity") or 0.0) for pt in equity]),
    }
    return {
        "month": month,
        "tradeCount": len(trades),
        "sampleNote": "月内笔数少，读数仅方向参考（M3 脉拍非验收）",
        "eodDays": sum(1 for d in eod_scores if d.startswith(month)),
        "byPhase": by_phase,
        "equitySlices": slices,
        "northstar": evaluate_northstar(by_phase, slices, full),
        "fullWindow": full,
    }


def attribution_stats(trades: list[dict]) -> dict:
    """SP1 归因段（章程 T2）：roundTrip 交易的 entryPhase 汇总（fail-visible：缺失计数不静默）；
    SP2-T3 扩展：byPhase 分相计数 + rebalanceCount（相位调仓清仓笔数，reason 前缀口径）。
    SP4-T4（评审 P1-1）：jev 源交易的 prevScore 按设计置空（分数轴不存在）——按 phaseLabel
    计入 byPhase，并新增 sourceAttribution {direct, fallback, unknown} 分源计数，不再误计 missing。"""
    by_band: dict[str, dict] = {}
    by_phase: dict[str, int] = {}
    available = 0
    missing = 0
    rebalance = 0
    source_attribution = {"direct": 0, "fallback": 0, "unknown": 0}
    for t in trades:
        if str(t.get("reason") or "").startswith("相位调仓"):
            rebalance += 1
        ep = t.get("entryPhase") if isinstance(t.get("entryPhase"), dict) else None
        if not isinstance(ep, dict):
            missing += 1
            continue
        if str(ep.get("source") or "").startswith("jev_"):
            # SP4：jev 系源（jev_seq_slot 两档 / jev_temp_band 冷温带）——prevScore 按设计置空，
            # 按 phaseLabel 计数（标签集合：offense/defense/cold/warm），不误计 missing
            available += 1
            label = ep.get("phaseLabel") if ep.get("phaseLabel") in ("offense", "defense", "cold", "warm") else None
            key = label or "unknown"
            by_phase[key] = by_phase.get(key, 0) + 1
            if key == "unknown":
                source_attribution["unknown"] += 1
            elif ep.get("fallbackUsed"):
                source_attribution["fallback"] += 1
            else:
                source_attribution["direct"] += 1
            continue
        if ep.get("prevScore") is None:
            missing += 1
            continue
        available += 1
        by_phase[str(ep.get("phase") or "unknown")] = by_phase.get(str(ep.get("phase") or "unknown"), 0) + 1
        slot = by_band.setdefault(str(ep.get("band") or "unknown"), {"trades": 0, "factorSet": set()})
        slot["trades"] += 1
        if isinstance(ep.get("factor"), (int, float)):
            slot["factorSet"].add(round(float(ep["factor"]), 2))
    for slot in by_band.values():
        slot["factorSet"] = sorted(slot["factorSet"])
    return {"availableTrades": available, "missingEntryPhase": missing, "byBand": by_band,
            "byPhase": by_phase, "rebalanceCount": rebalance, "sourceAttribution": source_attribution}


def _phase_of(score: float | None) -> str:
    if score is None:
        return "unknown"
    return "offense" if score >= PULSE_THRESHOLD else "defense"


# C6 分带（前一日 EOD as-of 口径）——带序与归类唯一来源=引擎 BAND_TAGS/band_of_score（execution.py）
# 2026-10-04 事故注记：此处曾手抄三档副本漏极热≥80，前日 ≥80 的交易被静默丢档（11 笔只显示 10 笔）。


def band_stats(trades: list[dict], eod_scores: dict[str, float | None], month: str) -> tuple[dict, int]:
    """基线交易按前一日 EOD 分带（as-of 无前视）——C6 证据逐次脉拍累积。

    归类复用引擎 band_of_score 四带全轴覆盖；返回 (bands, unbanded)：
    unbanded=当月入场却进不了任何档的笔数（缺前一日分或缺平仓价），fail-visible 显式暴露不静默。
    bands 每档携带用户展示名 label / 区间文案 rangeText，前端纯渲染不再自建映射。
    """
    # 前日解算与引擎 _phase_context 同口径（execution.py：严格取字典序前一日，None/缺即缺，
    # 不跳过缺分日锚更早——review P2：跳锚会让 band 归档用陈旧分且与 byBand 归因分歧）
    ordered = sorted(eod_scores.items())
    prev_score = {ordered[i][0]: ordered[i - 1][1] for i in range(1, len(ordered))}
    buckets: dict[str, list[float]] = {tag: [] for tag in BAND_TAGS}
    unbanded = 0
    for t in trades:
        entry = str(t.get("entryTradingDate") or "")
        if not entry.startswith(month):
            continue
        ret = t.get("netReturn")
        ps = prev_score.get(entry)
        if not isinstance(ret, (int, float)) or not isinstance(ps, (int, float)):
            unbanded += 1
            continue
        buckets[band_of_score(float(ps))].append(float(ret))
    out: dict = {}
    for tag in BAND_TAGS:
        rets = buckets[tag]
        label, range_text = PULSE_BAND_LABELS[tag]
        out[tag] = {
            "label": label,
            "rangeText": range_text,
            "trades": len(rets),
            "sumNetReturn": round(sum(rets), 4),
            "avgPerTrade": round(sum(rets) / len(rets), 4) if rets else None,
        }
    return out, unbanded


def month_trades_of(summary: dict, month: str) -> list[dict]:
    """当月入场 roundTrip（SP2-T3 从 ab_compare 内提为模块级，供挑战者臂复用）。"""
    return [
        t for t in round_trips_of(summary)
        if str(t.get("entryTradingDate") or "").startswith(month)
    ]


def month_trade_stats(summary: dict, month: str) -> dict:
    rets = [
        float(t["netReturn"])
        for t in month_trades_of(summary, month)
        if isinstance(t.get("netReturn"), (int, float))
    ]
    return {"tradeCount": len(rets), "sumNetReturn": round(sum(rets), 4)}


def _inject_eod_scores(cfg: dict, eod_valid: dict) -> dict:
    """SP2-T3：挑战者配置注入全量 eodScores（评审 P2-6：与已有键合并且 DB 新表优先——
    防手写陈旧分数静默压过库内新表；纯新增键保留）。"""
    out = json.loads(json.dumps(cfg))
    for key in ("phaseExposureControl", "phaseExitCoupling", "phaseRebalance"):
        if isinstance(out.get(key), dict):
            merged = dict(out[key].get("eodScores") or {})
            merged.update(eod_valid)
            out[key]["eodScores"] = merged
    return out


def build_arm_trade_configs(arms: list[str], arm_config_path: str, eod_scores: dict,
                            slot_scores: dict | None = None, jev_labels: dict | None = None) -> dict:
    """SP2-T3：臂装配（登记驱动，章程 §5.6 挑战者预算 ≤2）。

    内置 baseline（gate off + 归因 eodScores）/ champion（ladder③，C7）；挑战者经 --arm-config
    注入（JSON：{名: {trade_config: {...}}}）。未知名/超预算 fail-visible 截断进 skipped。
    SP4-T4：jev_labels（labels v3 产物 {slotLabels, fallbackLabels}）注入 source=jev_seq_slot 臂
    （配置内已有键优先、文件覆盖，与 slotScores 同语义）。
    """
    eod_valid = {d: s for d, s in eod_scores.items() if s is not None}
    builtin = {
        "baseline": {"phaseExposureControl": {"mode": "off", "eodScores": eod_valid}},
        "champion": {"phaseExposureControl": {"mode": "ladder", "ladder": [[40, 1.0], [60, 0.0], [999, 0.3]], "eodScores": eod_valid}},
    }
    extra: dict[str, dict] = {}
    extra_meta: dict[str, dict] = {}
    malformed: list[str] = []
    if arm_config_path:
        raw = json.loads(Path(arm_config_path).read_text(encoding="utf-8"))
        for name, spec in raw.items():
            cfg = spec.get("trade_config") if isinstance(spec, dict) else None
            if isinstance(cfg, dict):
                injected = _inject_eod_scores(cfg, eod_valid)
                ec = injected.get("phaseExposureControl")
                if isinstance(ec, dict) and str(ec.get("source") or "") == "slot_then_prev_eod":
                    merged = dict(ec.get("slotScores") or {})
                    merged.update(slot_scores or {})
                    ec["slotScores"] = merged
                if isinstance(ec, dict) and str(ec.get("source") or "") == "jev_seq_slot":
                    jl = jev_labels or {}
                    merged_labels = dict(ec.get("phaseLabels") or {})
                    merged_labels.update(jl.get("slotLabels") or {})
                    ec["phaseLabels"] = merged_labels
                    merged_fb = dict(ec.get("fallbackLabels") or {})
                    merged_fb.update(jl.get("fallbackLabels") or {})
                    ec["fallbackLabels"] = merged_fb
                extra[str(name)] = injected
                # 用户展示语义随臂数登记（单一事实源=本配置；前端纯渲染不自建臂数词典）
                extra_meta[str(name)] = {
                    "label": spec.get("label") if isinstance(spec.get("label"), str) else None,
                    "description": spec.get("description") if isinstance(spec.get("description"), str) else None,
                }
            else:
                malformed.append(str(name))
    out: dict[str, dict] = {}
    skipped: list[str] = []
    challenger_budget = 2
    for name in arms:
        if name in builtin:
            out[name] = builtin[name]
        elif name in extra:
            if len([n for n in out if n not in builtin]) >= challenger_budget:
                skipped.append(f"budget:{name}")  # 评审 P2-5：skipped 带原因码
                continue
            out[name] = extra[name]
        elif name in malformed:
            skipped.append(f"malformed:{name}")
        else:
            skipped.append(f"unregistered:{name}")
    return {"arms": out, "skipped": skipped, "armMeta": extra_meta}


def ab_compare(baseline: dict, controlled: dict, month: str) -> dict:
    """A/B 装配：基线 vs ladder③ 相位阶梯臂（C7，配置见 arm 字段），月内口径。"""

    def stats(summary: dict) -> dict:
        return month_trade_stats(summary, month)

    b, c = stats(baseline), stats(controlled)
    c_trades = month_trades_of(controlled, month)
    return {
        "baseline": b,
        "bandAvoided": c,
        "delta": {
            "tradesRemoved": b["tradeCount"] - c["tradeCount"],
            "netReturnSaved": round(c["sumNetReturn"] - b["sumNetReturn"], 4),
        },
        "arm": "按情绪分档出手（低温满仓、弱势期不开新仓、高温三成）",
        "attribution": attribution_stats(c_trades),
    }


def load_slot_scores(end: str) -> dict[str, dict[str, float]]:
    """SP3-T3.2：非 EOD 档情绪分（slot as-of 口径数据源），{date: {slot: score}}。"""
    from backend.data.repositories import repository_factory

    db = repository_factory.get_runtime_mongodb_database()
    out: dict[str, dict[str, float]] = {}
    for doc in db["hotlist_sentiment"].find(
        {"datasetId": "dragonboard_live", "snapshotType": "half_hour",
         "slotTime": {"$ne": "EOD"}, "tradingDate": {"$lte": end}},
        {"tradingDate": 1, "slotTime": 1, "emotionScore.score": 1},
    ):
        es = doc.get("emotionScore")
        if isinstance(es, dict) and isinstance(es.get("score"), (int, float)):
            out.setdefault(str(doc.get("tradingDate") or ""), {})[str(doc.get("slotTime"))] = float(es["score"])
    return out


def load_eod_scores(end_date: str) -> dict[str, float | None]:
    from backend.data.repositories import repository_factory

    db = repository_factory.get_runtime_mongodb_database()
    out: dict[str, float | None] = {}
    for doc in db["hotlist_sentiment"].find(
        {"datasetId": "dragonboard_live", "snapshotType": "half_hour", "slotTime": "EOD",
         "tradingDate": {"$lte": end_date}},
        {"tradingDate": 1, "emotionScore.score": 1},
    ):
        es = doc.get("emotionScore")
        out[str(doc.get("tradingDate") or "")] = (
            float(es["score"]) if isinstance(es, dict) and isinstance(es.get("score"), (int, float)) else None
        )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="M3 盘面脉拍（当月至今相位快照，隔离进程）")
    parser.add_argument("--month", required=True, help="YYYY-MM")
    parser.add_argument("--end", default="", help="截止日 YYYY-MM-DD（默认今天）")
    parser.add_argument("--out", default="")
    parser.add_argument("--arms", default="baseline,champion",
                        help="逗号分隔臂名：baseline,champion + --arm-config 内的挑战者名（章程 §5.6 预算挑战者≤2）")
    parser.add_argument("--arm-config", default="",
                        help="JSON：{挑战者名: {trade_config: {...}}}（预登记挑战者的配置注入）")
    parser.add_argument("--jev-labels", default="data/reports/phase-monitor/phase-labels-jev-v3.json",
                        help="SP4 labels v3 产物路径（jev_seq_slot 臂标签注入；缺失 fail-visible 记录）")
    args = parser.parse_args()
    end = args.end or datetime.now().strftime("%Y-%m-%d")

    from backend.cli import runtime_session
    from backend.services.backtest_service import BacktestService

    eod_scores = load_eod_scores(end)
    slot_scores = load_slot_scores(end)
    jev_labels: dict | None = None
    jev_labels_path = Path(args.jev_labels)
    if jev_labels_path.exists():
        jev_labels = json.loads(jev_labels_path.read_text(encoding="utf-8"))
    else:
        print(f"[phase-pulse] jev 标签文件缺失（fail-visible，jev 臂走 unknown/配置内标签）：{jev_labels_path}", file=sys.stderr)
    warmup_start = (datetime.strptime(f"{args.month}-01", "%Y-%m-%d")).replace(day=1)
    warmup_start = warmup_start.fromordinal(warmup_start.toordinal() - 10)
    arm_specs = build_arm_trade_configs(
        [a.strip() for a in args.arms.split(",") if a.strip()], args.arm_config, eod_scores, slot_scores,
        jev_labels)
    payload = {
        "dataset_id": "dragonboard_live",
        "snapshot_type": "half_hour",
        "start_date": warmup_start.strftime("%Y-%m-%d"),
        "end_date": end,
        "strategy_name": "ranktrend_early_big_move_v3_lifecycle_fusion",
        "random_seed": 20260430,
        "trade_config": arm_specs["arms"].get("baseline", {}),
        "dryRun": True,
    }
    summary = BacktestService(runtime_session()).run_ranktrend(payload)

    report = build_pulse_report(summary, eod_scores, args.month)
    report["meta"] = {
        "month": args.month, "end": end,
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "gate": "off（基线读数；A/B 对照用 trade_config.phaseExposureControl）",
        "jevLabelsLoaded": jev_labels is not None,
        "jevLabelsVersion": (jev_labels or {}).get("meta", {}).get("version") if jev_labels else None,
    }
    # C6 证据：基线交易按前日分带累积（四带全轴；unbanded=进不了任何档的笔数，fail-visible）
    report["bands"], report["unbandedTrades"] = band_stats(round_trips_of(summary), eod_scores, args.month)
    # SP1 归因段（章程 T2）：基线臂当月 entryPhase 汇总（与 A/B 同口径，不含 warmup 段）
    report["attribution"] = attribution_stats([
        t for t in round_trips_of(summary)
        if str(t.get("entryTradingDate") or "").startswith(args.month)
    ])
    # SP2-T3 多臂：baseline=主报告；champion=ab（向后兼容）；其余=challengers（预算≤2）
    report["armSkipped"] = arm_specs["skipped"]
    arm_meta = arm_specs.get("armMeta") or {}
    report["challengers"] = []
    for arm_name, arm_cfg in arm_specs["arms"].items():
        if arm_name == "baseline":
            continue
        meta = arm_meta.get(arm_name) or {}
        try:
            arm_summary = BacktestService(runtime_session()).run_ranktrend({**payload, "trade_config": arm_cfg})
        except Exception as exc:  # noqa: BLE001 — 单臂失败不阻断基线读数（fail-visible 降级）
            report["challengers"].append({"name": arm_name, "label": meta.get("label"),
                                          "description": meta.get("description"),
                                          "degraded": True, "reason": str(exc)})
            print(f"[phase-pulse] 臂 {arm_name} 失败（基线照常）: {exc}", file=sys.stderr)
            continue
        if arm_name == "champion":
            report["ab"] = ab_compare(summary, arm_summary, args.month)
        else:
            report["challengers"].append({
                "name": arm_name,
                "label": meta.get("label"),
                "description": meta.get("description"),
                "arm": json.dumps(arm_cfg, ensure_ascii=False)[:300],
                "stats": month_trade_stats(arm_summary, args.month),
                "attribution": attribution_stats(month_trades_of(arm_summary, args.month)),
            })
    out = Path(args.out) if args.out else Path(f"data/reports/phase-monitor/pulse-{args.month}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))

    from backend.operations.phase_monitor_persistence import persist_pulse

    persist_pulse(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
