# RankTrend V3 Live Signal Mapping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 RankTrend V3 实盘动作规则映射到 Dragon Board 行情总览【信号】列，并保留 tooltip 解释，供次日盯盘验证使用。

**Architecture:** 新增一个窄作用域纯函数模块，专门把 `stock + rankTrend` 映射成 `V3LiveSignalDecision`。先用 Vitest 锁定 `A主升买点 / B点火买点 / 转弱卖出 / 持有观察 / 无信号`，再把 DataTable 的 `jumpSignal` 列改为消费新决策对象，不扩散到后端或其它面板。

**Tech Stack:** Vue 3, TypeScript, Vitest

---

### Task 1: V3 信号纯函数 RED/GREEN

**Files:**
- Create: `src/services/rankTrend/liveV3SignalMapper.ts`
- Create: `src/services/rankTrend/__tests__/liveV3SignalMapper.test.ts`

- [ ] **Step 1: 写失败测试**
- [ ] **Step 2: 运行测试确认失败**
Run: `pnpm test:ranktrend -- src/services/rankTrend/__tests__/liveV3SignalMapper.test.ts`

- [ ] **Step 3: 实现最小纯函数**
支持：
  - `A主升买点`
  - `B点火买点`
  - `转弱卖出`
  - `持有观察`
  - `无信号`

- [ ] **Step 4: 运行测试确认通过**
Run: `pnpm test:ranktrend -- src/services/rankTrend/__tests__/liveV3SignalMapper.test.ts`

### Task 2: DataTable 接线

**Files:**
- Modify: `src/components/common/DataTable.vue`

- [ ] **Step 1: 将 `jumpSignal` 列切到 V3 决策对象**
- [ ] **Step 2: 更新 badge 文案、颜色和 tooltip**
- [ ] **Step 3: 保持其它列和现有 jump 数据流不受影响**

- [ ] **Step 4: 运行定向测试与类型检查**
Run: `pnpm test:ranktrend -- src/services/rankTrend/__tests__/liveV3SignalMapper.test.ts`
Run: `pnpm typecheck:ranktrend`

### Task 3: 收尾验证

**Files:**
- Review only: `quant-board/docs/superpowers/specs/2026-06-07-ranktrend-v3-live-signal-mapping-design.md`

- [ ] **Step 1: 核对实现与 spec 一致**
- [ ] **Step 2: 运行最终验证**
Run: `pnpm test:ranktrend -- src/services/rankTrend/__tests__/liveV3SignalMapper.test.ts`
Run: `pnpm typecheck:ranktrend`
