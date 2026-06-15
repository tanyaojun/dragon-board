# Trading Pool V2 Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist trading-pool rows as durable QuantBoard journal records while preserving the separation between candidate thesis records, trading-pool tracking records, and real `entry/exit` trade logs.

**Architecture:** V2 reuses the existing MongoDB `trade_journal` collection and journal API. A trading-pool record is `tradeType=trading_pool`, references its source thesis through top-level `candidateEntryId`, and stores V2 decisions in `signalsSnapshot.tradingPool`; historical real trades remain `tradeType=entry/exit` and are not read by the trading-pool projection.

**Tech Stack:** FastAPI + Pydantic, QuantBoard MongoDB repository, Vue 3 + TypeScript, existing `CandidateJournalService`, Vitest, pytest.

---

## Guardrails

- Do not create a separate MongoDB collection in V2.
- Do not write trading-pool state into `favorite_data`.
- Do not treat `tradeType=trading_pool` as a real historical `entry` or `exit`.
- Do not change existing candidate thesis filtering; candidate pool remains `tradeType=thesis`.
- Do not make `已介入` create a real trade log.
- Do not add SQLite/Supabase fallback behavior; current QuantBoard journal storage is MongoDB.

## File Map

- Modify: `quant-board/backend/data/models.py`
  - Add top-level `candidateEntryId` support to `TradeJournal`.
- Modify: `quant-board/backend/api/journal_routes.py`
  - Accept and update `candidate_entry_id`.
- Modify: `quant-board/backend/data/mongo_research_repository.py`
  - Filter journal entries by `candidateEntryId`; keep `tradeType` filtering explicit.
- Modify: `quant-board/tests/test_trade_journal.py`
  - Cover V2 create/list/update contract.
- Modify: `src/services/candidate/types.ts`
  - Add trading-pool persistence payload/update types.
- Modify: `src/services/candidate/CandidateJournalService.ts`
  - Add list/create/update helpers for `tradeType=trading_pool`.
- Modify: `src/services/candidate/__tests__/CandidateJournalService.test.ts`
  - Lock API payloads and thesis/trading-pool separation.
- Modify: `src/components/panels/CandidatePoolPanel.vue`
  - Load persisted trading-pool rows and persist manual intervention / refresh snapshots.
- Modify: `src/components/panels/__tests__/CandidatePoolPanel.test.ts`
  - Lock V2 journal-backed behavior without entry/exit conflation.
- Modify: `docs/candidate-pool/*` and `quant-board/docs/*`
  - Document `tradeType=trading_pool`, `candidateEntryId`, and `signalsSnapshot.tradingPool`.

## Task 1: Backend Journal Contract

- [ ] Add a failing pytest that creates a `trading_pool` journal entry with `candidate_entry_id`, verifies camelCase `candidateEntryId`, and filters by candidate.
- [ ] Add `candidate_entry_id` / `candidateEntryId` to journal request models, dataclass serialization, update field map, and repository filters.
- [ ] Run `cd quant-board; .\.venv\Scripts\python.exe -m pytest tests/test_trade_journal.py`.

## Task 2: Frontend Journal Service

- [ ] Add TypeScript types for persisted trading-pool payloads and update fields.
- [ ] Add service helpers to list, create, and update `tradeType=trading_pool` records.
- [ ] Add Vitest coverage confirming payloads use `trade_type=trading_pool`, top-level `candidate_entry_id`, and never query `entry/exit`.
- [ ] Run `pnpm exec vitest run src/services/candidate/__tests__/CandidateJournalService.test.ts --reporter=dot`.

## Task 3: Candidate Pool Panel Wiring

- [ ] Replace V1 session-only manual state with persisted trading-pool records when available.
- [ ] Keep V1 projection as the live recompute source; persist the current `signalsSnapshot.tradingPool` on refresh or manual intervention.
- [ ] Keep stale handling conservative: missing live signals update the trading-pool snapshot as stale but do not force historical trade-log writes.
- [ ] Run `pnpm exec vitest run src/components/panels/__tests__/CandidatePoolPanel.test.ts --reporter=dot`.

## Task 4: Documentation And Verification

- [ ] Update Dragon Board candidate-pool docs and QuantBoard API/architecture/MongoDB docs for the new journal contract.
- [ ] Run focused frontend tests, backend journal tests, app typecheck, and production build.
- [ ] Do not commit unrelated QuantBoard dirty files unless they are part of V2.
