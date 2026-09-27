<template>
  <div class="sector-rotation-tree">
    <div class="tree-toolbar">
      <h4 class="tree-title">🔄 轮动题材列表</h4>
      <span class="tree-count">共 {{ statuses.length }} 个题材</span>
    </div>
    <div class="tree-layout">
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
        <div class="detail-table-wrap">
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
/* 左目录右列表两栏（SectorStocksTree 范式） */
.tree-layout {
  display: grid;
  grid-template-columns: 200px 1fr;
  gap: 10px;
  align-items: start;
}
.tree-directory {
  display: flex;
  flex-direction: column;
  gap: 6px;
  position: sticky;
  top: 0;
}
.directory-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 9px 12px;
  background: var(--bg-secondary, rgba(255, 255, 255, 0.03));
  border: 1px solid var(--border-color);
  border-radius: 8px;
  cursor: pointer;
  transition: border-color 0.15s ease;
}
.directory-item:hover {
  border-color: var(--accent-color, #4a9eff);
}
.directory-item.selected {
  border-color: var(--accent-color, #4a9eff);
  background: var(--bg-tertiary, rgba(74, 158, 255, 0.08));
}
.directory-label {
  font-size: 13px;
  color: var(--text-primary);
}
.directory-count {
  font-size: 12px;
  color: var(--text-secondary, #9aa5b1);
}
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
.detail-count {
  font-size: 12px;
  color: var(--text-secondary, #9aa5b1);
}
.detail-table-wrap {
  max-height: 480px;
  overflow-y: auto;
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
  text-align: right;
  white-space: nowrap;
}
.detail-table th {
  position: sticky;
  top: 0;
  background: var(--bg-primary, #1a1d24);
  color: var(--text-secondary, #9aa5b1);
  font-weight: 400;
}
.detail-table th:first-child,
.detail-table td:first-child {
  text-align: left;
}
.detail-table td:first-child {
  color: var(--text-primary);
}
.cell-flags { color: #f5c15b; }
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
.trend-up { color: #f55b5b; }
.trend-down { color: #4caf7d; }
.tree-empty {
  padding: 16px;
  text-align: center;
  color: var(--text-secondary, #9aa5b1);
  font-size: 13px;
}
</style>
