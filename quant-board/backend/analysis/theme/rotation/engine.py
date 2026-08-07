"""组合引擎：把当前槽 + 历史槽位计算为 ThemeRotationResult（无 I/O）。"""

from __future__ import annotations

import math
from typing import Any

from backend.analysis.theme.rotation.config import ThemeRotationConfig
from backend.analysis.theme.rotation.factors import (
    breadth_score,
    combine_scores,
    crowding_score,
    flow_score,
    robust_z,
    strength_score,
)
from backend.analysis.theme.rotation.lifecycle import (
    mainline_concentration,
    market_phase_for,
    rotation_speed_score,
    rotation_state_for,
)
from backend.analysis.theme.rotation.models import (
    HistorySlot,
    MarketRotationSummary,
    ThemeFactorScores,
    ThemeRotationResult,
    ThemeRotationStatus,
)


def _theme_key(row: dict[str, Any]) -> str:
    return str(
        row.get("themeId")
        or row.get("entityKey")
        or row.get("id")
        or row.get("themeName")
        or row.get("entityName")
        or ""
    ).strip()


def _num(value: Any, default: float | None = None) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return v if math.isfinite(v) else default


def _market_change(indices: dict[str, Any] | None) -> float | None:
    if not isinstance(indices, dict):
        return None
    changes = [
        _num(v.get("change"))
        for v in indices.values()
        if isinstance(v, dict) and _num(v.get("change")) is not None
    ]
    if not changes:
        return None
    return sum(changes) / len(changes)


def _normalize_theme_label(value: str) -> str:
    """与 projection._normalize_theme_label 同口径：去掉概念/板块后缀（9.3-③ 归一化）。"""
    text = str(value or "").strip()
    for suffix in ("概念板块", "概念", "板块"):
        if text.endswith(suffix) and len(text) > len(suffix):
            text = text[: -len(suffix)]
    return text.strip()


def _stock_theme_labels(stock: dict[str, Any]) -> list[str]:
    """从 stock rows 的 themes 列表 + mainTheme 提取归一化题材标签（无 themeIds 的替代）。"""
    labels: list[str] = []
    raw = stock.get("themes")
    if isinstance(raw, list):
        labels.extend(str(item) for item in raw)
    main_theme = str(stock.get("mainTheme") or "")
    if main_theme and main_theme not in labels:
        labels.append(main_theme)
    return [_normalize_theme_label(label) for label in labels if str(label).strip()]


def _filter_theme_stocks(
    rows: list[dict[str, Any]] | None,
    key: str,
    name: str,
) -> list[dict[str, Any]] | None:
    """把上一槽股票按主题过滤（晋级率分母为主题内昨日涨停，审计 9.5）。"""
    if not rows:
        return None
    wanted = {_normalize_theme_label(key), _normalize_theme_label(name)}
    return [stock for stock in rows if wanted & set(_stock_theme_labels(stock))]


class ThemeRotationEngine:
    """跨槽位序列计算轮动状态；历史不足或字段缺失时输出 None + reasons，不伪造。"""

    def __init__(self, config: ThemeRotationConfig | None = None) -> None:
        self.config = config or ThemeRotationConfig()

    def compute(
        self,
        current_sector_rows: list[dict[str, Any]],
        history_slots: list[HistorySlot],
        current_stock_rows: list[dict[str, Any]],
        indices: dict[str, Any] | None = None,
        computed_at: int = 0,
        trading_date: str | None = None,
    ) -> ThemeRotationResult:
        cfg = self.config
        quality_issues: list[str] = []
        if len(history_slots) + 1 < cfg.min_slots_for_state:
            quality_issues.append(
                f"insufficient_history: 当前1槽+历史{len(history_slots)}槽<{cfg.min_slots_for_state}槽，不输出轮动状态"
            )

        # ── 汇总历史序列（按主题） ──────────────────────────────────────
        histories: dict[str, dict[str, Any]] = {}
        ordered_slots = sorted(history_slots, key=lambda s: s.timestamp_ms)
        for slot in ordered_slots:
            for row in slot.sector_rows:
                key = _theme_key(row)
                bucket = histories.setdefault(
                    key,
                    {
                        "heats": [],
                        "inflows": [],
                        "crowdings": [],
                        "ranks": [],
                        "prev_row": None,
                        "prev_lifecycle": None,
                        "prev_slot_stocks": None,
                    },
                )
                heat = _num(row.get("heatScore"))
                if heat is not None:
                    bucket["heats"].append(heat)
                inflow = _num(row.get("mainNetInflow"))
                if inflow is not None:
                    bucket["inflows"].append(inflow)
                crowding = _num(row.get("crowdingRisk"))
                if crowding is not None:
                    bucket["crowdings"].append(crowding)
                rank = _num(row.get("rank"))
                if rank is not None:
                    bucket["ranks"].append(int(rank))
                bucket["prev_row"] = row
                bucket["prev_lifecycle"] = str(row.get("lifecycle") or "") or None
                bucket["prev_slot_stocks"] = slot.stock_rows

        # ── 截面参照 ────────────────────────────────────────────────────
        all_heats = [
            _num(r.get("heatScore")) for r in current_sector_rows if _num(r.get("heatScore")) is not None
        ]
        all_inflows = [
            _num(r.get("mainNetInflow"))
            for r in current_sector_rows
            if _num(r.get("mainNetInflow")) is not None
        ]
        market_change = _market_change(indices)
        stock_by_theme: dict[str, list[dict[str, Any]]] = {}
        for stock in current_stock_rows:
            for label in _stock_theme_labels(stock):
                stock_by_theme.setdefault(label, []).append(stock)

        statuses: list[ThemeRotationStatus] = []
        rank_changes: list[int] = []
        for row in sorted(
            current_sector_rows,
            key=lambda r: int(_num(r.get("rank"), 999999) or 999999),
        ):
            key = _theme_key(row)
            name = str(row.get("themeName") or row.get("entityName") or key)
            hist = histories.get(
                key,
                {
                    "heats": [],
                    "inflows": [],
                    "crowdings": [],
                    "ranks": [],
                    "prev_row": None,
                    "prev_lifecycle": None,
                    "prev_slot_stocks": None,
                },
            )
            theme_stocks = (
                stock_by_theme.get(_normalize_theme_label(key))
                or stock_by_theme.get(_normalize_theme_label(name))
                or []
            )

            current_inflow = _num(row.get("mainNetInflow"))
            streak_series = (
                [*hist["inflows"], current_inflow]
                if current_inflow is not None
                else hist["inflows"]
            )
            positive_streak, negative_streak = _inflow_streaks(streak_series)

            strength, s_missing = strength_score(
                row,
                hist["heats"],
                all_heats,
                market_change,
                _num(hist["prev_row"].get("ztCount")) if hist["prev_row"] else None,
            )
            flow, f_missing = flow_score(
                row,
                hist["inflows"],
                all_inflows,
                positive_streak,
            )
            prev_theme_stocks = _filter_theme_stocks(hist["prev_slot_stocks"], key, name)
            breadth, b_missing = breadth_score(
                row,
                hist["prev_row"],
                theme_stocks,
                prev_theme_stocks,
            )
            crowding, c_missing = crowding_score(row, hist["crowdings"], theme_stocks)

            scores = ThemeFactorScores(
                theme_id=key,
                theme_name=name,
                strength=round(strength, 2) if strength is not None else None,
                flow=round(flow, 2) if flow is not None else None,
                breadth=round(breadth, 2) if breadth is not None else None,
                crowding=round(crowding, 2) if crowding is not None else None,
                # lifecycle 因子废弃（spec D5）：字段保留输出合同，但恒 None
                lifecycle=None,
                missing=s_missing + f_missing + b_missing + c_missing,
            )
            rotation_score = combine_scores(scores, cfg.weights, cfg.min_factors_for_score)

            enough_history = (len(hist["heats"]) + 1) >= cfg.min_slots_for_state
            # lifecycle 状态机废弃（spec D5）：不再由 heat/momentum/资金推导 8 态
            lifecycle_state = None
            life_reasons = []

            rank = int(_num(row.get("rank"), len(statuses) + 1) or (len(statuses) + 1))
            prev_rank = int(_num(hist["prev_row"].get("rank"), 0) or 0) if hist["prev_row"] else 0
            rank_change = (prev_rank - rank) if prev_rank else 0
            rank_changes.append(rank_change)

            heat_trend_raw = (
                linear_slope_heat(hist["heats"], _num(row.get("heatScore")))
                if enough_history
                else None
            )
            heat_trend = round(heat_trend_raw, 2) if heat_trend_raw is not None else None
            flow_trend_raw = (
                flow_summary(hist["inflows"], _num(row.get("mainNetInflow")))
                if hist["inflows"]
                else None
            )
            flow_trend = round(flow_trend_raw, 2) if flow_trend_raw is not None else None
            breadth_trend_raw = (
                breadth_trend_value(hist["prev_row"], row) if hist["prev_row"] else None
            )
            breadth_trend = (
                round(breadth_trend_raw, 2) if breadth_trend_raw is not None else None
            )
            crowding_trend_raw = (
                crowding_trend_value(hist["crowdings"], _num(row.get("crowdingRisk")))
                if hist["crowdings"]
                else None
            )
            crowding_trend = (
                round(crowding_trend_raw, 2) if crowding_trend_raw is not None else None
            )

            status = ThemeRotationStatus(
                theme_id=key,
                theme_name=name,
                rotation_state=None,
                lifecycle=None,  # spec D5：状态机废弃，输出合同恒 None
                rotation_score=round(rotation_score, 1) if rotation_score is not None else None,
                rank=rank,
                rank_change=rank_change,
                heat_trend=heat_trend,
                flow_trend=flow_trend,
                breadth_trend=breadth_trend,
                crowding_trend=crowding_trend,
                reasons=life_reasons,
                factor_breakdown={
                    "strength": scores.strength,
                    "flow": scores.flow,
                    "breadth": scores.breadth,
                    "crowding": scores.crowding,
                    "lifecycle": scores.lifecycle,
                },
                quality_flags=sorted(set(scores.missing)),
            )
            statuses.append(status)

        # ── 主线判定（设计 §5.2：横向 z-score Top3 且 资金集中度 Top3） ──
        theme_rows = {_theme_key(r): r for r in current_sector_rows}
        heat_zs = {
            key: robust_z(_num(r.get("heatScore"), 0.0), all_heats)
            for key, r in theme_rows.items()
        }
        z_rank = {
            key: index
            for index, (key, _) in enumerate(
                sorted(heat_zs.items(), key=lambda kv: -kv[1]), start=1
            )
        }
        positive_total = sum(v for v in all_inflows if v and v > 0)
        inflow_share = (
            {
                key: (_num(r.get("mainNetInflow"), 0.0) / positive_total)
                for key, r in theme_rows.items()
            }
            if positive_total > 0
            else {}
        )
        conc_rank = {
            key: index
            for index, (key, _) in enumerate(
                sorted(inflow_share.items(), key=lambda kv: -kv[1]), start=1
            )
        }
        mainline_candidates = [
            s
            for s in statuses
            if s.rotation_score is not None
            and z_rank.get(s.theme_id, 999) <= cfg.min_mainline_z_rank
            and conc_rank.get(s.theme_id, 999) <= cfg.min_mainline_concentration_rank
        ]
        mainline_candidates.sort(key=lambda s: -(s.rotation_score or 0))
        mainline_keys = {s.theme_id for s in mainline_candidates[: cfg.mainline_top_n]}
        # 历史不足时不伪造方向状态（fail-visible，沿用 rotation_state=None 语义）
        enough_state = len(ordered_slots) + 1 >= cfg.min_slots_for_state
        if enough_state:
            for status in statuses:
                if status.theme_id not in mainline_keys:
                    continue
                status.mainline_concentration_rank = conc_rank.get(status.theme_id)
                row = _row_for(current_sector_rows, status.theme_id) or {}
                momentum = _num(row.get("momentumScore"))
                status.rotation_state = rotation_state_for(
                    momentum if momentum is not None else 50.0,
                    (_num(row.get("mainNetInflow"), 0) or 0) > 0,
                    True,
                    _num(row.get("crowdingRisk"), 0.0),
                )
            for status in statuses:
                if status.rotation_state is not None:
                    continue
                row = _row_for(current_sector_rows, status.theme_id) or {}
                status.rotation_state = rotation_state_for(
                    _num(row.get("momentumScore"), 50.0),
                    (_num(row.get("mainNetInflow"), 0) or 0) > 0,
                    False,
                    _num(row.get("crowdingRisk"), 0.0),
                )

        # ── 市场摘要 ────────────────────────────────────────────────────
        max_board = max(
            (int(_num(s.get("boardHeight"), 0) or 0) for s in current_stock_rows),
            default=0,
        )
        total_zt = sum(int(_num(r.get("ztCount"), 0) or 0) for r in current_sector_rows)
        speed = rotation_speed_score(rank_changes) if rank_changes else None
        concentration = mainline_concentration(all_heats, cfg.mainline_top_n) if all_heats else None
        cooling_count = sum(1 for s in statuses if s.rotation_state == "outflow")
        cooling_theme_ratio = cooling_count / len(statuses) if statuses else None
        negative_inflow_count = sum(
            1 for r in current_sector_rows if (_num(r.get("mainNetInflow")) or 0) < 0
        )
        negative_inflow_theme_ratio = (
            negative_inflow_count / len(current_sector_rows) if current_sector_rows else None
        )
        market_phase = (
            market_phase_for(
                max_board_height=max_board,
                rotation_speed=speed,
                mainline_count=len([s for s in statuses if s.rotation_state == "mainline"]),
                mainline_concentration=concentration,
                total_zt_count=total_zt,
                cooling_theme_ratio=cooling_theme_ratio,
                negative_inflow_theme_ratio=negative_inflow_theme_ratio,
                cfg=cfg,
            )
            if enough_history_market(ordered_slots, cfg)
            else "unknown"
        )

        mainlines = [
            {
                "themeId": s.theme_id,
                "themeName": s.theme_name,
                "rotationScore": s.rotation_score,
                "rotationState": s.rotation_state,
                "rankChange": s.rank_change,
            }
            for s in statuses
            if s.rotation_state == "mainline"
        ]
        summary = MarketRotationSummary(
            market_phase=market_phase,
            rotation_speed=speed,
            mainline_concentration=concentration,
            max_board_height=max_board,
            main_lines=mainlines,
            inflow_themes=[
                {"themeId": s.theme_id, "themeName": s.theme_name}
                for s in statuses
                if s.rotation_state == "inflow"
            ],
            outflow_themes=[
                {"themeId": s.theme_id, "themeName": s.theme_name}
                for s in statuses
                if s.rotation_state == "outflow"
            ],
            suggestion=_suggestion_for(market_phase, mainlines),
            computed_at=computed_at,
            algorithm_version=cfg.algorithm_version,
            evidence={
                "framesUsed": len(ordered_slots) + 1,
                "qualityIssues": quality_issues,
                "historyLagSlots": 1,
                "crossDayBaseline": bool(
                    ordered_slots and any(s.trading_date != trading_date for s in ordered_slots)
                ),
            },
        )
        return ThemeRotationResult(
            statuses=statuses,
            market=summary,
            quality_issues=quality_issues,
            frames_used=len(ordered_slots) + 1,
        )


def _row_for(rows: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    for row in rows:
        if _theme_key(row) == key:
            return row
    return None


def _inflow_streaks(series: list[float]) -> tuple[int, int]:
    """从序列尾部数连续正/负净流入（不可同时为两者）。"""
    positive = 0
    negative = 0
    for value in reversed(series):
        if value > 0:
            if negative:
                break
            positive += 1
        elif value < 0:
            if positive:
                break
            negative += 1
        else:
            break
    return positive, negative


def linear_slope_heat(history: list[float], current: float | None) -> float | None:
    from backend.analysis.theme.rotation.factors import linear_slope

    if current is None:
        return None
    return linear_slope([*history, current])


def flow_summary(inflows: list[float], current: float | None) -> float | None:
    if current is None:
        return None
    series = [*inflows, current]
    return round(sum(series[-3:]) / len(series[-3:]), 4) if series else None


def breadth_trend_value(prev: dict[str, Any] | None, row: dict[str, Any]) -> float | None:
    from backend.analysis.theme.rotation.factors import _num

    if prev is None:
        return None
    p = _num(prev.get("breadthScore"))
    c = _num(row.get("breadthScore"))
    if p is None or c is None:
        return None
    return round(c - p, 2)


def crowding_trend_value(history: list[float], current: float | None) -> float | None:
    if current is None:
        return None
    return round(current - history[-1], 2) if history else None


def enough_history_market(ordered_slots: list[HistorySlot], cfg: ThemeRotationConfig) -> bool:
    return (len(ordered_slots) + 1) >= cfg.min_slots_for_state


def _suggestion_for(market_phase: str, mainlines: list[dict[str, Any]]) -> str:
    base = {
        "ice": "冰点期：等待题材企稳",
        "chaos": "混沌轮动期：控制仓位，观察资金方向",
        "rising": "主线上升期：跟踪主线题材",
        "climax": "高潮期：注意拥挤和分化",
        "cooling": "退潮期：规避降温题材",
        "unknown": "历史不足：暂不判定市场阶段",
    }
    names = "、".join(m["themeName"] for m in mainlines[:3])
    return f"{base.get(market_phase, '')} 主线：{names}" if names else base.get(market_phase, "")
