<!-- src/components/common/DataFreshness.vue -->
<template>
  <div class="data-freshness" :class="[connectionClass, dataStatusClass]" @click="showDetails = !showDetails">
    <!-- 状态图标 - 组合显示 -->
    <span class="status-icon">{{ combinedIcon }}</span>

    <!-- 简要信息 -->
    <span class="status-text">
      <template v-if="alltickConnected">
        AllTick实时
        <span class="subscribed-count">({{ alltickSubscribedStocks.length }}/{{ httpSubscribedCount }})</span>
      </template>
      <template v-else>
        HTTP轮询
        <span class="subscribed-count">({{ httpSubscribedCount }})</span>
      </template>
    </span>

    <!-- 详细面板（点击展开） -->
    <div v-if="showDetails" class="freshness-details" @click.stop>
      <!-- AllTick 订阅股票列表 -->
      <div class="subscription-section" v-if="alltickConnected">
        <div class="section-header">
          <span class="section-title">📡 AllTick实时订阅 ({{ alltickSubscribedStocks.length }}/5)</span>
          <span class="section-badge" :class="{ full: alltickSubscribedStocks.length === 5 }">
            {{ alltickSubscribedStocks.length === 5 ? '满额' : '等待' }}
          </span>
        </div>

        <!-- 股票列表 -->
        <div class="stock-list">
          <div v-for="stock in alltickSubscribedStocks" :key="stock.code" class="stock-item">
            <div class="stock-info">
              <span class="stock-name">{{ stock.name }}</span>
              <span class="stock-code">{{ stock.code }}</span>
            </div>
            <div class="stock-price">
              <span class="price">{{ stock.price.toFixed(2) }}</span>
              <span class="change" :class="stock.change >= 0 ? 'up' : 'down'">
                {{ stock.change > 0 ? '+' : '' }}{{ stock.change.toFixed(2) }}%
              </span>
            </div>
            <!-- 实时成交标记 -->
            <span class="tick-badge" v-if="stock.lastTick">⚡</span>
          </div>

          <!-- 等待中的占位 -->
          <div v-for="i in 5 - alltickSubscribedStocks.length" :key="'placeholder-' + i" class="stock-item placeholder">
            <div class="stock-info">
              <span class="stock-name">等待订阅...</span>
              <span class="stock-code">------</span>
            </div>
            <div class="stock-price">
              <span class="price">--.--</span>
              <span class="change">--.--%</span>
            </div>
          </div>
        </div>

        <!-- 轮询信息 -->
        <div class="rotation-info" v-if="rotationBatch">
          <span class="rotation-label">当前批次:</span>
          <span class="rotation-value">第 {{ rotationBatch }}/10 批</span>
          <span class="rotation-timer">⏱️ 45秒轮换</span>
        </div>

        <!-- 最近成交 -->
        <div class="recent-tick" v-if="lastTick">
          <span class="tick-label">最新成交:</span>
          <span class="tick-stock">{{ lastTick.name }} ({{ lastTick.code }})</span>
          <span class="tick-price">{{ lastTick.price }}</span>
          <span class="tick-volume">{{ lastTick.volume }}手</span>
        </div>
      </div>

      <!-- 状态信息 -->
      <div class="detail-item">
        <span class="detail-label">AllTick WebSocket:</span>
        <span class="detail-value" :class="alltickConnected ? 'good' : 'warn'">
          {{ alltickConnected ? '✅ 已连接' : '❌ 已断开' }}
        </span>
      </div>
      <div class="detail-item">
        <span class="detail-label">HTTP轮询:</span>
        <span class="detail-value good">✅ 运行中</span>
      </div>
      <div class="detail-item">
        <span class="detail-label">总订阅:</span>
        <span class="detail-value">{{ httpSubscribedCount }}只</span>
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
      <button class="refresh-btn" @click="manualRefresh">🔄 手动刷新</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { dataLayer } from '@/services/DataLayer'
import { EventManager } from '@/utils/eventManager'
import { AppEvents } from '@/types'
import { webSocketService } from '@/services/websocket'

const props = defineProps<{
  stockCode?: string
}>()

const showDetails = ref(false)
let clickOutsideHandler: ((e: MouseEvent) => void) | null = null
let updateTimer: ReturnType<typeof setInterval> | null = null

const unsubscribeFns: (() => void)[] = []

// ========== AllTick 相关状态 ==========
const alltickConnected = ref(false)
const alltickSubscribedCodes = ref<string[]>([])
const rotationBatch = ref<number | null>(null)
const lastTick = ref<any>(null)

// ========== 计算属性 ==========
const alltickSubscribedStocks = computed(() => {
  const stocks = dataLayer.getStocks()
  return alltickSubscribedCodes.value
    .map((code) => {
      const stock = stocks.find((s) => s.code === code)
      return stock
        ? {
          code: stock.code,
          name: stock.name || code,
          price: stock.price || 0,
          change: stock.change || 0,
          lastTick: (stock as any).lastTick,
        }
        : null
    })
    .filter(Boolean)
})

const httpSubscribedCount = computed(() => {
  try {
    return webSocketService.getStatus().subscribedCount || 0
  } catch {
    return 0
  }
})

const stockCount = computed(() => {
  return dataLayer.getStocks().length || 0
})

const lastUpdateTime = computed(() => {
  const stocks = dataLayer.getStocks()
  const latestUpdate = stocks.reduce((latest, s) => {
    return Math.max(latest, s.updatedAt || 0)
  }, 0)
  return latestUpdate ? new Date(latestUpdate).toLocaleTimeString() : '未知'
})

const dataStatus = computed(() => {
  const stocks = dataLayer.getStocks()
  if (stocks.length === 0) return 'empty'

  const latestStock = stocks[0]
  if (!latestStock.updatedAt) return 'unknown'

  const ageMinutes = (Date.now() - latestStock.updatedAt) / 60000

  if (ageMinutes < 1) return 'fresh'
  if (ageMinutes < 5) return 'normal'
  if (ageMinutes < 15) return 'stale'
  return 'expired'
})

const dataStatusText = computed(() => {
  const texts = {
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
  const classes = {
    fresh: 'data-fresh',
    normal: 'data-normal',
    stale: 'data-stale',
    expired: 'data-expired',
    empty: 'data-empty',
    unknown: 'data-unknown',
  }
  return classes[dataStatus.value] || ''
})

const connectionClass = computed(() => {
  return alltickConnected.value ? 'status-connected' : 'status-http'
})

const combinedIcon = computed(() => {
  const baseIcon = alltickConnected.value ? '🟢' : '🟡'
  if (dataStatus.value === 'stale') return '🟠'
  if (dataStatus.value === 'expired') return '🔴'
  return baseIcon
})

// ========== 事件处理 ==========
const updateAllTickStatus = () => {
  try {
    alltickConnected.value = (webSocketService as any).isAllTickConnected?.() || false
  } catch (error) {
    console.error('更新AllTick状态失败:', error)
  }
}

const updateSubscriptionList = (codes: string[]) => {
  alltickSubscribedCodes.value = codes
  // 获取当前轮询批次
  rotationBatch.value = (((webSocketService as any).currentBatchIndex ?? 0) % 10) + 1
}

const handleTick = (data: any) => {
  lastTick.value = {
    code: data.code,
    name: data.name,
    price: data.price,
    volume: data.volume,
    time: new Date().toLocaleTimeString(),
  }
  // 刷新订阅列表（更新成交标记）
  updateSubscriptionList(alltickSubscribedCodes.value)
}

// ✅ 修复：提取为具名函数
const handleDataUpdated = () => {
  updateSubscriptionList((webSocketService as any).getAllTickSubscribedStocks?.() || [])
}

const manualRefresh = async () => {
  try {
    EventManager.emit('refresh:manual')
    EventManager.emit(AppEvents.UI.TOAST, {
      message: '🔄 正在刷新数据...',
      duration: 1000,
      type: 'info',
    })
    showDetails.value = false
  } catch (error) {
    console.error('手动刷新失败:', error)
  }
}

// ========== 生命周期 ==========
onMounted(() => {
  clickOutsideHandler = (e: MouseEvent) => {
    const target = e.target as HTMLElement
    if (!target.closest('.data-freshness')) {
      showDetails.value = false
    }
  }
  document.addEventListener('click', clickOutsideHandler)

  // 初始更新
  updateAllTickStatus()
  updateSubscriptionList((webSocketService as any).getAllTickSubscribedStocks?.() || [])

  // 定时更新UI
  updateTimer = setInterval(() => {
    updateAllTickStatus()
    updateSubscriptionList((webSocketService as any).getAllTickSubscribedStocks?.() || [])
  }, 2000)

  // ✅ 只保存一次监听，并统一处理
  const unsub1 = EventManager.on(AppEvents.WEBSOCKET.STATUS_CHANGED, updateAllTickStatus)
  unsubscribeFns.push(unsub1)

  const unsub2 = EventManager.on(AppEvents.WEBSOCKET.SUBSCRIPTION_UPDATED, updateSubscriptionList)
  unsubscribeFns.push(unsub2)

  const unsub3 = EventManager.on(AppEvents.WEBSOCKET.TICK, handleTick)
  unsubscribeFns.push(unsub3)

  const unsub4 = EventManager.on(AppEvents.DATA.UPDATED, handleDataUpdated)
  unsubscribeFns.push(unsub4)
})
onUnmounted(() => {
  if (clickOutsideHandler) {
    document.removeEventListener('click', clickOutsideHandler)
  }

  if (updateTimer) {
    clearInterval(updateTimer)
    updateTimer = null
  }

  // ✅ 统一清理所有事件监听
  unsubscribeFns.forEach((fn) => {
    try {
      fn()
    } catch (e) {
      console.warn('[DataFreshness] 清理订阅失败:', e)
    }
  })
  unsubscribeFns.length = 0
})
</script>

<style scoped>
/* 原有样式保持不变 */
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

/* 连接状态样式 */
.status-connected {
  color: #2ecc71;
  border-color: #2ecc71;
  background: rgba(46, 204, 113, 0.1);
}

.status-http {
  color: #f1c40f;
  border-color: #f1c40f;
  background: rgba(241, 196, 15, 0.1);
}

/* 数据新鲜度样式 */
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

.data-empty {
  color: #95a5a6;
  border-color: #95a5a6;
}

.data-unknown {
  color: #95a5a6;
  border-color: #95a5a6;
}

/* 详细面板 */
.freshness-details {
  position: absolute;
  top: 100%;
  right: 0;
  margin-top: 8px;
  background: var(--bg-panel);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 16px;
  min-width: 280px;
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
  box-shadow: 0 4px 8px rgba(255, 165, 2, 0.3);
}

/* 订阅股票列表样式 */
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
  background: rgba(46, 204, 113, 0.2);
  border-radius: 12px;
  color: #2ecc71;
}

.section-badge.full {
  background: rgba(46, 204, 113, 0.3);
  font-weight: 600;
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
  padding: 8px 10px;
  background: var(--bg-secondary);
  border-radius: 6px;
  font-size: 12px;
  position: relative;
}

.stock-item.placeholder {
  opacity: 0.5;
  background: var(--bg-primary);
}

.stock-info {
  display: flex;
  flex-direction: column;
  min-width: 100px;
}

.stock-name {
  font-weight: 600;
  color: var(--text-primary);
}

.stock-code {
  font-size: 10px;
  color: var(--text-secondary);
  font-family: monospace;
}

.stock-price {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  min-width: 80px;
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

.tick-badge {
  position: absolute;
  right: 4px;
  top: 4px;
  font-size: 10px;
  animation: pulse 1s infinite;
}

.rotation-info {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 8px;
  background: var(--bg-secondary);
  border-radius: 4px;
  font-size: 11px;
  margin-top: 8px;
}

.rotation-label {
  color: var(--text-secondary);
}

.rotation-value {
  font-weight: 600;
  color: var(--color-highlight);
}

.rotation-timer {
  color: #3498db;
  font-size: 10px;
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

@keyframes pulse {

  0%,
  100% {
    opacity: 1;
  }

  50% {
    opacity: 0.5;
  }
}
</style>
