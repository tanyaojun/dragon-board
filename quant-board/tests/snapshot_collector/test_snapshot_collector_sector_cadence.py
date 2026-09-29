"""题材行携带频率策略（SECTOR_SNAPSHOT_TYPES）测试。

2026-09-28 用户决策：题材热度半小时一档已够研究用，five_minutes / quarter_hour
帧不携带题材行（sector rows + snapshot_context 题材原料一并剥离），题材序列研究
走 half_hour / hourly / daily 帧。配套约束：

1. 同刻多类型共享一次采集时，只有高频帧剥离题材行，同组 half_hour 帧不受影响；
2. 纯高频槽位唤醒（如 10:05 只有 five_minutes）整组跳过 theme heat 计算，
   题材上游开销不随 5 分钟采集频率放大；
3. 剥离是口径决策而非采集失败：必须落 qualityFlags（fail-visible），
   防止下游把空题材行误读为采集故障。
"""

from __future__ import annotations

import asyncio
from typing import Any

from backend.data.ingest.snapshot_ingest_normalizer import normalize_snapshot_ingest
from backend.snapshot_collector.models import (
    CollectorRunRequest,
    MarketDataContext,
    SourceHealth,
)
from backend.snapshot_collector.quality_gate import evaluate_quality
from backend.snapshot_collector.service import SnapshotCollectorService
from backend.snapshot_collector.slots import SECTOR_SNAPSHOT_TYPES


class FakeRepo:
    """最小仓储：捕获落库 payload，其余按未命中/成功处理。"""

    def __init__(self) -> None:
        self.runs: list[dict[str, Any]] = []
        self.saved: list[dict[str, Any]] = []

    def snapshot_exists(self, dataset_id: str, snapshot_id: str) -> bool:
        return False

    def save_snapshot_ingest(
        self,
        dataset: dict[str, Any],
        records: list[dict[str, Any]],
        frames: list[dict[str, Any]],
        stock_rows: list[dict[str, Any]],
        sector_rows: list[dict[str, Any]],
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        self.saved.append(
            {
                "snapshotId": (records[0] or {}).get("snapshotId", "") if records else "",
                "records": records,
                "frames": frames,
                "stock_rows": stock_rows,
                "sector_rows": sector_rows,
            }
        )
        return {"status": "done", "deduped": False}

    def insert_run(self, run: dict[str, Any]) -> None:
        self.runs.append(run)


class FakeThemeHeat:
    """计数型 theme heat 服务：factors 输出一个题材因子。"""

    def __init__(self) -> None:
        self.calls = 0

    def get_snapshot(self, include_runtime_funds: bool = True) -> dict[str, Any]:
        self.calls += 1
        return {
            "factorVersion": "test-v1",
            "computedAt": "2026-09-30T02:00:00+00:00",
            "quality": {"quoteCoverage": 1.0},
            "sources": {"funds": {"coverage_ratio": 1.0}},
            "factors": [
                {
                    "themeId": "theme_ai",
                    "themeName": "人工智能",
                    "rank": 1,
                    "heatLevel": 88.0,
                    "heatScore": 96.0,
                }
            ],
        }


def _make_ctx() -> MarketDataContext:
    return MarketDataContext(
        stocks=[
            {
                "code": "000001",
                "name": "平安银行",
                "rank": 1,
                "preClose": 10.0,
                "price": 10.5,
                "volume": 1000,
            }
        ],
        source_health=[SourceHealth(source="startup_bundle", ok=True, row_count=1)],
        snapshot_context={
            "hotThemes": [{"id": "theme_ai", "themeName": "人工智能"}],
            "marketData": {"indices": {"sh": 1.0}},
        },
    )


def _make_service(
    repo: FakeRepo, theme_heat: FakeThemeHeat | None
) -> SnapshotCollectorService:
    async def fake_collect(
        providers: list[Any], codes: list[str], timeout_ms: int | None = None
    ) -> MarketDataContext:
        return _make_ctx()

    return SnapshotCollectorService(
        repo,
        collect_fn=fake_collect,
        normalize_fn=normalize_snapshot_ingest,
        quality_fn=evaluate_quality,
        theme_heat_service=theme_heat,
    )


def _request(snapshot_type: str, slot_time: str) -> CollectorRunRequest:
    return CollectorRunRequest(
        dataset_id="dragonboard_backend_shadow",
        snapshot_type=snapshot_type,
        trading_date="2026-09-30",
        slot_time=slot_time,
        dry_run=False,
        force=False,
    )


def _saved_for(repo: FakeRepo, snapshot_id: str) -> dict[str, Any] | None:
    for item in repo.saved:
        if item["snapshotId"] == snapshot_id:
            return item
    return None


# ── 策略常量 ──────────────────────────────────────────────────────────────────


def test_sector_snapshot_types_policy() -> None:
    """题材行只随 half_hour/hourly/daily 帧；高频类型不携带。"""
    assert SECTOR_SNAPSHOT_TYPES == frozenset({"half_hour", "hourly", "daily"})
    assert "five_minutes" not in SECTOR_SNAPSHOT_TYPES
    assert "quarter_hour" not in SECTOR_SNAPSHOT_TYPES


# ── 同刻多类型：一次采集、按类型剥离 ────────────────────────────────────────


def test_aligned_group_half_hour_keeps_sectors_five_minutes_stripped() -> None:
    """10:00 同刻组：half_hour 帧带题材行，five_minutes 帧剥离并打标。"""
    repo = FakeRepo()
    theme_heat = FakeThemeHeat()
    service = _make_service(repo, theme_heat)

    results = asyncio.run(
        service.arun_once_multi(
            [
                _request("five_minutes", "10:00"),
                _request("half_hour", "10:00"),
            ]
        )
    )

    assert [r.status for r in results] == ["completed", "completed"]
    # 组内含 half_hour → theme heat 照常计算一次
    assert theme_heat.calls == 1

    half = _saved_for(repo, "half_hour:2026-09-30:10:00")
    five = _saved_for(repo, "five_minutes:2026-09-30:10:00")
    assert half is not None and five is not None

    # half_hour：题材行来自 theme heat sectors + snapshot_context hotThemes
    assert len(half["sector_rows"]) >= 1
    assert any(row.get("entityKey") == "theme_ai" for row in half["sector_rows"])
    assert "hotThemes" in (half["records"][0].get("payload") or {})

    # five_minutes：题材行与题材原料一并剥离，非题材 context（marketData）保留
    assert five["sector_rows"] == []
    assert "hotThemes" not in (five["records"][0].get("payload") or {})
    assert "marketData" in (five["records"][0].get("payload") or {})

    # 剥离决策 fail-visible：高频帧 qualityFlags 落标，half_hour 帧不落
    five_flags = set(five["frames"][0].get("qualityFlags") or [])
    half_flags = set(half["frames"][0].get("qualityFlags") or [])
    assert "sector_rows_skipped_sector_cadence" in five_flags
    assert "sector_rows_skipped_sector_cadence" not in half_flags
    assert any(
        "sector_rows_skipped_sector_cadence" in w
        for w in (results[0].quality.warnings or [])
    )


def test_pure_five_minutes_group_skips_theme_heat() -> None:
    """10:05 纯 five_minutes 唤醒：整组跳过 theme heat（上游开销不随频率放大）。"""
    repo = FakeRepo()
    theme_heat = FakeThemeHeat()
    service = _make_service(repo, theme_heat)

    results = asyncio.run(service.arun_once_multi([_request("five_minutes", "10:05")]))

    assert results[0].status == "completed"
    assert theme_heat.calls == 0
    saved = _saved_for(repo, "five_minutes:2026-09-30:10:05")
    assert saved is not None
    assert saved["sector_rows"] == []


def test_pure_quarter_hour_group_skips_theme_heat() -> None:
    """10:15 纯 quarter_hour 唤醒：同样跳过 theme heat 并剥离题材行。"""
    repo = FakeRepo()
    theme_heat = FakeThemeHeat()
    service = _make_service(repo, theme_heat)

    results = asyncio.run(
        service.arun_once_multi([_request("quarter_hour", "10:15")])
    )

    assert results[0].status == "completed"
    assert theme_heat.calls == 0
    saved = _saved_for(repo, "quarter_hour:2026-09-30:10:15")
    assert saved is not None
    assert saved["sector_rows"] == []
    flags = set(saved["frames"][0].get("qualityFlags") or [])
    assert "sector_rows_skipped_sector_cadence" in flags


# ── 单类型入口（CLI / API run-once / catch-up）同口径 ───────────────────────


def test_arun_once_single_five_minutes_skips_theme_heat() -> None:
    """单类型 run-once：five_minutes 跳过 theme heat，half_hour 不跳。"""
    repo = FakeRepo()
    theme_heat = FakeThemeHeat()
    service = _make_service(repo, theme_heat)

    five = asyncio.run(service.arun_once(_request("five_minutes", "10:10")))
    assert five.status == "completed"
    assert theme_heat.calls == 0

    half = asyncio.run(service.arun_once(_request("half_hour", "10:30")))
    assert half.status == "completed"
    assert theme_heat.calls == 1
    saved = _saved_for(repo, "half_hour:2026-09-30:10:30")
    assert saved is not None and len(saved["sector_rows"]) >= 1
