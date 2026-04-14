<!-- src/components/panels/BigOrderPanel.vue -->
<template>
  <Teleport to="body">
    <div v-if="visible" class="big-order-panel" :class="themeStore.themeClass">
      <!-- 面板头部 -->
      <div class="panel-header" ref="headerRef">
        <div class="header-left">
          <h3>
            <span class="header-icon">📊</span>
            大单监控
          </h3>
          <div class="stock-badge" v-if="stockCode">
            {{ stockName }} ({{ stockCode }})
          </div>
        </div>
        <div class="header-right">
          <!-- 语音播报开关 -->
          <div class="voice-toggle" :class="{ active: voiceEnabled }" @click="toggleVoice">
            <span class="voice-icon">🔊</span>
            <span class="voice-text">语音</span>
          </div>

          <!-- 密集大单预警 -->
          <div v-if="denseAlerts.length" class="alert-badge" @click="showAlerts = !showAlerts">
            <span class="alert-icon">⚠️</span>
            <span class="alert-count">{{ denseAlerts.length }}</span>
          </div>
          <button class="btn-close" @click="close">×</button>
        </div>
      </div>

      <!-- 预警列表 -->
      <div v-if="showAlerts" class="alert-list">
        <div class="alert-header">
          <span>密集大单预警</span>
          <button class="btn-small" @click="showAlerts = false">关闭</button>
        </div>
        <div class="alert-items">
          <div v-for="alert in denseAlerts" :key="alert.timestamp" class="alert-item">
            <span class="alert-time">{{ formatTime(alert.timestamp) }}</span>
            <span class="alert-desc">
              {{ alert.count }}笔大单 ({{ formatAmount(alert.totalAmount) }})
            </span>
            <span class="alert-avg">均{{ formatAmount(alert.avgAmount) }}</span>
          </div>
          <div v-if="!denseAlerts.length" class="alert-empty">
            暂无密集大单预警
          </div>
        </div>
      </div>

      <!-- 面板内容 -->
      <div class="panel-content">
        <!-- 股票选择 -->
        <div class="stock-selector">
          <input type="text" v-model="inputCode" placeholder="输入股票代码" @keyup.enter="handleStockChange">
          <button @click="handleStockChange">查看</button>
        </div>

        <!-- 筛选条件区域 -->
        <div class="filters-container">
          <!-- 第一行：常用筛选 -->
          <div class="filters-row">
            <div class="filter-item">
              <span class="filter-label">金额</span>
              <select v-model="amountFilter" class="filter-select">
                <option :value="0">全部</option>
                <option :value="30">≥30万</option>
                <option :value="50">≥50万</option>
                <option :value="100">≥100万</option>
                <option :value="300">≥300万</option>
                <option :value="500">≥500万</option>
                <option :value="800">≥800万</option>
                <option :value="1000">≥1000万</option>
                <option :value="2000">≥2000万</option>
              </select>
            </div>

            <div class="filter-item">
              <span class="filter-label">手数</span>
              <select v-model="volumeFilter" class="filter-select">
                <option :value="0">全部</option>
                <option :value="100">≥100手</option>
                <option :value="500">≥500手</option>
                <option :value="1000">≥1000手</option>
                <option :value="5000">≥5000手</option>
                <option :value="10000">≥1万手</option>
              </select>
            </div>

            <div class="filter-item">
              <span class="filter-label">类型</span>
              <select v-model="typeFilter" class="filter-select">
                <option value="">全部</option>
                <option value="2,3">买入</option>
                <option value="1,4">卖出</option>
                <option value="2">主动买</option>
                <option value="1">被动卖</option>
                <option value="3">被动买</option>
                <option value="4">主动卖</option>
              </select>
            </div>

            <div class="filter-item">
              <span class="filter-label">资金</span>
              <select v-model="fundMarkerFilter" class="filter-select">
                <option value="">全部</option>
                <option value="点火">点火</option>
                <option value="砸盘">砸盘</option>
              </select>
            </div>

            <div class="filter-item">
              <span class="filter-label">买盘</span>
              <select v-model="buyMarkerFilter" class="filter-select">
                <option value="">全部</option>
                <option value="买活跃">买活跃</option>
                <option value="承接好">承接好</option>
              </select>
            </div>

            <div class="filter-item">
              <span class="filter-label">时段</span>
              <select v-model="timeRangeFilter" class="filter-select">
                <option value="">全部</option>
                <option value="0930-1030">09:30-10:30</option> <!-- ✅ 格式正确 -->
                <option value="1030-1130">10:30-11:30</option> <!-- ✅ 格式正确 -->
                <option value="1300-1400">13:00-14:00</option> <!-- ✅ 格式正确 -->
                <option value="1400-1500">14:00-15:00</option> <!-- ✅ 格式正确 -->
              </select>
            </div>

            <button class="reset-filter-btn" @click="resetAllFilters" title="重置所有筛选">
              <span class="reset-icon">↺</span>
            </button>
          </div>

          <!-- 第二行：快速筛选标签 -->
          <button class="quick-tag" :class="{ active: fundMarkerFilter === '点火' }"
            @click="toggleFilter('fundMarker', '点火')">
            🔥 点火
          </button>
          <button class="quick-tag" :class="{ active: fundMarkerFilter === '砸盘' }"
            @click="toggleFilter('fundMarker', '砸盘')">
            💥 砸盘
          </button>
          <button class="quick-tag" :class="{ active: buyMarkerFilter === '买活跃' }"
            @click="toggleFilter('buyMarker', '买活跃')">
            📈 买活跃
          </button>
          <button class="quick-tag" :class="{ active: buyMarkerFilter === '承接好' }"
            @click="toggleFilter('buyMarker', '承接好')">
            📉 承接好
          </button>

          <!-- 大单表格 -->
          <BigOrderTable v-if="stockCode" :stock-code="stockCode" :stock-name="stockName" @refresh="handleTableRefresh"
            @show-analysis="showAnalysis = true" />
          <div v-else class="empty-state">
            <div class="empty-icon">📊</div>
            <div class="empty-text">请输入股票代码查看大单数据</div>
          </div>
        </div>

        <!-- 分析面板 -->
        <BigOrderAnalysis v-if="showAnalysis" v-model:visible="showAnalysis" :stock-code="stockCode"
          :stock-name="stockName" :statistics="statistics" :periods="periods" />
      </div>
    </div>
  </Teleport>
</template>


<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useThemeStore } from '@/stores/theme'
import { useBigOrderStore } from '@/stores/bigOrder'
import { EventManager } from '@/utils/eventManager'
import { AppEvents } from '@/types'
import { voiceService } from '@/services/VoiceService'
import BigOrderTable from '@/components/big-order/BigOrderTable.vue'
import BigOrderAnalysis from '@/components/big-order/BigOrderAnalysis.vue'

const props = defineProps<{
  visible: boolean
  stockCode?: string
  stockName?: string
  triggerRect?: DOMRect
}>()

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'close'): void
}>()

const themeStore = useThemeStore()
const store = useBigOrderStore()

const inputCode = ref(props.stockCode || '')
const showAlerts = ref(false)
const showAnalysis = ref(false)
const headerRef = ref<HTMLElement>()
const dataLoaded = ref(false)
const voiceEnabled = ref(false) // 语音播报开关

// 筛选条件状态 - 这些应该与 store 同步
const amountFilter = computed({
  get: () => store.currentFilter.value?.minAmount || 0,
  set: (value) => store.setFilter({ minAmount: value || undefined })
})

const volumeFilter = computed({
  get: () => store.currentFilter.value?.minVolume || 0,
  set: (value) => store.setFilter({ minVolume: value || undefined })
})

const typeFilter = computed({
  get: () => {
    const types = store.currentFilter.value?.types
    return types?.length ? types.join(',') : ''
  },
  set: (value) => {
    if (value) {
      store.setFilter({ types: value.split(',').map(Number) as (1 | 2 | 3 | 4)[] })
    } else {
      store.setFilter({ types: undefined })
    }
  }
})

// 资金标记筛选 - 用于快速筛选按钮
const fundMarkerFilter = computed({
  get: () => store.currentFilter.value?.fundMarker || '',
  set: (value) => {
    // 设置资金标记时，清除买盘标记
    store.setFilter({
      fundMarker: value || undefined,
      buyMarker: undefined  // 互斥：资金标记和买盘标记不能共存
    })
  }
})


// 买盘标记筛选 - 用于快速筛选按钮
const buyMarkerFilter = computed({
  get: () => store.currentFilter.value?.buyMarker || '',
  set: (value) => {
    // 设置买盘标记时，清除资金标记
    store.setFilter({
      buyMarker: value || undefined,
      fundMarker: undefined  // 互斥：资金标记和买盘标记不能共存
    })
  }
})

// 时段筛选 - 本地状态，watch 自动触发 store 更新
const timeRangeFilter = ref('')

watch(timeRangeFilter, (newVal) => {
  console.log('[BigOrderPanel] 时段筛选变化:', newVal)

  if (!newVal) {
    store.setTimeRange(undefined, undefined)
    return
  }

  const [start, end] = newVal.split('-')

  // 解析时间
  const startHour = parseInt(start.substring(0, 2))
  const startMin = parseInt(start.substring(2, 4))
  const endHour = parseInt(end.substring(0, 2))
  const endMin = parseInt(end.substring(2, 4))

  // 创建时间对象（使用固定日期）
  const baseDate = '2000-01-01T'
  const startTime = new Date(`${baseDate}${startHour.toString().padStart(2, '0')}:${startMin.toString().padStart(2, '0')}:00`)
  const endTime = new Date(`${baseDate}${endHour.toString().padStart(2, '0')}:${endMin.toString().padStart(2, '0')}:00`)

  store.setTimeRange(startTime, endTime)
}, { immediate: false })  // 不需要立即执行

// 切换快速筛选
const toggleFilter = (type: 'fundMarker' | 'buyMarker', value: string) => {
  console.log(`[BigOrderPanel] 切换筛选: ${type}=${value}`)

  const currentValue = type === 'fundMarker'
    ? fundMarkerFilter.value
    : buyMarkerFilter.value

  // 构建新的筛选条件
  const newFilter: Partial<BigOrderFilter> = {}

  if (currentValue === value) {
    // 如果点击的是已选中的标签，清除对应的标记
    if (type === 'fundMarker') {
      newFilter.fundMarker = undefined
      newFilter.buyMarker = undefined
    } else {
      newFilter.buyMarker = undefined
      newFilter.fundMarker = undefined
    }
  } else {
    // 否则设置新的标记，并清除另一组标记
    if (type === 'fundMarker') {
      newFilter.fundMarker = value
      newFilter.buyMarker = undefined
    } else {
      newFilter.buyMarker = value
      newFilter.fundMarker = undefined
    }
  }

  store.setFilter(newFilter)
}

// 从 store 获取数据
const statistics = computed(() => store.filteredStatistics)
const periods = computed(() => store.periods)
const denseAlerts = computed(() => store.denseAlerts)

// 取消订阅函数
let unsubscribeClickOutside: (() => void) | null = null
let unsubscribeBigOrderUpdate: (() => void) | null = null

// 加载数据 - 带防重复
const loadData = async (code: string, name?: string) => {
  if (!code) return

  if (dataLoaded.value && store.currentStockCode.value === code) {
    console.log(`[BigOrderPanel] 股票 ${code} 数据已加载，跳过`)
    return
  }

  await store.loadStockData(code, name || code)
  dataLoaded.value = true
}

// 处理股票切换
const handleStockChange = async () => {
  if (!inputCode.value) return

  const code = inputCode.value.replace(/[^0-9]/g, '').padStart(6, '0')
  if (code.length !== 6) return

  dataLoaded.value = false
  resetAllFilters()
  await loadData(code, code)
  showAlerts.value = false
  showAnalysis.value = false
}

// 表格刷新处理
const handleTableRefresh = () => {
  console.log('[BigOrderPanel] 表格刷新完成')

  // 使用 EventManager 显示 Toast 提示
  EventManager.emit(AppEvents.UI.TOAST, {
    message: '✅ 大单数据已刷新',
    type: 'success',
    duration: 2000
  })

  // 如果开启语音，播报刷新完成
  if (voiceEnabled.value) {
    voiceService.speak('数据已刷新')
  }
}


// 切换语音播报
const toggleVoice = () => {
  voiceEnabled.value = !voiceEnabled.value

  // 保存到 localStorage
  localStorage.setItem('big-order-voice', String(voiceEnabled.value))

  // 播报状态变化
  if (voiceEnabled.value) {
    voiceService.speak('语音播报已开启')
  }

  // 触发事件，通知其他组件
  EventManager.emit('big-order:voice-toggle', voiceEnabled.value)
}

// 应用所有筛选条件
const applyFilters = () => {
  const filter: any = {}

  if (amountFilter.value > 0) filter.minAmount = amountFilter.value
  if (volumeFilter.value > 0) filter.minVolume = volumeFilter.value
  if (typeFilter.value) {
    filter.types = typeFilter.value.split(',').map(Number) as (1 | 2 | 3 | 4)[]
  }
  if (fundMarkerFilter.value) filter.fundMarker = fundMarkerFilter.value
  if (buyMarkerFilter.value) filter.buyMarker = buyMarkerFilter.value

  if (timeRangeFilter.value) {
    const today = new Date().toDateString()
    const [start, end] = timeRangeFilter.value.split('-')
    const startHour = parseInt(start.substring(0, 2))
    const startMin = parseInt(start.substring(2, 4))
    const endHour = parseInt(end.substring(0, 2))
    const endMin = parseInt(end.substring(2, 4))

    filter.startTime = new Date(`${today} ${startHour}:${startMin}:00`).getTime()
    filter.endTime = new Date(`${today} ${endHour}:${endMin}:00`).getTime()
  }

  store.setFilter(filter)
}

// 重置所有筛选
const resetAllFilters = () => {
  // 先检查当前值，避免重复设置
  if (amountFilter.value !== 0 ||
    volumeFilter.value !== 0 ||
    typeFilter.value !== '' ||
    fundMarkerFilter.value !== '' ||
    buyMarkerFilter.value !== '' ||
    timeRangeFilter.value !== '') {

    amountFilter.value = 0
    volumeFilter.value = 0
    typeFilter.value = ''
    fundMarkerFilter.value = ''
    buyMarkerFilter.value = ''
    timeRangeFilter.value = ''
    store.resetFilter()  // store 的 resetFilter 应该直接重置所有值
  }
}

// 格式化函数
const formatTime = (timestamp: number) => {
  const date = new Date(timestamp)
  return date.toLocaleTimeString('zh-CN', { hour12: false })
}

const formatAmount = (amount: number) => {
  if (amount >= 100000000) return `${(amount / 100000000).toFixed(1)}亿`
  if (amount >= 10000) return `${Math.round(amount / 10000)}万`
  return amount.toString()
}

// 点击外部关闭
const handleClickOutside = (e: MouseEvent) => {
  const panel = document.querySelector('.big-order-panel')
  if (panel && !panel.contains(e.target as Node)) {
    close()
  }
}

// 关闭面板
const close = () => {
  emit('update:visible', false)
  emit('close')
}


// 监听股票变化
watch(() => props.stockCode, async (newCode, oldCode) => {
  if (newCode && newCode !== oldCode) {
    inputCode.value = newCode
    dataLoaded.value = false
    resetAllFilters()
    await loadData(newCode, props.stockName || newCode)
  }
})

// 监听大单更新事件（用于语音播报）
const handleBigOrderUpdate = (data: any) => {
  if (!voiceEnabled.value) return

  const { code, igniteCount, smashCount } = data

  // 只播报当前查看的股票
  if (code === store.currentStockCode.value) {
    if (igniteCount > 0) {
      voiceService.speak(`${store.currentStockName}出现${igniteCount}次点火信号`)
    }
    if (smashCount > 0) {
      voiceService.speak(`${store.currentStockName}出现${smashCount}次砸盘信号`)
    }
  }
}

onMounted(() => {
  // 使用 EventManager 监听点击外部事件
  unsubscribeClickOutside = EventManager.on('mousedown', handleClickOutside)

  // 监听大单更新事件
  unsubscribeBigOrderUpdate = EventManager.on('big-order:updated', handleBigOrderUpdate)

  // 从 localStorage 读取语音设置
  const savedVoice = localStorage.getItem('big-order-voice')
  if (savedVoice !== null) {
    voiceEnabled.value = savedVoice === 'true'
  }

  // 只在首次挂载且没有通过 watch 加载时加载
  if (props.stockCode && !dataLoaded.value) {
    inputCode.value = props.stockCode
    // 先重置筛选条件，再加载数据
    resetAllFilters()  // 确保只调用一次
    loadData(props.stockCode, props.stockName || props.stockCode)
  }
})

onUnmounted(() => {
  // 使用 EventManager 取消订阅
  if (unsubscribeClickOutside) {
    unsubscribeClickOutside()
  }

  if (unsubscribeBigOrderUpdate) {
    unsubscribeBigOrderUpdate()
  }

  store.clear()
})
</script>

<style scoped>
/* ========== 面板容器 ========== */
.big-order-panel {
  position: fixed;
  top: 60px;
  right: 20px;
  width: 800px;
  height: calc(100vh - 80px);
  background-color: var(--bg-panel);
  backdrop-filter: blur(var(--blur-amount));
  border: 1px solid var(--border-color);
  border-radius: 12px;
  box-shadow: var(--shadow-xl);
  display: flex;
  flex-direction: column;
  z-index: 1000;
  overflow: hidden;
  animation: slideIn 0.2s ease;
}

@keyframes slideIn {
  from {
    opacity: 0;
    transform: translateX(20px);
  }

  to {
    opacity: 1;
    transform: translateX(0);
  }
}

/* ========== 面板头部 ========== */
.panel-header {
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-color);
  display: flex;
  justify-content: space-between;
  align-items: center;
  background-color: var(--bg-header);
  flex-shrink: 0;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.header-left h3 {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
}

.header-icon {
  font-size: 18px;
}

.stock-badge {
  padding: 4px 10px;
  background-color: var(--bg-hover);
  border-radius: 16px;
  font-size: 12px;
  color: var(--text-secondary);
}

.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

/* ========== 语音播报开关 ========== */
.voice-toggle {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  background-color: var(--bg-hover);
  border-radius: 16px;
  cursor: pointer;
  transition: all 0.2s;
  border: 1px solid var(--border-light);
}

.voice-toggle:hover {
  background-color: var(--bg-active);
}

.voice-toggle.active {
  background-color: var(--color-highlight);
  color: white;
  border-color: var(--color-highlight);
}

.voice-toggle.active .voice-icon {
  color: white;
}

.voice-icon {
  font-size: 14px;
  color: var(--text-secondary);
}

.voice-text {
  font-size: 12px;
  font-weight: 500;
}

/* ========== 预警按钮 ========== */
.alert-badge {
  position: relative;
  width: 32px;
  height: 32px;
  border-radius: 6px;
  background-color: var(--bg-hover);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.2s;
}

.alert-badge:hover {
  background-color: var(--bg-active);
}

.alert-icon {
  font-size: 16px;
}

.alert-count {
  position: absolute;
  top: -4px;
  right: -4px;
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  background-color: #ff4757;
  color: white;
  font-size: 10px;
  font-weight: 600;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.btn-close {
  width: 32px;
  height: 32px;
  border: none;
  background: none;
  border-radius: 6px;
  color: var(--text-secondary);
  font-size: 20px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}

.btn-close:hover {
  background-color: var(--bg-hover);
  color: var(--text-primary);
}

/* ========== 预警列表 ========== */
.alert-list {
  position: absolute;
  top: 60px;
  right: 20px;
  width: 300px;
  background-color: var(--bg-panel);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  box-shadow: var(--shadow-lg);
  z-index: 1001;
  overflow: hidden;
}

.alert-header {
  padding: 12px 16px;
  background-color: var(--bg-header);
  border-bottom: 1px solid var(--border-color);
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
  font-weight: 600;
}

.btn-small {
  padding: 4px 8px;
  border: none;
  background: var(--bg-hover);
  border-radius: 4px;
  color: var(--text-secondary);
  font-size: 11px;
  cursor: pointer;
}

.btn-small:hover {
  background: var(--bg-active);
  color: var(--text-primary);
}

.alert-items {
  max-height: 300px;
  overflow-y: auto;
}

.alert-item {
  padding: 10px 16px;
  border-bottom: 1px solid var(--border-light);
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
}

.alert-item:last-child {
  border-bottom: none;
}

.alert-time {
  color: var(--text-tertiary);
  font-size: 11px;
}

.alert-desc {
  color: var(--text-primary);
  font-weight: 500;
}

.alert-avg {
  color: var(--text-secondary);
  font-size: 11px;
}

.alert-empty {
  padding: 20px;
  text-align: center;
  color: var(--text-tertiary);
  font-size: 12px;
}

/* ========== 面板内容 ========== */
.panel-content {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

/* ========== 股票选择器 ========== */
.stock-selector {
  padding: 16px 20px;
  display: flex;
  gap: 8px;
  border-bottom: 1px solid var(--border-color);
  flex-shrink: 0;
}

.stock-selector input {
  flex: 1;
  height: 36px;
  padding: 0 12px;
  background-color: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  color: var(--text-primary);
  font-size: 14px;
}

.stock-selector input:focus {
  outline: none;
  border-color: var(--color-highlight);
}

.stock-selector button {
  width: 64px;
  height: 36px;
  border: none;
  background-color: var(--color-highlight);
  color: white;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.stock-selector button:hover {
  opacity: 0.9;
  transform: translateY(-1px);
}

/* ========== 筛选容器 ========== */
.filters-container {
  padding: 12px 16px;
  background-color: var(--bg-secondary);
  border-bottom: 1px solid var(--border-color);
  flex-shrink: 0;
}

.filters-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.filter-item {
  display: flex;
  align-items: center;
  background-color: var(--bg-panel);
  border: 1px solid var(--border-light);
  border-radius: 6px;
  overflow: hidden;
  height: 32px;
}

.filter-label {
  padding: 0 8px;
  font-size: 12px;
  color: var(--text-tertiary);
  background-color: var(--bg-hover);
  height: 100%;
  display: flex;
  align-items: center;
  white-space: nowrap;
  border-right: 1px solid var(--border-light);
}

.filter-select {
  padding: 4px 8px;
  background-color: transparent;
  color: var(--text-primary);
  border: none;
  font-size: 12px;
  cursor: pointer;
  outline: none;
  min-width: 80px;
}

.filter-select option {
  background-color: var(--bg-panel);
}

.time-range .filter-select {
  min-width: 90px;
}

.reset-filter-btn {
  width: 32px;
  height: 32px;
  border: none;
  background-color: var(--bg-hover);
  border-radius: 6px;
  color: var(--text-secondary);
  font-size: 18px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
  margin-left: auto;
  flex-shrink: 0;
}

.reset-filter-btn:hover {
  background-color: var(--bg-active);
  color: var(--text-primary);
  transform: rotate(180deg);
}

.reset-icon {
  display: inline-block;
  transition: transform 0.3s;
}

/* ========== 快速筛选标签 ========== */
.quick-filters {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
  padding-top: 8px;
  border-top: 1px dashed var(--border-light);
  flex-wrap: wrap;
}

.quick-label {
  font-size: 12px;
  color: var(--text-tertiary);
  white-space: nowrap;
}

.quick-tag {
  padding: 4px 12px;
  border: 1px solid var(--border-light);
  background-color: var(--bg-panel);
  color: var(--text-secondary);
  border-radius: 16px;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s;
  white-space: nowrap;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.quick-tag:hover {
  background-color: var(--bg-hover);
  border-color: var(--border-color);
}

.quick-tag.active {
  background-color: var(--color-highlight);
  color: white;
  border-color: var(--color-highlight);
}

.quick-tag.active .emoji {
  filter: brightness(0) invert(1);
}

/* ========== 空状态 ========== */
.empty-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: var(--text-tertiary);
}

.empty-icon {
  font-size: 48px;
  margin-bottom: 16px;
  opacity: 0.5;
}

.empty-text {
  font-size: 14px;
}

/* ========== 分析模态框 ========== */
.analysis-modal {
  position: fixed;
  top: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  z-index: 2000;
  display: flex;
  align-items: center;
  justify-content: center;
}

.modal-overlay {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background-color: rgba(0, 0, 0, 0.5);
}

.modal-content {
  position: relative;
  width: 90%;
  max-width: 800px;
  max-height: 90vh;
  background-color: var(--bg-panel);
  border-radius: 12px;
  overflow: hidden;
  box-shadow: var(--shadow-xl);
  z-index: 2001;
}

/* ========== 响应式设计 ========== */
@media (max-width: 768px) {
  .big-order-panel {
    width: 100%;
    height: 100vh;
    top: 0;
    right: 0;
    border-radius: 0;
  }

  .modal-content {
    width: 95%;
    max-height: 95vh;
  }

  .filters-row {
    flex-direction: column;
    align-items: stretch;
  }

  .filter-item {
    width: 100%;
  }

  .filter-select {
    flex: 1;
  }

  .reset-filter-btn {
    margin-left: 0;
    width: 100%;
  }

  .quick-filters {
    flex-wrap: wrap;
  }
}
</style>
