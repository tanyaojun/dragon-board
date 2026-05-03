from __future__ import annotations

from typing import Any

DEFAULT_STRATEGY_NAME = "rank_trend_candidate"

STRATEGY_DEFINITIONS: list[dict[str, Any]] = [
    {
        "key": DEFAULT_STRATEGY_NAME,
        "label": "RankTrend 候选池",
        "description": "买入 A_MAIN 与连续确认后的 B_IGNITION，是当前正式策略。",
    },
    {
        "key": "hot_top10",
        "label": "热榜 Top10",
        "description": "只用热榜排名前 10 作为朴素对照组，不使用 RankTrend 分层。",
    },
    {
        "key": "a_main_only",
        "label": "A_MAIN only",
        "description": "只买 A_MAIN，衡量主升分层本身的交易贡献。",
    },
    {
        "key": "b_ignition_only",
        "label": "B_IGNITION only",
        "description": "只买连续确认后的 B_IGNITION，衡量点火分层的交易贡献。",
    },
    {
        "key": "a_b_combined",
        "label": "A+B",
        "description": "只买 A_MAIN 与连续确认后的 B_IGNITION，是当前正式策略的核心候选池对照。",
    },
]

SUPPORTED_STRATEGY_NAMES = {definition["key"] for definition in STRATEGY_DEFINITIONS}

CONTROL_STRATEGIES = [
    definition for definition in STRATEGY_DEFINITIONS if definition["key"] != DEFAULT_STRATEGY_NAME
]


def normalize_strategy_name(value: Any = None, default: str = DEFAULT_STRATEGY_NAME) -> str:
    strategy_name = str(value or default).strip()
    if not strategy_name:
        strategy_name = default
    if strategy_name not in SUPPORTED_STRATEGY_NAMES:
        supported = ", ".join(sorted(SUPPORTED_STRATEGY_NAMES))
        raise ValueError(f"unsupported strategyName: {strategy_name}. supported: {supported}")
    return strategy_name
