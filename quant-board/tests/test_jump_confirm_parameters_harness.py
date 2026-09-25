# -*- coding: utf-8 -*-
"""Jump 确认阈值扫描 harness 测试（方案 P6-c，观察因子标准；全 mock/小数据，不触 MongoDB）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from backend.analysis.ranktrend.engine import RankTrendConfig
from backend.operations.evaluate_jump_confirm_parameters import (
    ANCHOR_BASELINE,
    JUMP_TRIALS,
    _assert_overrides_applied,
    _save,
    build_specs,
    jump_confirm_stats,
    jump_vote_share,
    run_window,
    trial_summary,
)


def test_baseline_anchor_constant():
    """锚单一事实源（2026-09-25）：运行时读锚注册表 currentGeneration，不再硬编码代际值。"""
    from backend.operations.harness_common import baseline_anchor

    gen, anchors = baseline_anchor()
    assert gen == "gen-2026-10-b202610"
    assert ANCHOR_BASELINE == anchors


def test_jump_trial_table_completeness():
    """P6-c trial 表完整性：两单轴各 4 非默认档逐值断言（默认档由 baseline 承担，不重复跑）。"""
    chg = {
        s["overrides"]["jumpConfirmChangeMin"]
        for s in JUMP_TRIALS
        if "jumpConfirmChangeMin" in s["overrides"]
    }
    vr = {
        s["overrides"]["jumpConfirmVolumeRatioMin"]
        for s in JUMP_TRIALS
        if "jumpConfirmVolumeRatioMin" in s["overrides"]
    }
    assert chg == {1.0, 2.0, 4.0, 5.0}
    assert vr == {0.6, 0.8, 1.25, 1.5}
    assert len(JUMP_TRIALS) == 8  # 4 + 4，baseline 单独承担默认档（3.0 / 1.0）
    # 默认值不得混入非默认档（防重复跑同一剂量点）
    for s in JUMP_TRIALS:
        assert s["overrides"].get("jumpConfirmChangeMin") != 3.0
        assert s["overrides"].get("jumpConfirmVolumeRatioMin") != 1.0


def test_defaults_carried_by_baseline():
    """默认档由 baseline 承担：config 真实默认值必须为 3.0/1.0（engine/config.py，锁定扫描前提）。"""
    config = RankTrendConfig()
    assert config.jumpConfirmChangeMin == 3.0
    assert config.jumpConfirmVolumeRatioMin == 1.0


def test_single_variable_per_trial():
    """单变量拆分：每个 trial 只动一个参数（交互组合不扫，留精扫）。"""
    for spec in JUMP_TRIALS:
        assert len(spec["overrides"]) == 1, f"{spec['key']} 打包了多参数：{spec['overrides']}"


def test_all_trials_construct_valid_config():
    for spec in JUMP_TRIALS:
        assert RankTrendConfig.from_patch(spec["overrides"]) is not None


def test_assert_overrides_applied_rejects_unknown_field():
    """from_patch 对未知字段静默忽略——harness 必须逐键断言 override 生效（review C1 同款）。"""
    ok = RankTrendConfig.from_patch({"jumpConfirmChangeMin": 4.0})
    _assert_overrides_applied(ok, {"jumpConfirmChangeMin": 4.0})
    bad = RankTrendConfig.from_patch({"jumpConfirmChangeMinTypo": 4.0})
    with pytest.raises(AssertionError, match="override 未生效"):
        _assert_overrides_applied(bad, {"jumpConfirmChangeMinTypo": 4.0})


def test_save_strips_frames_cache(tmp_path):
    """__frames__ 全量帧缓存与 __out__ 不得落盘；windowsConsumed=True（审计 M3）。"""
    report = {
        "__out__": str(tmp_path / "jump.json"),
        "__frames__": {"decision": [{"tradingDate": "2026-05-04"}]},
        "decision": {"window": {"frameCount": 1}},
    }
    _save(report)
    saved = json.loads((tmp_path / "jump.json").read_text(encoding="utf-8"))
    assert "__frames__" not in saved
    assert "__out__" not in saved
    assert saved["windowsConsumed"] is True
    assert saved["decision"]["window"]["frameCount"] == 1


def test_resume_reruns_freeze_guard(monkeypatch, tmp_path):
    """resume（已含 window 条目）路径仍必须执行 8 月冻结守卫（review I2 同款）。"""
    monkeypatch.setattr(
        "backend.operations.optimize_resonance_parameters.load_frames",
        lambda s, e: [{"tradingDate": "2026-08-05"}],
    )
    monkeypatch.setattr(
        "backend.analysis.ranktrend.engine.RankTrendPythonEngine",
        lambda config=None: SimpleNamespace(replay=lambda frames, meta=None: []),
    )
    monkeypatch.setattr(
        "backend.operations.evaluate_jump_confirm_parameters.evaluate_gate",
        lambda config, frames: {"synergy": {"saEx": None, "passHard": False}},
    )
    report = {
        "__out__": str(tmp_path / "r.json"),
        "decision": {"window": {"start": "2026-04-15", "end": "2026-07-31", "frameCount": 1}},
    }
    with pytest.raises(ValueError, match="冻结"):
        run_window("decision", report)


def test_run_window_executes_extra_trial(monkeypatch, tmp_path):
    """--extra-trial 注入的 trial 必须真实进执行循环（review C2 同款；精扫入口）。"""
    monkeypatch.setattr(
        "backend.operations.optimize_resonance_parameters.load_frames",
        lambda s, e: [{"tradingDate": "2026-05-04"}],
    )
    monkeypatch.setattr(
        "backend.analysis.ranktrend.engine.RankTrendPythonEngine",
        lambda config=None: SimpleNamespace(replay=lambda frames, meta=None: []),
    )
    monkeypatch.setattr(
        "backend.operations.evaluate_jump_confirm_parameters.evaluate_gate",
        lambda config, frames: {"synergy": {"saEx": 0.1323, "passHard": True}},  # decision 锚值（gen-2026-10-b202610），避免误触漂移守卫
    )
    specs = build_specs('[{"key":"grid_chg3_vr12","desc":"交互精扫探针","overrides":{"jumpConfirmChangeMin":3.0,"jumpConfirmVolumeRatioMin":1.25}}]')
    keys = [s["key"] for s in specs]
    assert "grid_chg3_vr12" in keys and "baseline" in keys and "chg_1" in keys
    report = {"__out__": str(tmp_path / "r.json")}
    run_window("decision", report, specs=specs)
    trials = report["decision"]["trials"]
    assert "baseline" in trials
    assert "grid_chg3_vr12" in trials
    assert trials["grid_chg3_vr12"]["overrides"] == {"jumpConfirmChangeMin": 3.0, "jumpConfirmVolumeRatioMin": 1.25}


def test_baseline_anchor_drift_stops_immediately(monkeypatch, tmp_path):
    """baseline 首跑锚不复现 → 立即停止（配置漂移），不继续跑任何 trial。"""
    monkeypatch.setattr(
        "backend.operations.optimize_resonance_parameters.load_frames",
        lambda s, e: [{"tradingDate": "2026-05-04"}],
    )
    monkeypatch.setattr(
        "backend.analysis.ranktrend.engine.RankTrendPythonEngine",
        lambda config=None: SimpleNamespace(replay=lambda frames, meta=None: []),
    )
    monkeypatch.setattr(
        "backend.operations.evaluate_jump_confirm_parameters.evaluate_gate",
        lambda config, frames: {"synergy": {"saEx": 0.0700, "passHard": True}},  # ≠ 锚 0.112
    )
    report = {"__out__": str(tmp_path / "r.json")}
    with pytest.raises(RuntimeError, match="baseline 锚漂移"):
        run_window("decision", report)
    trials = report["decision"]["trials"]
    assert "baseline" in trials
    assert all(key == "baseline" for key in trials)  # 漂移即停，后续 trial 未跑


def _signal(jump: dict | None, resonance: dict | None) -> dict:
    return {"rankTrend": {"jump": jump or {}, "resonance": resonance or {}}}


def test_jump_confirm_stats_unconfirmed_rate():
    """G4 语义降级率（生产枚举 buy/sell）：降级=confirmed=False；分母=带方向且已过确认流的样本。

    2026-09-15 接线修复后：buy/sell 经确认分支核验（unconditionalPass=核验后放行）；
    修复前它们落 else 无条件放行（unconfirmedRate 恒为降级/总体的失真值，见 P6-c 报告）。
    统计口径本身不变。
    """
    signals = [
        _signal({"direction": "buy", "confirmed": True}, {}),       # 核验后放行
        _signal({"direction": "hold", "confirmed": False, "unconfirmedReasons": ["x"]}, {}),  # 降级
        _signal({"direction": "hold", "confirmed": True}, {}),      # 无方向无确认需求
        _signal({"direction": "sell", "confirmed": False, "unconfirmedReasons": ["y"]}, {}),  # 降级
        _signal({}, {}),                                            # 空 jump 对象（无事件）
        _signal({"direction": "buy"}, {}),                          # 有方向但缺 confirmed 字段
    ]
    stats = jump_confirm_stats(signals)
    assert stats["confirmRequired"] == 3  # buy 放行 1 + 降级 2
    assert stats["unconfirmed"] == 2
    assert stats["unconfirmedRate"] == round(2 / 3, 4)
    assert stats["unconditionalPass"] == 1  # 带方向且 confirmed=True（核验后放行）
    assert stats["missingConfirmed"] == 1  # 缺 confirmed 字段如实计数（fail-visible）
    assert stats["noJumpCount"] == 1


def test_confirm_gate_wiring_fixed():
    """消费面接线修复回归（2026-09-15）：生产枚举 buy/sell 已进入确认分支。

    修复前：_confirm_jump 确认分支只匹配 "up"/"down"（runtime.py:230-235），生产枚举
    buy/sell 全部落 else 无条件放行——G4 上线以来从未拦截（P6-c 实证 10936 事件全放行）。
    修复后：buy/sell 按方向做价格+量确认，弱数据降级 hold（G4 fail-visible）；
    "up"/"down" 保留为语义别名，行为不变。
    """
    from backend.analysis.ranktrend.engine import RankTrendConfig, _confirm_jump

    config = RankTrendConfig()
    # 强确认（远超阈值放量上涨）：buy 保持方向
    jumped = _confirm_jump({"direction": "buy", "events": [{"index": 1, "direction": "surge", "magnitude": 99}]},
                           {"change": 9.9, "volumeRatio": 9.9}, config)
    assert jumped["confirmed"] is True
    assert jumped["direction"] == "buy"
    # 弱数据 buy 被拦截（修复前该输入无条件放行——断线回归锚）
    buy_downgraded = _confirm_jump({"direction": "buy", "events": [{"index": 1, "direction": "surge", "magnitude": 99}]},
                                   {"change": 0.1, "volumeRatio": 0.1}, config)
    assert buy_downgraded["confirmed"] is False
    assert buy_downgraded["direction"] == "hold"  # G4 fail-visible：direction 降 hold，事件保留
    assert buy_downgraded["events"][0]["direction"] == "hold"  # events 同步降级但保留（不删）
    # sell 对称拦截
    sell_downgraded = _confirm_jump({"direction": "sell", "events": [{"index": 1, "direction": "collapse", "magnitude": 99}]},
                                    {"change": 0.1, "volumeRatio": 0.1}, config)
    assert sell_downgraded["confirmed"] is False
    assert sell_downgraded["direction"] == "hold"
    # 别名 up 语义不变（分支语义本身自始工作）
    up_downgraded = _confirm_jump({"direction": "up", "events": [{"index": 1, "direction": "surge", "magnitude": 99}]},
                                  {"change": 0.1, "volumeRatio": 0.1}, config)
    assert up_downgraded["confirmed"] is False
    assert up_downgraded["direction"] == "hold"


def test_jump_confirm_stats_zero_denominator_is_none():
    stats = jump_confirm_stats([_signal({}, {}), _signal({"direction": "hold", "confirmed": True}, {})])
    assert stats["confirmRequired"] == 0
    assert stats["unconfirmedRate"] is None  # 不伪造 0


def test_jump_vote_share_matches_da_definition():
    """Jump 票占比同 D-a 口径：res voted 且 tierReasons 含 'Jump'（fund10 前基线 12-14% 仅方向对照）。"""
    signals = [
        _signal({}, {"status": "ok", "direction": "buy", "tierReasons": ["Jump 事件驱动，排名跳跃式上升"]}),
        _signal({}, {"status": "ok", "direction": "sell", "tierReasons": ["共振衰竭/反向"]}),
        _signal({}, {"status": "ok", "direction": "hold", "tierReasons": ["中性"]}),
        _signal({}, {"status": "insufficient", "direction": "hold", "tierReasons": ["排名序列不足或无效"]}),
    ]
    assert jump_vote_share(signals) == 0.25  # 1/4（voted+Jump 占全体信号）


def test_jump_vote_share_empty_is_none():
    assert jump_vote_share([]) is None


def test_trial_summary_monitors_all_axes():
    """trial_summary 必须输出方案 P6-c 四监控量：syn saEx / res saEx / 降级率 / Jump 票占比。"""
    report = {
        "decision": {"trials": {
            "baseline": {"result": {"synergy": {"saEx": 0.112, "passHard": True}, "resSaEx": 0.02, "jumpConfirm": {"confirmRequired": 10, "unconfirmed": 5, "unconfirmedRate": 0.5}, "jumpVoteShare": 0.12}},
            "chg_1": {"result": {"synergy": {"saEx": 0.113, "passHard": True}, "resSaEx": 0.03, "jumpConfirm": {"confirmRequired": 10, "unconfirmed": 4, "unconfirmedRate": 0.4}, "jumpVoteShare": 0.14}},
        }},
    }
    summary = trial_summary(report, {"key": "chg_1"})
    win = summary["windows"]["decision"]
    assert win["saEx"] == 0.113 and win["saExRel"] == round((0.113 - 0.112) / 0.112, 4)
    assert win["resSaEx"] == 0.03 and win["resSaExRel"] == round((0.03 - 0.02) / 0.02, 4)
    assert win["unconfirmedRate"] == 0.4
    assert win["jumpVoteShare"] == 0.14
    assert summary["verdict"] == "monitor_only"  # 观察因子标准：不做 C1-C3 判定卡，不触发 Track 1
    assert "不触发 Track 1" in summary["note"] or "不进投票" in summary["note"]
