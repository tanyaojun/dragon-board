# 题材轮动状态页签 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在题材分析面板（SectorPanel）新增"轮动状态"页签，消费 `/api/theme-rotation/summary`（摘要区 + 可展开全量状态表），补齐设计文档登记的前端展示缺口。

**Architecture:** 纯消费不生产（单一事实源）——facade 新增 `getRotationSummary`，展示元数据（六态中文映射/分布计数）抽为纯函数模块 `rotationDisplay.ts` 便于真实单测，页签主体 `SectorRotationTab.vue` 懒加载渲染，`SectorPanel` 加页签分支。测试沿用代码库既有"源码契约测试"范式（ThemeMomentumPanel.test.ts 先例）+ 纯函数真实单测。

**Tech Stack:** Vue 3 `<script setup>` + TypeScript + Vitest；复用 `apiService.get` 与主题 CSS 变量；零新依赖。

**设计依据:** `docs/theme-module/2026-09-27-theme-rotation-panel-design.md`（已确认）。

**验证命令:** `pnpm exec vitest run src/services/theme/__tests__/rotationDisplay.test.ts src/components/panels/__tests__/SectorRotationTab.test.ts`；类型 `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`；构建 `pnpm build`。浏览器验收由用户本人执行。

---

## File Structure

```text
src/services/theme/rotationDisplay.ts            # 新建：六态元数据/标签映射/分布计数纯函数
src/services/theme/ThemeFacade.ts                # 修改：ThemeRotationSummary 类型 + getRotationSummary()
src/components/panels/SectorRotationTab.vue      # 新建：页签主体（摘要区+可展开状态表）
src/components/panels/SectorPanel.vue            # 修改：view 联合类型扩宽 + 页签按钮 + 分支 + import
src/services/theme/__tests__/rotationDisplay.test.ts        # 新建：纯函数真实单测
src/components/panels/__tests__/SectorRotationTab.test.ts   # 新建：源码契约测试
docs/theme-module/plans/task_plan_rotation_panel.md         # 本计划
```

---

### Task 1: 展示元数据纯函数 `rotationDisplay.ts`（TDD）

**Files:**
- Create: `src/services/theme/rotationDisplay.ts`
- Test: `src/services/theme/__tests__/rotationDisplay.test.ts`

- [ ] **Step 1.1: 写失败测试**（内容见 Task 1 代码块，`expect(marketPhaseLabel('cooling')).toBe('退潮')` 等 4 组用例）
- [ ] **Step 1.2: 运行确认失败** `pnpm exec vitest run src/services/theme/__tests__/rotationDisplay.test.ts` → FAIL（模块不存在）
- [ ] **Step 1.3: 实现** rotationDisplay.ts（完整代码见下）
- [ ] **Step 1.4: 运行确认通过**
- [ ] **Step 1.5: Commit** `feat(theme-panel): 轮动展示元数据纯函数——六态中文映射+分布计数`

```ts
// src/services/theme/rotationDisplay.ts
/** 轮动状态页签展示元数据（纯函数，无 I/O；后端 API 为唯一事实源，此处仅消费侧标签/计数）。 */

export interface PhaseMeta {
  label: string
  tone: string
}

export const MARKET_PHASE_META: Record<string, PhaseMeta> = {
  rising: { label: '升温', tone: 'phase-rising' },
  climax: { label: '高潮', tone: 'phase-climax' },
  cooling: { label: '退潮', tone: 'phase-cooling' },
  ice: { label: '冰点', tone: 'phase-ice' },
  chaos: { label: '混沌', tone: 'phase-chaos' },
  neutral: { label: '中性', tone: 'phase-neutral' },
}

export const ROTATION_STATE_META: Record<string, PhaseMeta> = {
  mainline: { label: '主线', tone: 'state-mainline' },
  inflow: { label: '流入', tone: 'state-inflow' },
  emerging: { label: '萌发', tone: 'state-emerging' },
  neutral: { label: '中性', tone: 'state-neutral' },
  outflow: { label: '流出', tone: 'state-outflow' },
  cooling: { label: '退潮', tone: 'state-cooling' },
}

export function marketPhaseLabel(phase: string | null | undefined): string {
  if (!phase) return '未知'
  return MARKET_PHASE_META[phase]?.label ?? phase
}

export function rotationStateLabel(state: string | null | undefined): string {
  if (!state) return '—'
  return ROTATION_STATE_META[state]?.label ?? state
}

export function stateTone(state: string | null | undefined): string {
  return (state && ROTATION_STATE_META[state]?.tone) || 'state-unknown'
}

export function countRotationStates(
  statuses: { rotationState: string | null }[],
): { state: string; count: number }[] {
  const counts = new Map<string, number>()
  for (const row of statuses) {
    const key = row.rotationState || 'unknown'
    counts.set(key, (counts.get(key) || 0) + 1)
  }
  return [...counts.entries()]
    .map(([state, count]) => ({ state, count }))
    .sort((a, b) => b.count - a.count)
}
```

```ts
// src/services/theme/__tests__/rotationDisplay.test.ts
import { describe, expect, it } from 'vitest'
import { countRotationStates, marketPhaseLabel, rotationStateLabel } from '../rotationDisplay'

describe('marketPhaseLabel', () => {
  it('maps known phases to Chinese labels', () => {
    expect(marketPhaseLabel('cooling')).toBe('退潮')
    expect(marketPhaseLabel('climax')).toBe('高潮')
    expect(marketPhaseLabel('rising')).toBe('升温')
    expect(marketPhaseLabel('ice')).toBe('冰点')
    expect(marketPhaseLabel('chaos')).toBe('混沌')
    expect(marketPhaseLabel('neutral')).toBe('中性')
  })

  it('falls back for unknown and missing phases without crashing', () => {
    expect(marketPhaseLabel('new_phase')).toBe('new_phase')
    expect(marketPhaseLabel(null)).toBe('未知')
    expect(marketPhaseLabel('')).toBe('未知')
  })
})

describe('rotationStateLabel', () => {
  it('maps known states and passes unknown through', () => {
    expect(rotationStateLabel('mainline')).toBe('主线')
    expect(rotationStateLabel('inflow')).toBe('流入')
    expect(rotationStateLabel('outflow')).toBe('流出')
    expect(rotationStateLabel('emerging')).toBe('萌发')
    expect(rotationStateLabel('neutral')).toBe('中性')
    expect(rotationStateLabel('cooling')).toBe('退潮')
    expect(rotationStateLabel('new_state')).toBe('new_state')
    expect(rotationStateLabel(null)).toBe('—')
  })
})

describe('countRotationStates', () => {
  it('counts by state with null as unknown and sorts descending', () => {
    const rows = [{ rotationState: 'inflow' }, { rotationState: 'inflow' }, { rotationState: 'outflow' }, { rotationState: null }]
    expect(countRotationStates(rows)).toEqual([
      { state: 'inflow', count: 2 },
      { state: 'outflow', count: 1 },
      { state: 'unknown', count: 1 },
    ])
  })

  it('returns empty for empty statuses', () => {
    expect(countRotationStates([])).toEqual([])
  })
})
```

---

### Task 2: facade `getRotationSummary` + 响应类型

**Files:**
- Modify: `src/services/theme/ThemeFacade.ts`（文件末尾追加，与 getThemeMomentumSummary 同区）

- [ ] **Step 2.1: 追加类型与取数函数**（完整代码见下；404/网络失败统一返回 null，由组件呈现"暂无轮动数据"+重试）
- [ ] **Step 2.2: 类型检查** `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false` → 0 error
- [ ] **Step 2.3: Commit** `feat(theme-panel): ThemeFacade 新增 getRotationSummary 与响应类型`

```ts
// ThemeFacade.ts 追加（文件末尾）
export interface ThemeRotationThemeRef {
  themeId: string
  themeName: string
}

export interface ThemeRotationStatusRow {
  entityKey: string
  entityName: string
  rank: number | null
  rankChange: number | null
  rotationState: string | null
  rotationScore: number | null
  factorBreakdown: {
    strength: number | null
    flow: number | null
    breadth: number | null
    crowding: number | null
    lifecycle: number | null
  } | null
  flowTrend: number | null
  heatTrend: number | null
  breadthTrend: number | null
  crowdingTrend: number | null
  qualityFlags: string[]
}

export interface ThemeRotationSummary {
  frame: {
    tradingDate: string
    slotTime: string
    snapshotId: string
    timestamp: number
    rotationSummary: {
      marketPhase: string | null
      rotationSpeed: number | null
      mainlineConcentration: number | null
      maxBoardHeight: number | null
      mainLines: ThemeRotationThemeRef[]
      inflowThemes: ThemeRotationThemeRef[]
      outflowThemes: ThemeRotationThemeRef[]
    } | null
  }
  statuses: ThemeRotationStatusRow[]
}

export async function getRotationSummary(params: {
  snapshotType: string
  datasetId?: string
}): Promise<ThemeRotationSummary | null> {
  try {
    const query = new URLSearchParams({
      dataset_id: params.datasetId || 'dragonboard_live',
      snapshot_type: params.snapshotType,
    })
    return await apiService.get<ThemeRotationSummary>(`/api/theme-rotation/summary?${query.toString()}`)
  } catch {
    return null
  }
}
```

---

### Task 3: 页签主体 `SectorRotationTab.vue`（TDD 契约测试先行）

**Files:**
- Create: `src/components/panels/SectorRotationTab.vue`
- Test: `src/components/panels/__tests__/SectorRotationTab.test.ts`

- [ ] **Step 3.1: 写契约测试**（5 组断言：facade 接线 / 摘要字段与"引擎判定无主线"文案 / 表排序筛选与 qualityFlags / fail-visible 文案与 state-unknown / 后续 Task 4 的 SectorPanel 接线断言——本任务先跳过第 5 组）
- [ ] **Step 3.2: 运行确认失败**（组件文件不存在）
- [ ] **Step 3.3: 实现组件**（完整代码见下：模板/脚本/样式三段）
- [ ] **Step 3.4: 运行确认通过**（第 1-4 组）
- [ ] **Step 3.5: Commit** `feat(theme-panel): SectorRotationTab 页签主体——摘要区+可展开全量状态表`

组件完整代码（模板/脚本/样式）：

```vue
<template>
  <div class="sector-rotation-tab">
    <div class="rotation-toolbar">
      <span class="rotation-updated">{{ dataTimeText }}</span>
      <button class="refresh-btn" :class="{ loading }" title="刷新" @click="loadData(true)">
        <span :class="{ 'rotate-animation': loading }">🔄</span>
      </button>
    </div>

    <div v-if="error" class="rotation-error">
      <span>⚠️</span>
      <span>{{ error }}</span>
      <button class="retry-btn" @click="loadData(true)">重试</button>
    </div>
    <div v-else-if="!summary" class="rotation-empty">
      <span>{{ loading ? '加载中…' : '暂无轮动数据' }}</span>
      <button v-if="!loading" class="retry-btn" @click="loadData(true)">重试</button>
    </div>

    <template v-else>
      <section class="rotation-summary">
        <div class="summary-row phase-row">
          <span class="phase-badge" :class="phaseTone">{{ phaseLabel }}</span>
          <span class="summary-metric">轮动速度 {{ formatNumber(rotationSummary?.rotationSpeed, 2) }}</span>
          <span class="summary-metric">主线集中度 {{ formatPercent(rotationSummary?.mainlineConcentration) }}</span>
          <span class="summary-metric">最高连板 {{ formatNumber(rotationSummary?.maxBoardHeight, 0) }}</span>
        </div>
        <div class="summary-row">
          <span class="row-label">主线</span>
          <template v-if="mainLineNames.length">
            <span v-for="name in mainLineNames" :key="name" class="theme-chip chip-mainline">{{ name }}</span>
          </template>
          <span v-else class="no-mainline">引擎判定无主线</span>
        </div>
        <div class="summary-row">
          <span class="row-label">流入</span>
          <span v-for="theme in inflowPreview" :key="theme.themeId" class="theme-chip chip-inflow">{{ theme.themeName }}</span>
          <span v-if="inflowRestCount > 0" class="chip-rest">等 {{ inflowRestCount }}</span>
          <span v-if="!inflowThemes.length" class="row-empty">—</span>
        </div>
        <div class="summary-row">
          <span class="row-label">流出</span>
          <span v-for="theme in outflowPreview" :key="theme.themeId" class="theme-chip chip-outflow">{{ theme.themeName }}</span>
          <span v-if="outflowRestCount > 0" class="chip-rest">等 {{ outflowRestCount }}</span>
          <span v-if="!outflowThemes.length" class="row-empty">—</span>
        </div>
        <div class="summary-row state-distribution">
          <span class="row-label">分布</span>
          <span v-for="bucket in stateBuckets" :key="bucket.state" class="state-count" :class="stateToneOf(bucket.state)">
            {{ stateLabelOf(bucket.state) }} {{ bucket.count }}
          </span>
        </div>
      </section>

      <section class="rotation-table-section">
        <button class="table-toggle" @click="tableOpen = !tableOpen">
          {{ tableOpen ? '收起题材状态表' : `展开题材状态表（${statuses.length}）` }}
        </button>
        <div v-if="tableOpen" class="rotation-table-wrap">
          <div class="table-filters">
            <button
              v-for="option in filterOptions"
              :key="option.value"
              class="filter-btn"
              :class="{ active: stateFilter === option.value }"
              @click="stateFilter = option.value"
            >
              {{ option.label }}
            </button>
          </div>
          <table class="rotation-table">
            <thead>
              <tr>
                <th
                  v-for="col in columns"
                  :key="col.key"
                  :class="{ sortable: col.sortable, sorted: sortKey === col.key }"
                  @click="col.sortable && toggleSort(col.key)"
                >
                  {{ col.label }}<span v-if="col.sortable && sortKey === col.key">{{ sortDir === 1 ? ' ▲' : ' ▼' }}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in visibleRows" :key="row.entityKey">
                <td>{{ row.entityName }}</td>
                <td>{{ row.rank ?? '—' }}</td>
                <td :class="trendClass(row.rankChange)">{{ formatSigned(row.rankChange) }}</td>
                <td><span class="state-badge" :class="stateToneOf(row.rotationState)">{{ stateLabelOf(row.rotationState) }}</span></td>
                <td>{{ formatNumber(row.rotationScore, 1) }}</td>
                <td>{{ formatNumber(row.factorBreakdown?.strength, 1) }}</td>
                <td>{{ formatNumber(row.factorBreakdown?.flow, 1) }}</td>
                <td>{{ formatNumber(row.factorBreakdown?.breadth, 1) }}</td>
                <td>{{ formatNumber(row.factorBreakdown?.crowding, 1) }}</td>
                <td :class="trendClass(row.flowTrend)">{{ formatFlowTrend(row.flowTrend) }}</td>
                <td>{{ row.qualityFlags?.length ? row.qualityFlags.join(',') : '—' }}</td>
              </tr>
              <tr v-if="visibleRows.length === 0">
                <td colspan="11" class="row-empty">该筛选下无题材</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  getRotationSummary,
  type ThemeRotationStatusRow,
  type ThemeRotationSummary,
} from '@/services/theme/ThemeFacade'
import {
  countRotationStates,
  MARKET_PHASE_META,
  marketPhaseLabel,
  rotationStateLabel,
  ROTATION_STATE_META,
} from '@/services/theme/rotationDisplay'

const loading = ref(false)
const error = ref<string | null>(null)
const summary = ref<ThemeRotationSummary | null>(null)
const tableOpen = ref(false)
const stateFilter = ref<string>('all')
const sortKey = ref<string>('rank')
const sortDir = ref<1 | -1>(1)

async function loadData(force = false) {
  if (loading.value && !force) return
  loading.value = true
  error.value = null
  try {
    const result = await getRotationSummary({ snapshotType: 'half_hour' })
    if (result) summary.value = result
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  if (!summary.value) loadData()
})

const rotationSummary = computed(() => summary.value?.frame.rotationSummary ?? null)
const dataTimeText = computed(() => {
  const frame = summary.value?.frame
  return frame ? `数据 ${frame.tradingDate} ${frame.slotTime}` : '未加载'
})
const phaseLabel = computed(() => marketPhaseLabel(rotationSummary.value?.marketPhase))
const phaseTone = computed(() => {
  const phase = rotationSummary.value?.marketPhase
  return (phase && MARKET_PHASE_META[phase]?.tone) || 'phase-unknown'
})
const mainLineNames = computed(() => rotationSummary.value?.mainLines.map((m) => m.themeName) ?? [])
const inflowThemes = computed(() => rotationSummary.value?.inflowThemes ?? [])
const outflowThemes = computed(() => rotationSummary.value?.outflowThemes ?? [])
const PREVIEW_COUNT = 8
const inflowPreview = computed(() => inflowThemes.value.slice(0, PREVIEW_COUNT))
const inflowRestCount = computed(() => Math.max(0, inflowThemes.value.length - PREVIEW_COUNT))
const outflowPreview = computed(() => outflowThemes.value.slice(0, PREVIEW_COUNT))
const outflowRestCount = computed(() => Math.max(0, outflowThemes.value.length - PREVIEW_COUNT))
const statuses = computed(() => summary.value?.statuses ?? [])
const stateBuckets = computed(() => countRotationStates(statuses.value))

const columns = [
  { key: 'entityName', label: '题材', sortable: false },
  { key: 'rank', label: '排名', sortable: true },
  { key: 'rankChange', label: '排名变化', sortable: true },
  { key: 'rotationState', label: '轮动状态', sortable: true },
  { key: 'rotationScore', label: '轮动分', sortable: true },
  { key: 'strength', label: '强度', sortable: true },
  { key: 'flow', label: '资金', sortable: true },
  { key: 'breadth', label: '广度', sortable: true },
  { key: 'crowding', label: '拥挤', sortable: true },
  { key: 'flowTrend', label: '净流入趋势', sortable: true },
  { key: 'qualityFlags', label: '质量标记', sortable: false },
] as const

function toggleSort(key: string) {
  if (sortKey.value === key) {
    sortDir.value = sortDir.value === 1 ? -1 : 1
  } else {
    sortKey.value = key
    sortDir.value = 1
  }
}

const BREAKDOWN_KEYS = new Set(['strength', 'flow', 'breadth', 'crowding'])

function sortValue(row: ThemeRotationStatusRow, key: string): number | string {
  if (key === 'rotationState') return rotationStateLabel(row.rotationState)
  if (BREAKDOWN_KEYS.has(key)) {
    const value = row.factorBreakdown?.[key as 'strength' | 'flow' | 'breadth' | 'crowding']
    return typeof value === 'number' ? value : Number.NEGATIVE_INFINITY
  }
  const direct = (row as unknown as Record<string, unknown>)[key]
  if (typeof direct === 'number') return direct
  if (typeof direct === 'string') return direct
  return Number.NEGATIVE_INFINITY
}

const visibleRows = computed(() => {
  const rows = statuses.value.filter(
    (row) => stateFilter.value === 'all' || (row.rotationState || 'unknown') === stateFilter.value,
  )
  const dir = sortDir.value
  const key = sortKey.value
  return [...rows].sort((a, b) => {
    const va = sortValue(a, key)
    const vb = sortValue(b, key)
    if (typeof va === 'string' || typeof vb === 'string') {
      return String(va).localeCompare(String(vb), 'zh-Hans-CN') * dir
    }
    return (va - vb) * dir
  })
})

const filterOptions = computed(() => [
  { value: 'all', label: `全部 ${statuses.value.length}` },
  ...stateBuckets.value.map((bucket) => ({
    value: bucket.state,
    label: `${rotationStateLabel(bucket.state)} ${bucket.count}`,
  })),
])

function formatNumber(value: number | null | undefined, digits = 1): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : '—'
}

function formatPercent(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? `${(value * 100).toFixed(2)}%` : '—'
}

function formatSigned(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—'
  return value > 0 ? `+${value}` : String(value)
}

function formatFlowTrend(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—'
  const abs = Math.abs(value)
  const text = abs >= 1e8 ? `${(abs / 1e8).toFixed(1)}亿` : abs >= 1e4 ? `${(abs / 1e4).toFixed(0)}万` : String(abs)
  return (value > 0 ? '+' : value < 0 ? '-' : '') + text
}

function trendClass(value: number | null | undefined) {
  return { 'trend-up': (value ?? 0) > 0, 'trend-down': (value ?? 0) < 0 }
}

function stateLabelOf(state: string | null | undefined): string {
  return rotationStateLabel(state)
}

function stateToneOf(state: string | null | undefined): string {
  return (state && ROTATION_STATE_META[state]?.tone) || 'state-unknown'
}
</script>

<style scoped>
.sector-rotation-tab {
  display: flex;
  flex-direction: column;
  gap: 10px;
  height: 100%;
  overflow-y: auto;
}
.rotation-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.rotation-updated {
  font-size: 12px;
  color: var(--text-secondary, #9aa5b1);
}
.refresh-btn,
.retry-btn,
.table-toggle,
.filter-btn {
  background: var(--bg-tertiary, transparent);
  border: 1px solid var(--border-color);
  color: var(--text-primary);
  border-radius: 4px;
  padding: 3px 10px;
  cursor: pointer;
  font-size: 12px;
}
.refresh-btn:hover,
.retry-btn:hover,
.table-toggle:hover,
.filter-btn:hover {
  border-color: var(--accent-color, #4a9eff);
}
.filter-btn.active {
  border-color: var(--accent-color, #4a9eff);
  color: var(--accent-color, #4a9eff);
}
.rotation-error,
.rotation-empty {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 16px;
  color: var(--text-secondary, #9aa5b1);
  font-size: 13px;
}
.rotation-summary {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px 12px;
  background: var(--bg-secondary, rgba(255, 255, 255, 0.03));
  border: 1px solid var(--border-color);
  border-radius: 6px;
}
.summary-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  font-size: 12px;
}
.row-label {
  color: var(--text-secondary, #9aa5b1);
  min-width: 30px;
}
.phase-badge {
  padding: 2px 10px;
  border-radius: 10px;
  font-weight: 600;
  border: 1px solid var(--border-color);
}
.phase-cooling { color: #5ba3f5; border-color: #5ba3f5; }
.phase-climax { color: #f55b5b; border-color: #f55b5b; }
.phase-rising { color: #f58b5b; border-color: #f58b5b; }
.phase-ice { color: #7fd4ff; border-color: #7fd4ff; }
.phase-chaos { color: #d4a0ff; border-color: #d4a0ff; }
.phase-neutral { color: var(--text-primary); }
.phase-unknown { color: var(--text-secondary, #9aa5b1); }
.summary-metric {
  color: var(--text-primary);
}
.theme-chip {
  padding: 1px 8px;
  border-radius: 8px;
  border: 1px solid var(--border-color);
}
.chip-mainline { color: #f5c15b; border-color: #f5c15b; }
.chip-inflow { color: #f55b5b; border-color: rgba(245, 91, 91, 0.5); }
.chip-outflow { color: #4caf7d; border-color: rgba(76, 175, 125, 0.5); }
.chip-rest { color: var(--text-secondary, #9aa5b1); }
.no-mainline { color: var(--text-secondary, #9aa5b1); }
.state-count,
.state-badge {
  padding: 1px 8px;
  border-radius: 8px;
  border: 1px solid var(--border-color);
}
.state-mainline { color: #f5c15b; border-color: #f5c15b; }
.state-inflow { color: #f55b5b; border-color: rgba(245, 91, 91, 0.5); }
.state-emerging { color: #5bd4f5; border-color: #5bd4f5; }
.state-neutral { color: var(--text-secondary, #9aa5b1); }
.state-outflow { color: #4caf7d; border-color: rgba(76, 175, 125, 0.5); }
.state-cooling { color: #5ba3f5; border-color: rgba(91, 163, 245, 0.5); }
.state-unknown { color: var(--text-secondary, #9aa5b1); }
.rotation-table-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.table-filters {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.rotation-table-wrap {
  overflow-x: auto;
}
.rotation-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.rotation-table th,
.rotation-table td {
  padding: 5px 8px;
  border-bottom: 1px solid var(--border-color);
  text-align: right;
  white-space: nowrap;
}
.rotation-table th:first-child,
.rotation-table td:first-child {
  text-align: left;
}
.rotation-table th.sortable {
  cursor: pointer;
  user-select: none;
}
.rotation-table th.sorted {
  color: var(--accent-color, #4a9eff);
}
.trend-up { color: #f55b5b; }
.trend-down { color: #4caf7d; }
.row-empty { color: var(--text-secondary, #9aa5b1); }
.rotate-animation { display: inline-block; animation: rotation-spin 1s linear infinite; }
@keyframes rotation-spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
```

契约测试（`src/components/panels/__tests__/SectorRotationTab.test.ts`）：

```ts
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

describe('SectorRotationTab', () => {
  const tab = readFileSync(join(process.cwd(), 'src', 'components', 'panels', 'SectorRotationTab.vue'), 'utf8')
  const facade = readFileSync(join(process.cwd(), 'src', 'services', 'theme', 'ThemeFacade.ts'), 'utf8')

  it('fetches via themeFacade.getRotationSummary against the rotation summary API', () => {
    expect(tab).toContain('getRotationSummary')
    expect(facade).toContain('export async function getRotationSummary')
    expect(facade).toContain('/api/theme-rotation/summary')
  })

  it('renders summary fields with explicit engine-no-mainline copy', () => {
    expect(tab).toContain('phase-badge')
    expect(tab).toContain('rotationSpeed')
    expect(tab).toContain('mainlineConcentration')
    expect(tab).toContain('maxBoardHeight')
    expect(tab).toContain('引擎判定无主线')
    expect(tab).toContain('inflowThemes')
    expect(tab).toContain('outflowThemes')
    expect(tab).toContain('state-distribution')
  })

  it('supports sortable and filterable status table with quality flags', () => {
    expect(tab).toContain('rotation-table')
    expect(tab).toContain('toggleSort')
    expect(tab).toContain('stateFilter')
    expect(tab).toContain('qualityFlags')
    expect(tab).toContain('展开题材状态表')
  })

  it('stays fail-visible on empty data and unknown states', () => {
    expect(tab).toContain('暂无轮动数据')
    expect(tab).toContain('重试')
    expect(tab).toContain('state-unknown')
  })
})
```

---

### Task 4: SectorPanel 接线

**Files:**
- Modify: `src/components/panels/SectorPanel.vue`（view 类型 166 行、页签按钮 tabs-left、分支链、import）

- [ ] **Step 4.1: 三处修改**

```ts
// 166 行
const view = ref<'hot' | 'rotation'>('hot')
// import 区（ThemeSortControl 之后）
import SectorRotationTab from './SectorRotationTab.vue'
```

```html
<!-- tabs-left 内"热门题材"按钮之后 -->
<button class="tab-btn" :class="{ active: view === 'rotation' }" @click="view = 'rotation'">
  🔄 轮动状态
</button>
<!-- 分支链末尾（热门题材 grid 分支之后） -->
<div v-else-if="view === 'rotation'" class="rotation-view">
  <SectorRotationTab />
</div>
```

- [ ] **Step 4.2: 契约测试补第 5 组**（SectorRotationTab.test.ts 追加）

```ts
  const panel = readFileSync(join(process.cwd(), 'src', 'components', 'panels', 'SectorPanel.vue'), 'utf8')

  it('is wired as a rotation tab inside SectorPanel', () => {
    expect(panel).toContain("view === 'rotation'")
    expect(panel).toContain('轮动状态')
    expect(panel).toContain('SectorRotationTab')
  })
```

- [ ] **Step 4.3: Commit** `feat(theme-panel): SectorPanel 接入轮动状态页签`

---

### Task 5: 收口验证

- [ ] **Step 5.1:** `pnpm exec vitest run src/services/theme/__tests__/rotationDisplay.test.ts src/components/panels/__tests__/SectorRotationTab.test.ts src/components/panels/__tests__/ThemeMomentumPanel.test.ts` 全绿
- [ ] **Step 5.2:** `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false` 0 error
- [ ] **Step 5.3:** `pnpm build` 成功
- [ ] **Step 5.4:** 交用户浏览器验收（用户本人执行）：打开题材分析面板 → 切"🔄 轮动状态"页签 → 摘要区字段渲染（相位徽章/主线空文案/流入流出/分布）→ 展开状态表排序筛选 → 控制台无错误。

## Self-Review 记录

- **Spec 覆盖**：懒加载（onMounted + 仅页签激活时挂载）、刷新/三态、摘要区五要素、全量表排序筛选、fail-visible 四条、样式复用主题变量、测试策略（真实单测+契约测试+类型+构建）、浏览器验收分工——全部有承载；
- **无占位符**：全部代码完整落计划；
- **类型一致性**：`ThemeRotationStatusRow`/`ThemeRotationSummary` 在 Task 2 定义，Task 3 组件消费同名；`rotationDisplay.ts` 导出与 Task 1 测试、Task 3 组件 import 一致。
