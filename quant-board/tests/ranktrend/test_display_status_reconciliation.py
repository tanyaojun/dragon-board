# -*- coding: utf-8 -*-
"""计数与规则判据契约（spec §4 + 等价内联 B1）。

恒等式：`sum(stageCounts) == 分池行数`；每行 stage ∈ 5 态 ∪ {unknown}。
规则引擎仍需要四个量（`activeOpportunityShare` / `strongMoneyShare` / `riskShare` /
`crowdedShare`）—— 它们是 `resolve_stage` 的输入，只作规则输入、不进展示层。
旧的 8 类分布（`statusCounts`/`statusShares`）与展示派生指标（`*Count`）已删除。

历史对照（旧口径已删除，勿在本文件恢复）：8 类 × 5 态的单向一致性 + 不可逆性校验
（`spec 2026-09-10-display-status-lifecycle-alignment-design.md §7`）随分类层消亡，
取而代之的是下面的**恒等式**（不再存在第二个口径，无需对账）。
"""
from __future__ import annotations

from backend.analysis.hotlist.sentiment import (
    STAGE_KEYS,
    annotate_rows_with_signals,
    build_day_metrics_from_sorted,
    derive_row_flags,
    is_risk_row,
    is_strong_money_row,
    is_yesterday_strong_row,
    resolve_row_stage,
    sort_rows,
)

REMOVED_METRIC_KEYS = (
    "statusCounts",
    "statusShares",
    "activeOpportunityCount",
    "opportunityCount",
    "opportunityShare",
    "riskCount",
    "crowdedCount",
)

KEPT_RULE_INPUT_KEYS = (
    "activeOpportunityShare",
    "strongMoneyShare",
    "riskShare",
    "crowdedShare",
)


def test_resolve_row_stage_counts_sources() -> None:
    source = {"displayStatus": 0, "fallback": 0}
    assert resolve_row_stage({"displayStatusStage": "cooling"}, [], source) == "cooling"
    assert source == {"displayStatus": 1, "fallback": 0}

    # 有 label 但无 stage（有记录、stage 缺失）→ unknown，仍计 displayStatus
    assert resolve_row_stage({"displayStatusLabel": "冷却"}, [], source) == "unknown"
    assert source == {"displayStatus": 2, "fallback": 0}

    # 完全没有记录 → unknown，计 fallback（fail-visible：来源缺失可辨识）
    assert resolve_row_stage({}, [], source) == "unknown"
    assert source == {"displayStatus": 2, "fallback": 1}


def test_stage_counts_cover_all_rows_and_drop_8class_fields() -> None:
    rows = sort_rows(
        [
            {"code": "000001", "compRank": 1, "displayStatusStage": "cooling", "change": 1.0},
            {"code": "000002", "compRank": 2, "displayStatusStage": "crowded", "change": -1.0},
            {"code": "000003", "compRank": 3, "displayStatusStage": "reversal", "change": 0.0},
            {"code": "000004", "compRank": 4, "change": 2.0},  # 无记录 → unknown
        ]
    )

    metrics = build_day_metrics_from_sorted(rows, len(rows))

    assert set(metrics["stageCounts"]) == set(STAGE_KEYS)
    assert sum(metrics["stageCounts"].values()) == metrics["topN"] == 4
    assert metrics["stageCounts"]["unknown"] == 1
    assert set(metrics["stageShares"]) == set(STAGE_KEYS)
    for removed in REMOVED_METRIC_KEYS:
        assert removed not in metrics, removed
    for kept in KEPT_RULE_INPUT_KEYS:
        assert kept in metrics, kept
    assert metrics["statusSourceCounts"] == {"displayStatus": 3, "fallback": 1}


def test_row_flags_are_equivalence_of_old_8class() -> None:
    # 旧「强资确认」：cooling + 强资金 + 量能承接 → strongMoney 且非 risk
    strong = derive_row_flags(
        {"cycle": {"stage": "cooling"}, "observation": {"volumePrice": {"signalTier": "A"}}},
        {"zlje": 1e8, "zljzb": 12.0},
    )
    assert strong == {"strongMoney": True, "risk": False}

    # cooling 但非强资 → risk（旧「转弱预警」）
    assert derive_row_flags({"cycle": {"stage": "cooling"}}, {}) == {"strongMoney": False, "risk": True}
    # reversal → risk（旧「转弱预警」）
    assert derive_row_flags({"cycle": {"stage": "reversal"}}, {})["risk"] is True
    # 资金背离：synergy.state=存疑 且 zljzb ≤ 0 → risk（旧「资金背离」）
    divergence = derive_row_flags(
        {"cycle": {"stage": "ignition"}, "observation": {"synergy": {"state": "存疑"}}},
        {"zljzb": -5},
    )
    assert divergence["risk"] is True
    # crowded / ignition 非强资 → 既非强资也非风险
    assert derive_row_flags({"cycle": {"stage": "crowded"}}, {}) == {"strongMoney": False, "risk": False}
    assert derive_row_flags({"cycle": {"stage": "ignition"}}, {}) == {"strongMoney": False, "risk": False}
    # 强资金但量能不承接（D）→ 不算强资
    assert derive_row_flags(
        {"cycle": {"stage": "cooling"}, "observation": {"volumePrice": {"signalTier": "D"}}},
        {"zlje": 1e8, "zljzb": 12.0},
    ) == {"strongMoney": False, "risk": True}


def test_strong_money_flag_requires_cooling_stage() -> None:
    # 合同（lifecycle-layering-contract.md 判据表 + derive_row_flags docstring）：
    # 强资判据 = `stage == cooling` 且强资金且量能承接。非 cooling 阶段即使强资金+量能承接
    # 也不得置位 —— 否则 `active = ignition + expansion + strong_money` 对同一行双计
    # （旧 8 类三标签互斥，activeOpportunityShare 抬高会翻转 resolve_stage 阈值判定）。
    for stage in ("ignition", "expansion", "crowded"):
        flags = derive_row_flags(
            {"cycle": {"stage": stage}, "observation": {"volumePrice": {"signalTier": "A"}}},
            {"zlje": 1e8, "zljzb": 12.0},
        )
        assert flags == {"strongMoney": False, "risk": False}, stage


def test_active_opportunity_share_does_not_double_count() -> None:
    # strongMoneyShare 按构造 ⊆ cooling 桶（计量侧结构保证）：即使出现与后端产出不一致的
    # 注入标记（expansion 行带 strongMoney=True），也不得把同一行在 active 里计两次。
    rows = sort_rows(
        [
            # 与后端产出口径一致的行：strong 只出现在 cooling 行
            {"code": "A1", "compRank": 1, "displayStatusStage": "cooling", "displayStatusStrongMoney": True, "displayStatusRisk": False},
            {"code": "A2", "compRank": 2, "displayStatusStage": "expansion", "displayStatusStrongMoney": False, "displayStatusRisk": False},
            {"code": "A3", "compRank": 3, "displayStatusStage": "ignition", "displayStatusStrongMoney": False, "displayStatusRisk": False},
            {"code": "A4", "compRank": 4, "displayStatusStage": "reversal", "displayStatusStrongMoney": False, "displayStatusRisk": True},
            # 故意不一致的行（生产 join 不会产出）：验证计量侧防御
            {"code": "A5", "compRank": 5, "displayStatusStage": "expansion", "displayStatusStrongMoney": True, "displayStatusRisk": False},
        ]
    )

    metrics = build_day_metrics_from_sorted(rows, len(rows))

    # active = ignition(1) + expansion(2，含 A5) + 强资(1，仅 cooling 行) = 4 —— A5 的
    # strong 标记被计量侧门控丢弃（stage ≠ cooling），同一次只贡献 expansion 一项，不双计；
    # strongMoneyShare 只认 cooling 判定行（A1），A5 的强资标记不计入。
    assert abs(metrics["activeOpportunityShare"] - 4 / 5) < 1e-9
    assert abs(metrics["strongMoneyShare"] - 1 / 5) < 1e-9


def test_fallback_rows_bucket_to_unknown_and_count_as_fallback() -> None:
    # gen-2 spec §「fallback 行归 unknown 桶」：无 snapshot_analysis 记录的行在 stageCounts
    # 里一律归 unknown 桶、statusSourceCounts 计 fallback；crowded/cooling 启发式只作规则
    # 输入（crowdedShare/strongMoneyShare 保持 B1 等价），不进展示分布。
    rows = sort_rows(
        [
            {"code": "B1", "compRank": 1, "change": 9.9, "volumeRatio": 2.5, "turnoverRate": 12.0},  # 过热启发式
            {"code": "B2", "compRank": 2, "change": 1.0, "zlje": 1e8, "zljzb": 12.0, "cddje": 1e7},  # 强资启发式
            {"code": "B3", "compRank": 3, "change": -1.0},  # 无信号
        ]
    )
    annotate_rows_with_signals(rows)

    metrics = build_day_metrics_from_sorted(rows, len(rows))

    assert metrics["stageCounts"]["unknown"] == 3
    assert sum(metrics["stageCounts"].values()) == metrics["topN"] == 3
    assert metrics["statusSourceCounts"] == {"displayStatus": 0, "fallback": 3}
    # 规则输入（B1 等价）不受分桶影响：过热行进 crowdedShare、强资行进 strongMoneyShare
    assert abs(metrics["crowdedShare"] - 1 / 3) < 1e-9
    assert abs(metrics["strongMoneyShare"] - 1 / 3) < 1e-9


def test_row_predicates_read_injected_flags() -> None:
    assert is_strong_money_row({"displayStatusStrongMoney": True}) is True
    assert is_strong_money_row({}) is False
    assert is_risk_row({"displayStatusRisk": True}) is True
    assert is_risk_row({}) is False
    # 昨强 = ignition/expansion 或强资（旧：主升确认+点火观察+强资确认）
    assert is_yesterday_strong_row({"displayStatusStage": "ignition"}) is True
    assert is_yesterday_strong_row({"displayStatusStage": "expansion"}) is True
    assert is_yesterday_strong_row(
        {"displayStatusStage": "cooling", "displayStatusStrongMoney": True}
    ) is True
    assert is_yesterday_strong_row({"displayStatusStage": "cooling"}) is False
    assert is_yesterday_strong_row({}) is False


def test_removed_8class_symbols_are_gone() -> None:
    """8 类分类层符号必须彻底删除（防止回潮）。"""
    import backend.analysis.hotlist.sentiment as module

    for symbol in ("STATUS_LABELS", "_YESTERDAY_STRONG_LABELS"):
        assert not hasattr(module, symbol), symbol
