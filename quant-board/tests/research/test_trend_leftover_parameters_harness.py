# -*- coding: utf-8 -*-
"""趋势漏网参数扫描 harness 测试（P5 案：thresholds 镜像缩放 + 5 momentum 参数 + requireMacdGoldenCross）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from backend.analysis.ranktrend.engine import RankTrendConfig
from backend.operations.evaluate_trend_leftover_parameters import (
    ACCEL_BOOST_TRIALS,
    ANCHOR_BASELINE,
    BASE_ACCEL_BOOST,
    BASE_BUY,
    BASE_DIR_BOOST,
    BASE_LONG_AGREE,
    BASE_SCORE_THRESHOLD,
    BASE_SELL,
    DIR_BOOST_TRIALS,
    FAST_HALF_BUY,
    LONG_AGREE_TRIALS,
    P5_TRIALS,
    SCORE_TRIALS,
    SWITCH_TRIALS,
    THRESHOLDS_TRIALS,
    TRIGGER_RATE_FLAG,
    _assert_overrides_applied,
    _assert_thresholds_len5,
    _scale_thresholds,
    _save,
    baseline_spec,
    run_window,
    trial_summary,
    trigger_rate_of,
)


def test_thresholds_match_config_defaults():
    """代际锁定：BASE_BUY/BASE_SELL 与 config 默认逐位一致（config.py:11-12 负镜像），漂移即失败。"""
    config = RankTrendConfig()
    assert list(BASE_BUY) == list(config.buyThresholds)
    assert list(BASE_SELL) == list(config.sellThresholds)
    assert list(BASE_SELL) == [-v for v in BASE_BUY]  # 负镜像
    assert list(FAST_HALF_BUY) == [3, 5, 8, 13, 21]
    assert BASE_LONG_AGREE == float(config.momentumLongAgreeThreshold)
    assert BASE_SCORE_THRESHOLD == float(config.momentumScoreThreshold)
    assert list(BASE_DIR_BOOST) == list(config.momentumDirectionShareBoost)
    assert list(BASE_ACCEL_BOOST) == list(config.momentumAccelShareBoost)
    assert config.requireMacdGoldenCross is False  # 二值开关：False=baseline 承担


def test_trial_table_completeness():
    """P5-a 表完整性：22 trial + baseline = 23；6 组键名逐组断言（默认档由 baseline 承担）。"""
    assert len(P5_TRIALS) == 22
    assert {s["key"] for s in THRESHOLDS_TRIALS} == {"thr_x05", "thr_x075", "thr_x125", "thr_x15", "thr_fast_half"}
    assert {s["key"] for s in LONG_AGREE_TRIALS} == {"long_agree_005", "long_agree_010", "long_agree_020", "long_agree_025"}
    assert {s["key"] for s in SCORE_TRIALS} == {"score_thr_25", "score_thr_30", "score_thr_40", "score_thr_45"}
    assert {s["key"] for s in DIR_BOOST_TRIALS} == {"dir_boost_30_70", "dir_boost_40_60", "dir_boost_60_40", "dir_boost_70_30"}
    assert {s["key"] for s in ACCEL_BOOST_TRIALS} == {"accel_boost_50_50", "accel_boost_60_40", "accel_boost_80_20", "accel_boost_90_10"}
    assert {s["key"] for s in SWITCH_TRIALS} == {"macd_golden_on"}
    keys = [s["key"] for s in P5_TRIALS]
    assert len(keys) == len(set(keys)), "trial key 重复"
    assert len(P5_TRIALS) + 1 == 23  # + baseline


def test_trial_level_values():
    """档位值逐个断言（6 组标量/list 档位与方案 P5-a 表一致）。"""
    patches = {s["key"]: s["overrides"] for s in P5_TRIALS}
    assert [patches[k]["momentumLongAgreeThreshold"] for k in ("long_agree_005", "long_agree_010", "long_agree_020", "long_agree_025")] == [0.05, 0.10, 0.20, 0.25]
    assert [patches[k]["momentumScoreThreshold"] for k in ("score_thr_25", "score_thr_30", "score_thr_40", "score_thr_45")] == [25, 30, 40, 45]
    assert [patches[k]["momentumDirectionShareBoost"] for k in ("dir_boost_30_70", "dir_boost_40_60", "dir_boost_60_40", "dir_boost_70_30")] == [
        [0.3, 0.7], [0.4, 0.6], [0.6, 0.4], [0.7, 0.3],
    ]
    assert [patches[k]["momentumAccelShareBoost"] for k in ("accel_boost_50_50", "accel_boost_60_40", "accel_boost_80_20", "accel_boost_90_10")] == [
        [0.5, 0.5], [0.6, 0.4], [0.8, 0.2], [0.9, 0.1],
    ]
    assert patches["macd_golden_on"] == {"requireMacdGoldenCross": True}  # 二值开关 1 对照（总纲豁免 5 档口径）
    # share 份额和=1 约束（乘性位置 raw×(b0+b1×share)，乘子范围 [b0,1]）
    for group in (DIR_BOOST_TRIALS, ACCEL_BOOST_TRIALS):
        for spec in group:
            boost = list(spec["overrides"].values())[0]
            assert abs(sum(boost) - 1.0) < 1e-9


def test_thresholds_mirror_scale_arithmetic():
    """镜像同步缩放算术自检：×0.5 / ×0.75 / ×1.25 / ×1.5 两 list 逐元素断言 + 快半档对照。"""
    assert _scale_thresholds(0.5) == {
        "buyThresholds": [2.5, 4.0, 6.5, 10.5, 17.0],
        "sellThresholds": [-2.5, -4.0, -6.5, -10.5, -17.0],
    }
    assert _scale_thresholds(0.75) == {
        "buyThresholds": [3.75, 6.0, 9.75, 15.75, 25.5],
        "sellThresholds": [-3.75, -6.0, -9.75, -15.75, -25.5],
    }
    assert _scale_thresholds(1.25) == {
        "buyThresholds": [6.25, 10.0, 16.25, 26.25, 42.5],
        "sellThresholds": [-6.25, -10.0, -16.25, -26.25, -42.5],
    }
    assert _scale_thresholds(1.5) == {
        "buyThresholds": [7.5, 12.0, 19.5, 31.5, 51.0],
        "sellThresholds": [-7.5, -12.0, -19.5, -31.5, -51.0],
    }
    fast = next(s for s in THRESHOLDS_TRIALS if s["key"] == "thr_fast_half")
    assert fast["overrides"] == {
        "buyThresholds": [3, 5, 8, 13, 21],
        "sellThresholds": [-3, -5, -8, -13, -21],
    }  # 快半档：档位前移非等比（≈ momentumPeriods 同构），负镜像同步
    # 等比档 trial 与 helper 一致；×1.0=baseline 承担，不在表内
    assert not any(s["key"] == "thr_x10" for s in THRESHOLDS_TRIALS)
    for factor, key in ((0.5, "thr_x05"), (0.75, "thr_x075"), (1.25, "thr_x125"), (1.5, "thr_x15")):
        spec = next(s for s in THRESHOLDS_TRIALS if s["key"] == key)
        assert spec["overrides"] == _scale_thresholds(factor)


def test_single_axis_separation():
    """单变量拆分：每个 trial 只动自己轴字段，禁止跨轴/打包（thresholds 双 list 算同轴同步替换）。"""
    axis_fields = {
        "thr_": {"buyThresholds", "sellThresholds"},
        "long_agree_": {"momentumLongAgreeThreshold"},
        "score_thr_": {"momentumScoreThreshold"},
        "dir_boost_": {"momentumDirectionShareBoost"},
        "accel_boost_": {"momentumAccelShareBoost"},
        "macd_golden_": {"requireMacdGoldenCross"},
    }
    for spec in P5_TRIALS:
        matched = [p for p in axis_fields if spec["key"].startswith(p)]
        assert len(matched) == 1, f"{spec['key']} 不匹配任何已知轴前缀或重匹配：{matched}"
        expected = axis_fields[matched[0]]
        assert set(spec["overrides"]) == expected, f"{spec['key']} 越轴：{set(spec['overrides'])} != {expected}"


def test_thresholds_len5_precheck_rejects_bad_patches():
    """预检纪律 1：from_patch 对 list 长度零校验（短 list 运行期 IndexError、长 list 静默截断）
    ——harness 预检必须拒绝，防 trial 假绿。"""
    with pytest.raises(AssertionError, match="5 元素"):
        _assert_thresholds_len5({"buyThresholds": [5, 8, 13], "sellThresholds": [-5, -8, -13]})  # 短 list
    with pytest.raises(AssertionError, match="5 元素"):
        _assert_thresholds_len5({"buyThresholds": [5, 8, 13, 21, 34, 55], "sellThresholds": [-5, -8, -13, -21, -34, -55]})  # 长 list 静默截断形态
    with pytest.raises(AssertionError, match="同步替换"):
        _assert_thresholds_len5({"buyThresholds": [2.5, 4, 6.5, 10.5, 17]})  # 单侧替换违反镜像同步约束
    with pytest.raises(AssertionError, match="镜像"):
        _assert_thresholds_len5({"buyThresholds": [5, 8, 13, 21, 34], "sellThresholds": [-6, -8, -13, -21, -34]})  # 非镜像
    _assert_thresholds_len5(_scale_thresholds(0.5))  # 合法档位（含浮点）放行
    _assert_thresholds_len5({"buyThresholds": [3, 5, 8, 13, 21], "sellThresholds": [-3, -5, -8, -13, -21]})
    _assert_thresholds_len5({"momentumScoreThreshold": 40})  # 非 thresholds patch 直通


def test_all_patches_construct_valid_configs():
    """22 个 patch 全部可构造合法 config（from_patch + 预检 + override 生效三重验证）。"""
    for spec in P5_TRIALS:
        _assert_thresholds_len5(spec["overrides"])
        config = RankTrendConfig.from_patch(spec["overrides"])
        assert config is not None
        _assert_overrides_applied(config, spec["overrides"])


def test_anchor_baseline_constant():
    """锚代际：post-fund10 基线锚（2026-09-15 fund10 落默认后；主代理已实测 oos2=0.0951）。"""
    assert ANCHOR_BASELINE == {"decision": 0.112, "oos1": 0.088, "oos2": 0.0951}


def test_baseline_spec_carries_anchor():
    """baseline 承担 ×1.0 默认档与锚断言：空 overrides + ANCHOR_BASELINE。"""
    spec = baseline_spec()
    assert spec["key"] == "baseline"
    assert spec["overrides"] == {}
    assert spec["anchor"] == ANCHOR_BASELINE


def test_assert_overrides_applied_rejects_unknown_field():
    """from_patch 对未知字段静默忽略（hasattr 无 else）——harness 必须逐键断言 override 生效。"""
    ok = RankTrendConfig.from_patch({"momentumScoreThreshold": 40})
    _assert_overrides_applied(ok, {"momentumScoreThreshold": 40})
    bad = RankTrendConfig.from_patch({"momentumScoreThresholdTypo": 40})
    with pytest.raises(AssertionError, match="override 未生效"):
        _assert_overrides_applied(bad, {"momentumScoreThresholdTypo": 40})


def test_save_strips_frames_cache(tmp_path):
    """__frames__ 全量帧缓存不得落盘（同 cs harness review I1）。"""
    report = {
        "__out__": str(tmp_path / "trend-leftover.json"),
        "__frames__": {"decision": [{"tradingDate": "2026-05-04"}]},
        "decision": {"window": {"frameCount": 1}},
    }
    _save(report)
    saved = json.loads((tmp_path / "trend-leftover.json").read_text(encoding="utf-8"))
    assert "__frames__" not in saved
    assert "__out__" not in saved
    assert saved["decision"]["window"]["frameCount"] == 1
    assert saved["windowsConsumed"] is True  # OOS-2 已被部分消费（M3 折扣标注）


def test_resume_reruns_freeze_guard(monkeypatch, tmp_path):
    """resume（已含 window 条目）路径仍必须执行 8 月冻结守卫。"""
    monkeypatch.setattr(
        "backend.operations.optimize_resonance_parameters.load_frames",
        lambda s, e: [{"tradingDate": "2026-08-05"}],
    )
    monkeypatch.setattr(
        "backend.analysis.ranktrend.engine.RankTrendPythonEngine",
        lambda config=None: SimpleNamespace(replay=lambda frames, meta=None: []),
    )
    monkeypatch.setattr(
        "backend.operations.evaluate_trend_leftover_parameters.evaluate_gate",
        lambda config, frames: {"synergy": {"saEx": None, "passHard": False}, "rankTrend": {"saEx": None, "passHard": False}},
    )
    report = {
        "__out__": str(tmp_path / "r.json"),
        "decision": {"window": {"start": "2026-04-15", "end": "2026-07-31", "frameCount": 1}},
    }
    with pytest.raises(ValueError, match="冻结"):
        run_window("decision", report)


def test_run_window_executes_extra_trial(monkeypatch, tmp_path):
    """--extra-trial 注入的 trial 必须真实进执行循环（review C2 同款）。"""
    monkeypatch.setattr(
        "backend.operations.optimize_resonance_parameters.load_frames",
        lambda s, e: [{"tradingDate": "2026-05-04"}],
    )
    monkeypatch.setattr(
        "backend.analysis.ranktrend.engine.RankTrendPythonEngine",
        lambda config=None: SimpleNamespace(replay=lambda frames, meta=None: []),
    )
    monkeypatch.setattr(
        "backend.operations.evaluate_trend_leftover_parameters.evaluate_gate",
        lambda config, frames: {"synergy": {"saEx": None, "passHard": False}, "rankTrend": {"saEx": None, "passHard": False}},
    )
    specs = [
        baseline_spec(),
        {"key": "extra_probe", "desc": "P5-b 精扫追加", "overrides": {"momentumScoreThreshold": 40}, "anchor": None},
    ]
    report = {"__out__": str(tmp_path / "r.json")}
    run_window("decision", report, specs=specs)
    trials = report["decision"]["trials"]
    assert "baseline" in trials
    assert "extra_probe" in trials
    assert trials["extra_probe"]["overrides"] == {"momentumScoreThreshold": 40}


def test_run_window_rejects_bad_thresholds_spec(monkeypatch, tmp_path):
    """预检在执行循环内生效：长度错误的 thresholds trial 在触引擎前被拒。"""
    monkeypatch.setattr(
        "backend.operations.optimize_resonance_parameters.load_frames",
        lambda s, e: [{"tradingDate": "2026-05-04"}],
    )
    engine_calls: list[str] = []

    def _boom(config=None):
        engine_calls.append("constructed")
        raise AssertionError("引擎不应被构造")

    monkeypatch.setattr("backend.analysis.ranktrend.engine.RankTrendPythonEngine", _boom)
    specs = [{"key": "bad_thr", "desc": "短 list", "overrides": {"buyThresholds": [5, 8], "sellThresholds": [-5, -8]}, "anchor": None}]
    report = {"__out__": str(tmp_path / "r.json")}
    with pytest.raises(AssertionError, match="5 元素"):
        run_window("decision", report, specs=specs)
    assert engine_calls == []


def test_main_wires_extra_trial_into_execution_loop(monkeypatch, tmp_path):
    """main() 全链路：--extra-trial 从 argparse 注入执行循环并落盘。"""
    monkeypatch.setattr(
        "backend.operations.optimize_resonance_parameters.load_frames",
        lambda s, e: [{"tradingDate": "2026-05-04"}],
    )
    monkeypatch.setattr(
        "backend.analysis.ranktrend.engine.RankTrendPythonEngine",
        lambda config=None: SimpleNamespace(replay=lambda frames, meta=None: []),
    )
    monkeypatch.setattr(
        "backend.operations.evaluate_trend_leftover_parameters.evaluate_gate",
        lambda config, frames: {"synergy": {"saEx": None, "passHard": False}, "rankTrend": {"saEx": None, "passHard": False}},
    )
    out = tmp_path / "main-run.json"
    extra = json.dumps({"key": "p5b_probe", "desc": "精扫", "overrides": {"momentumLongAgreeThreshold": 0.20}})
    monkeypatch.setattr(sys, "argv", ["prog", "--window", "oos2", "--out", str(out), "--extra-trial", extra])

    from backend.operations import evaluate_trend_leftover_parameters as harness

    assert harness.main() == 0
    saved = json.loads(out.read_text(encoding="utf-8"))
    trials = saved["oos2"]["trials"]
    assert "baseline" in trials
    assert len(trials) == 24  # baseline + 22 + 1 extra
    assert trials["p5b_probe"]["overrides"] == {"momentumLongAgreeThreshold": 0.20}
    assert saved["windowsConsumed"] is True
    assert "__frames__" not in saved


def test_trigger_rate_flag_line():
    assert TRIGGER_RATE_FLAG == 0.035  # 阶段 22.6 观察线


def test_trigger_rate_of():
    result = {"synergy": {"distribution": {"S": 3, "A": 4, "C": 93}}}
    assert trigger_rate_of(result) == 0.07
    assert trigger_rate_of({"synergy": {}}) is None  # fail-visible：缺分布如实 None，不伪造 0


def _mk_report(decision_rel: float = 0.0, oos_rel: float = 0.0, trial_pass: bool = True, base_pass: bool = True) -> dict:
    def _win(base_sa: float, trial_sa: float, trend_base: float = 0.02, trend_trial: float = 0.02) -> dict:
        rel = (trial_sa - base_sa) / abs(base_sa)
        return {"trials": {
            "baseline": {"result": {
                "synergy": {"saEx": base_sa, "passHard": base_pass, "distribution": {"S": 1, "A": 2, "C": 97}},
                "rankTrend": {"saEx": trend_base, "passHard": True},
            }},
            "t_x": {"result": {
                "synergy": {"saEx": trial_sa, "passHard": trial_pass, "distribution": {"S": 1, "A": 2, "C": 97}},
                "rankTrend": {"saEx": trend_trial, "passHard": True},
            }},
        }, "_rel": rel}

    decision = _win(0.100, 0.100 * (1 + decision_rel))
    oos1 = _win(0.080, 0.080 * (1 + oos_rel))
    oos2 = _win(0.090, 0.090 * (1 + oos_rel))
    return {"decision": decision, "oos1": oos1, "oos2": oos2}


def test_trial_summary_card_and_focus_dims():
    """判定卡 C1/C2/C3 → PASS_CANDIDATE；focus 维 rankTrendSaEx(Rel) 同批输出。"""
    report = _mk_report(decision_rel=0.04, oos_rel=0.01)
    summary = trial_summary(report, {"key": "t_x"})
    assert summary["verdictCard"] == {"C1_decisionRelGE3pct": True, "C2_oosAnyPositive": True, "C3_decisionPassHard": True}
    assert summary["cardResult"] == "PASS_CANDIDATE"
    for win in ("decision", "oos1", "oos2"):
        assert "rankTrendSaEx" in summary["windows"][win]
        assert "rankTrendSaExRel" in summary["windows"][win]
        assert summary["windows"][win]["triggerFlag"] is False  # S+A = 3/100 = 3% < 3.5% 观察线


def test_trial_summary_observe_when_card_fails():
    report = _mk_report(decision_rel=0.01, oos_rel=-0.02)
    summary = trial_summary(report, {"key": "t_x"})
    assert summary["cardResult"] == "OBSERVE"
    assert summary["verdictCard"]["C1_decisionRelGE3pct"] is False
    assert summary["verdictCard"]["C2_oosAnyPositive"] is False


def test_trial_summary_c3_is_drop_semantics():
    """C3 = decision passHard 不降：baseline True → trial False 才算降；False→False 不降。"""
    report = _mk_report(decision_rel=0.04, oos_rel=0.01, trial_pass=False, base_pass=True)
    summary = trial_summary(report, {"key": "t_x"})
    assert summary["verdictCard"]["C3_decisionPassHard"] is False
    assert summary["cardResult"] == "OBSERVE"
    report2 = _mk_report(decision_rel=0.04, oos_rel=0.01, trial_pass=False, base_pass=False)
    summary2 = trial_summary(report2, {"key": "t_x"})
    assert summary2["verdictCard"]["C3_decisionPassHard"] is True


def test_trial_summary_insufficient_data_is_visible():
    summary = trial_summary({}, {"key": "t_x"})
    assert summary["verdict"] == "insufficient_data"  # fail-visible：不伪造卡片
