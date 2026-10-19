"""backfill / 冗余实例守卫（2026-10-19 复盘）。

契约：
- ``SnapshotCollectorService.backfill_slots`` 绝不采集尚未到期的槽位
  （按整天生成槽位的 backfill-slots 在盘中执行会把当前行情盖到未来槽位）；
- ``collector_main`` 等锁失败时，若 8001 已被另一实例正常服务，本实例按“冗余”
  退出并清掉等待标记，不再留下 restartable=false 的假消息。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from backend import collector_main
from backend.snapshot_collector.service import SnapshotCollectorService

TZ_SHANGHAI = ZoneInfo("Asia/Shanghai")


class _BackfillRequest:
    __slots__ = ("dataset_id", "snapshot_type", "slots", "dry_run", "force")

    def __init__(
        self,
        dataset_id: str,
        snapshot_type: str,
        slots: list[dict[str, str]],
        dry_run: bool = True,
        force: bool = False,
    ) -> None:
        self.dataset_id = dataset_id
        self.snapshot_type = snapshot_type
        self.slots = slots
        self.dry_run = dry_run
        self.force = force


class FakeRepo:
    """backfill 守卫测试的最小仓库：仅需 snapshot_exists + insert_run。"""

    def __init__(self) -> None:
        self.runs: list[dict[str, Any]] = []

    def snapshot_exists(self, dataset_id: str, snapshot_id: str) -> bool:
        return False

    def save_snapshot_ingest(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"status": "done", "deduped": False}

    def insert_run(self, run: dict[str, Any]) -> None:
        self.runs.append(run)


def _service(monkeypatch: pytest.MonkeyPatch) -> tuple[SnapshotCollectorService, dict[str, int]]:
    from backend.snapshot_collector.models import MarketDataContext, SourceHealth

    calls = {"n": 0}

    async def fake_collect(
        providers: list[Any], codes: list[str], timeout_ms: int | None = None
    ) -> MarketDataContext:
        calls["n"] += 1
        return MarketDataContext(
            stocks=[{"code": "000001", "name": "平安银行", "rank": 1, "price": 10.5}],
            source_health=[SourceHealth(source="fake", ok=True, row_count=1)],
        )

    service = SnapshotCollectorService(FakeRepo(), collect_fn=fake_collect)
    return service, calls


def _today() -> str:
    return datetime.now(TZ_SHANGHAI).strftime("%Y-%m-%d")


def test_backfill_skips_not_due_slots(monkeypatch: pytest.MonkeyPatch) -> None:
    """未来槽位必须 blocked 且不触发采集（不得伪造未来帧）。"""
    service, calls = _service(monkeypatch)
    trading_date = _today()
    # 取一个确定晚于“现在 + grace”的槽位：依次尝试直到找到未到期的 5 分钟槽
    from backend.snapshot_collector.slots import generate_slots

    now_ms = int(datetime.now(TZ_SHANGHAI).timestamp() * 1000)
    grace_ms = service._close_grace_minutes() * 60 * 1000
    future = [
        s for s in generate_slots(trading_date, ["five_minutes"])
        if s.timestamp_ms > now_ms + grace_ms
    ]
    if not future:
        pytest.skip("当前时点已无未到期槽位（收盘后）")
    slot = future[0]

    result = service.backfill_slots(
        _BackfillRequest(
            dataset_id="test",
            snapshot_type="five_minutes",
            slots=[{"trading_date": trading_date, "slot_time": slot.slot_time}],
        )
    )

    assert result["total"] == 1
    assert result["blocked"] == 1
    assert result["succeeded"] == 0
    assert calls["n"] == 0
    assert result["details"][0]["snapshotId"] == f"five_minutes:{trading_date}:{slot.slot_time}"
    assert "slot_not_due" in result["details"][0]["message"]


def test_backfill_still_collects_past_slots(monkeypatch: pytest.MonkeyPatch) -> None:
    """已过 grace 的槽位不受守卫影响（正常补采路径）。"""
    service, calls = _service(monkeypatch)
    trading_date = "2026-06-11"  # 历史交易日：全部槽位早已到期

    result = service.backfill_slots(
        _BackfillRequest(
            dataset_id="test",
            snapshot_type="half_hour",
            slots=[{"trading_date": trading_date, "slot_time": "10:00"}],
        )
    )

    assert result["total"] == 1
    assert result["blocked"] == 0
    assert calls["n"] == 1
    assert result["details"][0]["status"] == "dry_run"


def test_serving_elsewhere_true_on_collector_health(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import io
    import json
    import urllib.request

    class _Response(io.BytesIO):
        status = 200

        def __enter__(self) -> "_Response":
            return self

        def __exit__(self, *exc: Any) -> bool:
            return False

    def fake_urlopen(url: str, timeout: float = 0) -> _Response:
        assert url.endswith("/api/health")
        return _Response(json.dumps({"status": "ok", "snapshotCollector": {"running": True}}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert collector_main._collector_serving_elsewhere() is True


def test_serving_elsewhere_false_when_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import urllib.request

    def fake_urlopen(url: str, timeout: float = 0) -> Any:
        raise OSError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert collector_main._collector_serving_elsewhere() is False


def test_serving_elsewhere_false_for_non_collector_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """8001 被别的服务占用（无 snapshotCollector 字段）不算“采集已在服务”。"""
    import io
    import json
    import urllib.request

    class _Response(io.BytesIO):
        status = 200

        def __enter__(self) -> "_Response":
            return self

        def __exit__(self, *exc: Any) -> bool:
            return False

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda url, timeout=0: _Response(json.dumps({"hello": "world"}).encode()),
    )
    assert collector_main._collector_serving_elsewhere() is False

# ── Redis 不可达时的防双采复查（2026-10-19 复盘）──────────────────────────


def test_degraded_lock_with_peer_serving_8001_must_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """锁后端降级（无 Redis 协调）+ 8001 已有实例在采 → 必须退出，绝不双采。"""
    class _Lock:
        degraded_reason = "lock backend unavailable: Error 10061"

    monkeypatch.setattr(collector_main, "_collector_serving_elsewhere", lambda port=8001: True)
    assert collector_main._degraded_lock_peer_running(_Lock()) is True


def test_degraded_lock_without_peer_may_continue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """锁后端降级但没有任何实例在服务 8001 → 允许单实例继续（可用性优先）。"""
    class _Lock:
        degraded_reason = "lock backend unavailable: Error 10061"

    monkeypatch.setattr(collector_main, "_collector_serving_elsewhere", lambda port=8001: False)
    assert collector_main._degraded_lock_peer_running(_Lock()) is False


def test_healthy_lock_never_triggers_peer_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """锁正常（Redis 可达）时不做对端复查——防双采由锁本身保证。"""
    class _Lock:
        degraded_reason = None

    def _boom(*args, **kwargs):
        raise AssertionError("锁正常时不应调用 8001 对端探测")

    monkeypatch.setattr(collector_main, "_collector_serving_elsewhere", _boom)
    assert collector_main._degraded_lock_peer_running(_Lock()) is False


def test_health_contract_reports_degraded_lock() -> None:
    """单实例协调降级必须在 health 契约里可见（degraded/alert，且不可重启）。"""
    contract = collector_main._collector_health_contract(
        {
            "enabled": True,
            "running": True,
            "lockBackend": "degraded",
            "lockError": "lock backend unavailable: Error 10061",
        }
    )
    assert contract["status"] == "degraded"
    assert contract["restartable"] is False
    assert contract["recommendedAction"] == "alert"
    assert "单实例协调降级" in contract["reason"]


def test_health_contract_ok_with_redis_lock() -> None:
    contract = collector_main._collector_health_contract(
        {"enabled": True, "running": True, "lockBackend": "redis"}
    )
    assert contract["status"] == "ok"


# ── 帧级可见性：指数用 last-good 必须打 indices_stale 标记（2026-10-19）────


def test_frame_flags_stale_indices(monkeypatch: pytest.MonkeyPatch) -> None:
    """server_market_evidence 的健康里带 stale 细节 → 帧 qualityFlags 必须可见。"""
    from backend.snapshot_collector.models import MarketDataContext, SourceHealth
    from backend.snapshot_collector.service import _source_health_dicts

    ctx = MarketDataContext(
        stocks=[{"code": "000001", "name": "平安银行", "rank": 1, "price": 10.5}],
        source_health=[
            SourceHealth(
                source="server_market_evidence",
                ok=True,
                row_count=1,
                details={"stale": True, "staleSeconds": 137.5, "errorCode": "upstream_error"},
            )
        ],
    )
    dicts = _source_health_dicts(ctx)
    assert dicts[0]["details"]["stale"] is True
    assert dicts[0]["details"]["staleSeconds"] == 137.5


def test_frame_flags_missing_indices_with_reason() -> None:
    """指数取不到时帧级必须可见且带结构化原因（fail-visible，2026-10-19）。"""
    from backend.snapshot_collector.models import MarketDataContext, SourceHealth
    from backend.snapshot_collector.service import _server_market_evidence_flags

    def _flags(error: str, indices: dict) -> list[str]:
        ctx = MarketDataContext(
            stocks=[{"code": "000001", "name": "平安银行", "rank": 1, "price": 10.5}],
            indices=indices,
            source_health=[
                SourceHealth(
                    source="server_market_evidence", ok=False, row_count=0, error=error
                )
            ],
        )
        return _server_market_evidence_flags(ctx)

    assert _flags("indices_timeout: upstream timeout after 30.0s", {}) == [
        "indices_missing:upstream_timeout"
    ]
    assert _flags("indices_failed: list index out of range", {}) == [
        "indices_missing:upstream_error"
    ]
    assert _flags("indices_timeout: x", {"sh": {"change": 1.0}}) == []


def test_frame_flags_stale_indices_via_helper() -> None:
    from backend.snapshot_collector.models import MarketDataContext, SourceHealth
    from backend.snapshot_collector.service import _server_market_evidence_flags

    ctx = MarketDataContext(
        indices={"sh": {"change": 1.0}},
        source_health=[
            SourceHealth(
                source="server_market_evidence",
                ok=False,
                error="",
                details={"stale": True, "staleSeconds": 137.5},
            )
        ],
    )
    assert _server_market_evidence_flags(ctx) == ["indices_stale:137.5s"]


class TestLiveLockState:
    """code review 修正：/api/health 的 lockBackend 必须反映“当下”，不是启动快照。

    否则一次瞬时 Redis 抖动会把 health 永久钉在 degraded → 契约给
    restartable=false/alert，launcher 后续对该服务的修复性重启被一直压制。
    """

    def teardown_method(self) -> None:
        collector_main._ACTIVE_LOCK = None
        collector_main._LOCK_STATE.update({"mode": "unknown", "error": ""})

    def test_falls_back_to_startup_snapshot_without_live_lock(self) -> None:
        collector_main._ACTIVE_LOCK = None
        collector_main._LOCK_STATE.update({"mode": "degraded", "error": "boot blip"})

        assert collector_main._live_lock_state() == ("degraded", "boot blip")

    def test_prefers_live_lock_state_and_recovers_after_clear(self) -> None:
        class _Lock:
            def __init__(self) -> None:
                self.degraded_reason: str | None = "lock backend unavailable: blip"

        lock = _Lock()
        collector_main._ACTIVE_LOCK = lock
        # 启动快照还写着 degraded，但活锁对象说“协调正常”→ 必须报 redis
        collector_main._LOCK_STATE.update({"mode": "degraded", "error": "boot blip"})

        assert collector_main._live_lock_state() == ("degraded", "lock backend unavailable: blip")

        lock.degraded_reason = None
        assert collector_main._live_lock_state() == ("redis", "")
