<!-- src/components/panels/TrendChartPanel.vue -->
<template>
  <Teleport to="body">
    <div v-if="visible" class="trend-panel" :style="panelStyle" ref="panelRef">
      <!-- 头部 -->
      <div class="panel-header">
        <div class="header-left">
          <span class="panel-icon">📈</span>
          <h3>龙头趋势·专业分析</h3>
          <span class="version-badge">v2.0.0</span>
        </div>
        <div class="header-actions">
          <button class="btn-icon" @click="refresh" :class="{ rotating: loading }" title="刷新">
            <span class="icon">↻</span>
          </button>
          <button class="btn-icon" @click="exportData" title="导出数据">📥</button>
          <button
            class="btn-icon"
            @click="toggleAutoRefresh"
            :class="{ active: autoRefresh }"
            title="自动刷新"
          >
            ⏱️
          </button>
          <button class="btn-icon close" @click="close" title="关闭">✕</button>
        </div>
      </div>

      <!-- 全局情绪卡片 -->
      <div class="emotion-card" :style="{ background: emotionGradient }">
        <div class="emotion-main">
          <div class="emotion-left">
            <span class="emotion-icon">{{ emotionIcon }}</span>
            <div class="emotion-info">
              <span class="emotion-phase">{{ sentiment.phase }}</span>
              <span class="emotion-score">{{ sentiment.overall }}分</span>
            </div>
          </div>
          <div class="emotion-suggestion">{{ sentiment.suggestion }}</div>
          <div class="emotion-meta">
            <span>涨停 {{ marketData.ztCount }}</span>
            <span>跌停 {{ marketData.dtCount }}</span>
            <span>炸板 {{ marketData.zhaban?.rate || 0 }}%</span>
          </div>
        </div>
      </div>

      <!-- 核心指标卡片 -->
      <div class="stats-grid">
        <div
          v-for="stat in coreStats"
          :key="stat.label"
          class="stat-card"
          :style="{ borderLeftColor: stat.color }"
        >
          <span class="stat-label">{{ stat.label }}</span>
          <span class="stat-value" :style="{ color: stat.color }">{{ stat.value }}</span>
          <span class="stat-change" :class="stat.trend > 0 ? 'up' : 'down'" v-if="stat.trend">
            {{ stat.trend > 0 ? '↑' : '↓' }} {{ Math.abs(stat.trend) }}
          </span>
        </div>
      </div>

      <!-- 多维分析标签页 -->
      <div class="tab-bar">
        <button
          v-for="tab in tabs"
          :key="tab.id"
          class="tab-btn"
          :class="{ active: activeTab === tab.id }"
          @click="activeTab = tab.id"
        >
          <span class="tab-icon">{{ tab.icon }}</span>
          <span class="tab-label">{{ tab.name }}</span>
        </button>
      </div>

      <!-- 图表容器 -->
      <div class="chart-wrapper">
        <div v-show="activeTab === 'leader'" class="chart-container" ref="leaderChartRef"></div>
        <div v-show="activeTab === 'sector'" class="chart-container" ref="sectorChartRef"></div>
        <div v-show="activeTab === 'money'" class="chart-container" ref="moneyChartRef"></div>
        <div v-show="activeTab === 'upgrade'" class="chart-container" ref="upgradeChartRef"></div>
        <div v-show="activeTab === 'board'" class="chart-container" ref="boardChartRef"></div>
        <div v-show="activeTab === 'emotion'" class="chart-container" ref="emotionChartRef"></div>
      </div>

      <!-- 数据表格 -->
      <div class="data-table-wrapper">
        <!-- 龙头排行 -->
        <div v-if="activeTab === 'leader'" class="data-section">
          <div class="section-header">
            <span class="section-title">👑 龙头股排行</span>
            <button class="more-btn" @click="viewAllLeaders">查看更多 →</button>
          </div>
          <div class="leader-table">
            <div class="table-header">
              <span>排名</span><span>代码</span><span>名称</span><span>级别</span><span>涨幅%</span><span>连板</span><span>热度</span>
            </div>
            <div
              v-for="(leader, idx) in leaderRanking"
              :key="leader.code"
              class="table-row"
              @click="selectStock(leader.code)"
            >
              <span class="rank" :style="{ color: getRankColor(idx) }">{{ idx + 1 }}</span>
              <span class="code">{{ leader.code }}</span>
              <span class="name">{{ leader.name }}</span>
              <span class="level" :style="{ color: getLevelColor(leader.level) }">{{
                leader.levelName
              }}</span>
              <span class="change" :class="leader.change >= 0 ? 'up' : 'down'"
                >{{ leader.change?.toFixed(2) }}%</span
              >
              <span class="days">{{ leader.continuousDays || 1 }}</span>
              <span class="score" :style="{ color: getHeatColor(leader.score) }">{{
                leader.score?.toFixed(0)
              }}</span>
            </div>
          </div>
        </div>

        <!-- 热门题材 -->
        <div v-if="activeTab === 'sector'" class="data-section">
          <div class="section-header">
            <span class="section-title">🔥 热门题材排行</span>
            <button class="more-btn" @click="viewAllSectors">查看更多 →</button>
          </div>
          <div class="sector-table">
            <div class="table-header">
              <span>排名</span><span>题材</span><span>热度</span><span>涨停</span><span>龙头</span><span>动量</span>
            </div>
            <div
              v-for="(sector, idx) in hotSectors"
              :key="sector.id"
              class="table-row"
              @click="viewSectorDetail(sector)"
            >
              <span class="rank" :style="{ color: getRankColor(idx) }">{{ idx + 1 }}</span>
              <span class="name">{{ sector.name }}</span>
              <span class="heat" :style="{ color: getHeatColor(sector.heatScore) }">{{
                sector.heatScore
              }}</span>
              <span class="zt">{{ sector.ztCount || 0 }}</span>
              <span class="leaders">{{ sector.leaderCount || 0 }}</span>
              <span class="momentum" :class="sector.momentum > 0 ? 'up' : 'down'">
                {{ sector.momentum > 0 ? '+' : '' }}{{ sector.momentum?.toFixed(1) }}
              </span>
            </div>
          </div>
        </div>

        <!-- 资金流向 -->
        <div v-if="activeTab === 'money'" class="data-section">
          <div class="fund-details">
            <div class="fund-item">
              <span class="label">主力净流入</span>
              <span class="value up">{{ formatMoney(moneyFlow.mainIn) }}</span>
            </div>
            <div class="fund-item">
              <span class="label">主力净流出</span>
              <span class="value down">{{ formatMoney(moneyFlow.mainOut) }}</span>
            </div>
            <div class="fund-item">
              <span class="label">净额</span>
              <span class="value" :class="moneyFlow.net >= 0 ? 'up' : 'down'">
                {{ formatMoney(moneyFlow.net) }}
              </span>
            </div>
          </div>
          <div class="fund-ratio">
            <div class="ratio-bar">
              <div class="ratio-in" :style="{ width: moneyFlow.inRatio + '%' }">
                <span v-if="moneyFlow.inRatio > 10">主力 {{ moneyFlow.inRatio.toFixed(1) }}%</span>
              </div>
              <div class="ratio-out" :style="{ width: moneyFlow.outRatio + '%' }">
                <span v-if="moneyFlow.outRatio > 10">散户 {{ moneyFlow.outRatio.toFixed(1) }}%</span>
              </div>
            </div>
          </div>
        </div>

        <!-- 晋级率分析 -->
        <div v-if="activeTab === 'upgrade'" class="data-section">
          <div class="upgrade-grid">
            <div class="upgrade-card">
              <span class="upgrade-label">一进二</span>
              <span class="upgrade-value">{{ upgradeRates.to2 }}%</span>
              <span class="upgrade-count"
                >{{ upgradeCounts.to2 }} / {{ upgradeCounts.total2 }}</span
              >
            </div>
            <div class="upgrade-card">
              <span class="upgrade-label">二进三</span>
              <span class="upgrade-value">{{ upgradeRates.to3 }}%</span>
              <span class="upgrade-count"
                >{{ upgradeCounts.to3 }} / {{ upgradeCounts.total3 }}</span
              >
            </div>
            <div class="upgrade-card">
              <span class="upgrade-label">三进四</span>
              <span class="upgrade-value">{{ upgradeRates.to4 }}%</span>
              <span class="upgrade-count"
                >{{ upgradeCounts.to4 }} / {{ upgradeCounts.total4 }}</span
              >
            </div>
            <div class="upgrade-card">
              <span class="upgrade-label">四进五</span>
              <span class="upgrade-value">{{ upgradeRates.to5 }}%</span>
              <span class="upgrade-count"
                >{{ upgradeCounts.to5 }} / {{ upgradeCounts.total5 }}</span
              >
            </div>
          </div>
        </div>

        <!-- 连板梯队 -->
        <div v-if="activeTab === 'board'" class="data-section">
          <div class="board-grid">
            <div v-for="level in boardLevels" :key="level.boards" class="board-level">
              <span class="board-label">{{ level.boards }}连板</span>
              <div class="board-stocks">
                <div
                  v-for="stock in level.stocks"
                  :key="stock.code"
                  class="board-stock"
                  @click="selectStock(stock.code)"
                >
                  <span class="stock-name">{{ stock.name }}</span>
                  <span class="stock-change" :class="stock.change >= 0 ? 'up' : 'down'">
                    {{ stock.change > 0 ? '+' : '' }}{{ stock.change?.toFixed(2) }}%
                  </span>
                </div>
                <div v-if="level.stocks.length === 0" class="empty-board">-</div>
              </div>
            </div>
          </div>
        </div>

        <!-- 情绪周期 -->
        <div v-if="activeTab === 'emotion'" class="data-section">
          <div class="emotion-phases">
            <div
              v-for="phase in emotionPhases"
              :key="phase.name"
              class="phase-card"
              :class="{ active: sentiment.phase === phase.name }"
              :style="{ borderColor: phase.color }"
            >
              <div class="phase-header" :style="{ background: phase.color + '20' }">
                <span class="phase-icon">{{ phase.icon }}</span>
                <span class="phase-name">{{ phase.name }}</span>
              </div>
              <div class="phase-features">
                <div v-for="feature in phase.features" :key="feature" class="feature-item">
                  • {{ feature }}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 底部 -->
      <div class="panel-footer">
        <span class="update-time">数据更新: {{ formatTime(lastUpdate) }}</span>
        <span class="data-source">数据源: 龙息分析器 + 题材分析</span>
        <button class="btn-clear" @click="clearCache">清除缓存</button>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import * as echarts from 'echarts'

// 服务导入
import { dragonBreathAnalyzer } from '@/services/DragonBreathAnalyzer'
import { dragonAnalyzer } from '@/services/DragonAnalyzer'
import { sectorAnalyzer } from '@/services/sectorAnalyzer'
import { dataLayer } from '@/services/DataLayer'
import { EventManager } from '@/utils/eventManager'
import { trendChartService } from '@/services/trendChartService'
import { useUIStore } from '@/stores/ui'

// 常量
import { MARKET_PHASES, LEADER_LEVELS, AppEvents } from '@/types'

const props = defineProps<{
  visible: boolean
  triggerRect?: DOMRect
}>()

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'close'): void
}>()

// ========== Stores ==========
const uiStore = useUIStore()

// ========== 状态 ==========
const panelRef = ref<HTMLElement | null>(null)
const loading = ref(false)
const autoRefresh = ref(true)
const activeTab = ref('leader')
const timeRange = ref(30)
const lastUpdate = ref(Date.now())
const chartsInitialized = ref(false)

// 图表容器引用
const leaderChartRef = ref<HTMLElement>()
const sectorChartRef = ref<HTMLElement>()
const moneyChartRef = ref<HTMLElement>()
const upgradeChartRef = ref<HTMLElement>()
const boardChartRef = ref<HTMLElement>()
const emotionChartRef = ref<HTMLElement>()

// 图表实例
let leaderChart: echarts.ECharts | null = null
let sectorChart: echarts.ECharts | null = null
let moneyChart: echarts.ECharts | null = null
let upgradeChart: echarts.ECharts | null = null
let boardChart: echarts.ECharts | null = null
let emotionChart: echarts.ECharts | null = null

// 定时器
let refreshTimer: ReturnType<typeof setInterval> | null = null

// ========== 标签页配置 ==========
const tabs = [
  { id: 'leader', name: '龙头趋势', icon: '👑' },
  { id: 'sector', name: '题材热度', icon: '🔥' },
  { id: 'money', name: '资金流向', icon: '💰' },
  { id: 'upgrade', name: '晋级率', icon: '📈' },
  { id: 'board', name: '连板梯队', icon: '⚡' },
  { id: 'emotion', name: '情绪周期', icon: '🌊' },
]

// ========== 数据获取 ==========
const sentiment = computed(() => dragonBreathAnalyzer.getMarketSentiment())
const marketData = computed(() => dragonBreathAnalyzer.getMarketData())
const leaders = computed(() => dragonAnalyzer.getAllLeaders?.({ limit: 50 }) || [])
const hotSectors = computed(() => sectorAnalyzer.getHotThemes?.(10) || [])

// 当前阶段信息
const currentPhase = computed(() => {
  return Object.values(MARKET_PHASES).find(p => p.name === sentiment.value.phase)
})

const emotionIcon = computed(() => currentPhase.value?.icon || '🌬️')
const emotionGradient = computed(
  () => currentPhase.value?.gradient || 'linear-gradient(135deg, #2c3e50, #34495e)'
)

// 核心指标
const coreStats = computed(() => {
  const s = sentiment.value
  const m = marketData.value
  const leaders_ = leaders.value

  return [
    {
      label: '市场情绪',
      value: s.overall.toFixed(0) + '分',
      color: currentPhase.value?.color || '#95a5a6',
      trend: s.overall - 50,
    },
    {
      label: '总龙头',
      value: leaders_.filter(l => l.level === 'TOTAL').length,
      color: '#FFD700',
      trend: 0,
    },
    {
      label: '连板龙头',
      value: leaders_.filter(l => l.level === 'CONTINUOUS').length,
      color: '#e74c3c',
      trend: 0,
    },
    {
      label: '涨停家数',
      value: m.ztCount,
      color: '#ff4757',
      trend: m.ztCount - (m.yesterdayZtPerformance || 0),
    },
  ]
})

// 龙头排行
const leaderRanking = computed(() => {
  return leaders.value.slice(0, 10).map(l => ({
    ...l,
    score: l.score || 0,
    change: l.change || 0,
    continuousDays: l.continuousDays || 1,
  }))
})

// 资金流向
const moneyFlow = computed(() => {
  const m = marketData.value.moneyFlow || {}
  const mainIn = Math.abs(m.main || 0) / 1e8
  const mainOut = Math.abs(m.retail || 0) / 1e8
  const net = mainIn - mainOut
  const total = mainIn + mainOut

  return {
    mainIn,
    mainOut,
    net,
    superIn: (m.cddje || 0) / 1e8,
    bigIn: mainIn * 0.6,
    mediumOut: mainOut * 0.4,
    smallOut: mainOut * 0.6,
    inRatio: total > 0 ? (mainIn / total) * 100 : 50,
    outRatio: total > 0 ? (mainOut / total) * 100 : 50,
  }
})

// 晋级率
const upgradeRates = computed(() => {
  const m = marketData.value
  return {
    to2: (((m.limitData?.erban || 0) / (m.yesterdayLimit?.yiban || 1)) * 100).toFixed(1),
    to3: (((m.limitData?.sanban || 0) / (m.yesterdayLimit?.erban || 1)) * 100).toFixed(1),
    to4: (((m.limitData?.sibanPlus || 0) / (m.yesterdayLimit?.sanban || 1)) * 100).toFixed(1),
    to5: (((m.limitData?.sibanPlus || 0) / (m.yesterdayLimit?.sanban || 1)) * 50).toFixed(1),
  }
})

const upgradeCounts = computed(() => {
  const m = marketData.value
  return {
    to2: m.limitData?.erban || 0,
    to3: m.limitData?.sanban || 0,
    to4: m.limitData?.sibanPlus || 0,
    to5: Math.floor((m.limitData?.sibanPlus || 0) / 2),
    total2: m.yesterdayLimit?.yiban || 1,
    total3: m.yesterdayLimit?.erban || 1,
    total4: m.yesterdayLimit?.sanban || 1,
    total5: m.yesterdayLimit?.sibanPlus || 1,
  }
})

// 连板梯队
const boardLevels = computed(() => {
  const stocks = dataLayer.getStocks()
  const levels = [2, 3, 4, 5, 6, 7, 8]

  return levels
    .map(boards => ({
      boards,
      stocks: stocks
        .filter(s => s.continuousDays === boards && (s.change || 0) > 9.5)
        .slice(0, 5)
        .map(s => ({ code: s.code, name: s.name, change: s.change })),
    }))
    .filter(level => level.stocks.length > 0 || level.boards <= 5)
})

// 情绪阶段列表
const emotionPhases = Object.values(MARKET_PHASES)

// ========== 面板样式 ==========
const panelStyle = computed(() => {
  if (!props.triggerRect) {
    return {
      top: '80px',
      left: '50%',
      transform: 'translateX(-50%)',
      width: '1200px',
      maxWidth: '90vw',
    }
  }
  return {
    top: props.triggerRect.bottom + 5 + 'px',
    left: '50%',
    transform: 'translateX(-50%)',
    width: '1200px',
    maxWidth: '90vw',
  }
})

// ========== 工具函数 ==========
const formatMoney = (value: number) => {
  if (!value && value !== 0) return '--'
  const abs = Math.abs(value)
  if (abs >= 1e8) return (value / 1e8).toFixed(2) + '亿'
  if (abs >= 1e4) return (value / 1e4).toFixed(2) + '万'
  return value.toFixed(2)
}

const formatTime = (timestamp: number) => {
  const date = new Date(timestamp)
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}:${String(date.getSeconds()).padStart(2, '0')}`
}

const getRankColor = (index: number) => {
  const colors = ['#ffd700', '#c0c0c0', '#cd7f32']
  return colors[index] || '#7f8c8d'
}

const getLevelColor = (level: string) => {
  return LEADER_LEVELS[level as keyof typeof LEADER_LEVELS]?.color || '#7f8c8d'
}

const getHeatColor = (score: number) => {
  if (score >= 80) return '#ff4757'
  if (score >= 60) return '#ffa502'
  if (score >= 40) return '#3498db'
  return '#7f8c8d'
}

// ========== 图表渲染 ==========
function renderLeaderChart(chart: echarts.ECharts) {
  const data = trendChartService.getLeaderTrendData(timeRange.value)

  chart.setOption({
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { data: ['总龙头', '连板龙头', '板块龙头'], bottom: 0, textStyle: { color: '#999' } },
    grid: { left: '3%', right: '4%', bottom: '10%', top: '5%', containLabel: true },
    xAxis: {
      type: 'category',
      data: data.labels,
      axisLabel: { rotate: 30, color: '#999' },
    },
    yAxis: { type: 'value', axisLabel: { color: '#999' } },
    series: [
      {
        name: '总龙头',
        type: 'line',
        data: data.total,
        color: '#FFD700',
        smooth: true,
        symbol: 'circle',
      },
      { name: '连板龙头', type: 'line', data: data.continuous, color: '#e74c3c', smooth: true },
      { name: '板块龙头', type: 'line', data: data.sector, color: '#3498db', smooth: true },
    ],
  })
}

function renderSectorChart(chart: echarts.ECharts) {
  const data = trendChartService.getSectorHeatData()

  chart.setOption({
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { data: ['题材热度', '涨停数量'], bottom: 0, textStyle: { color: '#999' } },
    grid: { left: '3%', right: '4%', bottom: '10%', top: '5%', containLabel: true },
    xAxis: {
      type: 'category',
      data: data.labels,
      axisLabel: { rotate: 30, color: '#999' },
    },
    yAxis: [
      { type: 'value', name: '热度', axisLabel: { color: '#999' } },
      { type: 'value', name: '涨停', axisLabel: { color: '#999' } },
    ],
    series: [
      { name: '题材热度', type: 'bar', data: data.heat, color: '#ffa502', yAxisIndex: 0 },
      {
        name: '涨停数量',
        type: 'line',
        data: data.zt,
        color: '#ff4757',
        yAxisIndex: 1,
        smooth: true,
      },
    ],
  })
}

function renderMoneyChart(chart: echarts.ECharts) {
  const mf = moneyFlow.value

  chart.setOption({
    tooltip: { trigger: 'item', formatter: '{b}: {c}亿' },
    legend: { orient: 'vertical', left: 'left', textStyle: { color: '#999' } },
    series: [
      {
        name: '资金流向',
        type: 'pie',
        radius: ['40%', '70%'],
        label: { show: true, position: 'outside', formatter: '{b}: {d}%', color: '#999' },
        data: [
          { value: mf.mainIn, name: '主力流入', itemStyle: { color: '#2ed573' } },
          { value: mf.mainOut, name: '主力流出', itemStyle: { color: '#ff4757' } },
          {
            value: Math.abs(mf.net),
            name: mf.net >= 0 ? '净流入' : '净流出',
            itemStyle: { color: '#ffa502' },
          },
        ],
      },
    ],
  })
}

function renderUpgradeChart(chart: echarts.ECharts) {
  chart.setOption({
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: '3%', right: '4%', bottom: '3%', top: '5%', containLabel: true },
    xAxis: {
      type: 'category',
      data: ['一进二', '二进三', '三进四', '四进五'],
      axisLabel: { color: '#999' },
    },
    yAxis: {
      type: 'value',
      name: '晋级率 %',
      max: 100,
      axisLabel: { color: '#999' },
    },
    series: [
      {
        name: '晋级率',
        type: 'bar',
        data: [
          parseFloat(upgradeRates.value.to2),
          parseFloat(upgradeRates.value.to3),
          parseFloat(upgradeRates.value.to4),
          parseFloat(upgradeRates.value.to5),
        ],
        itemStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: '#9b59b6' },
            { offset: 1, color: '#8e44ad' },
          ]),
        },
        label: { show: true, position: 'top', formatter: '{c}%', color: '#999' },
      },
    ],
  })
}

function renderBoardChart(chart: echarts.ECharts) {
  const boards = boardLevels.value
  const data = boards.map(b => b.stocks.length)
  const labels = boards.map(b => b.boards + '连板')

  chart.setOption({
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: '3%', right: '4%', bottom: '3%', top: '5%', containLabel: true },
    xAxis: {
      type: 'category',
      data: labels,
      axisLabel: { color: '#999' },
    },
    yAxis: {
      type: 'value',
      name: '股票数量',
      axisLabel: { color: '#999' },
    },
    series: [
      {
        name: '连板梯队',
        type: 'bar',
        data: data,
        itemStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: '#e74c3c' },
            { offset: 1, color: '#c0392b' },
          ]),
        },
        label: { show: true, position: 'top', color: '#999' },
      },
    ],
  })
}

function renderEmotionChart(chart: echarts.ECharts) {
  const history = dragonBreathAnalyzer.getHistory?.(30) || []
  const scores = history.map(h => h.sentiment.overall)
  const labels = history.map(h => new Date(h.timestamp).toLocaleDateString().slice(5))

  chart.setOption({
    tooltip: { trigger: 'axis' },
    grid: { left: '3%', right: '4%', bottom: '3%', top: '5%', containLabel: true },
    xAxis: {
      type: 'category',
      data: labels,
      axisLabel: { rotate: 30, color: '#999' },
    },
    yAxis: {
      type: 'value',
      min: 0,
      max: 100,
      axisLabel: { color: '#999' },
    },
    series: [
      {
        name: '情绪指数',
        type: 'line',
        data: scores,
        smooth: true,
        lineStyle: { color: '#9b59b6', width: 3 },
        areaStyle: { color: '#9b59b620' },
        markPoint: {
          data: [
            { type: 'max', name: '峰值' },
            { type: 'min', name: '谷值' },
          ],
        },
        markLine: {
          data: [
            { yAxis: 20, name: '冰点', lineStyle: { color: '#7f8c8d', type: 'dashed' } },
            { yAxis: 40, name: '启动', lineStyle: { color: '#3498db', type: 'dashed' } },
            { yAxis: 60, name: '发酵', lineStyle: { color: '#f39c12', type: 'dashed' } },
            { yAxis: 80, name: '高潮', lineStyle: { color: '#e74c3c', type: 'dashed' } },
          ],
        },
      },
    ],
  })
}

// 渲染当前标签页的图表
async function renderCurrentChart() {
  await nextTick()
  await new Promise(resolve => setTimeout(resolve, 50))

  switch (activeTab.value) {
    case 'leader':
      if (!leaderChart && leaderChartRef.value) {
        leaderChart = echarts.init(leaderChartRef.value)
      }
      if (leaderChart) renderLeaderChart(leaderChart)
      break
    case 'sector':
      if (!sectorChart && sectorChartRef.value) {
        sectorChart = echarts.init(sectorChartRef.value)
      }
      if (sectorChart) renderSectorChart(sectorChart)
      break
    case 'money':
      if (!moneyChart && moneyChartRef.value) {
        moneyChart = echarts.init(moneyChartRef.value)
      }
      if (moneyChart) renderMoneyChart(moneyChart)
      break
    case 'upgrade':
      if (!upgradeChart && upgradeChartRef.value) {
        upgradeChart = echarts.init(upgradeChartRef.value)
      }
      if (upgradeChart) renderUpgradeChart(upgradeChart)
      break
    case 'board':
      if (!boardChart && boardChartRef.value) {
        boardChart = echarts.init(boardChartRef.value)
      }
      if (boardChart) renderBoardChart(boardChart)
      break
    case 'emotion':
      if (!emotionChart && emotionChartRef.value) {
        emotionChart = echarts.init(emotionChartRef.value)
      }
      if (emotionChart) renderEmotionChart(emotionChart)
      break
  }
}

// ========== 操作方法 ==========
async function refresh() {
  loading.value = true
  dragonBreathAnalyzer.analyzeMarketBreath(true)
  dragonAnalyzer.recalculateAll?.()
  await nextTick()
  await renderCurrentChart()
  lastUpdate.value = Date.now()
  loading.value = false
  EventManager.emit(AppEvents.UI.TOAST, { message: '🔄 数据已刷新', duration: 1000, type: 'info' })
}

function close() {
  emit('update:visible', false)
  emit('close')
  EventManager.emit(AppEvents.UI.PANEL_CLOSE, { panel: 'trend' })
}

function toggleAutoRefresh() {
  autoRefresh.value = !autoRefresh.value
}

function exportData() {
  const data = {
    exportTime: new Date().toISOString(),
    sentiment: sentiment.value,
    marketData: marketData.value,
    leaders: leaders.value,
    hotSectors: hotSectors.value,
    moneyFlow: moneyFlow.value,
    upgradeRates: upgradeRates.value,
  }

  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `龙头趋势_${new Date().toISOString().slice(0, 10)}.json`
  a.click()
  URL.revokeObjectURL(url)

  EventManager.emit(AppEvents.UI.TOAST, {
    message: '📥 数据已导出',
    duration: 1500,
    type: 'success',
  })
}

function clearCache() {
  trendChartService.clearCache?.()
  EventManager.emit(AppEvents.UI.TOAST, {
    message: '🧹 缓存已清除',
    duration: 1500,
    type: 'success',
  })
}

function selectStock(code: string) {
  uiStore.selectStock(code)
  EventManager.emit(AppEvents.STOCK.SELECTED, { code })
}

function viewAllLeaders() {
  EventManager.emit('dragon:show-panel', { tab: 'list' })
}

function viewAllSectors() {
  EventManager.emit('sector:show-panel', { tab: 'hot' })
}

function viewSectorDetail(sector: any) {
  EventManager.emit('sector:show-detail', {
    sectorName: sector.name,
    sectorId: sector.id,
  })
}

// ========== 点击外部关闭 ==========
function handleClickOutside(e: MouseEvent) {
  if (!panelRef.value || !props.visible) return
  const target = e.target as Node
  if (panelRef.value.contains(target)) return
  close()
}

// ========== 自动刷新 ==========
function startAutoRefresh() {
  if (refreshTimer) clearInterval(refreshTimer)
  refreshTimer = setInterval(() => {
    if (autoRefresh.value && props.visible) {
      refresh()
    }
  }, 30000)
}

function stopAutoRefresh() {
  if (refreshTimer) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
}

// ========== 生命周期 ==========
onMounted(() => {
  document.addEventListener('click', handleClickOutside)
  setTimeout(() => {
    renderCurrentChart()
  }, 200)
  startAutoRefresh()
  EventManager.emit(AppEvents.UI.PANEL_OPEN, { panel: 'trend' })
})

onUnmounted(() => {
  stopAutoRefresh()
  if (leaderChart) leaderChart.dispose()
  if (sectorChart) sectorChart.dispose()
  if (moneyChart) moneyChart.dispose()
  if (upgradeChart) upgradeChart.dispose()
  if (boardChart) boardChart.dispose()
  if (emotionChart) emotionChart.dispose()
  document.removeEventListener('click', handleClickOutside)
})

// 监听标签页变化
watch(activeTab, async () => {
  await nextTick()
  setTimeout(() => {
    renderCurrentChart()
  }, 100)
})

// 监听可见性变化
watch(() => props.visible, async (val) => {
  if (val) {
    await nextTick()
    setTimeout(() => {
      renderCurrentChart()
      ;[leaderChart, sectorChart, moneyChart, upgradeChart, boardChart, emotionChart].forEach(chart => {
        chart?.resize()
      })
    }, 200)
  }
})
</script>

<style scoped>
.trend-panel {
  position: fixed;
  width: 1200px;
  max-width: 90vw;
  max-height: 85vh;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 24px;
  box-shadow: 0 20px 40px rgba(0, 0, 0, 0.4);
  z-index: 10008;
  font-size: 13px;
  overflow: hidden;
  backdrop-filter: blur(20px);
  display: flex;
  flex-direction: column;
  animation: slideIn 0.2s ease;
}

@keyframes slideIn {
  from {
    opacity: 0;
    transform: translate(-50%, -10px);
  }
  to {
    opacity: 1;
    transform: translate(-50%, 0);
  }
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 24px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-header);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.panel-icon {
  font-size: 24px;
}

.panel-header h3 {
  margin: 0;
  font-size: 18px;
  color: var(--color-highlight);
}

.version-badge {
  padding: 2px 8px;
  background: var(--color-highlight);
  color: #000;
  border-radius: 12px;
  font-size: 10px;
}

.header-actions {
  display: flex;
  gap: 6px;
}

.btn-icon {
  width: 36px;
  height: 36px;
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

.btn-icon.active {
  color: #2ed573;
  border-color: #2ed573;
}

.rotating {
  animation: rotate 1s infinite linear;
}

@keyframes rotate {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

.emotion-card {
  margin: 16px 24px;
  padding: 16px 20px;
  border-radius: 16px;
  color: white;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
}

.emotion-main {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 16px;
}

.emotion-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.emotion-icon {
  font-size: 28px;
}

.emotion-info {
  display: flex;
  flex-direction: column;
}

.emotion-phase {
  font-size: 16px;
  font-weight: 600;
}

.emotion-score {
  font-size: 12px;
  opacity: 0.9;
}

.emotion-suggestion {
  padding: 6px 16px;
  background: rgba(0, 0, 0, 0.3);
  border-radius: 20px;
  font-size: 13px;
}

.emotion-meta {
  display: flex;
  gap: 16px;
  font-size: 12px;
  background: rgba(0, 0, 0, 0.2);
  padding: 6px 12px;
  border-radius: 20px;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin: 0 24px 16px;
}

.stat-card {
  background: var(--bg-secondary);
  border-radius: 12px;
  padding: 14px;
  border-left: 4px solid transparent;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.stat-label {
  font-size: 11px;
  color: var(--text-secondary);
}

.stat-value {
  font-size: 20px;
  font-weight: 600;
}

.stat-change {
  font-size: 10px;
  margin-left: auto;
}

.stat-change.up {
  color: #ff4757;
}
.stat-change.down {
  color: #2ed573;
}

.tab-bar {
  display: flex;
  gap: 4px;
  padding: 0 24px 12px;
  border-bottom: 1px solid var(--border-color);
}

.tab-btn {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 10px 0;
  border: none;
  background: transparent;
  border-radius: 8px;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.2s;
  font-size: 13px;
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

.chart-wrapper {
  height: 280px;
  margin: 16px 24px;
  background: var(--bg-secondary);
  border-radius: 16px;
  padding: 16px;
}

.chart-container {
  width: 100%;
  height: 100%;
}

.data-table-wrapper {
  flex: 1;
  margin: 0 24px 16px;
  overflow-y: auto;
  max-height: 250px;
  border: 1px solid var(--border-color);
  border-radius: 12px;
  background: var(--bg-secondary);
}

.data-section {
  padding: 16px;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.section-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-highlight);
}

.more-btn {
  background: transparent;
  border: 1px solid var(--border-color);
  color: var(--text-secondary);
  padding: 4px 12px;
  border-radius: 16px;
  font-size: 11px;
  cursor: pointer;
  transition: all 0.2s;
}

.more-btn:hover {
  background: var(--color-highlight);
  color: #000;
  border-color: var(--color-highlight);
}

/* 表格样式 */
.leader-table,
.sector-table {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.table-header {
  display: grid;
  grid-template-columns: 50px 80px 100px 80px 70px 50px 50px;
  padding: 8px 12px;
  background: var(--bg-header);
  border-radius: 8px;
  font-size: 11px;
  color: var(--text-secondary);
  font-weight: 500;
}

.table-row {
  display: grid;
  grid-template-columns: 50px 80px 100px 80px 70px 50px 50px;
  padding: 8px 12px;
  background: var(--bg-primary);
  border-radius: 6px;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s;
}

.table-row:hover {
  background: var(--bg-hover);
  transform: translateX(4px);
}

.table-row .rank {
  font-weight: 600;
}
.table-row .code {
  color: var(--text-secondary);
  font-family: monospace;
}
.table-row .name {
  color: var(--text-primary);
}
.table-row .up {
  color: #ff4757;
}
.table-row .down {
  color: #2ed573;
}

/* 资金流向 */
.fund-details {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin-bottom: 16px;
}

.fund-item {
  background: var(--bg-primary);
  padding: 12px;
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.fund-item .label {
  font-size: 11px;
  color: var(--text-secondary);
}

.fund-item .value {
  font-size: 16px;
  font-weight: 600;
}

.fund-item .value.up {
  color: #ff4757;
}
.fund-item .value.down {
  color: #2ed573;
}

.fund-ratio {
  background: var(--bg-primary);
  padding: 12px;
  border-radius: 8px;
}

.ratio-bar {
  display: flex;
  height: 30px;
  background: var(--bg-secondary);
  border-radius: 15px;
  overflow: hidden;
}

.ratio-in {
  height: 100%;
  background: linear-gradient(90deg, #ff4757, #ff6b81);
  display: flex;
  align-items: center;
  justify-content: flex-end;
  padding-right: 8px;
  color: white;
  font-size: 11px;
  font-weight: 500;
}

.ratio-out {
  height: 100%;
  background: linear-gradient(90deg, #3498db, #5dade2);
  display: flex;
  align-items: center;
  padding-left: 8px;
  color: white;
  font-size: 11px;
  font-weight: 500;
}

/* 晋级率 */
.upgrade-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}

.upgrade-card {
  background: var(--bg-primary);
  padding: 16px;
  border-radius: 12px;
  text-align: center;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.upgrade-label {
  font-size: 12px;
  color: var(--text-secondary);
}

.upgrade-value {
  font-size: 24px;
  font-weight: bold;
  color: #9b59b6;
}

.upgrade-count {
  font-size: 11px;
  color: var(--text-secondary);
}

/* 连板梯队 */
.board-grid {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.board-level {
  display: flex;
  align-items: center;
  gap: 12px;
}

.board-label {
  width: 60px;
  font-size: 12px;
  font-weight: 600;
  color: #e74c3c;
}

.board-stocks {
  flex: 1;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.board-stock {
  padding: 4px 10px;
  background: var(--bg-primary);
  border-radius: 16px;
  font-size: 11px;
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  gap: 6px;
}

.board-stock:hover {
  background: var(--bg-hover);
  transform: translateY(-2px);
}

.stock-name {
  color: var(--text-primary);
}

.stock-change.up {
  color: #ff4757;
}
.stock-change.down {
  color: #2ed573;
}

.empty-board {
  color: var(--text-tertiary);
  font-size: 11px;
  padding: 4px 0;
}

/* 情绪周期 */
.emotion-phases {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}

.phase-card {
  background: var(--bg-primary);
  border-radius: 12px;
  overflow: hidden;
  border-left: 4px solid transparent;
  opacity: 0.6;
  transition: all 0.2s;
}

.phase-card.active {
  opacity: 1;
  transform: scale(1.02);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
}

.phase-header {
  padding: 10px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.phase-icon {
  font-size: 16px;
}

.phase-name {
  font-size: 12px;
  font-weight: 600;
}

.phase-features {
  padding: 10px;
  font-size: 11px;
  color: var(--text-secondary);
}

.feature-item {
  margin-bottom: 4px;
}

.panel-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 24px;
  border-top: 1px solid var(--border-color);
  background: var(--bg-header);
  font-size: 11px;
  color: var(--text-secondary);
}

.data-source {
  color: var(--text-tertiary);
}

.btn-clear {
  background: transparent;
  border: 1px solid var(--border-color);
  color: var(--color-highlight);
  padding: 4px 12px;
  border-radius: 16px;
  cursor: pointer;
  font-size: 11px;
  transition: all 0.2s;
}

.btn-clear:hover {
  background: var(--color-highlight);
  color: #000;
  border-color: var(--color-highlight);
}

/* 滚动条 */
.data-table-wrapper::-webkit-scrollbar {
  width: 4px;
}

.data-table-wrapper::-webkit-scrollbar-track {
  background: transparent;
}

.data-table-wrapper::-webkit-scrollbar-thumb {
  background: var(--border-color);
  border-radius: 2px;
}

.data-table-wrapper::-webkit-scrollbar-thumb:hover {
  background: var(--color-highlight);
}

/* 响应式 */
@media (max-width: 1024px) {
  .trend-panel {
    width: 95vw;
  }

  .stats-grid {
    grid-template-columns: repeat(2, 1fr);
  }

  .emotion-main {
    flex-direction: column;
    align-items: flex-start;
  }

  .table-header,
  .table-row {
    grid-template-columns: 40px 70px 80px 70px 60px 40px 40px;
    font-size: 11px;
  }
}
</style>
