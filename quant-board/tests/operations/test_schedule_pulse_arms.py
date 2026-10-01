# -*- coding: utf-8 -*-
"""SP2-B 排程脉拍多臂测试：_pulse_arms_args 的预算/回退/畸形容错 + 配置文件合同。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations import schedule


def _write_arms(tmp_path, payload) -> Path:
    p = tmp_path / "arms.json"
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return p


def test_pulse_arms_args_with_config(tmp_path):
    cfg = tmp_path / "arms.json"
    cfg.write_text(json.dumps({
        "exit_v1": {"trade_config": {"phaseExitCoupling": {"mode": "per_band", "bands": {}}}},
        "slot_v1": {"trade_config": {"phaseExposureControl": {"source": "slot_then_prev_eod"}}},
    }, ensure_ascii=False), encoding="utf-8")
    original = schedule._ARMS_CONFIG_PATH
    try:
        schedule._ARMS_CONFIG_PATH = cfg
        args = schedule._pulse_arms_args()
        assert args == ["--arms", "baseline,champion,exit_v1,slot_v1", "--arm-config", str(cfg)]
    finally:
        schedule._ARMS_CONFIG_PATH = original


def test_pulse_arms_args_budget_truncates_to_two(tmp_path):
    cfg = tmp_path / "arms.json"
    cfg.write_text(json.dumps({
        f"c{i}": {"trade_config": {}} for i in (1, 2, 3)
    }, ensure_ascii=False), encoding="utf-8")
    original = schedule._ARMS_CONFIG_PATH
    try:
        schedule._ARMS_CONFIG_PATH = cfg
        args = schedule._pulse_arms_args()
        assert args[1] == "baseline,champion,c1,c2"  # 预算 ≤2（章程 §5.6），c3 截断
    finally:
        schedule._ARMS_CONFIG_PATH = original


def test_pulse_arms_args_missing_file_falls_back(tmp_path):
    original = schedule._ARMS_CONFIG_PATH
    try:
        schedule._ARMS_CONFIG_PATH = tmp_path / "missing.json"
        assert schedule._pulse_arms_args() == []
    finally:
        schedule._ARMS_CONFIG_PATH = original


def test_pulse_arms_args_malformed_json_falls_back(tmp_path):
    cfg = tmp_path / "arms.json"
    cfg.write_text("{not json", encoding="utf-8")
    original = schedule._ARMS_CONFIG_PATH
    try:
        schedule._ARMS_CONFIG_PATH = cfg
        assert schedule._pulse_arms_args() == []
    finally:
        schedule._ARMS_CONFIG_PATH = original


def test_pulse_arms_args_skips_malformed_entries(tmp_path):
    cfg = tmp_path / "arms.json"
    cfg.write_text(json.dumps({
        "good": {"trade_config": {}},
        "broken": {},  # 缺 trade_config
        "notdict": "oops",
    }, ensure_ascii=False), encoding="utf-8")
    original = schedule._ARMS_CONFIG_PATH
    try:
        schedule._ARMS_CONFIG_PATH = cfg
        args = schedule._pulse_arms_args()
        assert args[1] == "baseline,champion,good"
    finally:
        schedule._ARMS_CONFIG_PATH = original


def test_committed_arms_config_matches_ledger_budget():
    """入库配置合同：恰好 2 个挑战者（章程 §5.6 预算），且都有 trade_config。"""
    raw = json.loads(schedule._ARMS_CONFIG_PATH.read_text(encoding="utf-8"))
    challengers = [k for k, v in raw.items()
                   if isinstance(v, dict) and isinstance(v.get("trade_config"), dict)
                   and k not in ("baseline", "champion")]
    assert len(challengers) <= 2
    assert set(challengers) == {"exit_v1", "slot_v1"}  # 台账登记的在跑臂；rebal_v1 排队
