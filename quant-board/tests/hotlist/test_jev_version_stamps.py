# -*- coding: utf-8 -*-
"""jev 全线版本戳纪律回归锁（2026-10-13 复盘修复：phase_band/daily_line 起戳）。

背景：全线盘点发现 phase_band 题与 daily_line 无题集代际戳（I15 口径：判据换代必须动戳，
跨代不可比）。本文件锁定「每条调 jev 的线都有独立版本戳常量」，新增线须在此登记。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def test_all_jev_lines_have_dedicated_version_stamps():
    from backend.analysis.hotlist import jev_state
    from backend.analysis.hotlist import jev_driver_ammo as drv
    from backend.analysis.hotlist import jev_relay_ammo as relay
    from backend.analysis.hotlist import jev_vote_ammo as vote
    from backend.operations import jev_daily_line as daily

    # 每日链 5 线 + 链外登记
    assert jev_state.QUESTION_SET_VERSION == "v2.5"                    # 热榜情绪
    assert drv.QUESTION_SET_VERSION_DRIVER == "v3.1"                   # 个股打标+合并相位
    assert drv.QUESTION_SET_VERSION_CYCLE == "v5"                      # cycle 阶段（链外）
    assert drv.QUESTION_SET_VERSION_PHASE_BAND == "v1"                 # 相位带（复盘修复起戳）
    assert relay.QUESTION_SET_VERSION_RELAY == "v6"                    # 连板指数（v6 板块/龙头结构）
    assert relay.QUESTION_SET_VERSION_ZHABAN == "v1"                   # 炸板归因（已挂链）
    assert vote.QUESTION_SET_VERSION_VOTE_CONFIRM == "v4-material"     # 方向判读（代际覆盖）
    assert vote.VOTE_AMMO_VERSION == "2026-10-13b"                     # b 代：四条款修订（同日复验）
    assert vote.QUESTION_SET_VERSION_LIFECYCLE_RECHECK == "v1"         # 生命周期复核
    assert daily.QUESTION_SET_VERSION_DAILY_LINE == "v1"               # 日线一句话（复盘修复起戳）


def test_daily_line_meta_carries_stamp():
    """daily_line 报告 meta 必须含 questionSetVersion（落 phase_monitor 可追溯）。"""
    from backend.operations import jev_daily_line as daily
    import inspect
    src = inspect.getsource(daily)
    assert '"questionSetVersion": QUESTION_SET_VERSION_DAILY_LINE' in src


def test_phase_band_doc_uses_dedicated_stamp():
    """phase_band 落档用独立戳（不再借 driver 戳——跨代不可比违规防范）。"""
    from backend.operations import jev_label_jiuyan as jl
    import inspect
    src = inspect.getsource(jl.run_phase_band_day)
    assert "QUESTION_SET_VERSION_PHASE_BAND" in src
    assert "QUESTION_SET_VERSION_DRIVER" not in src
