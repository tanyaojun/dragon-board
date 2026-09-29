# -*- coding: utf-8 -*-
"""displayStatus 纯投影合同（spec: docs/superpowers/specs/2026-09-10-displaystatus-stage-projection-design.md §3）。

displayStatus 只是 cycle.stage 的展示投影：{stage, label, tooltip}。
无分类层、无修正类、无 classKey；cooling 强资金承接只追加 tooltip，不改 label/stage。

历史对照（旧口径已删除，勿在本文件恢复）：三层修正级联 / 8 类 label+classKey /
`STAGE_MISSING_LABELS` / `is_stage_missing_fallback` / `statusSourceCounts.stageMissing`。
"""
from __future__ import annotations

import pytest

from backend.analysis.ranktrend.display_status import (
    STAGE_ENUM,
    STAGE_LABELS,
    STAGE_UNKNOWN_LABEL,
    STRONG_SUPPORT_NOTE,
    compute_display_status,
    is_stage_missing,
    stage_of,
)


@pytest.mark.parametrize("stage", list(STAGE_ENUM))
def test_label_is_stage_projection(stage: str) -> None:
    result = compute_display_status({"cycle": {"stage": stage}}, {})
    assert result["stage"] == stage
    assert result["label"] == STAGE_LABELS[stage]
    assert result["tooltip"]


@pytest.mark.parametrize("missing", [None, "", "unknown", "IGNITION", 7])
def test_missing_or_invalid_stage_projects_to_none_and_unknown_label(missing) -> None:
    analysis = {} if missing is None else {"cycle": {"stage": missing}}
    result = compute_display_status(analysis, {})
    assert result["stage"] is None
    assert result["label"] == STAGE_UNKNOWN_LABEL
    assert result["tooltip"]
    assert is_stage_missing(analysis) is True


def test_no_class_key_in_contract() -> None:
    result = compute_display_status({"cycle": {"stage": "crowded"}}, {})
    assert set(result) == {"stage", "label", "tooltip"}


def test_vocab_literal_contract() -> None:
    """词表逐字合同（code review Low 5）：STAGE_LABELS 是唯一来源，前端
    `src/types/hotlistSentiment.ts` 的 HOT_LIST_STAGE_LABELS 是逐字镜像（有对称 literal
    测试锚定）。改词必须同批改镜像 + 合同文档判据表，否则两端展示漂移。"""
    assert STAGE_ENUM == ("ignition", "expansion", "crowded", "reversal", "cooling")
    assert STAGE_LABELS == {
        "ignition": "点火",
        "expansion": "扩散",
        "crowded": "拥挤",
        "reversal": "反转",
        "cooling": "冷却",
    }
    assert STAGE_UNKNOWN_LABEL == "无阶段"


def test_cooling_strong_support_only_touches_tooltip() -> None:
    stock = {"zlje": 1000.0, "zljzb": 12.0}
    analysis = {
        "cycle": {"stage": "cooling"},
        "observation": {"volumePrice": {"signalTier": "A"}},
    }
    with_support = compute_display_status(analysis, stock)
    without_support = compute_display_status({"cycle": {"stage": "cooling"}}, {})
    assert with_support["stage"] == without_support["stage"] == "cooling"
    assert with_support["label"] == without_support["label"]
    assert with_support["tooltip"] != without_support["tooltip"]
    assert with_support["tooltip"].startswith(without_support["tooltip"])
    assert STRONG_SUPPORT_NOTE in with_support["tooltip"]


def test_non_cooling_stage_never_gets_strong_support_note() -> None:
    stock = {"zlje": 1000.0, "zljzb": 12.0}
    analysis = {"cycle": {"stage": "ignition"}, "observation": {"volumePrice": {"signalTier": "A"}}}
    assert compute_display_status(analysis, stock)["tooltip"] == compute_display_status(
        {"cycle": {"stage": "ignition"}}, {}
    )["tooltip"]


@pytest.mark.parametrize("bad", [None, [], "str", 3.4])
def test_as_dict_tolerates_bad_shapes(bad) -> None:
    result = compute_display_status(bad, bad)
    assert result["stage"] is None
    assert result["label"] == STAGE_UNKNOWN_LABEL


def test_stage_of_returns_empty_for_missing() -> None:
    assert stage_of({}) == ""
    assert stage_of({"cycle": None}) == ""
    assert stage_of({"cycle": "ignition"}) == ""
    assert stage_of({"cycle": {"stage": "ignition"}}) == "ignition"


def test_is_stage_missing_contract() -> None:
    for stage in STAGE_ENUM:
        assert is_stage_missing({"cycle": {"stage": stage}}) is False
    for stage in (None, "", "garbage", "Ignition"):
        assert is_stage_missing({"cycle": {"stage": stage}}) is True
    assert is_stage_missing({}) is True
    assert is_stage_missing({"cycle": ["ignition"]}) is True


def test_removed_symbols_are_gone() -> None:
    """分类层符号必须彻底删除（防止回潮）。"""
    import backend.analysis.ranktrend.display_status as module

    for symbol in (
        "STAGE_MISSING_LABELS",
        "STAGE_MISSING_TOOLTIP",
        "is_stage_missing_fallback",
        "_sample_status",
        "_STATUS",
        "_STAGE_KEYS",
    ):
        assert not hasattr(module, symbol), symbol
