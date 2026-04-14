<!-- src/components/big-order/BigOrderTable.vue -->
<template>
  <div class="big-order-table">
    <!-- 工具栏 -->
    <div class="toolbar">
      <div class="left">
        <div class="stock-info">
          <span class="stock-name">{{ stockName }}</span>
          <span class="stock-code">{{ stockCode }}</span>
        </div>
        <div class="filters">
          <select v-model="amountFilter" class="filter-select">
            <option :value="0">全部金额</option>
            <option :value="30">≥30万</option>
            <option :value="50">≥50万</option>
            <option :value="100">≥100万</option>
            <option :value="300">≥300万</option>
            <option :value="500">≥500万</option>
            <option :value="800">≥800万</option>
            <option :value="1000">≥1000万</option>
            <option :value="2000">≥2000万</option>
          </select>

          <select v-model="markerFilter" class="filter-select">
            <option value="">全部标记</option>
            <option value="点火">点火</option>
            <option value="砸盘">砸盘</option>
            <option value="买活跃">买活跃</option>
            <option value="承接好">承接好</option>
          </select>
        </div>
      </div>

      <div class="right">
        <div v-if="loading && progress > 0" class="progress-indicator">
          <div class="progress-bar" :style="{ width: progress + '%' }"></div>
          <span class="progress-text">{{ progress }}%</span>
        </div>
        <div v-if="!loading && dataLoaded" class="cache-badge" title="数据来自缓存">
          ⚡ 缓存
        </div>
        <button class="btn-icon" @click="handleRefresh" :disabled="loading">
          <span class="icon" :class="{ spinning: loading }">↻</span>
        </button>
        <button class="btn-icon" @click="$emit('show-analysis')">
          <span class="icon">📊</span>
        </button>
      </div>
    </div>

    <!-- 统计卡片 -->
    <div class="stats-cards">
      <div class="stat-card" @click="setMarkerFilter('')">
        <div class="stat-label">总笔数</div>
        <div v-if="loading && !stats" class="stat-value skeleton">---</div>
        <div v-else class="stat-value">{{ stats?.totalCount || 0 }}</div>
      </div>
      <div class="stat-card" @click="setMarkerFilter('')">
        <div class="stat-label">买入</div>
        <div v-if="loading && !stats" class="stat-value skeleton">---</div>
        <div v-else class="stat-value" :style="{ color: colorService.colors.buy }">
          {{ formatAmount(stats?.buyAmount || 0) }}
        </div>
      </div>
      <div class="stat-card" @click="setMarkerFilter('')">
        <div class="stat-label">卖出</div>
        <div v-if="loading && !stats" class="stat-value skeleton">---</div>
        <div v-else class="stat-value" :style="{ color: colorService.colors.sell }">
          {{ formatAmount(stats?.sellAmount || 0) }}
        </div>
      </div>
      <div class="stat-card" @click="setMarkerFilter('')">
        <div class="stat-label">净买</div>
        <div v-if="loading && !stats" class="stat-value skeleton">---</div>
        <div v-else class="stat-value" :style="{
          color: colorService.getStatisticsColor('netBuy', stats?.netBuy)
        }">
          {{ formatAmount(stats?.netBuy || 0) }}
        </div>
      </div>
      <div class="stat-card" @click="setMarkerFilter('点火')">
        <div class="stat-label">点火</div>
        <div v-if="loading && !stats" class="stat-value skeleton">---</div>
        <div v-else class="stat-value" :style="{ color: colorService.colors.ignite }">
          {{ stats?.igniteCount || 0 }}
        </div>
      </div>
      <div class="stat-card" @click="setMarkerFilter('砸盘')">
        <div class="stat-label">砸盘</div>
        <div v-if="loading && !stats" class="stat-value skeleton">---</div>
        <div v-else class="stat-value" :style="{ color: colorService.colors.smash }">
          {{ stats?.smashCount || 0 }}
        </div>
      </div>
      <div class="stat-card" @click="setMarkerFilter('买活跃')">
        <div class="stat-label">买活跃</div>
        <div v-if="loading && !stats" class="stat-value skeleton">---</div>
        <div v-else class="stat-value" :style="{ color: colorService.colors.buyActive }">
          {{ stats?.buyActiveCount || 0 }}
        </div>
      </div>
      <div class="stat-card" @click="setMarkerFilter('承接好')">
        <div class="stat-label">承接好</div>
        <div v-if="loading && !stats" class="stat-value skeleton">---</div>
        <div v-else class="stat-value" :style="{ color: colorService.colors.sellActive }">
          {{ stats?.sellActiveCount || 0 }}
        </div>
      </div>
    </div>

    <!-- 表格容器 -->
    <div class="table-container" ref="tableContainer" @scroll="handleScroll">
      <!-- 加载状态 -->
      <div v-if="loading && displayOrders.length === 0" class="empty-state">
        <div class="loading-animation">
          <div class="loading-spinner-large"></div>
          <div class="loading-text">
            <div>正在加载数据...</div>
            <div class="loading-progress">{{ progress }}%</div>
          </div>
        </div>
      </div>

      <!-- 空数据状态 -->
      <div v-else-if="!loading && displayOrders.length === 0" class="empty-state">
        <div class="empty-content">
          <div class="empty-icon">📊</div>
          <div class="empty-title">暂无大单数据</div>
          <div class="empty-desc">当前没有符合条件的大单记录</div>
          <div class="empty-suggestions">
            <span class="suggestion-tag">调整筛选条件</span>
            <span class="suggestion-tag">切换其他股票</span>
            <span class="suggestion-tag">点击刷新</span>
          </div>
        </div>
      </div>

      <!-- 有数据时显示表格 -->
      <template v-else>
        <div class="virtual-scroll" :style="{ height: totalHeight + 'px' }">
          <table>
            <thead>
              <tr>
                <th>时间</th>
                <th>金额</th>
                <th>手数</th>
                <th>均价</th>
                <th>买卖</th>
                <th>资金</th>
                <th>买盘</th>
              </tr>
            </thead>
            <tbody>
              <template v-for="chunk in renderedChunks" :key="chunk.start">
                <tr v-for="order in chunk.orders" :key="order.id" :style="colorService.getOrderStyle(order)">
                  <td>{{ order.timeStr }}</td>
                  <td>{{ order.amountStr }}</td>
                  <td>{{ order.volume.toFixed(0) }}</td>
                  <td>{{ order.price.toFixed(2) }}</td>
                  <td>{{ order.typeName }}</td>
                  <td>{{ order.fundMarker }}</td>
                  <td>{{ order.buyMarker }}</td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>

        <!-- 加载更多触发器（隐藏的） -->
        <div v-if="hasMore && !loading" class="load-more-trigger-observer" ref="loadMoreTrigger"></div>

        <!-- 加载更多动画 -->
        <div v-if="loadingMore" class="load-more-animation">
          <div class="loading-more">
            <div class="loading-spinner small"></div>
            <span>加载更多数据...</span>
          </div>
        </div>
      </template>
    </div>

    <!-- 底部信息条（非分页控件） -->
    <div class="footer-info" v-if="totalCount > 0">
      <span class="total-text">共 {{ totalCount }} 条记录</span>
      <span class="loaded-text" v-if="loadedCount < totalCount">
        已加载 {{ loadedCount }} 条
      </span>
      <span class="loaded-text" v-else>
        已全部加载
      </span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useBigOrderStore } from '@/stores/bigOrder'
import { BigOrderColorService } from '@/services/big-order/BigOrderColorService'

const props = defineProps<{
  stockCode: string
  stockName?: string
}>()

const emit = defineEmits<{
  (e: 'refresh'): void
  (e: 'show-analysis'): void
}>()

const store = useBigOrderStore()
const colorService = BigOrderColorService.getInstance()

// ==================== 筛选条件 ====================
const amountFilter = computed({
  get: () => store.currentFilter.value?.minAmount || 0,
  set: (value) => {
    store.setFilter({ minAmount: value || undefined })
  }
})

const markerFilter = computed({
  get: () => store.currentFilter.value?.fundMarker || '',
  set: (value) => {
    store.setFilter({ fundMarker: value || undefined })
  }
})

// ==================== 响应式数据 ====================
const displayOrders = computed(() => store.filteredOrders || [])
const stats = computed(() => store.filteredStatistics)
const loading = computed(() => store.loading)
const hasMore = computed(() => store.hasMore)
const loadedCount = computed(() => store.loadedCount)
const totalCount = computed(() => store.totalCount)

const progress = computed(() => {
  const service = (window as any).bigOrderService
  return service?.progress?.value || 0
})

// ==================== 虚拟滚动配置 ====================
const ROW_HEIGHT = 35
const BUFFER_SIZE = 30
const CHUNK_SIZE = 50

const tableContainer = ref<HTMLElement>()
const scrollTop = ref(0)
const containerHeight = ref(0)
const renderedChunks = ref<Array<{ start: number; orders: any[] }>>([])
const dataLoaded = ref(false)
const loadingMore = ref(false)

// ==================== 计算属性 ====================
const totalHeight = computed(() => displayOrders.value.length * ROW_HEIGHT)

const visibleRange = computed(() => {
  if (!displayOrders.value.length) return { start: 0, end: 0 }

  const start = Math.max(0, Math.floor(scrollTop.value / ROW_HEIGHT) - BUFFER_SIZE)
  const end = Math.min(
    displayOrders.value.length,
    Math.ceil((scrollTop.value + containerHeight.value) / ROW_HEIGHT) + BUFFER_SIZE
  )

  return { start, end }
})

// ==================== 分块渲染 ====================
const updateRenderedChunks = () => {
  if (!displayOrders.value.length) {
    renderedChunks.value = []
    return
  }

  const { start, end } = visibleRange.value
  const chunks: Array<{ start: number; orders: any[] }> = []

  const chunkStart = Math.floor(start / CHUNK_SIZE) * CHUNK_SIZE
  const chunkEnd = Math.ceil(end / CHUNK_SIZE) * CHUNK_SIZE

  for (let i = chunkStart; i < chunkEnd && i < displayOrders.value.length; i += CHUNK_SIZE) {
    const chunkOrders = displayOrders.value.slice(i, Math.min(i + CHUNK_SIZE, displayOrders.value.length))
    if (chunkOrders.length > 0) {
      chunks.push({ start: i, orders: chunkOrders })
    }
  }

  renderedChunks.value = chunks
}

// ==================== 滚动处理 ====================
let scrollRAF: number
const handleScroll = (e: Event) => {
  if (scrollRAF) cancelAnimationFrame(scrollRAF)

  scrollRAF = requestAnimationFrame(() => {
    const target = e.target as HTMLElement
    scrollTop.value = target.scrollTop
    containerHeight.value = target.clientHeight
  })
}

// ==================== 加载更多 ====================
const loadMore = async () => {
  if (!hasMore.value || loadingMore.value || loading.value) return

  loadingMore.value = true
  try {
    await store.loadMore()
    await nextTick()
    updateRenderedChunks()
  } catch (error) {
    console.error('[BigOrderTable] 加载更多失败:', error)
  } finally {
    loadingMore.value = false
  }
}

// ==================== 工具函数 ====================
const formatAmount = (amount: number) => {
  if (amount >= 100000000) return `${(amount / 100000000).toFixed(1)}亿`
  return `${Math.round(amount / 10000)}万`
}

const setMarkerFilter = (marker: string) => {
  if (markerFilter.value === marker) {
    store.setFilter({ fundMarker: undefined })
  } else {
    store.setFilter({ fundMarker: marker })
  }
}

const handleRefresh = async () => {
  if (loading.value) return

  try {
    // 可以添加一个短暂的刷新动画
    const refreshButton = document.querySelector('.btn-icon .icon')
    refreshButton?.classList.add('spinning')

    await store.refresh(100)

    // 刷新完成后更新虚拟滚动
    await nextTick()
    updateRenderedChunks()

    // 可以显示一个短暂的提示（通过console或者添加一个toast）
    console.log('[BigOrderTable] 刷新完成，数据已更新')

  } catch (error) {
    console.error('[BigOrderTable] 刷新失败:', error)
  } finally {
    // 移除旋转动画
    const refreshButton = document.querySelector('.btn-icon .icon')
    refreshButton?.classList.remove('spinning')
  }
}

// 添加一个监听，当数据更新时自动更新虚拟滚动
watch(() => store.filteredOrders, () => {
  updateRenderedChunks()
}, { deep: false })
// ==================== 数据加载 ====================
const loadData = async () => {
  if (!props.stockCode) return

  try {
    await store.loadStockData(props.stockCode, props.stockName)
    dataLoaded.value = true

    await nextTick()
    updateRenderedChunks()

    if (tableContainer.value) {
      tableContainer.value.scrollTop = 0
    }
  } catch (error) {
    console.error('[BigOrderTable] 加载数据失败:', error)
  }
}

// ==================== 监听器 ====================
watch(() => props.stockCode, async (newCode, oldCode) => {
  if (newCode && newCode !== oldCode) {
    dataLoaded.value = false
    scrollTop.value = 0
    renderedChunks.value = []
    await loadData()
  }
})

watch([visibleRange, displayOrders], () => {
  updateRenderedChunks()
}, { deep: false, immediate: true })

// ==================== 生命周期 ====================
let observer: IntersectionObserver
const loadMoreTrigger = ref<HTMLElement>()
const resizeObserver = ref<ResizeObserver | null>(null)

onMounted(async () => {
  await loadData()

  // 设置 Intersection Observer 触发加载更多
  observer = new IntersectionObserver(
    (entries) => {
      if (entries[0].isIntersecting && hasMore.value && !loadingMore.value && !loading.value) {
        loadMore()
      }
    },
    { rootMargin: '200px' }
  )

  if (tableContainer.value) {
    containerHeight.value = tableContainer.value.clientHeight

    resizeObserver.value = new ResizeObserver((entries) => {
      for (const entry of entries) {
        containerHeight.value = entry.contentRect.height
        updateRenderedChunks()
      }
    })
    resizeObserver.value.observe(tableContainer.value)
  }

  // 延迟观察加载触发器
  setTimeout(() => {
    if (loadMoreTrigger.value) {
      observer.observe(loadMoreTrigger.value)
    }
  }, 1000)
})

onUnmounted(() => {
  if (resizeObserver.value) {
    resizeObserver.value.disconnect()
  }
  if (observer) {
    observer.disconnect()
  }
  if (scrollRAF) {
    cancelAnimationFrame(scrollRAF)
  }
})
</script>

<style scoped>
/* ========== 基础布局 ========== */
.big-order-table {
  display: flex;
  flex-direction: column;
  height: 100%;
  background-color: var(--bg-primary);
  color: var(--text-primary);
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
}

/* ========== 工具栏 ========== */
.toolbar {
  padding: 8px 12px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid var(--border-light);
  background-color: var(--bg-panel);
  flex-shrink: 0;
}

.left {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}

.stock-info {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.stock-name {
  font-size: 15px;
  font-weight: 600;
  color: var(--color-highlight);
}

.stock-code {
  font-size: 12px;
  color: var(--text-tertiary);
  background-color: var(--bg-hover);
  padding: 2px 6px;
  border-radius: 4px;
}

.filters {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.filter-select {
  padding: 4px 8px;
  height: 28px;
  background-color: var(--bg-secondary);
  color: var(--text-primary);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  font-size: 12px;
  cursor: pointer;
  min-width: 80px;
}

.filter-select:hover {
  border-color: var(--color-highlight);
}

.right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.btn-icon {
  width: 28px;
  height: 28px;
  border: 1px solid transparent;
  background: transparent;
  border-radius: 4px;
  color: var(--text-secondary);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  transition: all 0.2s;
}

.btn-icon:hover {
  background-color: var(--bg-hover);
  border-color: var(--border-color);
  color: var(--text-primary);
}

.icon.spinning {
  animation: spin 1s linear infinite;
}

/* ========== 统计卡片 ========== */
.stats-cards {
  display: grid;
  grid-template-columns: repeat(8, 1fr);
  gap: 2px;
  padding: 6px 12px;
  background-color: var(--bg-secondary);
  border-bottom: 1px solid var(--border-light);
  flex-shrink: 0;
}

.stat-card {
  padding: 4px 2px;
  background-color: transparent;
  text-align: center;
  cursor: pointer;
  border-radius: 2px;
  transition: background-color 0.2s;
}

.stat-card:hover {
  background-color: var(--bg-hover);
}

.stat-label {
  font-size: 10px;
  color: var(--text-tertiary);
  margin-bottom: 1px;
  white-space: nowrap;
}

.stat-value {
  font-size: 12px;
  font-weight: 500;
  line-height: 1.3;
}

/* ========== 表格容器 ========== */
.table-container {
  flex: 1;
  min-height: 0;
  overflow: auto;
  position: relative;
  background-color: var(--bg-primary);
}

/* ========== 空状态 ========== */
.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 400px;
  height: 100%;
  width: 100%;
}

.loading-animation {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
}

.loading-spinner-large {
  width: 48px;
  height: 48px;
  border: 3px solid var(--border-light);
  border-top-color: var(--color-highlight);
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

.loading-text {
  text-align: center;
  color: var(--text-secondary);
  font-size: 14px;
}

.loading-progress {
  font-size: 24px;
  font-weight: 600;
  color: var(--color-highlight);
  margin-top: 4px;
}

.empty-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 48px 24px;
  text-align: center;
  max-width: 400px;
  margin: 0 auto;
}

.empty-icon {
  font-size: 64px;
  margin-bottom: 16px;
  opacity: 0.5;
  animation: float 3s ease-in-out infinite;
}

.empty-title {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 8px;
}

.empty-desc {
  font-size: 14px;
  color: var(--text-tertiary);
  margin-bottom: 24px;
}

.empty-suggestions {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  justify-content: center;
}

.suggestion-tag {
  padding: 6px 12px;
  background-color: var(--bg-hover);
  border: 1px solid var(--border-light);
  border-radius: 20px;
  font-size: 12px;
  color: var(--text-secondary);
  cursor: default;
  transition: all 0.2s;
}

.suggestion-tag:hover {
  background-color: var(--bg-panel);
  border-color: var(--color-highlight);
  color: var(--color-highlight);
}

/* ========== 虚拟滚动表格 ========== */
.virtual-scroll {
  position: relative;
  width: 100%;
}

table {
  width: 100%;
  border-collapse: collapse;
  font-size: 11px;
  table-layout: fixed;
}

th {
  position: sticky;
  top: 0;
  background-color: var(--bg-secondary);
  color: var(--text-secondary);
  font-weight: 500;
  padding: 8px 2px;
  text-align: center;
  z-index: 10;
  font-size: 11px;
  white-space: nowrap;
  border-bottom: 1px solid var(--border-light);
}

td {
  padding: 8px 2px;
  text-align: center;
  border-bottom: 1px solid var(--border-light);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  height: 35px;
  font-size: 11px;
}

tbody tr:hover {
  background-color: var(--bg-hover);
}

/* ========== 加载更多触发器 ========== */
.load-more-trigger-observer {
  height: 1px;
  visibility: hidden;
}

.load-more-animation {
  position: absolute;
  bottom: 16px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 20;
}

.loading-more {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  background-color: var(--bg-panel);
  border: 1px solid var(--border-light);
  border-radius: 20px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  font-size: 12px;
  color: var(--text-secondary);
}

.loading-spinner {
  display: inline-block;
  width: 20px;
  height: 20px;
  border: 2px solid var(--border-light);
  border-top-color: var(--color-highlight);
  border-radius: 50%;
  animation: spin 1s linear infinite;
  margin-right: 8px;
  vertical-align: middle;
}

.loading-spinner.small {
  width: 16px;
  height: 16px;
  border-width: 2px;
  margin-right: 4px;
}

/* ========== 进度指示器 ========== */
.progress-indicator {
  position: relative;
  width: 50px;
  height: 18px;
  background-color: var(--bg-hover);
  border-radius: 9px;
  overflow: hidden;
}

.progress-bar {
  height: 100%;
  background-color: var(--color-highlight);
  transition: width 0.2s;
}

.progress-text {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  font-size: 9px;
  color: white;
  font-weight: 500;
}

.cache-badge {
  padding: 2px 6px;
  background-color: var(--color-highlight);
  color: white;
  border-radius: 10px;
  font-size: 10px;
  display: flex;
  align-items: center;
  gap: 2px;
}

/* ========== 底部信息条 ========== */
.footer-info {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
  padding: 8px 12px;
  border-top: 1px solid var(--border-light);
  background-color: var(--bg-panel);
  font-size: 12px;
  color: var(--text-tertiary);
  flex-shrink: 0;
}

.loaded-text {
  color: var(--color-highlight);
  font-weight: 500;
}

/* ========== 动画 ========== */
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

@keyframes float {

  0%,
  100% {
    transform: translateY(0);
  }

  50% {
    transform: translateY(-10px);
  }
}

/* ========== 响应式 ========== */
@media (max-width: 1200px) {
  .stats-cards {
    grid-template-columns: repeat(4, 1fr);
  }
}

@media (max-width: 768px) {
  .toolbar {
    flex-direction: column;
    align-items: stretch;
    gap: 6px;
    height: auto;
  }

  .left {
    flex-direction: column;
    align-items: flex-start;
  }

  .filters {
    width: 100%;
  }

  .filter-select {
    flex: 1;
  }

  .stats-cards {
    grid-template-columns: repeat(4, 1fr);
  }

  .empty-suggestions {
    flex-direction: column;
    width: 100%;
  }

  .suggestion-tag {
    width: 100%;
    text-align: center;
  }
}

@media (max-width: 480px) {
  .stats-cards {
    grid-template-columns: repeat(2, 1fr);
  }

  .empty-icon {
    font-size: 48px;
  }

  .empty-title {
    font-size: 16px;
  }
}
</style>
