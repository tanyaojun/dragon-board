# THS Incremental Fund Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use `test-driven-development` for every behavior change and `verification-before-completion` before reporting success. Execute in the current dirty workspace; do not create a worktree, revert unrelated changes, or commit unless the user asks.

**Goal:** Restore THS `mainMonitorDetail` as the only dashboard fund source, serve Redis last-good immediately, and continuously refresh the actual market-list universe in bounded P0/P1 batches.

**Architecture:** A QuantBoard THS service owns the single-code request, validation, amount parsing and bounded five-code loader. FastAPI exposes compatible single-code and batch routes for tools and diagnostics, while the lifecycle scheduler calls the service directly, writes one Redis last-good record per code, and publishes the same versioned row to the existing local fund WebSocket. The market list and theme analyzer only consume that cache; `python-bridge` remains the price/volume WebSocket and is removed from the fund path.

**Tech Stack:** Python/FastAPI/httpx/asyncio/Redis, Vue 3/TypeScript/Vitest, .NET, pytest, Playwright CLI.

---

## Success Contract

- Fund source is exactly `ths_main_monitor`; `/api/quotes/eastmoney` is absent and `tdx_transaction` cannot populate dashboard funds.
- Missing rows stay absent and render `--`; failures retain last-good and never write `0`.
- FastAPI batch accepts at most five codes and returns successes plus failures independently; no batch-wide deadline cancels usable rows.
- QuantBoard restores P1 owner codes from Redis; a cold empty Redis waits for the first real Dragon Board `marketCodes` registration, persists it, and keeps P1 refreshing after browser disconnect.
- P0 target interval is 30 seconds, P1 is 180 seconds; two P0 batches must yield to one due P1 batch.
- Non-trading time is decided only through the bridge TDX calendar. A cold non-trading cache is filled once from THS's latest `sessionDate`, then stops continuous polling.
- Market list and theme panel use the same `code + version + zlje` record. Theme mapping's 4,000+ codes never become the default fund queue.
- `tools/THSBigOrder` uses FastAPI as its THS single-code primary and python-bridge/mootdx as its minute source. Tencent minute direct/proxy paths are removed; other legacy proxy sources remain unchanged. QuantBoard formal backtests do not consume this runtime cache.

## File Map

- FastAPI adapter: new `quant-board/backend/ths_main_monitor_service.py`, new `quant-board/backend/api/ths_main_monitor_routes.py`, `quant-board/backend/main.py`. The service stays at backend root because existing `backend/services.py` owns that import name.
- Adapter tests: new `quant-board/tests/test_ths_main_monitor_service.py`, new `quant-board/tests/test_ths_main_monitor_routes.py`.
- Cache and scheduler: `quant-board/backend/theme_fund_cache.py`, `quant-board/backend/theme_fund_stream.py`, new `quant-board/backend/theme_fund_scheduler.py`, `quant-board/backend/settings.py`, `quant-board/backend/main.py`.
- Backend contracts: `quant-board/backend/api/theme_heat_routes.py`, `quant-board/backend/theme_heat_service.py`, `quant-board/backend/snapshot_collector/providers.py`, `quant-board/backend/snapshot_collector/service.py`.
- Backend tests: `quant-board/tests/test_theme_fund_cache.py`, `quant-board/tests/test_theme_fund_stream.py`, new `quant-board/tests/test_theme_fund_scheduler.py`, new `quant-board/tests/test_theme_fund_lifecycle.py`, plus affected theme/snapshot tests.
- Frontend consumer: `src/services/themeFundStream.ts`, `src/services/realtime/RealtimeSubscriptionRegistry.ts`, `src/services/dataLoader/RealtimeQuoteCoordinator.ts`, `src/services/moneyFlowSourcePriority.ts`, `src/services/theme/ThemeHeatFeed.ts`, `src/components/common/DataTable.vue`, `src/App.vue`, affected theme stock panels and adjacent tests.
- Failed bridge path removal: `python-bridge/main.py`, `python-bridge/l2/provider.py`, `python-bridge/test_quote_snapshot_api.py`; delete only obsolete `python-bridge/big_order_calculator.py` and `python-bridge/test_big_order_calculator.py` after confirming no remaining imports.
- Tool migration: `tools/THSBigOrder/THSBigOrderDataProvider.cs`, `tools/THSBigOrder/DataSources/ThsBigOrderSourceClient.cs`, replace `TencentMinuteSourceClient.cs` with a bridge minute client, parser naming/contracts, and adjacent `tools/THSBigOrder.Tests/**` tests. Split legacy proxy `3000`, THS FastAPI `8000`, and mootdx bridge `8765` bases.
- Proxy cleanup: `proxy-server/routes/bigOrder.js`, the single Tencent minute handler in `proxy-server/routes/quotes.js`, `proxy-server/helpers/proxyCache.js`, `proxy-server/openapi.js`, `proxy-server/server.js`, `proxy-server/__tests__/thsBigOrder.test.mjs`, `proxy-server/__tests__/tencentMinute.test.mjs`, `proxy-server/__tests__/docs.test.mjs`; rewrite the Tencent minute test as a removed-route regression and retain Tencent batch quotes and unrelated routes.
- Bridge minute correction: `python-bridge/main.py`, `python-bridge/test_quote_snapshot_api.py`; remove the proxy Tencent minute route only after no tool consumer remains.
- Documentation: this design/plan and `quant-board/docs/api-cli.md`.

### Task 1: Add the bounded QuantBoard THS service and FastAPI contracts

**RED**

- Add service and route tests to require:
  - `GET /api/big-order/ths-detail?stockCode=002297` retains the tool-compatible raw THS envelope and authoritative `sessionDate`.
  - fresh, cache-hit and upstream-failed stale responses preserve `fetchedAt`, `servedAt` and `data.dragonMeta.cache.uiStale` without reading dashboard `theme-fund:v3` rows.
  - `GET /api/big-order/ths-fund-batch?codes=000001,600000` parses `title.mainbuy - title.mainsell` into yuan and preserves THS `sessionDate`.
  - More than five unique codes returns HTTP 400.
  - Malformed amounts or missing `sessionDate` produces a failure item, not `zlje=0`.
  - One upstream rejection still returns the other successful row.
  - HTTP 429/验证码/超时/不可用/非法 payload 分别返回 `ths_rate_limited`、`ths_captcha_required`、`ths_timeout`、`ths_upstream_unavailable`、`ths_invalid_payload`。
  - Requested concurrency is clamped to `1..2`.
  - scheduler and concurrent HTTP calls share one process-wide semaphore; global cooldown prevents all entry points from starting an upstream request.

Run: `cd quant-board; .\.venv\Scripts\python.exe -m pytest tests/test_ths_main_monitor_service.py tests/test_ths_main_monitor_routes.py -q`

Expected RED: the service and routes do not exist.

**GREEN**

- Add `ThsMainMonitorService` with one shared single-code request/validation path and a bounded batch loader.
- Put the raw payload last-good and shared request gate in the service. The scheduler may lower/restore the effective concurrency, but every HTTP and direct scheduler call must obey that same state.
- Add a nullable Chinese amount parser supporting plain yuan, `元`, `万`, `亿`, commas and signed values; reject non-finite values.
- Add FastAPI single-code and five-code routes. Return per-code rows and failures from the batch route:

```json
{
  "ok": true,
  "source": "ths_main_monitor",
  "data": {
    "rows": [{ "code": "000001", "zlje": 1230000, "sessionDate": "2026-07-24", "sourceTs": 0 }],
    "failures": [{ "code": "600000", "errorCode": "ths_timeout" }]
  }
}
```

- Do not add `/api/quotes/eastmoney` or restore the old all-market `/api/quotes/ths-money-flow` behavior.
- Register the router in `quant-board/backend/main.py`; FastAPI-generated OpenAPI is the contract source.
- The scheduler must depend on the service object directly. Do not add localhost HTTP calls from QuantBoard to port 8000.

Run the same QuantBoard pytest command and confirm both service and HTTP contracts pass.

### Task 2: Replace the TDX cache contract with THS last-good

**RED**

- Rewrite `quant-board/tests/test_theme_fund_cache.py` around `ths_main_monitor` and require:
  - finite `zlje` plus `sessionDate` is mandatory;
  - an older `sessionDate` or `sourceTs` cannot overwrite last-good;
  - a failed/malformed candidate leaves the previous row unchanged;
  - latest rows remain readable on a later non-trading date without an `isFinal` prerequisite;
  - Redis failure keeps process-memory last-good;
  - the new namespace does not read `theme-fund:v2` TDX rows;
  - owner code sets round-trip through Redis.

Run: `cd quant-board; .\.venv\Scripts\python.exe -m pytest tests/test_theme_fund_cache.py -q`

Expected RED: current cache rejects THS and requires TDX/final rows.

**GREEN**

- Change the cache namespace to `theme-fund:v3`.
- Store canonical fields `code`, `zlje`, `sessionDate`, `tradingDate`, `source`, `moneyFlowSource`, `sourceTs`, `updatedAt`, `version`.
- Keep schedule state separate from last-good; failed refreshes must not call `put()`.
- Add `set_owner_codes(owner, codes)` and `get_owner_codes()` using Redis JSON values plus memory fallback.

Run the same pytest command and confirm all cache tests pass.

### Task 3: Convert the backend fund stream into a cache broadcaster

**RED**

- Rewrite `quant-board/tests/test_theme_fund_stream.py` to require:
- a subscriber receives an immediate full state from cache;
- published THS rows are filtered to that subscriber's `marketCodes ∪ priorityCodes`;
- a theme-only P0 code absent from `marketCodes` still receives full state and patches but is not persisted into the P1 owner;
  - priority codes are removed on disconnect but persisted owner market codes remain P1;
  - the stream has no bridge URL, bridge message parser or `set_money_flow_pool` message.

Run: `cd quant-board; .\.venv\Scripts\python.exe -m pytest tests/test_theme_fund_stream.py -q`

**GREEN**

- Reduce `theme_fund_stream.py` to subscriber registration, owner/P0 aggregation, snapshot creation and `publish(rows)`.
- Update `/api/themes/fund-stream` to accept:

```json
{ "type": "subscribe", "marketCodes": ["000001"], "priorityCodes": ["000001"] }
```

- Persist `marketCodes` as the Dragon Board runtime owner; treat `priorityCodes` as connection-scoped P0 only.
- Keep `GET /api/themes/fund-rows` as a cache-only diagnostic read.

### Task 4: Implement the lifecycle THS scheduler

**RED**

- Create `quant-board/tests/test_theme_fund_scheduler.py` with deterministic fake clock/calendar/client tests for:
  - missing P0 before missing P1, then due-time ordering;
  - two P0 batches followed by one due P1 batch;
  - success writes cache and publishes immediately;
  - partial failure preserves successful rows and applies per-code `30/60/120/300` second backoff;
  - `ths_rate_limited`、`ths_captcha_required` 或同批全部 `ths_upstream_unavailable` 暂停 30 秒并降并发为 1；连续 3 个全成功批次后恢复 2；
  - first round completion schedules P0 at 30 seconds and P1 at 180 seconds instead of stopping;
  - non-trading warm cache makes no THS request;
  - Redis owner 为空时不请求 THS、不读取 proxy startup bundle；首个实际 `marketCodes` 注册后才建立队列并在非交易日冷补齐一次；
  - non-trading cold cache fills each missing owner once and does not continuously poll;
  - unavailable TDX calendar makes no upstream request and retains cache.
  - a 4,000-code theme mapping payload cannot enter Redis owner or the scheduler due queue unless codes are explicitly submitted by an actual market/P0 owner.

Run: `cd quant-board; .\.venv\Scripts\python.exe -m pytest tests/test_theme_fund_scheduler.py -q`

Expected RED: scheduler module is missing.

**GREEN**

- Add `theme_fund_scheduler.py` with one asyncio lifecycle task and one in-memory due-state record per owner code.
- Use `snapshot_collector.trading_calendar.is_trading_day()` only; session time checks may use Shanghai clock but must not infer weekends/holidays.
- Load owners from Redis immediately. If empty, stay idle until the first real Dragon Board `marketCodes` message persists the owner set; never derive it from theme mapping or a proxy startup bundle.
- Call `ThsMainMonitorService.load_batch()` with at most five codes. Never wait for a whole-universe collection and never call FastAPI through localhost HTTP.
- Publish each successful batch after Redis writes; leave failures absent or last-good.

Run the scheduler, cache and stream test files together.

### Task 5: Wire lifecycle, settings and backend consumers

**RED**

- Add `test_theme_fund_lifecycle.py` to require FastAPI startup starts the scheduler exactly once and shutdown awaits stop exactly once.
- Add a theme heat test proving only existing cached rows are aggregated and uncovered mapping stocks are not treated as zero.
- Add snapshot tests proving `ThemeFundCacheProvider` is no longer installed, bridge money fields are ignored, and formal stock rows do not contain `ths_main_monitor`.

**GREEN**

- Replace bridge stream settings with scheduler settings: enabled, batch size `5`, P0 `30`, P1 `180`, THS concurrency `2`, owner refresh interval, upstream timeout and THS upstream URL. Do not add a proxy URL or localhost FastAPI URL to the scheduler.
- Start/stop the scheduler in FastAPI lifecycle; the broadcaster itself has no background task.
- Change theme heat fund health/source metadata to `ths_main_monitor`; snapshot source metadata must not claim this runtime source.
- Keep theme heat's 4,000+ mapping universe only for theme attribution and aggregation; never write it to Redis owner or the scheduler due queue.
- Remove `ThemeFundCacheProvider` from snapshot collector assembly. Remove `tdx_transaction` metadata and do not add runtime THS cache to formal snapshots or backtest quality contracts.

Run:

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_theme_fund_cache.py tests/test_theme_fund_stream.py tests/test_theme_fund_scheduler.py tests/test_theme_fund_lifecycle.py tests/test_theme_heat_service.py tests/test_theme_heat_engine.py tests/test_snapshot_collector_providers.py tests/test_snapshot_collector_service.py tests/test_snapshot_collector_builder.py -q
```

### Task 6: Make the frontend send P1/P0 separately and accept only THS

**RED**

- Extend `quant-board/tests/test_theme_heat_service.py` to require one initial quote fetch, no additional quote-provider call when only fund version changes while fund aggregation updates, and a new quote fetch only after quote cache expiry or explicit force.

- Update adjacent Vitest tests to require:
  - registry sends all realtime market codes as `marketCodes` and explicit fund owners as `priorityCodes`;
  - `DataTable.vue` 当前滚动可见行、`App.vue` 主搜索结果、题材股票当前分页/搜索结果分别注册和清理 P0 owner；
  - the fund WebSocket accepts `ths_main_monitor`, rejects TDX and rejects lower per-code versions;
  - a replacement full-state cannot roll a code back to a lower version;
  - realtime quote projection maps THS `zlje` into DataLayer but bridge quote/tick messages cannot populate it;
  - missing money flow remains `undefined/null`, never zero;
  - 同一 fund patch 立即更新已缓存题材股票行，并在一次 debounce 后只重算资金聚合，不重新请求全市场腾讯行情。

Run:

```powershell
pnpm exec vitest run src/services/realtime/__tests__/RealtimeSubscriptionRegistry.test.ts src/services/__tests__/themeFundStream.test.ts src/services/__tests__/moneyFlowSourcePriority.test.ts src/services/dataLoader/__tests__/RealtimeQuoteCoordinator.test.ts src/services/theme/__tests__/ThemeHeatFeed.test.ts src/components/common/__tests__/DataTable.test.ts src/components/panels/__tests__/ThemePanelsDataContract.test.ts
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_theme_heat_service.py -q
```

**GREEN**

- Change `RealtimeSubscriptionRegistry.applyFunds` to receive separate market and priority lists.
- Use top-ranked rows only as a startup seed. `DataTable.vue` must calculate visible row codes from the scroll container and clear them on unmount; `App.vue` must register/clear main search result codes; theme stock panels must register current paginated/search result codes and clear them on close.
- Send the new WebSocket subscription shape from `themeFundStream.ts` and accept only `ths_main_monitor` rows.
- Remove tick accumulation and `tdx_transaction` money-flow projection from `RealtimeQuoteCoordinator`; keep price/depth/tick display responsibilities intact.
- Make source priority treat THS as the sole dashboard fund source. Do not show `资金数据降级`.
- On fund patch, update `ThemeHeatFeed.stockCache` rows by `code + version` immediately and debounce one theme refresh. Backend theme refresh must reuse the last quote snapshot when only fund version changes, so five-code patches do not refetch 4,000 Tencent quotes.

### Task 7: Remove the abandoned python-bridge fund path

**RED / CONTRACT CHECK**

- Update bridge tests so full state and patches contain quotes/depth/ticks only, no calculated dashboard money-flow contract.
- Confirm `/api/calendar` remains and still returns structured unavailable status without guessing.

**GREEN**

- Remove imports, pools, tasks and message fields introduced for `big_order_calculator` from `python-bridge/main.py` and `python-bridge/l2/provider.py`.
- Delete only `python-bridge/big_order_calculator.py` and `python-bridge/test_big_order_calculator.py` after `rg` shows no remaining imports.
- Preserve all mootdx calendar work and normal quote WebSocket behavior.

Run: `python -m unittest discover python-bridge -p "test_*.py"`

### Task 8: Correct mootdx minute data and migrate THSBigOrder sources

**RED**

- Add bridge tests proving `/api/quotes/minute` uses `Quotes.minutes(symbol, authoritativeDate)` under the shared `fetch_lock`: trading-session requests use today and allow 1..240 ordered points; after close/non-trading requests use the latest completed trading date and mark completeness without inventing missing points; malformed/negative rows are rejected; volume stays in lots and yuan amount uses `×100`. A concurrency test must prove minute and quote fetches cannot enter the TDX client together.
- Update `tools/THSBigOrder.Tests/**` to require the THS primary URI to use `http://127.0.0.1:8000/api/big-order/ths-detail`, the minute URI to use `http://127.0.0.1:8765/api/quotes/minute`, and quote/limit-up/Longhu fallback URIs to remain on `http://127.0.0.1:3000`.
- Require no request to `web.ifzq.gtimg.cn` or `/api/quotes/tencent/minute`. Bridge minute failure must use the tool's bounded last-good or surface missing/failed data; it must not fall back to Tencent.
- Add minute last-good tests: same authoritative session date within the bound is reused; a different session date is rejected; an expired row is rejected. For a current-date session use a 5-minute bound; for a completed prior session use a 7-day safety bound. This freshness rule does not infer trading days.
- Add a success-path regression: when THS supplies authoritative session date D but bridge returns a valid HTTP payload for D-1, reject the minute response and do not cache it. A later bridge failure must not surface the rejected D-1 row as stale.
- Add deterministic `BigOrderLastGoodMaxAge` tests proving the decision uses authoritative session-date equality plus the intraday window, never `DayOfWeek`; a holiday/non-trading natural date carrying the previous completed session must take the completed-session bound.
- Add or update proxy route/docs tests to require `/api/big-order/ths-detail` and `/api/quotes/tencent/minute` to be absent after migration without removing unrelated big-order or Tencent batch quote routes.

Run:

```powershell
python -m unittest discover python-bridge -p "test_*.py"
dotnet run --project tools\THSBigOrder.Tests\THSBigOrder.Tests.csproj
cd proxy-server
node --test __tests__/thsBigOrder.test.mjs __tests__/docs.test.mjs __tests__/tencentMinute.test.mjs
```

**GREEN**

- Fix bridge `/api/quotes/minute` to select today's date only during an actual TDX-calendar trading session; otherwise use the latest completed trading date. Acquire `fetch_lock`, ensure the client inside the lock, then call public mootdx `Quotes.minutes()`. Do not use raw `client.get_minute_time_data()` or natural-day assumptions.
- Split `THSBigOrderDataProvider` constructor configuration into legacy proxy, THS FastAPI and bridge bases, defaulting to `3000`, `8000` and `8765`. Pass only the FastAPI base to `ThsBigOrderSourceClient` and only the bridge base to the renamed minute client.
- Preserve the current public-constructor THS proxy-primary behavior: FastAPI is the single runtime THS primary, not a direct-first fallback. Add tests for FastAPI fresh, FastAPI stale and FastAPI failure; direct THS loading remains only an explicit internal/test path unless separately redesigned.
- Replace Tencent minute parsing/naming with the normalized bridge minute contract and remove both Tencent direct and proxy requests.
- Change `THSBigOrderDataProvider` minute cache fallback to validate the cached points' single session date against the authoritative expected session date. Apply a 5-minute bound for current-date data and a 7-day bound for a completed prior session; otherwise return missing/failed rather than stale.
- Validate successful minute responses before caching. Convert a missing/mixed/mismatched minute date to a failed minute result, then allow fallback only from a pre-existing same-session unexpired cache.
- Change the THS big-order last-good age helper to accept the authoritative expected session date. Use the 5-minute trading-window bound only when that date equals `now.Date`; otherwise use the completed-session bound. Do not inspect `DayOfWeek`.
- Remove the old THS detail handler and Tencent minute handler, their route listings, OpenAPI paths and cache TTL from `proxy-server`; retain a removed-route regression test and keep Longhu, Tencent batch quotes, limit-up and all unrelated proxy behavior.
- Verify the FastAPI single-code route before removing the proxy route so the tool never has two divergent implementations in the final state.

Run the same bridge, .NET and proxy commands after GREEN.

### Task 9: Documentation, live verification and review

- Update `quant-board/docs/api-cli.md` with the runtime-only THS cache/source and WebSocket subscription contract; explicitly exclude it from formal backtests.
- Run `rg -n "tdx_transaction|资金数据降级|/api/quotes/eastmoney|/api/quotes/ths-money-flow"` across changed runtime files and resolve only in-scope leftovers.
- Run `rg -n "Saturday|Sunday|DayOfWeek|getDay\\(|weekday|['\"]Sat['\"]|['\"]Sun['\"]|周六|周日|周末" tools/THSBigOrder quant-board/backend/theme_fund_* python-bridge/main.py src/services/themeFundStream.ts src/utils/time.ts`; runtime hits introduced or retained by this implementation are blocking. Tests may name concrete calendar examples, but production code must consume the TDX calendar or authoritative `sessionDate`.
- Run the explicit verification commands below, then full root `pnpm test` and `vue-tsc`:

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_ths_main_monitor_service.py tests/test_ths_main_monitor_routes.py tests/test_theme_fund_cache.py tests/test_theme_fund_stream.py tests/test_theme_fund_scheduler.py tests/test_theme_fund_lifecycle.py tests/test_theme_heat_service.py tests/test_snapshot_collector_providers.py tests/test_snapshot_collector_service.py -q
cd ..
python -m unittest discover python-bridge -p "test_*.py"
dotnet run --project tools\THSBigOrder.Tests\THSBigOrder.Tests.csproj
cd proxy-server
node --test __tests__/thsBigOrder.test.mjs __tests__/docs.test.mjs __tests__/routes.test.mjs __tests__/tencentMinute.test.mjs
```
- Before restarting Redis, record a v3 fund row/version/owner, run `redis-cli -p 6379 BGSAVE`, poll `LASTSAVE` until it advances, then restart and verify the same values. Restart legacy proxy `3000`, QuantBoard `8000`, bridge `8765`, and root Vite `5173` using existing project launch methods; do not change ports. Then stop only `3000` temporarily and prove FastAPI THS single/batch routes plus scheduler Redis versions continue updating without relying on the otherwise incomplete page; finally restart `3000` and verify all four ports are listening before browser acceptance.
- Use Playwright CLI to verify initial cache display, incremental coverage, market/theme value equality, `--` for missing rows, absence of degradation text, and no fund-stream console errors.
- Observe at least one P0 repeat interval and confirm versions continue increasing after initial coverage.
- Request an agent code review of the final diff. Fix all Critical/Important findings and rerun affected verification commands.

## Rollback

- Disable only the QuantBoard THS scheduler setting; cache reads and last-good WebSocket delivery remain available.
- Do not restore Eastmoney or TDX fund fallbacks and do not clear the Redis `theme-fund:v3` namespace.
- No Git commit, push, reset, checkout or unrelated formatting is part of this plan.
