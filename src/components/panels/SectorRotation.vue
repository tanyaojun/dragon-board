<!-- src/components/panels/SectorRotation.vue -->
<!-- 纯响应式版本：适配新的轮动分析数据结构 -->

<template>
  <Teleport to="body">
    <div v-if="visible" class="sector-rotation-panel" :style="panelStyle" ref="panelRef">
      <!-- 头部 -->
      <div class="panel-header">
        <div class="header-left">
          <h3>
            🔄 题材轮动 <span class="version-badge">v{{ version }}</span>
            <span v-if="dataVersion" class="version-info">v{{ dataVersion }}</span>
          </h3>
          <div class="stats-badge" v-if="rotationData">
            <span>轮动速度 {{ rotationData.rotationSpeed }}%</span>
            <span class="dot">•</span>
            <span>主线 {{ rotationData.mainLines.length }}个</span>
            <span class="dot">•</span>
            <span>强势 {{ rotationData.strongThemes?.length || 0 }}个</span>
          </div>
        </div>
        <div class="panel-actions">
          <button class="btn-icon" @click.stop="refresh" :class="{ loading }" title="刷新">
            <span :class="{ 'rotate-animation': loading }">🔄</span>
          </button>
          <button class="btn-icon" @click.stop="close" title="关闭">✕</button>
        </div>
      </div>

      <!-- 标签页 -->
      <div class="panel-tabs">
        <div class="tabs-left">
          <button class="tab-btn" :class="{ active: view === 'overview' }" @click="view = 'overview'">
            📊 轮动概览
          </button>
          <button class="tab-btn" :class="{ active: view === 'main' }" @click="view = 'main'">
            👑 主线板块
            <span v-if="rotationData?.mainLines?.length" class="tab-count">{{ rotationData.mainLines.length }}</span>
          </button>
          <button class="tab-btn" :class="{ active: view === 'strong' }" @click="view = 'strong'">
            ⚡ 强势板块
            <span v-if="rotationData?.strongThemes?.length" class="tab-count">{{ rotationData.strongThemes.length
              }}</span>
          </button>
          <button class="tab-btn" :class="{ active: view === 'inflow' }" @click="view = 'inflow'">
            📈 资金流入
            <span v-if="rotationData?.inflowThemes?.length" class="tab-count">{{ rotationData.inflowThemes.length
              }}</span>
          </button>
          <button class="tab-btn" :class="{ active: view === 'outflow' }" @click="view = 'outflow'">
            📉 资金流出
            <span v-if="rotationData?.outflowThemes?.length" class="tab-count">{{ rotationData.outflowThemes.length
              }}</span>
          </button>
        </div>
      </div>

      <!-- 内容区域 -->
      <div class="panel-content" ref="contentRef">
        <!-- 加载状态 -->
        <div v-if="loading" class="loading-state">
          <div class="loading-spinner"></div>
          <span>{{ loadingMessage }}</span>
        </div>

        <!-- 错误状态 -->
        <div v-else-if="error" class="error-state">
          <span class="error-icon">⚠️</span>
          <span>{{ error }}</span>
          <button class="retry-btn" @click="loadData">重试</button>
        </div>

        <!-- 空状态 -->
        <div v-else-if="!rotationData" class="empty-state">
          <span class="empty-icon">🔄</span>
          <span>暂无轮动数据</span>
        </div>

        <template v-else>
          <!-- 轮动概览视图 -->
          <div v-if="view === 'overview'" class="overview-view">
            <!-- 市场阶段卡片 -->
            <div class="market-phase-card" :class="rotationData.marketPhase">
              <div class="phase-header">
                <span class="phase-icon">{{ getMarketPhaseIcon(rotationData.marketPhase) }}</span>
                <span class="phase-name">{{ getMarketPhaseName(rotationData.marketPhase) }}</span>
                <span class="phase-speed">轮动速度 {{ rotationData.rotationSpeed }}%</span>
              </div>
              <div class="phase-suggestion">{{ rotationData.summary.suggestion }}</div>
            </div>

            <!-- 轮动仪表盘 -->
            <div class="dashboard-grid">
              <div class="dashboard-card">
                <div class="card-title">主线数量</div>
                <div class="card-value" style="color: #ffd700">{{ rotationData.mainLines.length }}</div>
              </div>
              <div class="dashboard-card">
                <div class="card-title">强势板块</div>
                <div class="card-value" style="color: #ff7f50">{{ rotationData.strongThemes?.length || 0 }}</div>
              </div>
              <div class="dashboard-card">
                <div class="card-title">流入板块</div>
                <div class="card-value" style="color: #ff4757">{{ rotationData.inflowThemes.length }}</div>
              </div>
              <div class="dashboard-card">
                <div class="card-title">流出板块</div>
                <div class="card-value" style="color: #3498db">{{ rotationData.outflowThemes.length }}</div>
              </div>
            </div>

            <!-- 轮动总结 -->
            <div class="summary-grid">
              <div class="summary-card" @click="showSectorDetail(rotationData.summary.topInflow)">
                <span class="summary-label">📈 流入榜首</span>
                <span class="summary-value">{{ rotationData.summary.topInflow }}</span>
                <span class="summary-money inflow">+{{ formatMoney(rotationData.inflowThemes[0]?.netInflow) }}</span>
              </div>
              <div class="summary-card" @click="showSectorDetail(rotationData.summary.topOutflow)">
                <span class="summary-label">📉 流出榜首</span>
                <span class="summary-value">{{ rotationData.summary.topOutflow }}</span>
                <span class="summary-money outflow">{{ formatMoney(rotationData.outflowThemes[0]?.netInflow) }}</span>
              </div>
              <div class="summary-card" @click="showSectorDetail(rotationData.summary.topStrength)">
                <span class="summary-label">⚡ 最强板块</span>
                <span class="summary-value">{{ rotationData.summary.topStrength }}</span>
                <span class="summary-score">{{ rotationData.strongThemes?.[0]?.strengthScore || 0 }}分</span>
              </div>
            </div>

            <!-- 主线板块预览 -->
            <div class="preview-section" v-if="rotationData.mainLines.length">
              <div class="section-header">
                <span class="section-title">👑 主线板块</span>
                <span class="section-count">{{ rotationData.mainLines.length }}</span>
              </div>
              <div class="preview-grid">
                <div v-for="item in rotationData.mainLines.slice(0, 3)" :key="item.themeId" class="preview-card"
                  @click="showSectorDetail(item.themeName)">
                  <div class="preview-name">{{ item.themeName }}</div>
                  <div class="preview-flow inflow">+{{ formatMoney(item.netInflow) }}</div>
                  <div class="preview-meta">
                    <span class="preview-days">{{ item.persistentDays }}天</span>
                    <span class="preview-score">{{ item.strengthScore }}分</span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- 主线板块视图 -->
          <div v-if="view === 'main'" class="list-view">
            <div v-if="rotationData.mainLines.length === 0" class="empty-list">
              暂无主线板块
            </div>
            <div v-else v-for="item in rotationData.mainLines" :key="item.themeId" class="list-item mainline"
              @click="showSectorDetail(item.themeName)">
              <div class="item-header">
                <span class="item-name">{{ item.themeName }}</span>
                <span class="item-days">{{ item.persistentDays }}天</span>
              </div>
              <div class="item-flow">
                <span class="flow-value inflow">+{{ formatMoney(item.netInflow) }}</span>
                <span class="flow-label">净流入</span>
              </div>
              <div class="item-stats">
                <span>📈 {{ item.ztCount }}涨停</span>
                <span>⚡ {{ item.strengthScore }}分</span>
                <span>📊 量比 {{ item.volumeRatio?.toFixed(2) }}</span>
              </div>
              <div class="item-rank-change" v-if="item.rankChange !== 0"
                :class="{ up: item.rankChange > 0, down: item.rankChange < 0 }">
                {{ formatRankChange(item.rankChange) }}
              </div>
            </div>
          </div>

          <!-- 强势板块视图 -->
          <div v-if="view === 'strong'" class="list-view">
            <div v-if="!rotationData.strongThemes?.length" class="empty-list">
              暂无强势板块
            </div>
            <div v-else v-for="item in rotationData.strongThemes" :key="item.themeId" class="list-item strong"
              @click="showSectorDetail(item.themeName)">
              <div class="item-header">
                <span class="item-name">{{ item.themeName }}</span>
                <span class="item-score">{{ item.strengthScore }}分</span>
              </div>
              <div class="item-stats-grid">
                <div class="stat">
                  <span class="stat-label">强度</span>
                  <span class="stat-value">{{ item.strengthScore }}</span>
                </div>
                <div class="stat">
                  <span class="stat-label">涨停</span>
                  <span class="stat-value">{{ getThemeMetric(item, 'ztCount') }}</span>
                </div>
                <div class="stat">
                  <span class="stat-label">量比</span>
                  <span class="stat-value">{{ getThemeMetric(item, 'volumeRatio').toFixed(2) }}</span>
                </div>
              </div>
              <div class="item-flow">
                <span class="flow-value" :class="getThemeMetric(item, 'netInflow') > 0 ? 'inflow' : 'outflow'">
                  {{ formatMoney(getThemeMetric(item, 'netInflow')) }}
                </span>
              </div>
            </div>
          </div>

          <!-- 资金流入视图 -->
          <div v-if="view === 'inflow'" class="list-view">
            <div v-if="rotationData.inflowThemes.length === 0" class="empty-list">
              暂无资金流入板块
            </div>
            <div v-else v-for="item in rotationData.inflowThemes" :key="item.themeId" class="list-item inflow"
              @click="showSectorDetail(item.themeName)">
              <div class="item-header">
                <span class="item-name">{{ item.themeName }}</span>
                <span class="item-rank" v-if="item.rankChange !== 0" :class="{ up: item.rankChange > 0 }">
                  ↑{{ Math.abs(item.rankChange) }}
                </span>
              </div>
              <div class="item-flow-large">
                <span class="flow-value inflow">+{{ formatMoney(item.netInflow) }}</span>
              </div>
              <div class="item-stats">
                <span>💪 强度 {{ item.strength }}</span>
                <span>📈 涨停 {{ item.ztCount }}</span>
                <span>📊 涨幅 {{ (item.avgChange || 0).toFixed(2) }}%</span>
              </div>
              <div class="item-fund-change" v-if="item.inflowChange">
                <span :class="item.inflowChange > 0 ? 'up' : 'down'">
                  资金 {{ item.inflowChange > 0 ? '+' : '' }}{{ item.inflowChange }}%
                </span>
              </div>
            </div>
          </div>

          <!-- 资金流出视图 -->
          <div v-if="view === 'outflow'" class="list-view">
            <div v-if="rotationData.outflowThemes.length === 0" class="empty-list">
              暂无资金流出板块
            </div>
            <div v-else v-for="item in rotationData.outflowThemes" :key="item.themeId" class="list-item outflow"
              @click="showSectorDetail(item.themeName)">
              <div class="item-header">
                <span class="item-name">{{ item.themeName }}</span>
                <span class="item-rank" v-if="item.rankChange !== 0" :class="{ down: item.rankChange < 0 }">
                  ↓{{ Math.abs(item.rankChange) }}
                </span>
              </div>
              <div class="item-flow-large">
                <span class="flow-value outflow">{{ formatMoney(item.netInflow) }}</span>
              </div>
              <div class="item-stats">
                <span>💪 强度 {{ item.strength }}</span>
                <span>📈 涨停 {{ item.ztCount }}</span>
                <span>📊 涨幅 {{ (item.avgChange || 0).toFixed(2) }}%</span>
              </div>
            </div>
          </div>
        </template>
      </div>

      <!-- 底部统计 -->
      <div class="panel-footer" v-if="!loading && !error && rotationData">
        <div class="footer-left">
          <span>📊 更新时间: {{ formatTime(rotationData.timestamp) }}</span>
        </div>
        <div class="footer-right">
          <span>⚡ 强势: {{ rotationData.summary.strongCount || 0 }}</span>
          <span class="dot">•</span>
          <span>📈 流入: {{ rotationData.summary.inflowCount }}</span>
          <span class="dot">•</span>
          <span>📉 流出: {{ rotationData.summary.outflowCount }}</span>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { dataLayer } from '@/services/DataLayer'
import { themeFacade } from '@/services/theme/ThemeFacade'
import { usePanel } from '@/composables/usePanel'
import type { RotationAnalysis } from '@/types/core'
import { useThemeRuntimeSnapshot } from '@/composables/useThemeRuntimeSnapshot'

const props = defineProps<{
  visible: boolean
  triggerRect?: DOMRect
}>()

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'close'): void
  (e: 'show-detail', sectorName: string): void
}>()

// ========== 版本号 ==========
const version = '5.0.0'

// ========== 视图状态 ==========
const view = ref<'overview' | 'main' | 'strong' | 'inflow' | 'outflow'>('overview')
const loading = ref(false)
const error = ref<string | null>(null)
const themeRuntime = useThemeRuntimeSnapshot()

// ========== 面板位置 ==========
const { panelRef, panelStyle } = usePanel({
  name: 'SectorRotation',
  visible: props.visible,
  triggerRect: props.triggerRect,
  triggerSelectors: ['[title*="轮动"]', '[title*="题材轮动"]'],
  onClose: close,
})

// ========== 核心数据 - 从 dataLayer 获取 ==========

// 轮动数据
const rotationData = computed(() => {
  const state = (dataLayer as any).state
  return themeRuntime.value.rotationSummary || themeFacade.getRotationSummary() || (state?.analysis?.rotation?.current as RotationAnalysis | null)
})

// 数据版本
const dataVersion = computed(() => dataLayer.getVersion().themes)

// ========== 加载数据 ==========
const loadData = async () => {
  loading.value = true
  error.value = null

  themeFacade.refresh({ emitAlerts: false })

  await new Promise(resolve => setTimeout(resolve, 300))

  if (!rotationData.value) {
    error.value = '暂无轮动数据'
  }

  loading.value = false
}

const loadingMessage = computed(() => loading.value ? '加载轮动数据...' : '')

// ========== 操作函数 ==========
function refresh() {
  dataLayer.refreshStocksVersion()
  themeFacade.refresh({ emitAlerts: false })
  loadData()
}

function close() {
  emit('update:visible', false)
  emit('close')
}

function showSectorDetail(sectorName: string) {
  emit('show-detail', sectorName)
}

// ========== 工具函数 ==========

// 市场阶段图标
function getMarketPhaseIcon(phase: string): string {
  const icons: Record<string, string> = {
    ice: '❄️',
    accumulation: '🏗️',
    rising: '📈',
    climax: '⚡',
    distribution: '📊',
    falling: '📉'
  }
  return icons[phase] || '🔄'
}

// 市场阶段名称
function getMarketPhaseName(phase: string): string {
  const names: Record<string, string> = {
    ice: '冰点期',
    accumulation: '筑底期',
    rising: '上升期',
    climax: '高潮期',
    distribution: '出货期',
    falling: '退潮期'
  }
  return names[phase] || phase
}

// 金额格式化
function formatMoney(value: number): string {
  if (!value && value !== 0) return '-'
  const absValue = Math.abs(value)
  if (absValue >= 100000000) {
    return (value / 100000000).toFixed(2) + '亿'
  }
  if (absValue >= 10000) {
    return (value / 10000).toFixed(2) + '万'
  }
  return value.toString()
}

// 时间格式化
function formatTime(timestamp: number): string {
  if (!timestamp) return '--:--'
  const date = new Date(timestamp)
  return `${date.getHours().toString().padStart(2, '0')}:${date.getMinutes().toString().padStart(2, '0')}`
}

// 排名变化格式化
function formatRankChange(change: number): string {
  if (change > 0) return `↑${change}`
  if (change < 0) return `↓${Math.abs(change)}`
  return '='
}

function getThemeMetric(item: unknown, key: string): number {
  const value = (item as Record<string, unknown>)?.[key]
  return Number(value) || 0
}

// ========== 生命周期 ==========
onMounted(() => {
  if (props.visible) {
    loadData()
  }
})

onUnmounted(() => {
  // 清理工作
})
</script>

<style scoped>
/* 样式保持不变，添加新样式 */
.version-info {
  margin-left: 4px;
  padding: 0 4px;
  background: var(--bg-primary);
  border-radius: 4px;
  font-size: 9px;
  color: var(--text-secondary);
}

.sector-rotation-panel {
  position: fixed;
  width: 560px;
  max-width: calc(100vw - 40px);
  max-height: 80vh;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
  z-index: 10006;
  font-size: 12px;
  overflow: hidden;
  backdrop-filter: blur(10px);
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-header);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.panel-header h3 {
  margin: 0;
  font-size: 16px;
  color: var(--color-highlight);
  display: flex;
  align-items: center;
  gap: 8px;
}

.version-badge {
  font-size: 10px;
  background: var(--color-highlight);
  color: #000;
  padding: 2px 6px;
  border-radius: 12px;
}

.stats-badge {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 20px;
  font-size: 10px;
  color: var(--text-secondary);
}

.dot {
  opacity: 0.5;
}

.panel-actions {
  display: flex;
  gap: 8px;
}

.btn-icon {
  width: 32px;
  height: 32px;
  border: 1px solid var(--border-color);
  background: transparent;
  border-radius: 8px;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 16px;
  transition: all 0.2s;
}

.btn-icon:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
  border-color: var(--color-highlight);
}

.panel-tabs {
  display: flex;
  gap: 4px;
  padding: 12px 20px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-secondary);
}

.tabs-left {
  display: flex;
  gap: 4px;
  flex: 1;
}

.tab-btn {
  flex: 1;
  padding: 8px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  border-radius: 8px;
  font-size: 12px;
  transition: all 0.2s;
  position: relative;
}

.tab-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.tab-btn.active {
  background: var(--color-highlight);
  color: #000;
  font-weight: 500;
}

.tab-count {
  margin-left: 4px;
  padding: 0 4px;
  background: rgba(0, 0, 0, 0.1);
  border-radius: 8px;
  font-size: 9px;
}

.panel-content {
  padding: 20px;
  max-height: calc(80vh - 120px);
  overflow-y: auto;
}

/* 概览视图 */
.overview-view {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.market-phase-card {
  padding: 16px;
  border-radius: 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-left-width: 4px;
}

.market-phase-card.ice {
  border-left-color: #7f8c8d;
}

.market-phase-card.accumulation {
  border-left-color: #95a5a6;
}

.market-phase-card.rising {
  border-left-color: #e74c3c;
}

.market-phase-card.climax {
  border-left-color: #ff4757;
}

.market-phase-card.distribution {
  border-left-color: #f39c12;
}

.market-phase-card.falling {
  border-left-color: #3498db;
}

.phase-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.phase-icon {
  font-size: 20px;
}

.phase-name {
  font-size: 14px;
  font-weight: 500;
}

.phase-speed {
  margin-left: auto;
  font-size: 11px;
  color: var(--text-secondary);
}

.phase-suggestion {
  font-size: 12px;
  color: var(--text-primary);
  line-height: 1.5;
}

.dashboard-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
}

.dashboard-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 10px;
}

.card-title {
  font-size: 10px;
  color: var(--text-secondary);
  margin-bottom: 4px;
}

.card-value {
  font-size: 20px;
  font-weight: bold;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
}

.summary-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.2s;
}

.summary-card:hover {
  background: var(--bg-hover);
  border-color: var(--color-highlight);
}

.summary-label {
  font-size: 10px;
  color: var(--text-secondary);
}

.summary-value {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-title);
}

.summary-money {
  font-size: 11px;
  font-weight: 500;
}

.summary-money.inflow {
  color: #ff4757;
}

.summary-money.outflow {
  color: #3498db;
}

.summary-score {
  font-size: 11px;
  color: #ffd700;
}

.preview-section {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 16px;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.section-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-title);
}

.section-count {
  padding: 2px 8px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  font-size: 10px;
}

.preview-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
}

.preview-card {
  padding: 12px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
}

.preview-card:hover {
  background: var(--bg-hover);
  border-color: var(--color-highlight);
}

.preview-name {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-title);
  margin-bottom: 4px;
}

.preview-flow {
  font-size: 13px;
  font-weight: bold;
  margin-bottom: 4px;
}

.preview-flow.inflow {
  color: #ff4757;
}

.preview-meta {
  display: flex;
  justify-content: space-between;
  font-size: 10px;
  color: var(--text-secondary);
}

/* 列表视图 */
.list-view {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.list-item {
  position: relative;
  padding: 16px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.2s;
  border-left-width: 4px;
}

.list-item:hover {
  background: var(--bg-hover);
  border-color: var(--color-highlight);
}

.list-item.mainline {
  border-left-color: #ffd700;
}

.list-item.strong {
  border-left-color: #ff7f50;
}

.list-item.inflow {
  border-left-color: #ff4757;
}

.list-item.outflow {
  border-left-color: #3498db;
}

.item-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.item-name {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-title);
}

.item-days,
.item-score,
.item-rank {
  font-size: 10px;
  padding: 2px 6px;
  background: var(--bg-primary);
  border-radius: 10px;
  color: var(--text-secondary);
}

.item-rank.up {
  color: #ff4757;
}

.item-rank.down {
  color: #3498db;
}

.item-flow {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-bottom: 8px;
}

.item-flow-large {
  margin-bottom: 8px;
}

.flow-value {
  font-size: 16px;
  font-weight: bold;
}

.flow-value.inflow {
  color: #ff4757;
}

.flow-value.outflow {
  color: #3498db;
}

.flow-label {
  font-size: 10px;
  color: var(--text-secondary);
}

.item-stats {
  display: flex;
  gap: 12px;
  font-size: 11px;
  color: var(--text-secondary);
}

.item-stats-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  margin-bottom: 8px;
}

.stat {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.stat-label {
  font-size: 9px;
  color: var(--text-secondary);
}

.stat-value {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-title);
}

.item-rank-change {
  position: absolute;
  top: 12px;
  right: 12px;
  font-size: 11px;
  font-weight: 500;
}

.item-rank-change.up {
  color: #ff4757;
}

.item-rank-change.down {
  color: #3498db;
}

.item-fund-change {
  font-size: 10px;
  text-align: right;
}

.item-fund-change .up {
  color: #ff4757;
}

.item-fund-change .down {
  color: #2ed573;
}

.empty-list {
  padding: 40px;
  text-align: center;
  color: var(--text-secondary);
  background: var(--bg-secondary);
  border-radius: 10px;
}

/* 底部 */
.panel-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 20px;
  border-top: 1px solid var(--border-color);
  background: var(--bg-header);
  font-size: 10px;
  color: var(--text-secondary);
}

.footer-right {
  display: flex;
  align-items: center;
  gap: 4px;
}

/* 加载状态 */
.loading-state,
.empty-state,
.error-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  gap: 16px;
}

.loading-spinner {
  width: 40px;
  height: 40px;
  border: 3px solid var(--border-color);
  border-top-color: var(--color-highlight);
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

.empty-icon,
.error-icon {
  font-size: 32px;
  opacity: 0.5;
}

.retry-btn {
  padding: 8px 16px;
  background: var(--color-highlight);
  border: none;
  border-radius: 20px;
  color: #000;
  font-size: 12px;
  cursor: pointer;
}

.rotate-animation {
  animation: rotate 1s infinite linear;
  display: inline-block;
}

@keyframes rotate {
  from {
    transform: rotate(0deg);
  }

  to {
    transform: rotate(360deg);
  }
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
