<!-- src/components/panels/RankTrendPanel.vue -->
<template>
  <Teleport to="body">
    <div v-if="visible" class="rank-trend-panel" :style="panelStyle" ref="panelRef">
      <!-- 头部 -->
      <div class="panel-header">
        <div class="header-left">
          <button class="back-btn" @click="close">← 返回</button>
          <h3>
            🎯 六维信号分析
            <span class="version-badge">v2.0</span>
          </h3>
        </div>
        <div class="panel-actions">
          <button class="btn-icon" @click="refresh" :class="{ loading }" title="刷新">
            <span :class="{ 'rotate-animation': loading }">🔄</span>
          </button>
          <button class="btn-icon" @click="close" title="关闭">✕</button>
        </div>
      </div>

      <!-- 搜索栏 -->
      <div class="search-bar">
        <input type="text" v-model="searchCode" placeholder="输入股票代码，如 600310" class="search-input"
          @keyup.enter="loadStock" />
        <button class="search-btn" @click="loadStock">分析</button>
      </div>

      <!-- 内容区域 -->
      <div class="panel-content">
        <!-- 加载状态 -->
        <div v-if="loading" class="loading-state">
          <div class="loading-spinner"></div>
          <span>加载中...</span>
        </div>

        <!-- 股票信息 -->
        <template v-else-if="currentStock">
          <!-- 股票头部卡片 -->
          <div class="stock-header-card">
            <div class="stock-info">
              <div class="stock-code">{{ currentStock.code }}</div>
              <div class="stock-name">{{ currentStock.name }}</div>
            </div>
            <div class="stock-change" :class="getChangeClass(currentStock.change)">
              {{ formatChange(currentStock.change) }}
            </div>
          </div>

          <!-- 综合信号大卡片 -->
          <div class="final-signal-card" :class="getSignalClass(currentStock.finalSignal)">
            <div class="final-signal-left">
              <div class="final-signal-label">综合判断</div>
              <div class="final-signal-value">{{ getSignalText(currentStock.finalSignal) }}</div>
            </div>
            <div class="final-signal-right">
              <div class="confidence-ring">
                <svg width="50" height="50" viewBox="0 0 60 60">
                  <circle cx="30" cy="30" r="26" fill="none" stroke="rgba(255,255,255,0.2)" stroke-width="4" />
                  <circle cx="30" cy="30" r="26" fill="none" stroke="currentColor" stroke-width="4"
                    :stroke-dasharray="163.36"
                    :stroke-dashoffset="163.36 * (1 - (currentStock.finalConfidence || 0) / 100)" stroke-linecap="round"
                    transform="rotate(-90 30 30)" />
                  <text x="30" y="36" text-anchor="middle" fill="currentColor" font-size="14" font-weight="bold">
                    {{ Math.round(currentStock.finalConfidence || 0) }}%
                  </text>
                </svg>
              </div>
              <div class="final-signal-metrics">
                <div class="metric-item">
                  <span class="metric-label">排名变化</span>
                  <span class="metric-value" :class="(currentStock.rankChange || 0) > 0 ? 'up' : 'down'">
                    {{ formatChange(currentStock.rankChange) }}
                  </span>
                </div>
                <div class="metric-item">
                  <span class="metric-label">MACD</span>
                  <span class="metric-value" :class="getCrossClass(currentStock.macdCross)">
                    {{ getCrossText(currentStock.macdCross) }}
                  </span>
                </div>
              </div>
            </div>
          </div>

          <!-- 计算详情卡片 -->
          <div v-if="signalDetails" class="calculation-detail-card">
            <div class="detail-header">
              <span class="detail-title">📐 六维信号计算详情</span>
              <span class="detail-tip">权重配置: 排名趋势35% | 资金25% | 技术15% | 板块10% | 情绪15%</span>
            </div>
            <div class="detail-items">
              <div v-for="item in signalDetails.items" :key="item.key" class="detail-item"
                :class="item.signal === 'buy' ? 'detail-buy' : item.signal === 'sell' ? 'detail-sell' : 'detail-hold'">
                <span class="detail-emoji">{{ item.emoji }}</span>
                <span class="detail-name">{{ item.name }}</span>
                <span class="detail-signal">{{ getSignalText(item.signal) }}</span>
                <span class="detail-conf">({{ item.confidence }}%)</span>
                <span class="detail-weight">权重{{ item.weight * 100 }}%</span>
                <span class="detail-contribution">→ {{ item.contributionText }}</span>
              </div>
            </div>
            <div class="detail-result">
              <span>加权总分 = {{ signalDetails.weightedScore.toFixed(4) }}</span>
              <span>总权重 = {{ signalDetails.totalWeight }}</span>
              <span>归一化分数 = {{ signalDetails.weightedScore.toFixed(4) }} / {{ signalDetails.totalWeight }} = {{
                signalDetails.normalizedScore.toFixed(4) }}</span>
              <span class="result-badge"
                :class="signalDetails.finalSignal === 'buy' ? 'result-buy' : signalDetails.finalSignal === 'sell' ? 'result-sell' : 'result-hold'">
                {{ signalDetails.finalSignal === 'buy' ? '✅ 买入信号' : signalDetails.finalSignal === 'sell' ? '❌ 卖出信号' :
                  '⏸️ 持有观望' }}
              </span>
            </div>
          </div>

          <!-- 六维信号网格 (2x3) -->
          <div class="signals-grid">
            <!-- 1. 排名趋势 -->
            <div class="signal-card" :class="getSignalClass(currentStock.rankTrendSignal)">
              <div class="signal-card-header">
                <span class="signal-icon">📊</span>
                <span class="signal-name">排名趋势</span>
                <span class="signal-badge" :class="getSignalClass(currentStock.rankTrendSignal)">
                  {{ getSignalText(currentStock.rankTrendSignal) }}
                </span>
              </div>
              <div class="signal-confidence">
                置信度 {{ currentStock.rankTrendConfidence || 0 }}%
              </div>
              <div class="signal-metrics">
                <div class="metric-row">
                  <span>排名变化</span>
                  <strong :class="(currentStock.rankChange || 0) > 0 ? 'up' : 'down'">
                    {{ formatChange(currentStock.rankChange) }}
                  </strong>
                </div>
                <div class="metric-row">
                  <span>综合排名</span>
                  <strong>{{ currentStock.compRank || '-' }}</strong>
                </div>
                <div class="metric-row">
                  <span>上榜平台</span>
                  <strong>{{ currentStock.platforms || 0 }}/8</strong>
                </div>
              </div>
            </div>

            <!-- 2. 资金信号 -->
            <div class="signal-card" :class="getSignalClass(currentStock.moneyFlowSignal)">
              <div class="signal-card-header">
                <span class="signal-icon">💰</span>
                <span class="signal-name">资金信号</span>
                <span class="signal-badge" :class="getSignalClass(currentStock.moneyFlowSignal)">
                  {{ getSignalText(currentStock.moneyFlowSignal) }}
                </span>
              </div>
              <div class="signal-confidence">
                置信度 {{ currentStock.moneyFlowConfidence || 0 }}%
              </div>
              <div class="signal-metrics">
                <div class="metric-row">
                  <span>主力净额</span>
                  <strong :class="(currentStock.zlje || 0) > 0 ? 'positive' : 'negative'">
                    {{ formatMoney(currentStock.zlje) }}
                  </strong>
                </div>
                <div class="metric-row">
                  <span>主力占比</span>
                  <strong>{{ (currentStock.zljzb || 0).toFixed(2) }}%</strong>
                </div>
                <div class="metric-row">
                  <span>机构增仓</span>
                  <strong>{{ formatMoney(currentStock.institutionBuy) }}</strong>
                </div>
              </div>
            </div>

            <!-- 3. 技术信号 -->
            <div class="signal-card" :class="getSignalClass(currentStock.technicalSignal)">
              <div class="signal-card-header">
                <span class="signal-icon">⚙️</span>
                <span class="signal-name">技术信号</span>
                <span class="signal-badge" :class="getSignalClass(currentStock.technicalSignal)">
                  {{ getSignalText(currentStock.technicalSignal) }}
                </span>
              </div>
              <div class="signal-confidence">
                置信度 {{ currentStock.technicalConfidence || 0 }}%
              </div>
              <div class="signal-metrics">
                <div class="metric-row">
                  <span>量比</span>
                  <strong>{{ (currentStock.volumeRatio || 0).toFixed(2) }}</strong>
                </div>
                <div class="metric-row">
                  <span>换手率</span>
                  <strong>{{ (currentStock.turnoverRate || 0).toFixed(2) }}%</strong>
                </div>
                <div class="metric-row">
                  <span>涨跌幅</span>
                  <strong :class="(currentStock.change || 0) > 0 ? 'up' : 'down'">
                    {{ formatChange(currentStock.change) }}
                  </strong>
                </div>
              </div>
            </div>

            <!-- 4. 情绪信号 -->
            <div class="signal-card" :class="getSignalClass(currentStock.marketSentimentSignal)">
              <div class="signal-card-header">
                <span class="signal-icon">🌊</span>
                <span class="signal-name">情绪信号</span>
                <span class="signal-badge" :class="getSignalClass(currentStock.marketSentimentSignal)">
                  {{ getSignalText(currentStock.marketSentimentSignal) }}
                </span>
              </div>
              <div class="signal-confidence">
                置信度 {{ currentStock.marketSentimentConfidence || 0 }}%
              </div>
              <div class="signal-metrics">
                <div class="metric-row">
                  <span>情绪得分</span>
                  <strong>{{ breathData?.overall || 0 }}</strong>
                </div>
                <div class="metric-row">
                  <span>情绪阶段</span>
                  <strong :class="['phase-color', breathData?.phaseName]">
                    {{ breathData?.phaseName || '-' }}
                  </strong>
                </div>
              </div>
            </div>

            <!-- 5. 板块信号 -->
            <div class="signal-card" :class="getSignalClass(currentStock.sectorSignal)">
              <div class="signal-card-header">
                <span class="signal-icon">📁</span>
                <span class="signal-name">板块信号</span>
                <span class="signal-badge" :class="getSignalClass(currentStock.sectorSignal)">
                  {{ getSignalText(currentStock.sectorSignal) }}
                </span>
              </div>
              <div class="signal-confidence">
                置信度 {{ currentStock.sectorConfidence || 0 }}%
              </div>
              <div class="signal-metrics">
                <div class="metric-row">
                  <span>主要题材</span>
                  <strong class="themes-text">
                    {{currentStock.themes?.slice(0, 2).map((t: any) => t.name).join(' · ') || '-'}}
                  </strong>
                </div>
              </div>
            </div>

            <!-- 6. MACD 指标卡片 -->
            <div class="signal-card macd-card">
              <div class="signal-card-header">
                <span class="signal-icon">📈</span>
                <span class="signal-name">MACD 指标</span>
                <span class="signal-badge" :class="getCrossClass(macdData?.cross)">
                  {{ getCrossText(macdData?.cross) }}
                </span>
              </div>
              <div class="macd-values">
                <div class="macd-item">
                  <span class="macd-label">MACD</span>
                  <span class="macd-number">{{ macdData?.macd?.toFixed(2) || 0 }}</span>
                </div>
                <div class="macd-item">
                  <span class="macd-label">信号线</span>
                  <span class="macd-number">{{ macdData?.signal?.toFixed(2) || 0 }}</span>
                </div>
                <div class="macd-item">
                  <span class="macd-label">柱状图</span>
                  <span class="macd-number" :class="(macdData?.histogram || 0) >= 0 ? 'positive' : 'negative'">
                    {{ macdData?.histogram?.toFixed(2) || 0 }}
                  </span>
                </div>
              </div>
              <div class="macd-trend">
                <span>MA5: {{ macdData?.ma5?.toFixed(2) || 0 }}</span>
                <span>MA10: {{ macdData?.ma10?.toFixed(2) || 0 }}</span>
                <span :class="macdData?.maTrend === 'up' ? 'up' : macdData?.maTrend === 'down' ? 'down' : ''">
                  趋势: {{ macdData?.maTrend === 'up' ? '向上' : macdData?.maTrend === 'down' ? '向下' : '平稳' }}
                </span>
              </div>
            </div>
          </div>

          <!-- 历史排名趋势 -->
          <div v-if="rankHistory.length" class="history-section">
            <div class="section-header">
              <span class="section-title">📈 历史排名趋势</span>
              <span class="section-count">最近{{ rankHistory.length }}个快照</span>
            </div>
            <!-- 趋势分析 -->
            <div class="trend-analysis" v-if="rankHistory.length >= 2">
              <div class="trend-stats">
                <span>当前排名: {{ rankHistory[rankHistory.length - 1] }}</span>
                <span>最高排名: {{ Math.min(...rankHistory) }}</span>
                <span>最低排名: {{ Math.max(...rankHistory) }}</span>
                <span :class="getTrendClass()">{{ getTrendText() }}</span>
              </div>
            </div>
            <div class="history-chart" ref="chartRef"></div>
          </div>
        </template>

        <!-- 空状态 -->
        <div v-else class="empty-state">
          <div class="empty-icon">🔍</div>
          <div class="empty-text">输入股票代码，查看六维信号</div>
          <div class="empty-hint">示例: 600396、000601、300750</div>
        </div>
      </div>

      <!-- 底部 -->
      <div class="panel-footer">
        <span>🎯 六维信号系统</span>
        <span>🕒 {{ formatTime(lastUpdate) }}</span>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { dataLayer } from '@/services/DataLayer'
import { usePanel } from '@/composables/usePanel'
import * as echarts from 'echarts'

const props = defineProps<{
  visible: boolean
  triggerRect?: DOMRect
}>()

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'close'): void
}>()

const close = () => {
  emit('update:visible', false)
  emit('close')
}

const { panelRef, panelStyle } = usePanel({
  name: 'RankTrendPanel',
  visible: props.visible,
  triggerRect: props.triggerRect,
  onClose: close,
})

const searchCode = ref('')
const loading = ref(false)
const currentStock = ref<any>(null)
const breathData = ref<any>(null)
const macdData = ref<any>(null)
const rankHistory = ref<number[]>([])
const signalDetails = ref<any>(null)
const lastUpdate = ref(Date.now())

let chart: echarts.ECharts | null = null
const chartRef = ref<HTMLElement | null>(null)

// 权重配置
const weights = {
  rankTrend: 0.35,      // 排名趋势 35%
  moneyFlow: 0.25,      // 资金流 25%
  technical: 0.15,      // 技术 15%
  sector: 0.10,         // 板块 10%
  sentiment: 0.15,      // 情绪 15%
}

// 计算六维信号详情
const calculateSignalDetails = (stock: any) => {
  const items = [
    { key: 'rankTrendSignal', confKey: 'rankTrendConfidence', name: '排名趋势', weight: weights.rankTrend, emoji: '📊' },
    { key: 'moneyFlowSignal', confKey: 'moneyFlowConfidence', name: '资金流向', weight: weights.moneyFlow, emoji: '💰' },
    { key: 'technicalSignal', confKey: 'technicalConfidence', name: '技术指标', weight: weights.technical, emoji: '⚡' },
    { key: 'sectorSignal', confKey: 'sectorConfidence', name: '板块题材', weight: weights.sector, emoji: '📁' },
    { key: 'marketSentimentSignal', confKey: 'marketSentimentConfidence', name: '市场情绪', weight: weights.sentiment, emoji: '🌊' },
  ]

  const details = []
  let weightedScore = 0
  let totalWeight = 0

  for (const item of items) {
    const signal = stock[item.key]
    const conf = stock[item.confKey] || 0
    let contribution = 0
    let contributionText = ''

    if (signal === 'buy') {
      contribution = item.weight * (conf / 100)
      weightedScore += contribution
      totalWeight += item.weight
      contributionText = `+${contribution.toFixed(4)}`
    } else if (signal === 'sell') {
      contribution = -item.weight * (conf / 100)
      weightedScore += contribution
      totalWeight += item.weight
      contributionText = `${contribution.toFixed(4)}`
    } else {
      contributionText = '不参与'
    }

    details.push({
      ...item,
      signal: signal || 'none',
      confidence: conf,
      contribution,
      contributionText,
    })
  }

  const normalizedScore = totalWeight > 0 ? weightedScore / totalWeight : 0
  const finalSignal = normalizedScore > 0.25 ? 'buy' : normalizedScore < -0.25 ? 'sell' : 'hold'

  return {
    items: details,
    weightedScore,
    totalWeight,
    normalizedScore,
    finalSignal,
  }
}

const loadStock = async () => {
  if (!searchCode.value) return

  loading.value = true
  try {
    const stocks = dataLayer.getStocks()
    const stock = stocks.find(s => s.code === searchCode.value)

    if (!stock) {
      loading.value = false
      return
    }

    currentStock.value = stock
    breathData.value = dataLayer.getBreathData()

    // 计算 MACD 数据（原有）
    macdData.value = {
      macd: stock.macd || 0,
      signal: stock.macdSignal || 0,
      histogram: stock.macdHistogram || 0,
      cross: stock.macdCross || 'none',
      ma5: stock.ma5 || 0,
      ma10: stock.ma10 || 0,
      maTrend: stock.maTrend || 'steady'
    }

    // ✅ 新增：计算六维信号详情
    signalDetails.value = calculateSignalDetails(stock)

    lastUpdate.value = Date.now()
    await loadRankHistory(searchCode.value)
    await nextTick()
    renderChart()
  } catch (error) {
    console.error('加载失败:', error)
  } finally {
    loading.value = false
  }
}

const loadRankHistory = async (code: string) => {
  try {
    const dates = await dataLayer.getSnapshotDates()
    const snapshots: { rank: number; timestamp: number; date: string }[] = []

    for (const date of dates) {
      const snapshot = await dataLayer.getSnapshotFromDB(date)
      if (snapshot?.type === 'daily' && snapshot?.hotlist) {
        const item = snapshot.hotlist.find((s: any) => s.code === code)
        if (item && item.rank) {
          snapshots.push({
            rank: item.rank,
            timestamp: snapshot.timestamp || Date.parse(date),
            date: date
          })
        }
      }
    }

    snapshots.sort((a, b) => a.timestamp - b.timestamp)
    rankHistory.value = snapshots.slice(-30).map(s => s.rank)

    console.log(`[RankTrendPanel] 加载 ${code} 历史排名: ${rankHistory.value.length} 个数据点`)
  } catch (error) {
    console.error('加载历史排名失败:', error)
    rankHistory.value = []
  }
}

const getTrendClass = () => {
  if (rankHistory.value.length < 2) return ''
  const first = rankHistory.value[0]
  const last = rankHistory.value[rankHistory.value.length - 1]
  if (last < first) return 'trend-up'
  if (last > first) return 'trend-down'
  return 'trend-steady'
}

const getTrendText = () => {
  if (rankHistory.value.length < 2) return ''
  const first = rankHistory.value[0]
  const last = rankHistory.value[rankHistory.value.length - 1]
  const change = first - last
  if (change > 0) return `排名上升 ${change} 位`
  if (change < 0) return `排名下降 ${Math.abs(change)} 位`
  return '排名平稳'
}

const renderChart = () => {
  if (!chartRef.value || rankHistory.value.length === 0) return

  // 销毁旧实例
  if (chart) {
    chart.dispose()
    chart = null
  }

  // 创建新实例
  chart = echarts.init(chartRef.value)

  // 计算最大最小值用于 Y 轴范围
  const maxRank = Math.max(...rankHistory.value)
  const minRank = Math.min(...rankHistory.value)
  const yAxisMin = Math.max(1, minRank - 5)
  const yAxisMax = maxRank + 5

  chart.setOption({
    grid: {
      left: '10%',
      right: '5%',
      top: 20,
      bottom: 10,
      containLabel: true
    },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params: any) => {
        if (!params || params.length === 0) return ''
        const data = params[0]
        const rank = data.value
        const index = data.dataIndex
        const total = rankHistory.value.length
        return `排名: ${rank}<br/>时间点: ${index + 1}/${total}`
      }
    },
    xAxis: {
      type: 'category',
      data: rankHistory.value.map((_, i) => i + 1),
      axisLabel: {
        show: true,
        fontSize: 9,
        color: '#9ca3af',
        interval: Math.floor(rankHistory.value.length / 10)
      },
      axisLine: { show: false },
      axisTick: { show: false }
    },
    yAxis: {
      type: 'value',
      name: '排名',
      nameTextStyle: { fontSize: 10, color: '#9ca3af' },
      inverse: true,  // 排名越小越好，所以倒置
      min: yAxisMin,
      max: yAxisMax,
      splitLine: { lineStyle: { color: '#2a2a3e', type: 'dashed' } },
      axisLabel: { fontSize: 10, color: '#9ca3af' }
    },
    series: [{
      type: 'line',
      data: rankHistory.value,
      smooth: true,
      lineStyle: {
        color: '#ff7f50',
        width: 2
      },
      areaStyle: {
        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: 'rgba(255, 127, 80, 0.3)' },
          { offset: 1, color: 'rgba(255, 127, 80, 0)' }
        ])
      },
      symbol: 'circle',
      symbolSize: 4,
      symbolFill: '#ff7f50',
      itemStyle: {
        color: '#ff7f50',
        borderColor: '#fff',
        borderWidth: 1
      },
      emphasis: {
        scale: 1.5
      }
    }]
  })

  // 自适应大小
  setTimeout(() => {
    chart?.resize()
  }, 100)
}

// 工具函数
const getSignalClass = (signal?: string) => {
  if (signal === 'buy') return 'signal-buy'
  if (signal === 'sell') return 'signal-sell'
  return 'signal-hold'
}

const getSignalText = (signal?: string) => {
  if (signal === 'buy') return '买入'
  if (signal === 'sell') return '卖出'
  return '持有'
}

const getChangeClass = (change: number) => {
  if (change > 0) return 'up'
  if (change < 0) return 'down'
  return ''
}

const getCrossClass = (cross?: string) => {
  if (cross === 'golden') return 'golden'
  if (cross === 'death') return 'death'
  return ''
}

const getCrossText = (cross?: string) => {
  if (cross === 'golden') return '金叉'
  if (cross === 'death') return '死叉'
  return '无'
}

const getPhaseColor = (phase?: string) => {
  // 返回 CSS 变量名，让浏览器解析
  const colorVars: Record<string, string> = {
    冰点期: 'var(--phase-ice)',
    低迷期: 'var(--phase-depressed)',
    启动期: 'var(--phase-start)',
    震荡期: 'var(--phase-oscillation)',
    平稳期: 'var(--phase-stable)',
    发酵期: 'var(--phase-ferment)',
    活跃期: 'var(--phase-active)',
    高潮期: 'var(--phase-climax)',
    退潮期: 'var(--phase-recession)'
  }
  return colorVars[phase || ''] || 'var(--text-secondary)'
}

const formatChange = (value?: number) => {
  if (value === undefined || value === null) return '-'
  return (value > 0 ? '+' : '') + value.toFixed(2) + '%'
}

const formatMoney = (value?: number) => {
  if (!value && value !== 0) return '-'
  const abs = Math.abs(value)
  if (abs >= 1e8) return (value / 1e8).toFixed(2) + '亿'
  if (abs >= 1e4) return (value / 1e4).toFixed(2) + '万'
  return value.toString()
}

const formatTime = (timestamp: number) => {
  const date = new Date(timestamp)
  return `${date.getHours().toString().padStart(2, '0')}:${date.getMinutes().toString().padStart(2, '0')}:${date.getSeconds().toString().padStart(2, '0')}`
}

const refresh = () => {
  if (searchCode.value) loadStock()
}

// 自动填充股票代码
watch(() => props.visible, (visible) => {
  if (visible && props.triggerRect) {
    const rect = props.triggerRect
    const target = document.elementFromPoint(rect.left + 10, rect.top + 10) as HTMLElement
    const row = target?.closest('[data-code]')
    if (row) {
      const code = row.getAttribute('data-code')
      if (code) {
        searchCode.value = code
        loadStock()
      }
    }
  }
})

onMounted(() => {
  window.addEventListener('resize', () => chart?.resize())
})

onUnmounted(() => {
  if (chart) {
    chart.dispose()
    chart = null
  }
})
</script>

<style scoped>
:root {
  --phase-ice: #7f8c8d;
  --phase-depressed: #95a5a6;
  --phase-start: #3498db;
  --phase-oscillation: #f39c12;
  --phase-stable: #2ecc71;
  --phase-ferment: #e67e22;
  --phase-active: #ff7f50;
  --phase-climax: #e74c3c;
  --phase-recession: #9b59b6;
}

.rank-trend-panel {
  position: fixed;
  width: 600px;
  max-width: calc(100vw - 40px);
  max-height: 85vh;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
  z-index: 10006;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  backdrop-filter: blur(10px);
}

/* 计算详情卡片 */
.calculation-detail-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 16px;
  margin-bottom: 20px;
}

.detail-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border-color);
  flex-wrap: wrap;
  gap: 8px;
}

.detail-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-highlight);
}

.detail-tip {
  font-size: 10px;
  color: var(--text-secondary);
}

/* 详情列表容器 */
.detail-items {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 12px;
}

/* 单个详情项 */
.detail-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  background: var(--bg-primary);
  border-radius: 8px;
  font-size: 12px;
  flex-wrap: wrap;
}

/* 买入信号项 */
.detail-item.detail-buy {
  border-left: 3px solid #f3091cad;
  background: rgba(187, 122, 127, 0.842);
}

/* 卖出信号项 */
.detail-item.detail-sell {
  border-left: 3px solid #2ed573;
  background: rgba(92, 148, 115, 0.897);
}

/* 持有信号项 */
.detail-item.detail-hold {
  border-left: 3px solid #aa8954a8;
  background: rgba(141, 100, 33, 0.534);
}

/* 表情符号 */
.detail-emoji {
  font-size: 18px;
  min-width: 28px;
  text-align: center;
}

/* 信号名称 */
.detail-name {
  width: 70px;
  font-weight: 500;
  color: var(--text-primary);
  font-size: 12px;
}

/* 信号方向文字 */
.detail-signal {
  width: 45px;
  font-weight: 600;
  font-size: 12px;
}

.detail-conf,
.detail-weight {
  color: #c0c0e0 !important;
}


/* 置信度 */
.detail-conf {
  min-width: 70px;
  color: #c0c0e0;
  font-family: monospace;
  font-size: 11px;
}

/* 权重 */
.detail-weight {
  min-width: 80px;
  color: #c0c0e0;
  font-family: monospace;
  font-size: 11px;
}

/* 贡献值 */
.detail-contribution {
  flex: 1;
  text-align: right;
  font-family: monospace;
  font-weight: 600;
  color: #e0e0e0 !important;
  font-size: 12px;
}

/* 结果区域 */
.detail-result {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: 12px;
  border-top: 1px solid var(--border-color);
  font-size: 11px;
  font-family: monospace;
  flex-wrap: wrap;
  gap: 12px;
  background: var(--bg-primary);
  padding: 12px;
  border-radius: 8px;
  margin-top: 8px;
}

/* 结果徽章 */
.result-badge {
  padding: 5px 14px;
  border-radius: 20px;
  font-weight: 700;
  font-size: 12px;
}

.result-buy {
  background: rgba(255, 71, 87, 0.15);
  color: #960814;
}

.result-sell {
  background: rgba(46, 213, 115, 0.15);
  color: #2ed573;
}

.result-hold {
  background: rgba(243, 156, 18, 0.15);
  color: #f39c12;
}


.detail-result span {
  color: var(--text-primary);
  font-size: 11px;
}

/* ========== 历史排名趋势样式 ========== */

.history-section {
  margin-top: 16px;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.section-title {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-title);
}

.section-count {
  font-size: 10px;
  padding: 2px 8px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  color: var(--text-secondary);
}

/* 趋势分析区域 */
.trend-analysis {
  margin-bottom: 12px;
  padding: 10px 14px;
  background: var(--bg-primary);
  border-radius: 8px;
  border: 1px solid var(--border-color);
}

.trend-stats {
  display: flex;
  gap: 20px;
  font-size: 11px;
  flex-wrap: wrap;
}

.trend-stats span {
  color: var(--text-secondary);
}

.trend-stats .trend-up {
  color: #ff4757;
  font-weight: 600;
}

.trend-stats .trend-down {
  color: #2ed573;
  font-weight: 600;
}

.trend-stats .trend-steady {
  color: #f39c12;
  font-weight: 600;
}

/* 图表容器 */
.history-chart {
  height: 140px;
  width: 100%;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 8px;
}

/* 加载状态 */
.loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  gap: 16px;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

/* 旋转动画 */
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

.phase-color.冰点期 {
  color: #7f8c8d;
}

.phase-color.低迷期 {
  color: #95a5a6;
}

.phase-color.启动期 {
  color: #3498db;
}

.phase-color.震荡期 {
  color: #f39c12;
}

.phase-color.平稳期 {
  color: #2ecc71;
}

.phase-color.发酵期 {
  color: #e67e22;
}

.phase-color.活跃期 {
  color: #ff7f50;
}

.phase-color.高潮期 {
  color: #e74c3c;
}

.phase-color.退潮期 {
  color: #9b59b6;
}

/* 头部 */
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

.back-btn {
  padding: 4px 10px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  font-size: 12px;
  cursor: pointer;
}

.back-btn:hover {
  background: var(--bg-hover);
  border-color: var(--color-highlight);
}

.panel-header h3 {
  margin: 0;
  font-size: 16px;
  color: var(--color-highlight);
}

.version-badge {
  font-size: 10px;
  background: var(--color-highlight);
  color: #000;
  padding: 2px 6px;
  border-radius: 12px;
  margin-left: 8px;
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
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}

.btn-icon:hover {
  background: var(--bg-hover);
  border-color: var(--color-highlight);
}

/* 搜索栏 */
.search-bar {
  display: flex;
  gap: 12px;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-color);
}

.search-input {
  flex: 1;
  padding: 8px 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 20px;
  font-size: 12px;
}

.search-input:focus {
  outline: none;
  border-color: var(--color-highlight);
}

.search-btn {
  padding: 8px 20px;
  background: var(--color-highlight);
  border: none;
  border-radius: 20px;
  font-weight: 500;
  cursor: pointer;
}

/* 内容区域 */
.panel-content {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
}

/* 股票头部卡片 */
.stock-header-card {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  background: var(--bg-secondary);
  border-radius: 12px;
  margin-bottom: 16px;
  border: 1px solid var(--border-color);
}

.stock-code {
  font-size: 20px;
  font-weight: 700;
  font-family: monospace;
  color: var(--text-title);
}

.stock-name {
  font-size: 12px;
  color: var(--text-secondary);
  margin-top: 2px;
}

.stock-change {
  font-size: 24px;
  font-weight: 700;
}

.stock-change.up {
  color: #ff4757;
}

.stock-change.down {
  color: #2ed573;
}

/* 综合信号卡片 */
.final-signal-card {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px;
  border-radius: 12px;
  margin-bottom: 20px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
}

.final-signal-card.signal-buy {
  border-left: 4px solid #ff4757;
}

.final-signal-card.signal-sell {
  border-left: 4px solid #2ed573;
}

.final-signal-card.signal-hold {
  border-left: 4px solid #f39c12;
}

.final-signal-label {
  font-size: 11px;
  color: var(--text-secondary);
  letter-spacing: 1px;
}

.final-signal-value {
  font-size: 28px;
  font-weight: 800;
}

.final-signal-card.signal-buy .final-signal-value {
  color: #ff4757;
}

.final-signal-card.signal-sell .final-signal-value {
  color: #2ed573;
}

.final-signal-card.signal-hold .final-signal-value {
  color: #f39c12;
}

.final-signal-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

.confidence-ring {
  color: var(--color-highlight);
}

.final-signal-metrics {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.metric-item {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  font-size: 11px;
}

.metric-label {
  color: var(--text-secondary);
}

.metric-value.up {
  color: #ff4757;
}

.metric-value.down {
  color: #2ed573;
}

.metric-value.golden {
  color: #ffd700;
}

.up,
.positive {
  color: #ff4757 !important;
}

.down,
.negative {
  color: #2ed573 !important;
}

.trend-analysis {
  margin-bottom: 12px;
  padding: 8px 12px;
  background: var(--bg-secondary);
  border-radius: 8px;
}

.trend-stats {
  display: flex;
  gap: 16px;
  font-size: 11px;
  flex-wrap: wrap;
}

.trend-stats span {
  color: var(--text-secondary);
}

.trend-stats .trend-up {
  color: #ff4757;
}

.trend-stats .trend-down {
  color: #2ed573;
}

.trend-stats .trend-steady {
  color: #f39c12;
}

/* 六维信号网格 */
.signals-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
  margin-bottom: 16px;
}

.signal-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 12px;
}

.signal-card.signal-buy {
  border-left: 3px solid #ff4757;
}

.signal-card.signal-sell {
  border-left: 3px solid #2ed573;
}

.signal-card.signal-hold {
  border-left: 3px solid #f39c12;
}

.signal-card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.signal-icon {
  font-size: 16px;
}

.signal-name {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-secondary);
}

.signal-badge {
  margin-left: auto;
  font-size: 10px;
  padding: 2px 8px;
  border-radius: 12px;
  font-weight: 600;
}

.signal-badge.signal-buy {
  background: rgba(255, 71, 87, 0.15);
  color: #ff4757;
}

.signal-badge.signal-sell {
  background: rgba(46, 213, 115, 0.15);
  color: #2ed573;
}

.signal-badge.signal-hold {
  background: rgba(243, 156, 18, 0.15);
  color: #f39c12;
}

.signal-confidence {
  font-size: 10px;
  color: var(--text-secondary);
  margin-bottom: 10px;
}

.signal-metrics {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.metric-row {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
}

.metric-row span:first-child {
  color: var(--text-secondary);
}

.metric-row strong {
  font-weight: 600;
}

.metric-row strong.up {
  color: #ff4757;
}

.metric-row strong.down {
  color: #2ed573;
}

.metric-row strong.positive {
  color: #ff4757;
}

.metric-row strong.negative {
  color: #2ed573;
}

.themes-text {
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* MACD 卡片 */
.macd-card {
  background: var(--bg-secondary);
}

.macd-values {
  display: flex;
  justify-content: space-around;
  margin-bottom: 10px;
  padding: 8px 0;
}

.macd-item {
  text-align: center;
}

.macd-label {
  display: block;
  font-size: 9px;
  color: var(--text-secondary);
  margin-bottom: 2px;
}

.macd-number {
  font-size: 12px;
  font-weight: 600;
}

.macd-number.positive {
  color: #ff4757;
}

.macd-number.negative {
  color: #2ed573;
}

.macd-trend {
  display: flex;
  justify-content: space-between;
  padding-top: 8px;
  border-top: 1px solid var(--border-color);
  font-size: 10px;
  color: var(--text-secondary);
}

.macd-trend .up {
  color: #ff4757;
}

.macd-trend .down {
  color: #2ed573;
}

/* 历史趋势 */
.history-section {
  margin-top: 8px;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.section-title {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-title);
}

.section-count {
  font-size: 10px;
  padding: 2px 6px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  color: var(--text-secondary);
}

.history-chart {
  height: 120px;
  width: 100%;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 8px;
}

/* 加载和空状态 */
.loading-state,
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

.empty-icon {
  font-size: 48px;
  opacity: 0.5;
}

.empty-text {
  font-size: 13px;
  color: var(--text-secondary);
}

.empty-hint {
  font-size: 11px;
  color: var(--text-tertiary);
}

/* 页脚 */
.panel-footer {
  padding: 10px 20px;
  border-top: 1px solid var(--border-color);
  background: var(--bg-header);
  font-size: 10px;
  color: var(--text-secondary);
  display: flex;
  justify-content: space-between;
}
</style>
