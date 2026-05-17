<!-- src/components/common/DataFreshness.vue -->
<template>
  <div class="data-freshness" :class="badgeToneClass" @click="showDetails = !showDetails">
    <span class="status-icon">{{ combinedIcon }}</span>
    <span class="status-text">
      {{ streamLabel }}
      <span class="subscribed-count">({{ subscribedCount }})</span>
    </span>

    <div v-if="showDetails" class="freshness-details" @click.stop>
      <div v-if="realtimeSubscribedStocks.length" class="subscription-section">
        <div class="section-header">
          <span class="section-title">TDX 热榜订阅 ({{ realtimeSubscribedStocks.length }})</span>
          <span class="section-badge" :class="statusClassName">{{ statusText }}</span>
        </div>

        <div class="stock-list">
          <div v-for="stock in realtimeSubscribedStocks" :key="stock.code" class="stock-item">
            <div class="stock-info">
              <div class="stock-name-line">
                <span class="stock-name">{{ stock.name }}</span>
                <span v-if="stock.isPriority" class="signal-pill">买+🔱</span>
              </div>
              <span class="stock-code">{{ stock.code }}</span>
            </div>
            <div class="stock-price">
              <span class="price">{{ stock.price.toFixed(2) }}</span>
              <span class="change" :class="stock.change >= 0 ? 'up' : 'down'">
                {{ stock.change > 0 ? '+' : '' }}{{ stock.change.toFixed(2) }}%
              </span>
            </div>
          </div>
        </div>

        <div v-if="lastTick" class="recent-tick">
          <span class="tick-label">最新逐笔:</span>
          <span class="tick-stock">{{ lastTick.code }}</span>
          <span class="tick-price">{{ lastTick.price }}</span>
          <span class="tick-volume">{{ lastTick.volume }}手</span>
        </div>
      </div>

      <div class="detail-item">
        <span class="detail-label">实时链路:</span>
        <span class="detail-value" :class="statusClassName">{{ statusText }}</span>
      </div>
      <div class="detail-item">
        <span class="detail-label">TDX 连接:</span>
        <span class="detail-value" :class="streamStatus.tdxConnected ? 'good' : 'warn'">
          {{ streamStatus.tdxConnected ? '✅ 已连接' : '⚠️ 未确认' }}
        </span>
      </div>
      <div class="detail-item">
        <span class="detail-label">HTTP 备用:</span>
        <span class="detail-value" :class="streamStatus.fallbackActive ? 'warn' : 'good'">
          {{ streamStatus.fallbackActive ? '启用中' : '待命' }}
        </span>
      </div>
      <div class="detail-item">
        <span class="detail-label">L2 Provider:</span>
        <span class="detail-value" :class="l2StatusClass">{{ l2StatusText }}</span>
      </div>
      <div class="detail-item">
        <span class="detail-label">十档深度:</span>
        <span class="detail-value" :class="l2DepthLevelCount >= 10 ? 'good' : 'warn'">
          {{ l2DepthLevelCount }}档
        </span>
      </div>
      <div class="detail-item">
        <span class="detail-label">订阅总数:</span>
        <span class="detail-value">{{ subscribedCount }}只</span>
      </div>
      <div class="detail-item">
        <span class="detail-label">当前时段:</span>
        <span class="detail-value" :class="isTradingSession ? 'good' : 'info'">
          {{ isTradingSession ? '交易时段' : '非交易时段' }}
        </span>
      </div>
      <div class="detail-item">
        <span class="detail-label">股票总数:</span>
        <span class="detail-value">{{ stockCount }}只</span>
      </div>
      <div class="detail-item">
        <span class="detail-label">最后更新:</span>
        <span class="detail-value">{{ lastUpdateTime }}</span>
      </div>
      <div class="detail-item">
        <span class="detail-label">数据状态:</span>
        <span class="detail-value" :class="dataStatusClass">{{ dataStatusText }}</span>
      </div>
      <button class="refresh-btn" @click="manualRefresh">手动刷新</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { dataLayer } from '@/services/DataLayer'
import { RefreshManager } from '@/services/RefreshManager'
import { webSocketService } from '@/services/websocket'
import { EventManager } from '@/utils/eventManager'
import { isTradingTime } from '@/utils/time'
import { AppEvents } from '@/types'

const showDetails = ref(false)
const streamStatus = ref(webSocketService.getStatus())
const subscribedCodes = ref<string[]>(webSocketService.getSubscribedStocks())
const lastTick = ref<{ code: string; price: number; volume: number } | null>(null)
const clockTick = ref(Date.now())

let clickOutsideHandler: ((event: MouseEvent) => void) | null = null
let updateTimer: ReturnType<typeof setInterval> | null = null
const unsubscribeFns: Array<() => void> = []

const realtimeSubscribedStocks = computed(() => {
  const stocks = dataLayer.getStocks()
  const stockMap = new Map(stocks.map((item) => [item.code, item]))

  const getCandidateTier = (stock: any) => stock?.rankTrend?.strategy?.candidateTier ?? null
  const getStrategyAction = (stock: any) => stock?.rankTrend?.strategy?.action ?? null
  const getFinalSignal = (stock: any) => stock?.rankTrend?.decision?.final?.signal ?? 'none'
  const getFinalConfidence = (stock: any) => Number(stock?.rankTrend?.decision?.final?.confidence) || 0
  const getMacdCross = (stock: any) => stock?.rankTrend?.technical?.macd?.cross ?? 'none'
  const getRankChange = (stock: any) => Number(stock?.rankTrend?.meta?.change) || 0
  const getCompRank = (stock: any) => {
    const compRank = Number(stock?.compRank)
    if (Number.isFinite(compRank) && compRank > 0) return compRank
    const fallbackRank = Number(stock?.rank)
    if (Number.isFinite(fallbackRank) && fallbackRank > 0) return fallbackRank
    return 9999
  }

  const isMainFocusStock = (stock: any) =>
    getCandidateTier(stock) === 'A_MAIN' && getStrategyAction(stock) === 'focus'

  const priorityOf = (stock: any) => {
    const finalSignal = getFinalSignal(stock)
    const macdCross = getMacdCross(stock)
    if (finalSignal === 'buy' && macdCross === 'golden') return 3
    if (finalSignal === 'buy') return 2
    if (macdCross === 'golden') return 1
    return 0
  }

  return subscribedCodes.value
    .map((code) => stockMap.get(code) || null)
    .filter((stock): stock is NonNullable<typeof stock> => Boolean(stock) && isMainFocusStock(stock))
    .map((stock) => ({
      code: stock.code,
      name: stock.name || stock.code,
      price: Number(stock.price) || 0,
      change: Number(stock.change) || 0,
      turnover: Number(stock.turnover) || 0,
      compRank: getCompRank(stock),
      finalConfidence: getFinalConfidence(stock),
      rankChange: getRankChange(stock),
      priority: priorityOf(stock),
      isPriority: priorityOf(stock) === 3,
    }))
    .filter(Boolean)
    .sort((left: any, right: any) => {
      if (left.compRank !== right.compRank) return left.compRank - right.compRank
      if (right.priority !== left.priority) return right.priority - left.priority
      if (right.finalConfidence !== left.finalConfidence) return right.finalConfidence - left.finalConfidence
      if (right.rankChange !== left.rankChange) return right.rankChange - left.rankChange
      if (right.change !== left.change) return right.change - left.change
      return right.turnover - left.turnover
    })
    .slice(0, 10) as Array<{
      code: string
      name: string
      price: number
      change: number
      turnover: number
      compRank: number
      finalConfidence: number
      rankChange: number
      priority: number
      isPriority: boolean
    }>
})

const subscribedCount = computed(() => streamStatus.value.subscribedCount || subscribedCodes.value.length || 0)
const l2DepthLevelCount = computed(() => Number(streamStatus.value.l2?.depthLevelCount) || 0)
const l2StatusText = computed(() => {
  const l2 = streamStatus.value.l2
  if (!l2?.provider) return '未启用'
  return `${l2.provider}:${l2.status || 'unknown'}`
})
const l2StatusClass = computed(() => {
  const status = streamStatus.value.l2?.status
  if (status === 'ok') return 'good'
  if (status === 'disabled' || !status) return 'info'
  return 'warn'
})

const stockCount = computed(() => dataLayer.getStocks().length || 0)
const isTradingSession = computed(() => isTradingTime(new Date(clockTick.value)))

const isWsPrimaryActive = computed(() => {
  void streamStatus.value
  return webSocketService.isPrimaryActive()
})

const isTdxRealtimeHealthy = computed(() => {
  void streamStatus.value
  return webSocketService.isTdxRealtimeHealthy()
})

const latestWsActivityTime = computed(() => {
  const lastMessageTime = Number(streamStatus.value.lastMessageTime) || 0
  const lastHeartbeatTime = Number(streamStatus.value.lastHeartbeatTime) || 0
  return Math.max(lastMessageTime, lastHeartbeatTime, 0)
})

const latestStockUpdateTime = computed(() => {
  return dataLayer
    .getStocks()
    .reduce((latest, stock) => Math.max(latest, Number(stock.updatedAt) || 0), 0)
})

const lastUpdateTime = computed(() => {
  const latestUpdate = isTdxRealtimeHealthy.value && latestWsActivityTime.value > 0
    ? latestWsActivityTime.value
    : latestStockUpdateTime.value
  return latestUpdate ? new Date(latestUpdate).toLocaleTimeString() : '未知'
})

const wsActivityAgeSeconds = computed(() => {
  if (!latestWsActivityTime.value) return Infinity
  return (clockTick.value - latestWsActivityTime.value) / 1000
})

const httpActivityAgeSeconds = computed(() => {
  if (!latestStockUpdateTime.value) return Infinity
  return (clockTick.value - latestStockUpdateTime.value) / 1000
})

const wsFreshnessHealthy = computed(() => {
  return (
    isTdxRealtimeHealthy.value &&
    latestWsActivityTime.value > 0 &&
    webSocketService.hasFreshData()
  )
})

const dataStatus = computed(() => {
  if (!isTradingSession.value) {
    if (isTdxRealtimeHealthy.value) {
      if (latestWsActivityTime.value > 0 && wsActivityAgeSeconds.value < 30) return 'normal'
      if (!latestStockUpdateTime.value) return 'unknown'
      return 'normal'
    }

    if (latestStockUpdateTime.value > 0) return 'normal'
    return 'unknown'
  }

  if (isTdxRealtimeHealthy.value) {
    if (wsFreshnessHealthy.value) {
      return 'fresh'
    }

    if (!latestWsActivityTime.value) return 'unknown'
    if (wsActivityAgeSeconds.value < 15) return 'normal'
    if (wsActivityAgeSeconds.value < 30) return 'stale'
    return 'expired'
  }

  const stocks = dataLayer.getStocks()
  if (!stocks.length) return 'empty'

  if (!latestStockUpdateTime.value) return 'unknown'
  if (httpActivityAgeSeconds.value < 3) return 'fresh'
  if (httpActivityAgeSeconds.value < 10) return 'normal'
  if (httpActivityAgeSeconds.value < 30) return 'stale'
  return 'expired'
})

const dataStatusText = computed(() => {
  const texts: Record<string, string> = {
    fresh: '数据新鲜',
    normal: '数据正常',
    stale: '数据较旧',
    expired: '数据过期',
    empty: '无数据',
    unknown: '未知状态',
  }
  return texts[dataStatus.value] || '未知'
})

const dataStatusClass = computed(() => {
  const classes: Record<string, string> = {
    fresh: 'data-fresh',
    normal: 'data-normal',
    stale: 'data-stale',
    expired: 'data-expired',
    empty: 'data-empty',
    unknown: 'data-unknown',
  }
  return classes[dataStatus.value] || ''
})

const badgeLevel = computed<'fresh' | 'normal' | 'expired' | 'unknown'>(() => {
  if (dataStatus.value === 'fresh') return 'fresh'
  if (dataStatus.value === 'expired' || dataStatus.value === 'empty') return 'expired'
  if (dataStatus.value === 'unknown') return 'unknown'
  return 'normal'
})

const effectiveMode = computed<'ws' | 'recovering' | 'http'>(() => {
  if (isTdxRealtimeHealthy.value) return 'ws'
  if (isWsPrimaryActive.value) return 'recovering'
  return 'http'
})

const streamLabel = computed(() => {
  if (effectiveMode.value === 'ws') return 'TDX实时'
  if (effectiveMode.value === 'recovering') return 'TDX恢复中'
  return 'HTTP备用'
})

const statusText = computed(() => {
  if (effectiveMode.value === 'ws') return 'TDX实时'
  if (effectiveMode.value === 'recovering') return 'TDX恢复中'
  return 'HTTP备用'
})

const statusClassName = computed(() => {
  if (effectiveMode.value === 'ws') return 'good'
  if (effectiveMode.value === 'recovering') return 'info'
  return 'warn'
})

const badgeToneClass = computed(() => {
  const toneMap: Record<string, string> = {
    fresh: 'status-fresh',
    normal: 'status-normal',
    expired: 'status-expired',
    unknown: 'status-unknown',
  }
  return toneMap[badgeLevel.value] || 'status-unknown'
})

const combinedIcon = computed(() => {
  const iconMap: Record<string, string> = {
    fresh: '🟢',
    normal: '🔵',
    expired: '🔴',
    unknown: '⚪',
  }
  return iconMap[badgeLevel.value] || '⚪'
})

const updateStatus = () => {
  streamStatus.value = webSocketService.getStatus()
}

const updateSubscriptionList = (payload?: any) => {
  if (Array.isArray(payload)) {
    subscribedCodes.value = payload
    return
  }
  subscribedCodes.value = webSocketService.getSubscribedStocks()
}

const handleTick = (payload: any) => {
  lastTick.value = {
    code: String(payload?.code || ''),
    price: Number(payload?.price) || 0,
    volume: Number(payload?.volume) || 0,
  }
}

const manualRefresh = async () => {
  EventManager.emit(AppEvents.UI.TOAST, {
    message: '正在刷新数据...',
    duration: 1000,
    type: 'info',
  })
  const result = await RefreshManager.requestRefresh({
    kind: 'full',
    source: 'data-freshness',
    trigger: 'manual',
    force: true,
  })
  if (result.busy || result.skipped) {
    EventManager.emit(AppEvents.UI.TOAST, {
      message: result.busy ? '刷新进行中' : '刷新已跳过',
      duration: 1500,
      type: 'info',
    })
  } else if (!result.success) {
    EventManager.emit(AppEvents.UI.TOAST, {
      message: '刷新失败，请稍后重试',
      duration: 2000,
      type: 'error',
    })
  }
  showDetails.value = false
}

onMounted(() => {
  clickOutsideHandler = (event: MouseEvent) => {
    const target = event.target as HTMLElement
    if (!target.closest('.data-freshness')) {
      showDetails.value = false
    }
  }
  document.addEventListener('click', clickOutsideHandler)

  updateStatus()
  updateSubscriptionList()

  updateTimer = setInterval(() => {
    clockTick.value = Date.now()
  }, 1000)

  unsubscribeFns.push(EventManager.on(AppEvents.WEBSOCKET.STATUS_CHANGED, updateStatus))
  unsubscribeFns.push(EventManager.on(AppEvents.WEBSOCKET.SUBSCRIPTION_UPDATED, updateSubscriptionList))
  unsubscribeFns.push(EventManager.on(AppEvents.WEBSOCKET.FULL_STATE, updateStatus))
  unsubscribeFns.push(EventManager.on(AppEvents.WEBSOCKET.QUOTE_PATCH, updateStatus))
  unsubscribeFns.push(EventManager.on(AppEvents.WEBSOCKET.DEPTH_PATCH, updateStatus))
  unsubscribeFns.push(EventManager.on(AppEvents.WEBSOCKET.HEARTBEAT, updateStatus))
  unsubscribeFns.push(EventManager.on(AppEvents.WEBSOCKET.TICK, handleTick))
})

onUnmounted(() => {
  if (clickOutsideHandler) {
    document.removeEventListener('click', clickOutsideHandler)
  }

  if (updateTimer) {
    clearInterval(updateTimer)
    updateTimer = null
  }

  unsubscribeFns.forEach((unsubscribe) => {
    try {
      unsubscribe()
    } catch (error) {
      console.warn('[DataFreshness] 清理订阅失败:', error)
    }
  })
  unsubscribeFns.length = 0
})
</script>

<style scoped>
.data-freshness {
  display: inline-flex;
  align-items: center;
  padding: 4px 12px;
  border-radius: 20px;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s;
  position: relative;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  user-select: none;
  z-index: 100;
}

.data-freshness:hover {
  transform: translateY(-1px);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}

.status-icon {
  margin-right: 6px;
  font-size: 14px;
}

.status-text {
  font-weight: 500;
}

.subscribed-count {
  margin-left: 4px;
  font-size: 10px;
  opacity: 0.8;
}

.status-fresh {
  color: #2ecc71;
  border-color: #2ecc71;
  background: rgba(46, 204, 113, 0.1);
}

.status-normal {
  color: #3498db;
  border-color: #3498db;
  background: rgba(52, 152, 219, 0.1);
}

.status-expired {
  color: #e74c3c;
  border-color: #e74c3c;
  background: rgba(231, 76, 60, 0.1);
}

.status-unknown {
  color: #95a5a6;
  border-color: #95a5a6;
  background: rgba(149, 165, 166, 0.1);
}

.data-fresh {
  color: #2ecc71;
  border-color: #2ecc71;
}

.data-normal {
  color: #3498db;
  border-color: #3498db;
}

.data-stale {
  color: #e67e22;
  border-color: #e67e22;
}

.data-expired {
  color: #e74c3c;
  border-color: #e74c3c;
}

.data-empty,
.data-unknown {
  color: #95a5a6;
  border-color: #95a5a6;
}

.freshness-details {
  position: absolute;
  top: 100%;
  right: 0;
  margin-top: 8px;
  background: var(--bg-panel);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 16px;
  width: min(276px, calc(100vw - 24px));
  max-width: calc(100vw - 24px);
  max-height: min(70vh, 560px);
  overflow-y: auto;
  overflow-x: hidden;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.15);
  z-index: 10000;
  backdrop-filter: blur(10px);
}

.detail-item {
  display: flex;
  justify-content: space-between;
  margin-bottom: 10px;
  font-size: 12px;
  line-height: 1.5;
}

.detail-label {
  color: var(--text-secondary);
  font-weight: 500;
}

.detail-value {
  font-weight: 600;
}

.detail-value.good {
  color: #2ecc71;
}

.detail-value.warn {
  color: #e67e22;
}

.detail-value.info {
  color: #3498db;
}

.detail-value.error {
  color: #e74c3c;
}

.refresh-btn {
  width: 100%;
  margin-top: 12px;
  padding: 8px;
  background: var(--color-highlight);
  border: none;
  border-radius: 8px;
  color: #000;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.refresh-btn:hover {
  opacity: 0.9;
  transform: translateY(-1px);
}

.subscription-section {
  margin-bottom: 16px;
  padding: 12px;
  background: var(--bg-primary);
  border-radius: 8px;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

.section-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-highlight);
}

.section-badge {
  font-size: 10px;
  padding: 2px 8px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.08);
}

.section-badge.good {
  color: #2ecc71;
}

.section-badge.info {
  color: #3498db;
}

.section-badge.warn {
  color: #e67e22;
}

.stock-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 10px;
}

.stock-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  padding: 8px 9px;
  background: var(--bg-secondary);
  border-radius: 6px;
  font-size: 12px;
}

.stock-info {
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex: 1;
}

.stock-name-line {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.stock-name {
  font-weight: 600;
  color: var(--text-primary);
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.stock-code {
  font-size: 10px;
  color: var(--text-secondary);
  font-family: monospace;
}

.signal-pill {
  flex-shrink: 0;
  padding: 1px 6px;
  border-radius: 999px;
  background: rgba(255, 107, 107, 0.14);
  color: #ff6b6b;
  font-size: 10px;
  font-weight: 700;
}

.stock-price {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  min-width: 70px;
}

.price {
  font-weight: 600;
  color: var(--text-primary);
}

.change {
  font-size: 11px;
  font-weight: 500;
}

.change.up {
  color: #ff4757;
}

.change.down {
  color: #2ed573;
}

.recent-tick {
  margin-top: 8px;
  padding: 6px 8px;
  background: rgba(46, 204, 113, 0.1);
  border-radius: 4px;
  font-size: 11px;
  display: flex;
  gap: 8px;
  align-items: center;
  border-left: 2px solid #2ecc71;
}

.tick-label {
  color: #2ecc71;
  font-weight: 600;
}

.tick-stock {
  font-weight: 500;
  color: var(--text-primary);
}

.tick-price {
  font-weight: 600;
  color: #ff4757;
}

.tick-volume {
  color: var(--text-secondary);
  font-size: 10px;
}
</style>
