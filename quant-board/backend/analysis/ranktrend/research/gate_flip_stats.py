"""门控翻转率统计（WP3.2）——纯函数，供 diagnose_gate_flip_rate.py 调用。

三类门控状态逐帧提取 + 相邻帧翻转计数：lifecycle veto（per-stock，action=="veto"）、
synergy B/D 降档（per-stock，tierReasons 精确锚点——WP2 抑制文案含"环境降档"后缀，
必须 fullmatch 精确匹配，跨计划协同约定）、regime state（市场级，调用方按 snapshotId 去重）。
字段缺失按 fail-visible 计入 missing_fields，不静默丢弃。
"""
from __future__ import annotations

import re
from typing import Any

_BD_DOWNGRADE_PATTERN = re.compile(r"周期 [BD] 环境降档")


def extract_gate_states(signal: dict[str, Any]) -> dict[str, Any]:
    rank_trend = signal.get("rankTrend") if isinstance(signal, dict) else None
    cycle = (rank_trend or {}).get("cycle") or {}
    decision = cycle.get("decision") or {}
    observation = (rank_trend or {}).get("observation") or {}
    synergy = observation.get("synergy") or {}
    strategy = (rank_trend or {}).get("strategy") or {}
    regime = strategy.get("regime") or {}
    tier_reasons = synergy.get("tierReasons") or []
    return {
        "veto": str(decision.get("action") or "") == "veto",
        "bd_downgrade": any(_BD_DOWNGRADE_PATTERN.fullmatch(str(reason)) for reason in tier_reasons),
        "regime_state": str(regime.get("state") or ""),
    }


def _flips(series: list[Any]) -> int:
    return sum(1 for prev, curr in zip(series, series[1:]) if prev != curr)


def count_gate_flips(states_by_code: dict[str, list[dict[str, Any]]], regime_states: list[str]) -> dict[str, Any]:
    """regime state 是市场级状态（同帧全 code 相同）——只按市场级序列统计一次，不按 code 重复计数。"""
    per_code: dict[str, dict[str, int]] = {}
    comparable_pairs = 0
    missing_fields = 0
    totals = {"veto": 0, "bd_downgrade": 0, "regime_state": _flips(regime_states)}
    for code, states in states_by_code.items():
        veto_series = [bool(state.get("veto")) for state in states]
        bd_series = [bool(state.get("bd_downgrade")) for state in states]
        regime_series = [str(state.get("regime_state") or "") for state in states]
        missing_fields += sum(1 for value in regime_series if not value)
        pairs = sum(
            1 for prev, curr in zip(regime_series, regime_series[1:]) if prev and curr
        )
        comparable_pairs += pairs
        counts = {
            "veto": _flips(veto_series),
            "bd_downgrade": _flips(bd_series),
            "regime_state": 0,  # 市场级状态不在 per-code 视图重复计数
        }
        per_code[code] = counts
        totals["veto"] += counts["veto"]
        totals["bd_downgrade"] += counts["bd_downgrade"]
    market_pairs = max(len(regime_states) - 1, 0)
    comparable_pairs = max(comparable_pairs, market_pairs)
    flip_rates = {
        key: (value / comparable_pairs if comparable_pairs else 0.0)
        for key, value in totals.items()
    }
    return {
        "comparable_pairs": comparable_pairs,
        "flip_counts": totals,
        "flip_rates": flip_rates,
        "per_code": per_code,
        "missing_fields": missing_fields,
    }


def top_flip_codes(per_code: dict[str, dict[str, int]], key: str, n: int = 10) -> list[tuple[str, int]]:
    return sorted(
        ((code, int(counts.get(key) or 0)) for code, counts in per_code.items()),
        key=lambda item: (-item[1], item[0]),
    )[: max(n, 0)]
