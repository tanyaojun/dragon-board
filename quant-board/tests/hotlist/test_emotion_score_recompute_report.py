# -*- coding: utf-8 -*-
"""emotion_score_recompute.summarize 纯函数测试（T5，review T5-S5）。

对照口径：old/new 快照以 _id 为键；diffMeaningful 标记防 dry-run 平凡结果误读；
oldOnly/newOnly 计数暴露 slotTime 旧值迁移态造成的覆盖缺口（fail-visible）。"""
from backend.operations.emotion_score_recompute import summarize


def _doc(stage, raw_stage, trading_date="2026-06-05", slot_time="10:00"):
    return {"tradingDate": trading_date, "slotTime": slot_time, "stage": stage, "rawStage": raw_stage}


def test_summarize_counts_and_matrix():
    old = {
        "d1": _doc("退潮", "退潮"),
        "d2": _doc("启动", "发酵", slot_time="11:00"),
        "eod": _doc("退潮", "发酵", slot_time="EOD"),
    }
    new = {
        "d1": _doc("冰点", "启动"),
        "d2": _doc("启动", "发酵", slot_time="11:00"),
        "eod": _doc("冰点", "冰点", slot_time="EOD"),
    }
    summary = summarize(old, new)
    assert summary["diffMeaningful"] is True
    assert summary["slotDocs"]["n"] == 2 and summary["slotDocs"]["stageSame"] == 1
    assert summary["slotDocs"]["stageSameRate"] == 0.5
    # rawStage 口径：'' 与 None 归一化后视为一致（or None）
    assert summary["slotDocs"]["rawStageSame"] == 1
    assert summary["slotDocs"]["matrix"] == {"退潮->冰点": 1, "启动->启动": 1}
    assert summary["eodDocs"]["n"] == 1 and summary["eodDocs"]["stageSame"] == 0
    # 五档分布按槽位口径（EOD 不入分布）
    assert summary["oldStageCounts"] == {"退潮": 1, "启动": 1}
    assert summary["newStageCounts"] == {"冰点": 1, "启动": 1}


def test_summarize_empty_returns_none_rates():
    summary = summarize({}, {})
    assert summary["slotDocs"]["n"] == 0
    assert summary["slotDocs"]["stageSameRate"] is None
    assert summary["oldOnlyDocs"] == 0 and summary["newOnlyDocs"] == 0


def test_summarize_flags_coverage_gap_and_dry_run():
    old = {"d1": _doc("退潮", "退潮"), "ghost": _doc("退潮", "退潮", trading_date="2026-06-01")}
    new = {"d1": _doc("冰点", "冰点")}
    # dry-run：不写库 → new 读到的就是旧文档，diff 恒平凡一致 → 显式标记无意义
    summary_dry = summarize(old, dict(old), diff_meaningful=False)
    assert summary_dry["diffMeaningful"] is False
    assert summary_dry["slotDocs"]["stageSameRate"] == 1.0
    # 覆盖缺口：ghost 只在旧快照（迁移态孤儿）→ oldOnlyDocs 计数暴露
    summary = summarize(old, new)
    assert summary["oldOnlyDocs"] == 1 and summary["newOnlyDocs"] == 0
    assert summary["slotDocs"]["n"] == 1
