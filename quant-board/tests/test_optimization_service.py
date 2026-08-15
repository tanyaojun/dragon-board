# -*- coding: utf-8 -*-
"""OptimizationService._build_request 链路测试（阶段 1：字段白名单投影下传）。"""
from __future__ import annotations

from typing import Any

from backend.services.optimization_service import OptimizationService
from backend.services.shared import BACKTEST_RANKTREND_STOCK_FIELDS


class _StubRepo:
    def __init__(self, frames: list[dict[str, Any]]) -> None:
        self.frames = frames
        self.last_fields: list[str] | None = None

    def load_frames(
        self,
        dataset_id: str,
        snapshot_type: str = "half_hour",
        start_date: str | None = None,
        end_date: str | None = None,
        include_payload: bool = True,
        fields: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        self.last_fields = fields
        return self.frames


def _minimal_frames() -> list[dict[str, Any]]:
    # 两帧且每帧至少一行，能通过 _prepare_frames_for_backtest 的 quality gate（min_snapshot_count=2）
    return [
        {
            "snapshotId": "s1", "type": "half_hour", "timestamp": 1,
            "tradingDate": "2026-08-01", "slotTime": "10:00",
            "captureMode": "real_time", "source": "test",
            "stocks": [{"snapshotId": "s1", "code": "000001", "capitalFlowSource": "ths"}],
        },
        {
            "snapshotId": "s2", "type": "half_hour", "timestamp": 2,
            "tradingDate": "2026-08-01", "slotTime": "10:30",
            "captureMode": "real_time", "source": "test",
            "stocks": [{"snapshotId": "s2", "code": "000002", "capitalFlowSource": "ths"}],
        },
    ]


def test_build_request_passes_field_whitelist_to_load_frames() -> None:
    stub = _StubRepo(_minimal_frames())
    # __new__ 绕过 __init__（避免 create_repository 连接真实 Mongo）；
    # 前提：_build_request 只访问 self.repo（当前实现 :293 唯一 self 访问点，落地时如增加 self 依赖需同步调整）
    service = OptimizationService.__new__(OptimizationService)
    service.repo = stub

    payload = {
        "dataset_id": "dragonboard_live",
        "snapshot_type": "half_hour",
        "method": "random",
        "max_trials": 4,
        "random_seed": 20260430,
    }
    dataset_id, snapshot_type, strategy_name, run_frames, request, payload_for_request_json = service._build_request(payload)

    assert dataset_id == "dragonboard_live"
    assert len(run_frames) == 2
    assert stub.last_fields == list(BACKTEST_RANKTREND_STOCK_FIELDS)
    assert "fields" not in request  # 投影字段只用于数据加载，不进优化请求体（payload_for_request_json 亦不含）
