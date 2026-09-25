# -*- coding: utf-8 -*-
"""scan_repool_sample_floor B-202610 演练扩展测试：oos2u 终判窗 + horizon（h8）口径。

2026-09-25 演练（rerun-plan §5.1.3.4/§8 N8 终判执行内容）：
- --window 需接受 oos2u（未消费裁决窗；本批次执行属 §2.1 消费禁令的豁免场景）；
- --horizon 需透传（N8 终判要求补 h8 口径读数）；默认 1 保持 golden 路径零漂移，
  result 键名按 horizon 动态生成（lifecycleH1/h1 在默认值下与历史报告键名一致）。
"""
from __future__ import annotations

import json
import sys

from backend.operations import scan_repool_sample_floor as scan_mod


def _frames() -> list[dict]:
    frames = []
    for i in range(8):
        frames.append(
            {
                "snapshotId": f"half_hour:2026-08-20:{i:02d}",
                "tradingDate": "2026-08-20",
                "type": "half_hour",
                "timestamp": i,
                "stocks": [
                    {"code": "000001", "name": "常驻", "rank": 2 - (i % 2), "avgRankNum": 20.0, "change": 1.5},
                    {"code": "000002", "name": "回池", "rank": 1 + (i % 2), "avgRankNum": 20.0, "change": -0.5},
                ],
            }
        )
    return frames


def _run(monkeypatch, argv: list[str], out: str) -> None:
    monkeypatch.setattr(scan_mod, "load_frames", lambda start, end: _frames())
    monkeypatch.setattr(sys, "argv", ["prog", *argv, "--out", out])
    assert scan_mod.main() == 0


def test_oos2u_window_supported(monkeypatch, tmp_path):
    """--window oos2u 必须可跑（N8 终判窗）；run_window 底层本就走 data_windows.WINDOWS。"""
    out = str(tmp_path / "scan.json")
    _run(monkeypatch, ["--window", "oos2u"], out)
    report = json.loads(open(out, encoding="utf-8").read())
    assert "oos2u" in report
    assert report["windowsConsumed"] == ["oos2u"]
    trials = report["oos2u"]["trials"]
    assert set(trials) == {"baseline", "floor3", "floor4", "floor7", "floor10"}
    assert trials["baseline"]["isBaseline"] is True


def test_horizon_default_keeps_legacy_keys(monkeypatch, tmp_path):
    """默认 horizon=1：result 键名 lifecycleH1/h1 与历史报告逐字一致（golden 不漂移）。"""
    out = str(tmp_path / "scan.json")
    _run(monkeypatch, ["--window", "oos1"], out)
    report = json.loads(open(out, encoding="utf-8").read())
    baseline = report["oos1"]["trials"]["baseline"]
    assert "lifecycleH1" in baseline
    assert "horizon" in baseline and baseline["horizon"] == 1
    floor3 = report["oos1"]["trials"]["floor3"]
    assert "h1" in floor3["newlyJudged"]


def test_horizon_8_passthrough(monkeypatch, tmp_path):
    """--horizon 8：lifecycle 统计与新增判定样本质量全部走 h8 口径，键名同步标注。"""
    out = str(tmp_path / "scan.json")
    _run(monkeypatch, ["--window", "oos1", "--horizon", "8"], out)
    report = json.loads(open(out, encoding="utf-8").read())
    baseline = report["oos1"]["trials"]["baseline"]
    assert baseline["horizon"] == 8
    assert "lifecycleH8" in baseline and "lifecycleH1" not in baseline
    floor3 = report["oos1"]["trials"]["floor3"]
    assert "h8" in floor3["newlyJudged"] and "h1" not in floor3["newlyJudged"]
    h8 = floor3["newlyJudged"]["h8"]
    assert h8.get("frameCount") == len(_frames())  # 统计容器真实产出（非空壳）
