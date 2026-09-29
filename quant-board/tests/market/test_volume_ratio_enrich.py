from __future__ import annotations

from backend.snapshot_collector.service import SnapshotCollectorService
import backend.services.market.volume_ratio_service as vrs
import backend.data.repositories.repository_factory as rf


def _service() -> SnapshotCollectorService:
    # _enrich_volume_ratios 不依赖 repo，仅需合法实例
    return SnapshotCollectorService(repo=object())


def test_enrich_overrides_existing_volume_ratio_with_golden(monkeypatch) -> None:
    monkeypatch.setattr(rf, "get_runtime_mongodb_database", lambda: None)
    monkeypatch.setattr(
        vrs,
        "compute_volume_ratios",
        lambda db, stocks: {
            "000001": {
                "volumeRatio": 2.6,
                "status": "available",
                "source": "quantboard_volume_ratio",
                "calculatedAt": 123,
            }
        },
    )
    rows = [
        {
            "code": "000001",
            "volumeRatio": 1.8,
            "volumeRatioMeta": {"source": "tencent_f10", "status": "available"},
        }
    ]
    _service()._enrich_volume_ratios(rows)
    # golden 三日口径覆盖腾讯 f10
    assert rows[0]["volumeRatio"] == 2.6
    assert rows[0]["volumeRatioMeta"]["source"] == "quantboard_volume_ratio"


def test_enrich_keeps_tencent_f10_when_golden_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(rf, "get_runtime_mongodb_database", lambda: None)
    monkeypatch.setattr(
        vrs,
        "compute_volume_ratios",
        lambda db, stocks: {
            "000001": {
                "volumeRatio": None,
                "status": "unavailable",
                "reason": "insufficient_history",
                "source": "unavailable",
            }
        },
    )
    rows = [
        {
            "code": "000001",
            "volumeRatio": 1.8,
            "volumeRatioMeta": {"source": "tencent_f10", "status": "available"},
        }
    ]
    _service()._enrich_volume_ratios(rows)
    # golden 不可用时保留腾讯 f10 兜底值与其来源标记
    assert rows[0]["volumeRatio"] == 1.8
    assert rows[0]["volumeRatioMeta"]["source"] == "tencent_f10"


def test_enrich_failure_keeps_rows_untouched(monkeypatch) -> None:
    monkeypatch.setattr(rf, "get_runtime_mongodb_database", lambda: None)
    monkeypatch.setattr(
        vrs,
        "compute_volume_ratios",
        lambda db, stocks: (_ for _ in ()).throw(RuntimeError("db down")),
    )
    rows = [{"code": "000001", "volumeRatio": 1.8}]
    _service()._enrich_volume_ratios(rows)
    # fail-visible：计算异常不阻断、不改动已有行
    assert rows[0]["volumeRatio"] == 1.8
