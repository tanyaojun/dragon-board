<template>
  <Teleport to="body">
    <div v-if="visible" class="sector-rotation-panel" :style="panelStyle" ref="panelRef">
      <div class="panel-header">
        <div class="header-left">
          <button class="back-btn" @click.stop="close">← 返回</button>
          <h3>
            🔄 {{ row?.entityName || '题材轮动明细' }}
            <span class="version-badge">v1.0.0</span>
          </h3>
        </div>
        <div class="panel-actions">
          <button class="btn-icon" @click.stop="close" title="关闭">✕</button>
        </div>
      </div>

      <div class="panel-content">
        <div v-if="!row" class="empty-state">
          <div class="empty-icon">📊</div>
          <div class="empty-text">暂无轮动数据</div>
        </div>
        <template v-else>
          <div class="info-card">
            <div class="info-row">
              <span class="info-label">题材名称</span>
              <span class="info-value">{{ row.entityName }}</span>
            </div>
            <div class="info-row">
              <span class="info-label">轮动状态</span>
              <span class="state-badge" :class="stateToneOf(row.rotationState)">{{ stateLabelOf(row.rotationState) }}</span>
            </div>
            <div class="info-row">
              <span class="info-label">数据时点</span>
              <span class="info-value">{{ dataTime || '—' }}</span>
            </div>
          </div>

          <div class="metrics-grid">
            <div class="metric-card">
              <div class="metric-icon">🔄</div>
              <div class="metric-content">
                <div class="metric-label">轮动分</div>
                <div class="metric-value">{{ formatNumber(row.rotationScore, 1) }}</div>
                <div class="metric-level">0-100 相对分</div>
              </div>
            </div>
            <div class="metric-card">
              <div class="metric-icon">📊</div>
              <div class="metric-content">
                <div class="metric-label">热度排名</div>
                <div class="metric-value">{{ row.rank ?? '—' }}</div>
                <div class="metric-level" :class="trendClass(row.rankChange)">较昨日 {{ formatSigned(row.rankChange) }}</div>
              </div>
            </div>
            <div class="metric-card">
              <div class="metric-icon">💰</div>
              <div class="metric-content">
                <div class="metric-label">净流入趋势</div>
                <div class="metric-value" :class="trendClass(row.flowTrend)">{{ formatFlowTrend(row.flowTrend) }}</div>
              </div>
            </div>
          </div>

          <div class="factors-grid">
            <div v-for="factor in factorCards" :key="factor.key" class="factor-card">
              <div class="factor-label">{{ factor.label }}</div>
              <div class="factor-value">{{ formatNumber(factor.value, 1) }}</div>
              <div class="factor-progress">
                <div class="progress-bar" :style="{ width: progressWidth(factor.value) }"></div>
              </div>
            </div>
          </div>

          <div class="info-card" v-if="row.qualityFlags?.length">
            <div class="info-row">
              <span class="info-label">质量标记</span>
              <span class="info-value flags">{{ row.qualityFlags.join(', ') }}</span>
            </div>
          </div>
        </template>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { usePanel } from '../../composables/usePanel'
import type { ThemeRotationStatusRow } from '@/services/theme/ThemeFacade'
import { rotationStateLabel, ROTATION_STATE_META } from '@/services/theme/rotationDisplay'

const props = defineProps<{
  visible: boolean
  triggerRect?: DOMRect
  row: ThemeRotationStatusRow | null
  dataTime?: string
}>()

const emit = defineEmits<{ (e: 'close'): void }>()

const { panelRef, panelStyle } = usePanel({
  name: 'SectorRotationPanel',
  visible: props.visible,
  triggerRect: props.triggerRect,
  onClose: close,
})

function close() {
  emit('close')
}

const factorCards = computed(() => {
  const breakdown = props.row?.factorBreakdown
  return [
    { key: 'strength', label: '强度', value: breakdown?.strength ?? null },
    { key: 'flow', label: '资金', value: breakdown?.flow ?? null },
    { key: 'breadth', label: '广度', value: breakdown?.breadth ?? null },
    { key: 'crowding', label: '拥挤', value: breakdown?.crowding ?? null },
  ]
})

function progressWidth(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '0%'
  return `${Math.max(0, Math.min(100, value))}%`
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

function stateLabelOf(state: string | null | undefined): string {
  return rotationStateLabel(state)
}

function stateToneOf(state: string | null | undefined): string {
  return (state && ROTATION_STATE_META[state]?.tone) || 'state-unknown'
}
</script>

<style scoped>
.sector-rotation-panel {
  position: fixed;
  z-index: 3000;
  width: 420px;
  max-height: 80vh;
  overflow-y: auto;
  background: var(--bg-primary, #1a1d24);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.45);
}
.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  border-bottom: 1px solid var(--border-color);
}
.header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}
.header-left h3 {
  margin: 0;
  font-size: 14px;
  color: var(--text-primary);
}
.version-badge {
  font-size: 11px;
  color: var(--text-secondary, #9aa5b1);
  font-weight: 400;
}
.back-btn,
.btn-icon {
  background: var(--bg-tertiary, transparent);
  border: 1px solid var(--border-color);
  color: var(--text-primary);
  border-radius: 4px;
  padding: 3px 10px;
  cursor: pointer;
  font-size: 12px;
}
.back-btn:hover,
.btn-icon:hover {
  border-color: var(--accent-color, #4a9eff);
}
.panel-actions {
  display: flex;
  gap: 6px;
}
.panel-content {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px 14px;
}
.empty-state {
  padding: 24px;
  text-align: center;
  color: var(--text-secondary, #9aa5b1);
}
.info-card {
  background: var(--bg-secondary, rgba(255, 255, 255, 0.03));
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.info-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 12px;
}
.info-label {
  color: var(--text-secondary, #9aa5b1);
}
.info-value {
  color: var(--text-primary);
}
.info-value.flags {
  color: #f5c15b;
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
.metrics-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
}
.metric-card {
  background: var(--bg-secondary, rgba(255, 255, 255, 0.03));
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.metric-icon {
  font-size: 16px;
}
.metric-label {
  font-size: 11px;
  color: var(--text-secondary, #9aa5b1);
}
.metric-value {
  font-size: 18px;
  font-weight: 700;
  color: var(--text-primary);
}
.metric-level {
  font-size: 11px;
  color: var(--text-secondary, #9aa5b1);
}
.factors-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
}
.factor-card {
  background: var(--bg-secondary, rgba(255, 255, 255, 0.03));
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.factor-label {
  font-size: 11px;
  color: var(--text-secondary, #9aa5b1);
}
.factor-value {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}
.factor-progress {
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
.trend-up { color: #f55b5b !important; }
.trend-down { color: #4caf7d !important; }
</style>
