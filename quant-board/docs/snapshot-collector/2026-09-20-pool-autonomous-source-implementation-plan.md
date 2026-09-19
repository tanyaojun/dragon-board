# 快照采集池单一事实源（自治热榜池）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 快照采集池切换为采集器自治的八平台热榜实时合并池（`autonomous` 模式，默认），bundle 降级为只供 `snapshotContext`，使任何时刻前端行情列表中的股票必然在快照池内；提供 `bundle_first` 配置开关可一键回退。

**Architecture:** 重写 `providers.py` 的 `collect_market_context` / `collect_market_context_async` 路由——`ProxyMergedHotlistProvider` 从 fallback 升为主池来源，`StartupBundleStockProvider` 只供 context；每行注入 `poolSource` provenance，merged health 注入 `poolComposition` 明细；自治池全挂时 bundle 行兜底（fail-visible，§4.0）。mode 经 `SnapshotCollectorService._collect_context` 从 settings 读取传入；自定义 `collect_fn`（现有测试/扩展）走原分支不受影响。

**Tech Stack:** Python 3 / pytest（quant-board `.venv`）；无新依赖。

**Spec:** `docs/superpowers/specs/2026-09-19-snapshot-pool-autonomous-source-design.md`（2026-09-19 用户已确认）

**验证命令（quant-board 目录）：**

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_snapshot_collector_providers.py tests/test_snapshot_collector_async_pipeline.py tests/test_snapshot_collector_service.py -v
.\.venv\Scripts\python.exe -m pytest
```

---

## 文件结构（改动映射）

| 文件 | 动作 | 职责 |
| --- | --- | --- |
| `quant-board/backend/core/settings.py` | 修改 | 新增 `snapshot_collector_pool_source_mode`（默认 `autonomous`）+ env 覆盖 |
| `quant-board/backend/snapshot_collector/providers.py` | 修改 | 路由重写（同步 + async）、`_mark_pool_source`、poolComposition、bundle 兜底 |
| `quant-board/backend/snapshot_collector/service.py` | 修改 | `_pool_source_mode()` 读取 + `_collect_context` 传参 + `snapshot_context_missing` warning |
| `quant-board/tests/test_snapshot_collector_service.py` | 修改 | settings 默认值 / env 覆盖用例 |
| `quant-board/tests/test_snapshot_collector_providers.py` | 修改 | 新增 autonomous 路由用例；旧用例显式 `bundle_first` 守护回退路径 |
| `quant-board/tests/test_snapshot_collector_async_pipeline.py` | 修改 | async autonomous 用例 |
| `quant-board/docs/snapshot-collector/2026-09-20-pool-autonomous-source-implementation-plan.md` | 本文件 | 实施状态回填 |
| `quant-board/docs/architecture.md` | 修改 | 采集池口径段落同步 |

已有事实（写代码前须知）：

- `_create_providers`（service.py:864）返回 `[StartupBundleStockProvider, ProxyMergedHotlistProvider, TencentBasicQuoteProvider, BridgeQuoteProvider, MarketFundCacheProvider, ProxyLimitUpProvider, (ThemeMappingProvider)]`——列表里**没有** `ProxyHotlistProvider`（单平台诊断 provider，仅测试/CLI 手动组装）。
- `StartupBundleStockProvider.collect()` 成功时设置实例属性 `snapshot_context`（providers.py:533-537）；测试中 patch `collect` 时须手动设置该属性。
- `SourceHealth` 有 `details`、`failed_batches` 字段；merged provider 的 health 已带 `details={"rankProvenance": {...}}` 与 `failed_batches=failed_platforms`。
- `service.py` `_collect_context`（284-303）用 `self._collect_fn is providers_module.collect_market_context_async` 区分真实链路与自定义 `collect_fn`——mode 参数只走真实链路分支，自定义 collect_fn（如 `test_arun_once_multi_collects_once_derives_per_type` 的 `fake_collect`）签名不变。

---

### Task 1: Settings 新增 `snapshot_collector_pool_source_mode`

**Files:**
- Modify: `quant-board/backend/core/settings.py`（约 140 行 `snapshot_collector_*` 字段区；约 431 行 env 覆盖区）
- Test: `quant-board/tests/test_snapshot_collector_service.py`

- [ ] **Step 1: 写失败测试（默认值 + env 覆盖）**

在 `quant-board/tests/test_snapshot_collector_service.py` 的 `TestSettingsDefaults` 类末尾（`test_default_allow_live_dataset_is_false` 之后）追加：

```python
    def test_default_pool_source_mode_is_autonomous(self) -> None:
        settings = Settings()
        assert settings.snapshot_collector_pool_source_mode == "autonomous"
```

在 `TestSettingsEnvOverrides` 类末尾（`test_allow_live_dataset_via_env_true` 之后）追加：

```python
    def test_pool_source_mode_via_env(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("QUANT_BOARD_SNAPSHOT_COLLECTOR_POOL_SOURCE_MODE", "bundle_first")
        settings = Settings()
        assert settings.snapshot_collector_pool_source_mode == "bundle_first"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd quant-board && .\.venv\Scripts\python.exe -m pytest tests/test_snapshot_collector_service.py::TestSettingsDefaults::test_default_pool_source_mode_is_autonomous tests/test_snapshot_collector_service.py::TestSettingsEnvOverrides::test_pool_source_mode_via_env -v`
Expected: FAIL（`Settings` object has no attribute `snapshot_collector_pool_source_mode`）

- [ ] **Step 3: 最小实现**

`quant-board/backend/core/settings.py`：在 `snapshot_collector_provider_timeout_ms: int = Field(default=30000)`（约 142 行）之后新增字段：

```python
    # 采集池来源模式（2026-09-20 spec：docs/superpowers/specs/2026-09-19-snapshot-pool-autonomous-source-design.md）
    # autonomous = 八平台热榜实时合并池为主池（bundle 只供 snapshotContext）；
    # bundle_first = 旧行为（bundle 为主池，merged 仅 fallback）。改后重启采集进程生效。
    snapshot_collector_pool_source_mode: str = Field(default="autonomous")
```

在 `__init__` 的 env 覆盖区（`self.snapshot_collector_provider_timeout_ms = max(...)` 之后）追加：

```python
        self.snapshot_collector_pool_source_mode = os.environ.get(
            "QUANT_BOARD_SNAPSHOT_COLLECTOR_POOL_SOURCE_MODE",
            self.snapshot_collector_pool_source_mode,
        )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd quant-board && .\.venv\Scripts\python.exe -m pytest tests/test_snapshot_collector_service.py -v`
Expected: PASS（全部用例）

- [ ] **Step 5: 提交**

```bash
git add quant-board/backend/core/settings.py quant-board/tests/test_snapshot_collector_service.py
git commit -m "feat(collector): snapshot_collector_pool_source_mode 配置项（默认 autonomous）"
```

---

### Task 2: 同步版路由重写（autonomous 主池 + bundle 兜底 + provenance）

**Files:**
- Modify: `quant-board/backend/snapshot_collector/providers.py`（模块常量区约 46 行；`collect_market_context` 1865-1963）
- Test: `quant-board/tests/test_snapshot_collector_providers.py`

- [ ] **Step 1: 写失败测试**

在 `quant-board/tests/test_snapshot_collector_providers.py` 的 `TestCollectMarketContext` 类之后新增类（沿用该文件的 mock 模式；文件顶部已有 `SourceHealth`、`StartupBundleStockProvider`、`ProxyMergedHotlistProvider`、`TencentBasicQuoteProvider`、`collect_market_context` 导入）：

```python
class TestCollectMarketContextAutonomous:
    """autonomous 模式（spec 2026-09-19）：merged 热榜池为主池，bundle 只供 snapshotContext。"""

    def _make_providers(self, startup_rows, merged_rows, startup_context=None, merged_raises=False):
        startup = StartupBundleStockProvider(base_url=PROXY_BASE_URL)
        startup.snapshot_context = startup_context if startup_context is not None else {"breathData": {"k": "v"}}
        startup_rows = startup_rows if startup_rows is not None else [
            {"code": "600000", "name": "浦发银行", "rank": 2},
        ]
        merged = ProxyMergedHotlistProvider(base_url=PROXY_BASE_URL)
        merged_health = SourceHealth(
            source="merged_hotlist_proxy",
            ok=True,
            row_count=len(merged_rows),
            details={"rankProvenance": {"platformTotals": {"eastmoney": len(merged_rows)}, "platformWeights": {}}},
        )
        self.merged_health = merged_health
        if merged_raises:
            def merged_collect(*args, **kwargs):
                raise RuntimeError("all platforms failed")
            merged.collect = merged_collect
        else:
            merged.collect = lambda *args, **kwargs: (merged_rows, merged_health)
        startup.collect = lambda *args, **kwargs: (startup_rows, SourceHealth(source="startup_bundle", ok=True, row_count=len(startup_rows)))
        tencent = TencentBasicQuoteProvider(base_url=PROXY_BASE_URL)
        return startup, merged, tencent

    def test_merged_is_primary_pool_and_rows_marked_autonomous(self) -> None:
        startup, merged, _ = self._make_providers(
            startup_rows=[{"code": "600000", "name": "浦发银行", "rank": 2}],
            merged_rows=[{"code": "000001", "name": "平安银行", "rank": 1}],
        )

        ctx = collect_market_context([startup, merged], [], timeout_ms=5000, pool_source_mode="autonomous")

        assert [row["code"] for row in ctx.stocks] == ["000001"]
        assert ctx.stocks[0]["poolSource"] == "autonomous"

    def test_bundle_rows_do_not_enter_pool_but_supply_snapshot_context(self) -> None:
        context = {"breathData": {"up": 1}, "marketData": {"index": 3000}}
        startup, merged, _ = self._make_providers(
            startup_rows=[{"code": "600000", "name": "浦发银行", "rank": 2}],
            merged_rows=[{"code": "000001", "name": "平安银行", "rank": 1}],
            startup_context=context,
        )

        ctx = collect_market_context([startup, merged], [], timeout_ms=5000, pool_source_mode="autonomous")

        assert all(row["code"] != "600000" for row in ctx.stocks)
        assert ctx.snapshot_context == context

    def test_merged_failure_falls_back_to_bundle_rows_marked_bundle_fallback(self) -> None:
        startup, merged, _ = self._make_providers(
            startup_rows=[{"code": "600000", "name": "浦发银行", "rank": 2}],
            merged_rows=[],
            merged_raises=True,
        )

        ctx = collect_market_context([startup, merged], [], timeout_ms=5000, pool_source_mode="autonomous")

        assert [row["code"] for row in ctx.stocks] == ["600000"]
        assert ctx.stocks[0]["poolSource"] == "bundle_fallback"

    def test_quotes_request_autonomous_pool_codes(self) -> None:
        startup, merged, tencent = self._make_providers(
            startup_rows=[{"code": "600000", "name": "浦发银行", "rank": 2}],
            merged_rows=[{"code": "000001", "name": "平安银行", "rank": 1}],
        )
        tencent.collect = lambda codes, **kwargs: (
            {"000001": {"code": "000001", "volumeRatio": 1.8}},
            SourceHealth("theme_quote_tencent", True, row_count=1),
        )

        ctx = collect_market_context([startup, merged, tencent], [], timeout_ms=5000, pool_source_mode="autonomous")

        assert ctx.quotes == [{"code": "000001", "volumeRatio": 1.8}]

    def test_pool_composition_in_merged_health_details(self) -> None:
        startup, merged, _ = self._make_providers(
            startup_rows=[{"code": "600000", "name": "浦发银行", "rank": 2}],
            merged_rows=[{"code": "000001", "name": "平安银行", "rank": 1}],
        )

        ctx = collect_market_context([startup, merged], [], timeout_ms=5000, pool_source_mode="autonomous")

        merged_health = next(h for h in ctx.source_health if h.source == "merged_hotlist_proxy")
        composition = merged_health.details["poolComposition"]
        assert composition["mode"] == "autonomous"
        assert composition["poolSize"] == 1
        assert composition["platformTotals"] == {"eastmoney": 1}
        assert "rankProvenance" in merged_health.details

    def test_bundle_first_mode_keeps_legacy_behavior(self) -> None:
        startup, merged, _ = self._make_providers(
            startup_rows=[{"code": "600000", "name": "浦发银行", "rank": 2}],
            merged_rows=[{"code": "000001", "name": "平安银行", "rank": 1}],
        )

        ctx = collect_market_context([startup, merged], [], timeout_ms=5000, pool_source_mode="bundle_first")

        # 旧行为：bundle 为主池，merged 被 skip，无 poolSource 标记
        assert [row["code"] for row in ctx.stocks] == ["600000"]
        assert "poolSource" not in ctx.stocks[0]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd quant-board && .\.venv\Scripts\python.exe -m pytest tests/test_snapshot_collector_providers.py::TestCollectMarketContextAutonomous -v`
Expected: FAIL（`collect_market_context() got an unexpected keyword argument 'pool_source_mode'`）

- [ ] **Step 3: 实现**

`quant-board/backend/snapshot_collector/providers.py`：

3a. 模块常量区（`_HOTLIST_WEIGHTS` 之后）新增：

```python
# 采集池来源模式（2026-09-20 spec：docs/superpowers/specs/2026-09-19-snapshot-pool-autonomous-source-design.md）
# autonomous = 八平台热榜实时合并池为主池（bundle 只供 snapshotContext，merged 全挂时 bundle 行兜底）；
# bundle_first = 旧行为（bundle 为主池，merged/单平台热榜仅 fallback）。
POOL_SOURCE_MODES = ("autonomous", "bundle_first")
_POOL_SOURCE_AUTONOMOUS = "autonomous"
_POOL_SOURCE_BUNDLE_FALLBACK = "bundle_fallback"


def _normalize_pool_source_mode(value: Any) -> str:
    mode = str(value or "").strip()
    return mode if mode in POOL_SOURCE_MODES else "autonomous"


def _mark_pool_source(rows: list[dict[str, Any]], source: str) -> None:
    for row in rows:
        if isinstance(row, dict):
            row["poolSource"] = source


def _codes_of(rows: list[dict[str, Any]]) -> list[str]:
    return [
        str(row.get("code") or "").strip()
        for row in rows
        if isinstance(row, dict) and str(row.get("code") or "").strip()
    ]


def _append_pool_composition(health: Any, *, mode: str, pool_size: int) -> None:
    composition = {
        "poolComposition": {
            "mode": mode,
            "poolSize": pool_size,
            "failedPlatforms": list(health.failed_batches or []),
            "platformTotals": (health.details or {}).get("rankProvenance", {}).get("platformTotals", {}),
        }
    }
    if isinstance(health.details, dict):
        health.details.update(composition)
```

3b. `collect_market_context` 签名与开头改为（新增 `pool_source_mode` 参数，默认 `autonomous`）：

```python
def collect_market_context(
    providers: list[Any],
    codes: list[str],
    *,
    timeout_ms: int = _DEFAULT_TIMEOUT_MS,
    pool_source_mode: str = "autonomous",
) -> MarketDataContext:
```

docstring 的 Provider routing 段落同步改写为：

```
    Provider routing（pool_source_mode）
    -----------------------------------
    * ``autonomous``（默认）: ``ProxyMergedHotlistProvider`` 为主池来源；
      ``StartupBundleStockProvider`` 只供 ``snapshot_context``（其 stocks 不入池），
      merged 全挂时 bundle 行兜底（``poolSource=bundle_fallback``）。
      ``ProxyHotlistProvider``（单平台诊断源）不入池。
    * ``bundle_first``（回退）: 旧行为——bundle 为主池，merged/单平台热榜仅 fallback。
    * ``TencentBasicQuoteProvider`` → ``ctx.quotes``；``BridgeQuoteProvider`` → quotes/depth/market_meta；
      ``ThemeMappingProvider`` → ``ctx.themes``；``ProxyLimitUpProvider`` → ``ctx.limit_up``
```

3c. 函数体开头加一行规范化，替换前两个 provider 分支（`ctx = MarketDataContext()` 与 `active_codes = [...]` 之后）：

```python
    mode = _normalize_pool_source_mode(pool_source_mode)
```

```python
    bundle_fallback_rows: list[dict[str, Any]] = []
    for provider in providers:
        try:
            if isinstance(provider, StartupBundleStockProvider):
                rows, health = provider.collect(timeout_ms=timeout_ms)
                ctx.source_health.append(health)
                if mode == "bundle_first":
                    if rows:
                        ctx.stocks = rows
                        ctx.snapshot_context = dict(provider.snapshot_context)
                        active_codes = _codes_of(rows)
                else:
                    # autonomous：bundle 只供 context；rows 留作 merged 全挂时的兜底池
                    if provider.snapshot_context:
                        ctx.snapshot_context = dict(provider.snapshot_context)
                    bundle_fallback_rows = [row for row in rows if isinstance(row, dict)]

            elif isinstance(provider, ProxyMergedHotlistProvider):
                if ctx.stocks:
                    continue
                rows, health = provider.collect(timeout_ms=timeout_ms)
                ctx.source_health.append(health)
                if mode == "bundle_first":
                    if not ctx.stocks:
                        ctx.stocks.extend(rows)
                        if not active_codes:
                            active_codes = _codes_of(rows)
                elif rows:
                    _mark_pool_source(rows, _POOL_SOURCE_AUTONOMOUS)
                    ctx.stocks = rows
                    active_codes = _codes_of(rows)
                elif bundle_fallback_rows:
                    # 全平台失败但有 bundle 行：fail-visible 兜底（不构成丢帧）
                    _mark_pool_source(bundle_fallback_rows, _POOL_SOURCE_BUNDLE_FALLBACK)
                    ctx.stocks = bundle_fallback_rows
                    active_codes = _codes_of(bundle_fallback_rows)
                _append_pool_composition(health, mode=mode, pool_size=len(ctx.stocks))

            elif isinstance(provider, ProxyHotlistProvider):
                # 单平台诊断源：仅 bundle_first 且池为空时沿用旧行为；autonomous 不入池
                if mode == "autonomous" or ctx.stocks:
                    continue
                rows, health = provider.collect(timeout_ms=timeout_ms)
                ctx.stocks.extend(rows)
                ctx.source_health.append(health)
                if not active_codes:
                    active_codes = _codes_of(rows)
```

其余分支（Tencent/Bridge/Fund/Theme/LimitUp）与结尾 `_append_quote_coverage_warning(ctx, active_codes)` 不变。

- [ ] **Step 4: 更新现有用例守护回退路径**

`TestCollectMarketContext` 中以下用例在 `collect_market_context(...)` 调用中追加实参 `pool_source_mode="bundle_first"`（保持验证旧行为，成为回退路径守护测试）：
`test_assembles_stocks_from_hotlist_provider`、`test_merges_bounded_tencent_quotes_after_stock_codes_are_known`、`test_assembles_quotes_from_bridge_provider`、`test_assembles_depth_from_bridge_provider`、`test_assembles_themes_from_theme_provider`、`test_aggregates_source_health` 及该类中其余断言 `ctx.stocks` 依赖 bundle/hotlist 供池的用例（逐个核对：凡用例内未 mock merged provider 且依赖 startup/hotlist 行入池的，都要加）。

Run: `cd quant-board && .\.venv\Scripts\python.exe -m pytest tests/test_snapshot_collector_providers.py -v`
Expected: PASS（新旧全部用例）

- [ ] **Step 5: 提交**

```bash
git add quant-board/backend/snapshot_collector/providers.py quant-board/tests/test_snapshot_collector_providers.py
git commit -m "feat(collector): autonomous 采集池路由——merged 热榜为主池 + bundle 兜底 + provenance"
```

---

### Task 3: async 变体同步

**Files:**
- Modify: `quant-board/backend/snapshot_collector/providers.py`（`collect_market_context_async` 1966 起）
- Test: `quant-board/tests/test_snapshot_collector_async_pipeline.py`

- [ ] **Step 1: 写失败测试**

在 `quant-board/tests/test_snapshot_collector_async_pipeline.py` 末尾追加（文件顶部已导入 `collect_market_context_async`；`_merged_provider`/`FakeHotlistService` 为该文件既有 helper，`MarketDataContext`/`SourceHealth` 在用例内局部导入的模式沿用）：

```python
def test_collect_market_context_async_autonomous_merged_is_primary() -> None:
    from backend.snapshot_collector.models import SourceHealth
    from backend.snapshot_collector.providers import (
        ProxyMergedHotlistProvider,
        StartupBundleStockProvider,
    )

    startup = StartupBundleStockProvider(base_url="http://127.0.0.1:3000")
    startup.snapshot_context = {"breathData": {"k": "v"}}
    startup_rows = [{"code": "600000", "name": "浦发银行", "rank": 2}]
    merged_rows = [{"code": "000001", "name": "平安银行", "rank": 1}]
    startup.collect = lambda *args, **kwargs: (
        startup_rows,
        SourceHealth(source="startup_bundle", ok=True, row_count=len(startup_rows)),
    )
    merged = ProxyMergedHotlistProvider(base_url="http://127.0.0.1:3000")
    merged_health = SourceHealth(source="merged_hotlist_proxy", ok=True, row_count=1)
    merged.acollect = lambda **kwargs: _async((merged_rows, merged_health))

    ctx = asyncio.run(
        collect_market_context_async(
            [startup, merged],
            [],
            timeout_ms=5000,
            pool_source_mode="autonomous",
        )
    )

    assert [row["code"] for row in ctx.stocks] == ["000001"]
    assert ctx.stocks[0]["poolSource"] == "autonomous"
    assert ctx.snapshot_context == {"breathData": {"k": "v"}}


def _async(value: Any):
    async def _inner():
        return value

    return _inner()
```

（若文件顶部无 `from typing import Any` 则补充导入。）

- [ ] **Step 2: 运行测试确认失败**

Run: `cd quant-board && .\.venv\Scripts\python.exe -m pytest tests/test_snapshot_collector_async_pipeline.py::test_collect_market_context_async_autonomous_merged_is_primary -v`
Expected: FAIL（unexpected keyword argument `pool_source_mode`）

- [ ] **Step 3: 实现**

`collect_market_context_async` 签名加 `pool_source_mode: str = "autonomous"`（keyword-only，与同步版一致）；函数体开头 `mode = _normalize_pool_source_mode(pool_source_mode)`；把 StartupBundle 与 merged 两个分支改为与 Task 2 Step 3c 完全相同的 autonomous/bundle_first 逻辑（`provider.acollect` 代替 `provider.collect`，其余逐字一致）：

```python
async def collect_market_context_async(
    providers: list[Any],
    codes: list[str],
    *,
    timeout_ms: int = _DEFAULT_TIMEOUT_MS,
    pool_source_mode: str = "autonomous",
) -> MarketDataContext:
```

```python
    bundle_fallback_rows: list[dict[str, Any]] = []
    for provider in providers:
        try:
            if isinstance(provider, StartupBundleStockProvider):
                rows, health = await provider.acollect(timeout_ms=timeout_ms)
                ctx.source_health.append(health)
                if mode == "bundle_first":
                    if rows:
                        ctx.stocks = rows
                        ctx.snapshot_context = dict(provider.snapshot_context)
                        active_codes = _codes_of(rows)
                else:
                    if provider.snapshot_context:
                        ctx.snapshot_context = dict(provider.snapshot_context)
                    bundle_fallback_rows = [row for row in rows if isinstance(row, dict)]

            elif isinstance(provider, ProxyMergedHotlistProvider):
                if ctx.stocks:
                    continue
                rows, health = await provider.acollect(timeout_ms=timeout_ms)
                ctx.source_health.append(health)
                if mode == "bundle_first":
                    if not ctx.stocks:
                        ctx.stocks.extend(rows)
                        if not active_codes:
                            active_codes = _codes_of(rows)
                elif rows:
                    _mark_pool_source(rows, _POOL_SOURCE_AUTONOMOUS)
                    ctx.stocks = rows
                    active_codes = _codes_of(rows)
                elif bundle_fallback_rows:
                    _mark_pool_source(bundle_fallback_rows, _POOL_SOURCE_BUNDLE_FALLBACK)
                    ctx.stocks = bundle_fallback_rows
                    active_codes = _codes_of(bundle_fallback_rows)
                _append_pool_composition(health, mode=mode, pool_size=len(ctx.stocks))

            elif isinstance(provider, ProxyHotlistProvider):
                if mode == "autonomous" or ctx.stocks:
                    continue
                rows, health = await provider.acollect(timeout_ms=timeout_ms)
                ctx.stocks.extend(rows)
                ctx.source_health.append(health)
                if not active_codes:
                    active_codes = _codes_of(rows)
```

其余分支不变。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd quant-board && .\.venv\Scripts\python.exe -m pytest tests/test_snapshot_collector_async_pipeline.py tests/test_snapshot_collector_providers.py -v`
Expected: PASS（含现有 `test_collect_market_context_async_orchestrates`——单 merged provider 在 autonomous 下行为与旧断言一致：merged 行入池）

- [ ] **Step 5: 提交**

```bash
git add quant-board/backend/snapshot_collector/providers.py quant-board/tests/test_snapshot_collector_async_pipeline.py
git commit -m "feat(collector): async 采集路由同步 autonomous 模式"
```

---

### Task 4: service 读取 mode + snapshot_context_missing 打标

**Files:**
- Modify: `quant-board/backend/snapshot_collector/service.py`（`_collect_context` 284-303；`_settings_or_default` 辅助区约 943 行；`_persist_one` quality 生成后约 451 行）
- Test: `quant-board/tests/test_snapshot_collector_async_pipeline.py`

- [ ] **Step 1: 写失败测试**

`test_snapshot_collector_async_pipeline.py` 的 `test_arun_once_multi_collects_once_derives_per_type` 中，`ctx` 构造不含 `snapshot_context`（默认空 dict）——在该测试末尾追加断言（dry_run 结果的 warnings 已带标记）：

```python
    assert any(
        "snapshot_context_missing" in warning
        for result in results
        for warning in (result.quality.warnings or [])
    )
```

并在其后新增真实链路传参用例。注意：`_collect_context` 的真实链路判断锚点是**同步版**函数（`self._collect_fn is providers_module.collect_market_context`，service.py:292），分支内实际调用的是 `collect_market_context_async`（service.py:293）——monkeypatch 需同时替换两个模块属性为同一 fake_route（判断锚点 + 调用点），断言 fake_route 收到 settings 的 mode：

```python
def test_collect_context_passes_pool_source_mode_to_real_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """真实链路（collect_fn is collect_market_context）必须把 settings 的 mode 传给 async 路由。"""
    from backend.snapshot_collector import providers as providers_module
    from backend.snapshot_collector.models import MarketDataContext
    from backend.snapshot_collector.service import SnapshotCollectorService

    captured: dict[str, Any] = {}

    async def fake_route(
        providers_list: list[Any],
        codes: list[str],
        *,
        timeout_ms: int | None = None,
        pool_source_mode: str = "autonomous",
    ) -> MarketDataContext:
        captured["mode"] = pool_source_mode
        return MarketDataContext()

    # 判断锚点（service.py:292 is 判断）与调用点（service.py:293）都指向 fake_route
    monkeypatch.setattr(providers_module, "collect_market_context", fake_route)
    monkeypatch.setattr(providers_module, "collect_market_context_async", fake_route)

    service = SnapshotCollectorService(
        FakeRepo(),
        settings=type("S", (), {"snapshot_collector_pool_source_mode": "bundle_first"})(),
        collect_fn=providers_module.collect_market_context,
        normalize_fn=lambda *a, **k: None,
        quality_fn=lambda **k: None,
        theme_heat_service=None,
    )

    ctx = asyncio.run(service._collect_context("2026-09-20"))

    assert captured["mode"] == "bundle_first"
    assert isinstance(ctx, MarketDataContext)
```

（`FakeRepo` 为该文件既有类；`_collect_context` 内部 `self._create_providers` 只构造 provider 对象不触网，`theme_heat_service=None` 时返回空 sectors，均为既有行为。）

- [ ] **Step 2: 运行测试确认失败**

Run: `cd quant-board && .\.venv\Scripts\python.exe -m pytest tests/test_snapshot_collector_async_pipeline.py -v`
Expected: FAIL（`snapshot_context_missing` 断言处 warning 缺失；传参用例因 `_collect_context` 尚未传 mode 而失败）

- [ ] **Step 3: 实现**

3a. `service.py` 辅助区（`_provider_timeout_ms` 之后）新增：

```python
    def _pool_source_mode(self) -> str:
        return providers_module._normalize_pool_source_mode(
            getattr(self._settings_or_default(), "snapshot_collector_pool_source_mode", "autonomous")
        )
```

（`providers_module` 别名已存在于 service.py:30 `from . import providers as providers_module`。）

3b. `_collect_context` 真实链路分支传参——判断锚点是同步版（service.py:292 `if self._collect_fn is providers_module.collect_market_context:`），分支内的 async 调用（service.py:293）加实参：

```python
        if self._collect_fn is providers_module.collect_market_context:
            market_context = await providers_module.collect_market_context_async(
                providers_list, codes, timeout_ms=timeout_ms,
                pool_source_mode=self._pool_source_mode(),
            )
```

（`elif inspect.iscoroutinefunction(...)` / `else` 分支不动——自定义 collect_fn 签名不变。）

3c. `_persist_one` 中 `quality = self._quality_fn(...)` 之后、`diagnostic_flags = [...]` 之前追加：

```python
        if not market_context.snapshot_context:
            # autonomous 模式下前端离线 → bundle 缺失 → snapshotContext 证据缺位：
            # fail-visible 打标，不阻断采集（spec §4 错误处理表）
            quality.warnings.append("snapshot_context_missing")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd quant-board && .\.venv\Scripts\python.exe -m pytest tests/test_snapshot_collector_async_pipeline.py tests/test_snapshot_collector_service.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add quant-board/backend/snapshot_collector/service.py quant-board/tests/test_snapshot_collector_async_pipeline.py
git commit -m "feat(collector): 采集链传参 pool_source_mode + snapshot_context_missing 打标"
```

---

### Task 5: 全量验证 + 文档同步

**Files:**
- Modify: `quant-board/docs/architecture.md`（snapshot_collector 采集池口径段落）
- Modify: `docs/superpowers/specs/2026-09-19-snapshot-pool-autonomous-source-design.md`（状态行回填）
- Modify: 本计划文件（勾选完成项）

- [ ] **Step 1: 全量后端测试**

Run: `cd quant-board && .\.venv\Scripts\python.exe -m pytest`
Expected: 全部 PASS，无 import 断裂（backend 归档硬约束：目录调整必须全量 pytest 验证）

- [ ] **Step 2: 文档同步**

`architecture.md`：在 snapshot_collector 相关段落补充一句（按该文档现有格式，找到描述采集器 provider/池的段落）：

```
采集池来源（2026-09-20）：默认 `autonomous`——每槽直连 market_proxy 热榜服务实时合并八平台全量
（`ProxyMergedHotlistProvider` 主池），行级 `poolSource` provenance；bundle 降级为只供
`snapshotContext`，自治池全挂时 bundle 行兜底（`bundle_fallback`）。回退开关
`QUANT_BOARD_SNAPSHOT_COLLECTOR_POOL_SOURCE_MODE=bundle_first`。设计与实测验收见
`docs/superpowers/specs/2026-09-19-snapshot-pool-autonomous-source-design.md`。
```

spec 状态行追加：`> 状态：设计已确认（2026-09-19）；实施完成（2026-09-20，见 quant-board/docs/snapshot-collector/2026-09-20-pool-autonomous-source-implementation-plan.md）`。

- [ ] **Step 3: 提交**

```bash
git add quant-board/docs/architecture.md docs/superpowers/specs/2026-09-19-snapshot-pool-autonomous-source-design.md quant-board/docs/snapshot-collector/2026-09-20-pool-autonomous-source-implementation-plan.md
git commit -m "docs(collector): 采集池 autonomous 口径文档同步 + spec 状态回填"
```

---

### Task 6（交付后下一交易日，人工）: 实测验收

按 spec §7 执行并记录到本计划尾部：

1. 盘中打开前端，导出/记录行情列表 codes；收盘后取 `half_hour` 最新帧 stock-rows codes，脚本比对「列表 ⊆ 帧池」。
2. 面板「全池状态结构」与列表对账，确认不再出现「列表有、快照无」方向差异。
3. 采集 run 审计（`snapshot_collector_runs`）核对 `poolComposition.poolSize` 相比 bundle 时代 +10~15%、analyze 耗时在预算内。
4. 盘后重载页面复验 1/2（时点差最大场景）。
5. 设置 `QUANT_BOARD_SNAPSHOT_COLLECTOR_POOL_SOURCE_MODE=bundle_first` 重启采集进程，确认回退路径生效后改回 `autonomous`。
