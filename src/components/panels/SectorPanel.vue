<!-- src/components/panels/SectorPanel.vue -->
<!-- 纯响应式版本：使用真实的 jxbk 数据，包含轮动和预警 -->

<template>
  <div v-if="visible" class="sector-panel" :style="combinedPanelStyle" ref="panelRef">
    <!-- 头部 -->
    <div class="panel-header">
      <div class="header-left">
        <h3>
          📊 题材分析 <span class="version-badge">v{{ version }}</span>
          <span v-if="lastUpdate" class="mapping-badge" :title="`最后更新: ${formatTime(lastUpdate)}`">
            ⏱️ {{ formatTime(lastUpdate) }}
          </span>
        </h3>
        <div class="stats-badge">
          <span>{{ jxbkBlocks.length }}个板块</span>
          <span class="dot">•</span>
          <span>{{jxbkBlocks.filter(b => b.ztCount > 0).length}}个有涨停</span>
        </div>
      </div>
      <div class="panel-actions">
        <button class="btn-icon" @click="refresh" :class="{ loading }" :disabled="loading" title="刷新">
          <span :class="{ 'rotate-animation': loading }">🔄</span>
        </button>
        <button class="btn-icon" @click="close" title="关闭">✕</button>
      </div>
    </div>

    <!-- 标签页 -->
    <div class="panel-tabs">
      <div class="tabs-left">
        <button class="tab-btn" :class="{ active: view === 'hot' }" @click="view = 'hot'">
          🔥 热门题材
          <span v-if="jxbkBlocks.length" class="tab-count">{{ jxbkBlocks.length }}</span>
        </button>
        <button class="tab-btn" :class="{ active: view === 'rotation' }" @click="view = 'rotation'">
          🔄 题材轮动
          <span v-if="rotationData" class="tab-count">{{ rotationData.rotationSpeed }}%</span>
        </button>
        <button class="tab-btn" :class="{ active: view === 'alerts' }" @click="view = 'alerts'">
          ⚠️ 实时预警
          <span v-if="alertCount > 0" class="alert-count">{{ alertCount }}</span>
        </button>
        <!-- 联动分析 -->
        <button class="tab-btn" :class="{ active: view === 'correlation' }" @click="view = 'correlation'">
          🔗 联动分析
        </button>
      </div>

      <!-- 视图模式切换 -->
      <div class="tabs-right">
        <button class="view-mode-btn" :class="{ active: viewMode === 'grid' }" @click="viewMode = 'grid'" title="网格视图">
          <span>📇</span>
        </button>
        <button class="view-mode-btn" :class="{ active: viewMode === 'tree' }" @click="viewMode = 'tree'" title="树形视图">
          <span>🌲</span>
        </button>
      </div>
    </div>

    <!-- 内容区域 -->
    <div class="panel-content">
      <!-- 加载状态 -->
      <div v-if="loading" class="loading-state">
        <div class="loading-spinner"></div>
        <span>加载数据...</span>
      </div>

      <!-- 错误状态 -->
      <div v-else-if="error" class="error-state">
        <span class="error-icon">⚠️</span>
        <span>{{ error }}</span>
        <button class="retry-btn" @click="loadData">重试</button>
      </div>

      <!-- 树形视图 -->
      <div v-else-if="view === 'hot' && viewMode === 'tree'" class="tree-view">
        <SectorStocksTree ref="treeRef" :initialSector="selectedSectorName" @select-stock="handleSelectStock"
          class="sector-tree-component" />
      </div>

      <!-- 联动分析视图 -->
      <div v-else-if="view === 'correlation'" class="correlation-view">
        <ThemeCorrelationPanel :visible="true" embedded @select-stock="handleSelectStock" @close="view = 'hot'" />
      </div>

      <!-- 热门题材视图 -->
      <div v-else-if="view === 'hot'" class="sectors-grid">
        <div v-if="jxbkBlocks.length === 0" class="empty-state">
          <span class="empty-icon">📊</span>
          <span>暂无板块数据</span>
        </div>

        <div v-for="(block, index) in jxbkBlocks" :key="block.code" class="sector-card"
          @click="showSectorDetail(block.name, $event)">

          <!-- 卡片头部 - 只有排名和名称 -->
          <div class="card-header">
            <div class="rank-wrapper" :style="{ background: getRankColor(index) }">
              <span class="rank-badge">{{ index + 1 }}</span>
            </div>
            <div class="sector-info">
              <span class="sector-name">{{ block.name }}</span>
            </div>
          </div>

          <!-- 统计数据 - 6个字段全部放在这里 -->
          <div class="stats-grid">
            <!-- 第一行：强度、涨停、主力净额 -->
            <div class="stats-row">
              <div class="stat-item">
                <span class="stat-icon">💪</span>
                <span class="stat-value">{{ block.strength }}</span>
                <span class="stat-label">强度</span>
              </div>
              <div class="stat-item">
                <span class="stat-icon">📈</span>
                <span class="stat-value">{{ block.ztCount }}</span>
                <span class="stat-label">涨停</span>
              </div>
              <div class="stat-item">
                <span class="stat-icon">💰</span>
                <span class="stat-value">{{ formatMoney(block.mainNetInflow) }}</span>
                <span class="stat-label">主力净额</span>
              </div>
            </div>

            <!-- 第二行：300W、量比、涨幅 -->
            <div class="stats-row">
              <div class="stat-item">
                <span class="stat-icon">💎</span>
                <span class="stat-value">{{ formatMoney(block.bigMoney300) }}</span>
                <span class="stat-label">300W</span>
              </div>
              <div class="stat-item">
                <span class="stat-icon">📊</span>
                <span class="stat-value">{{ block.volumeRatio.toFixed(2) }}</span>
                <span class="stat-label">量比</span>
              </div>
              <div class="stat-item">
                <span class="stat-icon">📈</span>
                <span class="stat-value" :class="block.change >= 0 ? 'up' : 'down'">
                  {{ block.change > 0 ? '+' : '' }}{{ block.change.toFixed(2) }}%
                </span>
                <span class="stat-label">涨幅</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 轮动视图 -->
      <div v-else-if="view === 'rotation'" class="rotation-view">
        <div v-if="!rotationData" class="empty-state">暂无轮动数据</div>
        <div v-else class="rotation-content">
          <!-- 市场阶段 -->
          <div class="market-phase-card" :class="rotationData.marketPhase">
            <div class="phase-header">
              <span class="phase-icon">{{ getMarketPhaseIcon(rotationData.marketPhase) }}</span>
              <span class="phase-name">{{ getMarketPhaseName(rotationData.marketPhase) }}</span>
              <span class="phase-speed">轮动速度 {{ rotationData.rotationSpeed }}%</span>
            </div>
            <div class="phase-suggestion">{{ rotationData.summary.suggestion }}</div>
          </div>

          <!-- 主线板块 -->
          <div class="rotation-section" v-if="rotationData.mainLines.length">
            <div class="section-header">
              <span class="section-title">👑 主线板块</span>
              <span class="section-count">{{ rotationData.mainLines.length }}</span>
            </div>
            <div class="rotation-items">
              <div v-for="item in rotationData.mainLines" :key="item.themeId" class="rotation-item mainline"
                @click="showSectorDetail(item.themeName, $event)">
                <div class="item-header">
                  <span class="item-name">{{ item.themeName }}</span>
                  <span class="item-days">{{ item.persistentDays || 1 }}天</span>
                </div>
                <div class="item-flow">
                  <span class="flow-value inflow" v-if="item.netInflow > 0">
                    +{{ formatMoney(item.netInflow) }}
                  </span>
                  <span class="flow-value outflow" v-else>
                    {{ formatMoney(item.netInflow) }}
                  </span>
                </div>
                <div class="item-stats">
                  <span>📈 {{ item.ztCount || 0 }}涨停</span>
                  <span class="item-days">{{ item.strengthScore }}</span>
                </div>
              </div>
            </div>
          </div>

          <!-- 如果没有主线，就不显示这个区域，而不是用资金流入冒充 -->
          <div v-else-if="!rotationData.mainLines.length && rotationData.inflowThemes.length" class="empty-hint">
            <span class="empty-icon">🔄</span>
            <span class="empty-text">暂无明确主线，市场轮动较快</span>
          </div>

          <!-- 资金流入流出概览 -->
          <div class="rotation-summary">
            <div class="summary-item">
              <span class="summary-label">📈 流入</span>
              <span class="summary-value">{{ rotationData.inflowThemes.length }}</span>
            </div>
            <div class="summary-item">
              <span class="summary-label">📉 流出</span>
              <span class="summary-value">{{ rotationData.outflowThemes.length }}</span>
            </div>
            <div class="summary-item">
              <span class="summary-label">⚡ 轮动</span>
              <span class="summary-value">{{ rotationData.quickRotation.length }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 预警视图 -->
      <div v-else-if="view === 'alerts'" class="alerts-view">
        <div v-if="alerts.length === 0" class="empty-state">✅ 暂无预警信息</div>
        <div v-else class="alerts-list">
          <div v-for="alert in alerts.slice(0, 20)" :key="alert.id" class="alert-item" :class="'alert-' + alert.level">
            <div class="alert-header">
              <span class="alert-icon">{{ getAlertIcon(alert.type) }}</span>
              <span class="alert-level">{{ alert.level }}</span>
              <span class="alert-time">{{ formatTimeAgo(alert.timestamp) }}</span>
            </div>
            <div class="alert-title">{{ alert.title }}</div>
            <div class="alert-message">{{ alert.message }}</div>
            <div class="alert-meta" v-if="alert.themeName">
              <span class="alert-theme" @click.stop="showSectorDetail(alert.themeName, $event)">
                🔗 {{ alert.themeName }}
              </span>
            </div>
          </div>
          <div v-if="alerts.length > 20" class="more-hint">
            还有 {{ alerts.length - 20 }} 条预警...
          </div>
        </div>
      </div>
    </div>

    <div class="panel-footer">
      <span>📡 数据来源: jxbk</span>
      <span>🕒 {{ formatTime(lastUpdate) }}</span>
    </div>

    <!-- 题材详情弹窗 -->
    <SectorDetail v-if="sectorDetail?.visible" :visible="sectorDetail.visible" :sectorName="sectorDetail.sectorName"
      :triggerRect="sectorDetail.triggerRect" @update:visible="handleDetailClose" />
  </div>
</template>

<script setup lang="ts">
import { debugLog } from '@/utils/logger'
import { ref, computed, onMounted } from 'vue'
import { dataLayer } from '../../services/DataLayer'
import { usePanel } from '../../composables/usePanel'
import type { RotationAnalysis, StockAlert } from '../../types/core'
import SectorStocksTree from './SectorStocksTree.vue'
import SectorDetail from './SectorDetail.vue'
import ThemeCorrelationPanel from './ThemeCorrelationPanel.vue'
import { useUIStore } from '../../stores/ui'
import { sectorAnalyzer } from '../../services/sectorAnalyzer'
import { themeFacade } from '../../services/theme/ThemeFacade'

// 状态
const viewMode = ref<'grid' | 'tree'>('grid') // 默认网格视图
const treeRef = ref<InstanceType<typeof SectorStocksTree>>()
const selectedSectorName = ref('')
const error = ref<string | null>(null)
const loading = ref(false)
const version = '6.0.0'
const view = ref<'hot' | 'rotation' | 'alerts' | 'correlation'>('hot')

// 题材详情弹窗状态
const sectorDetail = ref<{
  visible: boolean
  sectorName: string
  triggerRect?: DOMRect
} | null>(null)

// 根据视图模式计算面板宽度
const panelWidth = computed(() => {
  return viewMode.value === 'tree' ? '1200px' : '560px'
})

// 合并 usePanel 返回的样式和动态宽度
const combinedPanelStyle = computed(() => {
  return {
    ...panelStyle.value,
    width: panelWidth.value
  }
})

const props = defineProps<{
  visible: boolean
  triggerRect?: DOMRect
}>()

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'close'): void
  (e: 'show-detail', sectorName: string, event: MouseEvent): void
}>()

const { panelRef, panelStyle } = usePanel({
  name: 'SectorPanel',
  visible: props.visible,
  triggerRect: props.triggerRect,
  triggerSelectors: ['[title*="题材分析"]', '.sector-card'],
  onClose: close,
})

// ========== 数据源 ==========
const jxbkBlocks = computed(() => {
  return themeFacade.getJxbkBlocksCompat(20)
})

const lastUpdate = computed(() => {
  return themeFacade.getJxbkLastUpdate()
})

const rotationData = computed(() => {
  return themeFacade.getRotationSummary() || ((dataLayer as any).state?.analysis?.rotation?.current as RotationAnalysis | null)
})

const alerts = computed(() => {
  const state = (dataLayer as any).state
  return (state?.analysis?.alerts?.items || []) as StockAlert[]
})

const alertCount = computed(() => alerts.value.length)

// ========== 加载数据 ==========
const loadData = async () => {
  loading.value = true
  error.value = null

  try {
    await themeFacade.refreshJxbkAndFactors({ force: true })

    // 验证数据是否存在
    if (jxbkBlocks.value.length === 0) {
      error.value = '暂无板块数据'
    }
  } catch (err) {
    console.error('[SectorPanel] 加载数据失败:', err)
    error.value = err instanceof Error ? err.message : '加载失败'
  } finally {
    loading.value = false
  }
}

const refresh = async () => {
  try {
    loading.value = true
    error.value = null

    // legacy fallback: 清除旧 sectorAnalyzer 缓存
    if (sectorAnalyzer && typeof sectorAnalyzer.clearCache === 'function') {
      sectorAnalyzer.clearCache()
    }

    await themeFacade.refreshJxbkAndFactors({ force: true })

    // ✅ 3. 重新加载前N个板块的个股数据（可选，提升体验）
    if (sectorAnalyzer && typeof sectorAnalyzer.preloadTopSectors === 'function') {
      await sectorAnalyzer.preloadTopSectors(3)
    }

    // 如果当前是树形视图，刷新树组件
    if (viewMode.value === 'tree' && treeRef.value) {
      // 树组件会通过 dataLayer 自动响应数据变化
      // 如果有强制刷新方法，可以调用
      if (typeof (treeRef.value as any)?.refresh === 'function') {
        (treeRef.value as any).refresh()
      }
    }

  } catch (err) {
    console.error('[SectorPanel] 刷新失败:', err)
    error.value = err instanceof Error ? err.message : '刷新失败'
  } finally {
    loading.value = false
  }
}

function close() {
  emit('update:visible', false)
  emit('close')
}

function showSectorDetail(sectorName: string, event?: MouseEvent) {
  debugLog('[SectorPanel] showSectorDetail:', sectorName, 'viewMode:', viewMode.value)

  if (viewMode.value === 'tree') {
    selectedSectorName.value = sectorName
  } else {
    // 网格视图模式：显示详情弹窗
    sectorDetail.value = {
      visible: true,
      sectorName,
      triggerRect: event ? (event.currentTarget as HTMLElement).getBoundingClientRect() : undefined
    }

  }
}

function handleDetailClose(value: boolean) {
  if (sectorDetail.value) {
    sectorDetail.value.visible = value
  }
}

// ========== 工具函数 ==========
function getRankColor(index: number): string {
  const colors = ['#ffd700', '#c0c0c0', '#cd7f32']
  return index < 3 ? colors[index] : '#ffb142'
}

function handleSelectStock(code: string) {
  try {
    // 直接在函数内获取 store
    const uiStore = useUIStore()
    if (uiStore && typeof uiStore.selectStock === 'function') {
      uiStore.selectStock(code)
    } else {
      console.warn('[SectorPanel] UIStore 不存在或没有 selectStock 方法')
    }
  } catch (error) {
    console.error('[SectorPanel] 选择股票失败:', error)
  }
}

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

function formatTime(timestamp: number | null): string {
  if (!timestamp) return '--:--'
  const date = new Date(timestamp)
  return `${date.getHours().toString().padStart(2, '0')}:${date.getMinutes().toString().padStart(2, '0')}`
}

function formatTimeAgo(timestamp: number): string {
  if (!timestamp) return '未知'
  const diff = Math.floor((Date.now() - timestamp) / 60000)
  if (diff < 1) return '刚刚'
  if (diff < 60) return diff + '分钟前'
  return Math.floor(diff / 60) + '小时前'
}

// 轮动相关
function getMarketPhaseIcon(phase: string): string {
  const icons: Record<string, string> = {
    accumulation: '🏗️',
    rising: '📈',
    distribution: '📊',
    falling: '📉'
  }
  return icons[phase] || '🔄'
}

function getMarketPhaseName(phase: string): string {
  const names: Record<string, string> = {
    accumulation: '筑底期',
    rising: '上升期',
    distribution: '出货期',
    falling: '下降期'
  }
  return names[phase] || phase
}

// 预警相关
function getAlertIcon(type: string): string {
  const icons: Record<string, string> = {
    leader_fall: '👑',
    leader_emerge: '🌟',
    batch_limit_up: '📈',
    batch_explode: '💥',
    heat_surge: '🔥',
    heat_plunge: '❄️',
    volume_surge: '📊',
    rotation_signal: '🔄',
    money_flow: '💰'
  }
  return icons[type] || '⚠️'
}

// ========== 生命周期 ==========
onMounted(() => {
  if (props.visible) {
    loadData()
    // 延迟2秒预加载前3个板块
    setTimeout(() => {
      // 修复：移除未定义的 sectorAnalyzer
      // 如果有预加载功能，应该通过 dataLayer 实现
      debugLog('[SectorPanel] 可以在这里实现预加载逻辑')
    }, 2000)
  }
})

</script>

<style scoped>
/* ========== 面板基础样式 ========== */
.sector-panel {
  position: fixed;
  width: 1200px;
  max-width: calc(100vw - 40px);
  max-height: 80vh;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
  z-index: 10004;
  font-size: 12px;
  overflow: hidden;
  color: var(--text-primary);
}

/* ========== 头部样式 ========== */
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
  flex-wrap: wrap;
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

.mapping-badge {
  font-size: 10px;
  background: var(--bg-secondary);
  color: var(--text-secondary);
  padding: 2px 6px;
  border-radius: 12px;
  cursor: help;
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

.stock-count {
  color: var(--color-highlight);
  font-weight: 500;
}

.version-info {
  margin-left: 4px;
  padding: 0 4px;
  background: var(--bg-primary);
  border-radius: 4px;
  font-size: 9px;
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
  display: flex;
  align-items: center;
  justify-content: center;
}

.btn-icon:hover:not(:disabled) {
  background: var(--bg-hover);
  color: var(--text-primary);
  border-color: var(--color-highlight);
}

.btn-icon:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* ========== 标签页样式 ========== */
.panel-tabs {
  display: flex;
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

.alert-count {
  position: absolute;
  top: -4px;
  right: -4px;
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  background: #ff4757;
  color: white;
  border-radius: 8px;
  font-size: 9px;
  line-height: 16px;
}

/* ========== 内容区域 ========== */
.panel-content {
  padding: 20px;
  max-height: calc(80vh - 120px);
  overflow-y: auto;
}

/* ========== 板块卡片样式 ========== */
.sectors-grid {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.sector-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 16px;
  cursor: pointer;
  transition: all 0.2s;
}

.sector-card:hover {
  transform: translateY(-2px);
  border-color: var(--color-highlight);
  box-shadow: 0 4px 12px rgba(255, 177, 66, 0.2);
}

/* 卡片头部 - 排名和名称 */
.card-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}

.rank-wrapper {
  width: 48px;
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 24px;
  flex-shrink: 0;
}

.rank-badge {
  color: #000;
  font-weight: bold;
  font-size: 18px;
}

.sector-info {
  flex: 1;
}

.sector-name {
  display: block;
  font-weight: bold;
  font-size: 18px;
  color: var(--text-title);
  margin-bottom: 4px;
}

/* 树型视图 */
.tabs-right {
  display: flex;
  gap: 4px;
  margin-left: auto;
  padding-right: 16px;
}

.view-mode-btn {
  width: 32px;
  height: 32px;
  border: 1px solid var(--border-color);
  background: transparent;
  border-radius: 8px;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
}

.view-mode-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
  border-color: var(--color-highlight);
}

.view-mode-btn.active {
  background: var(--color-highlight);
  border-color: var(--color-highlight);
  color: #000;
}

.tree-view {
  height: 100%;
  min-height: 500px;
  padding: 16px;
}

.sector-tree-component {
  height: 100%;
  border: 1px solid var(--border-color);
  border-radius: 12px;
  overflow: hidden;
}

/* 统计数据网格 - 两行三列 */
.stats-grid {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.stats-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
}

.stat-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  padding: 10px 4px;
  min-width: 0;
}

.stat-icon {
  font-size: 16px;
  margin-bottom: 4px;
}

.stat-value {
  font-size: 15px;
  font-weight: bold;
  color: var(--text-title);
  word-break: break-word;
  text-align: center;
  width: 100%;
}

.stat-value.up {
  color: #ff4757;
}

.stat-value.down {
  color: #2ed573;
}

.stat-label {
  font-size: 10px;
  color: var(--text-secondary);
  margin-top: 2px;
}

/* 标签样式（备用） */
.sector-tags {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
  margin-top: 4px;
}

.tag {
  padding: 2px 8px;
  border-radius: 12px;
  font-size: 10px;
  font-weight: 500;
}

.strength-tag {
  background: rgba(255, 177, 66, 0.15);
  color: #ffb142;
}

.strength-tag.strength-s {
  background: rgba(255, 71, 87, 0.15);
  color: #ff4757;
}

.strength-tag.strength-a {
  background: rgba(255, 127, 80, 0.15);
  color: #ff7f50;
}

.strength-tag.strength-b {
  background: rgba(255, 177, 66, 0.15);
  color: #ffb142;
}

.strength-tag.strength-c {
  background: rgba(74, 144, 226, 0.15);
  color: #4a90e2;
}

.strength-tag.strength-d {
  background: rgba(127, 140, 141, 0.15);
  color: #7f8c8d;
}

.zt-tag {
  background: rgba(255, 71, 87, 0.15);
  color: #ff4757;
}

/* ========== 轮动视图样式 ========== */
.rotation-view {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.rotation-content {
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

.market-phase-card.accumulation {
  border-left-color: #7f8c8d;
}

.market-phase-card.rising {
  border-left-color: #e74c3c;
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
}

.rotation-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
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

.rotation-items {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.rotation-item {
  padding: 12px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
}

.rotation-item:hover {
  background: var(--bg-hover);
  border-color: var(--color-highlight);
}

.rotation-item.mainline {
  border-left: 4px solid #ffd700;
}

.rotation-item.inflow {
  border-left: 4px solid #ff4757;
}

.rotation-item.outflow {
  border-left: 4px solid #3498db;
}

.rotation-item.quick {
  border-left: 4px solid #f39c12;
}

.item-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.item-name {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-title);
}

.item-days,
.item-rank {
  padding: 2px 6px;
  background: var(--bg-secondary);
  border-radius: 10px;
  font-size: 10px;
  color: var(--text-secondary);
}

.item-flow {
  margin-bottom: 4px;
}

.flow-value {
  font-size: 14px;
  font-weight: 500;
}

.flow-value.inflow {
  color: #ff4757;
}

.flow-value.outflow {
  color: #3498db;
}

.item-stats {
  display: flex;
  gap: 12px;
  font-size: 10px;
  color: var(--text-secondary);
}

.item-rank-change {
  font-size: 11px;
  font-weight: 500;
}

.item-rank-change.up {
  color: #ff4757;
}

.item-rank-change.down {
  color: #2ed573;
}

.rotation-summary {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  margin-top: 8px;
}

.summary-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
}

.summary-label {
  font-size: 10px;
  color: var(--text-secondary);
}

.summary-value {
  font-size: 18px;
  font-weight: bold;
  color: var(--text-title);
}

/* ========== 预警视图样式 ========== */
.alerts-view {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.alerts-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.alert-item {
  padding: 12px;
  border-radius: 8px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-left-width: 4px;
}

.alert-item.alert-critical {
  border-left-color: #ff4757;
}

.alert-item.alert-warning {
  border-left-color: #f39c12;
}

.alert-item.alert-info {
  border-left-color: #3498db;
}

.alert-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.alert-icon {
  font-size: 14px;
}

.alert-level {
  font-size: 10px;
  padding: 2px 8px;
  background: var(--bg-primary);
  border-radius: 10px;
  text-transform: capitalize;
}

.alert-time {
  margin-left: auto;
  font-size: 10px;
  color: var(--text-secondary);
}

.alert-title {
  font-size: 13px;
  font-weight: 500;
  margin-bottom: 2px;
}

.alert-message {
  font-size: 11px;
  color: var(--text-secondary);
  margin-bottom: 4px;
}

.alert-meta {
  display: flex;
  gap: 8px;
}

.alert-theme {
  font-size: 10px;
  padding: 2px 8px;
  background: var(--bg-primary);
  border-radius: 10px;
  color: var(--color-highlight);
  cursor: pointer;
}

.more-hint {
  padding: 8px;
  text-align: center;
  font-size: 11px;
  color: var(--text-secondary);
  border-top: 1px dashed var(--border-color);
}

/* ========== 通用状态样式 ========== */
.loading-state,
.error-state,
.empty-state {
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
  font-size: 48px;
  opacity: 0.5;
}

.retry-btn {
  padding: 6px 12px;
  background: var(--color-highlight);
  border: none;
  border-radius: 16px;
  color: #000;
  font-size: 11px;
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

/* ========== 页脚 ========== */
.panel-footer {
  padding: 12px 20px;
  border-top: 1px solid var(--border-color);
  background: var(--bg-header);
  font-size: 10px;
  color: var(--text-secondary);
  display: flex;
  justify-content: space-between;
}
</style>
