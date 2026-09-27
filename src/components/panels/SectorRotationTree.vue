<template>
  <div class="sector-rotation-tree">
    <div class="tree-toolbar">
      <h4 class="tree-title">🔄 轮动题材列表</h4>
      <span class="tree-count">共 {{ statuses.length }} 个题材</span>
    </div>
    <div class="tree-groups">
      <template v-for="group in groups" :key="group.state">
        <div v-if="group.rows.length" class="tree-group">
          <div class="group-header">
            <span class="state-badge" :class="stateToneOf(group.state)">{{ stateLabelOf(group.state) }}</span>
            <span class="group-count">{{ group.rows.length }}</span>
          </div>
          <div class="tree-content">
            <div
              v-for="row in group.rows"
              :key="row.entityKey"
              class="tree-node"
              :class="{ selected: selectedKey === row.entityKey }"
              @click="emitSelect(row, $event)"
            >
              <div class="node-header">
                <span class="node-name">{{ row.entityName }}</span>
                <div class="node-badges">
                  <span class="rank-badge">#{{ row.rank ?? '—' }}</span>
                  <span class="state-badge" :class="stateToneOf(row.rotationState)">{{ stateLabelOf(row.rotationState) }}</span>
                </div>
              </div>
              <div class="node-metrics">
                <span class="score">轮动分 {{ formatNumber(row.rotationScore, 1) }}</span>
                <span class="rank-change" :class="trendClass(row.rankChange)">排名 {{ formatSigned(row.rankChange) }}</span>
                <span class="flow" :class="(row.flowTrend ?? 0) >= 0 ? 'inflow' : 'outflow'">{{ formatFlowTrend(row.flowTrend) }}</span>
              </div>
              <div class="node-progress" v-if="row.rotationScore != null">
                <div class="progress-bar" :style="{ width: Math.max(0, Math.min(100, row.rotationScore)) + '%' }"></div>
              </div>
            </div>
          </div>
        </div>
      </template>
      <div v-if="!hasVisibleRows" class="tree-empty">该筛选下无题材</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { ThemeRotationStatusRow } from '@/services/theme/ThemeFacade'
import { rotationStateLabel, ROTATION_STATE_META } from '@/services/theme/rotationDisplay'

const props = defineProps<{
  statuses: ThemeRotationStatusRow[]
  selectedKey?: string
}>()

const emit = defineEmits<{ (e: 'select', row: ThemeRotationStatusRow, event: MouseEvent): void }>()

// 分组顺序：主线确认 → 流入 → 萌发 → 中性 → 流出 → 退潮，其余未知态兜底在后
const GROUP_ORDER = ['mainline', 'inflow', 'emerging', 'neutral', 'outflow', 'cooling']

const groups = computed(() => {
  const byState = new Map<string, ThemeRotationStatusRow[]>()
  for (const row of props.statuses) {
    const key = row.rotationState || 'unknown'
    const list = byState.get(key) || []
    list.push(row)
    byState.set(key, list)
  }
  const ordered = [
    ...GROUP_ORDER,
    ...[...byState.keys()].filter((key) => !GROUP_ORDER.includes(key)),
  ]
  return ordered.map((state) => ({ state, rows: byState.get(state) ?? [] }))
})

const hasVisibleRows = computed(() => groups.value.some((group) => group.rows.length > 0))

function emitSelect(row: ThemeRotationStatusRow, event: MouseEvent) {
  emit('select', row, event)
}

function stateLabelOf(state: string | null | undefined): string {
  return rotationStateLabel(state)
}

function stateToneOf(state: string | null | undefined): string {
  return (state && ROTATION_STATE_META[state]?.tone) || 'state-unknown'
}

function formatNumber(value: number | null | undefined, digits = 1): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : '—'
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
</script>

<style scoped>
.sector-rotation-tree {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.tree-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.tree-title {
  margin: 0;
  font-size: 13px;
  color: var(--text-primary);
}
.tree-count {
  font-size: 12px;
  color: var(--text-secondary, #9aa5b1);
}
.tree-groups {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.group-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.group-count {
  font-size: 12px;
  color: var(--text-secondary, #9aa5b1);
}
.tree-content {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 8px;
}
.tree-node {
  background: var(--bg-secondary, rgba(255, 255, 255, 0.03));
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 8px 10px;
  cursor: pointer;
  transition: border-color 0.15s ease;
}
.tree-node:hover {
  border-color: var(--accent-color, #4a9eff);
}
.tree-node.selected {
  border-color: var(--accent-color, #4a9eff);
  background: var(--bg-tertiary, rgba(74, 158, 255, 0.08));
}
.node-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}
.node-name {
  font-size: 13px;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.node-badges {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}
.rank-badge {
  font-size: 11px;
  color: var(--text-secondary, #9aa5b1);
}
.state-badge {
  padding: 1px 8px;
  border-radius: 8px;
  border: 1px solid var(--border-color);
  font-size: 11px;
}
.state-mainline { color: #f5c15b; border-color: #f5c15b; }
.state-inflow { color: #f55b5b; border-color: rgba(245, 91, 91, 0.5); }
.state-emerging { color: #5bd4f5; border-color: #5bd4f5; }
.state-neutral { color: var(--text-secondary, #9aa5b1); }
.state-outflow { color: #4caf7d; border-color: rgba(76, 175, 125, 0.5); }
.state-cooling { color: #5ba3f5; border-color: rgba(91, 163, 245, 0.5); }
.state-unknown { color: var(--text-secondary, #9aa5b1); }
.node-metrics {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 5px;
  font-size: 12px;
}
.score {
  color: var(--text-primary);
}
.rank-change,
.flow {
  color: var(--text-secondary, #9aa5b1);
}
.flow.inflow,
.trend-up { color: #f55b5b; }
.flow.outflow,
.trend-down { color: #4caf7d; }
.node-progress {
  margin-top: 6px;
  height: 3px;
  border-radius: 2px;
  background: var(--border-color);
  overflow: hidden;
}
.progress-bar {
  height: 100%;
  background: linear-gradient(90deg, #f5a15b, #f5c15b);
  border-radius: 2px;
}
.tree-empty {
  padding: 16px;
  text-align: center;
  color: var(--text-secondary, #9aa5b1);
  font-size: 13px;
}
</style>
