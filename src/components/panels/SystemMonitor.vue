<!-- src/components/panels/SystemMonitor.vue -->
<!-- 纯响应式版本：移除事件，使用计算属性 -->

<template>
  <Teleport to="body">
    <div v-if="visible" class="system-monitor" :style="panelStyle" ref="panelRef">
      <div class="monitor-header">
        <h3>📊 系统监控</h3>
        <button class="close-btn" @click="close">✕</button>
      </div>

      <div class="monitor-content">
        <!-- ========== 刷新管理器状态 ========== -->
        <div class="section">
          <div class="section-title">⏱️ 刷新管理器</div>
          <div class="stats-grid">
            <div class="stat-item">
              <span class="stat-label">当前策略</span>
              <span class="stat-value" :style="{ color: refreshStatus?.strategyColor }">
                {{ refreshStatus?.strategyName || refreshStatus?.strategy || '未知' }}
              </span>
            </div>
            <div class="stat-item">
              <span class="stat-label">运行状态</span>
              <span class="stat-value" :class="refreshStatus?.isRunning ? 'good' : 'warn'">
                {{ refreshStatus?.isRunning ? '运行中' : '已停止' }}
              </span>
            </div>
            <div class="stat-item">
              <span class="stat-label">全量间隔</span>
              <span class="stat-value">{{
                formatInterval(refreshStatus?.fullRefreshInterval)
              }}</span>
            </div>
            <div class="stat-item">
              <span class="stat-label">增量间隔</span>
              <span class="stat-value">{{
                formatInterval(refreshStatus?.incrementalRefreshInterval)
              }}</span>
            </div>
          </div>
        </div>

        <!-- ========== 算法管理器状态 ========== -->
        <div class="section">
          <div class="section-title">🧠 算法管理器</div>
          <div class="stats-grid">
            <div class="stat-item">
              <span class="stat-label">当前算法</span>
              <span class="stat-value">{{ algorithmName }}</span>
            </div>
            <div class="stat-item">
              <span class="stat-label">版本</span>
              <span class="stat-value">v{{ algorithmVersion }}</span>
            </div>
            <div class="stat-item">
              <span class="stat-label">初始化</span>
              <span class="stat-value" :class="algorithmInitialized ? 'good' : 'warn'">
                {{ algorithmInitialized ? '是' : '否' }}
              </span>
            </div>
            <div class="stat-item">
              <span class="stat-label">自定义权重</span>
              <span class="stat-value" :class="hasCustomWeights ? 'good' : 'normal'">
                {{ hasCustomWeights ? '有' : '无' }}
              </span>
            </div>
          </div>
        </div>

        <!-- ========== 增量更新器状态 ========== -->
        <div class="section">
          <div class="section-title">⚡ 增量更新器</div>
          <div class="stats-grid">
            <div class="stat-item">
              <span class="stat-label">队列大小</span>
              <span class="stat-value">{{ incrementalQueueSize }}</span>
            </div>
            <div class="stat-item">
              <span class="stat-label">处理中</span>
              <span class="stat-value" :class="incrementalProcessing ? 'warn' : 'good'">
                {{ incrementalProcessing ? '是' : '否' }}
              </span>
            </div>
            <div class="stat-item">
              <span class="stat-label">热点股票</span>
              <span class="stat-value">{{ incrementalHotStocks }}只</span>
            </div>
            <div class="stat-item">
              <span class="stat-label">总更新</span>
              <span class="stat-value">{{ incrementalTotalUpdates }}</span>
            </div>
          </div>
        </div>

        <!-- ========== 数据层状态 ========== -->
        <div class="section">
          <div class="section-title">📦 数据层</div>
          <div class="stats-grid">
            <div class="stat-item">
              <span class="stat-label">股票数量</span>
              <span class="stat-value">{{ dataStats.stocks }}</span>
            </div>
            <div class="stat-item">
              <span class="stat-label">题材数量</span>
              <span class="stat-value">{{ dataStats.themes }}</span>
            </div>
            <div class="stat-item">
              <span class="stat-label">实时行情</span>
              <span class="stat-value">{{ dataStats.quotes }}</span>
            </div>
            <div class="stat-item">
              <span class="stat-label">平台数量</span>
              <span class="stat-value">{{ dataStats.platforms }}</span>
            </div>
          </div>
        </div>

        <!-- ========== 缓存状态 ========== -->
        <div class="section">
          <div class="section-title">⚡ 缓存</div>
          <div class="stats-grid">
            <div class="stat-item">
              <span class="stat-label">总缓存大小</span>
              <span class="stat-value">{{ totalCacheSize }}</span>
            </div>
            <div class="stat-item">
              <span class="stat-label">总命中率</span>
              <span class="stat-value" :class="getHitRateClass(totalHitRate)">
                {{ totalHitRate }}
              </span>
            </div>
          </div>
        </div>

        <!-- ========== 龙头分析状态 ========== -->
        <div class="section">
          <div class="section-title">🐲 龙头分析</div>
          <div class="stats-grid">
            <div class="stat-item">
              <span class="stat-label">总龙头</span>
              <span class="stat-value">{{ leaderStats.totalLeadersCount || 0 }}</span>
            </div>
            <div class="stat-item">
              <span class="stat-label">连板龙头</span>
              <span class="stat-value">{{ leaderStats.continuousLeaders || 0 }}</span>
            </div>
            <div class="stat-item">
              <span class="stat-label">板块龙头</span>
              <span class="stat-value">{{ leaderStats.sectorLeaders || 0 }}</span>
            </div>
            <div class="stat-item">
              <span class="stat-label">情绪龙头</span>
              <span class="stat-value">{{ leaderStats.emotionLeaders || 0 }}</span>
            </div>
          </div>
        </div>

        <!-- ========== 龙息分析状态 ========== -->
        <div class="section">
          <div class="section-title">🌬️ 龙息分析</div>
          <div class="stats-grid">
            <div class="stat-item">
              <span class="stat-label">市场情绪</span>
              <span class="stat-value">{{ breathPhase }}</span>
            </div>
            <div class="stat-item">
              <span class="stat-label">情绪分数</span>
              <span class="stat-value">{{ breathScore }}分</span>
            </div>
            <div class="stat-item">
              <span class="stat-label">涨停/跌停</span>
              <span class="stat-value">{{ ztCount }}/{{ dtCount }}</span>
            </div>
            <div class="stat-item">
              <span class="stat-label">上涨/下跌</span>
              <span class="stat-value">{{ upCount }}/{{ downCount }}</span>
            </div>
          </div>
          <div class="suggestion-text" v-if="breathSuggestion">
            💡 {{ breathSuggestion }}
          </div>
        </div>

        <!-- ========== 性能指标 ========== -->
        <div class="section">
          <div class="section-title">⏱️ 性能</div>
          <div class="stats-grid">
            <div class="stat-item">
              <span class="stat-label">数据新鲜度</span>
              <span class="stat-value" :class="getFreshnessClass(dataFreshness)">
                {{ dataFreshness }}
              </span>
            </div>
            <div class="stat-item">
              <span class="stat-label">WebSocket</span>
              <span class="stat-value" :class="getWsClass(wsStatus)">
                {{ wsStatus }}
              </span>
            </div>
          </div>
        </div>

        <!-- ========== 操作按钮 ========== -->
        <div class="actions">
          <button class="action-btn" @click="refreshAll">🔄 刷新所有</button>
          <button class="action-btn" @click="clearCache">🧹 清除缓存</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { debugLog } from '@/utils/logger'
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { dataLayer } from '@/services/DataLayer'
import { sectorAnalyzer } from '@/services/sectorAnalyzer'
import { dragonAnalyzer } from '@/services/DragonAnalyzer'
import { dragonBreathAnalyzer } from '@/services/DragonBreathAnalyzer'
import { RefreshManager } from '@/services/RefreshManager'
import { algorithmManager } from '@/services/Algorithm'
import { incrementalUpdater } from '@/services/IncrementalUpdater'
//import { webSocketService } from '@/services/websocket'
import { usePanel } from '@/composables/usePanel'

const props = defineProps<{
  visible: boolean
  triggerRect?: DOMRect
}>()

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'close'): void
}>()

// ========== 面板定位 ==========
const { panelRef, panelStyle } = usePanel({
  name: 'SystemMonitor',
  visible: props.visible,
  triggerRect: props.triggerRect,
  onClose: () => emit('close')
})

// ========== 刷新管理器状态 ==========
const refreshStatus = computed(() => {
  try {
    return RefreshManager?.getStatus?.() || null
  } catch {
    return null
  }
})

// ========== 算法管理器状态 ==========
const algorithmName = computed(() => {
  try {
    return algorithmManager?.getCurrentAlgorithm?.()?.name || '未知'
  } catch {
    return '未知'
  }
})

const algorithmVersion = computed(() => {
  try {
    return algorithmManager?.getVersion?.() || 0
  } catch {
    return 0
  }
})

const algorithmInitialized = computed(() => {
  try {
    return algorithmManager?.getStatus?.()?.initialized || false
  } catch {
    return false
  }
})

const hasCustomWeights = computed(() => {
  try {
    return algorithmManager?.getStatus?.()?.hasCustomWeights || false
  } catch {
    return false
  }
})

// ========== 增量更新器状态 ==========
const incrementalQueueSize = computed(() => {
  try {
    return incrementalUpdater?.getStatus?.()?.queueSize || 0
  } catch {
    return 0
  }
})

const incrementalProcessing = computed(() => {
  try {
    return incrementalUpdater?.getStatus?.()?.processing || false
  } catch {
    return false
  }
})

const incrementalHotStocks = computed(() => {
  try {
    return incrementalUpdater?.getStatus?.()?.hotStocksLimit || 0
  } catch {
    return 0
  }
})

const incrementalTotalUpdates = computed(() => {
  try {
    return incrementalUpdater?.getStatus?.()?.stats?.totalUpdates || 0
  } catch {
    return 0
  }
})

// ========== 数据层统计 ==========
const dataStats = computed(() => {
  try {
    const stocks = dataLayer.getStocks()?.length || 0
    const themes = dataLayer.getRawThemes()?.length || 0
    const quotes = dataLayer.getQuotesCount?.() || 0
    const platforms = 8 // 固定8平台

    return { stocks, themes, quotes, platforms }
  } catch {
    return { stocks: 0, themes: 0, quotes: 0, platforms: 8 }
  }
})

// ========== 缓存统计 ==========
const totalCacheSize = computed(() => {
  try {
    const cache = (window as any).cacheManager
    return cache?.size?.() || 0
  } catch {
    return 0
  }
})

const totalHitRate = computed(() => {
  try {
    const cache = (window as any).cacheManager
    const stats = cache?.getStats?.()
    if (!stats) return '0%'
    const total = stats.hits + stats.misses
    if (total === 0) return '0%'
    return ((stats.hits / total) * 100).toFixed(1) + '%'
  } catch {
    return '0%'
  }
})

// ========== 龙头统计 ==========
const leaderStats = computed(() => {
  try {
    return dragonAnalyzer?.getStats?.() || {}
  } catch {
    return {}
  }
})

// ========== 龙息分析 ==========
const breathPhase = computed(() => {
  try {
    return dragonBreathAnalyzer?.getMarketSentiment?.()?.phase || '未知'
  } catch {
    return '未知'
  }
})

const breathScore = computed(() => {
  try {
    return dragonBreathAnalyzer?.getMarketSentiment?.()?.overall?.toFixed(0) || '0'
  } catch {
    return '0'
  }
})

const breathSuggestion = computed(() => {
  try {
    return dragonBreathAnalyzer?.getMarketSentiment?.()?.suggestion || ''
  } catch {
    return ''
  }
})

const ztCount = computed(() => {
  try {
    return dragonBreathAnalyzer?.getMarketData?.()?.ztCount || 0
  } catch {
    return 0
  }
})

const dtCount = computed(() => {
  try {
    return dragonBreathAnalyzer?.getMarketData?.()?.dtCount || 0
  } catch {
    return 0
  }
})

const upCount = computed(() => {
  try {
    return dragonBreathAnalyzer?.getMarketData?.()?.upCount || 0
  } catch {
    return 0
  }
})

const downCount = computed(() => {
  try {
    return dragonBreathAnalyzer?.getMarketData?.()?.downCount || 0
  } catch {
    return 0
  }
})

// ========== 性能指标 ==========
const dataFreshness = computed(() => {
  try {
    const stocks = dataLayer.getStocks()
    if (!stocks || stocks.length === 0) return '无数据'
    const firstStock = stocks[0]
    if (!firstStock?.updatedAt) return '未知'
    const minutes = (Date.now() - firstStock.updatedAt) / 60000
    if (minutes < 1) return '新鲜'
    if (minutes < 5) return '正常'
    if (minutes < 15) return '较旧'
    return '过期'
  } catch {
    return '未知'
  }
})

const wsStatus = computed(() => {
  try {
    return webSocketService?.getStatus?.()?.status || 'unknown'
  } catch {
    return 'unknown'
  }
})

// ========== 工具函数 ==========
function formatInterval(ms: number): string {
  if (!ms) return '--'
  if (ms < 1000) return ms + 'ms'
  if (ms < 60000) return (ms / 1000).toFixed(1) + '秒'
  return (ms / 60000).toFixed(0) + '分钟'
}

function getHitRateClass(rate: string): string {
  const num = parseFloat(rate)
  if (num >= 80) return 'good'
  if (num >= 50) return 'normal'
  return 'warn'
}

function getFreshnessClass(freshness: string): string {
  const classes: Record<string, string> = {
    新鲜: 'good',
    正常: 'normal',
    较旧: 'warn',
    过期: 'danger',
  }
  return classes[freshness] || ''
}

function getWsClass(status: string): string {
  const classes: Record<string, string> = {
    connected: 'good',
    http_fallback: 'normal',
    mock: 'warn',
    disconnected: 'danger',
  }
  return classes[status] || ''
}

// ========== 操作函数 ==========
function refreshAll() {
  // 直接调用刷新管理器的方法，不依赖事件
  RefreshManager?.manualRefresh?.('full')
}

function clearCache() {
  try {
    const cache = (window as any).cacheManager
    cache?.clear?.()
  } catch (e) {
    console.warn('[SystemMonitor] 清除缓存失败:', e)
  }
}

function close() {
  emit('update:visible', false)
  emit('close')
}

// ========== 生命周期 ==========
onMounted(() => {
  debugLog('[SystemMonitor] 挂载')
})

onUnmounted(() => {
  debugLog('[SystemMonitor] 卸载')
})
</script>

<style scoped>
.suggestion-text {
  margin-top: 8px;
  padding: 8px;
  background: var(--bg-secondary);
  border-radius: 6px;
  font-size: 11px;
  color: var(--text-primary);
  border-left: 3px solid var(--color-highlight);
}

.sub-section {
  margin-top: 12px;
  padding-top: 8px;
  border-top: 1px dashed var(--border-color);
}

.mini-stats {
  display: flex;
  gap: 8px;
  justify-content: space-around;
}

.mini-stat {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 4px;
  background: var(--bg-primary);
  border-radius: 4px;
  min-width: 40px;
}

.mini-label {
  font-size: 8px;
  color: var(--text-tertiary);
}

.mini-value {
  font-size: 12px;
  font-weight: bold;
  color: var(--text-primary);
}

.mini-value.danger {
  color: #ff4757;
}

.factor-preview {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.factor-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 10px;
}

.factor-name {
  width: 50px;
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.factor-bar {
  flex: 1;
  height: 4px;
  background: var(--bg-primary);
  border-radius: 2px;
  overflow: hidden;
}

.factor-bar-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--color-highlight), #ffa502);
  border-radius: 2px;
}

.factor-weight {
  width: 35px;
  color: var(--color-highlight);
  text-align: right;
  font-weight: 500;
}

/* 原有其他样式保持不变 */
.ws-details {
  margin-top: 12px;
  padding: 8px;
  background: var(--bg-secondary);
  border-radius: 6px;
  font-size: 10px;
}

.detail-row {
  display: flex;
  justify-content: space-between;
  margin-bottom: 4px;
  color: var(--text-secondary);
}

.detail-row span:last-child {
  color: var(--text-primary);
  font-weight: 500;
}

.stat-item.full-market {
  grid-column: span 2;
  position: relative;
  background: linear-gradient(135deg, var(--bg-secondary), var(--bg-hover));
  border: 1px solid var(--color-highlight);
}

.stat-badge {
  position: absolute;
  top: 4px;
  right: 4px;
  padding: 2px 6px;
  background: var(--bg-primary);
  border-radius: 10px;
  font-size: 8px;
  color: var(--text-secondary);
  border: 1px solid var(--border-color);
}

.stat-badge.active {
  background: var(--color-highlight);
  color: #000;
  border-color: var(--color-highlight);
}

.system-monitor {
  position: fixed;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
  z-index: 10010;
  font-size: 12px;
  backdrop-filter: blur(10px);
}

.monitor-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-header);
}

.monitor-header h3 {
  margin: 0;
  font-size: 16px;
  color: var(--color-highlight);
}

.close-btn {
  width: 32px;
  height: 32px;
  border: 1px solid var(--border-color);
  background: transparent;
  border-radius: 8px;
  color: var(--text-secondary);
  cursor: pointer;
}

.close-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.monitor-content {
  padding: 20px;
  max-height: calc(80vh - 70px);
  overflow-y: auto;
}

.section {
  margin-bottom: 24px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--border-color);
}

.section:last-child {
  border-bottom: none;
  margin-bottom: 0;
  padding-bottom: 0;
}

.section-title {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-title);
  margin-bottom: 12px;
}

.sub-title {
  font-size: 12px;
  color: var(--text-secondary);
  margin: 12px 0 8px;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
  margin-bottom: 12px;
}

.stat-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.stat-label {
  font-size: 10px;
  color: var(--text-secondary);
}

.stat-value {
  font-size: 16px;
  font-weight: bold;
  color: var(--text-primary);
}

.stat-value.good {
  color: #2ecc71;
}

.stat-value.normal {
  color: #f1c40f;
}

.stat-value.warn {
  color: #e67e22;
}

.stat-value.danger {
  color: #e74c3c;
}

.version-info {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 8px;
  background: var(--bg-secondary);
  border-radius: 8px;
}

.version-item {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 10px;
  color: var(--text-secondary);
}

.version-badge {
  padding: 2px 4px;
  background: var(--bg-primary);
  border-radius: 4px;
  font-family: monospace;
}

.cache-details {
  margin-top: 12px;
}

.cache-detail-item {
  background: var(--bg-secondary);
  border-radius: 6px;
  padding: 8px;
  margin-bottom: 6px;
}

.cache-detail-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.cache-name {
  font-weight: bold;
  color: var(--text-primary);
  width: 60px;
}

.cache-size {
  font-size: 10px;
  color: var(--text-secondary);
}

.cache-hitrate {
  margin-left: auto;
  font-weight: bold;
}

.cache-hitrate.good {
  color: #2ecc71;
}

.cache-hitrate.normal {
  color: #f1c40f;
}

.cache-hitrate.warn {
  color: #e67e22;
}

.cache-stats {
  display: flex;
  gap: 12px;
  font-size: 10px;
  color: var(--text-secondary);
}

.theme-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.theme-tag {
  padding: 4px 8px;
  border-radius: 12px;
  font-size: 10px;
  white-space: nowrap;
}

.leader-list {
  margin-top: 8px;
}

.leader-item {
  display: flex;
  justify-content: space-between;
  padding: 6px 8px;
  background: var(--bg-secondary);
  border-radius: 6px;
  margin-bottom: 4px;
}

.leader-name {
  color: var(--text-primary);
}

.leader-score {
  color: var(--color-highlight);
  font-weight: 500;
}

.actions {
  display: flex;
  gap: 8px;
  margin-top: 16px;
}

.action-btn {
  flex: 1;
  padding: 8px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  color: var(--text-primary);
  font-size: 11px;
  cursor: pointer;
  transition: all 0.2s;
}

.action-btn:hover {
  background: var(--bg-hover);
  border-color: var(--color-highlight);
}

.hitrate-trend {
  margin-top: 12px;
  padding: 8px;
  background: var(--bg-secondary);
  border-radius: 6px;
}

.trend-bars {
  display: flex;
  align-items: flex-end;
  gap: 4px;
  height: 60px;
}

.trend-bar {
  flex: 1;
  min-width: 4px;
  border-radius: 2px 2px 0 0;
  transition: height 0.3s;
}

.ws-details {
  margin-top: 12px;
  padding: 8px;
  background: var(--bg-secondary);
  border-radius: 6px;
  font-size: 10px;
}

.detail-row {
  display: flex;
  justify-content: space-between;
  margin-bottom: 4px;
  color: var(--text-secondary);
}

.detail-row span:last-child {
  color: var(--text-primary);
  font-weight: 500;
}

.stat-item.full-market {
  grid-column: span 2;
  position: relative;
  background: linear-gradient(135deg, var(--bg-secondary), var(--bg-hover));
  border: 1px solid var(--color-highlight);
}

.stat-badge {
  position: absolute;
  top: 4px;
  right: 4px;
  padding: 2px 6px;
  background: var(--bg-primary);
  border-radius: 10px;
  font-size: 8px;
  color: var(--text-secondary);
  border: 1px solid var(--border-color);
}

.stat-badge.active {
  background: var(--color-highlight);
  color: #000;
  border-color: var(--color-highlight);
}

.full-market-preview {
  margin-top: 12px;
  padding: 8px;
  background: var(--bg-secondary);
  border-radius: 8px;
}

.preview-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 4px 0;
  font-size: 11px;
  border-bottom: 1px dashed var(--border-color);
}

.preview-item:last-child {
  border-bottom: none;
}

.preview-code {
  font-family: monospace;
  color: var(--text-secondary);
  width: 60px;
}

.preview-name {
  flex: 1;
  color: var(--text-primary);
  margin-left: 8px;
}

.preview-price {
  color: var(--color-highlight);
  font-weight: 500;
}

/* 完整样式 */
.system-monitor {
  position: fixed;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
  z-index: 10010;
  font-size: 12px;
  backdrop-filter: blur(10px);
}

.monitor-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-header);
}

.monitor-header h3 {
  margin: 0;
  font-size: 16px;
  color: var(--color-highlight);
}

.close-btn {
  width: 32px;
  height: 32px;
  border: 1px solid var(--border-color);
  background: transparent;
  border-radius: 8px;
  color: var(--text-secondary);
  cursor: pointer;
}

.close-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.monitor-content {
  padding: 20px;
  max-height: calc(80vh - 70px);
  overflow-y: auto;
}

.section {
  margin-bottom: 24px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--border-color);
}

.section:last-child {
  border-bottom: none;
  margin-bottom: 0;
  padding-bottom: 0;
}

.section-title {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-title);
  margin-bottom: 12px;
}

.sub-title {
  font-size: 12px;
  color: var(--text-secondary);
  margin: 12px 0 8px;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
  margin-bottom: 12px;
}

.stat-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.stat-label {
  font-size: 10px;
  color: var(--text-secondary);
}

.stat-value {
  font-size: 16px;
  font-weight: bold;
  color: var(--text-primary);
}

.stat-value.good {
  color: #2ecc71;
}

.stat-value.normal {
  color: #f1c40f;
}

.stat-value.warn {
  color: #e67e22;
}

.stat-value.danger {
  color: #e74c3c;
}

.version-info {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 8px;
  background: var(--bg-secondary);
  border-radius: 8px;
}

.version-item {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 10px;
  color: var(--text-secondary);
}

.version-badge {
  padding: 2px 4px;
  background: var(--bg-primary);
  border-radius: 4px;
  font-family: monospace;
}

.cache-details {
  margin-top: 12px;
}

.cache-detail-item {
  background: var(--bg-secondary);
  border-radius: 6px;
  padding: 8px;
  margin-bottom: 6px;
}

.cache-detail-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.cache-name {
  font-weight: bold;
  color: var(--text-primary);
  width: 60px;
}

.cache-size {
  font-size: 10px;
  color: var(--text-secondary);
}

.cache-hitrate {
  margin-left: auto;
  font-weight: bold;
}

.cache-hitrate.good {
  color: #2ecc71;
}

.cache-hitrate.normal {
  color: #f1c40f;
}

.cache-hitrate.warn {
  color: #e67e22;
}

.cache-stats {
  display: flex;
  gap: 12px;
  font-size: 10px;
  color: var(--text-secondary);
}

.theme-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.theme-tag {
  padding: 4px 8px;
  border-radius: 12px;
  font-size: 10px;
  white-space: nowrap;
}

.leader-list {
  margin-top: 8px;
}

.leader-item {
  display: flex;
  justify-content: space-between;
  padding: 6px 8px;
  background: var(--bg-secondary);
  border-radius: 6px;
  margin-bottom: 4px;
}

.leader-name {
  color: var(--text-primary);
}

.leader-score {
  color: var(--color-highlight);
  font-weight: 500;
}

.actions {
  display: flex;
  gap: 8px;
  margin-top: 16px;
}

.action-btn {
  flex: 1;
  padding: 8px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  color: var(--text-primary);
  font-size: 11px;
  cursor: pointer;
  transition: all 0.2s;
}

.action-btn:hover {
  background: var(--bg-hover);
  border-color: var(--color-highlight);
}

.quote-details {
  margin-top: 12px;
}

.quote-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 8px;
  background: var(--bg-secondary);
  border-radius: 6px;
  margin-bottom: 4px;
  font-size: 11px;
}

.quote-code {
  font-family: monospace;
  color: var(--text-secondary);
  width: 60px;
}

.quote-price {
  font-weight: 500;
  color: var(--text-primary);
}

.quote-change {
  font-weight: 500;
  min-width: 60px;
  text-align: right;
}

.quote-change.up {
  color: #ff4757;
}

.quote-change.down {
  color: #2ed573;
}

.stat-item.full-market {
  grid-column: span 2;
  position: relative;
  background: linear-gradient(135deg, var(--bg-secondary), var(--bg-hover));
  border: 1px solid var(--color-highlight);
}

.stat-badge {
  position: absolute;
  top: 4px;
  right: 4px;
  padding: 2px 6px;
  background: var(--bg-primary);
  border-radius: 10px;
  font-size: 8px;
  color: var(--text-secondary);
  border: 1px solid var(--border-color);
}

.stat-badge.active {
  background: var(--color-highlight);
  color: #000;
  border-color: var(--color-highlight);
}

.full-market-preview {
  margin-top: 12px;
  padding: 8px;
  background: var(--bg-secondary);
  border-radius: 8px;
}

.preview-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 4px 0;
  font-size: 11px;
  border-bottom: 1px dashed var(--border-color);
}

.preview-item:last-child {
  border-bottom: none;
}

.preview-code {
  font-family: monospace;
  color: var(--text-secondary);
  width: 60px;
}

.preview-name {
  flex: 1;
  color: var(--text-primary);
  margin-left: 8px;
}

.preview-price {
  color: var(--color-highlight);
  font-weight: 500;
}

/* 缓存版本管理 */
.version-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}

.version-card {
  background: var(--bg-secondary);
  border-radius: 8px;
  padding: 10px;
  border: 1px solid var(--border-color);
}

.version-header {
  font-size: 11px;
  font-weight: bold;
  color: var(--text-title);
  margin-bottom: 8px;
  padding-bottom: 4px;
  border-bottom: 1px dashed var(--border-color);
}

.version-card .version-item {
  display: flex;
  justify-content: space-between;
  font-size: 10px;
  margin-bottom: 4px;
  color: var(--text-secondary);
}

.version-card .version-item span:last-child {
  font-family: monospace;
  background: var(--bg-primary);
  padding: 2px 4px;
  border-radius: 4px;
  color: var(--color-highlight);
}

/* 缓存管理器 */
.cache-manager-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 8px;
}

.cache-manager-card {
  background: var(--bg-secondary);
  border-radius: 8px;
  padding: 10px;
  border: 1px solid var(--border-color);
}

.manager-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
  padding-bottom: 4px;
  border-bottom: 1px dashed var(--border-color);
}

.manager-name {
  font-size: 11px;
  font-weight: bold;
  color: var(--text-title);
  text-transform: capitalize;
}

.manager-size {
  font-size: 10px;
  color: var(--text-secondary);
  background: var(--bg-primary);
  padding: 2px 6px;
  border-radius: 10px;
}

.manager-stats {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.manager-stats .stat-row {
  display: flex;
  justify-content: space-between;
  font-size: 10px;
  color: var(--text-secondary);
}

.manager-stats .stat-row span:last-child {
  color: var(--text-primary);
  font-weight: 500;
}

/* 热门缓存键 */
.hot-keys-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 150px;
  overflow-y: auto;
}

.hot-key-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  background: var(--bg-secondary);
  border-radius: 6px;
  font-size: 10px;
}

.key-name {
  flex: 1;
  font-family: monospace;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.key-count {
  color: var(--color-highlight);
  font-weight: 500;
  min-width: 50px;
  text-align: right;
}

.key-size {
  color: var(--text-secondary);
  min-width: 50px;
  text-align: right;
}

/* 工具函数 */
.truncate-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 版本告警 */
.version-alert {
  margin-top: 8px;
  padding: 8px;
  background: rgba(255, 71, 87, 0.1);
  border: 1px solid #ff4757;
  border-radius: 6px;
  color: #ff4757;
  font-size: 11px;
  display: flex;
  align-items: center;
  gap: 6px;
}

/* 命中率趋势 */
.hitrate-trend {
  margin-top: 12px;
  padding: 8px;
  background: var(--bg-secondary);
  border-radius: 6px;
}

.trend-bars {
  display: flex;
  align-items: flex-end;
  gap: 4px;
  height: 60px;
}

.trend-bar {
  flex: 1;
  min-width: 4px;
  border-radius: 2px 2px 0 0;
  transition: height 0.3s;
}

/* 预热状态 */
.preload-status {
  padding: 8px;
  background: var(--bg-secondary);
  border-radius: 6px;
}

.progress-bar {
  height: 6px;
  background: var(--bg-primary);
  border-radius: 3px;
  overflow: hidden;
  margin-bottom: 8px;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--color-highlight), #ffa502);
  transition: width 0.3s;
}

.preload-stats {
  display: flex;
  justify-content: space-between;
  font-size: 10px;
  color: var(--text-secondary);
}

/* 告警标记 */
.alert-badge {
  position: absolute;
  top: -4px;
  right: -4px;
  width: 8px;
  height: 8px;
  background: #ff4757;
  border-radius: 50%;
  animation: pulse 1.5s infinite;
}

@keyframes pulse {

  0%,
  100% {
    opacity: 1;
    transform: scale(1);
  }

  50% {
    opacity: 0.5;
    transform: scale(1.2);
  }
}
</style>
