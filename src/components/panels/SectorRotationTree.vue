<template>
  <div class="sector-rotation-tree">
    <div class="rotation-toolbar">
      <h4 class="tree-title">🔄 轮动题材列表</h4>
      <span class="tree-count">共 {{ statuses.length }} 个题材</span>
    </div>
    <div class="tree-body">
      <!-- 左：固定四目录（全部/流入/流出/中性） -->
      <div class="tree-directory">
        <div
          v-for="entry in directory"
          :key="entry.key"
          class="directory-item"
          :class="{ selected: category === entry.key }"
          @click="emit('update:category', entry.key)"
        >
          <span class="directory-label">{{ entry.label }}</span>
          <span class="directory-count">{{ entry.count }}</span>
        </div>
      </div>

      <!-- 右：该目录下题材的轮动明细表 -->
      <div class="tree-detail">
        <div class="detail-header">
          <h4 class="detail-title">{{ categoryLabel }} · 题材轮动明细</h4>
          <span class="detail-count">{{ categoryRows.length }} 个题材</span>
        </div>
        <table class="detail-table">
          <thead>
            <tr>
              <th>题材</th>
              <th>轮动状态</th>
              <th>轮动分</th>
              <th>热度排名</th>
              <th>排名变化</th>
              <th>强度</th>
              <th>资金</th>
              <th>广度</th>
              <th>拥挤</th>
              <th>净流入趋势</th>
              <th>质量标记</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in categoryRows" :key="row.entityKey">
              <td class="cell-name">{{ row.entityName }}</td>
              <td><span class="state-badge" :class="stateToneOf(row.rotationState)">{{ stateLabelOf(row.rotationState) }}</span></td>
              <td>{{ formatNumber(row.rotationScore, 1) }}</td>
              <td>{{ row.rank ?? '—' }}</td>
              <td :class="trendClass(row.rankChange)">{{ formatSigned(row.rankChange) }}</td>
              <td>{{ formatNumber(row.factorBreakdown?.strength, 1) }}</td>
              <td>{{ formatNumber(row.factorBreakdown?.flow, 1) }}</td>
              <td>{{ formatNumber(row.factorBreakdown?.breadth, 1) }}</td>
              <td>{{ formatNumber(row.factorBreakdown?.crowding, 1) }}</td>
              <td :class="trendClass(row.flowTrend)">{{ formatFlowTrend(row.flowTrend) }}</td>
              <td class="cell-flags">{{ row.qualityFlags?.length ? row.qualityFlags.join(',') : '—' }}</td>
            </tr>
            <tr v-if="!categoryRows.length">
              <td colspan="11" class="tree-empty">该目录下无题材</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { ThemeRotationStatusRow } from '@/services/theme/ThemeFacade'
import { rotationStateLabel, ROTATION_STATE_META, type RotationCategory } from '@/services/theme/rotationDisplay'

const props = defineProps<{
  statuses: ThemeRotationStatusRow[]
  category: RotationCategory
}>()

const emit = defineEmits<{ (e: 'update:category', value: RotationCategory): void }>()

// 固定四目录（2026-09-27 用户定版）：全部/流入/流出/中性
const DIRECTORY: { key: RotationCategory; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'inflow', label: '流入' },
  { key: 'outflow', label: '流出' },
  { key: 'neutral', label: '中性' },
]

const directory = computed(() =>
  DIRECTORY.map((entry) => ({
    ...entry,
    count:
      entry.key === 'all'
        ? props.statuses.length
        : props.statuses.filter((row) => row.rotationState === entry.key).length,
  })),
)

const categoryRows = computed(() =>
  props.category === 'all'
    ? props.statuses
    : props.statuses.filter((row) => row.rotationState === props.category),
)

const categoryLabel = computed(
  () => DIRECTORY.find((entry) => entry.key === props.category)?.label ?? '全部',
)

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
/* 样式对齐 SectorStocksTree：同款容器/卡片/表格语言（--color-highlight 橙色选中系） */
.sector-rotation-tree {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 480px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  overflow: hidden;
}
.rotation-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  border-bottom: 1px solid var(--border-color);
}
.tree-title {
  margin: 0;
  font-size: 14px;
  display: flex;
  align-items: center;
  gap: 12px;
  color: var(--text-primary);
}
.tree-count {
  font-size: 11px;
  color: var(--text-secondary);
}
.tree-body {
  flex: 1;
  display: flex;
  min-height: 0;
}
.tree-directory {
  width: 200px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px 8px;
  border-right: 1px solid var(--border-color);
  overflow-y: auto;
}
.directory-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
}
.directory-item:hover {
  background: var(--bg-hover);
  border-color: var(--color-highlight);
}
.directory-item.selected {
  border-color: var(--color-highlight);
  background: rgba(255, 127, 80, 0.1);
}
.directory-label {
  font-weight: 500;
  color: var(--text-primary);
  font-size: 13px;
}
.directory-count {
  font-size: 11px;
  color: var(--text-secondary);
}
.tree-detail {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
  padding: 12px 16px;
}
.detail-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}
.detail-title {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 0;
  font-size: 14px;
  color: var(--text-primary);
}
.detail-count {
  font-size: 11px;
  color: var(--text-secondary);
}
.detail-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.detail-table th,
.detail-table td {
  padding: 8px 10px;
  border-bottom: 1px solid var(--border-color);
  text-align: right;
  white-space: nowrap;
}
.detail-table th {
  position: sticky;
  top: 0;
  background: var(--bg-primary);
  color: var(--text-secondary);
  font-weight: 400;
  z-index: 1;
}
.detail-table th:first-child,
.detail-table td:first-child {
  text-align: left;
}
.detail-table td:first-child {
  color: var(--text-primary);
}
.detail-table tr:hover td {
  background: var(--bg-hover);
}
.cell-flags { color: #f5c15b; }
.state-badge {
  padding: 2px 8px;
  border-radius: 12px;
  border: 1px solid var(--border-color);
  font-size: 11px;
}
.state-mainline { color: #ff7f50; border-color: #ff7f50; }
.state-inflow { color: #ff4757; border-color: rgba(255, 71, 87, 0.5); }
.state-emerging { color: #5bd4f5; border-color: #5bd4f5; }
.state-neutral { color: var(--text-secondary); }
.state-outflow { color: #2ed573; border-color: rgba(46, 213, 115, 0.5); }
.state-cooling { color: #5ba3f5; border-color: rgba(91, 163, 245, 0.5); }
.state-unknown { color: var(--text-secondary); }
.trend-up { color: #ff4757; }
.trend-down { color: #2ed573; }
.tree-empty {
  padding: 16px;
  text-align: center;
  color: var(--text-secondary);
  font-size: 13px;
}
</style>
