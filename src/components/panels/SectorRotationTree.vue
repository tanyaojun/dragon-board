<template>
  <div class="sector-rotation-tree">
    <div class="tree-toolbar">
      <h4 class="tree-title">🔄 轮动题材列表</h4>
      <span class="tree-count">共 {{ statuses.length }} 个题材</span>
    </div>
    <div class="tree-layout">
      <!-- 左：题材卡片目录（SectorStocksTree 树形卡片范式） -->
      <div class="tree-directory">
        <div
          v-for="row in statuses"
          :key="row.entityKey"
          class="tree-node"
          :class="{ selected: selectedRow?.entityKey === row.entityKey }"
          @click="selectedKey = row.entityKey"
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
            <span class="flow" :class="(row.flowTrend ?? 0) >= 0 ? 'inflow' : 'outflow'">{{ formatFlowTrend(row.flowTrend) }}</span>
          </div>
        </div>
        <div v-if="!statuses.length" class="tree-empty">该筛选下无题材</div>
      </div>

      <!-- 右：选中题材的轮动明细（字段列表） -->
      <div class="tree-detail">
        <template v-if="selectedRow">
          <div class="detail-header">
            <h4 class="detail-title">{{ selectedRow.entityName }} 轮动明细</h4>
            <span class="state-badge" :class="stateToneOf(selectedRow.rotationState)">{{ stateLabelOf(selectedRow.rotationState) }}</span>
          </div>
          <table class="detail-table">
            <tbody>
              <tr v-for="field in detailFields" :key="field.label">
                <th>{{ field.label }}</th>
                <td :class="field.tone">{{ field.value }}</td>
              </tr>
            </tbody>
          </table>
        </template>
        <div v-else class="tree-empty">点击左侧题材查看轮动明细</div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { ThemeRotationStatusRow } from '@/services/theme/ThemeFacade'
import { rotationStateLabel, ROTATION_STATE_META } from '@/services/theme/rotationDisplay'

const props = defineProps<{
  statuses: ThemeRotationStatusRow[]
}>()

// 选中题材：内部状态；筛选变化导致选中行不可见时自动回落到列表首行
const selectedKey = ref<string | null>(null)
const selectedRow = computed(() => {
  const byKey = props.statuses.find((row) => row.entityKey === selectedKey.value)
  return byKey ?? props.statuses[0] ?? null
})

const detailFields = computed(() => {
  const row = selectedRow.value
  if (!row) return []
  const breakdown = row.factorBreakdown
  return [
    { label: '轮动状态', value: stateLabelOf(row.rotationState), tone: stateToneOf(row.rotationState) },
    { label: '轮动分', value: formatNumber(row.rotationScore, 1), tone: '' },
    { label: '热度排名', value: row.rank ?? '—', tone: '' },
    { label: '排名变化', value: formatSigned(row.rankChange), tone: trendClass(row.rankChange) },
    { label: '强度', value: formatNumber(breakdown?.strength, 1), tone: '' },
    { label: '资金', value: formatNumber(breakdown?.flow, 1), tone: '' },
    { label: '广度', value: formatNumber(breakdown?.breadth, 1), tone: '' },
    { label: '拥挤', value: formatNumber(breakdown?.crowding, 1), tone: '' },
    { label: '净流入趋势', value: formatFlowTrend(row.flowTrend), tone: trendClass(row.flowTrend) },
    { label: '热度趋势', value: formatSigned(row.heatTrend), tone: trendClass(row.heatTrend) },
    { label: '广度趋势', value: formatSigned(row.breadthTrend), tone: trendClass(row.breadthTrend) },
    { label: '拥挤趋势', value: formatSigned(row.crowdingTrend), tone: trendClass(row.crowdingTrend) },
    { label: '质量标记', value: row.qualityFlags?.length ? row.qualityFlags.join(', ') : '—', tone: 'flags' },
  ]
})

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
/* 左目录右列表两栏布局（SectorStocksTree 范式） */
.tree-layout {
  display: grid;
  grid-template-columns: 280px 1fr;
  gap: 10px;
  align-items: start;
}
.tree-directory {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 520px;
  overflow-y: auto;
  padding-right: 2px;
}
.tree-node {
  background: var(--bg-secondary, rgba(255, 255, 255, 0.03));
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 7px 10px;
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
  margin-top: 4px;
  font-size: 12px;
}
.score {
  color: var(--text-primary);
}
.flow.inflow { color: #f55b5b; }
.flow.outflow { color: #4caf7d; }
.tree-detail {
  background: var(--bg-secondary, rgba(255, 255, 255, 0.03));
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 10px 12px;
}
.detail-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
}
.detail-title {
  margin: 0;
  font-size: 13px;
  color: var(--text-primary);
}
.detail-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.detail-table th,
.detail-table td {
  padding: 6px 8px;
  border-bottom: 1px solid var(--border-color);
  text-align: left;
}
.detail-table th {
  color: var(--text-secondary, #9aa5b1);
  font-weight: 400;
  width: 110px;
}
.detail-table td {
  color: var(--text-primary);
}
.detail-table td.flags { color: #f5c15b; }
.detail-table td.trend-up { color: #f55b5b; }
.detail-table td.trend-down { color: #4caf7d; }
.tree-empty {
  padding: 16px;
  text-align: center;
  color: var(--text-secondary, #9aa5b1);
  font-size: 13px;
}
</style>
