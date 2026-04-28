<!-- src/components/panels/StockL2DetailPanel.vue -->
<template>
  <div v-if="visible" ref="panelRef" class="stock-l2-panel" :style="panelStyle">
    <div class="panel-header">
      <div>
        <div class="panel-title">{{ resolvedStockName || stockCode || '十档详情' }}</div>
        <div class="panel-subtitle">
          {{ stockCode || '--' }} · {{ streamText }} · {{ lastUpdateText }}
        </div>
      </div>
      <button class="close-btn" @click="emit('close')">×</button>
    </div>

    <div v-if="stock" class="panel-body">
      <div class="summary-grid">
        <div class="summary-card">
          <span class="summary-label">最新价</span>
          <span class="summary-value" :class="priceClass">{{ formatPrice(stock.price) }}</span>
        </div>
        <div class="summary-card">
          <span class="summary-label">涨跌幅</span>
          <span class="summary-value" :class="priceClass">{{ formatPercent(stock.change) }}</span>
        </div>
        <div class="summary-card">
          <span class="summary-label">买1 / 卖1</span>
          <span class="summary-value summary-pair">
            <span class="buy-price">{{ formatPrice(panelSummary.bid1Price) }}</span>
            <span class="pair-divider">/</span>
            <span class="sell-price">{{ formatPrice(panelSummary.ask1Price) }}</span>
          </span>
        </div>
        <div class="summary-card">
          <span class="summary-label">{{ depthTitle }}差</span>
          <span class="summary-value" :class="depthClass">{{ formatPercent((panelSummary.depthImbalance || 0) * 100) }}</span>
        </div>
        <div class="summary-card">
          <span class="summary-label">买盘总量</span>
          <span class="summary-value buy-price">{{ formatVolume(panelSummary.bidTotal, true) }}</span>
        </div>
        <div class="summary-card">
          <span class="summary-label">卖盘总量</span>
          <span class="summary-value sell-price">{{ formatVolume(panelSummary.askTotal, true) }}</span>
        </div>
        <div class="summary-card">
          <span class="summary-label">近60s主买</span>
          <span class="summary-value buy-price">{{ formatTickWindowVolume(panelSummary.tickBuyVolume) }}</span>
        </div>
        <div class="summary-card">
          <span class="summary-label">近60s主卖</span>
          <span class="summary-value sell-price">{{ formatTickWindowVolume(panelSummary.tickSellVolume) }}</span>
        </div>
      </div>

      <div class="depth-layout">
        <div class="depth-card">
          <div class="depth-header sell-header">
            <span>卖盘{{ depthTitle }}</span>
            <span class="align-right">价格</span>
            <span class="align-right">数量</span>
          </div>
          <div v-for="row in askRows" :key="`ask-${row.level}`" class="depth-row">
            <span class="level-tag sell-tag">卖{{ row.level }}</span>
            <span class="depth-price sell-price">{{ formatPrice(row.price) }}</span>
            <span class="depth-volume">{{ formatVolume(row.volume) }}</span>
          </div>
        </div>

        <div class="depth-card">
          <div class="depth-header buy-header">
            <span>买盘{{ depthTitle }}</span>
            <span class="align-right">价格</span>
            <span class="align-right">数量</span>
          </div>
          <div v-for="row in bidRows" :key="`bid-${row.level}`" class="depth-row">
            <span class="level-tag buy-tag">买{{ row.level }}</span>
            <span class="depth-price buy-price">{{ formatPrice(row.price) }}</span>
            <span class="depth-volume">{{ formatVolume(row.volume) }}</span>
          </div>
        </div>
      </div>

      <div v-if="depthNotice" class="depth-notice">{{ depthNotice }}</div>

      <div class="ticks-card">
        <div class="ticks-header">
          <span>最近逐笔</span>
          <span>{{ recentTicks.length }} 条</span>
        </div>
        <div v-if="recentTicks.length" class="ticks-list">
          <div class="ticks-columns">
            <span>时间</span>
            <span>方向</span>
            <span class="align-right">成交价</span>
            <span class="align-right">成交量</span>
            <span class="align-right">成交额</span>
          </div>
          <div v-for="tick in recentTicks" :key="tickKey(tick)" class="tick-row">
            <span class="tick-time">{{ tick.tradeTime || '--:--:--' }}</span>
            <span class="tick-side" :class="tick.side">{{ sideLabel(tick.side) }}</span>
            <span class="tick-price" :class="tick.side === 'buy' ? 'buy-price' : tick.side === 'sell' ? 'sell-price' : ''">
              {{ formatPrice(tick.price) }}
            </span>
            <span class="tick-volume">{{ formatVolume(tick.volume) }}</span>
            <span class="tick-amount">{{ formatAmount(tick.amount) }}</span>
          </div>
        </div>
        <div v-else class="empty-state">{{ tickEmptyText }}</div>
      </div>
    </div>

    <div v-else class="empty-state">暂无该股票十档行情数据</div>
  </div>
</template>

<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import type { TickTrade } from '@/types'
import { usePanel } from '@/composables/usePanel'
import { dataLayer } from '@/services/DataLayer'
import { webSocketService } from '@/services/websocket'

const props = defineProps<{
  visible: boolean
  stockCode: string
  stockName?: string
  triggerRect?: DOMRect
}>()

const emit = defineEmits<{
  (e: 'close'): void
}>()

const { panelRef, panelStyle } = usePanel({
  name: 'StockL2DetailPanel',
  visible: props.visible,
  triggerRect: props.triggerRect,
  onClose: () => emit('close'),
})

const refreshVersion = ref(0)
let refreshTimer: ReturnType<typeof setInterval> | null = null

const startRefresh = () => {
  if (refreshTimer) return
  refreshTimer = setInterval(() => {
    refreshVersion.value++
  }, 250)
}

const stopRefresh = () => {
  if (!refreshTimer) return
  clearInterval(refreshTimer)
  refreshTimer = null
}

watch(
  () => props.visible,
  (visible) => {
    if (visible) {
      refreshVersion.value++
      startRefresh()
      return
    }
    stopRefresh()
  },
  { immediate: true },
)

watch(
  () => props.stockCode,
  () => {
    refreshVersion.value++
  },
)

onUnmounted(() => {
  stopRefresh()
})

const stock = computed(() => {
  refreshVersion.value
  return props.stockCode ? dataLayer.getStock(props.stockCode) : null
})

const depth10 = computed(() => {
  refreshVersion.value
  return props.stockCode ? dataLayer.getDepth10(props.stockCode) : null
})

const l2Summary = computed(() => {
  refreshVersion.value
  return props.stockCode ? dataLayer.getL2Summary(props.stockCode) : null
})

const recentTicks = computed(() => {
  refreshVersion.value
  if (!props.stockCode) return []
  const ticks = dataLayer.getRecentTicks(props.stockCode)
  if (ticks.length) return ticks.slice(-40).reverse()
  return webSocketService.getRecentTicks(props.stockCode).slice(-40).reverse()
})

const isInRealtimeSubscription = computed(() => {
  refreshVersion.value
  if (!props.stockCode) return false
  return webSocketService.getSubscribedStocks().includes(props.stockCode)
})

const resolvedStockName = computed(() => props.stockName || stock.value?.name || '')

const streamText = computed(() => {
  refreshVersion.value
  const status = webSocketService.getStatus()
  if (status.status === 'connected' && !status.fallbackActive) return 'TDX实时'
  return 'HTTP备用'
})

const lastUpdateText = computed(() => {
  const updateTs =
    Number(stock.value?.updatedAt) || Number(l2Summary.value?.timestamp) || Number(depth10.value?.timestamp) || 0
  return updateTs ? new Date(updateTs).toLocaleTimeString() : '等待数据'
})

const depthLevels = computed(() => {
  const maxLevels = Math.max(depth10.value?.asks?.length || 0, depth10.value?.bids?.length || 0)
  if (maxLevels >= 10) return 10
  if (maxLevels >= 5) return 5
  return Math.max(5, maxLevels || 0)
})

const depthTitle = computed(() => `${depthLevels.value}档`)

const panelSummary = computed(() => {
  const bid1 = depth10.value?.bids?.[0]
  const ask1 = depth10.value?.asks?.[0]
  const bidTotal = Number(l2Summary.value?.bid10Total) || (depth10.value?.bids || []).reduce((sum, level) => sum + (Number(level.volume) || 0), 0)
  const askTotal = Number(l2Summary.value?.ask10Total) || (depth10.value?.asks || []).reduce((sum, level) => sum + (Number(level.volume) || 0), 0)

  return {
    bid1Price: Number(l2Summary.value?.bid1Price) || Number(stock.value?.bid1Price) || Number(bid1?.price) || 0,
    ask1Price: Number(l2Summary.value?.ask1Price) || Number(stock.value?.ask1Price) || Number(ask1?.price) || 0,
    bidTotal,
    askTotal,
    depthImbalance:
      Number(l2Summary.value?.depthImbalance ?? stock.value?.depthImbalance) ||
      (() => {
        const total = bidTotal + askTotal
        return total > 0 ? (bidTotal - askTotal) / total : 0
      })(),
    tickBuyVolume: Number(l2Summary.value?.tickBuyVolume ?? stock.value?.tickBuyVolume) || 0,
    tickSellVolume: Number(l2Summary.value?.tickSellVolume ?? stock.value?.tickSellVolume) || 0,
  }
})

const askRows = computed(() => {
  const source = depth10.value?.asks || []
  return Array.from({ length: depthLevels.value }, (_, index) => {
    const level = depthLevels.value - index
    const row = source[level - 1]
    return {
      level,
      price: Number(row?.price) || 0,
      volume: Number(row?.volume) || 0,
    }
  })
})

const bidRows = computed(() => {
  const source = depth10.value?.bids || []
  return Array.from({ length: depthLevels.value }, (_, index) => {
    const level = index + 1
    const row = source[index]
    return {
      level,
      price: Number(row?.price) || 0,
      volume: Number(row?.volume) || 0,
    }
  })
})

const priceClass = computed(() => {
  const change = Number(stock.value?.change) || 0
  if (change > 0) return 'buy-price'
  if (change < 0) return 'sell-price'
  return ''
})

const depthClass = computed(() => {
  const imbalance = Number(panelSummary.value?.depthImbalance) || 0
  if (imbalance > 0) return 'buy-price'
  if (imbalance < 0) return 'sell-price'
  return ''
})

const depthNotice = computed(() => {
  const hasBids = (depth10.value?.bids?.length || 0) > 0
  const hasAsks = (depth10.value?.asks?.length || 0) > 0
  const status = webSocketService.getStatus()
  const wsPrimaryActive = status.status === 'connected' && !status.fallbackActive

  if (!isInRealtimeSubscription.value && wsPrimaryActive) {
    return '当前股票不在实时订阅池，详情面板只能显示已有缓存或 HTTP 行情，盘口不会持续刷新。'
  }
  if (!hasBids && !hasAsks) return '当前盘口数据尚未返回。'
  if (hasBids && !hasAsks) return '当前卖盘为空，常见于涨停封单或卖盘暂时缺失。'
  if (!hasBids && hasAsks) return '当前买盘为空，常见于跌停封单或买盘暂时缺失。'
  if ((depth10.value?.bids?.length || 0) <= 5 && (depth10.value?.asks?.length || 0) <= 5) {
    return '当前上游返回的是五档盘口，十档/L2 将在后续链路打通后补齐。'
  }
  return ''
})

const tickEmptyText = computed(() => {
  const status = webSocketService.getStatus()
  if (!isInRealtimeSubscription.value && status.status === 'connected' && !status.fallbackActive) {
    return '当前股票不在实时订阅池'
  }
  if (status.status === 'connected' && !status.fallbackActive) {
    return '当前上游未返回逐笔数据'
  }
  return '暂无逐笔数据'
})

function formatPrice(value?: number | null) {
  if (!Number.isFinite(Number(value)) || Number(value) <= 0) return '--'
  return Number(value).toFixed(2)
}

function formatPercent(value?: number | null) {
  if (!Number.isFinite(Number(value))) return '--'
  const numeric = Number(value)
  return `${numeric > 0 ? '+' : ''}${numeric.toFixed(2)}%`
}

function formatVolume(value?: number | null, zeroAsZero = false) {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return '--'
  if (numeric === 0) return zeroAsZero ? '0' : '--'
  if (numeric < 0) return '--'
  if (numeric >= 1e8) return `${(numeric / 1e8).toFixed(2)}亿`
  if (numeric >= 1e4) return `${(numeric / 1e4).toFixed(2)}万`
  return `${numeric}`
}

function formatTickWindowVolume(value?: number | null) {
  const numeric = Number(value)
  if (!Number.isFinite(numeric) || numeric <= 0) return '--'
  return formatVolume(numeric, true)
}

function formatAmount(value?: number | null) {
  const numeric = Number(value)
  if (!Number.isFinite(numeric) || numeric <= 0) return '--'
  if (numeric >= 1e8) return `${(numeric / 1e8).toFixed(2)}亿`
  if (numeric >= 1e4) return `${(numeric / 1e4).toFixed(2)}万`
  return numeric.toFixed(0)
}

function sideLabel(side: TickTrade['side']) {
  if (side === 'buy') return '主买'
  if (side === 'sell') return '主卖'
  return '中性'
}

function tickKey(tick: TickTrade) {
  return `${tick.tradeTime}-${tick.price}-${tick.volume}-${tick.side}`
}
</script>

<style scoped>
.stock-l2-panel {
  position: fixed;
  z-index: 10080;
  width: min(760px, calc(100vw - 32px));
  max-height: min(820px, calc(100vh - 32px));
  overflow: hidden;
  border-radius: 16px;
  border: 1px solid var(--border-color);
  background: var(--bg-panel);
  box-shadow: 0 20px 50px rgba(0, 0, 0, 0.28);
  backdrop-filter: blur(12px);
}

.panel-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 18px 20px 14px;
  border-bottom: 1px solid var(--border-color);
}

.panel-title {
  font-size: 18px;
  font-weight: 700;
  color: var(--text-primary);
}

.panel-subtitle {
  margin-top: 4px;
  font-size: 12px;
  color: var(--text-secondary);
}

.close-btn {
  width: 32px;
  height: 32px;
  border: none;
  border-radius: 50%;
  background: var(--bg-secondary);
  color: var(--text-primary);
  font-size: 22px;
  cursor: pointer;
}

.panel-body {
  padding: 16px 20px 20px;
  overflow: auto;
  max-height: calc(100vh - 140px);
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}

.summary-card,
.depth-card,
.ticks-card {
  border: 1px solid var(--border-color);
  border-radius: 12px;
  background: var(--bg-secondary);
}

.summary-card {
  padding: 12px;
}

.summary-label {
  display: block;
  margin-bottom: 6px;
  font-size: 11px;
  color: var(--text-secondary);
}

.summary-value {
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
}

.depth-layout {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
  margin-bottom: 16px;
}

.depth-notice {
  margin: -4px 0 16px;
  padding: 10px 12px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.04);
  color: var(--text-secondary);
  font-size: 12px;
}

.depth-header,
.ticks-header,
.ticks-columns {
  display: grid;
  align-items: center;
  padding: 12px 14px;
  gap: 12px;
  font-size: 12px;
  font-weight: 700;
}

.depth-header,
.ticks-header {
  border-bottom: 1px solid var(--border-color);
}

.depth-header {
  grid-template-columns: 52px minmax(72px, 1fr) minmax(72px, 1fr);
}

.ticks-header,
.ticks-columns,
.tick-row {
  grid-template-columns: 72px 52px minmax(64px, 1fr) minmax(72px, 1fr) minmax(88px, 1fr);
}

.sell-header {
  color: #2ed573;
}

.buy-header {
  color: #ff6b6b;
}

.depth-row,
.tick-row,
.ticks-columns {
  display: grid;
  align-items: center;
  padding: 8px 14px;
  font-size: 12px;
}

.depth-row,
.tick-row {
  border-bottom: 1px solid rgba(255, 255, 255, 0.04);
}

.depth-row {
  grid-template-columns: 52px minmax(72px, 1fr) minmax(72px, 1fr);
  gap: 12px;
}

.ticks-columns {
  color: var(--text-secondary);
  font-size: 11px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.04);
}

.level-tag {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 42px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
  padding: 3px 0;
}

.sell-tag {
  color: #2ed573;
  background: rgba(46, 213, 115, 0.12);
}

.buy-tag {
  color: #ff6b6b;
  background: rgba(255, 107, 107, 0.12);
}

.depth-price,
.tick-price,
.depth-volume,
.tick-volume,
.tick-amount,
.tick-time {
  font-family: 'SF Mono', Monaco, Consolas, monospace;
  font-variant-numeric: tabular-nums;
}

.summary-pair {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.pair-divider {
  color: var(--text-secondary);
}

.buy-price,
.tick-side.buy {
  color: #ff6b6b;
}

.sell-price,
.tick-side.sell {
  color: #2ed573;
}

.tick-side.neutral {
  color: var(--text-secondary);
}

.align-right,
.depth-price,
.depth-volume,
.tick-price,
.tick-volume,
.tick-amount {
  justify-self: end;
  text-align: right;
}

.ticks-list {
  max-height: 260px;
  overflow: auto;
}

.empty-state {
  padding: 24px;
  text-align: center;
  color: var(--text-secondary);
  font-size: 13px;
}

@media (max-width: 900px) {
  .summary-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .depth-layout {
    grid-template-columns: 1fr;
  }

  .ticks-header,
  .ticks-columns,
  .tick-row {
    grid-template-columns: 64px 44px minmax(60px, 1fr) minmax(64px, 1fr) minmax(76px, 1fr);
    gap: 8px;
  }
}
</style>
