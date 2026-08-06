<!-- src/components/panels/ThemeMomentumPanel.vue -->
<!-- 题材动量 v2 独立面板：全字段排行榜 + 行展开（spec D6） -->

<template>
  <Teleport to="body">
    <div v-if="visible" class="theme-momentum-panel" :style="panelStyle" ref="panelRef">
      <div class="panel-header">
        <div class="header-left">
          <h3>
            📊 题材动量 <span class="version-badge">v{{ version }}</span>
            <span v-if="summary?.version" class="version-info">{{ summary.version }}</span>
            <span v-if="computedAtText" class="rotation-time-badge" :title="`计算时间: ${computedAtText}`">
              🕒 {{ computedAtText }}
            </span>
          </h3>
          <div class="stats-badge" v-if="summary">
            <span>强势 {{ stats.up }} 个</span>
            <span class="dot">·</span>
            <span>退潮 {{ stats.down }} 个</span>
            <span class="dot">·</span>
            <span>中性 {{ stats.neutral }} 个</span>
          </div>
        </div>
        <div class="panel-actions">
          <button class="btn-icon" @click.stop="loadData(true)" :class="{ loading }" title="刷新">
            <span :class="{ 'rotate-animation': loading }">🔄</span>
          </button>
          <button class="btn-icon" @click.stop="close" title="关闭">✕</button>
        </div>
      </div>

      <div class="panel-content" ref="contentRef">
        <div v-if="loading" class="loading-state">
          <div class="loading-spinner"></div>
          <span>加载题材动量…</span>
        </div>
        <div v-else-if="error" class="error-state">
          <span class="error-icon">⚠️</span>
          <span>{{ error }}</span>
          <button class="retry-btn" @click="loadData(true)">重试</button>
        </div>
        <div v-else-if="!summary" class="empty-state">
          <span class="empty-icon">🔄</span>
          <span>暂无题材动量数据</span>
        </div>

        <template v-else>
          <div v-if="summary.qualityFlags.length" class="quality-flags">
            <span v-for="flag in summary.qualityFlags" :key="flag" class="quality-tag">{{ flag }}</span>
          </div>

          <table class="momentum-table">
            <thead>
              <tr>
                <th>题材</th>
                <th>动量分</th>
                <th>方向</th>
                <th>阶段</th>
                <th>RPS 5/10/20</th>
                <th>距高点</th>
                <th>资金量能</th>
                <th>拥挤扣分</th>
              </tr>
            </thead>
            <tbody>
              <template v-for="factor in sortedFactors" :key="factor.themeId">
                <tr :class="['momentum-row', directionClass(factor.direction)]" @click="toggle(factor.themeId)">
                  <td class="theme-name">{{ factor.themeName }}</td>
                  <td class="score-cell">{{ factor.score ?? '--' }}</td>
                  <td><span class="direction-badge" :class="directionClass(factor.direction)">
                    {{ directionText(factor.direction) }}</span></td>
                  <td>{{ factor.phaseLabel || '—' }}</td>
                  <td class="rps-cell">
                    <span class="rps-value" :class="rpsTone(factor.rps?.d5)">{{ factor.rps?.d5 ?? '--' }}</span>
                    <span class="rps-sep">/</span>
                    <span class="rps-value" :class="rpsTone(factor.rps?.d10)">{{ factor.rps?.d10 ?? '--' }}</span>
                    <span class="rps-sep">/</span>
                    <span class="rps-value" :class="rpsTone(factor.rps?.d20)">{{ factor.rps?.d20 ?? '--' }}</span>
                  </td>
                  <td>{{ factor.nearHigh ?? '--' }}</td>
                  <td>{{ factor.flowVolume ?? '--' }}</td>
                  <td class="penalty-cell" :class="{ penalized: (factor.crowdingPenalty ?? 0) > 0 }">
                    {{ factor.crowdingPenalty ?? '--' }}</td>
                </tr>
                <tr v-if="expanded.has(factor.themeId)" class="detail-row">
                  <td colspan="8">
                    <div class="detail-grid">
                      <div class="detail-block">
                        <h4>多窗口动量</h4>
                        <p>5日 {{ fmtNum(factor.windowMomentum) }}</p>
                      </div>
                      <div class="detail-block">
                        <h4>整体性</h4>
                        <p>宽度/一致性 {{ factor.breadth ?? '--' }}</p>
                      </div>
                      <div class="detail-block">
                        <h4>日内状态</h4>
                        <p>短变化 {{ factor.intraday?.shortChange ?? '--' }}</p>
                        <p>涨停增量 {{ factor.intraday?.ztDelta ?? '--' }}</p>
                        <p>资金增量 {{ factor.intraday?.inflowDelta ?? '--' }}</p>
                      </div>
                      <div class="detail-block reasons">
                        <h4>依据</h4>
                        <ul>
                          <li v-for="(reason, index) in (factor.reasons || [])" :key="index">{{ reason }}</li>
                          <li v-if="!(factor.reasons || []).length">—</li>
                        </ul>
                      </div>
                    </div>
                  </td>
                </tr>
              </template>
            </tbody>
          </table>
        </template>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'

import { usePanel } from '@/composables/usePanel'
import {
  themeFacade,
  type ThemeMomentumSummary,
  type ThemeMomentumSummaryFactor,
} from '@/services/theme/ThemeFacade'
import { DEFAULT_RANK_TREND_SNAPSHOT_TYPE } from '@/types/rankTrendDefaults'

const props = defineProps<{
  visible: boolean
  triggerRect?: DOMRect
}>()

const emit = defineEmits<{ (event: 'close'): void }>()

const version = '1.0.0'
const contentRef = ref<HTMLElement | null>(null)
const { panelRef, panelStyle } = usePanel({
  name: 'ThemeMomentumPanel',
  visible: props.visible,
  triggerRect: props.triggerRect,
  onClose: close,
})

const loading = ref(false)
const error = ref<string | null>(null)
const summary = ref<ThemeMomentumSummary | null>(null)
const expanded = ref<Set<string>>(new Set())

const sortedFactors = computed<ThemeMomentumSummaryFactor[]>(() =>
  [...(summary.value?.factors || [])].sort((a, b) => (b.score ?? -1) - (a.score ?? -1)),
)

const stats = computed(() => {
  const factors = summary.value?.factors || []
  return {
    up: factors.filter((f) => f.direction === 'up').length,
    down: factors.filter((f) => f.direction === 'down').length,
    neutral: factors.filter((f) => f.direction === 'neutral').length,
  }
})

const computedAtText = computed(() => {
  const ts = summary.value?.computedAt
  if (!ts) return ''
  const date = new Date(ts)
  if (Number.isNaN(date.getTime())) return ''
  return `${date.getMonth() + 1}-${date.getDate()} ${String(date.getHours()).padStart(2, '0')}:${String(
    date.getMinutes(),
  ).padStart(2, '0')}`
})

async function loadData(force = false) {
  if (loading.value && !force) return
  loading.value = true
  error.value = null
  try {
    const result = await themeFacade.getThemeMomentumSummary({
      snapshotType: DEFAULT_RANK_TREND_SNAPSHOT_TYPE,
    })
    if (result) summary.value = result
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

function toggle(themeId: string) {
  const next = new Set(expanded.value)
  if (next.has(themeId)) next.delete(themeId)
  else next.add(themeId)
  expanded.value = next
}

function close() {
  emit('close')
}

function directionClass(direction?: string): string {
  return direction === 'up' ? 'positive-tone' : direction === 'down' ? 'negative-tone' : 'neutral-tone'
}

function directionText(direction?: string): string {
  return direction === 'up' ? '上行' : direction === 'down' ? '下行' : '中性'
}

function rpsTone(value?: number | null): string {
  if (value == null) return ''
  return value >= 80 ? 'rps-strong' : value >= 50 ? 'rps-mid' : 'rps-weak'
}

function fmtNum(value?: number | null): string {
  return value == null ? '--' : String(value)
}

onMounted(() => {
  if (props.visible) loadData()
})

onUnmounted(() => {
  /* Teleport 面板随 visible 卸载 */
})
</script>

<style scoped>
.theme-momentum-panel {
  position: fixed;
  z-index: 1001;
  width: 860px;
  max-width: calc(100vw - 32px);
  max-height: min(78vh, 720px);
  background: #14161c;
  border: 1px solid #2a2d36;
  border-radius: 12px;
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.5);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  color: #d7dae0;
  font-size: 13px;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid #2a2d36;
  background: #191c24;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

h3 {
  margin: 0;
  font-size: 14px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.version-badge {
  font-size: 10px;
  background: #2f3542;
  color: #9aa3b2;
  border-radius: 4px;
  padding: 1px 5px;
  vertical-align: middle;
}

.version-info {
  font-size: 10px;
  color: #6c7a8d;
  font-family: monospace;
}

.rotation-time-badge {
  font-size: 11px;
  color: #8b96a5;
}

.stats-badge {
  display: flex;
  gap: 6px;
  font-size: 12px;
  color: #9aa3b2;
}

.dot {
  color: #4a5260;
}

.panel-actions {
  display: flex;
  gap: 6px;
}

.btn-icon {
  background: #23262e;
  border: 1px solid #2f3542;
  color: #9aa3b2;
  border-radius: 6px;
  width: 26px;
  height: 26px;
  cursor: pointer;
  font-size: 13px;
}

.btn-icon:hover {
  background: #2f3542;
  color: #fff;
}

.rotate-animation {
  display: inline-block;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.panel-content {
  overflow-y: auto;
  padding: 12px 16px;
  flex: 1;
}

.loading-state,
.error-state,
.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 48px 0;
  color: #8b96a5;
}

.loading-spinner {
  width: 18px;
  height: 18px;
  border: 2px solid #2f3542;
  border-top-color: #f39c12;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

.error-icon,
.empty-icon {
  font-size: 20px;
}

.retry-btn {
  background: #2f3542;
  color: #fff;
  border: none;
  border-radius: 6px;
  padding: 4px 12px;
  cursor: pointer;
}

.quality-flags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 10px;
}

.quality-tag {
  font-size: 10px;
  background: #3a2417;
  color: #e8a87c;
  border-radius: 4px;
  padding: 2px 6px;
}

.momentum-table {
  width: 100%;
  border-collapse: collapse;
}

.momentum-table th {
  font-size: 11px;
  color: #6c7a8d;
  font-weight: 500;
  text-align: left;
  padding: 6px 8px;
  border-bottom: 1px solid #2a2d36;
  white-space: nowrap;
}

.momentum-table td {
  padding: 7px 8px;
  border-bottom: 1px solid #23262e;
  white-space: nowrap;
}

.momentum-row {
  cursor: pointer;
}

.momentum-row:hover {
  background: #1c2028;
}

.theme-name {
  color: #eef0f3;
  font-weight: 500;
}

.score-cell {
  font-family: monospace;
  font-size: 13px;
  font-weight: 600;
}

.positive-tone {
  color: #ff6b6b;
}

.negative-tone {
  color: #4ecdc4;
}

.neutral-tone {
  color: #8b96a5;
}

.direction-badge {
  display: inline-block;
  font-size: 11px;
  border-radius: 4px;
  padding: 1px 6px;
  background: #23262e;
}

.rps-cell {
  font-family: monospace;
}

.rps-sep {
  color: #4a5260;
  margin: 0 2px;
}

.rps-strong {
  color: #ff6b6b;
}

.rps-mid {
  color: #f39c12;
}

.rps-weak {
  color: #4ecdc4;
}

.penalty-cell.penalized {
  color: #e8a87c;
}

.detail-row td {
  background: #171a21;
  padding: 0;
}

.detail-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  padding: 12px 16px;
}

.detail-block h4 {
  margin: 0 0 6px;
  font-size: 11px;
  color: #6c7a8d;
  font-weight: 500;
}

.detail-block p {
  margin: 2px 0;
  font-size: 12px;
}

.detail-block.reasons ul {
  margin: 0;
  padding-left: 16px;
  font-size: 12px;
}

@media (max-width: 720px) {
  .detail-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
