from __future__ import annotations
import gzip
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from backend.analysis.ranktrend.engine import RankTrendConfig, RankTrendPythonEngine
from backend.analysis.theme.heat_level import resolve_heat_level
from backend.analysis.theme.rotation.signals import (
    rrg_quadrants,
    sg1_rrg_migration_flags,
    sg2_rotation_switch_flags,
    sg3_inflow_turn_positive_flags,
)
from backend.analysis.theme.trend import ThemeTrendConfig, ThemeTrendPythonEngine
from backend.core.backtest import (
    BacktestEngine,
    TradeSimulator,
    normalize_strategy_name,
)
from backend.data.models.models import BacktestRun
from backend.data.ingest.json_codec import dumps_json_field, loads_json_field
from backend.data.repositories.repository_factory import (
    create_repository,
    get_runtime_mongodb_database,
    storage_source_label,
)
from backend.core.settings import get_settings
from backend.data.repositories.theme_daily_factor_repository import ThemeDailyFactorRepository
from backend.core.utils import json_dumps, new_id, stable_hash
from backend.services.shared import (
    DEFAULT_BACKTEST_STRATEGY_CONFIG,
    trade_defaults_for_strategy,
    BACKTEST_COMPARE_METRICS,
    camel_get,
    _price_is_positive,
    _raw_stock_code,
    _is_cross_market_zero_price_stock,
    _load_a_share_codes,
    _prepare_frames_for_backtest,
    _ensure_runtime_filtered_frames_usable,
)
from backend.services.efficacy import (
    compute_execution_entry_layer1_efficacy,
    compute_signal_efficacy,
)


def _apply_trade_config_defaults_and_patch(
    trade_config: dict[str, Any],
    trade_defaults: dict[str, Any],
    trade_config_patch: dict[str, Any] | None,
) -> dict[str, Any]:
    """策略级 defaults 中未显式构造的键 setdefault 并入，patch 最后覆盖一切。

    显式构造键已用 defaults 作默认值，setdefault 防止 defaults 反向覆盖显式语义；
    payload patch（trade_config/tradeConfig）优先级最高（显式请求 > 策略默认）。
    回归背景：2026-09-23 落默认发现 v5 defaults 独有键（breakevenTrailing 等）
    从未进入 trade_config——显式构造只引用了个别 defaults 值（见
    tests/test_v5_trade_defaults.py::test_run_ranktrend_merges_defaults_keys_not_explicitly_built）。
    """
    for key, value in trade_defaults.items():
        trade_config.setdefault(key, value)
    trade_config.update(trade_config_patch or {})
    return trade_config


def _positive_price_stock_rows(frames: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    output: list[dict[str, Any]] = []
    dropped_rows = 0
    impacted_snapshots: set[str] = set()
    empty_snapshots: list[str] = []
    for frame in frames:
        stocks = frame.get("stocks") if isinstance(frame.get("stocks"), list) else []
        kept: list[dict[str, Any]] = []
        for stock in stocks:
            if not isinstance(stock, dict):
                kept.append(stock)
                continue
            if _price_is_positive(stock.get("price")):
                kept.append(stock)
            else:
                dropped_rows += 1
                impacted_snapshots.add(str(frame.get("snapshotId") or ""))
        next_frame = {**frame, "stocks": kept}
        if stocks and not kept:
            empty_snapshots.append(str(frame.get("snapshotId") or ""))
        output.append(next_frame)
    return output, {
        "reason": "positive_price_stock_rows_only",
        "sourceTargetFrames": len(frames),
        "usableTargetFrames": len([frame for frame in output if frame.get("stocks")]),
        "droppedNonPositivePriceRows": dropped_rows,
        "impactedSnapshots": len(impacted_snapshots),
        "emptySnapshotsAfterFilter": len(empty_snapshots),
        "emptySnapshotIdsAfterFilter": empty_snapshots[:50],
    }


def _cross_market_zero_price_stock_rows(
    frames: list[dict[str, Any]],
    a_share_codes: set[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    output: list[dict[str, Any]] = []
    dropped_rows = 0
    impacted_snapshots: set[str] = set()
    empty_snapshots: list[str] = []
    examples: list[dict[str, Any]] = []
    skipped_all_zero_frames: list[str] = []
    for frame in frames:
        stocks = frame.get("stocks") if isinstance(frame.get("stocks"), list) else []
        if stocks and all(isinstance(stock, dict) and not _price_is_positive(stock.get("price")) for stock in stocks):
            skipped_all_zero_frames.append(str(frame.get("snapshotId") or ""))
            output.append(frame)
            continue
        kept: list[dict[str, Any]] = []
        for stock in stocks:
            if not isinstance(stock, dict) or not _is_cross_market_zero_price_stock(stock, a_share_codes):
                kept.append(stock)
                continue
            dropped_rows += 1
            snapshot_id = str(frame.get("snapshotId") or "")
            impacted_snapshots.add(snapshot_id)
            if len(examples) < 20:
                examples.append({
                    "snapshotId": snapshot_id,
                    "code": _raw_stock_code(stock.get("code")),
                    "name": str(stock.get("name") or ""),
                })
        next_frame = {**frame, "stocks": kept}
        if stocks and not kept:
            empty_snapshots.append(str(frame.get("snapshotId") or ""))
        output.append(next_frame)
    return output, {
        "reason": "cross_market_zero_price_rows_excluded",
        "sourceTargetFrames": len(frames),
        "usableTargetFrames": len([frame for frame in output if frame.get("stocks")]),
        "droppedCrossMarketZeroPriceRows": dropped_rows,
        "impactedSnapshots": len(impacted_snapshots),
        "emptySnapshotsAfterFilter": len(empty_snapshots),
        "emptySnapshotIdsAfterFilter": empty_snapshots[:50],
        "skippedAllZeroPriceFrames": len(skipped_all_zero_frames),
        "skippedAllZeroPriceFrameIds": skipped_all_zero_frames[:50],
        "aShareUniverseAvailable": a_share_codes is not None,
        "aShareUniverseCodeCount": len(a_share_codes or set()),
        "examples": examples,
    }


def _drop_all_zero_price_frames(frames: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    output: list[dict[str, Any]] = []
    dropped_ids: list[str] = []
    dropped_rows = 0
    for frame in frames:
        stocks = frame.get("stocks") if isinstance(frame.get("stocks"), list) else []
        is_all_zero = bool(stocks) and all(
            isinstance(stock, dict) and not _price_is_positive(stock.get("price"))
            for stock in stocks
        )
        if is_all_zero:
            dropped_ids.append(str(frame.get("snapshotId") or ""))
            dropped_rows += len(stocks)
            continue
        output.append(frame)
    return output, {
        "reason": "all_zero_price_frames_excluded",
        "sourceTargetFrames": len(frames),
        "usableTargetFrames": len(output),
        "droppedAllZeroPriceFrames": len(dropped_ids),
        "droppedAllZeroPriceRows": dropped_rows,
        "droppedSnapshotIds": dropped_ids[:50],
    }


def _price_quality_diagnostics(
    frames: list[dict[str, Any]],
    a_share_codes: set[str] | None = None,
) -> dict[str, Any]:
    cross_market_rows = 0
    cross_market_snapshots: set[str] = set()
    cross_market_examples: list[dict[str, Any]] = []
    all_zero_frame_ids: list[str] = []
    all_zero_rows = 0
    partial_a_share_rows = 0
    partial_a_share_snapshots: set[str] = set()
    partial_a_share_examples: list[dict[str, Any]] = []

    for frame in frames:
        snapshot_id = str(frame.get("snapshotId") or "")
        stocks = frame.get("stocks") if isinstance(frame.get("stocks"), list) else []
        is_all_zero = bool(stocks) and all(
            isinstance(stock, dict) and not _price_is_positive(stock.get("price"))
            for stock in stocks
        )
        if is_all_zero:
            all_zero_frame_ids.append(snapshot_id)
            all_zero_rows += len(stocks)
            continue

        for stock in stocks:
            if not isinstance(stock, dict) or _price_is_positive(stock.get("price")):
                continue
            if _is_cross_market_zero_price_stock(stock, a_share_codes):
                cross_market_rows += 1
                cross_market_snapshots.add(snapshot_id)
                if len(cross_market_examples) < 20:
                    cross_market_examples.append({
                        "snapshotId": snapshot_id,
                        "code": _raw_stock_code(stock.get("code")),
                        "name": str(stock.get("name") or ""),
                    })
                continue
            partial_a_share_rows += 1
            partial_a_share_snapshots.add(snapshot_id)
            if len(partial_a_share_examples) < 20:
                partial_a_share_examples.append({
                    "snapshotId": snapshot_id,
                    "code": _raw_stock_code(stock.get("code")),
                    "name": str(stock.get("name") or ""),
                    "price": stock.get("price"),
                })

    return {
        "role": "report_only",
        "autoApplyDefaults": False,
        "computedBeforeResearchFilters": True,
        "crossMarketZeroPriceRows": {
            "rowCount": cross_market_rows,
            "snapshotCount": len(cross_market_snapshots),
            "examples": cross_market_examples,
            "aShareUniverseAvailable": a_share_codes is not None,
            "aShareUniverseCodeCount": len(a_share_codes or set()),
            "skippedAllZeroPriceFrames": len(all_zero_frame_ids),
        },
        "allZeroPriceFrames": {
            "frameCount": len(all_zero_frame_ids),
            "rowCount": all_zero_rows,
            "snapshotIds": all_zero_frame_ids[:50],
        },
        "partialAshareZeroPriceRows": {
            "rowCount": partial_a_share_rows,
            "snapshotCount": len(partial_a_share_snapshots),
            "examples": partial_a_share_examples,
        },
    }


def _persisted_heat_level(factor: object) -> float:
    """落库热度相对分（0-100 置信度合成项，缺失按 0 计）。

    口径解释唯一实现是 `heat_level.resolve_heat_level`（design §4.2 三分支）；
    本包装只做非 dict 输入与 `None → 0.0` 兜底（缺失不伪装满分），
    不重复实现口径规则。"""
    if not isinstance(factor, dict):
        return 0.0
    return resolve_heat_level(factor) or 0.0


# Phase R3 SG 变体（设计文档 §5.4/§6.1）：仅这两个策略触发 SG 预计算，既有策略零开销。
THEME_SG_STRATEGIES = frozenset({"theme_rotation_chase", "theme_state_hybrid"})

_THEME_SG_SOURCES = ("sg1", "sg2", "sg3")


def _payload_float(value: Any, default: float) -> float:
    """payload 数值参数安全转换：非法/NaN 回退默认（门控参数防御）。"""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    return numeric if numeric == numeric else default


def _gating_number(value: Any) -> float:
    """门控惩罚值读取：缺失/非法按 0 处理（不调整），由构建侧默认值兜底。"""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    return numeric if numeric == numeric else 0.0


def _theme_sg_hit(sg_inputs: dict[str, Any] | None, theme_name: str, trading_date: str) -> tuple[bool, list[str]]:
    """查 (theme, date) 的 SG 触发与来源（仅 True 计触发；False/None 均不触发）。"""
    if not sg_inputs:
        return False, []
    per_day = (sg_inputs.get("sgFlags") or {}).get(theme_name) or {}
    entry = per_day.get(trading_date) or {}
    sources = [name for name in _THEME_SG_SOURCES if entry.get(name) is True]
    return bool(sources), sources


def _close_slot_rows_by_day(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """daily 题材行按日取收盘槽横截面（15:30 优先 / 15:00 回退，R1 锚点口径）。"""
    by_day_slot: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for row in rows:
        by_day_slot.setdefault(str(row.get("tradingDate")), {}).setdefault(str(row.get("slotTime")), []).append(row)
    out: dict[str, list[dict[str, Any]]] = {}
    for d, slots in by_day_slot.items():
        picked = next((slots[s] for s in ("15:30", "15:00") if s in slots), None)
        if picked:
            out[d] = picked
    return out


_SG1_MAX_GAP_NATURAL_DAYS = 7


def _natural_days_between(start: str, end: str) -> int:
    ya, ma, da = map(int, start.split("-"))
    yb, mb, db = map(int, end.split("-"))
    return date(yb, mb, db).toordinal() - date(ya, ma, da).toordinal()


def _sg1_close_slot_flags(
    change_seq: dict[str, float | None],
    benchmark_by_day: dict[str, float],
) -> tuple[dict[str, bool | None], bool]:
    """R3b SG1 收盘槽序列：严格出勤 + >7 自然日空洞截断（task_plan_r3b.md 语义定版）。

    - 观测日 = change 非空的 15:00 日；span = [首观测, 末观测] 内的全部基准日历日；
    - 相邻日历日自然间隔 > _SG1_MAX_GAP_NATURAL_DAYS（4-5 月题材行空洞类）→ 截断为
      最后一个断点之后，跨空洞动量不产生（防 7-06 边界系统性假触发）；
    - 截断后 <2 天或 span 内任一日缺勤 → ({}, False)，调用方计 insufficient、全 None。
    返回 ({date: sg1 flag}, sufficient)；未观测日不在返回 dict 中（消费方 .get 默认 None）。
    """
    obs = {d: v for d, v in change_seq.items() if v is not None}
    if not obs:
        return {}, False
    first = min(obs)
    last = max(obs)
    span = [d for d in sorted(benchmark_by_day) if first <= d <= last]
    start_idx = 0
    for idx, (a, b) in enumerate(zip(span, span[1:])):
        if _natural_days_between(a, b) > _SG1_MAX_GAP_NATURAL_DAYS:
            start_idx = idx + 1
    series = span[start_idx:]
    if len(series) < 2 or any(d not in obs for d in series):
        return {}, False
    quadrants = rrg_quadrants(
        [obs[d] for d in series], [benchmark_by_day[d] for d in series]
    )
    flags = sg1_rrg_migration_flags(dict(zip(series, quadrants)))
    return flags, True


class BacktestService:
    def __init__(self, session: Any | None):
        self.repo = create_repository(session)

    def _augment_low_hotlist_examples(
        self,
        dataset_id: str,
        examples: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for raw in examples:
            item = dict(raw)
            if item.get("snapshotId") and not item.get("captureMode"):
                frame = self.repo.get_snapshot_frame(str(item["snapshotId"]), dataset_id=dataset_id)
                if isinstance(frame, dict) and frame.get("captureMode"):
                    item["captureMode"] = frame.get("captureMode")
            output.append(item)
        return output

    @staticmethod
    def _normalize_quality_warnings(
        warnings: list[str],
        *,
        synthesized_empty_hotlist_count: int,
        raw_empty_hotlist_count: int,
        real_low_hotlist_count: int,
    ) -> list[str]:
        normalized: list[str] = []
        for warning in warnings:
            if (
                synthesized_empty_hotlist_count
                and raw_empty_hotlist_count == 0
                and (
                    warning.startswith("Empty hotlist snapshot:")
                    or ("个空热榜快照" in warning and "重新导入或剔除" in warning)
                )
            ):
                continue
            if (
                synthesized_empty_hotlist_count
                and real_low_hotlist_count == 0
                and "个低热榜快照" in warning
            ):
                continue
            normalized.append(warning)

        if synthesized_empty_hotlist_count:
            normalized.append(
                f"存在 {synthesized_empty_hotlist_count} 个 synthesized 补帧未生成热榜行，相关快照已在回测前剔除，并非原始热榜抓取为 0 行。"
            )

        return list(dict.fromkeys(normalized))

    def _normalize_data_quality(
        self,
        dataset_id: str,
        data_quality: dict[str, Any],
    ) -> dict[str, Any]:
        normalized = dict(data_quality)
        raw_layer2 = normalized.get("layer2ExecutionQuality")
        if not (isinstance(raw_layer2, dict) and raw_layer2.get("layer2Status")):
            normalized.pop("layer2ExecutionQuality", None)

        examples = normalized.get("lowHotlistExamples")
        if isinstance(examples, list):
            normalized_examples = self._augment_low_hotlist_examples(
                dataset_id,
                [item for item in examples if isinstance(item, dict)],
            )
            normalized["lowHotlistExamples"] = normalized_examples
            synthesized_count = sum(
                1
                for item in normalized_examples
                if item.get("stockRowCount") == 0 and item.get("captureMode") == "synthesized"
            )
            normalized.setdefault("synthesizedEmptyHotlistCount", synthesized_count)
            normalized.setdefault(
                "rawEmptyHotlistCount",
                max(0, int(normalized.get("emptyHotlistCount") or 0) - synthesized_count),
            )

        synthesized_empty_hotlist_count = int(normalized.get("synthesizedEmptyHotlistCount") or 0)
        raw_empty_hotlist_count = int(normalized.get("rawEmptyHotlistCount") or 0)
        real_low_hotlist_count = max(
            0,
            int(normalized.get("lowHotlistCount") or 0) - synthesized_empty_hotlist_count,
        )
        warnings = normalized.get("warnings")
        if isinstance(warnings, list):
            normalized["warnings"] = self._normalize_quality_warnings(
                [str(item) for item in warnings],
                synthesized_empty_hotlist_count=synthesized_empty_hotlist_count,
                raw_empty_hotlist_count=raw_empty_hotlist_count,
                real_low_hotlist_count=real_low_hotlist_count,
            )
        if (
            synthesized_empty_hotlist_count
            and raw_empty_hotlist_count == 0
            and str(normalized.get("recommendation") or "").startswith("可以用于候选观察")
        ):
            normalized["recommendation"] = (
                "可以用于候选观察，但需注意样本内存在 synthesized 补帧缺口；相关空热榜补帧已在回测前剔除。"
            )
        return normalized

    @staticmethod
    def _summary_response(
        run_id: str,
        result: dict[str, Any],
        metadata: dict[str, Any] | None = None,
        full_attribution: bool = False,
    ) -> dict[str, Any]:
        signals = result.get("signals") or []
        signal_count = int(result.get("signalCount") or len(signals))
        compact = BacktestService._compact_backtest_result(result, signal_count=signal_count)
        compact["signalCount"] = signal_count
        compact["isCompact"] = True
        if full_attribution:
            # dry-run（2026-09-23 引擎提速立项）：结果不落库，归因数据（全量 trades/equityCurve）
            # 直接随轻量摘要返回，扫描分析脚本从响应体取而不是读 Mongo。
            simulation = result.get("tradeSimulation") if isinstance(result.get("tradeSimulation"), dict) else {}
            compact["trades"] = list(simulation.get("trades") or [])
            compact["equityCurve"] = list(simulation.get("equityCurve") or [])
        compact["notes"] = [
            *(result.get("notes") or []),
            (
                "dry-run：跳过落库与 result_json 序列化，runId 仅为响应标识；全量 trades/equityCurve 已随响应返回。"
                if full_attribution
                else f"接口默认返回轻量摘要和前 120 条 signals 预览，完整压缩结果已落库：{run_id}"
            ),
        ]
        meta = metadata or {}
        return {"id": run_id, "runId": run_id, "run_id": run_id, **meta, "result": compact, **compact}

    @staticmethod
    def _compact_backtest_result(result: dict[str, Any], *, signal_count: int) -> dict[str, Any]:
        compact = {
            key: value
            for key, value in result.items()
            if key
            not in {
                "signals",
                "strategyDecisions",
                "tradeSimulation",
                "roundTripTrades",
                "trades",
                "tradeEvents",
                "equityCurve",
                "openPositions",
            }
        }

        signals = result.get("signals") if isinstance(result.get("signals"), list) else []
        compact["signals"] = [
            BacktestService._compact_signal_preview(signal)
            for signal in signals[:120]
            if isinstance(signal, dict)
        ]
        compact["signalPreviewCount"] = len(compact["signals"])
        compact["signalCount"] = signal_count

        for key in ("roundTripTrades", "trades", "tradeEvents", "equityCurve", "openPositions"):
            values = result.get(key)
            if isinstance(values, list):
                compact[key] = values[:120]

        simulation = result.get("tradeSimulation")
        if isinstance(simulation, dict):
            compact["tradeSimulation"] = BacktestService._compact_trade_simulation(simulation)

        decisions = result.get("strategyDecisions")
        if isinstance(decisions, dict):
            frame_results = decisions.get("frameResults") if isinstance(decisions.get("frameResults"), list) else []
            compact["strategyDecisions"] = {
                key: value
                for key, value in decisions.items()
                if key != "frameResults"
            }
            compact["strategyDecisions"]["frameResultCount"] = len(frame_results)
            compact["strategyDecisions"]["frameResults"] = [
                BacktestService._compact_strategy_frame(frame)
                for frame in frame_results[:20]
                if isinstance(frame, dict)
            ]

        return compact

    @staticmethod
    def _compact_signal_preview(signal: dict[str, Any]) -> dict[str, Any]:
        rank_trend = signal.get("rankTrend") if isinstance(signal.get("rankTrend"), dict) else {}
        decision = rank_trend.get("decision") if isinstance(rank_trend.get("decision"), dict) else {}
        final = decision.get("final") if isinstance(decision.get("final"), dict) else {}
        technical = rank_trend.get("technical") if isinstance(rank_trend.get("technical"), dict) else {}
        momentum = technical.get("momentumProfile") if isinstance(technical.get("momentumProfile"), dict) else {}
        return {
            "snapshotId": signal.get("snapshotId"),
            "tradingDate": signal.get("tradingDate"),
            "slotTime": signal.get("slotTime"),
            "code": signal.get("code"),
            "name": signal.get("name"),
            "rank": signal.get("rank"),
            "price": signal.get("price"),
            "candidateTier": signal.get("candidateTier"),
            "action": signal.get("action"),
            "signal": signal.get("signal") or final.get("signal"),
            "finalSignal": final.get("signal"),
            "confidence": signal.get("confidence"),
            "stage": signal.get("stage"),
            "regime": signal.get("regime"),
            "score": signal.get("score"),
            "technicalSignals": technical.get("signals"),
            "momentumProfile": momentum,
            "risk": rank_trend.get("risk"),
            "momentum": momentum.get("momentum"),
            "acceleration": momentum.get("acceleration"),
            "riskFlags": signal.get("riskFlags") or [],
            "reasons": signal.get("reasons") or [],
            "mainTheme": signal.get("mainTheme"),
            "themeRole": signal.get("themeRole"),
        }

    @staticmethod
    def _compact_trade_simulation(simulation: dict[str, Any]) -> dict[str, Any]:
        compact = {
            key: value
            for key, value in simulation.items()
            if key not in {"roundTripTrades", "trades", "tradeEvents", "equityHistory", "equityCurve", "openPositions"}
        }
        for key in ("roundTripTrades", "trades", "tradeEvents", "equityHistory", "equityCurve", "openPositions"):
            values = simulation.get(key)
            if isinstance(values, list):
                compact[key] = values[:120]
                compact[f"{key}Count"] = len(values)
        return compact

    @staticmethod
    def _compact_strategy_frame(frame: dict[str, Any]) -> dict[str, Any]:
        return {
            "snapshotId": frame.get("snapshotId"),
            "tradingDate": frame.get("tradingDate"),
            "slotTime": frame.get("slotTime"),
            "buyCandidateCount": len(frame.get("buyCandidates") or []),
            "watchCandidateCount": len(frame.get("watchCandidates") or []),
            "excludedCandidateCount": len(frame.get("excludedCandidates") or []),
            "buyCandidates": [
                BacktestService._compact_decision_preview(item)
                for item in (frame.get("buyCandidates") or [])[:20]
                if isinstance(item, dict)
            ],
            "watchCandidates": [
                BacktestService._compact_decision_preview(item)
                for item in (frame.get("watchCandidates") or [])[:20]
                if isinstance(item, dict)
            ],
            "excludedCandidates": [
                BacktestService._compact_decision_preview(item)
                for item in (frame.get("excludedCandidates") or [])[:20]
                if isinstance(item, dict)
            ],
        }

    @staticmethod
    def _compact_decision_preview(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "code": item.get("code"),
            "name": item.get("name"),
            "rank": item.get("rank"),
            "signal": item.get("signal"),
            "candidateTier": item.get("candidateTier"),
            "confidence": item.get("confidence"),
            "stage": item.get("stage"),
            "regime": item.get("regime"),
            "reason": item.get("reason") or item.get("explanation"),
        }

    def run_ranktrend(self, payload: dict[str, Any]) -> dict[str, Any]:
        dataset_id = str(camel_get(payload, "dataset_id", "datasetId", ""))
        snapshot_type = str(camel_get(payload, "snapshot_type", "snapshotType", "half_hour"))
        payload_strategy_name = camel_get(payload, "strategy_name", "strategyName", None)
        trade_config_patch = camel_get(payload, "trade_config", "tradeConfig", {}) or {}
        strategy_name = normalize_strategy_name(
            payload_strategy_name
            if payload_strategy_name is not None
            else trade_config_patch.get("entryStrategy") or trade_config_patch.get("controlStrategy") or trade_config_patch.get("strategyName")
        )
        strategy_version = str(camel_get(payload, "strategy_version", "strategyVersion", "0.1.0"))
        frames = self.repo.load_frames(
            dataset_id,
            snapshot_type=snapshot_type,
            start_date=camel_get(payload, "start_date", "startDate"),
            end_date=camel_get(payload, "end_date", "endDate"),
            include_payload=True,
        )
        if not frames:
            raise ValueError(f"dataset has no frames for {snapshot_type}: {dataset_id}")
        run_frames, quality_gate = _prepare_frames_for_backtest(frames, snapshot_type)
        a_share_codes = _load_a_share_codes(self.repo)
        report_only_diagnostics = (
            quality_gate.get("reportOnlyDiagnostics")
            if isinstance(quality_gate.get("reportOnlyDiagnostics"), dict)
            else {}
        )
        report_only_diagnostics = dict(report_only_diagnostics)
        report_only_diagnostics["priceQuality"] = _price_quality_diagnostics(run_frames, a_share_codes)
        quality_gate["reportOnlyDiagnostics"] = report_only_diagnostics
        exclude_non_positive_price_rows = bool(camel_get(payload, "exclude_non_positive_price_rows", "excludeNonPositivePriceRows", False))
        exclude_cross_market_zero_price_rows = bool(camel_get(payload, "exclude_cross_market_zero_price_rows", "excludeCrossMarketZeroPriceRows", False))
        exclude_all_zero_price_frames = bool(camel_get(payload, "exclude_all_zero_price_frames", "excludeAllZeroPriceFrames", False))
        price_filter: dict[str, Any] | None = None
        cross_market_price_filter: dict[str, Any] | None = None
        all_zero_frame_filter: dict[str, Any] | None = None
        runtime_filter = quality_gate.get("runtimeFilter") if isinstance(quality_gate.get("runtimeFilter"), dict) else {}
        runtime_filter = dict(runtime_filter)
        if exclude_all_zero_price_frames:
            run_frames, all_zero_frame_filter = _drop_all_zero_price_frames(run_frames)
            runtime_filter["allZeroPriceFrameFilter"] = all_zero_frame_filter
        if exclude_cross_market_zero_price_rows:
            run_frames, cross_market_price_filter = _cross_market_zero_price_stock_rows(
                run_frames,
                a_share_codes,
            )
            runtime_filter["crossMarketPriceFilter"] = cross_market_price_filter
        if exclude_non_positive_price_rows:
            run_frames, price_filter = _positive_price_stock_rows(run_frames)
            runtime_filter["priceFilter"] = price_filter
        if runtime_filter:
            quality_gate["runtimeFilter"] = runtime_filter
        if exclude_all_zero_price_frames or exclude_cross_market_zero_price_rows or exclude_non_positive_price_rows:
            _ensure_runtime_filtered_frames_usable(run_frames, quality_gate)

        trade_defaults = trade_defaults_for_strategy(strategy_name)
        trade_config = {
            "initialCapital": camel_get(payload, "initial_cash", "initialCash", trade_defaults["initialCapital"]),
            "maxPositions": camel_get(payload, "max_positions", "maxPositions", trade_defaults["maxPositions"]),
            "positionSize": camel_get(payload, "position_size", "positionSize", trade_defaults["positionSize"]),
            "minJumpConfidence": camel_get(
                payload,
                "min_jump_confidence",
                "minJumpConfidence",
                trade_defaults["minJumpConfidence"],
            ),
            "takeProfit": camel_get(payload, "take_profit_pct", "takeProfitPct", trade_defaults["takeProfit"]),
            "stopLoss": -abs(float(camel_get(payload, "stop_loss_pct", "stopLossPct", abs(trade_defaults["stopLoss"])))),
            "maxHoldingBars": camel_get(payload, "max_holding_bars", "maxHoldingBars", trade_defaults["maxHoldingBars"]),
            "targetHoldingDays": camel_get(payload, "target_holding_days", "targetHoldingDays", trade_defaults["targetHoldingDays"]),
            "enforceT1": camel_get(payload, "enforce_t1", "enforceT1", trade_defaults["enforceT1"]),
            "executionMode": camel_get(payload, "execution_mode", "executionMode", trade_defaults["executionMode"]),
            "feeRate": camel_get(payload, "fee_rate", "feeRate", trade_defaults["feeRate"]),
            "stampTaxRate": camel_get(payload, "stamp_tax_rate", "stampTaxRate", trade_defaults["stampTaxRate"]),
            "slippageRate": camel_get(payload, "slippage_rate", "slippageRate", trade_defaults["slippageRate"]),
            "useOrderBookPrice": camel_get(payload, "use_order_book_price", "useOrderBookPrice", trade_defaults["useOrderBookPrice"]),
            "enforceLimitStatus": camel_get(payload, "enforce_limit_status", "enforceLimitStatus", trade_defaults["enforceLimitStatus"]),
            "enforceVolumeLimit": camel_get(payload, "enforce_volume_limit", "enforceVolumeLimit", trade_defaults["enforceVolumeLimit"]),
            "enforceOrderBookQueue": camel_get(payload, "enforce_order_book_queue", "enforceOrderBookQueue", trade_defaults["enforceOrderBookQueue"]),
            "allowPartialFills": camel_get(payload, "allow_partial_fills", "allowPartialFills", trade_defaults["allowPartialFills"]),
            "volumeParticipationRate": camel_get(payload, "volume_participation_rate", "volumeParticipationRate", trade_defaults["volumeParticipationRate"]),
            "orderBookParticipationRate": camel_get(payload, "order_book_participation_rate", "orderBookParticipationRate", trade_defaults["orderBookParticipationRate"]),
            "useIntrabarStops": camel_get(payload, "use_intrabar_stops", "useIntrabarStops", trade_defaults["useIntrabarStops"]),
            "intrabarAmbiguity": camel_get(payload, "intrabar_ambiguity", "intrabarAmbiguity", trade_defaults["intrabarAmbiguity"]),
            "entryStrategy": strategy_name,
        }
        trade_config = _apply_trade_config_defaults_and_patch(trade_config, trade_defaults, trade_config_patch)
        trade_config["entryStrategy"] = strategy_name
        strategy_config = {
            **DEFAULT_BACKTEST_STRATEGY_CONFIG,
            **(camel_get(payload, "strategy_config", "strategyConfig", {}) or {}),
        }
        for src, dst in [("macdFast", "macdFast"), ("macdSlow", "macdSlow"), ("macdSignal", "macdSignal"), ("momentumPeriods", "momentumPeriods")]:
            if src in payload:
                strategy_config[dst] = payload[src]
        options = {
            "enable_trade_simulation": camel_get(payload, "enable_trade_simulation", "enableTradeSimulation", True),
            "horizons": camel_get(payload, "horizons", default=[1, 3, 5, 10]),
            "trade_config": trade_config,
            "strategy_config": strategy_config,
            "strategy_name": strategy_name,
            "strategy_version": strategy_version,
            "dataset_id": dataset_id,
            "snapshot_type": snapshot_type,
            "random_seed": int(camel_get(payload, "random_seed", "randomSeed", 20260430)),
            "quality_gate": quality_gate,
            "research_filters": {
                "excludeNonPositivePriceRows": exclude_non_positive_price_rows,
                "excludeCrossMarketZeroPriceRows": exclude_cross_market_zero_price_rows,
                "excludeAllZeroPriceFrames": exclude_all_zero_price_frames,
                "priceFilter": price_filter,
                "crossMarketPriceFilter": cross_market_price_filter,
                "allZeroPriceFrameFilter": all_zero_frame_filter,
            },
        }
        result = BacktestEngine().run(run_frames, options)

        # Layer 1: signal efficacy (computed from backtest signals)
        layer_1_efficacy = compute_signal_efficacy(
            signals=result.get("signals") or [],
            frames=run_frames,
        )
        execution_layer_1_efficacy = compute_execution_entry_layer1_efficacy(
            trade_events=result.get("tradeEvents") or [],
            frames=run_frames,
        )
        quality_gate["layer1SignalEfficacy"] = layer_1_efficacy
        quality_gate["executionLayer1Efficacy"] = execution_layer_1_efficacy
        if isinstance(result.get("dataQuality"), dict):
            result["dataQuality"]["layer1SignalEfficacy"] = layer_1_efficacy
            result["dataQuality"]["executionLayer1Efficacy"] = execution_layer_1_efficacy
            result["dataQuality"] = self._normalize_data_quality(dataset_id, result["dataQuality"])
            result["warnings"] = list(result["dataQuality"].get("warnings") or [])

        run_id = new_id("bt")
        request_meta = {
            **payload,
            "dataset_id": dataset_id,
            "snapshot_type": snapshot_type,
            "random_seed": int(camel_get(payload, "random_seed", "randomSeed", 20260430)),
            "strategy_name": strategy_name,
            "strategy_version": strategy_version,
            "strategy_config": strategy_config,
            "trade_config": trade_config,
            "research_filters": options["research_filters"],
        }
        # dry-run 开关注入在服务层之后（runner 注入 payload），剔除后 configHash 才能与
        # 同参数持久化 run 对账一致；默认路径 payload 无此键，零行为变化。
        request_meta.pop("dry_run", None)
        request_meta.pop("dryRun", None)
        trading_dates = sorted({str(f.get("tradingDate") or "") for f in run_frames if f.get("tradingDate")})
        summary_metadata = {
            "datasetId": dataset_id,
            "dataset_id": dataset_id,
            "strategyName": strategy_name,
            "strategyVersion": strategy_version,
            "snapshotType": snapshot_type,
            "randomSeed": request_meta["random_seed"],
            "configHash": stable_hash(request_meta),
        }
        dry_run = bool(camel_get(payload, "dry_run", "dryRun", False))
        if dry_run:
            # 扫描/harness 专用（2026-09-23 引擎提速立项层 2）：跳过五表落库与
            # result_json 大 JSON gzip 序列化；默认 False，正式回测与既有 API 合同不变。
            return self._summary_response(run_id, result, {**summary_metadata, "dryRun": True}, full_attribution=True)
        run = BacktestRun(
            id=run_id,
            dataset_id=dataset_id,
            strategy_name=strategy_name,
            strategy_version=strategy_version,
            snapshot_type=snapshot_type,
            random_seed=request_meta["random_seed"],
            status="completed",
            config_hash=summary_metadata["configHash"],
            date_start=trading_dates[0] if trading_dates else None,
            date_end=trading_dates[-1] if trading_dates else None,
            request_json=dumps_json_field(request_meta),
            result_json=dumps_json_field(result),
        )
        self.repo.save_backtest_run(run)

        # 归一化结果双写
        simulation = result.get("tradeSimulation") or {}
        self.repo.save_backtest_trades(run_id, simulation.get("trades") or [], append=False)
        self.repo.save_backtest_equity_curve(run_id, simulation.get("equityCurve") or [], append=False)
        self.repo.save_backtest_signals(run_id, result.get("strategyDecisions") or {}, append=False)
        self.repo.save_backtest_quality_report(run_id, result.get("dataQuality") or {}, quality_gate)

        return self._summary_response(
            run_id,
            result,
            summary_metadata,
        )

    def run_theme_trend(self, payload: dict[str, Any]) -> dict[str, Any]:
        dataset_id = str(camel_get(payload, "dataset_id", "datasetId", ""))
        snapshot_type = str(camel_get(payload, "snapshot_type", "snapshotType", "half_hour"))
        strategy_name = str(camel_get(payload, "strategy_name", "strategyName", "theme_rotation"))
        from backend.core.backtest.strategy import THEME_STRATEGY_NAMES
        if strategy_name not in THEME_STRATEGY_NAMES:
            raise ValueError(f"unsupported theme strategy: {strategy_name}")
        random_seed = int(camel_get(payload, "random_seed", "randomSeed", 20260430))

        frames = self.repo.load_frame_bundles(
            dataset_id, snapshot_type=snapshot_type,
        )
        if not frames:
            raise ValueError(f"dataset has no frames for {snapshot_type}: {dataset_id}")


        engine_config = {
            "crowdedRiskThreshold": int(camel_get(payload, "crowdingBlockThreshold", "crowdingBlockThreshold", 75)),
            "minFrames": 2,
            # 持续性因子进合成分的权重（Phase 4 P4-3 前置接线）：默认 0.0 = 关，
            # 与历史逐位一致；显式传值才生效（一次一候选纪律）。
            "persistenceScoreWeight": _payload_float(
                camel_get(payload, "persistence_score_weight", "persistenceScoreWeight"), 0.0
            ),
            # 拥挤硬层阈值（D2① 参数化）：信号层（ThemeTrendConfig）与执行层
            # （_theme_execution_signals 入参）共用同一 payload 键，单旋钮双消费点
            "crowdedHardLayerThreshold": _payload_float(
                camel_get(payload, "crowding_hard_layer_threshold", "crowdingHardLayerThreshold", 75.0), 75.0
            ),
        }
        config = ThemeTrendConfig.from_patch(engine_config)
        # 日级持续性原料注入（Path B，2026-09-27）：仅 weight>0 时读库，默认路径零 IO；
        # 非 Mongo / 读失败返回 {}，引擎逐信号打 persistence_daily_key_missing。
        persistence_score_weight = engine_config["persistenceScoreWeight"]
        daily_factors = None
        if persistence_score_weight > 0:
            # 帮手在 daily_factors_service（无环：该模块本就模块级依赖
            # backtest_service._close_slot_rows_by_day，反向模块级导入会成环）
            from backend.services.theme.daily_factors_service import load_daily_persistence_inputs

            trading_days = sorted({str(f.get("tradingDate") or "") for f in frames} - {""})
            daily_factors, daily_source_flags = load_daily_persistence_inputs(dataset_id, trading_days)
        theme_result = ThemeTrendPythonEngine().replay_sequence(frames, config=config, daily_factors=daily_factors)
        if persistence_score_weight > 0 and daily_source_flags:
            # 数据源级结构化原因透出（code review I-4：禁止单靠信号级 key_missing 失真归因）
            theme_result["qualityReport"]["warnings"] = list(dict.fromkeys(
                [*theme_result["qualityReport"].get("warnings", []), *daily_source_flags]
            ))

        quality_report = theme_result.get("qualityReport", {})
        factors = theme_result.get("factors", [])
        signals = theme_result.get("signals", [])
        exposures = theme_result.get("exposures", [])
        sg_inputs = self._theme_sg_inputs(dataset_id, frames) if strategy_name in THEME_SG_STRATEGIES else None
        # 条件层门控（设计 §5.3，2026-09-27 Task2 机制接线）：默认关，显式开关才
        # 生效（一次一候选纪律）；门控只降可信 + 打标，不做硬门禁，不影响 tier。
        sentiment_gating_enabled = bool(camel_get(payload, "sentiment_gating_enabled", "sentimentGatingEnabled", False))
        crowding_percentile_enabled = bool(camel_get(payload, "crowding_percentile_enabled", "crowdingPercentileEnabled", False))
        gating_inputs: dict[str, Any] | None = None
        if sentiment_gating_enabled or crowding_percentile_enabled:
            gating_inputs = {
                **self._theme_gating_inputs(frames, dataset_id, include_crowding_percentile=crowding_percentile_enabled),
                "sentimentPhases": tuple(
                    str(item)
                    for item in (
                        camel_get(payload, "sentiment_gating_phases", "sentimentGatingPhases")
                        or ("cooling", "ice")
                    )
                ),
                "sentimentConfidencePenalty": _payload_float(
                    camel_get(payload, "sentiment_gating_confidence_penalty", "sentimentGatingConfidencePenalty", 10.0), 10.0
                ),
                "crowdingPercentileHighThreshold": _payload_float(
                    camel_get(payload, "crowding_percentile_high_threshold", "crowdingPercentileHighThreshold", 90.0), 90.0
                ),
                "crowdingPercentileConfidencePenalty": _payload_float(
                    camel_get(payload, "crowding_percentile_confidence_penalty", "crowdingPercentileConfidencePenalty", 10.0), 10.0
                ),
            }
        execution_signals = self._theme_execution_signals(
            frames, factors, exposures, strategy_name, sg_inputs=sg_inputs, gating_inputs=gating_inputs,
            crowded_hard_layer_threshold=_payload_float(
                camel_get(payload, "crowding_hard_layer_threshold", "crowdingHardLayerThreshold", 75.0), 75.0
            ),
        )
        trade_config = self._theme_trade_config(payload, strategy_name)
        trade_simulation = (
            TradeSimulator().run(frames, execution_signals, trade_config)
            if bool(camel_get(payload, "enable_trade_simulation", "enableTradeSimulation", True))
            else {"enabled": False, "trades": [], "equityCurve": []}
        )

        run_id = new_id("bt")
        request_meta = {
            **payload,
            "dataset_id": dataset_id,
            "snapshot_type": snapshot_type,
            "strategy_name": strategy_name,
            "random_seed": random_seed,
            "engine_config": engine_config,
            "trade_config": trade_config,
        }

        result: dict[str, Any] = {
            "strategyName": strategy_name,
            "analysisMode": "theme_trend",
            "themeTrend": {
                "factorVersion": "theme-factor-v12",
                "signalVersion": "theme-signal-v12",
                "factorCount": len(factors),
                "exposureCount": len(exposures),
                "signalCount": len(signals),
                "factors": factors[:120],
                "signals": signals[:120],
                "exposures": exposures[:120],
                "executionSignalCount": len(execution_signals),
                "tradeSimulation": {
                    "enabled": bool(trade_simulation.get("enabled", False)),
                    "tradeCount": int(trade_simulation.get("tradeCount") or 0),
                    "equityCount": len(trade_simulation.get("equityCurve") or []),
                },
            },
            "signals": signals,
            "signalCount": len(signals),
            "executionSignals": execution_signals[:120],
            "tradeSimulation": trade_simulation,
            "totalReturn": trade_simulation.get("totalReturn"),
            "realizedReturn": trade_simulation.get("realizedReturn"),
            "maxDrawdown": trade_simulation.get("maxDrawdown"),
            "winRate": trade_simulation.get("winRate"),
            "tradeCount": trade_simulation.get("tradeCount"),
            "trades": trade_simulation.get("trades") or [],
            "equityCurve": trade_simulation.get("equityCurve") or [],
            "dataQuality": {
                "passed": not quality_report.get("blocked", False),
                "researchGrade": "degraded" if quality_report.get("warnings") else "research_ready",
                "frameCount": quality_report.get("frameCount", 0),
                "warnings": quality_report.get("warnings", []),
            },
        }
        if gating_inputs and gating_inputs.get("qualityFlags"):
            # 门控 context 的结构化降级原因随 run 落库可观察（fail-visible）
            result["dataQuality"]["themeGatingQualityFlags"] = list(gating_inputs["qualityFlags"])

        trading_dates = sorted({str(f.get("tradingDate") or "") for f in frames if f.get("tradingDate")})
        run = BacktestRun(
            id=run_id,
            dataset_id=dataset_id,
            strategy_name=strategy_name,
            snapshot_type=snapshot_type,
            random_seed=random_seed,
            status="completed",
            config_hash=stable_hash(request_meta),
            date_start=trading_dates[0] if trading_dates else None,
            date_end=trading_dates[-1] if trading_dates else None,
            request_json=dumps_json_field(request_meta),
            result_json=dumps_json_field(result),
        )
        self.repo.save_backtest_run(run)

        if signals:
            signal_rows = [
                {
                    "snapshotId": s.get("snapshotId", ""),
                    "tradingDate": s.get("tradingDate", ""),
                    "code": "",
                    "name": s.get("themeName", ""),
                    "candidateTier": s.get("lifecycle", ""),
                    "signal": s.get("signal", "watch"),
                    "confidence": s.get("score", 0.0),
                    "rank": 0,
                    "reasons": [f"theme_lifecycle:{s.get('lifecycle', '')}"],
                    "riskFlags": [s.get("risk", "")] if s.get("risk") != "none" else [],
                    "mainTheme": s.get("themeName", ""),
                    "themeHeat": 0.0,
                    "themeContribution": 0.0,
                    "themeRole": "",
                    "themeSupportScore": s.get("score", 0.0),
                    "themeRiskFlags": [],
                    "themeReasons": [f"lifecycle:{s.get('lifecycle', '')}"],
                }
                for s in signals
            ]
            self.repo.save_backtest_signal_rows(run_id, signal_rows, append=False)

        self.repo.save_backtest_trades(run_id, trade_simulation.get("trades") or [], append=False)
        self.repo.save_backtest_equity_curve(run_id, trade_simulation.get("equityCurve") or [], append=False)
        self.repo.save_backtest_quality_report(
            run_id, result.get("dataQuality", {}), quality_report,
        )

        return self._summary_response(
            run_id, result,
            {
                "datasetId": dataset_id,
                "dataset_id": dataset_id,
                "strategyName": strategy_name,
                "snapshotType": snapshot_type,
                "randomSeed": random_seed,
                "configHash": run.config_hash,
            },
        )

    def run_theme_confluence(self, payload: dict[str, Any]) -> dict[str, Any]:
        dataset_id = str(camel_get(payload, "dataset_id", "datasetId", ""))
        snapshot_type = str(camel_get(payload, "snapshot_type", "snapshotType", "half_hour"))
        strategy_name = str(camel_get(payload, "strategy_name", "strategyName", "hotlist_theme_confluence"))
        from backend.core.backtest.strategy import THEME_STRATEGY_NAMES
        if strategy_name not in THEME_STRATEGY_NAMES:
            raise ValueError(f"unsupported confluence strategy: {strategy_name}")
        random_seed = int(camel_get(payload, "random_seed", "randomSeed", 20260430))

        frames = self.repo.load_frame_bundles(
            dataset_id, snapshot_type=snapshot_type,
        )
        if not frames:
            raise ValueError(f"dataset has no frames for {snapshot_type}: {dataset_id}")


        confluence_weight = _payload_float(
            camel_get(payload, "persistence_score_weight", "persistenceScoreWeight"), 0.0
        )
        config = ThemeTrendConfig.from_patch(
            {
                "crowdedRiskThreshold": int(camel_get(payload, "maxThemeCrowding", "maxThemeCrowding", 85)),
                "minFrames": 2,
                # 持续性因子进合成分的权重（Phase 4 P4-3 前置接线）：默认 0.0 = 关
                "persistenceScoreWeight": confluence_weight,
                "crowdedHardLayerThreshold": _payload_float(
                    camel_get(payload, "crowding_hard_layer_threshold", "crowdingHardLayerThreshold", 75.0), 75.0
                ),
            }
        )
        # 日级持续性原料注入（Path B）：仅 weight>0 时读库，默认路径零 IO
        confluence_daily = None
        if confluence_weight > 0:
            from backend.services.theme.daily_factors_service import load_daily_persistence_inputs

            confluence_days = sorted({str(f.get("tradingDate") or "") for f in frames} - {""})
            confluence_daily, confluence_source_flags = load_daily_persistence_inputs(dataset_id, confluence_days)
        theme_result = ThemeTrendPythonEngine().replay_sequence(frames, config=config, daily_factors=confluence_daily)
        if confluence_weight > 0 and confluence_source_flags:
            theme_result["qualityReport"]["warnings"] = list(dict.fromkeys(
                [*theme_result["qualityReport"].get("warnings", []), *confluence_source_flags]
            ))

        rank_trend_control: dict[str, Any] = {}
        rank_frames: list[dict[str, Any]] = []
        rank_signals: list[dict[str, Any]] = []
        try:
            rank_frames = self.repo.load_frames(
                dataset_id, snapshot_type=snapshot_type, include_payload=True,
            )
            if rank_frames:
                rank_config = RankTrendConfig()
                from backend.services.theme.hotlist_sentiment_service import make_hotlist_sentiment_provider
                rank_signals = RankTrendPythonEngine(
                    rank_config,
                    sentiment_provider=make_hotlist_sentiment_provider(dataset_id, snapshot_type),
                ).replay(rank_frames)
                rank_trend_control = {
                    "signalCount": len(rank_signals),
                    "description": "RankTrend-only 控制组基线",
                }
        except Exception as exc:
            rank_trend_control = {
                "error": "RankTrend control baseline unavailable",
                "reason": str(exc)[:200],
            }

        run_id = new_id("bt")
        request_meta = {
            **payload,
            "dataset_id": dataset_id,
            "snapshot_type": snapshot_type,
            "strategy_name": strategy_name,
            "random_seed": random_seed,
        }

        quality_report = theme_result.get("qualityReport", {})
        signals = theme_result.get("signals", [])
        factors = theme_result.get("factors", [])
        exposures = theme_result.get("exposures", [])
        execution_frames = rank_frames or frames
        execution_signals = self._confluence_execution_signals(
            rank_signals, factors, exposures,
            crowded_hard_layer_threshold=_payload_float(
                camel_get(payload, "crowding_hard_layer_threshold", "crowdingHardLayerThreshold", 75.0), 75.0
            ),
        )
        trade_config = self._theme_trade_config(payload, strategy_name)
        trade_simulation = (
            TradeSimulator().run(execution_frames, execution_signals, trade_config)
            if bool(camel_get(payload, "enable_trade_simulation", "enableTradeSimulation", True))
            else {"enabled": False, "trades": [], "equityCurve": []}
        )
        result: dict[str, Any] = {
            "strategyName": strategy_name,
            "analysisMode": "theme_confluence",
            "themeTrend": {
                "factorVersion": "theme-factor-v12",
                "signalVersion": "theme-signal-v12",
                "signals": signals[:120],
                "signalCount": len(signals),
                "executionSignalCount": len(execution_signals),
                "rankTrendControl": rank_trend_control,
                "tradeSimulation": {
                    "enabled": bool(trade_simulation.get("enabled", False)),
                    "tradeCount": int(trade_simulation.get("tradeCount") or 0),
                    "equityCount": len(trade_simulation.get("equityCurve") or []),
                },
            },
            "signals": signals,
            "signalCount": len(signals),
            "executionSignals": execution_signals[:120],
            "tradeSimulation": trade_simulation,
            "totalReturn": trade_simulation.get("totalReturn"),
            "realizedReturn": trade_simulation.get("realizedReturn"),
            "maxDrawdown": trade_simulation.get("maxDrawdown"),
            "winRate": trade_simulation.get("winRate"),
            "tradeCount": trade_simulation.get("tradeCount"),
            "trades": trade_simulation.get("trades") or [],
            "equityCurve": trade_simulation.get("equityCurve") or [],
            "dataQuality": {
                "passed": not quality_report.get("blocked", False),
                "researchGrade": "degraded" if quality_report.get("warnings") else "research_ready",
                "warnings": quality_report.get("warnings", []),
            },
            "isCompact": True,
            "notes": [f"共振策略：RankTrend 候选为主，ThemeTrend 辅助排序/拥挤降级。完整结果已落库：{run_id}"],
        }

        trading_dates = sorted({str(f.get("tradingDate") or "") for f in frames if f.get("tradingDate")})
        run = BacktestRun(
            id=run_id,
            dataset_id=dataset_id,
            strategy_name=strategy_name,
            snapshot_type=snapshot_type,
            random_seed=random_seed,
            status="completed",
            config_hash=stable_hash(request_meta),
            date_start=trading_dates[0] if trading_dates else None,
            date_end=trading_dates[-1] if trading_dates else None,
            request_json=dumps_json_field(request_meta),
            result_json=dumps_json_field(result),
        )
        self.repo.save_backtest_run(run)
        if signals:
            signal_rows = [
                {
                    "snapshotId": s.get("snapshotId", ""),
                    "tradingDate": s.get("tradingDate", ""),
                    "code": "",
                    "name": s.get("themeName", ""),
                    "candidateTier": s.get("lifecycle", ""),
                    "signal": s.get("signal", "watch"),
                    "confidence": s.get("score", 0.0),
                    "rank": 0,
                    "reasons": [f"confluence:{s.get('lifecycle', '')}"],
                    "riskFlags": [s.get("risk", "")] if s.get("risk") != "none" else [],
                    "mainTheme": s.get("themeName", ""),
                    "themeHeat": 0.0,
                    "themeContribution": 0.0,
                    "themeRole": "",
                    "themeSupportScore": s.get("score", 0.0),
                    "themeRiskFlags": [],
                    "themeReasons": [f"confluence_lifecycle:{s.get('lifecycle', '')}"],
                }
                for s in signals
            ]
            self.repo.save_backtest_signal_rows(run_id, signal_rows, append=False)
        self.repo.save_backtest_trades(run_id, trade_simulation.get("trades") or [], append=False)
        self.repo.save_backtest_equity_curve(run_id, trade_simulation.get("equityCurve") or [], append=False)
        self.repo.save_backtest_quality_report(
            run_id, result.get("dataQuality", {}), quality_report,
        )

        return self._summary_response(
            run_id, result,
            {
                "datasetId": dataset_id,
                "dataset_id": dataset_id,
                "strategyName": strategy_name,
                "snapshotType": snapshot_type,
                "randomSeed": random_seed,
                "configHash": run.config_hash,
            },
        )

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        run = self.repo.get_backtest_run(run_id)
        if not run:
            return None
        result = loads_json_field(run.result_json, {})
        data_quality = result.get("dataQuality")
        if isinstance(data_quality, dict):
            result["dataQuality"] = self._normalize_data_quality(run.dataset_id, data_quality)
        compact = self._summary_response(run.id, result)
        return {
            **compact,
            "id": run.id,
            "runId": run.id,
            "datasetId": run.dataset_id,
            "dataset_id": run.dataset_id,
            "strategyName": run.strategy_name,
            "strategyVersion": run.strategy_version,
            "snapshotType": run.snapshot_type,
            "randomSeed": run.random_seed,
            "configHash": run.config_hash,
            "createdAt": run.created_at.isoformat(),
        }

    def list_runs(self, *, limit: int = 50) -> dict[str, Any]:
        rows, total = self.repo.list_backtest_runs(limit=limit)
        return {
            "items": [self._run_option(row) for row in rows],
            "limit": max(1, min(int(limit), 200)),
            "total": total,
        }

    @staticmethod
    def _run_option(run: BacktestRun) -> dict[str, Any]:
        return {
            "id": run.id,
            "runId": run.id,
            "datasetId": run.dataset_id,
            "dataset_id": run.dataset_id,
            "strategyName": run.strategy_name,
            "strategyVersion": run.strategy_version,
            "snapshotType": run.snapshot_type,
            "configHash": run.config_hash,
            "randomSeed": run.random_seed,
            "status": run.status,
            "dateStart": run.date_start,
            "dateEnd": run.date_end,
            "errorReason": run.error_reason,
            "createdAt": run.created_at.isoformat() if run.created_at else None,
            "finishedAt": run.finished_at.isoformat() if run.finished_at else None,
        }

    def get_trades(self, run_id: str, limit: int = 100, offset: int = 0) -> dict[str, Any] | None:
        if not self.repo.get_backtest_run(run_id):
            return None
        self._validate_pagination(limit, offset)
        items = self.repo.get_backtest_trades(run_id, limit=limit, offset=offset)
        source = storage_source_label()
        total = self.repo.count_backtest_trades(run_id)
        return {
            "runId": run_id,
            "items": items,
            "limit": limit,
            "offset": offset,
            "total": total,
            "source": source,
        }

    def get_equity(self, run_id: str) -> dict[str, Any] | None:
        if not self.repo.get_backtest_run(run_id):
            return None
        items = self.repo.get_backtest_equity_curve(run_id)
        source = storage_source_label()
        return {"runId": run_id, "items": items, "source": source}

    def get_signals(
        self,
        run_id: str,
        limit: int = 200,
        offset: int = 0,
        tier: str | None = None,
        regime: str | None = None,
    ) -> dict[str, Any] | None:
        if not self.repo.get_backtest_run(run_id):
            return None
        self._validate_pagination(limit, offset)
        items = self.repo.get_backtest_signals(run_id, limit=limit, offset=offset, tier=tier, regime=regime)
        total = self.repo.count_backtest_signals(run_id, tier=tier, regime=regime)
        source = storage_source_label()
        return {
            "runId": run_id,
            "items": items,
            "filters": {"tier": tier, "regime": regime},
            "limit": limit,
            "offset": offset,
            "total": total,
            "source": source,
        }

    def get_quality(self, run_id: str) -> dict[str, Any] | None:
        run = self.repo.get_backtest_run(run_id)
        if not run:
            return None
        quality = self.repo.get_backtest_quality_report(run_id)
        if quality is None:
            return {"runId": run_id, "qualityReport": None}
        result = loads_json_field(run.result_json, {})
        data_quality = result.get("dataQuality") if isinstance(result.get("dataQuality"), dict) else {}
        normalized_quality = dict(quality)
        if data_quality:
            normalized_data_quality = self._normalize_data_quality(run.dataset_id, data_quality)
            warnings = normalized_data_quality.get("warnings")
            if isinstance(warnings, list):
                normalized_quality["warnings"] = warnings
        dataset = self.repo.get_dataset(run.dataset_id)
        if dataset is not None:
            if not int(normalized_quality.get("stockCount") or 0):
                normalized_quality["stockCount"] = int(dataset.stock_row_count or 0)
            if not int(normalized_quality.get("sectorCount") or 0):
                normalized_quality["sectorCount"] = int(dataset.sector_row_count or 0)
        return {"runId": run_id, "qualityReport": normalized_quality}

    def delete_run(self, run_id: str) -> dict[str, Any] | None:
        return self.repo.delete_backtest_run(run_id, checkpoint=True)

    def research_storage_summary(self) -> dict[str, Any]:
        return self.repo.research_storage_summary()

    def vacuum_research_sqlite(self) -> dict[str, Any]:
        return self.repo.vacuum_research_sqlite()

    def cleanup_research(self, payload: dict[str, Any], *, apply: bool = False) -> dict[str, Any]:
        older_than_days = int(payload.get("olderThanDays") or payload.get("older_than_days") or 30)
        keep_latest = int(payload.get("keepLatestPerGroup") or payload.get("keep_latest_per_group") or 10)
        if older_than_days < 0:
            raise ValueError({"code": "invalid_cleanup_request", "field": "olderThanDays"})
        if keep_latest < 0:
            raise ValueError({"code": "invalid_cleanup_request", "field": "keepLatestPerGroup"})
        if apply and not bool(payload.get("confirm")):
            raise ValueError({"code": "cleanup_confirmation_required", "message": "confirm=true is required"})
        return self.repo.cleanup_research_backtests(
            older_than_days=older_than_days,
            keep_latest_per_group=keep_latest,
            dataset_id=str(payload.get("datasetId") or payload.get("dataset_id") or "") or None,
            snapshot_type=str(payload.get("snapshotType") or payload.get("snapshot_type") or "") or None,
            include_failed=bool(payload.get("includeFailed") or payload.get("include_failed")),
            apply=apply,
            checkpoint=apply,
        )

    @staticmethod
    def _theme_trade_config(payload: dict[str, Any], strategy_name: str) -> dict[str, Any]:
        patch = camel_get(payload, "trade_config", "tradeConfig", {}) or {}
        trade_defaults = trade_defaults_for_strategy(strategy_name)
        config = {
            "initialCapital": camel_get(payload, "initial_cash", "initialCash", trade_defaults["initialCapital"]),
            "maxPositions": camel_get(payload, "max_positions", "maxPositions", trade_defaults["maxPositions"]),
            "positionSize": camel_get(payload, "position_size", "positionSize", trade_defaults["positionSize"]),
            "minJumpConfidence": camel_get(
                payload,
                "min_jump_confidence",
                "minJumpConfidence",
                trade_defaults["minJumpConfidence"],
            ),
            "takeProfit": camel_get(payload, "take_profit_pct", "takeProfitPct", trade_defaults["takeProfit"]),
            "stopLoss": -abs(float(camel_get(payload, "stop_loss_pct", "stopLossPct", abs(trade_defaults["stopLoss"])))),
            "maxHoldingBars": camel_get(payload, "max_holding_bars", "maxHoldingBars", trade_defaults["maxHoldingBars"]),
            "targetHoldingDays": camel_get(payload, "target_holding_days", "targetHoldingDays", trade_defaults["targetHoldingDays"]),
            "maxThemeExposure": camel_get(payload, "max_theme_exposure", "maxThemeExposure", 0.45),
            "enforceT1": camel_get(payload, "enforce_t1", "enforceT1", trade_defaults["enforceT1"]),
            "executionMode": camel_get(payload, "execution_mode", "executionMode", trade_defaults["executionMode"]),
            "feeRate": camel_get(payload, "fee_rate", "feeRate", trade_defaults["feeRate"]),
            "stampTaxRate": camel_get(payload, "stamp_tax_rate", "stampTaxRate", trade_defaults["stampTaxRate"]),
            "slippageRate": camel_get(payload, "slippage_rate", "slippageRate", trade_defaults["slippageRate"]),
            "useOrderBookPrice": camel_get(payload, "use_order_book_price", "useOrderBookPrice", trade_defaults["useOrderBookPrice"]),
            "enforceLimitStatus": camel_get(payload, "enforce_limit_status", "enforceLimitStatus", trade_defaults["enforceLimitStatus"]),
            "enforceVolumeLimit": camel_get(payload, "enforce_volume_limit", "enforceVolumeLimit", trade_defaults["enforceVolumeLimit"]),
            "enforceOrderBookQueue": camel_get(payload, "enforce_order_book_queue", "enforceOrderBookQueue", trade_defaults["enforceOrderBookQueue"]),
            "allowPartialFills": camel_get(payload, "allow_partial_fills", "allowPartialFills", trade_defaults["allowPartialFills"]),
            "volumeParticipationRate": camel_get(payload, "volume_participation_rate", "volumeParticipationRate", trade_defaults["volumeParticipationRate"]),
            "orderBookParticipationRate": camel_get(payload, "order_book_participation_rate", "orderBookParticipationRate", trade_defaults["orderBookParticipationRate"]),
            "useIntrabarStops": camel_get(payload, "use_intrabar_stops", "useIntrabarStops", trade_defaults["useIntrabarStops"]),
            "intrabarAmbiguity": camel_get(payload, "intrabar_ambiguity", "intrabarAmbiguity", trade_defaults["intrabarAmbiguity"]),
            "entryStrategy": strategy_name,
        }
        config = _apply_trade_config_defaults_and_patch(config, trade_defaults, patch)
        config["entryStrategy"] = strategy_name
        return config

    def _theme_sg_inputs(self, dataset_id: str, frames: list[dict[str, Any]]) -> dict[str, Any]:
        """SG 变体输入预计算（Phase R3，fail-visible：缺失打标，不伪造触发）。

        - SG2 序列：frames 中每日 15:00 帧的题材 rotationState（缺失日补 None）；
        - SG1（R3b 口径修正）：frames 15:00 帧题材 change 收盘槽序列——daily 类型
          7 月仅 15 天曾结构性饿死 SG1（全 248 题材 insufficient）。严格出勤语义：
          题材 span 内 15:00 日历日全出勤、相邻日历日自然间隔 >7 天截断（4-5 月空洞）、
          不足 2 天或缺勤 → 整题材 sg1_insufficient 计数、全 None（_sg1_close_slot_flags）；
        - SG3：daily 收盘横截面（snapshot_type="daily" 硬过滤，R1 锚点口径）的
          mainNetInflow 日序列（15:00 口径另批评估，一次一变量）；
        - mainLines /（诊断用）按 15:00 帧 rotationSummary 提取；None=缺失、[]=引擎判定无主线。
        返回 {sgFlags: {theme: {date: {sg1,sg2,sg3}}}, mainlineNamesByDay: {date: list|None},
        qualityFlags: [str]}。
        """
        days = sorted({str(f.get("tradingDate")) for f in frames if f.get("tradingDate")})
        quality_flags: list[str] = []
        if not days:
            return {"sgFlags": {}, "mainlineNamesByDay": {}, "qualityFlags": ["no_trading_days"]}

        rotation_by_theme: dict[str, dict[str, str | None]] = {}
        close_changes_by_theme: dict[str, dict[str, float | None]] = {}
        mainlines_by_day: dict[str, list[str] | None] = {}
        day_has_15h: set[str] = set()
        for frame in frames:
            if str(frame.get("slotTime")) != "15:00":
                continue
            d = str(frame.get("tradingDate") or "")
            day_has_15h.add(d)
            for row in frame.get("entities") or frame.get("hotThemes") or []:
                if not isinstance(row, dict):
                    continue
                # 只排除 H4 派生主线行；真实数据为 hot_theme、测试夹具落库为 sector，
                # 白名单会在任一环境漏收（2026-09-26 调试实证）。
                if str(row.get("entityType") or "") == "rotation_main_line":
                    continue
                name = str(row.get("entityName") or "")
                if name:
                    rotation_by_theme.setdefault(name, {})[d] = str(row.get("rotationState") or "") or None
                    chg = row.get("change")
                    # 落库 change 为百分数单位（2.5=+2.5%），rrg_quadrants 虚拟指数契约是
                    # 小数（0.025=+2.5%）——此处统一换算，防止 RS 水平分类被量纲扭曲。
                    close_changes_by_theme.setdefault(name, {})[d] = (
                        float(chg) / 100.0 if isinstance(chg, (int, float)) else None
                    )
            rs = frame.get("rotationSummary") or {}
            ml = rs.get("mainLines")
            mainlines_by_day[d] = (
                [str(m.get("themeName")) for m in ml if isinstance(m, dict) and m.get("themeName")]
                if isinstance(ml, list)
                else None
            )
        for d in days:
            if d not in day_has_15h:
                quality_flags.append(f"missing_15h_frame:{d}")
                mainlines_by_day.setdefault(d, None)
        for seq in rotation_by_theme.values():
            for d in days:
                seq.setdefault(d, None)

        inflow_by_theme: dict[str, dict[str, float | None]] = {}
        res = self.repo.list_snapshot_sector_rows(
            dataset_id,
            start_date=days[0],
            end_date=days[-1],
            snapshot_type="daily",
            entity_type="hot_theme",
            sort="asc",
        )
        for d, rows in _close_slot_rows_by_day(res.get("rows") or []).items():
            for row in rows:
                name = str(row.get("entityName") or "")
                if not name:
                    continue
                inflow = row.get("mainNetInflow")
                inflow_by_theme.setdefault(name, {})[d] = float(inflow) if isinstance(inflow, (int, float)) else None

        # SG1 基准：SG1 日历日（有 ≥1 题材 15:00 change）全题材等权 change 均值
        sg1_calendar = sorted({
            d
            for seq in close_changes_by_theme.values()
            for d, v in seq.items()
            if v is not None
        })
        benchmark_close: dict[str, float] = {}
        for d in sg1_calendar:
            vals = [seq[d] for seq in close_changes_by_theme.values() if seq.get(d) is not None]
            benchmark_close[d] = sum(vals) / len(vals)

        sg_flags: dict[str, dict[str, dict[str, bool | None]]] = {}
        sg1_insufficient = 0
        all_themes = sorted(set(rotation_by_theme) | set(close_changes_by_theme) | set(inflow_by_theme))
        for name in all_themes:
            entry = sg_flags.setdefault(name, {})
            sg1_flags, sg1_ok = _sg1_close_slot_flags(
                close_changes_by_theme.get(name) or {}, benchmark_close
            )
            if not sg1_ok:
                sg1_insufficient += 1
            sg2_flags = sg2_rotation_switch_flags({d: (rotation_by_theme.get(name) or {}).get(d) for d in days})
            inflow_seq = inflow_by_theme.get(name) or {}
            sg3_flags = sg3_inflow_turn_positive_flags({d: inflow_seq.get(d) for d in days}, positive_min_days=1)
            for d in days:
                entry[d] = {"sg1": sg1_flags.get(d), "sg2": sg2_flags.get(d), "sg3": sg3_flags.get(d)}
        if sg1_insufficient:
            quality_flags.append(f"sg1_insufficient_count:{sg1_insufficient}")
        return {
            "sgFlags": sg_flags,
            "mainlineNamesByDay": mainlines_by_day,
            "qualityFlags": quality_flags,
        }

    @staticmethod
    def _theme_gating_inputs(
        frames: list[dict[str, Any]],
        dataset_id: str,
        *,
        include_crowding_percentile: bool,
    ) -> dict[str, Any]:
        """条件层门控 context（设计 §5.3，Task2 接线）。

        情绪维：half_hour 15:00 帧 rotationSummary.marketPhase（引擎权威口径，
        对齐 _theme_sg_inputs 取数）；缺失 15:00 帧的交易日 → None + missing 标记。
        拥挤度分位维（可选）：读 theme_daily_factors 落库行（Task1），仅 mongodb
        后端；非 Mongo / 读失败 / 无行 → 显式降级标记。
        消费端（_theme_execution_signals）对 None 值不调整——不伪造中性门控。
        """
        market_phase_by_day: dict[str, str | None] = {}
        day_has_15h: set[str] = set()
        for frame in frames:
            if str(frame.get("slotTime")) != "15:00":
                continue
            d = str(frame.get("tradingDate") or "")
            day_has_15h.add(d)
            rotation_summary = frame.get("rotationSummary")
            phase = rotation_summary.get("marketPhase") if isinstance(rotation_summary, dict) else None
            market_phase_by_day[d] = str(phase or "") or None
        all_days = sorted({str(f.get("tradingDate") or "") for f in frames if f.get("tradingDate")})
        quality_flags: list[str] = []
        for d in all_days:
            if d not in day_has_15h:
                quality_flags.append(f"missing_15h_frame:{d}")
                market_phase_by_day.setdefault(d, None)
        crowding_by_theme_day: dict[str, dict[str, float | None]] = {}
        if include_crowding_percentile:
            if get_settings().storage_backend != "mongodb":
                quality_flags.append("crowding_percentile_source_unavailable:storage_backend_not_mongodb")
            elif not all_days:
                quality_flags.append("crowding_percentile_source_unavailable:no_trading_days")
            else:
                try:
                    factor_repo = ThemeDailyFactorRepository(get_runtime_mongodb_database())
                    docs = factor_repo.list_range(dataset_id, all_days[0], all_days[-1])
                    for doc in docs:
                        factors_doc = doc.get("factors")
                        percentile = factors_doc.get("crowdingPercentile") if isinstance(factors_doc, dict) else None
                        value = float(percentile) if isinstance(percentile, (int, float)) else None
                        d = str(doc.get("tradingDate") or "")
                        # themeId 与 themeName 双键：信号层按 entityName 查，分位行按映射 themeId 存
                        for key in {str(doc.get("themeId") or ""), str(doc.get("themeName") or "")} - {""}:
                            crowding_by_theme_day.setdefault(key, {})[d] = value
                    if not docs:
                        quality_flags.append("crowding_percentile_no_rows")
                except Exception as exc:
                    quality_flags.append(f"crowding_percentile_source_unavailable:{exc}")
        return {
            "marketPhaseByDay": market_phase_by_day,
            "crowdingPercentileByDay": crowding_by_theme_day,
            "qualityFlags": quality_flags,
        }

    @staticmethod
    def _theme_execution_signals(
        frames: list[dict[str, Any]],
        factors: list[dict[str, Any]],
        exposures: list[dict[str, Any]],
        strategy_name: str,
        sg_inputs: dict[str, Any] | None = None,
        gating_inputs: dict[str, Any] | None = None,
        crowded_hard_layer_threshold: float = 75.0,
    ) -> list[dict[str, Any]]:
        factor_by_snapshot_theme = {
            (str(factor.get("snapshotId") or ""), str(factor.get("themeName") or "")): factor
            for factor in factors
        }
        exposure_by_snapshot_code = {
            (str(exposure.get("snapshotId") or ""), str(exposure.get("code") or "")): exposure
            for exposure in exposures
            if exposure.get("code")
        }
        output: list[dict[str, Any]] = []
        for frame in frames:
            snapshot_id = str(frame.get("snapshotId") or "")
            trading_date = str(frame.get("tradingDate") or "")
            for stock in frame.get("stocks") or frame.get("rows") or frame.get("hotlist") or []:
                if not isinstance(stock, dict):
                    continue
                code = str(stock.get("code") or "")
                if not code:
                    continue
                exposure = exposure_by_snapshot_code.get((snapshot_id, code))
                theme_name = str((exposure or {}).get("themeName") or stock.get("mainTheme") or "")
                factor = factor_by_snapshot_theme.get((snapshot_id, theme_name), {})
                # D5：lifecycle 状态机废弃，执行分层改用 rotationState 方向标签 + 拥挤度
                lifecycle = str(factor.get("lifecycle") or "neutral")  # 仅解释字段
                rotation_state = str(factor.get("rotationState") or "neutral")
                crowding = float(factor.get("crowdingRisk") or 0)
                contribution = float((exposure or {}).get("themeContribution") or stock.get("themeContribution") or 0)
                exposure_weight = float((exposure or {}).get("exposureWeight") or stock.get("themeExposureWeight") or 0)
                tier = "N_NEUTRAL"
                if crowding >= crowded_hard_layer_threshold:
                    tier = "C_CROWDED"
                elif rotation_state in {"mainline", "inflow"} and (exposure_weight >= 55 or contribution >= 8):
                    tier = "A_MAIN"
                elif rotation_state == "inflow":
                    tier = "B_IGNITION"
                elif rotation_state in {"outflow"}:
                    tier = "D_EXIT_RISK"
                role = str((exposure or {}).get("role") or stock.get("themeRole") or "")
                heat_level = _persisted_heat_level(factor)
                confidence = min(100.0, max(0.0, exposure_weight or heat_level))
                theme_risk_flags = [f"crowding:{crowding}"] if crowding >= crowded_hard_layer_threshold else []
                theme_reasons = [f"lifecycle:{lifecycle}", f"strategy:{strategy_name}"]
                confluence_score = round(
                    min(100.0, max(0.0, heat_level * 0.45 + exposure_weight * 0.35 + contribution * 0.8)),
                    2,
                )
                # B10（评审 M4）：透传展示字段改吃 heatLevel 相对分（0-100），不再透传
                # 绝对值；缺失回退 stock 行 themeHeat，仍缺失按 0.0（展示合成项语义）。
                raw_theme_heat = resolve_heat_level(factor)
                if raw_theme_heat is None:
                    raw_theme_heat = stock.get("themeHeat")
                if strategy_name == "leader_theme_confirmation":
                    if role == "leader" and tier in {"A_MAIN", "B_IGNITION"} and crowding < crowded_hard_layer_threshold:
                        theme_reasons.append("leader_confirmation")
                        confidence = min(100.0, confidence + 6.0)
                    else:
                        tier = "D_EXIT_RISK" if lifecycle in {"cooling", "reversal"} or crowding >= crowded_hard_layer_threshold else "N_NEUTRAL"
                        theme_risk_flags.append("leader_required")
                        theme_reasons.append("leader_downgraded_to_watch")
                elif strategy_name == "hotlist_theme_confluence":
                    if confluence_score >= 75 and tier in {"A_MAIN", "B_IGNITION"} and crowding < crowded_hard_layer_threshold:
                        theme_reasons.append("hotlist_confluence")
                        confidence = min(100.0, max(confidence, confluence_score))
                    elif confluence_score < 45 or role == "noise":
                        tier = "N_NEUTRAL"
                        theme_risk_flags.append("theme_noise_or_weak_confluence")
                        theme_reasons.append("hotlist_filtered")
                elif strategy_name == "theme_rotation_chase" and sg_inputs is not None:
                    # R3 变体：SG 驱动补涨——退出/拥挤优先保持，触发给 B_IGNITION（不给 A_MAIN）
                    sg_hit, sg_sources = _theme_sg_hit(sg_inputs, theme_name, trading_date)
                    if tier not in {"C_CROWDED", "D_EXIT_RISK"}:
                        tier = "B_IGNITION" if sg_hit else "N_NEUTRAL"
                    theme_reasons.extend(sg_sources)
                elif strategy_name == "theme_state_hybrid" and sg_inputs is not None:
                    # R3 变体：引擎 mainLines 非空日走主线确认规则（保留初判），空/缺失日走 SG 补涨
                    sg_hit, sg_sources = _theme_sg_hit(sg_inputs, theme_name, trading_date)
                    mainlines = (sg_inputs.get("mainlineNamesByDay") or {}).get(trading_date)
                    if isinstance(mainlines, list) and mainlines:
                        if theme_name not in mainlines and tier != "C_CROWDED":
                            tier = "N_NEUTRAL"
                            theme_risk_flags.append("not_in_engine_mainlines")
                        theme_reasons.append("engine_mainline_day")
                    else:
                        if mainlines is None:
                            theme_risk_flags.append("missing_mainlines")
                        if tier not in {"C_CROWDED", "D_EXIT_RISK"}:
                            tier = "B_IGNITION" if sg_hit else "N_NEUTRAL"
                        theme_reasons.extend(sg_sources)
                else:
                    theme_reasons.append("theme_rotation")
                if gating_inputs and tier in {"A_MAIN", "B_IGNITION"}:
                    # 条件层门控（设计 §5.3）：只降可信 + 打标，不改 tier（不做硬门禁）；
                    # 相位缺失/分位缺失 → 不调整不伪造；两门控可叠加。
                    phase = (gating_inputs.get("marketPhaseByDay") or {}).get(trading_date)
                    if phase and phase in (gating_inputs.get("sentimentPhases") or ()):
                        confidence = min(100.0, max(0.0, confidence - _gating_number(gating_inputs.get("sentimentConfidencePenalty"))))
                        theme_reasons.append(f"sentiment_gate:{phase}")
                        theme_risk_flags.append(f"sentiment_phase:{phase}")
                    percentile = ((gating_inputs.get("crowdingPercentileByDay") or {}).get(theme_name) or {}).get(trading_date)
                    threshold = gating_inputs.get("crowdingPercentileHighThreshold")
                    if (
                        isinstance(percentile, (int, float))
                        and isinstance(threshold, (int, float))
                        and percentile >= threshold
                    ):
                        confidence = min(100.0, max(0.0, confidence - _gating_number(gating_inputs.get("crowdingPercentileConfidencePenalty"))))
                        theme_reasons.append(f"crowding_percentile_high:{round(float(percentile), 1)}")
                        theme_risk_flags.append("crowding_percentile_high")
                output.append({
                    **stock,
                    "snapshotId": snapshot_id,
                    "timestamp": frame.get("timestamp"),
                    "tradingDate": frame.get("tradingDate"),
                    "slotTime": frame.get("slotTime"),
                    "code": code,
                    "name": stock.get("name") or code,
                    "rank": int(stock.get("rank") or 999),
                    "candidateTier": tier,
                    "regime": "strong" if tier in {"A_MAIN", "B_IGNITION"} else "weak",
                    "confidence": confidence,
                    # D5：lifecycle 状态机废弃，stage 输出 rotationState 方向标签（报告分组口径）
                    "stage": rotation_state,
                    "rankTrend": {"strategy": {"momentum": {"acceleration": 1 if tier != "D_EXIT_RISK" else -1}}},
                    "mainTheme": theme_name,
                    "themeHeat": float(raw_theme_heat) if raw_theme_heat is not None else 0.0,
                    "themeContribution": contribution,
                    "themeRole": role,
                    "themeSupportScore": exposure_weight,
                    "themeConfluenceScore": confluence_score,
                    "themeRiskFlags": theme_risk_flags,
                    "themeReasons": theme_reasons,
                })
        return output

    @staticmethod
    def _confluence_execution_signals(
        rank_signals: list[dict[str, Any]],
        factors: list[dict[str, Any]],
        exposures: list[dict[str, Any]],
        crowded_hard_layer_threshold: float = 75.0,
    ) -> list[dict[str, Any]]:
        factor_by_snapshot_theme = {
            (str(factor.get("snapshotId") or ""), str(factor.get("themeName") or "")): factor
            for factor in factors
        }
        exposure_by_snapshot_code = {
            (str(exposure.get("snapshotId") or ""), str(exposure.get("code") or "")): exposure
            for exposure in exposures
            if exposure.get("code")
        }
        output: list[dict[str, Any]] = []
        for signal in rank_signals:
            snapshot_id = str(signal.get("snapshotId") or "")
            code = str(signal.get("code") or "")
            exposure = exposure_by_snapshot_code.get((snapshot_id, code))
            theme_name = str((exposure or {}).get("themeName") or signal.get("mainTheme") or "")
            factor = factor_by_snapshot_theme.get((snapshot_id, theme_name), {})
            lifecycle = str(factor.get("lifecycle") or "neutral")
            crowding = float(factor.get("crowdingRisk") or 0)
            item = dict(signal)
            item["mainTheme"] = theme_name
            # B10：与 _theme_execution_signals 同口径，themeHeat 透传相对分
            raw_theme_heat = resolve_heat_level(factor)
            if raw_theme_heat is None:
                raw_theme_heat = signal.get("themeHeat")
            item["themeHeat"] = float(raw_theme_heat) if raw_theme_heat is not None else 0.0
            item["themeContribution"] = float((exposure or {}).get("themeContribution") or signal.get("themeContribution") or 0)
            item["themeRole"] = (exposure or {}).get("role") or signal.get("themeRole") or ""
            item["themeSupportScore"] = float((exposure or {}).get("exposureWeight") or signal.get("themeSupportScore") or 0)
            item["themeReasons"] = [*([str(v) for v in signal.get("themeReasons") or []]), f"theme_lifecycle:{lifecycle}"]
            item["themeRiskFlags"] = [*([str(v) for v in signal.get("themeRiskFlags") or []])]
            if lifecycle in {"cooling", "reversal"} or crowding >= crowded_hard_layer_threshold:
                item["candidateTier"] = "D_EXIT_RISK"
                item["regime"] = "retreat"
                item["themeRiskFlags"].append("theme_blocked")
            elif lifecycle in {"mainline", "expansion", "ignition"} and item.get("candidateTier") in {"A_MAIN", "B_IGNITION"}:
                item["confidence"] = min(100.0, float(item.get("confidence") or 0) + 5.0)
            output.append(item)
        return output

    def compare_runs(self, run_ids: list[str], metrics: list[str] | None = None) -> dict[str, Any]:
        metric_names = metrics or ["totalReturn", "sharpe", "maxDrawdown", "winRate"]
        invalid = [metric for metric in metric_names if metric not in BACKTEST_COMPARE_METRICS]
        if invalid:
            raise ValueError(
                {
                    "code": "invalid_backtest_metric",
                    "metric": invalid[0],
                    "allowedMetrics": sorted(BACKTEST_COMPARE_METRICS),
                }
            )
        runs = []
        for run_id in run_ids:
            run = self.repo.get_backtest_run(run_id)
            if not run:
                raise LookupError(run_id)
            result = loads_json_field(run.result_json, {})
            metric_values = {metric: self._metric_value(result, metric) for metric in metric_names}
            missing = [metric for metric, value in metric_values.items() if value is None]
            item = {
                "runId": run.id,
                "datasetId": run.dataset_id,
                "snapshotType": run.snapshot_type,
                "strategyName": run.strategy_name,
                "strategyVersion": run.strategy_version,
                "configHash": run.config_hash,
                "randomSeed": run.random_seed,
                "metrics": metric_values,
            }
            if missing:
                item["missingMetrics"] = missing
            runs.append(item)
        return {"runs": runs, "metrics": metric_names}

    def export_report(self, run_id: str) -> dict[str, Any] | None:
        run = self.repo.get_backtest_run(run_id)
        if not run:
            return None
        result = loads_json_field(run.result_json, {})
        return {
            "runId": run.id,
            "datasetId": run.dataset_id,
            "snapshotType": run.snapshot_type,
            "strategyName": run.strategy_name,
            "strategyVersion": run.strategy_version,
            "configHash": run.config_hash,
            "randomSeed": run.random_seed,
            "request": loads_json_field(run.request_json, {}),
            "metrics": {metric: self._metric_value(result, metric) for metric in sorted(BACKTEST_COMPARE_METRICS)},
            "trades": self.repo.get_backtest_trades(run_id),
            "equityCurve": self.repo.get_backtest_equity_curve(run_id),
            "signals": self.repo.get_backtest_signals(run_id),
            "qualityReport": self.repo.get_backtest_quality_report(run_id),
            "result": result,
        }

    @staticmethod
    def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
        count = 0
        with path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json_dumps(row))
                handle.write("\n")
                count += 1
        return count

    @staticmethod
    def _write_json_array(handle: Any, rows: Iterable[dict[str, Any]]) -> int:
        count = 0
        handle.write("[")
        for row in rows:
            if count:
                handle.write(",")
            handle.write(json_dumps(row))
            count += 1
        handle.write("]")
        return count

    def export_report_bundle(self, run_id: str, output: Path) -> dict[str, Any]:
        run = self.repo.get_backtest_run(run_id)
        if not run:
            return {"ok": False, "error": {"code": "backtest_run_not_found", "runId": run_id}}

        tmp_output = output.with_name(f"{output.name}.tmp")
        tmp_output.mkdir(parents=True, exist_ok=True)
        result = loads_json_field(run.result_json, {})
        request = loads_json_field(run.request_json, {})

        signals_count = self._write_jsonl(tmp_output / "signals.jsonl", self.repo.iter_backtest_signals(run_id))
        trades_count = self._write_jsonl(tmp_output / "trades.jsonl", self.repo.iter_backtest_trades(run_id))
        equity_count = self._write_jsonl(tmp_output / "equity_curve.jsonl", self.repo.iter_backtest_equity_curve(run_id))
        quality_report = self.repo.get_backtest_quality_report(run_id)
        (tmp_output / "quality_report.json").write_text(json_dumps(quality_report or {}), encoding="utf-8")

        summary = {
            "runId": run.id,
            "datasetId": run.dataset_id,
            "snapshotType": run.snapshot_type,
            "strategyName": run.strategy_name,
            "strategyVersion": run.strategy_version,
            "configHash": run.config_hash,
            "randomSeed": run.random_seed,
            "metrics": {metric: self._metric_value(result, metric) for metric in sorted(BACKTEST_COMPARE_METRICS)},
            "request": request,
        }
        (tmp_output / "result_summary.json").write_text(json_dumps(summary), encoding="utf-8")

        manifest = {
            "ok": True,
            "format": "jsonl-bundle",
            "runId": run.id,
            "exportedAt": datetime.now(timezone.utc).isoformat(),
            "files": {
                "manifest": {"path": "manifest.json"},
                "resultSummary": {"path": "result_summary.json"},
                "qualityReport": {"path": "quality_report.json", "present": quality_report is not None},
                "signals": {"path": "signals.jsonl", "rows": signals_count},
                "trades": {"path": "trades.jsonl", "rows": trades_count},
                "equityCurve": {"path": "equity_curve.jsonl", "rows": equity_count},
            },
        }

        output.mkdir(parents=True, exist_ok=True)
        for name in ("signals.jsonl", "trades.jsonl", "equity_curve.jsonl", "quality_report.json", "result_summary.json"):
            (tmp_output / name).replace(output / name)
        (tmp_output / "manifest.json").write_text(json_dumps(manifest), encoding="utf-8")
        (tmp_output / "manifest.json").replace(output / "manifest.json")
        return manifest

    def export_report_gzip(self, run_id: str, output: Path) -> dict[str, Any]:
        run = self.repo.get_backtest_run(run_id)
        if not run:
            return {"ok": False, "error": {"code": "backtest_run_not_found", "runId": run_id}}

        output.parent.mkdir(parents=True, exist_ok=True)
        tmp_output = output.with_name(f"{output.name}.tmp")
        result = loads_json_field(run.result_json, {})
        request = loads_json_field(run.request_json, {})
        metrics = {metric: self._metric_value(result, metric) for metric in sorted(BACKTEST_COMPARE_METRICS)}
        quality_report = self.repo.get_backtest_quality_report(run_id) or {}
        with gzip.open(tmp_output, "wt", encoding="utf-8") as handle:
            handle.write("{")
            handle.write(f'"runId":{json_dumps(run.id)}')
            handle.write(f',"datasetId":{json_dumps(run.dataset_id)}')
            handle.write(f',"snapshotType":{json_dumps(run.snapshot_type)}')
            handle.write(f',"strategyName":{json_dumps(run.strategy_name)}')
            handle.write(f',"strategyVersion":{json_dumps(run.strategy_version)}')
            handle.write(f',"configHash":{json_dumps(run.config_hash)}')
            handle.write(f',"randomSeed":{json_dumps(run.random_seed)}')
            handle.write(f',"request":{json_dumps(request)}')
            handle.write(f',"metrics":{json_dumps(metrics)}')
            handle.write(f',"qualityReport":{json_dumps(quality_report)}')
            handle.write(',"trades":')
            self._write_json_array(handle, self.repo.iter_backtest_trades(run_id))
            handle.write(',"equityCurve":')
            self._write_json_array(handle, self.repo.iter_backtest_equity_curve(run_id))
            handle.write(',"signals":')
            self._write_json_array(handle, self.repo.iter_backtest_signals(run_id))
            handle.write("}")
        tmp_output.replace(output)
        return {"ok": True, "format": "json.gz", "runId": run.id}

    @staticmethod
    def _validate_pagination(limit: int, offset: int) -> None:
        if limit < 1 or limit > 1000:
            raise ValueError({"code": "invalid_pagination", "field": "limit", "value": limit, "message": "limit must be between 1 and 1000"})
        if offset < 0:
            raise ValueError({"code": "invalid_pagination", "field": "offset", "value": offset, "message": "offset must be greater than or equal to 0"})

    @staticmethod
    def _metric_value(result: dict[str, Any], metric: str) -> Any:
        if metric == "totalTrades":
            return result.get("tradeCount")
        return result.get(metric)
