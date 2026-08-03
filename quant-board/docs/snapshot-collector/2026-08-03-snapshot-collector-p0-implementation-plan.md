# Snapshot Collector P0 实施计划：独立采集进程 + 硬门禁移除 + 行情字段补齐

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **实施状态（2026-08-03）**：用户确认在主工作区 `D:\dragon-board` 直接实施，不做隔离 worktree；8001 由
> **DragonBoardLauncher 核心启动项**管理（不建 Windows 计划任务、不恢复 supervisor.py 常驻守护；
> supervisor.py 历史版本已定位：`b037f59` 创建、`7322fce` 删除，其"启动 backend.main 第二实例"的设计被
> 本计划 Task 2 的精简 `collector_main` + 进程内网关方案取代）。Task 0/1/2 已实施，Task 3-5 未开始。

**Goal:** 让 snapshot_collector 在 8000 进程不可用时仍能按时采集（独立进程 + 进程内直连 + 交易日历降级），移除 normalizer 残留硬门禁，并补齐回测所需行情字段（pe/pb/cirMV/totalMV/volumeRatio/limitUpPrice/limitDownPrice/lastTradePrice/lastTradeVolume）。

**Architecture:** 新增 `backend/collector_main.py` 独立 FastAPI 采集进程（默认 8001），只挂 snapshot-collector 路由与健康检查，自行启动行情/热榜/资金后台刷新；collector provider 通过 `MarketDataGateway` 抽象改为进程内直连 `market_proxy` 服务单例（HTTP 走 proxy 仅作为 CLI/手动回退）；采集进程启动时用 Redis `SET NX` 单实例锁防重复实例；交易日历在 bridge 不可用时回退本地缓存/工作日启发式。normalizer 的 `formal snapshot hotlist is empty` 抛错改为打 qualityFlags 保留数据。腾讯 provider 补齐 f9/f20/f21/f23/ztPrice/dtPrice 映射并接入 `compute_volume_ratios` golden。

**Tech Stack:** Python 3.13、FastAPI、asyncio、pymongo、redis、httpx、pytest、uvicorn

---

## Task 0: 隔离 worktree

> 已按用户决定改为"主工作区实施"：跳过 worktree，直接在 `D:\dragon-board`（main 分支）实施。

**Files:**
- 无源码改动

- [ ] **Step 1: 创建隔离 worktree**

  执行时使用 `superpowers:using-git-worktrees` 创建 `quantboard-collector-p0` worktree；确认 `git rev-parse --show-toplevel` 指向该 worktree，`git status --short` 干净。

- [ ] **Step 2: 记录基线**

  Run: `cd <worktree>\quant-board && .\.venv\Scripts\python.exe -m pytest tests/test_snapshot_collector_*.py -q`
  Expected: 全部 PASS（记录通过数量）；失败项先修隔离问题再继续。

- [ ] **Step 3: Commit（空基线）**

  ```bash
  git -C <worktree> status --short
  ```
  确认无改动后再开始 Task 1。

---

## Task 1: MarketDataGateway（provider 进程内直连，去掉 8000 自环）

> 实施状态：已完成（作为 Task 2 前置一并落地）。

**Files:**
- Create: `quant-board/backend/snapshot_collector/gateway.py`
- Modify: `quant-board/backend/snapshot_collector/providers.py`
- Test: `quant-board/tests/test_snapshot_collector_gateway.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_snapshot_collector_gateway.py
from __future__ import annotations

import pytest

from backend.snapshot_collector.gateway import InProcessMarketDataGateway


class FakeQuotesCache:
    def status(self):
        return {"rowCount": 2, "lastError": None}

    def get_diff(self, codes):
        return {
            "rc": 0,
            "data": {
                "diff": [
                    {"f12": codes[0], "f14": "测试", "f2": 10.0},
                    {"f12": codes[1], "f14": "测试2", "f2": 20.0},
                ]
            },
        }


def test_inprocess_gateway_quotes_uses_cache(monkeypatch):
    fake = FakeQuotesCache()
    monkeypatch.setattr(
        "backend.market_proxy.quotes.get_market_quotes_cache", lambda: fake
    )
    gateway = InProcessMarketDataGateway()
    body = gateway.get_json("http://127.0.0.1:1/api/quotes/tencent?codes=000001,600000", 5.0)
    assert body["rc"] == 0
    assert len(body["data"]["diff"]) == 2


def test_inprocess_gateway_quotes_cold_cache_degrades(monkeypatch):
    fake = FakeQuotesCache()
    fake.status = lambda: {"rowCount": 0, "lastError": "fetch_timeout"}
    monkeypatch.setattr(
        "backend.market_proxy.quotes.get_market_quotes_cache", lambda: fake
    )
    gateway = InProcessMarketDataGateway()
    body = gateway.get_json("http://127.0.0.1:1/api/quotes/tencent?codes=000001", 5.0)
    assert body["ok"] is False
    assert body["degraded"] is True


def test_inprocess_gateway_unsupported_path_raises():
    gateway = InProcessMarketDataGateway()
    with pytest.raises(RuntimeError):
        gateway.get_json("http://127.0.0.1:1/api/unknown", 5.0)
```

- [ ] **Step 2: 运行确认失败**

  Run: `.\.venv\Scripts\python.exe -m pytest tests/test_snapshot_collector_gateway.py -v`
  Expected: FAIL（`backend.snapshot_collector.gateway` 不存在）。

- [ ] **Step 3: 实现 gateway.py**

```python
# backend/snapshot_collector/gateway.py
from __future__ import annotations

import json
import re
from typing import Any, Protocol
from urllib.parse import parse_qs, urlparse


class MarketDataGateway(Protocol):
    def get_json(self, url: str, timeout_s: float) -> Any: ...
    def post_json(self, url: str, timeout_s: float, payload: Any | None = None) -> Any: ...


class HttpMarketDataGateway:
    """原行为：经 proxy(3000) 转发到 8000；供 CLI/手动 run 与旧链路使用。"""

    def __init__(self, client: Any = None) -> None:
        self._client = client

    def _client_or_default(self) -> Any:
        if self._client is None:
            from .providers import _get_proxy_http_client

            self._client = _get_proxy_http_client()
        return self._client

    def get_json(self, url: str, timeout_s: float) -> Any:
        response = self._client_or_default().get(url, timeout=timeout_s)
        response.raise_for_status()
        return response.json()

    def post_json(self, url: str, timeout_s: float, payload: Any | None = None) -> Any:
        headers = {"Content-Type": "application/json"} if payload is not None else None
        response = self._client_or_default().post(
            url,
            content=json.dumps(payload) if payload is not None else None,
            headers=headers,
            timeout=timeout_s,
        )
        response.raise_for_status()
        return response.json()


def _degraded(error_code: str, message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "degraded": True,
        "errorCode": error_code,
        "message": message,
        "rc": 0,
        "data": {"diff": []},
    }


def _read_service_cache(service: Any, key: str, ttl_ms: int) -> Any | None:
    """同步读取 market_proxy 服务单例的进程内/Redis 缓存，冷缓存返回 None。"""
    cache = getattr(service, "_cache", None)
    if isinstance(cache, dict):
        entry = cache.get(key)
        if entry and int(entry.get("fetched_at_ms") or 0) + ttl_ms > int(__import__("time").time() * 1000):
            return entry.get("payload")
    redis_get = getattr(service, "_redis_get", None)
    if callable(redis_get):
        entry = redis_get(key)
        if entry is not None:
            return entry.get("payload")
    return None


class InProcessMarketDataGateway:
    """采集进程内直连 market_proxy 服务单例，避免 8000 自环。

    只实现采集器实际使用的路由；进程内后台刷新任务（quotes/hotlist）负责
    预热缓存，冷缓存显式降级（fail-visible），不伪造数据。
    """

    def get_json(self, url: str, timeout_s: float) -> Any:
        del timeout_s
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        path = parsed.path

        if path == "/api/quotes/tencent":
            from backend.market_proxy.quotes import get_market_quotes_cache

            cache = get_market_quotes_cache()
            status = cache.status()
            if status["rowCount"] == 0:
                return _degraded(status["lastError"] or "cache_not_ready", status["lastError"] or "cache_not_ready")
            codes = (query.get("codes") or [""])[0].split(",")
            return cache.get_diff(codes)

        if path == "/api/limitup/ths/pools":
            from backend.market_proxy.limitup import get_limitup_service

            date = (query.get("date") or [""])[0]
            payload = _read_service_cache(get_limitup_service(), date, ttl_ms=300_000)
            if payload is None:
                return {"ok": False, "degraded": True, "date": date, "pools": {}, "errors": ["cache_not_ready"]}
            return payload

        raise RuntimeError(f"in-process gateway does not support GET {path}")

    def post_json(self, url: str, timeout_s: float, payload: Any | None = None) -> Any:
        del timeout_s, payload
        path = urlparse(url).path
        match = re.fullmatch(r"/api/([a-z0-9]+)/hot", path)
        if match:
            platform = match.group(1)
            from backend.market_proxy.hotlists import get_hotlist_service

            service = get_hotlist_service()
            entry = _read_service_cache(service, platform, ttl_ms=int(service._ttl_ms))
            if entry is None:
                return {
                    "ok": False,
                    "degraded": True,
                    "source": platform,
                    "errorCode": "cache_not_ready",
                    "message": "in-process hotlist cache not ready",
                    "data": [],
                }
            return entry
        raise RuntimeError(f"in-process gateway does not support POST {path}")


def create_gateway(in_process: bool = False) -> MarketDataGateway:
    return InProcessMarketDataGateway() if in_process else HttpMarketDataGateway()
```

- [ ] **Step 4: 运行确认通过**

  Run: `.\.venv\Scripts\python.exe -m pytest tests/test_snapshot_collector_gateway.py -v`
  Expected: PASS（3 passed）。

- [ ] **Step 5: providers 注入 gateway（最小改动）**

  在 `backend/snapshot_collector/providers.py`：

  - 模块级加入 `_DEFAULT_GATEWAY: Any | None = None` 与 `set_default_gateway(gateway)` / `_get_default_gateway()`。
  - `_BatchedProxyProvider.__init__`、`StartupBundleStockProvider.__init__`、`ProxyMergedHotlistProvider.__init__`、`ProxyLimitUpProvider.__init__`、`BridgeQuoteProvider.__init__` 增加 `gateway: Any | None = None` 参数，保存为 `self._gateway = gateway or _get_default_gateway()`。
  - `_BatchedProxyProvider._collect_batch`、`StartupBundleStockProvider.collect`、`ProxyMergedHotlistProvider._fetch_platform`、`ProxyLimitUpProvider.collect`、`BridgeQuoteProvider.set_pool/collect` 中的 `_http_get_json/_http_post_json` 改为 `self._gateway.get_json/post_json(...)`。
  - `ProxyHotlistProvider.collect` 同样改走 gateway（`_http_post_json` → `self._gateway.post_json`）。
  - `collect_market_context(providers, codes, timeout_ms=..., gateway=None)` 增加 gateway 参数：provider 未显式注入时用 `setattr(provider, "_gateway", gateway)` 兜底（仅当该 provider 有 `_gateway` 属性）。

  保持 `HttpMarketDataGateway` 为默认，现有 CLI/手动链路行为不变。

- [ ] **Step 6: 运行全量 collector 定向测试**

  Run: `.\.venv\Scripts\python.exe -m pytest tests/test_snapshot_collector_*.py -q`
  Expected: PASS（含 gateway 新增用例；任何 provider 契约回归需修复）。

- [ ] **Step 7: Commit**

  ```bash
  git add quant-board/backend/snapshot_collector/gateway.py quant-board/backend/snapshot_collector/providers.py quant-board/tests/test_snapshot_collector_gateway.py
  git commit -m "feat(collector): add market data gateway to decouple providers from 8000 self-loop"
  ```

---

## Task 2: collector_main 独立采集进程 + Redis 单实例锁 + 交易日历降级

> 实施状态：已完成（2026-08-03，主工作区）。启动载体最终采用 **DragonBoardLauncher 核心启动项**：
> `LauncherServices.CoreStartupStages` 增加 `["collector"]` 阶段（在 quant-api 之前启动，谁先拿锁谁采集）；
> `SnapshotCollectorProbe` 探针改指 8001；`LauncherProcessManager` 就绪门禁/停止列表/孤儿清理同步；
> `LauncherForm` 增加采集服务卡片。不新增计划任务，不恢复 supervisor.py。

**实际落地文件（与上文 Step 编号对应）：**

- Create: `quant-board/backend/snapshot_collector/gateway.py`（Http/InProcess 双网关，provider 注入）
- Create: `quant-board/backend/snapshot_collector/instance_lock.py`（Redis SET NX + renew，TTL 300s，Redis 缺失 fail-open）
- Modify: `quant-board/backend/snapshot_collector/trading_calendar.py`（bridge→本地缓存→工作日启发式，`trading_date_from_ts` 不再抛异常）
- Create: `quant-board/backend/collector_main.py`（8001 独立进程：采集路由 + 健康检查 + 行情/热榜/资金/涨停池刷新 + 锁续期）
- Modify: `quant-board/backend/main.py`（8000 侧 scheduler 启动前竞争同一 Redis 锁，锁被持有则让位）
- Modify: `tools/DragonBoardLauncher/{LauncherServices,LauncherProcessManager,SnapshotCollectorProbe,LauncherForm}.cs`
- Test: `quant-board/tests/test_snapshot_collector_{gateway,instance_lock,calendar_fallback}.py`；`test_snapshot_collector_scheduler.py` 既有 3 个 `trading_date_from_ts` 用例补 `_CACHE_PATH` monkeypatch

验证结果：定向 pytest 104 passed；全量 collector 套件（排除两个 HEAD 既有失败文件）452 passed；
`dotnet build tools/DragonBoardLauncher` 0 警告 0 错误；`backend.collector_main`/gateway/instance_lock 冒烟导入正常。

**注意（既有基线失败，与本次改动无关）**：`d6b27fc`（2026-08-03 18:31，"urllib 换共享 httpx.Client"）未同步
`tests/test_snapshot_collector_bridge_provider.py` 与 `tests/test_snapshot_collector_contract.py`，二者仍 mock
`urllib.request.urlopen`，在 HEAD 上即失败（19 项）。建议后续把这两个测试文件改为 mock httpx 客户端层。

**Files:**
- Create: `quant-board/backend/collector_main.py`
- Create: `quant-board/backend/snapshot_collector/instance_lock.py`
- Modify: `quant-board/backend/snapshot_collector/trading_calendar.py`
- Test: `quant-board/tests/test_snapshot_collector_instance_lock.py`、`quant-board/tests/test_snapshot_collector_calendar_fallback.py`

- [ ] **Step 1: 写失败测试（单实例锁）**

```python
# tests/test_snapshot_collector_instance_lock.py
from __future__ import annotations

from backend.snapshot_collector.instance_lock import RedisInstanceLock


class FakeRedis:
    def __init__(self):
        self._values: dict[str, str] = {}

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self._values:
            return False
        self._values[key] = value
        return True

    def get(self, key):
        return self._values.get(key)


def test_lock_acquire_and_release():
    redis = FakeRedis()
    lock = RedisInstanceLock(redis, "collector")
    assert lock.acquire() is True
    assert RedisInstanceLock(redis, "collector").acquire() is False  # 第二实例拿不到
    lock.release()
    assert RedisInstanceLock(redis, "collector").acquire() is True


def test_lock_redis_unavailable_is_not_fatal():
    lock = RedisInstanceLock(None, "collector")
    assert lock.acquire() is True  # 无 Redis 时降级为允许启动（fail-open，避免停采）
```

- [ ] **Step 2: 运行确认失败**

  Run: `.\.venv\Scripts\python.exe -m pytest tests/test_snapshot_collector_instance_lock.py -v`
  Expected: FAIL（模块不存在）。

- [ ] **Step 3: 实现 instance_lock.py**

```python
# backend/snapshot_collector/instance_lock.py
from __future__ import annotations

import logging
import uuid
from typing import Any


logger = logging.getLogger(__name__)


class RedisInstanceLock:
    """Redis SET NX 单实例锁：防止重复拉起采集进程导致重复采集。

    Redis 不可用/未配置时 fail-open（允许启动），避免锁本身成为停采原因；
    重复实例时第二个进程拒绝启动 scheduler。
    """

    def __init__(self, redis_client: Any, name: str, ttl_seconds: int = 86400) -> None:
        self._redis = redis_client
        self._key = f"snapshot-collector:instance-lock:{name}"
        self._token = uuid.uuid4().hex
        self._ttl_seconds = max(60, ttl_seconds)

    def acquire(self) -> bool:
        if self._redis is None:
            logger.warning("Redis unavailable: instance lock disabled (fail-open)")
            return True
        try:
            return bool(
                self._redis.set(self._key, self._token, nx=True, ex=self._ttl_seconds)
            )
        except Exception as exc:
            logger.warning("instance lock acquire failed: %s", exc)
            return True

    def release(self) -> None:
        if self._redis is None:
            return
        try:
            if self._redis.get(self._key) == self._token:
                self._redis.delete(self._key)
        except Exception as exc:
            logger.warning("instance lock release failed: %s", exc)
```

- [ ] **Step 4: 运行确认通过**

  Run: `.\.venv\Scripts\python.exe -m pytest tests/test_snapshot_collector_instance_lock.py -v`
  Expected: PASS（2 passed）。

- [ ] **Step 5: 写失败测试（交易日历降级）**

```python
# tests/test_snapshot_collector_calendar_fallback.py
from __future__ import annotations

from backend.snapshot_collector import trading_calendar as tc


def test_trading_date_from_ts_falls_back_to_weekday_when_bridge_down(monkeypatch, tmp_path):
    monkeypatch.setattr(tc, "_CACHE_PATH", tmp_path / "calendar_cache.json")
    monkeypatch.setattr(
        tc,
        "_fetch_bridge_calendar",
        lambda date: None,  # bridge 不可用
    )
    # 2026-08-03 是周一
    ts = 1785733200000  # 2026-08-03 13:00 Asia/Shanghai
    assert tc.trading_date_from_ts(ts) == "2026-08-03"
    assert tc._last_calendar_source == "heuristic_weekday"


def test_trading_date_from_ts_uses_cache_when_bridge_down(monkeypatch, tmp_path):
    cache_path = tmp_path / "calendar_cache.json"
    cache_path.write_text('{"2026-08-03": false}', encoding="utf-8")
    monkeypatch.setattr(tc, "_CACHE_PATH", cache_path)
    monkeypatch.setattr(
        tc,
        "_fetch_bridge_calendar",
        lambda date: None,
    )
    ts = 1785733200000
    assert tc.trading_date_from_ts(ts) is None  # 缓存明确非交易日
```

- [ ] **Step 6: 运行确认失败**

  Run: `.\.venv\Scripts\python.exe -m pytest tests/test_snapshot_collector_calendar_fallback.py -v`
  Expected: FAIL（当前实现抛 `TradingCalendarUnavailable`，且无缓存路径）。

- [ ] **Step 7: 实现交易日历降级**

  修改 `backend/snapshot_collector/trading_calendar.py`：

  ```python
  _CACHE_PATH = Path(__file__).resolve().parents[2] / "data" / "trading_calendar_cache.json"
  _last_calendar_source: str = "bridge"

  def _read_calendar_cache() -> dict[str, bool]:
      try:
          if _CACHE_PATH.exists():
              return json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
      except Exception:
          pass
      return {}

  def _write_calendar_cache(date: str, value: bool) -> None:
      try:
          data = _read_calendar_cache()
          data[date] = value
          _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
          _CACHE_PATH.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
      except Exception:
          pass

  def _weekday_heuristic(date: datetime.date) -> bool:
      return date.weekday() < 5
  ```

  `is_trading_day(date)` 改为：先查缓存命中直接返回；否则尝试 bridge，成功后写缓存并返回；bridge 失败时回退 `_weekday_heuristic` 并把全局 `_last_calendar_source` 置为 `"heuristic_weekday"`（不再抛异常）。

  `trading_date_from_ts` 保持返回 `str | None`，不再因 bridge 异常抛错；`_last_calendar_source` 供 status API 暴露（Task 2 Step 9 使用）。

- [ ] **Step 8: 运行确认通过**

  Run: `.\.venv\Scripts\python.exe -m pytest tests/test_snapshot_collector_calendar_fallback.py tests/test_snapshot_collector_scheduler.py -q`
  Expected: PASS。

- [ ] **Step 9: 实现 collector_main.py（独立采集进程）**

```python
# backend/collector_main.py
"""Standalone snapshot collector process (default port 8001).

Only mounts snapshot-collector routes and health; starts the market-proxy
background refreshers the collector needs, so 8000 availability no longer
gates snapshot collection.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.settings import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    from backend.market_fund_scheduler import market_fund_scheduler
    from backend.market_proxy.hotlists import (
        close_hotlist_client,
        start_hotlist_refresh,
        stop_hotlist_refresh,
    )
    from backend.market_proxy.quotes import (
        start_market_quotes_refresh,
        stop_market_quotes_refresh,
    )
    from backend.snapshot_collector.instance_lock import RedisInstanceLock
    from backend.snapshot_collector.providers import (
        InProcessMarketDataGateway,
        close_collector_http,
        set_default_gateway,
    )
    from backend.snapshot_collector.scheduler import snapshot_collector_scheduler

    settings = get_settings()
    redis_client = None
    if settings.redis_url:
        try:
            import redis as redis_module

            redis_client = redis_module.Redis.from_url(
                settings.redis_url,
                socket_connect_timeout=1.0,
                socket_timeout=1.0,
                decode_responses=True,
            )
        except Exception:
            redis_client = None
    lock = RedisInstanceLock(redis_client, "dragonboard_live")
    if not lock.acquire():
        raise RuntimeError("another snapshot collector instance holds the lock")

    set_default_gateway(InProcessMarketDataGateway())
    try:
        await start_market_quotes_refresh()
        await start_hotlist_refresh()
        market_fund_scheduler.start()
        snapshot_collector_scheduler.start()
        yield
    finally:
        await snapshot_collector_scheduler.stop()
        market_fund_scheduler.stop()
        await stop_hotlist_refresh()
        await close_hotlist_client()
        await stop_market_quotes_refresh()
        close_collector_http()
        lock.release()


app = FastAPI(title="QuantBoard Snapshot Collector", lifespan=lifespan)

from backend.api.snapshot_collector_routes import router as snapshot_collector_router

app.include_router(snapshot_collector_router)


@app.get("/api/health")
def health() -> dict:
    from backend.snapshot_collector.scheduler import snapshot_collector_scheduler
    from backend.snapshot_collector.trading_calendar import _last_calendar_source

    status = snapshot_collector_scheduler.status()
    status["calendarSource"] = _last_calendar_source
    return {"status": "ok", "snapshotCollector": status}
```

  `market_fund_scheduler.stop()` 若为 async，改为 `await market_fund_scheduler.stop()`（以 `backend/main.py` 现有 shutdown 用法为准）。

- [ ] **Step 10: 手动冒烟验证独立进程**

  Run:
  ```powershell
  cd <worktree>\quant-board
  .\.venv\Scripts\python.exe -m uvicorn backend.collector_main:app --host 127.0.0.1 --port 8001
  ```
  另开终端：`Invoke-RestMethod http://127.0.0.1:8001/api/health` 与 `http://127.0.0.1:8001/api/snapshot-collector/scheduler/status`。
  Expected: `enabled=true`、`running=true`、`dataset_id` 与 `.env.local` 一致；同时确认 8000 进程不受影响。

- [ ] **Step 11: Commit**

  ```bash
  git add quant-board/backend/collector_main.py quant-board/backend/snapshot_collector/instance_lock.py quant-board/backend/snapshot_collector/trading_calendar.py quant-board/tests/test_snapshot_collector_instance_lock.py quant-board/tests/test_snapshot_collector_calendar_fallback.py
  git commit -m "feat(collector): standalone collector process with instance lock and calendar fallback"
  ```

---

## Task 3: 移除 normalizer 硬门禁（fail-visible）

> 实施状态：已完成（2026-08-03，主工作区）。
> - `backend/data/snapshot_ingest_normalizer.py`：`formal snapshot hotlist is empty` 抛错改为给
>   frame/record 打 `empty_hotlist_with_partial_data` 标记并保留数据；快照身份/records 缺失等
>   合同校验仍抛错。全源无数据的拒写判定保留在 `service.run_once`（`not stock_rows and
>   all_hotlist_sources_failed`）。
> - 新增 `tests/test_snapshot_ingest_normalizer_gate.py`（3 用例：空热榜保留+打标、身份缺失仍抛、
>   records 缺失仍抛）；同步更新 `tests/test_snapshot_collector_builder.py` 中旧的"空热榜拒写"契约为
>   "保留+打标"。
> - 验证：新增文件 3 passed；collector 全套件（排除两个 HEAD 既有失败文件）457 passed。

**Files:**
- Modify: `quant-board/backend/data/snapshot_ingest_normalizer.py`
- Test: `quant-board/tests/test_snapshot_ingest_normalizer_gate.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_snapshot_ingest_normalizer_gate.py
from __future__ import annotations

import pytest

from backend.data.schemas import SnapshotIngestRequest
from backend.data.snapshot_ingest_normalizer import normalize_snapshot_ingest


def _bundle_without_stock_rows():
    return {
        "items": [
            {
                "id": "half_hour:2026-08-03:15:00",
                "type": "half_hour",
                "tradingDate": "2026-08-03",
                "slotTime": "15:00",
                "timestamp": 1785751200000,
                "payload": {"sectors": [{"themeId": "T1"}]},
            }
        ],
        "frames": [
            {
                "snapshotId": "half_hour:2026-08-03:15:00",
                "type": "half_hour",
                "tradingDate": "2026-08-03",
                "slotTime": "15:00",
                "timestamp": 1785751200000,
                "stockRowCount": 0,
                "sectorRowCount": 5,
            }
        ],
        "stockRows": [],
        "sectorRows": [
            {
                "snapshotId": "half_hour:2026-08-03:15:00",
                "entityType": "hot_theme",
                "entityKey": "T1",
            }
        ],
        "snapshotId": "half_hour:2026-08-03:15:00",
    }


def test_normalizer_keeps_partial_data_when_hotlist_empty():
    request = SnapshotIngestRequest(
        dataset_id="dragonboard_live",
        bundle=_bundle_without_stock_rows(),
        source="quantboard_backend_collector",
    )
    dataset, records, frames, stock_rows, sector_rows, key = normalize_snapshot_ingest(request)
    assert len(frames) == 1
    assert len(sector_rows) == 1
    assert len(stock_rows) == 0
    assert "empty_hotlist_with_partial_data" in frames[0].get("qualityFlags", [])


def test_normalizer_still_requires_identity():
    bundle = _bundle_without_stock_rows()
    bundle["frames"][0]["snapshotId"] = ""
    request = SnapshotIngestRequest(
        dataset_id="dragonboard_live",
        bundle=bundle,
        source="quantboard_backend_collector",
    )
    with pytest.raises(ValueError):
        normalize_snapshot_ingest(request)
```

- [ ] **Step 2: 运行确认失败**

  Run: `.\.venv\Scripts\python.exe -m pytest tests/test_snapshot_ingest_normalizer_gate.py -v`
  Expected: 第一个用例 FAIL（当前 raise `formal snapshot hotlist is empty`）。

- [ ] **Step 3: 修改 normalizer**

  在 `snapshot_ingest_normalizer.py` 中，将 `empty_formal_snapshot_ids` 的抛错逻辑替换为：

  ```python
  for frame in frames:
      sid = row_snapshot_id(frame)
      if (
          str(frame.get("type") or "") != "five_minute"
          and sid
          and str(frame.get("captureMode") or "real_time") != "restored"
          and stock_row_count_by_snapshot.get(sid, 0) == 0
      ):
          flags = list(frame.get("qualityFlags") or [])
          flags.append("empty_hotlist_with_partial_data")
          frame["qualityFlags"] = list(dict.fromkeys(flags))
          for record in records:
              if row_snapshot_id(record) == sid:
                  rec_flags = list(record.get("qualityFlags") or [])
                  rec_flags.append("empty_hotlist_with_partial_data")
                  record["qualityFlags"] = list(dict.fromkeys(rec_flags))
  ```

  保留 snapshot identity 校验（`snapshot_ids` 为空仍 raise）；保留 `records` 缺失 raise。全源无数据拒写仍由 `service.py` 的 `not stock_rows and all_hotlist_sources_failed` 分支负责。

- [ ] **Step 4: 运行确认通过**

  Run: `.\.venv\Scripts\python.exe -m pytest tests/test_snapshot_ingest_normalizer_gate.py tests/test_snapshot_collector_contract.py -q`
  Expected: PASS（原 contract 测试同步通过）。

- [ ] **Step 5: Commit**

  ```bash
  git add quant-board/backend/data/snapshot_ingest_normalizer.py quant-board/tests/test_snapshot_ingest_normalizer_gate.py
  git commit -m "fix(collector): save partial data when hotlist empty instead of blocking ingest"
  ```

---

## Task 4: 行情字段补齐（pe/pb/cirMV/totalMV/volumeRatio/limitUpPrice/limitDownPrice/lastTrade*）

> 实施状态：已完成（2026-08-03，主工作区）。
> - `providers.py` `TencentBasicQuoteProvider`：补齐 `pe(f9)/pb(f23)/totalMarketValue(f20 万元→元)/cirMV(f21 万元→元)`；
>   缺失时保持缺失（不写 0 占位）；`volumeRatio` 沿用 f10。
> - `builder.py`：quote 透传 `cirMV/pb/limitUpPrice/limitDownPrice`，派生 `lastTradePrice/lastTradeVolume`；
>   **涨跌停价改由 preClose 按 A 股规则派生**（ST 5%、创业板/科创板 20%、北交所 30%、其余 10%）——
>   实测 akshare 腾讯 `getBoardRankList` 无 ztj/dtj 字段，两个上游都没有涨跌停价，派生口径与回测自身
>   `_limit_pct_threshold` 一致。
> - `service.py`：`run_once` 接入 `compute_volume_ratios` golden（进程内调用，缺失才填，带
>   `volumeRatioMeta` 来源/状态）。
> - 新增 `tests/test_snapshot_collector_quote_fields.py`（5 用例：provider 全字段、builder 透传、主板派生、
>   ST/创业板派生、service 量比 golden 填充）。
> - 验证：新增 5 passed；collector 全套件（排除两个 HEAD 既有失败文件）462 passed。

**Files:**
- Modify: `quant-board/backend/market_proxy/quotes.py`
- Modify: `quant-board/backend/snapshot_collector/providers.py`
- Modify: `quant-board/backend/snapshot_collector/builder.py`
- Modify: `quant-board/backend/snapshot_collector/service.py`
- Test: `quant-board/tests/test_snapshot_collector_quote_fields.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_snapshot_collector_quote_fields.py
from __future__ import annotations

from backend.snapshot_collector.providers import TencentBasicQuoteProvider
from backend.snapshot_collector.builder import build_ingest_payload
from backend.snapshot_collector.models import MarketDataContext, SnapshotSlot


def _diff_row():
    return {
        "f12": "000001",
        "f14": "平安银行",
        "f2": 11.62,
        "f3": -0.09,
        "f6": 1060851.0,
        "f5": 1232708862.0,
        "f8": 0.55,
        "f9": 5.24,
        "f10": 0.64,
        "f20": 22549700.0,
        "f21": 22549300.0,
        "f23": 0.49,
        "ztPrice": 12.78,
        "dtPrice": 10.46,
    }


def test_tencent_provider_maps_full_fields():
    provider = TencentBasicQuoteProvider()
    row = provider._normalize_row(_diff_row())
    assert row["pe"] == 5.24
    assert row["pb"] == 0.49
    assert row["totalMarketValue"] == 22549700.0 * 10000  # 万元 -> 元
    assert row["cirMV"] == 22549300.0 * 10000
    assert row["volumeRatio"] == 0.64
    assert row["limitUpPrice"] == 12.78
    assert row["limitDownPrice"] == 10.46


def test_builder_passes_quote_extra_fields_through():
    ctx = MarketDataContext(
        stocks=[{"code": "000001", "name": "平安银行", "rank": 1}],
        quotes=[
            {
                "code": "000001",
                "price": 11.62,
                "pctChange": -0.09,
                "volume": 1060851.0,
                "amount": 1232708862.0,
                "pe": 5.24,
                "pb": 0.49,
                "totalMarketValue": 225497000000.0,
                "cirMV": 225493000000.0,
                "limitUpPrice": 12.78,
                "limitDownPrice": 10.46,
            }
        ],
    )
    slot = SnapshotSlot("half_hour", "2026-08-03", "15:00", 1785751200000)
    payload = build_ingest_payload(slot, ctx, dataset_id="dragonboard_live")
    row = payload["stockRows"][0]
    assert row["pe"] == 5.24
    assert row["pb"] == 0.49
    assert row["totalMV"] == 225497000000.0
    assert row["cirMV"] == 225493000000.0
    assert row["limitUpPrice"] == 12.78
    assert row["limitDownPrice"] == 10.46
    assert row["lastTradePrice"] == 11.62
    assert row["lastTradeVolume"] == 1060851.0
```

- [ ] **Step 2: 运行确认失败**

  Run: `.\.venv\Scripts\python.exe -m pytest tests/test_snapshot_collector_quote_fields.py -v`
  Expected: FAIL（pe/pb/cirMV/limitUpPrice 等断言不通过）。

- [ ] **Step 3: market_proxy 透传涨停价/跌停价**

  修改 `backend/market_proxy/quotes.py` 的 `to_tencent_diff_item`，在返回 dict 中追加（新增键不破坏前端合同）：

  ```python
  "ztPrice": _number(row.get("ztj")),
  "dtPrice": _number(row.get("dtj")),
  ```

- [ ] **Step 4: 腾讯 provider 全字段映射**

  修改 `TencentBasicQuoteProvider._normalize_row`：

  ```python
  row = {
      "code": code,
      "name": str(item.get("f14") or code),
      "price": _safe_float(item.get("f2")),
      "change": _safe_float(item.get("f3")),
      "volume": _safe_float(item.get("f6")),
      "amount": _safe_float(item.get("f5")),
      "turnoverRate": _safe_float(item.get("f8")),
      "pe": _safe_float(item.get("f9")),
      "pb": _safe_float(item.get("f23")),
      # f20/f21 单位为万元（前端合同），collector 落库统一为元
      "totalMarketValue": _safe_float(item.get("f20")) * 10000,
      "cirMV": _safe_float(item.get("f21")) * 10000,
      "limitUpPrice": _safe_float(item.get("ztPrice")),
      "limitDownPrice": _safe_float(item.get("dtPrice")),
  }
  volume_ratio = _safe_float(item.get("f10"), float("nan"))
  if math.isfinite(volume_ratio) and volume_ratio > 0:
      row["volumeRatio"] = volume_ratio
  return row
  ```

- [ ] **Step 5: builder 透传与 lastTrade 派生**

  修改 `builder.py _enrich_stock_rows_from_quotes`：

  - 在 `tmv` 块后追加：

    ```python
    cir_mv = q.get("cirMV")
    if cir_mv is not None:
        row["cirMV"] = cir_mv
    pb = q.get("pb")
    if pb is not None:
        row["pb"] = pb
    for field in ("limitUpPrice", "limitDownPrice"):
        value = q.get(field)
        if value is not None and not row.get(field):
            row[field] = value
    if row.get("price") is not None and not row.get("lastTradePrice"):
        row["lastTradePrice"] = row["price"]
    if row.get("volume") is not None and not row.get("lastTradeVolume"):
        row["lastTradeVolume"] = row["volume"]
    ```

- [ ] **Step 6: service 接入量比 golden**

  修改 `service.py`：

  - `run_once` 在 `build_ingest_payload` 之后、`normalize` 之前调用新 helper：

    ```python
    self._enrich_volume_ratios(bundle.get("stockRows") or [])
    ```

  - 新增方法：

    ```python
    def _enrich_volume_ratios(self, stock_rows: list[dict[str, Any]]) -> None:
        from backend.data.repository_factory import get_runtime_mongodb_database
        from backend.volume_ratio_service import compute_volume_ratios

        if not stock_rows:
            return
        try:
            db = get_runtime_mongodb_database()
            items = compute_volume_ratios(db, stock_rows)
        except Exception:
            return
        for row in stock_rows:
            code = str(row.get("code") or "")
            item = items.get(code)
            if not item:
                continue
            ratio = item.get("volumeRatio")
            if isinstance(ratio, (int, float)) and not isinstance(ratio, bool) and ratio > 0 and not row.get("volumeRatio"):
                row["volumeRatio"] = round(float(ratio), 4)
                row["volumeRatioMeta"] = {
                    "source": str(item.get("source") or "quantboard_volume_ratio"),
                    "status": str(item.get("status") or "unavailable"),
                    "calculatedAt": item.get("calculatedAt"),
                }
    ```

- [ ] **Step 7: 运行确认通过**

  Run: `.\.venv\Scripts\python.exe -m pytest tests/test_snapshot_collector_quote_fields.py tests/test_snapshot_collector_providers.py tests/test_theme_fund_cache.py -q`
  Expected: PASS（新增字段 + provider 契约回归）。

- [ ] **Step 8: Commit**

  ```bash
  git add quant-board/backend/market_proxy/quotes.py quant-board/backend/snapshot_collector/providers.py quant-board/backend/snapshot_collector/builder.py quant-board/backend/snapshot_collector/service.py quant-board/tests/test_snapshot_collector_quote_fields.py
  git commit -m "feat(collector): map full quote fields and wire volume-ratio golden"
  ```

---

## Task 5: 验证、文档与收尾

> 实施状态：已完成（2026-08-03，主工作区）。
> - 全量 pytest：1165 passed；28 个失败均为 HEAD 既有基线（`test_snapshot_collector_bridge_provider.py` 22 +
>   `test_snapshot_collector_contract.py` 6，仍在 mock `urllib.request.urlopen`）。另修复了网关重构暴露的
>   `test_theme_heat_providers.py` 3 个用例（注入点改为网关）。
> - 真实 dry-run 验收（HTTP 网关链路）：修复了本机系统代理（iKuuuVPN 127.0.0.1:7890）劫持 httpx
>   localhost 请求导致 502 的问题——采集器本地客户端 `trust_env=False`（回归测试锁定）。dry-run 结果为
>   227 行，Task 4 新字段覆盖率 ≥99%（pe/pb/cirMV/totalMV/volumeRatio/涨跌停价/lastTrade*）。
> - 文档同步：`architecture.md`、`api-cli.md`、`AI_COLLABORATION.md`、本计划与优化方案文档。
> - `dotnet build -c Release` 0 警告 0 错误。

---

## 附加任务：存量历史字段按证据回填（2026-08-03 已完成）

> - 新增 `backend/operations/snapshot_field_backfill.py` + CLI `snapshot-backfill-fields`（默认 dry-run，
>   `--apply` 写库，默认先备份）。只填充缺失字段，只使用行内证据；`pe/pb/cirMV/volumeRatio` 无历史
>   时点证据，保持缺失不伪造；`zljzb` 加 (0,100] 单位安全界。
> - 执行结果（`dragonboard_live`，527,616 行扫描）：189,889 行回填 —— `lastTradePrice` 183,359、
>   `lastTradeVolume` 179,436、`limitUpPrice/limitDownPrice` 各 86,254、`zljzb` 4,613、`amplitude` 2,823。
> - 备份集合 `snapshot_stock_rows_field_backfill_backup_20260803_134807`（189,889 文档，与更新数一致）；
>   审计 `snapshot-field-backfill-5043f907fa80467ca6bdbee6b40cbc5b`。行数无漂移（527,616 不变）；
>   按交易所规则抽样 3,000 行校验全部精确匹配；近期交易日涨跌停价/振幅/最新价覆盖率升至 ~99%。
> - 测试：`tests/test_snapshot_field_backfill.py` 12 用例（主板/创业板/科创板/北交所/ST 涨跌停派生、
>   占位零值不视为证据、不覆盖已有值、dry-run 不写库、apply 备份+更新+审计）。

**Files:**
- Modify: `quant-board/docs/architecture.md`、`quant-board/docs/api-cli.md`、`quant-board/docs/AI_COLLABORATION.md`
- Modify: `quant-board/docs/snapshot-collector/2026-08-03-snapshot-collector-optimization-plan.md`（状态更新）

- [ ] **Step 1: 全量定向测试**

  Run:
  ```powershell
  cd <worktree>\quant-board
  .\.venv\Scripts\python.exe -m pytest tests/test_snapshot_collector_*.py tests/test_snapshot_ingest_normalizer_gate.py tests/test_volume_ratio_service.py -q
  .\.venv\Scripts\python.exe -m pytest -q
  ```
  Expected: 全部 PASS；失败项若属于既有基线须记录并说明。

- [ ] **Step 2: 真实 dry-run 验收（8001 独立进程）**

  Run:
  ```powershell
  .\.venv\Scripts\python.exe -m backend.cli snapshot-collector-run-once --dataset-id dragonboard_live --snapshot-type half_hour --trading-date <下一交易日> --slot-time 15:00 --dry-run
  ```
  Expected: `ok=true`；`details.stockRowCount > 0`；sourceHealth 显示 `theme_quote_tencent` 有行数、`quote_bridge` 正常。

- [ ] **Step 3: 首个完整交易日人工核对（上线后）**

  查 MongoDB（不只 API status）：

  ```powershell
  .\.venv\Scripts\python.exe -m backend.cli snapshot-collector-audit --dataset-id dragonboard_live --snapshot-type half_hour
  ```
  核对：缺槽为空、countDrifts 为空、`volumeRatio/pe/pb/cirMV/totalMV` 覆盖率 ≥95%（同日 tencent 源健康时）。

- [ ] **Step 4: 文档同步**

  - `architecture.md`：采集进程独立运行（8001）、provider 网关、日历降级、单实例锁。
  - `api-cli.md`：`collector_main` 启动命令；`snapshot_collector_poll_ms` 标注废弃。
  - `AI_COLLABORATION.md`：P0 完成状态与验收口径。
  - 优化方案文档头部状态改为"P0 已实施，P1 待排期"。

- [ ] **Step 5: Commit**

  ```bash
  git add quant-board/docs/architecture.md quant-board/docs/api-cli.md quant-board/docs/AI_COLLABORATION.md quant-board/docs/snapshot-collector/
  git commit -m "docs(collector): record standalone collector process and P0 field mapping"
  ```

- [ ] **Step 6: 汇总合并说明**

  输出：改动文件清单、验证结果、8001 进程运行方式、与 8000 并存说明、回滚方式（关闭 8001 即恢复旧链路）。

---

## Self-Review

- P0 目标覆盖：独立采集进程（Task 2）✓；normalizer 硬门禁移除（Task 3）✓；行情字段补齐 + 量比接入（Task 4）✓。
- 无占位符：所有测试与实现代码均给出具体内容。
- 类型一致：`MarketDataGateway.get_json/post_json` 在 gateway.py、providers.py、测试中签名一致；`_enrich_volume_ratios` 在 service.py 内定义并在 `run_once` 调用。
- 未纳入（明确留待 P1）：当日缺槽自动回补 + 飞书告警、SnapshotDerivationService 主题字段、sector 资金/rotationState 补齐、backfill 限当日、runs 逐字段覆盖统计。
