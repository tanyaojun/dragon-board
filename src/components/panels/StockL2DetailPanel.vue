<!-- src/components/panels/StockL2DetailPanel.vue -->
<template>
  <div
    v-if="visible"
    ref="panelRef"
    class="stock-l2-panel"
    :style="stockPanelStyle"
    role="dialog"
    aria-label="股票盘口详情"
  >
    <div class="panel-header">
      <div>
        <div class="panel-title-row">
          <div class="panel-title">{{ resolvedStockName || stockCode || '十档详情' }}</div>
          <span class="stream-pill">{{ streamText }}</span>
        </div>
        <div class="panel-subtitle">
          <span>{{ stockCode || '--' }}</span>
          <span class="subtitle-dot">·</span>
          <span>{{ lastUpdateText }}</span>
        </div>
      </div>
      <button class="close-btn" type="button" aria-label="关闭详情面板" @click="emit('close')">×</button>
    </div>

    <div v-if="stock" class="panel-body">
      <section class="quote-board">
        <div class="quote-primary">
          <span class="quote-kicker">最新价</span>
          <strong class="quote-price" :class="priceClass">{{ formatPrice(stock.price) }}</strong>
          <span class="quote-change" :class="priceClass">{{ formatPercent(stock.change) }}</span>
        </div>

        <div class="quote-metrics">
          <div class="metric-item">
            <span>买1</span>
            <strong class="buy-price">{{ formatPrice(panelSummary.bid1Price) }}</strong>
          </div>
          <div class="metric-item">
            <span>卖1</span>
            <strong class="sell-price">{{ formatPrice(panelSummary.ask1Price) }}</strong>
          </div>
          <div class="metric-item">
            <span>近60s主买</span>
            <strong class="buy-price">{{ formatTickWindowVolume(panelSummary.tickBuyVolume) }}</strong>
          </div>
          <div class="metric-item">
            <span>近60s主卖</span>
            <strong class="sell-price">{{ formatTickWindowVolume(panelSummary.tickSellVolume) }}</strong>
          </div>
        </div>

        <div class="imbalance-panel">
          <div class="imbalance-heading">
            <span>{{ depthTitle }}盘口</span>
            <strong :class="depthClass">{{ imbalanceLabel }}</strong>
          </div>
          <div class="imbalance-track" :class="depthTrendClass" :style="imbalanceMeterStyle">
            <span class="track-midline"></span>
            <span class="imbalance-fill"></span>
          </div>
          <div class="imbalance-meta">
            <span class="buy-price">买 {{ formatVolume(panelSummary.bidTotal, true) }}</span>
            <span class="sell-price">卖 {{ formatVolume(panelSummary.askTotal, true) }}</span>
          </div>
        </div>
      </section>

      <section class="order-book-shell">
        <div class="order-book-header">
          <div>
            <span class="section-eyebrow">Order Book</span>
            <strong>{{ depthTitle }}盘口深度</strong>
          </div>
          <span class="book-state" :class="depthClass">{{ formatPercent((panelSummary.depthImbalance || 0) * 100) }}</span>
        </div>

        <div class="depth-layout">
          <div class="depth-card sell-book" :class="{ 'is-empty-book': !hasAskDepth }">
            <div class="depth-titlebar">
              <span>卖盘压力</span>
              <strong class="sell-price">{{ formatVolume(panelSummary.askTotal, true) }}</strong>
            </div>
            <div class="depth-header sell-header">
              <span>档位</span>
              <span class="align-right">价格</span>
              <span class="align-right">数量</span>
            </div>
            <div
              v-for="row in askRows"
              :key="`ask-${row.level}`"
              class="depth-row depth-row-sell"
              :class="{ 'is-empty-row': !hasDepthData(row) }"
              :style="depthBarStyle(row.volume, askMaxVolume)"
            >
              <span class="level-tag sell-tag">卖{{ row.level }}</span>
              <span class="depth-price sell-price">{{ formatPrice(row.price) }}</span>
              <span class="depth-volume">{{ formatVolume(row.volume) }}</span>
            </div>
            <div v-if="!hasAskDepth" class="book-empty-note sell-empty">卖盘暂空</div>
          </div>

          <div class="spread-rail">
            <span>Spread</span>
            <strong>{{ spreadText }}</strong>
            <em>{{ bookMoodText }}</em>
          </div>

          <div class="depth-card buy-book" :class="{ 'is-empty-book': !hasBidDepth }">
            <div class="depth-titlebar">
              <span>买盘承接</span>
              <strong class="buy-price">{{ formatVolume(panelSummary.bidTotal, true) }}</strong>
            </div>
            <div class="depth-header buy-header">
              <span>档位</span>
              <span class="align-right">价格</span>
              <span class="align-right">数量</span>
            </div>
            <div
              v-for="row in bidRows"
              :key="`bid-${row.level}`"
              class="depth-row depth-row-buy"
              :class="{ 'is-empty-row': !hasDepthData(row) }"
              :style="depthBarStyle(row.volume, bidMaxVolume)"
            >
              <span class="level-tag buy-tag">买{{ row.level }}</span>
              <span class="depth-price buy-price">{{ formatPrice(row.price) }}</span>
              <span class="depth-volume">{{ formatVolume(row.volume) }}</span>
            </div>
            <div v-if="!hasBidDepth" class="book-empty-note buy-empty">买盘暂空</div>
          </div>
        </div>
      </section>

      <div v-if="depthNotice" class="depth-notice">{{ depthNotice }}</div>

      <div class="ticks-card">
        <div class="ticks-header">
          <div>
            <span class="section-eyebrow">Tape</span>
            <strong>最近逐笔</strong>
          </div>
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

const stockPanelStyle = computed(() => ({
  ...panelStyle.value,
  '--panel-top': panelStyle.value.top || '100px',
}))

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

const askMaxVolume = computed(() => Math.max(...askRows.value.map((row) => row.volume), 0))

const bidMaxVolume = computed(() => Math.max(...bidRows.value.map((row) => row.volume), 0))

const hasAskDepth = computed(() => askRows.value.some(hasDepthData))

const hasBidDepth = computed(() => bidRows.value.some(hasDepthData))

const imbalanceMeterStyle = computed(() => {
  const imbalance = Number(panelSummary.value.depthImbalance) || 0
  const width = Math.max(4, Math.min(Math.abs(imbalance) * 50, 50))
  const left = imbalance >= 0 ? 50 : 50 - width
  return {
    '--imbalance-left': `${left}%`,
    '--imbalance-width': `${width}%`,
  }
})

const imbalanceLabel = computed(() => formatPercent((panelSummary.value.depthImbalance || 0) * 100))

const depthTrendClass = computed(() => {
  const imbalance = Number(panelSummary.value.depthImbalance) || 0
  if (imbalance > 0) return 'is-buy-strong'
  if (imbalance < 0) return 'is-sell-strong'
  return 'is-balanced'
})

const spreadText = computed(() => {
  const bid1 = Number(panelSummary.value.bid1Price)
  const ask1 = Number(panelSummary.value.ask1Price)
  if (!Number.isFinite(bid1) || !Number.isFinite(ask1) || bid1 <= 0 || ask1 <= 0) return '--'
  return (ask1 - bid1).toFixed(2)
})

const bookMoodText = computed(() => {
  if (hasBidDepth.value && !hasAskDepth.value) return '单边买盘'
  if (!hasBidDepth.value && hasAskDepth.value) return '单边卖盘'
  const imbalance = Number(panelSummary.value.depthImbalance) || 0
  if (imbalance > 0.25) return '买盘占优'
  if (imbalance < -0.25) return '卖盘占优'
  return '盘口均衡'
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

function hasDepthData(row: { price: number; volume: number }) {
  return row.price > 0 || row.volume > 0
}

function depthBarStyle(volume: number, maxVolume: number) {
  const current = Number(volume)
  const max = Number(maxVolume)
  const depthStrength = Number.isFinite(current) && Number.isFinite(max) && max > 0 ? current / max : 0
  return {
    '--depth-strength': `${Math.max(0.04, Math.min(depthStrength, 1)) * 100}%`,
  }
}
</script>

<style scoped>
.stock-l2-panel {
  --l2-buy: #ff5968;
  --l2-buy-soft: rgba(255, 89, 104, 0.14);
  --l2-sell: #19d987;
  --l2-sell-soft: rgba(25, 217, 135, 0.14);
  --l2-amber: #f5c55e;
  --l2-border: rgba(255, 255, 255, 0.13);
  --l2-divider: rgba(255, 255, 255, 0.07);

  position: fixed;
  z-index: 10080;
  width: min(800px, calc(100vw - 32px));
  max-height: min(820px, calc(100vh - var(--panel-top, 100px) - 16px));
  overflow: hidden;
  border-radius: 18px;
  border: 1px solid;
  border-color: color-mix(in srgb, var(--border-color) 64%, white 20%);
  background:
    radial-gradient(circle at 8% 0%, rgba(245, 197, 94, 0.14), transparent 33%),
    radial-gradient(circle at 100% 16%, rgba(255, 89, 104, 0.11), transparent 28%),
    linear-gradient(180deg, rgba(255, 255, 255, 0.06), rgba(255, 255, 255, 0.015)),
    color-mix(in srgb, var(--bg-panel) 88%, #080b0f 12%);
  box-shadow:
    0 28px 80px rgba(0, 0, 0, 0.46),
    inset 0 1px 0 rgba(255, 255, 255, 0.1);
  backdrop-filter: blur(18px) saturate(1.08);
  color: var(--text-primary);
  isolation: isolate;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 16px 18px 13px;
  border-bottom: 1px solid;
  border-bottom-color: var(--l2-divider);
  background:
    linear-gradient(90deg, rgba(245, 197, 94, 0.11), transparent 44%),
    rgba(0, 0, 0, 0.16);
}

.panel-title-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}

.panel-title {
  color: var(--text-primary);
  font-size: 20px;
  font-weight: 800;
  line-height: 1.25;
}

.panel-subtitle {
  display: flex;
  align-items: center;
  gap: 7px;
  margin-top: 5px;
  color: var(--text-secondary);
  font-family: Consolas, 'SF Mono', Monaco, monospace;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.stream-pill {
  display: inline-flex;
  align-items: center;
  min-height: 22px;
  padding: 0 9px;
  border: 1px solid;
  border-radius: 999px;
  border-color: rgba(245, 197, 94, 0.28);
  background: rgba(245, 197, 94, 0.12);
  color: var(--l2-amber);
  font-size: 11px;
  font-weight: 800;
}

.subtitle-dot {
  opacity: 0.55;
}

.close-btn {
  flex: 0 0 auto;
  width: 44px;
  height: 44px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.07);
  color: var(--text-primary);
  font-size: 22px;
  line-height: 1;
  cursor: pointer;
  transition:
    background-color 160ms ease,
    border-color 160ms ease,
    transform 160ms ease;
}

.close-btn:hover,
.close-btn:focus-visible {
  border-color: rgba(255, 255, 255, 0.18);
  background: rgba(255, 255, 255, 0.13);
  outline: none;
}

.close-btn:active {
  transform: scale(0.96);
}

.panel-body {
  padding: 14px 15px 16px;
  overflow: auto;
  max-height: calc(100vh - var(--panel-top, 100px) - 88px);
}

.quote-board {
  display: grid;
  grid-template-columns: minmax(176px, 0.85fr) minmax(260px, 1.35fr) minmax(190px, 0.95fr);
  gap: 12px;
  margin-bottom: 12px;
}

.quote-primary,
.quote-metrics,
.imbalance-panel,
.order-book-shell,
.ticks-card,
.depth-card {
  border: 1px solid var(--l2-border);
  border-radius: 14px;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.06), transparent),
    color-mix(in srgb, var(--bg-secondary) 82%, #07090c 18%);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
}

.quote-primary {
  display: flex;
  flex-direction: column;
  justify-content: center;
  position: relative;
  min-height: 122px;
  overflow: hidden;
  padding: 16px 18px;
  background:
    linear-gradient(135deg, rgba(255, 89, 104, 0.18), transparent 58%),
    color-mix(in srgb, var(--bg-secondary) 76%, #08090c 24%);
}

.quote-primary::before {
  position: absolute;
  inset: 10px auto 10px 0;
  width: 4px;
  border-radius: 0 999px 999px 0;
  content: '';
  background: var(--l2-buy);
}

.quote-kicker,
.section-eyebrow {
  display: block;
  margin-bottom: 5px;
  color: var(--text-secondary);
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0;
  text-transform: uppercase;
}

.quote-price {
  display: block;
  font-family: Consolas, 'SF Mono', Monaco, monospace;
  font-size: 38px;
  font-variant-numeric: tabular-nums;
  font-weight: 800;
  line-height: 1;
}

.quote-change {
  margin-top: 7px;
  font-family: Consolas, 'SF Mono', Monaco, monospace;
  font-size: 16px;
  font-variant-numeric: tabular-nums;
  font-weight: 800;
}

.quote-metrics {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  overflow: hidden;
}

.metric-item {
  display: flex;
  flex-direction: column;
  justify-content: center;
  min-height: 61px;
  padding: 13px 14px;
  border-right: 1px solid var(--l2-divider);
  border-bottom: 1px solid var(--l2-divider);
}

.metric-item:nth-child(2n) {
  border-right: none;
}

.metric-item:nth-last-child(-n + 2) {
  border-bottom: none;
}

.metric-item span,
.imbalance-heading span,
.depth-titlebar span {
  color: var(--text-secondary);
  font-size: 11px;
  font-weight: 800;
}

.metric-item strong {
  margin-top: 7px;
  font-family: Consolas, 'SF Mono', Monaco, monospace;
  font-size: 16px;
  font-variant-numeric: tabular-nums;
  font-weight: 800;
}

.imbalance-panel {
  display: flex;
  flex-direction: column;
  justify-content: center;
  min-height: 122px;
  padding: 14px;
}

.imbalance-heading,
.imbalance-meta,
.order-book-header,
.depth-titlebar,
.ticks-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.imbalance-heading strong,
.book-state {
  font-family: Consolas, 'SF Mono', Monaco, monospace;
  font-size: 15px;
  font-variant-numeric: tabular-nums;
  font-weight: 800;
}

.imbalance-track {
  position: relative;
  height: 18px;
  margin: 18px 0 13px;
  overflow: hidden;
  border-radius: 999px;
  background:
    linear-gradient(90deg, rgba(25, 217, 135, 0.2), transparent 46%),
    linear-gradient(90deg, transparent 54%, rgba(255, 89, 104, 0.22)),
    rgba(255, 255, 255, 0.06);
}

.track-midline {
  position: absolute;
  top: 2px;
  bottom: 2px;
  left: 50%;
  width: 1px;
  background: rgba(255, 255, 255, 0.28);
}

.imbalance-fill {
  position: absolute;
  top: 3px;
  bottom: 3px;
  left: var(--imbalance-left);
  width: var(--imbalance-width);
  min-width: 4px;
  border-radius: 999px;
}

.imbalance-track.is-buy-strong .imbalance-fill {
  background: linear-gradient(90deg, var(--l2-buy-soft), var(--l2-buy));
}

.imbalance-track.is-sell-strong .imbalance-fill {
  background: linear-gradient(90deg, var(--l2-sell), var(--l2-sell-soft));
}

.imbalance-track.is-balanced .imbalance-fill {
  background: rgba(255, 255, 255, 0.34);
}

.imbalance-meta {
  font-family: Consolas, 'SF Mono', Monaco, monospace;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  font-weight: 800;
}

.order-book-shell {
  padding: 13px;
  margin-bottom: 12px;
}

.order-book-header {
  margin-bottom: 12px;
}

.order-book-header strong,
.ticks-header strong {
  display: block;
  color: var(--text-primary);
  font-size: 14px;
  font-weight: 800;
}

.depth-layout {
  display: grid;
  gap: 12px;
  margin-bottom: 0;
}

.depth-card {
  overflow: hidden;
}

.sell-book {
  background:
    linear-gradient(180deg, rgba(25, 217, 135, 0.065), transparent 38%),
    color-mix(in srgb, var(--bg-secondary) 82%, #07090c 18%);
}

.buy-book {
  background:
    linear-gradient(180deg, rgba(255, 89, 104, 0.075), transparent 38%),
    color-mix(in srgb, var(--bg-secondary) 82%, #07090c 18%);
}

.is-empty-book {
  opacity: 0.78;
}

.depth-titlebar {
  padding: 12px 13px 10px;
}

.depth-titlebar strong {
  font-family: Consolas, 'SF Mono', Monaco, monospace;
  font-size: 13px;
  font-variant-numeric: tabular-nums;
  font-weight: 800;
}

.depth-header {
  display: grid;
  grid-template-columns: 52px minmax(72px, 1fr) minmax(72px, 1fr);
  align-items: center;
  gap: 12px;
  padding: 9px 13px;
  border-top: 1px solid var(--l2-divider);
  border-bottom: 1px solid var(--l2-divider);
  background: rgba(0, 0, 0, 0.16);
  font-size: 11px;
  font-weight: 800;
}

.sell-header {
  color: var(--l2-sell);
}

.buy-header {
  color: var(--l2-buy);
}

.depth-row,
.tick-row,
.ticks-columns {
  display: grid;
  align-items: center;
  gap: 12px;
  padding: 9px 13px;
  font-size: 12px;
}

.depth-row,
.tick-row {
  border-bottom: 1px solid var(--l2-divider);
}

.depth-row {
  position: relative;
  grid-template-columns: 52px minmax(72px, 1fr) minmax(72px, 1fr);
  min-height: 39px;
  overflow: hidden;
}

.depth-row > * {
  position: relative;
  z-index: 1;
}

.depth-row::before {
  position: absolute;
  top: 5px;
  right: 8px;
  bottom: 5px;
  width: var(--depth-strength);
  max-width: calc(100% - 16px);
  min-width: 0;
  border-radius: 9px;
  content: '';
  opacity: 0.92;
}

.depth-row-sell::before {
  background: linear-gradient(90deg, transparent, rgba(25, 217, 135, 0.22));
}

.depth-row-buy::before {
  background: linear-gradient(90deg, transparent, rgba(255, 89, 104, 0.24));
}

.is-empty-row {
  color: var(--text-secondary);
}

.is-empty-row::before {
  display: none;
}

.level-tag {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  padding: 4px 0;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 800;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.045);
}

.sell-tag {
  color: var(--l2-sell);
  background: var(--l2-sell-soft);
}

.buy-tag {
  color: var(--l2-buy);
  background: var(--l2-buy-soft);
}

.depth-price,
.tick-price,
.depth-volume,
.tick-volume,
.tick-amount,
.tick-time {
  font-family: Consolas, 'SF Mono', Monaco, monospace;
  font-variant-numeric: tabular-nums;
}

.buy-price,
.tick-side.buy {
  color: var(--l2-buy);
}

.sell-price,
.tick-side.sell {
  color: var(--l2-sell);
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

.depth-notice {
  margin: 0 0 12px;
  padding: 11px 13px;
  border: 1px solid;
  border-color: rgba(245, 197, 94, 0.18);
  border-radius: 14px;
  background:
    linear-gradient(90deg, rgba(245, 197, 94, 0.12), transparent),
    rgba(0, 0, 0, 0.1);
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.55;
}

.ticks-card {
  overflow: hidden;
}

.ticks-header {
  padding: 12px 13px;
  border-bottom: 1px solid var(--l2-divider);
  background: rgba(0, 0, 0, 0.12);
}

.ticks-header > span {
  color: var(--text-secondary);
  font-family: Consolas, 'SF Mono', Monaco, monospace;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  font-weight: 800;
}

.ticks-columns {
  grid-template-columns: 72px 52px minmax(64px, 1fr) minmax(72px, 1fr) minmax(88px, 1fr);
  border-bottom-color: var(--l2-divider);
  background: rgba(0, 0, 0, 0.14);
  color: var(--text-secondary);
  font-size: 11px;
  font-weight: 800;
}

.tick-row {
  grid-template-columns: 72px 52px minmax(64px, 1fr) minmax(72px, 1fr) minmax(88px, 1fr);
}

.tick-side {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 38px;
  min-height: 22px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 800;
}

.tick-side.buy {
  background: var(--l2-buy-soft);
}

.tick-side.sell {
  background: var(--l2-sell-soft);
}

.tick-side.neutral {
  color: var(--text-secondary);
  background: rgba(255, 255, 255, 0.06);
}

.ticks-list {
  max-height: 260px;
  overflow: auto;
}

.empty-state {
  padding: 28px 24px;
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.6;
  text-align: center;
}

.depth-layout {
  grid-template-columns: minmax(0, 1fr) 72px minmax(0, 1fr);
  align-items: stretch;
}

.spread-rail {
  display: grid;
  align-content: center;
  justify-items: center;
  gap: 8px;
  min-height: 100%;
  padding: 12px 8px;
  border: 1px solid rgba(245, 197, 94, 0.2);
  border-radius: 14px;
  background:
    linear-gradient(180deg, rgba(245, 197, 94, 0.16), transparent 44%, rgba(255, 89, 104, 0.1)),
    rgba(0, 0, 0, 0.18);
  color: var(--text-secondary);
  text-align: center;
}

.spread-rail::before,
.spread-rail::after {
  width: 1px;
  height: 64px;
  content: '';
  background: linear-gradient(180deg, transparent, rgba(245, 197, 94, 0.55), transparent);
}

.spread-rail span {
  color: var(--l2-amber);
  font-size: 10px;
  font-weight: 900;
}

.spread-rail strong {
  color: var(--text-primary);
  font-family: Consolas, 'SF Mono', Monaco, monospace;
  font-size: 17px;
  font-variant-numeric: tabular-nums;
  font-weight: 900;
}

.spread-rail em {
  max-width: 4em;
  color: var(--text-secondary);
  font-size: 11px;
  font-style: normal;
  font-weight: 800;
  line-height: 1.35;
}

.book-empty-note {
  margin: 10px 12px 12px;
  padding: 10px 12px;
  border: 1px dashed rgba(255, 255, 255, 0.16);
  border-radius: 12px;
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 800;
  text-align: center;
}

.sell-empty {
  border-color: rgba(25, 217, 135, 0.26);
  color: var(--l2-sell);
}

.buy-empty {
  border-color: rgba(255, 89, 104, 0.28);
  color: var(--l2-buy);
}

.depth-card {
  position: relative;
}

.depth-card::after {
  position: absolute;
  inset: 0;
  pointer-events: none;
  content: '';
  background-image:
    linear-gradient(rgba(255, 255, 255, 0.035) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, 0.026) 1px, transparent 1px);
  background-size: 100% 39px, 56px 100%;
  opacity: 0.42;
}

.panel-body::-webkit-scrollbar,
.ticks-list::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}

.panel-body::-webkit-scrollbar-track,
.ticks-list::-webkit-scrollbar-track {
  background: rgba(255, 255, 255, 0.02);
}

.panel-body::-webkit-scrollbar-thumb,
.ticks-list::-webkit-scrollbar-thumb {
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.16);
}

.panel-body::-webkit-scrollbar-thumb:hover,
.ticks-list::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.26);
}

@media (max-width: 900px) {
  .quote-board {
    grid-template-columns: 1fr;
  }

  .depth-layout {
    grid-template-columns: 1fr;
  }

  .spread-rail {
    grid-template-columns: 1fr auto 1fr;
    min-height: 58px;
  }

  .spread-rail::before,
  .spread-rail::after {
    width: 100%;
    height: 1px;
  }

  .spread-rail em {
    max-width: none;
  }
}

@media (max-width: 560px) {
  .stock-l2-panel {
    width: calc(100vw - 20px);
    max-height: calc(100vh - var(--panel-top, 10px) - 10px);
    border-radius: 14px;
  }

  .panel-header {
    padding: 15px;
  }

  .panel-body {
    padding: 12px;
  }

  .quote-price {
    font-size: 32px;
  }

  .ticks-card {
    overflow-x: auto;
  }

  .ticks-list {
    min-width: 520px;
  }
}
</style>
