# -*- coding: utf-8 -*-
"""题材语料采集三槽配置与状态键隔离（review 2026-11-02 Major：fe92d53a 无护栏）。"""
from __future__ import annotations

import datetime

from backend.snapshot_collector.scheduler import _THEME_CORPUS_ATTEMPTS


def test_theme_corpus_three_slots_config():
    """三槽：08:45 盘前 kpl / 11:45 盘中 kpl（2026-11-02 用户裁决 B）/ 16:10 kpl+jiuyan。"""
    assert _THEME_CORPUS_ATTEMPTS == (
        (datetime.time(8, 45), "preopen", ("kpl",)),
        (datetime.time(11, 45), "midday", ("kpl",)),
        (datetime.time(16, 10), "postclose", ("kpl", "jiuyan")),
    )


def test_theme_corpus_state_keys_isolated_from_jiuyan():
    """state key = f"theme:{kind}"，kind 必须带 theme: 前缀——与韭研裸 kind
    （preopen/midday/final）不同命名空间，否则同日状态互踩（误跳跑/双跑）。"""
    from backend.snapshot_collector import scheduler
    import inspect
    src = inspect.getsource(scheduler)
    assert 'f"theme:{theme_kind}"' in src, "题材采集 state key 必须是 theme:{kind}（与韭研隔离）"
    kinds = {kind for _, kind, _ in _THEME_CORPUS_ATTEMPTS}
    jiuyan_kinds = {"preopen", "midday", "final"}  # 韭研 _JIUYAN_ATTEMPTS 的裸 kind
    assert all(f"theme:{k}" != j for k in kinds for j in jiuyan_kinds)
