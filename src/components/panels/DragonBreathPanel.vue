<!-- src/components/panels/DragonBreathPanel.vue -->
<!-- 纯响应式版本：只依赖 dataLayer，从 emotion.ts 读取情绪阶段配置 -->

<template>
  <div v-show="visible" class="breath-panel" :style="panelStyle" ref="panelRef">
    <!-- 头部 -->
    <div class="panel-header">
      <div class="header-left">
        <h3>🔥 龙息分析 · 市场情绪</h3>
        <div class="stats-badge" v-if="marketData">
          <span :class="marketData.upCount >= marketData.downCount ? 'up-text' : ''">
            {{ formatNumber(marketData.upCount) }}涨
          </span>
          <span class="dot">•</span>
          <span :class="marketData.downCount > marketData.upCount ? 'down-text' : ''">
            {{ formatNumber(marketData.downCount) }}跌
          </span>
        </div>
      </div>
      <div class="panel-actions">
        <button class="btn-icon" @click.stop="refresh" :class="{ loading }" title="刷新">🔄</button>
        <button class="btn-icon" @click.stop="exportData" title="导出数据">📥</button>
        <button class="btn-icon" @click.stop="handleClose" title="关闭">✕</button>
      </div>
    </div>

    <!-- 情绪卡片 - 从 emotion.ts 读取阶段信息 -->
    <div class="sentiment-card" :style="{ background: phaseGradient }">
      <div class="sentiment-main">
        <div class="sentiment-left">
          <div class="sentiment-score-circle">
            <div class="score-circle" :style="{
              background: `conic-gradient(#fff ${sentiment.overall || 0}%, rgba(255,255,255,0.2) 0)`,
              boxShadow: `0 0 20px ${phaseColor}80`,
            }">
              <span class="score-value">{{ Math.round(sentiment.overall || 0) }}</span>
            </div>
            <span class="score-label">情绪指数</span>
          </div>
          <div class="sentiment-info">
            <div class="sentiment-phase" :style="{ color: phaseColor }">
              {{ phaseIcon }} {{ sentiment.phaseName || sentiment.phase || '未知' }}
            </div>
            <div class="sentiment-risk" :class="`risk-${sentiment.riskLevel}`">
              <span class="risk-dot"></span>
              {{ sentiment.riskLevel }}风险
            </div>
            <div class="sentiment-suggestion">{{ sentiment.suggestion || '暂无建议' }}</div>
          </div>
        </div>
        <div class="sentiment-stats">
          <div class="stat-row">
            <span class="stat-label">涨停</span>
            <span class="stat-value up-text">{{ marketData.ztCount }}</span>
            <span class="stat-sub">炸板 {{ marketData.zhaban?.count || 0 }}</span>
          </div>
          <div class="stat-row">
            <span class="stat-label">跌停</span>
            <span class="stat-value down-text">{{ marketData.dtCount }}</span>
            <span class="stat-sub">封板 {{ marketData.zhaban?.fengbanRate?.toFixed(0) || 0 }}%</span>
          </div>
          <div class="stat-row">
            <span class="stat-label">连板</span>
            <span class="stat-value up-text">
              {{ marketData.limitData.yiban }}/{{ marketData.limitData.erban }}/{{
                marketData.limitData.sanban
              }}+{{ marketData.limitData.sibanPlus }}
            </span>
            <span class="stat-sub">最高 {{ marketData.limitData.sibanPlus || 0 }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 标签页 -->
    <div class="panel-tabs">
      <button class="tab-btn" :class="{ active: view === 'overview' }" @click="view = 'overview'">
        📊 市场概览
      </button>
      <button class="tab-btn" :class="{ active: view === 'limit' }" @click="view = 'limit'">
        📈 连板分析
      </button>
      <button class="tab-btn" :class="{ active: view === 'money' }" @click="view = 'money'">
        💰 资金流向
      </button>
      <button class="tab-btn" :class="{ active: view === 'plates' }" @click="view = 'plates'">
        📋 热点板块
      </button>
      <button class="tab-btn" :class="{ active: view === 'factors' }" @click="view = 'factors'">
        🌬️ 龙息因子
      </button>
    </div>

    <!-- 内容区域 -->
    <div class="panel-content" ref="contentRef">
      <!-- 加载状态 -->
      <div v-if="loading" class="loading-state">
        <div class="loading-spinner"></div>
        <span>加载市场数据...</span>
      </div>

      <!-- 错误状态 -->
      <div v-else-if="error" class="error-state">
        <span class="error-icon">⚠️</span>
        <span>{{ error }}</span>
        <button class="retry-btn" @click="loadData">重试</button>
      </div>

      <template v-else>
        <!-- 市场概览视图 -->
        <div v-if="view === 'overview'" class="overview-view">
          <!-- 情绪指标网格 -->
          <div class="metrics-grid">
            <div class="metric-item">
              <span class="metric-label">上涨家数</span>
              <span class="metric-value up-text">{{ marketData.upCount }}</span>
              <span class="metric-percent">{{ upRatio }}%</span>
            </div>
            <div class="metric-item">
              <span class="metric-label">下跌家数</span>
              <span class="metric-value down-text">{{ marketData.downCount }}</span>
              <span class="metric-percent">{{ downRatio }}%</span>
            </div>
            <div class="metric-item">
              <span class="metric-label">涨停家数</span>
              <span class="metric-value up-text">{{ marketData.ztCount }}</span>
              <span class="metric-percent">昨日 {{ marketData.yesterdayLimit?.yiban || 0 }}</span>
            </div>
            <div class="metric-item">
              <span class="metric-label">跌停家数</span>
              <span class="metric-value down-text">{{ marketData.dtCount }}</span>
              <span class="metric-percent">昨日 {{ marketData.yesterdayLimit?.sanban || 0 }}</span>
            </div>
            <div class="metric-item">
              <span class="metric-label">总成交额</span>
              <span class="metric-value">{{ formatAmount(marketData.totalAmo) }}</span>
              <span class="metric-percent" :class="marketData.amoDiff >= 0 ? 'up-text' : 'down-text'">
                {{ marketData.amoDiff >= 0 ? '+' : '' }}{{ formatAmount(marketData.amoDiff) }}
              </span>
            </div>
            <div class="metric-item">
              <span class="metric-label">量比</span>
              <span class="metric-value">{{ marketData.volumeRatio?.toFixed(2) || '--' }}</span>
              <span class="metric-percent">昨涨停 {{ formatPercent(marketData.yesterdayZtPerformance) }}</span>
            </div>
          </div>

          <!-- 涨跌比例图 -->
          <div class="ratio-section">
            <div class="ratio-header">
              <span class="ratio-title">📊 涨跌分布</span>
              <div class="ratio-values">
                <span class="up-text">上涨 {{ upRatio }}%</span>
                <span class="dot">|</span>
                <span class="down-text">下跌 {{ downRatio }}%</span>
              </div>
            </div>
            <div class="ratio-bar-container">
              <div class="ratio-bar">
                <div class="ratio-bar-up" :style="{ width: upRatio + '%' }"></div>
                <div class="ratio-bar-down" :style="{ width: downRatio + '%' }"></div>
              </div>
            </div>
          </div>

          <!-- 指数表现 -->
          <div class="indices-section">
            <div class="section-title">📈 主要指数</div>
            <div class="indices-grid">
              <div v-for="item in indexItems" :key="item.key" class="index-item">
                <span class="index-name">{{ item.name }}</span>
                <span class="index-value" :class="getChangeClass(item.value)">
                  {{ formatPercent(item.value) }}
                </span>
              </div>
            </div>
          </div>
        </div>

        <!-- 连板分析视图 -->
        <div v-if="view === 'limit'" class="limit-view">
          <!-- 连板统计卡片 -->
          <div class="limit-stats-grid">
            <div class="limit-stat-card">
              <span class="limit-label">一板</span>
              <span class="limit-value up-text">{{ marketData.limitData.yiban }}</span>
              <span class="limit-sub">昨日 {{ marketData.yesterdayLimit?.yiban || 0 }}</span>
            </div>
            <div class="limit-stat-card">
              <span class="limit-label">二板</span>
              <span class="limit-value up-text">{{ marketData.limitData.erban }}</span>
              <span class="limit-sub">晋级率 {{ erbanRate }}%</span>
            </div>
            <div class="limit-stat-card">
              <span class="limit-label">三板</span>
              <span class="limit-value up-text">{{ marketData.limitData.sanban }}</span>
              <span class="limit-sub">晋级率 {{ sanbanRate }}%</span>
            </div>
            <div class="limit-stat-card">
              <span class="limit-label">四板+</span>
              <span class="limit-value up-text">{{ marketData.limitData.sibanPlus }}</span>
              <span class="limit-sub">晋级率 {{ sibanPlusRate }}%</span>
            </div>
          </div>

          <!-- 连板分布柱状图 -->
          <div class="limit-distribution">
            <div class="section-title">📊 连板分布</div>
            <div class="limit-bars">
              <div v-for="(item, index) in limitBarData" :key="index" class="limit-bar-item">
                <div class="limit-bar" :style="{ height: item.height + 'px' }">
                  <span class="limit-bar-value">{{ item.count }}</span>
                </div>
                <span class="limit-bar-label">{{ item.label }}</span>
              </div>
            </div>
          </div>

          <!-- 炸板分析 -->
          <div class="zhaban-section">
            <div class="zhaban-header">
              <span class="zhaban-title">💥 炸板分析</span>
              <span class="zhaban-rate">{{ (marketData.zhaban?.rate || 0).toFixed(2) }}%</span>
            </div>
            <div class="zhaban-bar">
              <div class="zhaban-bar-fill" :style="{ width: (marketData.zhaban?.rate || 0) + '%' }"></div>
            </div>
            <div class="zhaban-stats">
              <span>炸板: {{ marketData.zhaban?.count || 0 }} 家</span>
              <span>封板: {{ marketData.zhaban?.ztCount || 0 }} 家</span>
              <span>封板率: {{ marketData.zhaban?.fengbanRate?.toFixed(2) || 0 }}%</span>
            </div>
          </div>

          <!-- 晋级率分析 -->
          <div class="promotion-section">
            <div class="section-title">📈 晋级率</div>
            <div class="promotion-grid">
              <div class="promotion-item">
                <span class="promotion-label">一进二</span>
                <span class="promotion-value">{{ erbanRate }}%</span>
              </div>
              <div class="promotion-item">
                <span class="promotion-label">二进三</span>
                <span class="promotion-value">{{ sanbanRate }}%</span>
              </div>
              <div class="promotion-item">
                <span class="promotion-label">三进四</span>
                <span class="promotion-value">{{ sibanPlusRate }}%</span>
              </div>
            </div>
          </div>
        </div>

        <!-- 资金流向视图 -->
        <div v-if="view === 'money'" class="money-view">
          <!-- 主力资金 -->
          <div class="money-section">
            <div class="section-title">💰 主力资金</div>
            <div class="money-main">
              <div class="money-item large">
                <span class="money-label">主力净额</span>
                <span class="money-value" :class="(marketData.moneyFlow?.main || 0) >= 0 ? 'up-text' : 'down-text'">
                  {{ formatAmount(marketData.moneyFlow?.main) }}
                </span>
              </div>
              <div class="money-item">
                <span class="money-label">散户净额</span>
                <span class="money-value" :class="(marketData.moneyFlow?.retail || 0) >= 0 ? 'up-text' : 'down-text'">
                  {{ formatAmount(marketData.moneyFlow?.retail) }}
                </span>
              </div>
            </div>
          </div>

          <!-- 资金流向图 -->
          <div class="flow-section">
            <div class="section-title">📊 资金流向比例</div>
            <div class="flow-chart">
              <div class="flow-bar">
                <div class="flow-bar-in" :style="{
                  width: getFlowPercent(marketData.moneyFlow?.main, marketData.totalAmo) + '%',
                }">
                  <span class="flow-label" v-if="getFlowPercent(marketData.moneyFlow?.main, marketData.totalAmo) > 10">
                    主力
                    {{
                      getFlowPercent(marketData.moneyFlow?.main, marketData.totalAmo).toFixed(1)
                    }}%
                  </span>
                </div>
                <div class="flow-bar-out" :style="{
                  width: getFlowPercent(marketData.moneyFlow?.retail, marketData.totalAmo) + '%',
                }">
                  <span class="flow-label"
                    v-if="getFlowPercent(marketData.moneyFlow?.retail, marketData.totalAmo) > 10">
                    散户
                    {{
                      getFlowPercent(marketData.moneyFlow?.retail, marketData.totalAmo).toFixed(1)
                    }}%
                  </span>
                </div>
              </div>
            </div>
          </div>

          <!-- 超大单资金 -->
          <div class="super-money-section">
            <div class="section-title">💎 超大单资金</div>
            <div class="super-money-grid">
              <div class="super-money-item">
                <span class="label">超大单净额</span>
                <span class="value" :class="(marketData.cddje || 0) >= 0 ? 'up-text' : 'down-text'">
                  {{ formatAmount(marketData.cddje) }}
                </span>
              </div>
              <div class="super-money-item">
                <span class="label">超大单占比</span>
                <span class="value">{{ marketData.cddjzb?.toFixed(2) || 0 }}%</span>
              </div>
            </div>
          </div>
        </div>

        <!-- 热点板块视图 -->
        <div v-if="view === 'plates'" class="plates-view">
          <div class="plates-list">
            <div v-for="plate in hotPlates" :key="plate.id" class="plate-item"
              :class="{ active: selectedPlate === plate.id }" @click="selectPlate(plate.id)">
              <div class="plate-header">
                <span class="plate-name">{{ plate.name }}</span>
                <span class="plate-change" :class="plate.pcp >= 0 ? 'up-text' : 'down-text'">
                  {{ plate.pcp > 0 ? '+' : '' }}{{ plate.pcp.toFixed(2) }}%
                </span>
                <span class="plate-count">{{ plate.stockCount }}家</span>
              </div>
              <div class="plate-desc">{{ plate.desc }}</div>
              <div class="plate-stocks" v-if="selectedPlate === plate.id">
                <div v-for="stock in (plate.stocks as any[])" :key="stock.code" class="plate-stock">
                  <span class="stock-code">{{ stock.code }}</span>
                  <span class="stock-name">{{ stock.name }}</span>
                  <span class="stock-change" :class="(stock.change || 0) >= 0 ? 'up-text' : 'down-text'">
                    {{ (stock.change || 0) > 0 ? '+' : '' }}{{ (stock.change || 0).toFixed(2) }}%
                  </span>
                </div>
              </div>
            </div>
            <div v-if="hotPlates.length === 0" class="empty-state">暂无热点板块数据</div>
          </div>
        </div>

        <!-- 龙息因子视图 -->
        <div v-if="view === 'factors'" class="factors-view">
          <div class="factors-header">
            <h4>🔥 龙息因子 ({{ breathFactors.length }})</h4>
            <span class="factor-tip">得分越高表示情绪越好</span>
          </div>

          <!-- 总分显示卡片 -->
          <div class="total-score-card">
            <div class="total-header">
              <span class="total-icon">📊</span>
              <span class="total-title">市场情绪总分</span>
            </div>
            <div class="total-value" :style="{ color: getTotalScoreColor(sentiment.overall) }">
              {{ Math.round(sentiment.overall) }}/100分
            </div>
            <div class="total-breakdown">
              <span>自研因子: {{ selfTotalScore }}/86分</span>
              <span>通达信情绪: {{ tdxScoreWeighted.toFixed(2) }}/14分</span>
            </div>
            <div class="total-bar">
              <div class="total-bar-fill" :style="{ width: sentiment.overall + '%' }"></div>
            </div>
          </div>

          <!-- 因子卡片网格 -->
          <div class="factors-grid" v-if="breathFactors.length > 0">
            <div v-for="factor in breathFactors" :key="factor.id" class="factor-card">
              <div class="factor-header">
                <span class="factor-name">{{ factor.name }}</span>
                <span class="factor-max">权重{{ factor.weight }}%</span>
              </div>
              <!-- 原始得分 -->
              <div class="factor-score" :style="{ color: getFactorScoreColor(factor.score, factor.maxScore) }">
                {{ factor.score }}/{{ factor.maxScore }}分
              </div>
              <div class="factor-raw" :style="{ color: getFactorValueColor(factor.rawValue, factor.id) }">
                {{ formatRawValue(factor.rawValue, factor.unit) }}
              </div>
              <div class="factor-desc">{{ factor.description }}</div>
              <div class="factor-bar">
                <div class="factor-bar-fill" :style="{
                  width: (factor.score / factor.maxScore * 100) + '%',
                  background: getFactorScoreGradient(factor.score, factor.maxScore)
                }"></div>
              </div>
              <!-- 加权贡献 -->
              <div class="factor-contribution">
                贡献: {{ ((factor.score / factor.maxScore) * factor.weight).toFixed(2) }}/{{ factor.weight }}分
              </div>
            </div>
          </div>

          <!-- 权重分布 -->
          <div class="weights-section" v-if="breathFactors.length > 0">
            <div class="section-title">⚖️ 权重分布</div>
            <div class="weights-grid">
              <div v-for="factor in breathFactors" :key="factor.id" class="weight-item">
                <span class="weight-name">{{ factor.name }}</span>
                <div class="weight-bar-container">
                  <div class="weight-bar">
                    <div class="weight-bar-fill" :style="{
                      width: factor.weight + '%',
                      background: 'linear-gradient(90deg, #ffa502, #ffd700)'
                    }"></div>
                  </div>
                </div>
                <span class="weight-value">{{ factor.weight.toFixed(2) }}%</span>
              </div>
              <div class="weight-item total">
                <span class="weight-name">总计</span>
                <div class="weight-bar-container">
                  <div class="weight-bar">
                    <div class="weight-bar-fill" :style="{
                      width: totalWeightForBar + '%',
                      background: 'linear-gradient(90deg, #ffa502, #ffd700)'
                    }"></div>
                  </div>
                </div>
                <span class="weight-value">{{ totalWeightForBar.toFixed(2) }}%</span>
              </div>
            </div>
          </div>

          <!-- 操作建议卡片 -->
          <div class="suggestions-card">
            <div class="suggestions-header">
              <span class="suggestions-icon">💡</span>
              <span class="suggestions-title">操作建议</span>
            </div>
            <ul class="suggestions-list">
              <li v-for="(suggestion, index) in suggestions" :key="index">
                {{ suggestion }}
              </li>
            </ul>
          </div>
        </div>
      </template>
    </div>

    <!-- 底部 -->
    <div class="panel-footer">
      <span class="update-time">更新: {{ formatTime(marketData.timestamp) }}</span>
      <span class="dot">•</span>
      <span class="source-info">数据源: 通达信/选股通</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { dataLayer } from '@/services/DataLayer'
import { dragonBreathAnalyzer } from '@/services/DragonBreathAnalyzer'
import {
  EMOTION_PHASES,
  EMOTION_PHASE_BY_NAME,
  EMOTION_SCORE_CONFIG,
} from '@/types/emotion'
import { usePanel } from '@/composables/usePanel'

interface FactorItem {
  id: string
  name: string
  rawValue: number
  score: number
  weight: number
  maxScore: number
  unit: string
  description: string
}

const props = defineProps<{
  visible: boolean
  triggerRect?: DOMRect
}>()

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'close'): void
}>()

// ========== 面板定位 ==========
function handleClose() {
  emit('update:visible', false)
  emit('close')
}

const { panelRef, panelStyle } = usePanel({
  name: 'DragonBreathPanel',
  visible: props.visible,
  triggerRect: props.triggerRect,
  triggerSelectors: ['[title*="龙息分析"]'],
  onClose: handleClose,
})

// ========== 状态 ==========
const loading = ref(false)
const error = ref<string | null>(null)
const view = ref<'overview' | 'limit' | 'money' | 'plates' | 'factors'>('factors')
const selectedPlate = ref<number | null>(null)
const contentRef = ref<HTMLElement | null>(null)
const unsubscribeFns: (() => void)[] = []



// ========== 从 dataLayer 获取数据 ==========

// 市场数据
const marketData = computed(() => {
  const breath = (dataLayer as any).state?.analysis?.breath
  const marketData = breath?.marketData || {}

  return {
    upCount: marketData.upCount ?? 0,
    downCount: marketData.downCount ?? 0,
    ztCount: marketData.ztCount ?? 0,
    dtCount: marketData.dtCount ?? 0,
    largeCapChange: marketData.largeCapChange ?? 0,
    microCapChange: marketData.microCapChange ?? 0,
    passRate: marketData.passRate ?? { to2: 0, to3: 0, to4: 0 },
    limitData: marketData.limitData ?? { yiban: 0, erban: 0, sanban: 0, sibanPlus: 0 },
    yesterdayLimit: marketData.yesterdayLimit ?? {},
    zhaban: marketData.zhaban ?? {},
    moneyFlow: marketData.moneyFlow ?? {},
    totalAmo: marketData.totalAmo ?? 0,
    amoDiff: marketData.amoDiff ?? 0,
    volumeRatio: marketData.volumeRatio ?? 0,
    indices: marketData.indices ?? {},
    cddje: marketData.cddje ?? 0,
    cddjzb: marketData.cddjzb ?? 0,
    yesterdayZtPerformance: marketData.yesterdayZtPerformance,
    timestamp: marketData.timestamp ?? Date.now(),
  }
})

// 情绪数据
const sentiment = computed(() => {
  const breath = (dataLayer as any).state?.analysis?.breath
  const sent = breath?.sentiment || {}

  return {
    phase: sent.phase || 'oscillation',
    phaseName: sent.phaseName || '震荡期',
    overall: sent.overall ?? 50,
    riskLevel: sent.riskLevel || '中',
    suggestion: sent.suggestion || '观望为主',
  }
})

// 龙息因子数据（9个因子统一显示）
const breathFactors = computed(() => {
  const breath = (dataLayer as any).state?.analysis?.breath
  const factors = breath?.factors || []

  // ✅ 直接从配置文件读取，不再重复定义
  const factorConfig = EMOTION_SCORE_CONFIG.factors

  const factorNameMap: Record<string, string> = {
    promotionRate: '晋级率',
    yesterdayZtAvgChange: '昨日涨停表现',
    ztCount: '涨停数',
    dtCount: '跌停数',
    zhabanRate: '炸板率',
    maxContinuousDays: '连板高度',
    upDownRatio: '涨跌比',
    volumeRatio: '量比',
    tdxEmotion: '通达信情绪',
  }

  const factorUnitMap: Record<string, string> = {
    promotionRate: '%',
    yesterdayZtAvgChange: '%',
    ztCount: '家',
    dtCount: '家',
    zhabanRate: '%',
    maxContinuousDays: '天',
    upDownRatio: '倍',
    volumeRatio: '',
    tdxEmotion: '',
  }

  const factorDescMap: Record<string, string> = {
    promotionRate: '昨日涨停今日继续涨停的比例（加权平均）',
    yesterdayZtAvgChange: '昨日涨停股今日平均涨幅',
    ztCount: '当日涨停家数，反映进攻意愿',
    dtCount: '当日跌停家数，反映市场风险',
    zhabanRate: '炸板率越低，涨停质量越高',
    maxContinuousDays: '市场最高连板天数',
    upDownRatio: '上涨家数/下跌家数',
    volumeRatio: '今日成交量/昨日成交量',
    tdxEmotion: '通达信专业情绪指标',
  }

  return factors.map((factor: any) => {
    const config = factorConfig[factor.id]

    return {
      id: factor.id,
      name: factorNameMap[factor.id] || factor.name || '未知因子',
      rawValue: factor.rawValue ?? 0,
      score: factor.score ?? 0,
      maxScore: config?.maxScore ?? 10,  // 从配置文件读取
      weight: config?.weight ?? 10,       // 从配置文件读取
      unit: factorUnitMap[factor.id] || '',
      description: factorDescMap[factor.id] || factor.description || '暂无描述',
    }
  })
})

// 通达信情绪得分（按权重计算）
const tdxScoreWeighted = computed(() => {
  const factor = breathFactors.value.find((f: any) => f.id === 'tdxEmotion')
  if (!factor) return 0
  if (factor.maxScore === 0) return 0
  return (factor.score / factor.maxScore) * factor.weight
})

// 自研因子总分（按权重计算）
const selfTotalScore = computed(() => {
  let total = 0
  for (const factor of breathFactors.value) {
    if (factor.id !== 'tdxEmotion') {
      if (factor.maxScore > 0) {
        total += (factor.score / factor.maxScore) * factor.weight
      }
    }
  }
  return Math.round(total)
})

const totalWeightForBar = computed(() => {
  return breathFactors.value.reduce((sum: number, f: FactorItem) => sum + (f.weight || 0), 0)
})

// 热点板块
const hotPlates = computed(() => {
  const hotThemes = dataLayer.getHotThemes?.() || []
  return hotThemes.slice(0, 5).map((theme: any, index: number) => ({
    id: theme.id || index,
    name: theme.name,
    pcp: theme.heatScore > 3000 ? 3.5 : theme.heatScore > 1500 ? 1.5 : -0.5,
    stockCount: theme.stockCount || 0,
    desc: getThemeDescription(theme),
    stocks: [],
  }))
})

// ========== 从 emotion.ts 获取阶段信息 ==========
const currentPhase = computed(() => {
  const phaseName = sentiment.value.phaseName
  return EMOTION_PHASE_BY_NAME[phaseName] || EMOTION_PHASES.OSCILLATION
})

const phaseColor = computed(() => currentPhase.value?.color || '#95a5a6')
const phaseGradient = computed(() => currentPhase.value?.gradient || 'linear-gradient(135deg, #2c3e50, #34495e)')
const phaseIcon = computed(() => currentPhase.value?.icon || '🌬️')

// ========== 计算属性 ==========
const totalStocks = computed(() => marketData.value.upCount + marketData.value.downCount)
const upRatio = computed(() =>
  totalStocks.value ? ((marketData.value.upCount / totalStocks.value) * 100).toFixed(2) : '0',
)
const downRatio = computed(() =>
  totalStocks.value ? ((marketData.value.downCount / totalStocks.value) * 100).toFixed(2) : '0',
)

const erbanRate = computed(() => {
  if (!marketData.value.yesterdayLimit?.yiban) return '0.00'
  return ((marketData.value.limitData.erban / marketData.value.yesterdayLimit.yiban) * 100).toFixed(2)
})

const sanbanRate = computed(() => {
  if (!marketData.value.yesterdayLimit?.erban) return '0.00'
  return ((marketData.value.limitData.sanban / marketData.value.yesterdayLimit.erban) * 100).toFixed(2)
})

const sibanPlusRate = computed(() => {
  if (!marketData.value.yesterdayLimit?.sanban) return '0.00'
  return ((marketData.value.limitData.sibanPlus / marketData.value.yesterdayLimit.sanban) * 100).toFixed(2)
})

// 连板柱状图数据
const limitBarData = computed(() => {
  const maxCount = Math.max(
    marketData.value.limitData.yiban,
    marketData.value.limitData.erban,
    marketData.value.limitData.sanban,
    marketData.value.limitData.sibanPlus,
  )

  return [
    {
      label: '一板',
      count: marketData.value.limitData.yiban,
      height: maxCount > 0 ? (marketData.value.limitData.yiban / maxCount) * 60 : 20,
    },
    {
      label: '二板',
      count: marketData.value.limitData.erban,
      height: maxCount > 0 ? (marketData.value.limitData.erban / maxCount) * 60 : 20,
    },
    {
      label: '三板',
      count: marketData.value.limitData.sanban,
      height: maxCount > 0 ? (marketData.value.limitData.sanban / maxCount) * 60 : 20,
    },
    {
      label: '四板+',
      count: marketData.value.limitData.sibanPlus,
      height: maxCount > 0 ? (marketData.value.limitData.sibanPlus / maxCount) * 60 : 20,
    },
  ]
})

// 操作建议
const suggestions = computed(() => {
  const list: string[] = []

  if (currentPhase.value) {
    list.push(`${currentPhase.value.icon} ${currentPhase.value.suggestion}`)
  }

  const promotionRate = breathFactors.value.find((f: FactorItem) => f.id === 'promotionRate')?.score || 0
  const ztCount = marketData.value.ztCount
  const dtCount = marketData.value.dtCount
  const zhabanRate = marketData.value.zhaban?.rate || 0

  if (promotionRate >= 8) {
    list.push('📈 晋级率得分≥8分，接力情绪极强')
  } else if (promotionRate >= 6) {
    list.push('📊 晋级率得分≥6分，接力情绪良好')
  } else if (promotionRate < 4) {
    list.push('📉 晋级率得分不足4分，接力情绪冰点')
  }

  if (ztCount > 80) {
    list.push('📈 涨停家数超过80家，市场极度活跃')
  } else if (ztCount > 50) {
    list.push('📊 涨停家数超过50家，市场情绪较好')
  } else if (ztCount < 20) {
    list.push('📉 涨停家数不足20家，市场情绪低迷')
  }

  if (dtCount > 30) {
    list.push('⚠️ 跌停家数超过30家，市场风险较大')
  } else if (dtCount > 10) {
    list.push('📉 跌停家数超过10家，亏钱效应明显')
  }

  if (zhabanRate > 50) {
    list.push('💥 炸板率超过50%，追高风险极大')
  } else if (zhabanRate > 40) {
    list.push('⚠️ 炸板率超过40%，打板需谨慎')
  } else if (zhabanRate < 20) {
    list.push('✅ 炸板率低于20%，封板质量较好')
  }

  return [...new Set(list)].slice(0, 5)
})

// ========== 工具函数 ==========
function getThemeDescription(theme: any): string {
  if (theme.heatScore > 3000) return '🔥 热门题材，多股涨停'
  if (theme.heatScore > 1500) return '🌟 题材活跃，资金关注'
  if (theme.momentum > 20) return '📈 题材升温，趋势向上'
  if (theme.momentum < -20) return '📉 题材降温，注意风险'
  return '⚖️ 题材平稳，震荡为主'
}

function getFactorScoreColor(score: number, maxScore: number = 10): string {
  const percent = (score / maxScore) * 100
  if (percent >= 80) return '#ff4757'
  if (percent >= 60) return '#ffa502'
  if (percent >= 40) return '#3498db'
  return '#7f8c8d'
}

function getFactorScoreGradient(score: number, maxScore: number = 10): string {
  const percent = (score / maxScore) * 100
  if (percent >= 80) return 'linear-gradient(90deg, #ff4757, #ff6b81)'
  if (percent >= 60) return 'linear-gradient(90deg, #ffa502, #ffb347)'
  if (percent >= 40) return 'linear-gradient(90deg, #3498db, #5dade2)'
  return 'linear-gradient(90deg, #7f8c8d, #95a5a6)'
}

function getFactorValueColor(value: number, factorId?: string): string {
  if (!factorId) {
    if (value >= 70) return '#ff4757'
    if (value >= 50) return '#ffa502'
    if (value >= 30) return '#3498db'
    return '#7f8c8d'
  }

  if (factorId === 'ztCount') {
    if (value >= 80) return '#ff4757'
    if (value >= 50) return '#ffa502'
    if (value >= 30) return '#3498db'
    return '#7f8c8d'
  }

  if (factorId === 'dtCount') {
    if (value <= 5) return '#2ed573'
    if (value <= 10) return '#ffa502'
    if (value <= 20) return '#3498db'
    return '#ff4757'
  }

  if (factorId === 'zhabanRate') {
    if (value <= 20) return '#2ed573'
    if (value <= 30) return '#3498db'
    if (value <= 40) return '#ffa502'
    return '#ff4757'
  }

  if (factorId === 'promotionRate' || factorId === 'yesterdayZtAvgChange') {
    if (value >= 40) return '#ff4757'
    if (value >= 30) return '#ffa502'
    if (value >= 20) return '#3498db'
    return '#7f8c8d'
  }

  if (factorId === 'maxContinuousDays') {
    if (value >= 5) return '#ff4757'
    if (value >= 4) return '#ffa502'
    if (value >= 3) return '#3498db'
    return '#7f8c8d'
  }

  if (factorId === 'upDownRatio') {
    if (value >= 2) return '#ff4757'
    if (value >= 1.5) return '#ffa502'
    if (value >= 1) return '#3498db'
    return '#7f8c8d'
  }

  if (factorId === 'volumeRatio') {
    if (value >= 1.2) return '#ff4757'
    if (value >= 1.0) return '#ffa502'
    if (value >= 0.8) return '#3498db'
    return '#7f8c8d'
  }

  if (value >= 70) return '#ff4757'
  if (value >= 50) return '#ffa502'
  if (value >= 30) return '#3498db'
  return '#7f8c8d'
}

function getTotalScoreColor(score: number): string {
  if (score >= 80) return '#ff4757'
  if (score >= 60) return '#ffa502'
  if (score >= 40) return '#3498db'
  return '#7f8c8d'
}

function formatRawValue(value: number, unit: string): string {
  if (value === undefined || value === null) return '--'
  if (unit === '%') return value.toFixed(2) + '%'
  if (unit === '家') return Math.round(value) + '家'
  if (unit === '天') return Math.round(value) + '天'
  if (unit === '倍') return value.toFixed(0) + '倍'
  return value.toFixed(2)
}

function selectPlate(plateId: number) {
  selectedPlate.value = selectedPlate.value === plateId ? null : plateId
}

function loadData() {
  // 纯响应式，不需要手动加载
}

function refresh() {
  dragonBreathAnalyzer.refresh()
}

function exportData() {
  const exportData = {
    exportTime: new Date().toISOString(),
    sentiment: sentiment.value,
    marketData: marketData.value,
    factors: breathFactors.value,
    hotPlates: hotPlates.value,
    suggestions: suggestions.value,
  }

  const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `龙息数据_${new Date().toISOString().slice(0, 10)}.json`
  a.click()
  URL.revokeObjectURL(url)
}

function formatNumber(num: number): string {
  if (num >= 10000) return (num / 10000).toFixed(2) + '万'
  return num.toString()
}

function formatAmount(amount?: number): string {
  if (!amount && amount !== 0) return '--'
  const yi = Math.abs(amount) / 100000000
  const sign = amount >= 0 ? '' : '-'
  if (yi >= 10000) return sign + (yi / 10000).toFixed(2) + '万亿'
  return sign + yi.toFixed(0) + '亿'
}

function formatPercent(value?: number): string {
  if (value === undefined || value === null) return '--'
  return (value > 0 ? '+' : '') + value.toFixed(2) + '%'
}

function getChangeClass(value?: number): string {
  if (!value) return ''
  return value > 0 ? 'up-text' : value < 0 ? 'down-text' : ''
}

function getFlowPercent(value: number, total: number): number {
  if (!total || total === 0) return 0
  return Math.min(100, (Math.abs(value) / total) * 100)
}

function formatTime(timestamp: number): string {
  if (!timestamp) return '--:--:--'
  const date = new Date(timestamp)
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}:${String(date.getSeconds()).padStart(2, '0')}`
}

// 计算属性：所有指数数据（包含名称和值）
const indexItems = computed(() => {
  const items: Array<{ name: string; value: number; key: string }> = []

  // 从 marketData.indices 中获取
  const indices = marketData.value.indices
  if (indices && typeof indices === 'object') {
    Object.entries(indices).forEach(([key, value]) => {

      // 检查 value 的结构
      if (value && typeof value === 'object' && 'change' in value) {
        const change = (value as any).change
        if (change !== undefined && change !== null) {
          items.push({
            key,
            name: getIndexName(key),
            value: change
          })
        }
      }
    })
  }

  // 添加大票
  const largeCapChange = marketData.value.largeCapChange
  if (largeCapChange !== undefined && largeCapChange !== null) {
    console.log('添加大票:', largeCapChange)
    items.push({
      key: 'largeCapChange',
      name: '大票',
      value: largeCapChange
    })
  }

  // 添加微盘
  const microCapChange = marketData.value.microCapChange
  if (microCapChange !== undefined && microCapChange !== null) {
    console.log('添加微盘:', microCapChange)
    items.push({
      key: 'microCapChange',
      name: '微盘',
      value: microCapChange
    })
  }

  console.log('[DragonBreathPanel] indexItems 结果:', items)
  return items
})

// 指数名称映射
function getIndexName(key: string): string {
  const names: Record<string, string> = {
    sh: '上证指数',
    hs300: '沪深300',
    zz500: '中证500',
    zz1000: '中证1000',
    largeCapChange: '大票',
    microCapChange: '微盘',
    bjs: '北证',
  }
  return names[key] || key
}

// ========== 生命周期 ==========
onMounted(() => {
  console.log('[DragonBreathPanel] 挂载')

  const unsubBreath = dataLayer.subscribe('analysis.breath', () => { })
  unsubscribeFns.push(unsubBreath)

  const unsubHotThemes = dataLayer.subscribe('theme.hotThemes', () => { })
  unsubscribeFns.push(unsubHotThemes)
})

onUnmounted(() => {
  console.log('[DragonBreathPanel] 卸载')
  unsubscribeFns.forEach(fn => fn())
})
</script>
<style scoped>
:root {
  --color-red: #ff4757;
  --color-orange: #ffa502;
  --color-blue: #3498db;
  --color-green: #2ed573;
  --color-purple: #9b59b6;
  --color-gray: #7f8c8d;
  --color-highlight: #ffa502;
}

.breath-panel {
  position: fixed;
  width: 520px;
  max-width: calc(100vw - 40px);
  max-height: 80vh;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
  z-index: 10006;
  font-size: 12px;
  overflow: hidden;
  backdrop-filter: blur(10px);
}

.factor-unit {
  font-size: 10px;
  color: var(--text-secondary);
  margin-left: 2px;
}

/* 空状态 */
.empty-state {
  grid-column: span 2;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 48px;
  color: var(--text-secondary);
  font-size: 12px;
  gap: 12px;
  background: var(--bg-secondary);
  border-radius: 12px;
  border: 1px dashed var(--border-color);
}

.empty-icon {
  font-size: 40px;
  opacity: 0.5;
  filter: grayscale(0.5);
}

/* 百分比颜色已经在JS中动态设置，这里只需要基础样式 */
.weight-value,
.factor-weight,
.score-value {
  font-feature-settings: 'tnum';
}

.breath-panel {
  position: fixed;
  width: 520px;
  max-width: calc(100vw - 40px);
  max-height: 80vh;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
  z-index: 10006;
  font-size: 12px;
  overflow: hidden;
  backdrop-filter: blur(10px);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.stats-badge {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 2px 8px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 20px;
  font-size: 10px;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-header);
}

.panel-header h3 {
  margin: 0;
  font-size: 15px;
  color: #ff7f50;
}

.panel-actions {
  display: flex;
  gap: 6px;
}

.btn-icon {
  width: 28px;
  height: 28px;
  border: 1px solid var(--border-color);
  background: transparent;
  border-radius: 6px;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
}

.btn-icon:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
  border-color: #ff7f50;
}

.btn-icon.active {
  color: #2ed573;
  border-color: #2ed573;
}

.btn-icon.loading {
  animation: pulse 1s infinite;
}

.sentiment-stats {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 160px;
  background: rgba(0, 0, 0, 0.15);
  padding: 10px 12px;
  border-radius: 8px;
}

.stat-row {
  display: flex;
  align-items: center;
  gap: 8px;
  justify-content: space-between;
}

.stat-label {
  width: 40px;
  font-size: 11px;
  opacity: 0.8;
  color: white;
}

.stat-value {
  font-weight: bold;
  min-width: 40px;
  text-align: right;
  font-size: 14px;
}

.stat-value.up-text {
  color: #ff4757;
}

.stat-value.down-text {
  color: #2ed573;
}

.stat-sub {
  font-size: 9px;
  opacity: 0.7;
  min-width: 45px;
  text-align: right;
  color: rgba(255, 255, 255, 0.7);
}

/* 情绪卡片 */
.sentiment-card {
  margin: 16px;
  padding: 16px;
  border-radius: 12px;
  color: white;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
}

.sentiment-main {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
}

.sentiment-left {
  display: flex;
  align-items: center;
  gap: 16px;
  flex: 1;
}

.sentiment-score-circle {
  display: flex;
  flex-direction: column;
  align-items: center;
  flex-shrink: 0;
}

.score-circle {
  width: 60px;
  height: 60px;
  border-radius: 30px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 4px;
  background: rgba(255, 255, 255, 0.2);
  transition: box-shadow 0.3s;
}

.score-value {
  width: 50px;
  height: 50px;
  background: rgba(255, 255, 255, 0.3);
  border-radius: 25px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  font-weight: bold;
  color: white;
}

.score-label {
  font-size: 10px;
  opacity: 0.8;
}

.sentiment-info {
  flex: 1;
}

.sentiment-phase {
  font-size: 18px;
  font-weight: bold;
  margin-bottom: 4px;
}

.sentiment-risk {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 12px;
  background: rgba(0, 0, 0, 0.2);
  margin-bottom: 6px;
}

.risk-dot {
  width: 6px;
  height: 6px;
  border-radius: 3px;
}

.risk-低 .risk-dot {
  background: #2ed573;
}

.risk-中 .risk-dot {
  background: #ffa502;
}

.risk-高 .risk-dot {
  background: #ff4757;
}

.sentiment-suggestion {
  font-size: 12px;
  opacity: 0.9;
}

/* 标签页 */
.panel-tabs {
  display: flex;
  gap: 4px;
  padding: 0 16px 12px;
}

.tab-btn {
  flex: 1;
  padding: 8px 4px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  border-radius: 8px;
  font-size: 11px;
  transition: all 0.2s;
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

.panel-content {
  padding: 0 16px 16px;
  max-height: calc(80vh - 240px);
  overflow-y: auto;
}

/* 市场概览 - 6宫格 */
.metrics-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  margin-bottom: 16px;
}

.metric-item {
  background: var(--bg-secondary);
  border-radius: 8px;
  padding: 10px;
  text-align: center;
  border: 1px solid var(--border-color);
}

.metric-label {
  display: block;
  font-size: 10px;
  color: var(--text-secondary);
  margin-bottom: 4px;
}

.metric-value {
  display: block;
  font-size: 18px;
  font-weight: bold;
  line-height: 1.2;
  margin-bottom: 2px;
}

.metric-percent {
  font-size: 9px;
  color: var(--text-secondary);
}

/* 涨跌比例图 */
.ratio-section {
  background: var(--bg-secondary);
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 16px;
  border: 1px solid var(--border-color);
}

.ratio-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

.ratio-title {
  font-size: 12px;
  color: var(--text-secondary);
}

.ratio-values {
  display: flex;
  gap: 8px;
  font-size: 11px;
}

.dot {
  opacity: 0.3;
}

.ratio-bar-container {
  background: var(--bg-primary);
  border-radius: 4px;
  overflow: hidden;
}

.ratio-bar {
  display: flex;
  height: 8px;
  background: var(--bg-primary);
}

.ratio-bar-up {
  height: 100%;
  background: linear-gradient(90deg, #ff4757, #ff6b81);
  transition: width 0.3s;
}

.ratio-bar-down {
  height: 100%;
  background: linear-gradient(90deg, #2ed573, #7bed9f);
  transition: width 0.3s;
}

/* 指数表现 */
.indices-section {
  background: var(--bg-secondary);
  border-radius: 8px;
  padding: 12px;
  border: 1px solid var(--border-color);
}

.section-title {
  font-size: 12px;
  font-weight: bold;
  margin-bottom: 12px;
  color: #ff7f50;
}

.indices-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
}

.index-item {
  background: var(--bg-primary);
  border-radius: 6px;
  padding: 6px;
  text-align: center;
}

.index-name {
  display: block;
  font-size: 9px;
  color: var(--text-secondary);
  margin-bottom: 2px;
}

.index-value {
  font-size: 11px;
  font-weight: bold;
}

/* 连板统计卡片 */
.limit-stats-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
  margin-bottom: 16px;
}

.limit-stat-card {
  background: var(--bg-secondary);
  border-radius: 8px;
  padding: 10px;
  text-align: center;
  border: 1px solid var(--border-color);
}

.limit-label {
  display: block;
  font-size: 10px;
  color: var(--text-secondary);
  margin-bottom: 4px;
}

.limit-value {
  display: block;
  font-size: 16px;
  font-weight: bold;
  margin-bottom: 2px;
}

.limit-sub {
  font-size: 9px;
  color: var(--text-secondary);
}

/* 连板分布柱状图 */
.limit-distribution {
  background: var(--bg-secondary);
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 16px;
  border: 1px solid var(--border-color);
}

.limit-bars {
  display: flex;
  justify-content: space-around;
  align-items: flex-end;
  height: 100px;
  padding: 10px 0;
}

.limit-bar-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 40px;
}

.limit-bar {
  width: 30px;
  background: linear-gradient(180deg, #ff7f50, #ff4757);
  border-radius: 4px 4px 0 0;
  position: relative;
  margin-bottom: 8px;
  transition: height 0.3s;
}

.limit-bar-value {
  position: absolute;
  top: -16px;
  left: 50%;
  transform: translateX(-50%);
  font-size: 10px;
  color: var(--text-secondary);
}

.limit-bar-label {
  font-size: 10px;
  color: var(--text-secondary);
}

/* 炸板分析 */
.zhaban-section {
  background: var(--bg-secondary);
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 16px;
  border: 1px solid var(--border-color);
}

.zhaban-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.zhaban-title {
  font-size: 12px;
  font-weight: bold;
  color: #ff7f50;
}

.zhaban-rate {
  font-size: 16px;
  font-weight: bold;
  color: #ff4757;
}

.zhaban-bar {
  height: 6px;
  background: var(--bg-primary);
  border-radius: 3px;
  overflow: hidden;
  margin-bottom: 8px;
}

.zhaban-bar-fill {
  height: 100%;
  background: linear-gradient(90deg, #ff7f50, #ff4757);
  transition: width 0.3s;
}

.zhaban-stats {
  display: flex;
  justify-content: space-between;
  font-size: 10px;
  color: var(--text-secondary);
}

/* 晋级率 */
.promotion-section {
  background: var(--bg-secondary);
  border-radius: 8px;
  padding: 12px;
  border: 1px solid var(--border-color);
}

.promotion-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
}

.promotion-item {
  background: var(--bg-primary);
  border-radius: 6px;
  padding: 8px;
  text-align: center;
}

.promotion-label {
  display: block;
  font-size: 10px;
  color: var(--text-secondary);
  margin-bottom: 4px;
}

.promotion-value {
  font-size: 14px;
  font-weight: bold;
  color: var(--color-highlight);
}

/* 资金流向 */
.money-section {
  background: var(--bg-secondary);
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 16px;
  border: 1px solid var(--border-color);
}

.money-main {
  display: flex;
  gap: 12px;
}

.money-item {
  flex: 1;
  background: var(--bg-primary);
  border-radius: 6px;
  padding: 10px;
}

.money-item.large {
  flex: 2;
}

.money-label {
  display: block;
  font-size: 10px;
  color: var(--text-secondary);
  margin-bottom: 4px;
}

.money-value {
  font-size: 14px;
  font-weight: bold;
}

/* 资金流向图 */
.flow-section {
  background: var(--bg-secondary);
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 16px;
  border: 1px solid var(--border-color);
}

.flow-bar {
  display: flex;
  height: 30px;
  background: var(--bg-primary);
  border-radius: 15px;
  overflow: hidden;
}

.flow-bar-in {
  height: 100%;
  background: linear-gradient(90deg, #ff4757, #ff6b81);
  display: flex;
  align-items: center;
  justify-content: flex-end;
  padding-right: 8px;
  transition: width 0.3s;
}

.flow-bar-out {
  height: 100%;
  background: linear-gradient(90deg, #3498db, #5dade2);
  display: flex;
  align-items: center;
  padding-left: 8px;
  transition: width 0.3s;
}

.flow-label {
  color: white;
  font-size: 10px;
  font-weight: bold;
  white-space: nowrap;
}

/* 超大单资金 */
.super-money-section {
  background: var(--bg-secondary);
  border-radius: 8px;
  padding: 12px;
  border: 1px solid var(--border-color);
}

.super-money-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 8px;
}

.super-money-item {
  background: var(--bg-primary);
  border-radius: 6px;
  padding: 8px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.super-money-item .label {
  font-size: 10px;
  color: var(--text-secondary);
}

.super-money-item .value {
  font-size: 12px;
  font-weight: bold;
}

/* 热点板块 */
.plates-view {
  height: 100%;
}

.plates-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.plate-item {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 10px;
  cursor: pointer;
  transition: all 0.2s;
}

.plate-item:hover {
  background: var(--bg-hover);
  border-color: var(--color-highlight);
}

.plate-item.active {
  border-color: var(--color-highlight);
  background: var(--bg-hover);
}

.plate-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.plate-name {
  font-weight: bold;
  color: var(--text-title);
  font-size: 12px;
}

.plate-change {
  font-size: 11px;
  font-weight: bold;
  margin-left: auto;
}

.plate-count {
  font-size: 10px;
  color: var(--text-secondary);
  background: var(--bg-primary);
  padding: 2px 6px;
  border-radius: 10px;
}

.plate-desc {
  font-size: 10px;
  color: var(--text-secondary);
  margin-bottom: 8px;
}

.plate-stocks {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed var(--border-color);
}

.plate-stock {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
  font-size: 11px;
}

.plate-stock .stock-code {
  color: var(--text-secondary);
  font-family: monospace;
}

.plate-stock .stock-name {
  flex: 1;
  color: var(--text-primary);
}

.plate-stock .stock-change {
  min-width: 60px;
  text-align: right;
  font-weight: bold;
}

/* 底部 */
.panel-footer {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  border-top: 1px solid var(--border-color);
  background: var(--bg-header);
  font-size: 9px;
  color: var(--text-secondary);
}

.up-text {
  color: #ff4757 !important;
}

.down-text {
  color: #2ed573 !important;
}

.loading-state {
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

.error-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 60px 20px;
  gap: 12px;
}

.error-icon {
  font-size: 32px;
}

.retry-btn {
  padding: 8px 16px;
  background: var(--color-highlight);
  border: none;
  border-radius: 20px;
  color: #000;
  font-size: 12px;
  cursor: pointer;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
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

.dot {
  opacity: 0.5;
}

/* 龙息因子视图 */
.factors-view {
  padding: 4px 0;
}

.factors-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  padding: 0 4px;
}

.factors-header h4 {
  margin: 0;
  font-size: 14px;
  color: var(--text-primary);
  display: flex;
  align-items: center;
  gap: 6px;
}

.factors-header h4::before {
  content: '🌬️';
  font-size: 16px;
}

.factor-count {
  background: var(--bg-primary);
  padding: 2px 8px;
  border-radius: 12px;
  font-size: 11px;
  color: var(--color-highlight);
}

/* 因子卡片网格 */
.factors-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin-bottom: 20px;
}

.factor-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 14px;
  transition: all 0.2s ease;
  position: relative;
  overflow: hidden;
}

.factor-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
  border-color: var(--color-highlight);
}

/* 卡片顶部装饰条 */
.factor-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
  background: linear-gradient(90deg, var(--color-highlight), transparent);
  opacity: 0.5;
}

.factor-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.factor-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-title);
  letter-spacing: 0.3px;
}

.factor-weight {
  font-size: 11px;
  padding: 3px 8px;
  background: var(--bg-primary);
  border-radius: 20px;
  color: var(--color-highlight);
  font-weight: 600;
  border: 1px solid rgba(255, 165, 2, 0.2);
}

.factor-value {
  font-size: 28px;
  font-weight: 700;
  margin-bottom: 6px;
  line-height: 1.2;
  font-family: 'JetBrains Mono', monospace;
  text-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
}

.factor-desc {
  font-size: 10px;
  color: var(--text-secondary);
  margin-bottom: 12px;
  line-height: 1.4;
  min-height: 28px;
  opacity: 0.8;
}

.factor-bar {
  height: 4px;
  background: var(--bg-primary);
  border-radius: 2px;
  overflow: hidden;
}

.factor-bar-fill {
  height: 100%;
  border-radius: 2px;
  transition: width 0.4s cubic-bezier(0.4, 0, 0.2, 1);
}

/* 操作建议卡片 */
.suggestions-card {
  background: linear-gradient(135deg, #2a2a2a, #1a1a1a);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 16px;
  margin-top: 20px;
  position: relative;
  overflow: hidden;
}

.suggestions-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
  background: linear-gradient(90deg, var(--color-highlight), #ffd700, transparent);
}

.suggestions-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.suggestions-icon {
  font-size: 20px;
  filter: drop-shadow(0 2px 4px rgba(255, 165, 2, 0.3));
}

.suggestions-title {
  font-size: 14px;
  font-weight: bold;
  color: var(--color-highlight);
}

.suggestions-list {
  margin: 0;
  padding-left: 20px;
  color: var(--text-primary);
}

.suggestions-list li {
  margin-bottom: 8px;
  font-size: 12px;
  line-height: 1.5;
  color: var(--text-secondary);
}

.suggestions-list li::marker {
  color: var(--color-highlight);
}

/* 权重分布 */
.weights-section {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  padding: 16px;
  margin-top: 16px;
}

.weights-grid {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.weight-item {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
}

.weight-name {
  width: 45px;
  /* 固定宽度，确保对齐 */
  font-size: 12px;
  font-weight: 500;
  color: var(--text-primary);
  text-align: left;
}

.weight-bar-container {
  flex: 1;
  /* 占据剩余空间 */
  min-width: 0;
  /* 防止flex溢出 */
}

.weight-bar {
  height: 8px;
  background: var(--bg-primary);
  border-radius: 4px;
  overflow: hidden;
  width: 100%;
}

.weight-bar-fill {
  height: 100%;
  border-radius: 4px;
  transition: width 0.3s ease;
}

.weight-value {
  width: 48px;
  /* 固定宽度，确保对齐 */
  font-size: 12px;
  font-weight: 600;
  color: var(--color-highlight);
  text-align: right;
  font-family: monospace;
}

/* 总计行特殊样式 */
.weight-item.total {
  margin-top: 4px;
  padding-top: 8px;
  border-top: 1px dashed var(--border-color);
}

.weight-item.total .weight-name {
  color: var(--color-highlight);
  font-weight: 600;
}

.weight-item.total .weight-bar-fill {
  background: linear-gradient(90deg, var(--color-highlight), #ffd700);
  box-shadow: 0 0 8px rgba(255, 165, 2, 0.5);
}

.weight-item.total .weight-value {
  color: var(--color-highlight);
  font-weight: 700;
}

/* 总分显示卡片 */
.total-score-card {
  background: linear-gradient(135deg, #1a1a2e, #16213e);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 16px;
  margin: 20px 0;
}

.total-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.total-icon {
  font-size: 20px;
}

.total-title {
  font-size: 14px;
  font-weight: bold;
  color: var(--text-primary);
}

.total-value {
  font-size: 36px;
  font-weight: bold;
  font-family: monospace;
  margin-bottom: 8px;
}

.total-breakdown {
  display: flex;
  gap: 16px;
  font-size: 11px;
  color: var(--text-secondary);
  margin-bottom: 12px;
}

.total-bar {
  height: 8px;
  background: var(--bg-primary);
  border-radius: 4px;
  overflow: hidden;
}

.total-bar-fill {
  height: 100%;
  background: linear-gradient(90deg, #ffa502, #ff4757);
  border-radius: 4px;
  transition: width 0.4s ease;
}

/* 因子卡片中的最高分标签 */
.factor-max {
  font-size: 10px;
  padding: 2px 6px;
  background: var(--bg-primary);
  border-radius: 12px;
  color: var(--text-secondary);
}

/* 因子提示标签 */
.factor-tip {
  font-size: 10px;
  color: var(--text-secondary);
  background: var(--bg-primary);
  padding: 2px 8px;
  border-radius: 12px;
}


.factor-raw {
  font-size: 11px;
  font-weight: 500;
  margin-bottom: 8px;
  opacity: 0.8;
}

/* 响应式调整 */
@media (max-width: 480px) {
  .factors-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

/* 情绪因子得分区域 */
.factor-scores {
  background: linear-gradient(135deg, var(--bg-secondary), var(--bg-hover));
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 16px;
  margin-bottom: 20px;
}

.factor-scores h4 {
  margin: 0 0 12px 0;
  font-size: 13px;
  color: var(--text-primary);
  display: flex;
  align-items: center;
  gap: 6px;
}

.factor-score-item {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.factor-score-item:last-child {
  margin-bottom: 0;
}

.factor-score-item .factor-name {
  width: 70px;
  font-size: 12px;
  color: var(--text-secondary);
}

.factor-score {
  font-size: 28px;
  font-weight: 700;
  line-height: 1.2;
  font-family: monospace;
  margin-bottom: 4px;
}

.factor-raw {
  font-size: 11px;
  font-weight: 500;
  margin-bottom: 8px;
  opacity: 0.8;
}

.factor-desc {
  font-size: 10px;
  color: var(--text-secondary);
  margin-bottom: 10px;
  line-height: 1.4;
  min-height: 32px;
}

.score-bar {
  flex: 1;
  height: 6px;
  background: var(--bg-primary);
  border-radius: 3px;
  overflow: hidden;
}

.score-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--color-highlight), #ffd700);
  border-radius: 3px;
  transition: width 0.3s ease;
  box-shadow: 0 0 8px rgba(255, 165, 2, 0.3);
}

.score-value {
  width: 35px;
  font-size: 12px;
  font-weight: 600;
  color: var(--color-highlight);
  text-align: right;
  font-family: monospace;
}

/* 添加贡献说明样式 */
.factor-contribution {
  font-size: 10px;
  color: var(--text-secondary);
  margin-top: 8px;
  padding-top: 6px;
  border-top: 1px dashed var(--border-color);
  text-align: right;
  font-family: monospace;
}
</style>
