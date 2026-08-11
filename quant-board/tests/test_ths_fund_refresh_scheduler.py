from __future__ import annotations

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from backend.services.market.ths_fund_refresh_scheduler import ThsFundRefreshScheduler
from backend.services.market.ths_main_monitor_service import ThsMainMonitorError


TZ = ZoneInfo("Asia/Shanghai")


class FakeThsService:
    def __init__(
        self,
        titles: dict[str, tuple[str, str]] | None = None,
        fail_codes: set[str] | None = None,
        error_code: str | None = None,
        error_codes: dict[str, str] | None = None,
        hang: bool = False,
        hang_codes: set[str] | None = None,
    ) -> None:
        self.titles = titles or {}
        self.fail_codes = fail_codes or set()
        self.error_code = error_code
        self.error_codes = error_codes or {}
        self.hang = hang
        self.hang_codes = hang_codes or set()
        self.batches: list[list[str]] = []
        self.cooldowns: list[float] = []
        self.concurrency_calls: list[int] = []
        self.concurrency = 2

    async def load_raw(self, code: str):
        self.batches.append([code])
        if self.hang or code in self.hang_codes:
            await asyncio.sleep(3600)
        per_code_error = self.error_codes.get(code)
        if per_code_error:
            raise ThsMainMonitorError(per_code_error)
        if self.error_code:
            raise ThsMainMonitorError(self.error_code)
        if code in self.fail_codes:
            raise ThsMainMonitorError("ths_invalid_payload")
        title = self.titles.get(code)
        if title is None:
            return {
                "stockCode": code,
                "sessionDate": "2026-08-07",
                "fetchedAt": 1,
                "stale": True,
                "data": {},
            }
        return {
            "stockCode": code,
            "sessionDate": "2026-08-07",
            "fetchedAt": 1,
            "stale": False,
            "data": {
                "title": {"mainbuy": title[0], "mainsell": title[1]},
                "list": [
                    {"money": 5_000_000, "tradetype": "1"},
                    {"money": 5_000_000, "tradetype": "2"},
                    {"money": 299_999, "tradetype": "1"},  # 低于 30 万不入档
                ],
            },
        }

    def enter_cooldown(self, seconds: float) -> None:
        self.cooldowns.append(seconds)

    async def set_effective_concurrency(self, value: int) -> None:
        self.concurrency_calls.append(value)
        self.concurrency = value


class FakeCache:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, object]] = {}
        self.reject_codes: set[str] = set()

    def put(self, row: dict[str, object]) -> dict[str, object]:
        code = str(row["code"])
        if code in self.reject_codes:
            raise ValueError("rejected for test")
        saved = {**row, "version": len(self.rows) + 1}
        self.rows[code] = saved
        return saved


class FakeFundRepo:
    def __init__(self) -> None:
        self.docs: list[dict] = []

    def upsert_many(self, docs: list[dict]) -> int:
        self.docs.extend(docs)
        return len(docs)


class FailingFundRepo:
    """模拟 MongoDB 故障：upsert 抛异常。"""

    def upsert_many(self, docs: list[dict]) -> int:
        raise RuntimeError("mongodb down")


class HangingFundRepo:
    """模拟 MongoDB TCP 挂起：upsert 长时间不返回（后台线程会自然结束）。"""

    def upsert_many(self, docs: list[dict]) -> int:
        import time

        time.sleep(2.0)
        return 0


class FakeStream:
    def __init__(
        self,
        codes: list[str],
        priority_codes: list[str] | None = None,
        active_owner: bool = True,
    ) -> None:
        self.codes = codes
        self.priority = priority_codes or []
        self.active = active_owner
        self.codes_changed = asyncio.Event()
        self.publish_calls: list[list[dict]] = []

    def market_codes(self) -> list[str]:
        return list(self.codes)

    def priority_codes(self) -> list[str]:
        return list(self.priority)

    def has_active_owner(self) -> bool:
        return self.active

    def publish(self, rows: list[dict]) -> None:
        self.publish_calls.append(list(rows))


def _titles(*codes: str) -> dict[str, tuple[str, str]]:
    # mainbuy − mainsell = 2.68亿 − 2.99亿 = −3100万
    return {code: ("2.68亿", "2.99亿") for code in codes}


def _mutable_clock(value: datetime):
    box = {"current": value}
    return box, (lambda: box["current"])


def _scheduler(
    *,
    service: FakeThsService,
    cache: FakeCache | None = None,
    stream: FakeStream | None = None,
    fund_repo: FakeFundRepo | None = None,
    now=None,
    current: datetime | None = None,
    **kwargs,
) -> ThsFundRefreshScheduler:
    return ThsFundRefreshScheduler(
        service=service,
        cache=cache or FakeCache(),
        stream=stream or FakeStream([]),
        fund_repo=fund_repo,
        now=now or (lambda: current),
        **kwargs,
    )


@pytest.mark.asyncio
async def test_no_owner_makes_zero_requests() -> None:
    current = datetime(2026, 8, 7, 10, 0, 0, tzinfo=TZ)
    service = FakeThsService()
    scheduler = _scheduler(service=service, current=current, stream=FakeStream([]))

    assert await scheduler.run_once() is False
    assert service.batches == []


@pytest.mark.asyncio
async def test_first_round_fills_all_codes_in_small_batches() -> None:
    current = datetime(2026, 8, 7, 10, 0, 0, tzinfo=TZ)
    codes = [f"{i:06d}" for i in range(1, 13)]  # 12 只
    service = FakeThsService(titles=_titles(*codes))
    cache = FakeCache()
    scheduler = _scheduler(
        service=service,
        cache=cache,
        stream=FakeStream(codes),
        current=current,
        batch_size=5,
    )

    for _ in range(10):
        await scheduler.run_once()

    assert set(cache.rows) == set(codes)
    assert all(len(b) <= 5 for b in service.batches)
    assert all(r["moneyFlowSource"] == "ths_main_monitor" for r in cache.rows.values())
    assert all(pytest.approx(r["zlje"]) == -31_000_000.0 for r in cache.rows.values())


@pytest.mark.asyncio
async def test_refreshed_codes_respect_interval() -> None:
    box, now = _mutable_clock(datetime(2026, 8, 7, 10, 0, 0, tzinfo=TZ))
    service = FakeThsService(titles=_titles("000001"))
    cache = FakeCache()
    scheduler = _scheduler(
        service=service,
        cache=cache,
        stream=FakeStream(["000001"]),
        now=now,
        refresh_interval_seconds=180,
    )

    assert await scheduler.run_once() is True
    assert await scheduler.run_once() is False  # interval 内不重复
    box["current"] = datetime(2026, 8, 7, 10, 3, 5, tzinfo=TZ)
    assert await scheduler.run_once() is True


@pytest.mark.asyncio
async def test_systemic_rate_limit_enters_cooldown_and_lowers_concurrency() -> None:
    current = datetime(2026, 8, 7, 10, 0, 0, tzinfo=TZ)
    service = FakeThsService(error_code="ths_rate_limited")
    scheduler = _scheduler(
        service=service,
        current=current,
        stream=FakeStream(["000001", "000002"]),
        systemic_cooldown_seconds=30.0,
    )

    assert await scheduler.run_once() is True
    assert service.cooldowns  # enter_cooldown 被调用
    assert service.concurrency_calls == [1]  # 并发降为 1
    assert scheduler.status()["circuitOpenUntil"] >= current.timestamp() + 30


@pytest.mark.asyncio
async def test_concurrent_rate_limit_not_masked_by_timeout() -> None:
    # 并发 2 中 000001 限流（systemic）、000002 超时（timeout）：
    # 修复前共享 _last_error 被 timeout 覆盖 → 系统性冷却失效；
    # 修复后冷却必须触发，且 last_error 取 systemic 错误码。
    current = datetime(2026, 8, 7, 10, 0, 0, tzinfo=TZ)
    service = FakeThsService(
        titles=_titles("000001", "000002"),
        error_codes={"000001": "ths_rate_limited"},
        hang_codes={"000002"},
    )
    scheduler = _scheduler(
        service=service,
        current=current,
        stream=FakeStream(["000001", "000002"]),
        systemic_cooldown_seconds=30.0,
        batch_timeout_seconds=1.0,
    )

    assert await scheduler.run_once() is True
    assert service.cooldowns  # 冷却被触发（限流未被 timeout 掩盖）
    assert scheduler.status()["circuitOpenUntil"] >= current.timestamp() + 30
    assert scheduler.status()["lastError"] == "ths_rate_limited"
    assert scheduler.status()["effectiveConcurrency"] == 1


@pytest.mark.asyncio
async def test_consecutive_success_restores_concurrency() -> None:
    box, now = _mutable_clock(datetime(2026, 8, 7, 10, 0, 0, tzinfo=TZ))
    service = FakeThsService(titles=_titles("000001"))
    scheduler = _scheduler(
        service=service,
        stream=FakeStream(["000001"]),
        now=now,
        refresh_interval_seconds=180,
        base_concurrency=2,
    )
    scheduler._effective_concurrency = 1

    for index in range(3):
        # 每轮推进超过刷新间隔，让同一股票再次到期
        box["current"] = box["current"].replace(minute=box["current"].minute + 4)
        assert await scheduler.run_once() is True

    assert scheduler.status()["effectiveConcurrency"] == 2
    assert service.concurrency_calls[-1] == 2


@pytest.mark.asyncio
async def test_single_stock_failure_does_not_block_others() -> None:
    current = datetime(2026, 8, 7, 10, 0, 0, tzinfo=TZ)
    service = FakeThsService(titles=_titles("000001"), fail_codes={"000002"})
    cache = FakeCache()
    scheduler = _scheduler(
        service=service,
        cache=cache,
        stream=FakeStream(["000001", "000002"]),
        current=current,
    )

    assert await scheduler.run_once() is True
    assert "000001" in cache.rows
    assert "000002" not in cache.rows
    assert scheduler.status()["lastRowCount"] == 1


@pytest.mark.asyncio
async def test_retry_backoff_increases() -> None:
    current = datetime(2026, 8, 7, 10, 0, 0, tzinfo=TZ)
    service = FakeThsService(fail_codes={"000001"})
    scheduler = _scheduler(
        service=service,
        current=current,
        stream=FakeStream(["000001"]),
        retry_backoff_seconds=(30, 60, 120, 300),
    )

    assert await scheduler.run_once() is True
    assert scheduler._retry_at["000001"] == current.timestamp() + 30
    assert await scheduler.run_once() is False  # 退避中不请求

    box, now = _mutable_clock(datetime(2026, 8, 7, 10, 0, 35, tzinfo=TZ))
    scheduler._now = now
    assert await scheduler.run_once() is True
    assert scheduler._retry_at["000001"] == box["current"].timestamp() + 60


@pytest.mark.asyncio
async def test_single_timeout_backs_off_without_blocking_others() -> None:
    current = datetime(2026, 8, 7, 10, 0, 0, tzinfo=TZ)
    service = FakeThsService(titles=_titles("000002"), hang_codes={"000001"})
    cache = FakeCache()
    scheduler = _scheduler(
        service=service,
        cache=cache,
        stream=FakeStream(["000001", "000002"]),
        current=current,
        batch_timeout_seconds=0.1,
        systemic_cooldown_seconds=30.0,
    )

    assert await scheduler.run_once() is True
    assert "000002" in cache.rows  # 挂起的那只不阻塞同批其它
    assert "000001" not in cache.rows
    assert scheduler._retry_at["000001"] == current.timestamp() + 30
    assert scheduler.status()["circuitOpenUntil"] == 0.0  # 单只超时不触发全局冷却


@pytest.mark.asyncio
async def test_mongo_persist_writes_seven_buckets() -> None:
    current = datetime(2026, 8, 7, 10, 0, 0, tzinfo=TZ)
    service = FakeThsService(titles=_titles("000001"))
    fund_repo = FakeFundRepo()
    scheduler = _scheduler(
        service=service,
        stream=FakeStream(["000001"]),
        fund_repo=fund_repo,
        current=current,
    )

    assert await scheduler.run_once() is True
    assert len(fund_repo.docs) == 1
    doc = fund_repo.docs[0]
    assert doc["code"] == "000001"
    assert doc["sessionDate"] == "2026-08-07"
    assert doc["source"] == "ths_main_monitor"
    assert doc["total"]["zlje"] == pytest.approx(-31_000_000.0)
    assert doc["total"]["buyAmount"] == pytest.approx(268_000_000.0)
    assert doc["total"]["sellAmount"] == pytest.approx(299_000_000.0)
    assert [b["tier"] for b in doc["buckets"]] == [
        "ge_1000w",
        "700_1000w",
        "500_700w",
        "300_500w",
        "100_300w",
        "50_100w",
        "30_50w",
    ]
    # list 两笔 500 万（买/卖各一）→ 500_700w 档；299999 低于 30 万不入档
    b500 = next(b for b in doc["buckets"] if b["tier"] == "500_700w")
    assert b500["buyCount"] == 1
    assert b500["sellCount"] == 1
    assert b500["net"] == 0.0


@pytest.mark.asyncio
async def test_mongo_persist_disabled_without_repo() -> None:
    current = datetime(2026, 8, 7, 10, 0, 0, tzinfo=TZ)
    service = FakeThsService(titles=_titles("000001"))
    cache = FakeCache()
    scheduler = _scheduler(
        service=service,
        cache=cache,
        stream=FakeStream(["000001"]),
        current=current,
    )

    assert await scheduler.run_once() is True
    assert "000001" in cache.rows
    assert scheduler.status()["mongoPersistEnabled"] is False


@pytest.mark.asyncio
async def test_priority_codes_refresh_faster_than_regular() -> None:
    box, now = _mutable_clock(datetime(2026, 8, 7, 10, 0, 0, tzinfo=TZ))
    service = FakeThsService(titles=_titles("000001", "000002"))
    cache = FakeCache()
    scheduler = _scheduler(
        service=service,
        cache=cache,
        stream=FakeStream(["000001", "000002"], priority_codes=["000001"]),
        now=now,
        refresh_interval_seconds=180,
        priority_interval_seconds=30,
    )

    assert await scheduler.run_once() is True  # 首轮全刷
    first_batches = list(service.batches)
    # 35 秒后：P0（000001）到期再刷，P1（000002）未到期
    box["current"] = datetime(2026, 8, 7, 10, 0, 35, tzinfo=TZ)
    assert await scheduler.run_once() is True
    assert service.batches[-1] == ["000001"]
    assert scheduler._next_refresh_at["000002"] > box["current"].timestamp()
    # 180 秒后：P1 也到期
    box["current"] = datetime(2026, 8, 7, 10, 3, 5, tzinfo=TZ)
    assert await scheduler.run_once() is True
    assert first_batches  # 首轮确实刷过


@pytest.mark.asyncio
async def test_priority_codes_are_sorted_first_when_due() -> None:
    box, now = _mutable_clock(datetime(2026, 8, 7, 10, 0, 0, tzinfo=TZ))
    service = FakeThsService(titles=_titles("000001", "000002", "000003", "000004", "000005", "000006"))
    scheduler = _scheduler(
        service=service,
        stream=FakeStream(
            ["000001", "000002", "000003", "000004", "000005", "000006"],
            priority_codes=["000004", "000001"],
        ),
        now=now,
        batch_size=5,
        refresh_interval_seconds=180,
        priority_interval_seconds=30,
    )

    assert await scheduler.run_once() is True  # 首轮 5 只（P0 优先：000001、000004 在前）
    first_round = [b[0] for b in service.batches[:5]]
    assert first_round[:2] == ["000001", "000004"]
    box["current"] = box["current"].replace(minute=0, second=40)
    assert await scheduler.run_once() is True  # 补齐未刷的 000006 + P0（000001/000004）到期重刷
    second_round = [b[0] for b in service.batches[5:]]
    assert "000006" in second_round
    assert "000005" not in second_round  # P1（180s）未到期


@pytest.mark.asyncio
async def test_status_reports_priority_count() -> None:
    current = datetime(2026, 8, 7, 10, 0, 0, tzinfo=TZ)
    scheduler = _scheduler(
        service=FakeThsService(titles=_titles("000001", "000002")),
        stream=FakeStream(["000001", "000002"], priority_codes=["000001"]),
        current=current,
        priority_interval_seconds=30,
    )
    status = scheduler.status()
    assert status["priorityCount"] == 1
    assert status["priorityIntervalSeconds"] == 30


@pytest.mark.asyncio
async def test_outside_trading_hours_skips_requests_after_initialized() -> None:
    box, now = _mutable_clock(datetime(2026, 8, 7, 10, 0, 0, tzinfo=TZ))
    service = FakeThsService(titles=_titles("000001"))
    scheduler = _scheduler(service=service, stream=FakeStream(["000001"]), now=now)
    assert await scheduler.run_once() is True  # 周五盘中初始化一轮
    assert service.batches == [["000001"]]

    # 周六非交易时段：已初始化 → 暂停，不产生新请求
    box["current"] = datetime(2026, 8, 8, 10, 0, 0, tzinfo=TZ)
    assert await scheduler.run_once() is False
    assert len(service.batches) == 1
    assert scheduler.status()["lastError"] == "outside_trading_hours"


@pytest.mark.asyncio
async def test_outside_trading_hours_cold_start_initializes() -> None:
    # 周六冷启动（未刷过）：允许请求一轮拿最近交易日 L2，首屏资金列不空
    current = datetime(2026, 8, 8, 10, 0, 0, tzinfo=TZ)
    service = FakeThsService(titles=_titles("000001"))
    cache = FakeCache()
    scheduler = _scheduler(
        service=service,
        cache=cache,
        stream=FakeStream(["000001"]),
        current=current,
    )

    assert await scheduler.run_once() is True
    assert service.batches == [["000001"]]
    assert "000001" in cache.rows
    assert scheduler.status()["lastSessionDate"] == "2026-08-07"


@pytest.mark.asyncio
async def test_cold_start_outside_hours_writes_redis_but_skips_mongo() -> None:
    # 非交易时段冷启动刷一轮：Redis/内存 last-good 有值（首屏不空），
    # MongoDB 不写（避免垃圾文档；MongoDB 只固化交易时段数据）
    current = datetime(2026, 8, 8, 10, 0, 0, tzinfo=TZ)  # 周六
    service = FakeThsService(titles=_titles("000001"))
    cache = FakeCache()
    fund_repo = FakeFundRepo()
    scheduler = _scheduler(
        service=service,
        cache=cache,
        stream=FakeStream(["000001"]),
        fund_repo=fund_repo,
        current=current,
    )

    assert await scheduler.run_once() is True
    assert "000001" in cache.rows  # Redis/内存热缓存有值
    assert cache.rows["000001"]["zlje"] == pytest.approx(-31_000_000.0)
    assert fund_repo.docs == []  # MongoDB 不写


@pytest.mark.asyncio
async def test_outside_trading_hours_cold_start_drains_full_pool() -> None:
    # 周六冷启动多只池：冷启动例外应持续刷到全池完成（不只一轮），
    # 否则 233 只展示池只有 5 只有资金——2026-08-08 用户反馈首屏只有数笔的根因
    current = datetime(2026, 8, 8, 10, 0, 0, tzinfo=TZ)  # 周六
    codes = [f"{i:06d}" for i in range(1, 13)]  # 12 只 = 3 批 × 5
    service = FakeThsService(titles=_titles(*codes))
    cache = FakeCache()
    scheduler = _scheduler(
        service=service,
        cache=cache,
        stream=FakeStream(codes),
        current=current,
        batch_size=5,
    )

    rounds = 0
    while await scheduler.run_once() and rounds < 10:
        rounds += 1

    assert set(cache.rows) == set(codes)  # 全池都有最近交易日 L2
    assert scheduler.status()["lastSessionDate"] == "2026-08-07"
    assert scheduler._needs_cold_init() is False  # 刷完即暂停
    assert all(len(b) <= 5 for b in service.batches)


@pytest.mark.asyncio
async def test_trading_hours_persist_writes_mongo() -> None:
    # 交易时段冷启动（周五 10:00）→ Redis + MongoDB 都写
    current = datetime(2026, 8, 7, 10, 0, 0, tzinfo=TZ)
    service = FakeThsService(titles=_titles("000001"))
    cache = FakeCache()
    fund_repo = FakeFundRepo()
    scheduler = _scheduler(
        service=service,
        cache=cache,
        stream=FakeStream(["000001"]),
        fund_repo=fund_repo,
        current=current,
    )

    assert await scheduler.run_once() is True
    assert "000001" in cache.rows
    assert len(fund_repo.docs) == 1
    assert fund_repo.docs[0]["sessionDate"] == "2026-08-07"
    assert fund_repo.docs[0]["total"]["zlje"] == pytest.approx(-31_000_000.0)


@pytest.mark.asyncio
async def test_mongo_failure_does_not_block_redis_or_scheduler() -> None:
    # 交易时段 MongoDB 故障（upsert 抛异常）：只记日志，Redis/内存 last-good
    # 照常写入，调度器不崩——前端资金列仍显示有值（读取不经过 MongoDB）
    current = datetime(2026, 8, 7, 10, 0, 0, tzinfo=TZ)
    service = FakeThsService(titles=_titles("000001"))
    cache = FakeCache()
    scheduler = _scheduler(
        service=service,
        cache=cache,
        stream=FakeStream(["000001"]),
        fund_repo=FailingFundRepo(),
        current=current,
    )

    assert await scheduler.run_once() is True  # 不抛异常
    assert "000001" in cache.rows  # Redis/内存行照常
    assert cache.rows["000001"]["zlje"] == pytest.approx(-31_000_000.0)
    assert scheduler.status()["lastError"] is None


@pytest.mark.asyncio
async def test_mongo_hang_does_not_slow_refresh() -> None:
    # MongoDB TCP 挂起（upsert 长时间不返回）：超时后刷新继续，不拖慢 P0/P1 节奏
    import time as _time

    current = datetime(2026, 8, 7, 10, 0, 0, tzinfo=TZ)
    service = FakeThsService(titles=_titles("000001"))
    cache = FakeCache()
    scheduler = _scheduler(
        service=service,
        cache=cache,
        stream=FakeStream(["000001"]),
        fund_repo=HangingFundRepo(),
        current=current,
        mongo_write_timeout_seconds=0.1,
    )

    start = _time.monotonic()
    assert await scheduler.run_once() is True
    elapsed = _time.monotonic() - start
    assert elapsed < 1.0  # 0.5s 超时后立即继续，未被 2.0s 挂起拖住
    assert "000001" in cache.rows


@pytest.mark.asyncio
async def test_lunch_break_skips_requests_after_initialized() -> None:
    box, now = _mutable_clock(datetime(2026, 8, 7, 10, 0, 0, tzinfo=TZ))
    service = FakeThsService(titles=_titles("000001"))
    scheduler = _scheduler(service=service, stream=FakeStream(["000001"]), now=now)
    assert await scheduler.run_once() is True  # 盘中初始化

    # 周五 12:00 午休：已初始化 → 暂停
    box["current"] = datetime(2026, 8, 7, 12, 0, 0, tzinfo=TZ)
    assert await scheduler.run_once() is False
    assert len(service.batches) == 1


def test_is_trading_time_boundaries() -> None:
    cases = [
        (9, 29, False),
        (9, 30, True),
        (11, 30, True),
        (11, 31, False),
        (13, 0, True),
        (15, 0, True),
        (15, 1, False),
    ]
    for hour, minute, expected in cases:
        now = datetime(2026, 8, 7, hour, minute, 0, tzinfo=TZ)  # 周五
        assert ThsFundRefreshScheduler._is_trading_time(now) is expected, f"{hour}:{minute:02d}"
    # 周六/周日全天非交易
    saturday = datetime(2026, 8, 8, 10, 0, 0, tzinfo=TZ)
    sunday = datetime(2026, 8, 9, 10, 0, 0, tzinfo=TZ)
    assert ThsFundRefreshScheduler._is_trading_time(saturday) is False
    assert ThsFundRefreshScheduler._is_trading_time(sunday) is False


@pytest.mark.asyncio
async def test_status_owner_state_active_and_persisted() -> None:
    current = datetime(2026, 8, 7, 10, 0, 0, tzinfo=TZ)

    active = _scheduler(
        service=FakeThsService(titles=_titles("000001")),
        stream=FakeStream(["000001"], active_owner=True),
        current=current,
    )
    assert active.status()["ownerState"] == "active"

    persisted = _scheduler(
        service=FakeThsService(titles=_titles("000001")),
        stream=FakeStream(["000001"], active_owner=False),
        current=current,
    )
    assert persisted.status()["ownerState"] == "persisted"


def test_compute_wait_seconds_outside_trading_hours() -> None:
    # 周六 10:00 → 距周一 09:30 约 47.5h，上限 3600 秒
    now = datetime(2026, 8, 8, 10, 0, 0, tzinfo=TZ)
    scheduler = _scheduler(service=FakeThsService(), stream=FakeStream(["000001"]), current=now)
    assert scheduler._compute_wait_seconds() == 3600.0


def test_compute_wait_seconds_lunch_break() -> None:
    # 周五 12:00 午休 → 距 13:00 开盘 3600 秒（cap 3600）
    now = datetime(2026, 8, 7, 12, 0, 0, tzinfo=TZ)
    scheduler = _scheduler(service=FakeThsService(), stream=FakeStream(["000001"]), current=now)
    assert scheduler._compute_wait_seconds() == 3600.0


def test_compute_wait_seconds_trading_hours_uses_due_horizon() -> None:
    # 盘中：无到期码时按刷新间隔（180s）等待
    now = datetime(2026, 8, 7, 10, 0, 0, tzinfo=TZ)
    scheduler = _scheduler(
        service=FakeThsService(titles=_titles("000001")),
        stream=FakeStream(["000001"]),
        current=now,
        refresh_interval_seconds=180,
    )
    assert scheduler._compute_wait_seconds() == 180.0


@pytest.mark.asyncio
async def test_run_once_publishes_written_rows_to_stream() -> None:
    # H1 回归（2026-08-11 实盘复盘）：调度器每批写入 Redis 后必须 publish 到
    # fund-stream，前端才能收到 P0/P1 校准增量（否则只靠 300s idle 断线重连拿快照）
    current = datetime(2026, 8, 7, 10, 0, 0, tzinfo=TZ)
    service = FakeThsService(titles=_titles("000001", "000002", "000003"))
    cache = FakeCache()
    stream = FakeStream(codes=["000001", "000002", "000003"])
    scheduler = _scheduler(service=service, cache=cache, stream=stream, current=current)

    assert await scheduler.run_once() is True
    assert stream.publish_calls, "刷新成功后必须 publish 到 fund-stream"
    published = stream.publish_calls[-1]
    assert len(published) == 3
    for row in published:
        assert row["code"] in {"000001", "000002", "000003"}
        assert "version" in row  # 推送行带单调 version，前端据此去重
        assert row["moneyFlowSource"] == "ths_main_monitor"


@pytest.mark.asyncio
async def test_stale_raw_skips_cache_and_mongo() -> None:
    current = datetime(2026, 8, 7, 10, 0, 0, tzinfo=TZ)
    service = FakeThsService(titles=_titles("000001"))
    cache = FakeCache()
    fund_repo = FakeFundRepo()
    scheduler = _scheduler(
        service=service,
        cache=cache,
        stream=FakeStream(["000001", "000002"]),
        fund_repo=fund_repo,
        current=current,
    )

    assert await scheduler.run_once() is True
    assert "000001" in cache.rows
    assert "000002" not in cache.rows
    assert [d["code"] for d in fund_repo.docs] == ["000001"]
    assert scheduler._retry_at["000002"] == current.timestamp() + 30
