# -*- coding: utf-8 -*-
"""「算不出来」也落库为「无阶段」（spec §4，用户裁决）。

背景：部分股票在整个历史窗口内没有有效 ``avgRankNum``（八平台均榜排名），建不起
attention 序列 → 被 ``_analyze_frames`` 的 gate 跳过 → 不落 ``snapshot_analysis``
→ hotlist join 取不到 ``displayStatus`` → 落旧口径 ``fallback``。全库约 1/5 的
``snapshot_stock_rows`` 如此，兜底因此消不掉。

本机制把它们显式落库为 ``cycle=None`` + ``meta.sampleQuality.status=insufficient``，
经纯投影得出 ``{stage: None, label: "无阶段"}``：阶段缺失在 ``stageCounts.unknown``
里如实体现，而**不伪装成任何 lifecycle 阶段**（fail-visible，不静默）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.services import snapshot_analysis_service as svc

SERVICE_PATH = (
    Path(__file__).resolve().parent.parent / "backend" / "services" / "snapshot_analysis_service.py"
)


def _frame(codes: list[str]) -> dict[str, Any]:
    return {
        "tradingDate": "2026-07-06",
        "slotTime": "14:00",
        "type": "half_hour",
        "snapshotId": "half_hour:2026-07-06:14:00",
        "stocks": [
            {"code": code, "price": 10.0 + index, "rank": index + 1}
            for index, code in enumerate(codes)
        ],
    }


def test_insufficient_entries_fill_rows_without_analysis() -> None:
    entries = svc._insufficient_entries(_frame(["300671", "688362"]), {"688362"})

    assert [entry["code"] for entry in entries] == ["300671"]
    analysis = entries[0]["analysis"]
    assert analysis["meta"]["sampleQuality"]["status"] == "insufficient"
    assert analysis["observation"]["status"] == "insufficient"
    # 无阶段：不得伪装成任何 lifecycle 阶段（stageCounts.unknown 里如实体现）
    assert analysis["cycle"] is None
    # displayStatus 必须随 entry 落库（hotlist join 只读 analysis.displayStatus）
    assert analysis["displayStatus"] == {
        "stage": None,
        "label": "无阶段",
        "tooltip": "生命周期阶段缺失或非法，无法判定。",
    }


def test_insufficient_entries_skip_seen_and_malformed_rows() -> None:
    frame = _frame(["300671"])
    frame["stocks"].extend([{"code": ""}, "not-a-dict", {"noCode": True}])

    assert svc._insufficient_entries(frame, {"300671"}) == []


def test_compute_snapshot_analysis_appends_insufficient_entries(monkeypatch) -> None:
    frame = _frame(["600000", "300671"])
    monkeypatch.setattr(svc, "_load_frames_for_analysis", lambda *args, **kwargs: ([{"x": 1}], {"600000": []}))
    monkeypatch.setattr(
        svc,
        "_analyze_frames",
        lambda *args, **kwargs: [
            {"stocks": [{"code": "600000", "analysis": {"observation": {"rankTrend": {}}}}]}
        ],
    )
    monkeypatch.setattr(svc, "RankTrendPythonEngine", lambda *args, **kwargs: object())

    entries = svc.compute_snapshot_analysis(object(), "dragonboard_live", "half_hour", frame)

    assert [entry["code"] for entry in entries] == ["600000", "300671"]
    assert entries[1]["analysis"]["displayStatus"]["label"] == "无阶段"
    assert entries[1]["analysis"]["displayStatus"]["stage"] is None


def test_compute_snapshot_analysis_falls_back_to_full_frame_when_no_output(monkeypatch) -> None:
    frame = _frame(["600000", "300671"])
    monkeypatch.setattr(svc, "_load_frames_for_analysis", lambda *args, **kwargs: ([], {}))

    entries = svc.compute_snapshot_analysis(object(), "dragonboard_live", "half_hour", frame)

    # 无帧也必须 fail-visible（整帧「无阶段」），不得静默返回空
    assert [entry["code"] for entry in entries] == ["600000", "300671"]
    assert all(entry["analysis"]["displayStatus"]["label"] == "无阶段" for entry in entries)


def test_snapshot_analysis_service_contract_keeps_insufficient_fill() -> None:
    source = SERVICE_PATH.read_text(encoding="utf-8")

    assert "_insufficient_entries(" in source
    assert "compute_display_status(analysis, row)" in source
    assert '"sampleQuality": {"status": "insufficient"' in source
    assert '"cycle": None,' in source
