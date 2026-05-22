# Opening Weak-To-Strong Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the V3 `opening_weak_to_strong` signal across shared fixtures, desktop C#, web TypeScript, proxy cache, and Dragon Board display.

**Architecture:** Keep detection as pure TS/C# logic driven by the same JSON fixture. The proxy stores and arbitrates generated signals only; it does not sample quotes or calculate signals. UI layers consume events/signals and stay thin.

**Tech Stack:** .NET 8 WinForms console-style tests, Vue 3 + TypeScript + Vitest, Node/Express proxy tests, `mootdx` python-bridge metadata.

---

### Task 1: Shared Fixture And Pure Detectors

**Files:**
- Create: `docs/yidong-jingling/fixtures/opening-weak-to-strong-cases.json`
- Create: `src/services/hotlist/openingWeakToStrongTypes.ts`
- Create: `src/services/hotlist/OpeningWeakToStrongDetector.ts`
- Create: `src/services/hotlist/__tests__/OpeningWeakToStrongDetector.test.ts`
- Create: `tools/YiDongJingLing/Events/OpeningWeakToStrongDetector.cs`
- Modify: `tools/YiDongJingLing.Tests/Program.cs`

- [ ] Write failing TS and C# fixture tests covering `002552`, low-open red reversal, strong-open-with-precondition, missing baseline, ordinary board attempt, and after-cutoff.
- [ ] Run targeted tests and confirm failures are due to missing detector implementation.
- [ ] Implement minimal pure detector logic with `variant`, `score`, `confidence`, `factors`, `riskFlags`, and baseline quality.
- [ ] Run targeted TS/C# tests and confirm green.

### Task 2: Proxy Opening Signal Cache

**Files:**
- Create: `proxy-server/routes/openingSignals.js`
- Create: `proxy-server/__tests__/openingSignals.test.mjs`
- Modify: `proxy-server/app.js`
- Modify: `proxy-server/openapi.js`
- Modify: `proxy-server/__tests__/docs.test.mjs` if OpenAPI snapshot expectations require it.

- [ ] Write route tests for create, merge duplicate, upgrade canonical signal, query today, and voice owner arbitration.
- [ ] Run proxy route tests and confirm red.
- [ ] Implement in-memory daily cache with `canonicalSignal`, `reportsBySource`, `sources`, `firstTriggerAt`, `lastReportedAt`, and `voiceOwner`.
- [ ] Add OpenAPI entries for `POST /api/opening-signals` and `GET /api/opening-signals/today`.
- [ ] Run proxy tests and docs tests.

### Task 3: Desktop Event Chain

**Files:**
- Modify: `tools/YiDongJingLing/MarketData/TradingSession.cs`
- Create: `tools/YiDongJingLing/MarketData/OpeningAuctionStateStore.cs`
- Create: `tools/YiDongJingLing/Events/OpeningSignalReporter.cs`
- Modify: `tools/YiDongJingLing/Events/EventRecord.cs`
- Modify: `tools/YiDongJingLing/Events/EventDeduper.cs`
- Modify: `tools/YiDongJingLing/Events/EventVoicePolicy.cs`
- Modify: `tools/YiDongJingLing/MainForm.cs`
- Modify: `tools/YiDongJingLing/Settings/AppSettings.cs`
- Modify: `tools/YiDongJingLing/SettingsForm.cs`
- Modify: `tools/YiDongJingLing.Tests/Program.cs`

- [ ] Write tests for sampling windows, event priority, voice policy, dry-run suppression, and reporter payload.
- [ ] Run tests and confirm red.
- [ ] Wire `09:24:50-09:25:10` baseline capture and `09:30-09:35` detection into `HandleQuotes`.
- [ ] Add event type, display reason, priority, and strong-signal voice behavior gated by proxy voice owner and dry-run.
- [ ] Run .NET tests and Release build.

### Task 4: Web Realtime Event Chain

**Files:**
- Create: `src/services/hotlist/OpeningAuctionStateStore.ts`
- Create: `src/services/hotlist/OpeningRealtimeEventBuffer.ts`
- Create: `src/services/hotlist/OpeningSignalClient.ts`
- Modify: `src/services/hotlist/hotStockEventTypes.ts`
- Modify: `src/services/hotlist/HotStockEventMonitorService.ts`
- Modify: `src/services/hotlist/HotStockEventSpeechService.ts`
- Modify: `src/components/panels/HotStockEventMonitorPanel.vue`
- Add/modify tests under `src/services/hotlist/__tests__`.

- [ ] Write tests proving HTTP event feeds cannot create `opening_weak_to_strong`.
- [ ] Write tests proving WebSocket quote samples can create the event and submit it to proxy.
- [ ] Implement realtime buffer and event conversion into existing monitor state.
- [ ] Gate web voice by proxy `voiceOwner=web` and `dryRun=false`.
- [ ] Run Vitest and `vue-tsc`.

### Task 5: Dragon Board Main Table Signal

**Files:**
- Create/extend: `src/services/hotlist/OpeningSignalClient.ts`
- Modify: `src/components/common/DataTable.vue`
- Modify/add: `src/components/common/__tests__/DataTable.test.ts`

- [ ] Write tests for rendering the compact “竞价弱转强” badge next to matching stock rows.
- [ ] Implement today-signal polling client and table badge without changing sort order.
- [ ] Run component tests, `vue-tsc`, and `pnpm build`.

### Task 6: Bridge Forced Sampling Metadata

**Files:**
- Modify: `python-bridge/main.py`
- Add tests if a Python test harness exists; otherwise add a small diagnostic or documented dry-run command.

- [ ] Inspect current diffing and broadcast loop.
- [ ] Add forced opening snapshot metadata without calculating signals in bridge.
- [ ] Ensure per-code `capturedAt/bridgeTs` can be emitted even if quote values are unchanged.
- [ ] Verify bridge startup and sample payload shape.

### Task 7: Documentation And Morning Runbook

**Files:**
- Modify: `docs/yidong-jingling/task_plan.md`
- Modify: `docs/yidong-jingling/findings.md`
- Modify: `docs/yidong-jingling/progress.md`
- Modify: `docs/yidong-jingling/opening-weak-to-strong-plan.md`
- Modify: `docs/yidong-jingling/usage.md`

- [ ] Update status for completed phases and record verification output.
- [ ] Add dry-run morning checklist and known downgrade behavior if implementation details changed.
- [ ] Run `git diff --check`.
