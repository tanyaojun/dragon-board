# -*- coding: utf-8 -*-
"""scan_repool_sample_floor resume 路径测试（2026-09-21 review Critical 修复防线）。

渐进 resume 场景：baseline trial 已缓存而后续 trial 缺失时，run_window 必须重算
baseline status map 作为新增判定样本的对照集——空对照会把 newlyJudged 全部伪装成 0
（「无新增样本」假结论，2026-09-21 review 前 resume 路径的真实缺陷）。
"""
from __future__ import annotations

import json
import sys

from backend.operations import scan_repool_sample_floor as scan_mod


def _frames_with_repooled_stock() -> list[dict]:
    """出池回池场景合成帧：股 A（000001）8 帧全在（degraded）；股 B（000002）只在前
    3 帧出现——baseline(floor5) 判 insufficient、floor3 判 degraded → 新增判定样本
    恰好 1 条（H0 检验的输入非空）。rank 落在 1..2（tier_forward_returns 分母=帧内
    股数）。"""
    frames = []
    for i in range(8):
        stocks = [
            {"code": "000001", "name": "常驻", "rank": 2 - (i % 2), "avgRankNum": 20.0, "change": 1.5},
        ]
        if i < 3:
            stocks.append(
                {"code": "000002", "name": "回池", "rank": 1 + (i % 2), "avgRankNum": 20.0, "change": -0.5}
            )
        frames.append(
            {
                "snapshotId": f"half_hour:2026-08-20:{i:02d}",
                "tradingDate": "2026-08-20",
                "type": "half_hour",
                "timestamp": i,
                "stocks": stocks,
            }
        )
    return frames


def _run(monkeypatch, out: str) -> None:
    monkeypatch.setattr(scan_mod, "load_frames", lambda start, end: _frames_with_repooled_stock())
    monkeypatch.setattr(sys, "argv", ["prog", "--window", "oos1", "--out", out])
    assert scan_mod.main() == 0


def test_full_run_newly_judged_is_nonzero(tmp_path, monkeypatch):
    out = str(tmp_path / "scan.json")
    _run(monkeypatch, out)
    report = json.loads(open(out, encoding="utf-8").read())
    floor3 = report["oos1"]["trials"]["floor3"]
    # A(sampleCount 3/4) + B(sampleCount 3) 三帧：baseline(5) insufficient、floor3 degraded
    assert floor3["newlyJudged"]["newlyJudgedCount"] == 3
    assert report["windowsConsumed"] == ["oos1"]


def test_resume_rebuilds_baseline_status_map(tmp_path, monkeypatch):
    out = str(tmp_path / "scan.json")
    _run(monkeypatch, out)
    full = json.loads(open(out, encoding="utf-8").read())
    expected = full["oos1"]["trials"]["floor3"]["newlyJudged"]

    # 模拟中断：baseline 已落盘、floor3 缺失（渐进 resume 的真实形态）
    interrupted = json.loads(open(out, encoding="utf-8").read())
    interrupted["oos1"]["trials"].pop("floor3")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(interrupted, fh, ensure_ascii=False, indent=2)

    _run(monkeypatch, out)
    resumed = json.loads(open(out, encoding="utf-8").read())
    floor3 = resumed["oos1"]["trials"]["floor3"]
    # 修复前：baseline_status 空 → newlyJudgedCount 恒 0（假冒 0）
    assert floor3["newlyJudged"]["newlyJudgedCount"] == expected["newlyJudgedCount"] == 3
    assert floor3["newlyJudged"]["lifecycleTierDist"] == expected["lifecycleTierDist"]
    # windowsConsumed 跨 resume 不丢失（Important 修复）
    assert resumed["windowsConsumed"] == ["oos1"]


def test_resume_rejects_legacy_schema_and_reruns_fresh(tmp_path, monkeypatch):
    out = str(tmp_path / "scan.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({"oos1": {"trials": {"baseline": {"note": "f686ada5 时代无版本字段"}}}}, fh)

    _run(monkeypatch, out)
    report = json.loads(open(out, encoding="utf-8").read())
    # 旧格式缓存弃用 → 全新跑（floor3 由本次实跑产出，非旧缓存）
    assert report["schemaVersion"] == scan_mod.SCHEMA_VERSION
    assert report["oos1"]["trials"]["floor3"]["newlyJudged"]["newlyJudgedCount"] == 3
