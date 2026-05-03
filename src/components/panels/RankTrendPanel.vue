<!-- src/components/panels/RankTrendPanel.vue -->
<template>
  <Teleport to="body">
    <div v-if="visible" ref="panelRef" class="rank-trend-panel" :style="panelStyle">
      <header class="panel-header">
        <div class="header-title">
          <button class="ghost-btn" type="button" @click="close">返回</button>
          <div>
            <h3>排名趋势策略</h3>
            <span>候选池 · 生命周期 · 多周期动量</span>
          </div>
        </div>
        <div class="panel-actions">
          <button class="icon-btn" type="button" title="刷新" :class="{ loading }" @click="refresh">↻</button>
          <button class="icon-btn" type="button" title="关闭" @click="close">×</button>
        </div>
      </header>

      <div class="search-bar">
        <input
          v-model.trim="searchCode"
          class="search-input"
          type="text"
          placeholder="输入股票代码"
          @keyup.enter="loadStock"
        />
        <label class="snapshot-select">
          <span>快照</span>
          <select v-model="selectedSnapshotType" class="snapshot-input">
            <option v-for="type in RANK_TREND_SNAPSHOT_TYPES" :key="type" :value="type">
              {{ snapshotTypeText(type) }}
            </option>
          </select>
        </label>
        <button class="primary-btn" type="button" @click="loadStock">应用并分析</button>
      </div>

      <section class="config-card">
        <div class="config-head">
          <div>
            <strong>分析参数</strong>
            <span>直接作用于当前排名趋势分析器，默认值来自 `rankTrendDefaults.ts`</span>
          </div>
          <div class="config-actions">
            <button class="ghost-btn" type="button" @click="showConfigEditor = !showConfigEditor">
              {{ showConfigEditor ? '收起参数' : '展开参数' }}
            </button>
            <button class="ghost-btn" type="button" @click="resetRuntimeConfig">恢复默认</button>
          </div>
        </div>

        <div class="config-summary">
          <span>MACD {{ runtimeConfigForm.macdFast }}/{{ runtimeConfigForm.macdSlow }}/{{ runtimeConfigForm.macdSignal }}</span>
          <span>综合阈值 {{ runtimeConfigForm.buyScoreThreshold.toFixed(2) }}/{{ runtimeConfigForm.sellScoreThreshold.toFixed(2) }}</span>
          <span>快照偏好 {{ snapshotTypeText(selectedSnapshotType) }}</span>
        </div>

        <div v-if="showConfigEditor" class="config-grid">
          <label class="config-field wide">
            <span>动量周期</span>
            <input v-model.trim="runtimeConfigForm.momentumPeriods" type="text" placeholder="3, 5, 8, 13, 21" />
            <small>固定 5 个值，逗号分隔</small>
          </label>
          <label class="config-field wide">
            <span>动量权重</span>
            <input v-model.trim="runtimeConfigForm.momentumWeights" type="text" placeholder="0.15, 0.2, 0.25, 0.25, 0.15" />
            <small>固定 5 个值，会自动归一化</small>
          </label>
          <label class="config-field wide">
            <span>买入阈值组</span>
            <input v-model.trim="runtimeConfigForm.buyThresholds" type="text" placeholder="5, 8, 12, 15, 20" />
          </label>
          <label class="config-field wide">
            <span>卖出阈值组</span>
            <input v-model.trim="runtimeConfigForm.sellThresholds" type="text" placeholder="-5, -8, -12, -15, -20" />
          </label>

          <label class="config-field">
            <span>MACD Fast</span>
            <input v-model.number="runtimeConfigForm.macdFast" type="number" min="2" max="60" />
          </label>
          <label class="config-field">
            <span>MACD Slow</span>
            <input v-model.number="runtimeConfigForm.macdSlow" type="number" min="3" max="120" />
          </label>
          <label class="config-field">
            <span>MACD Signal</span>
            <input v-model.number="runtimeConfigForm.macdSignal" type="number" min="2" max="60" />
          </label>

          <label class="config-field">
            <span>方向权重</span>
            <input v-model.number="runtimeConfigForm.directionWeight" type="number" min="0.01" max="1" step="0.01" />
          </label>
          <label class="config-field">
            <span>加速度权重</span>
            <input v-model.number="runtimeConfigForm.accelerationWeight" type="number" min="0.01" max="1" step="0.01" />
          </label>
          <label class="config-field">
            <span>零线权重</span>
            <input v-model.number="runtimeConfigForm.crossWeight" type="number" min="0.01" max="1" step="0.01" />
          </label>
          <label class="config-field">
            <span>MACD 权重</span>
            <input v-model.number="runtimeConfigForm.macdWeight" type="number" min="0.01" max="1" step="0.01" />
          </label>
          <label class="config-field">
            <span>买入综合阈值</span>
            <input v-model.number="runtimeConfigForm.buyScoreThreshold" type="number" min="0.01" max="1" step="0.01" />
          </label>
          <label class="config-field">
            <span>卖出综合阈值</span>
            <input v-model.number="runtimeConfigForm.sellScoreThreshold" type="number" min="-1" max="-0.01" step="0.01" />
          </label>
        </div>
      </section>

      <main class="panel-content">
        <div v-if="loading" class="state-view">
          <div class="loading-spinner"></div>
          <span>{{ loadingText }}</span>
        </div>

        <div v-else-if="errorMessage" class="state-view error-view">
          <strong>{{ errorMessage }}</strong>
          <span>{{ dataStatus }}</span>
        </div>

        <template v-else-if="currentStock">
          <section class="hero-card" :class="[signalClass(currentStock.finalSignal), tierClass(currentStock.statusClass)]">
            <div class="hero-left">
              <div class="stock-row">
                <div>
                  <div class="stock-code">{{ currentStock.code }}</div>
                  <div class="stock-name">{{ currentStock.name || '-' }}</div>
                </div>
                <div class="price-block">
                  <strong>{{ formatPrice(currentStock.price) }}</strong>
                  <span :class="changeClass(currentStock.change)">{{ formatPercent(currentStock.change) }}</span>
                </div>
              </div>

              <div class="decision-row">
                <div>
                  <span class="eyebrow">状态</span>
                  <h2>{{ currentStock.statusLabel }}</h2>
                </div>
              </div>

              <div class="tag-row">
                <span>{{ signalText(currentStock.finalSignal) }}</span>
                <span>{{ regimeText(currentStock.regimeState) }}</span>
              </div>
            </div>

            <div class="hero-right">
              <div class="confidence-ring">
                <svg viewBox="0 0 76 76" aria-hidden="true">
                  <circle cx="38" cy="38" r="31" class="ring-bg" />
                  <circle
                    cx="38"
                    cy="38"
                    r="31"
                    class="ring-value"
                    :stroke-dasharray="ringDash"
                    :stroke-dashoffset="ringOffset(currentStock.finalConfidence)"
                  />
                  <text x="38" y="43">{{ Math.round(currentStock.finalConfidence || 0) }}%</text>
                </svg>
                <span>策略置信度</span>
              </div>

              <div class="metric-stack">
                <div>
                  <span>当前排名</span>
                  <strong>{{ currentStock.currentRank || '-' }}</strong>
                </div>
                <div>
                  <span>排名变化</span>
                  <strong :class="rankChangeClass(currentStock.rankChange)">
                    {{ formatRankChange(currentStock.rankChange) }}
                  </strong>
                </div>
                <div>
                  <span>百分位</span>
                  <strong>{{ formatNumber(currentStock.currentPercentile, 1) }}</strong>
                </div>
              </div>
            </div>
          </section>

          <section v-if="!currentStock.rankTrend" class="notice-card">
            当前股票没有生成排名趋势结果。面板已经按当前 DataLayer 股票列表调用
            RankTrendAnalyzer，若仍为空，通常是快照样本不足或当前股票未出现在快照热榜中。
          </section>

          <section v-else class="strategy-card">
            <div class="section-head">
              <div>
                <h4>策略解释</h4>
                <span>{{ dataStatus }}</span>
              </div>
              <strong>{{ sampleQualityText(currentStock.rankTrend) }}</strong>
            </div>

            <div class="context-grid">
              <article>
                <span>市场环境</span>
                <strong>{{ regimeText(currentStock.regimeState) }}</strong>
                <small>分数 {{ formatNumber(currentStock.regimeScore, 2) }}</small>
              </article>
              <article>
                <span>生命周期</span>
                <strong>{{ stageText(currentStock.stage) }}</strong>
                <small>{{ currentStock.entryReason }}</small>
              </article>
              <article>
                <span>风险压力</span>
                <strong>{{ formatNumber(currentStock.riskPressure, 2) }}</strong>
                <small>协同 {{ formatNumber(currentStock.riskSynergy, 2) }}</small>
              </article>
            </div>

            <div class="momentum-card">
              <div class="section-head compact">
                <div>
                  <h4>多周期动量</h4>
                  <span>短冲击 · 中确认 · 长拥挤 · 加速度 · 异动</span>
                </div>
                <strong>综合 {{ formatNumber(currentStock.momentum?.composite, 2) }}</strong>
              </div>
              <div class="momentum-list">
                <div v-for="item in momentumRows" :key="item.key" class="momentum-row">
                  <span>{{ item.label }}</span>
                  <div class="momentum-track">
                    <i :class="item.className" :style="{ width: item.width }"></i>
                  </div>
                  <strong :class="item.className">{{ item.text }}</strong>
                </div>
              </div>
            </div>

            <div v-if="strategyReasons.length" class="reason-list">
              <div v-for="reason in strategyReasons" :key="reason" class="reason-item">
                {{ reason }}
              </div>
            </div>
          </section>

          <section class="signal-card">
            <div class="section-head compact">
              <div>
                <h4>信号拆解</h4>
                <span>旧信号保留为解释层，不直接等同交易指令</span>
              </div>
              <strong :class="signalClass(currentStock.finalSignal)">
                {{ signalText(currentStock.finalSignal) }}
              </strong>
            </div>
            <div class="signal-grid">
              <article v-for="item in signalRows" :key="item.key" :class="signalClass(item.signal)">
                <span>{{ item.label }}</span>
                <strong>{{ signalText(item.signal) }}</strong>
                <small>{{ Math.round(item.confidence || 0) }}%</small>
              </article>
            </div>
          </section>

          <section class="market-card">
            <div class="market-grid">
              <article>
                <span>主力净额</span>
                <strong :class="numberClass(currentStock.zlje)">{{ formatMoney(currentStock.zlje) }}</strong>
              </article>
              <article>
                <span>主力占比</span>
                <strong>{{ formatPercent(currentStock.zljzb) }}</strong>
              </article>
              <article>
                <span>量比</span>
                <strong>{{ formatNumber(currentStock.volumeRatio, 2) }}</strong>
              </article>
              <article>
                <span>换手率</span>
                <strong>{{ formatPercent(currentStock.turnoverRate) }}</strong>
              </article>
              <article>
                <span>MACD</span>
                <strong :class="crossClass(currentStock.macdCross)">{{ crossText(currentStock.macdCross) }}</strong>
              </article>
              <article>
                <span>情绪</span>
                <strong>{{ breathData?.phaseName || '-' }}</strong>
              </article>
            </div>
          </section>

          <section v-if="rankHistory.length" class="history-card">
            <div class="section-head compact">
              <div>
                <h4>快照排名</h4>
                <span>{{ historySource }} · 最近 {{ rankHistory.length }} 个样本</span>
              </div>
              <strong :class="trendClass">{{ trendText }}</strong>
            </div>
            <div ref="chartRef" class="history-chart"></div>
          </section>
        </template>

        <div v-else class="state-view">
          <strong>输入股票代码开始分析</strong>
          <span>面板将从 DataLayer 读取当前榜单，并调用 RankTrendAnalyzer 生成策略结果。</span>
        </div>
      </main>

      <footer class="panel-footer">
        <span>{{ dataStatus || '等待分析' }}</span>
        <span>{{ formatTime(lastUpdate) }}</span>
      </footer>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { usePanel } from '@/composables/usePanel'
import { dataLayer } from '@/services/DataLayer'
import { rankTrendAnalyzer, type RankTrendResult } from '@/services/RankTrendAnalyzer'
import {
  buildRankTrendStatusContext,
  getRankTrendDisplayStatus,
  type RankTrendStatusContext,
} from '@/services/rankTrend/compat'
import {
  buildRankTrendSnapshotPriority,
  cloneDefaultRankTrendRuntimeConfig,
  DEFAULT_RANK_TREND_SNAPSHOT_TYPE,
  getRankTrendSnapshotHistoryLimit,
  getRankTrendSnapshotLabel,
  RANK_TREND_SNAPSHOT_TYPES,
  normalizeRankTrendRuntimeConfig,
  type RankTrendRuntimeDefaults,
  type RankTrendSnapshotType,
} from '@/types/rankTrendDefaults'

type Signal = 'buy' | 'sell' | 'hold' | 'none'
type PreferredSnapshotType = RankTrendSnapshotType

interface RuntimeConfigForm {
  momentumPeriods: string
  momentumWeights: string
  buyThresholds: string
  sellThresholds: string
  macdFast: number
  macdSlow: number
  macdSignal: number
  directionWeight: number
  accelerationWeight: number
  crossWeight: number
  macdWeight: number
  buyScoreThreshold: number
  sellScoreThreshold: number
}

interface PanelStockView {
  code: string
  name: string
  price: number
  change: number
  zlje: number
  zljzb: number
  volumeRatio: number
  turnoverRate: number
  currentRank: number
  currentPercentile: number
  rankChange: number
  finalSignal: Signal
  finalConfidence: number
  rankTrendSignal: Signal
  rankTrendConfidence: number
  accelerationSignal: Signal
  accelerationConfidence: number
  crossSignal: Signal
  crossConfidence: number
  moneyFlowSignal: Signal
  moneyFlowConfidence: number
  sectorSignal: Signal
  sectorConfidence: number
  sentimentSignal: Signal
  sentimentConfidence: number
  macdCross: string
  statusLabel: string
  statusClass: string
  tier: string
  action: string
  stage: string
  regimeState: string
  regimeScore: number
  riskPressure: number
  riskSynergy: number
  entryReason: string
  momentum: NonNullable<RankTrendResult['strategy']>['momentum'] | null
  rankTrend: RankTrendResult | null
}

const props = defineProps<{
  visible: boolean
  triggerRect?: DOMRect
  stockCode?: string
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

const ringDash = 194.78
const searchCode = ref('')
const selectedSnapshotType = ref<PreferredSnapshotType>(DEFAULT_RANK_TREND_SNAPSHOT_TYPE)
const showConfigEditor = ref(false)
const loading = ref(false)
const loadingText = ref('正在计算策略结构')
const currentStock = ref<PanelStockView | null>(null)
const breathData = ref<any>(null)
const rankHistory = ref<number[]>([])
const historySource = ref('')
const dataStatus = ref('')
const errorMessage = ref('')
const lastUpdate = ref(Date.now())
const chartRef = ref<HTMLElement | null>(null)
let chart: echarts.ECharts | null = null
let resizeHandler: (() => void) | null = null
const runtimeConfigForm = reactive<RuntimeConfigForm>(createRuntimeConfigForm())

const stageLabels: Record<string, string> = {
  ignition: '点火',
  expansion: '扩散',
  crowded: '拥挤',
  reversal: '反转',
  cooling: '冷却',
}

const regimeLabels: Record<string, string> = {
  strong: '强势',
  normal: '常态',
  weak: '弱势',
  retreat: '退潮',
}

const strategyReasons = computed(() => {
  const reasons = currentStock.value?.rankTrend?.strategy?.reasons
  return Array.isArray(reasons) ? reasons.filter(Boolean).map(String) : []
})

const signalRows = computed(() => {
  const stock = currentStock.value
  if (!stock) return []
  return [
    { key: 'rank', label: '排名趋势', signal: stock.rankTrendSignal, confidence: stock.rankTrendConfidence },
    { key: 'acceleration', label: '动量加速', signal: stock.accelerationSignal, confidence: stock.accelerationConfidence },
    { key: 'cross', label: '零线交叉', signal: stock.crossSignal, confidence: stock.crossConfidence },
    { key: 'money', label: '资金流向', signal: stock.moneyFlowSignal, confidence: stock.moneyFlowConfidence },
    { key: 'sector', label: '题材板块', signal: stock.sectorSignal, confidence: stock.sectorConfidence },
    { key: 'sentiment', label: '市场情绪', signal: stock.sentimentSignal, confidence: stock.sentimentConfidence },
  ]
})

const momentumRows = computed(() => {
  const momentum = currentStock.value?.momentum
  const items = [
    { key: 'short', label: '短周期', value: momentum?.short },
    { key: 'mid', label: '中周期', value: momentum?.mid },
    { key: 'long', label: '长周期', value: momentum?.long },
    { key: 'acceleration', label: '加速度', value: momentum?.acceleration },
    { key: 'shock', label: '冲击', value: momentum?.shock },
  ]

  return items.map((item) => {
    const value = Number(item.value ?? 0)
    const abs = Math.min(100, Math.abs(value) * 8)
    return {
      ...item,
      width: `${Math.max(4, abs)}%`,
      text: signedNumber(value),
      className: value > 0 ? 'positive' : value < 0 ? 'negative' : 'neutral',
    }
  })
})

const trendClass = computed(() => {
  if (rankHistory.value.length < 2) return 'neutral'
  const first = rankHistory.value[0]
  const last = rankHistory.value[rankHistory.value.length - 1]
  if (last < first) return 'positive'
  if (last > first) return 'negative'
  return 'neutral'
})

const trendText = computed(() => {
  if (rankHistory.value.length < 2) return '样本不足'
  const first = rankHistory.value[0]
  const last = rankHistory.value[rankHistory.value.length - 1]
  const change = first - last
  if (change > 0) return `上升 ${change} 位`
  if (change < 0) return `下降 ${Math.abs(change)} 位`
  return '排名平稳'
})

function formatRuntimeConfigArray(values: number[]): string {
  return values.join(', ')
}

function createRuntimeConfigForm(
  config: RankTrendRuntimeDefaults = cloneDefaultRankTrendRuntimeConfig(),
): RuntimeConfigForm {
  return {
    momentumPeriods: formatRuntimeConfigArray(config.momentumPeriods),
    momentumWeights: formatRuntimeConfigArray(config.momentumWeights),
    buyThresholds: formatRuntimeConfigArray(config.buyThresholds),
    sellThresholds: formatRuntimeConfigArray(config.sellThresholds),
    macdFast: config.macdFast,
    macdSlow: config.macdSlow,
    macdSignal: config.macdSignal,
    directionWeight: config.directionWeight,
    accelerationWeight: config.accelerationWeight,
    crossWeight: config.crossWeight,
    macdWeight: config.macdWeight,
    buyScoreThreshold: config.buyScoreThreshold,
    sellScoreThreshold: config.sellScoreThreshold,
  }
}

function applyRuntimeConfigForm(next: RuntimeConfigForm) {
  runtimeConfigForm.momentumPeriods = next.momentumPeriods
  runtimeConfigForm.momentumWeights = next.momentumWeights
  runtimeConfigForm.buyThresholds = next.buyThresholds
  runtimeConfigForm.sellThresholds = next.sellThresholds
  runtimeConfigForm.macdFast = next.macdFast
  runtimeConfigForm.macdSlow = next.macdSlow
  runtimeConfigForm.macdSignal = next.macdSignal
  runtimeConfigForm.directionWeight = next.directionWeight
  runtimeConfigForm.accelerationWeight = next.accelerationWeight
  runtimeConfigForm.crossWeight = next.crossWeight
  runtimeConfigForm.macdWeight = next.macdWeight
  runtimeConfigForm.buyScoreThreshold = next.buyScoreThreshold
  runtimeConfigForm.sellScoreThreshold = next.sellScoreThreshold
}

function parseRuntimeConfigSeries(value: string, expectedLength: number, label: string): number[] {
  const parts = String(value || '')
    .split(',')
    .map((item) => Number(item.trim()))
    .filter((item) => Number.isFinite(item))

  if (parts.length !== expectedLength) {
    throw new Error(`${label} 需要 ${expectedLength} 个数值，当前为 ${parts.length} 个`)
  }
  return parts
}

function buildRuntimeConfigFromForm(): RankTrendRuntimeDefaults {
  const defaults = cloneDefaultRankTrendRuntimeConfig()
  return normalizeRankTrendRuntimeConfig(defaults, {
    momentumPeriods: parseRuntimeConfigSeries(
      runtimeConfigForm.momentumPeriods,
      defaults.momentumPeriods.length,
      '动量周期',
    ),
    momentumWeights: parseRuntimeConfigSeries(
      runtimeConfigForm.momentumWeights,
      defaults.momentumWeights.length,
      '动量权重',
    ),
    buyThresholds: parseRuntimeConfigSeries(
      runtimeConfigForm.buyThresholds,
      defaults.buyThresholds.length,
      '买入阈值组',
    ),
    sellThresholds: parseRuntimeConfigSeries(
      runtimeConfigForm.sellThresholds,
      defaults.sellThresholds.length,
      '卖出阈值组',
    ),
    macdFast: runtimeConfigForm.macdFast,
    macdSlow: runtimeConfigForm.macdSlow,
    macdSignal: runtimeConfigForm.macdSignal,
    directionWeight: runtimeConfigForm.directionWeight,
    accelerationWeight: runtimeConfigForm.accelerationWeight,
    crossWeight: runtimeConfigForm.crossWeight,
    macdWeight: runtimeConfigForm.macdWeight,
    buyScoreThreshold: runtimeConfigForm.buyScoreThreshold,
    sellScoreThreshold: runtimeConfigForm.sellScoreThreshold,
  })
}

function resetRuntimeConfig() {
  applyRuntimeConfigForm(createRuntimeConfigForm())
  rankTrendAnalyzer.updateRuntimeConfig(cloneDefaultRankTrendRuntimeConfig())
  dataStatus.value = '已恢复排名趋势默认参数'
}

function applyPanelRuntimeConfig(): RankTrendRuntimeDefaults {
  const normalized = buildRuntimeConfigFromForm()
  rankTrendAnalyzer.updateRuntimeConfig(normalized)
  applyRuntimeConfigForm(createRuntimeConfigForm(normalized))
  return normalized
}

function snapshotTypeText(type: PreferredSnapshotType): string {
  return getRankTrendSnapshotLabel(type)
}

function normalizeCode(code: string): string {
  return String(code || '').trim().toUpperCase()
}

function buildRankMap(stocks: any[]): Map<string, number> {
  const rankMap = new Map<string, number>()
  stocks.forEach((stock, index) => {
    const code = normalizeCode(stock?.code)
    if (!code) return
    const rank = Number(stock?.rank ?? stock?.compRank ?? index + 1)
    rankMap.set(code, Number.isFinite(rank) && rank > 0 ? rank : index + 1)
  })
  return rankMap
}

function getPrice(stock: any): number {
  return Number(stock?.price ?? stock?.latestPrice ?? stock?.lastPrice ?? stock?.close ?? 0)
}

function buildPanelStockView(
  stock: any,
  analysis: RankTrendResult | null,
  rank: number,
  statusContext?: RankTrendStatusContext,
): PanelStockView {
  const strategy = analysis?.strategy
  const technical = analysis?.technical
  const cycle = analysis?.cycle
  const risk = analysis?.risk
  const finalSignal = (analysis?.decision?.final?.signal ?? stock?.finalSignal ?? 'hold') as Signal
  const status = getRankTrendDisplayStatus(analysis, stock, statusContext)

  return {
    code: normalizeCode(stock?.code),
    name: String(stock?.name ?? ''),
    price: getPrice(stock),
    change: Number(stock?.change ?? 0),
    zlje: Number(stock?.zlje ?? 0),
    zljzb: Number(stock?.zljzb ?? 0),
    volumeRatio: Number(stock?.volumeRatio ?? 0),
    turnoverRate: Number(stock?.turnoverRate ?? stock?.turnover ?? 0),
    currentRank: Number(analysis?.meta?.currentRank ?? rank ?? 0),
    currentPercentile: Number(analysis?.meta?.currentPercentile ?? 0),
    rankChange: Number(analysis?.meta?.change ?? stock?.rankChange ?? 0),
    finalSignal,
    finalConfidence: Number(analysis?.decision?.final?.confidence ?? stock?.finalConfidence ?? 0),
    rankTrendSignal: (technical?.signals?.direction?.signal ?? stock?.rankTrendSignal ?? 'hold') as Signal,
    rankTrendConfidence: Number(technical?.signals?.direction?.confidence ?? stock?.rankTrendConfidence ?? 0),
    accelerationSignal: (technical?.signals?.acceleration?.signal ?? 'hold') as Signal,
    accelerationConfidence: Number(technical?.signals?.acceleration?.confidence ?? 0),
    crossSignal: (technical?.signals?.zeroCross?.signal ?? 'hold') as Signal,
    crossConfidence: Number(technical?.signals?.zeroCross?.confidence ?? 0),
    moneyFlowSignal: (stock?.moneyFlowSignal ?? 'hold') as Signal,
    moneyFlowConfidence: Number(stock?.moneyFlowConfidence ?? 0),
    sectorSignal: (stock?.sectorSignal ?? 'hold') as Signal,
    sectorConfidence: Number(stock?.sectorConfidence ?? 0),
    sentimentSignal: finalSignal,
    sentimentConfidence: Number(analysis?.decision?.final?.confidence ?? 0),
    macdCross: String(technical?.macd?.cross ?? stock?.macdCross ?? 'none'),
    statusLabel: status.label,
    statusClass: status.classKey,
    tier: String(strategy?.candidateTier ?? 'N_NEUTRAL'),
    action: String(strategy?.action ?? 'hold'),
    stage: String(cycle?.stage ?? ''),
    regimeState: String(strategy?.regime?.state ?? ''),
    regimeScore: Number(strategy?.regime?.score ?? 0),
    riskPressure: Number(risk?.pressure ?? 0),
    riskSynergy: Number(risk?.synergy ?? 0),
    entryReason: String(cycle?.entryAdvice?.reason ?? '-'),
    momentum: strategy?.momentum ?? null,
    rankTrend: analysis,
  }
}

async function loadStock() {
  const code = normalizeCode(searchCode.value)
  if (!code) return

  loading.value = true
  loadingText.value = '读取 DataLayer 当前榜单'
  errorMessage.value = ''
  currentStock.value = null
  rankHistory.value = []
  disposeChart()

  try {
    const runtimeConfig = applyPanelRuntimeConfig()
    const stocks = dataLayer.getStocks()
    const rankMap = buildRankMap(stocks)
    const sourceStock = stocks.find((stock: any) => normalizeCode(stock?.code) === code)

    if (!sourceStock) {
      errorMessage.value = `未在当前榜单找到 ${code}`
      dataStatus.value = 'DataLayer 当前股票列表无该代码'
      return
    }

    loadingText.value = `调用 RankTrendAnalyzer 计算（${snapshotTypeText(selectedSnapshotType.value)}）`
    const results = await rankTrendAnalyzer.getRankTrends(rankMap, {
      updateSignalStore: false,
      preferredSnapshotType: selectedSnapshotType.value,
    })
    const analysis = results.get(code) ?? (sourceStock.rankTrend as RankTrendResult | undefined) ?? null
    const rank = rankMap.get(code) ?? Number(sourceStock.compRank ?? 0)

    const statusContext = buildRankTrendStatusContext(stocks)
    currentStock.value = buildPanelStockView(sourceStock, analysis, rank, statusContext)
    breathData.value = dataLayer.getBreathData()
    const sampleQuality = analysis?.meta?.sampleQuality
    const runtimeSummary = `${runtimeConfig.macdFast}/${runtimeConfig.macdSlow}/${runtimeConfig.macdSignal}`
    dataStatus.value = analysis
      ? `已基于 ${sampleQuality?.snapshotType || selectedSnapshotType.value} 生成，样本 ${sampleQuality?.sampleCount || 0}/${sampleQuality?.requiredSampleCount || 0}，MACD ${runtimeSummary}`
      : `已应用参数并调用分析器，但当前股票没有有效 rankTrend 结果`
    lastUpdate.value = Date.now()

    loadingText.value = '加载快照排名曲线'
    await loadRankHistory(code, selectedSnapshotType.value)
    await nextTick()
    renderChart()
  } catch (error) {
    console.error('[RankTrendPanel] 加载失败:', error)
    errorMessage.value = '排名趋势面板加载失败'
    dataStatus.value = error instanceof Error ? error.message : String(error)
  } finally {
    loading.value = false
  }
}

async function loadRankHistory(code: string, preferredType: PreferredSnapshotType) {
  const sourcePriority = buildRankTrendSnapshotPriority(preferredType)

  for (const sourceType of sourcePriority) {
    const records = await rankTrendAnalyzer.getSnapshotsByType(sourceType, {
      limit: getRankTrendSnapshotHistoryLimit(sourceType),
    })
    const ranks = records
      .map((record) => {
        const hotlist = Array.isArray(record?.snapshot?.hotlist) ? record.snapshot.hotlist : []
        const index = hotlist.findIndex((item: any) => normalizeCode(item?.code) === code)
        const item = index >= 0 ? hotlist[index] : null
        const rank = Number(item?.rank ?? (index >= 0 ? index + 1 : 0))
        return rank > 0 ? { rank, timestamp: Number(record.timestamp ?? 0) } : null
      })
      .filter((item): item is { rank: number; timestamp: number } => Boolean(item))
      .sort((a, b) => a.timestamp - b.timestamp)

    if (ranks.length >= 2) {
      rankHistory.value = ranks.map((item) => item.rank)
      historySource.value = snapshotTypeText(sourceType)
      return
    }
  }

  rankHistory.value = []
  historySource.value = '无有效快照'
}

function renderChart() {
  if (!chartRef.value || rankHistory.value.length < 2) return
  disposeChart()

  chart = echarts.init(chartRef.value)
  const maxRank = Math.max(...rankHistory.value)
  const minRank = Math.min(...rankHistory.value)

  chart.setOption({
    grid: { left: 34, right: 12, top: 18, bottom: 24 },
    tooltip: {
      trigger: 'axis',
      formatter: (params: any) => {
        const item = Array.isArray(params) ? params[0] : null
        if (!item) return ''
        return `排名: ${item.value}<br/>样本: ${item.dataIndex + 1}/${rankHistory.value.length}`
      },
    },
    xAxis: {
      type: 'category',
      data: rankHistory.value.map((_, index) => index + 1),
      axisLine: { lineStyle: { color: '#3a3f4b' } },
      axisTick: { show: false },
      axisLabel: { color: '#8c94a3', fontSize: 10 },
    },
    yAxis: {
      type: 'value',
      inverse: true,
      min: Math.max(1, minRank - 5),
      max: maxRank + 5,
      splitLine: { lineStyle: { color: 'rgba(140,148,163,0.16)', type: 'dashed' } },
      axisLabel: { color: '#8c94a3', fontSize: 10 },
    },
    series: [
      {
        type: 'line',
        data: rankHistory.value,
        smooth: true,
        symbol: 'circle',
        symbolSize: 5,
        lineStyle: { color: '#4db6ac', width: 2 },
        itemStyle: { color: '#4db6ac' },
        areaStyle: { color: 'rgba(77,182,172,0.12)' },
      },
    ],
  })

  setTimeout(() => chart?.resize(), 60)
}

function disposeChart() {
  if (chart) {
    chart.dispose()
    chart = null
  }
}

function refresh() {
  if (searchCode.value) loadStock()
}

function ringOffset(confidence?: number): number {
  const value = Math.max(0, Math.min(100, Number(confidence ?? 0)))
  return ringDash * (1 - value / 100)
}

function signedNumber(value: number): string {
  if (!Number.isFinite(value)) return '-'
  return `${value > 0 ? '+' : ''}${value.toFixed(2)}`
}

function formatNumber(value?: number | null, digits = 2): string {
  const number = Number(value)
  if (!Number.isFinite(number)) return '-'
  return number.toFixed(digits)
}

function formatPrice(value?: number): string {
  const number = Number(value)
  if (!Number.isFinite(number) || number <= 0) return '-'
  return number.toFixed(2)
}

function formatPercent(value?: number): string {
  const number = Number(value)
  if (!Number.isFinite(number)) return '-'
  return `${number > 0 ? '+' : ''}${number.toFixed(2)}%`
}

function formatRankChange(value?: number): string {
  const number = Number(value)
  if (!Number.isFinite(number) || number === 0) return '0.00%'
  return `${number > 0 ? '+' : ''}${number.toFixed(2)}%`
}

function formatMoney(value?: number): string {
  const number = Number(value)
  if (!Number.isFinite(number)) return '-'
  const abs = Math.abs(number)
  if (abs >= 1e8) return `${(number / 1e8).toFixed(2)}亿`
  if (abs >= 1e4) return `${(number / 1e4).toFixed(2)}万`
  return number.toFixed(0)
}

function formatTime(timestamp: number): string {
  const date = new Date(timestamp)
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}:${String(date.getSeconds()).padStart(2, '0')}`
}

function signalText(signal?: string): string {
  if (signal === 'buy') return '买入'
  if (signal === 'sell') return '卖出'
  if (signal === 'none') return '无信号'
  return '持有'
}

function stageText(stage?: string): string {
  return stage ? stageLabels[stage] ?? stage : '-'
}

function regimeText(regime?: string): string {
  return regime ? regimeLabels[regime] ?? regime : '-'
}

function crossText(cross?: string): string {
  if (cross === 'golden') return '金叉'
  if (cross === 'death') return '死叉'
  return '无'
}

function sampleQualityText(rankTrend: RankTrendResult | null): string {
  const quality = rankTrend?.meta?.sampleQuality
  if (!quality) return '实时计算'
  return `${quality.snapshotType} · ${quality.sampleCount}/${quality.requiredSampleCount} · ${quality.status}`
}

function signalClass(signal?: string): string {
  if (signal === 'buy') return 'is-buy'
  if (signal === 'sell') return 'is-sell'
  return 'is-hold'
}

function tierClass(tier?: string): string {
  return tier ? `tier-${tier}` : 'tier-empty'
}

function changeClass(value?: number): string {
  const number = Number(value)
  if (number > 0) return 'positive'
  if (number < 0) return 'negative'
  return 'neutral'
}

function rankChangeClass(value?: number): string {
  const number = Number(value)
  if (number > 0) return 'positive'
  if (number < 0) return 'negative'
  return 'neutral'
}

function numberClass(value?: number): string {
  const number = Number(value)
  if (number > 0) return 'positive'
  if (number < 0) return 'negative'
  return 'neutral'
}

function crossClass(cross?: string): string {
  if (cross === 'golden') return 'positive'
  if (cross === 'death') return 'negative'
  return 'neutral'
}

watch(
  () => [props.visible, props.stockCode],
  ([visible, stockCode]) => {
    if (!visible) return
    const code = normalizeCode(String(stockCode || ''))
    if (code) {
      searchCode.value = code
      loadStock()
    }
  },
  { immediate: true },
)

onMounted(() => {
  resizeHandler = () => chart?.resize()
  window.addEventListener('resize', resizeHandler)
})

onUnmounted(() => {
  if (resizeHandler) window.removeEventListener('resize', resizeHandler)
  disposeChart()
})
</script>

<style scoped>
.rank-trend-panel {
  position: fixed;
  width: 620px;
  max-width: calc(100vw - 32px);
  max-height: 88vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  color: var(--text-primary);
  background: #17191d;
  border: 1px solid rgba(150, 160, 180, 0.22);
  border-radius: 12px;
  box-shadow: 0 18px 50px rgba(0, 0, 0, 0.42);
  z-index: 10006;
}

.panel-header,
.panel-footer,
.search-bar,
.config-card {
  flex: 0 0 auto;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 16px;
  background: #1d2025;
  border-bottom: 1px solid rgba(150, 160, 180, 0.16);
}

.header-title {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.header-title h3 {
  margin: 0;
  font-size: 15px;
  line-height: 1.3;
  color: #f3f5f8;
}

.header-title span {
  display: block;
  margin-top: 2px;
  font-size: 11px;
  color: #8f98a8;
}

.panel-actions {
  display: flex;
  gap: 8px;
}

.ghost-btn,
.icon-btn,
.primary-btn {
  height: 30px;
  border: 1px solid rgba(150, 160, 180, 0.24);
  color: #dce2ea;
  background: #242830;
  cursor: pointer;
}

.ghost-btn {
  padding: 0 12px;
  border-radius: 8px;
}

.icon-btn {
  width: 30px;
  border-radius: 8px;
  font-size: 16px;
}

.primary-btn {
  min-width: 64px;
  padding: 0 16px;
  border-color: #4db6ac;
  border-radius: 8px;
  background: #4db6ac;
  color: #071313;
  font-weight: 700;
}

.ghost-btn:hover,
.icon-btn:hover {
  border-color: #4db6ac;
}

.icon-btn.loading {
  color: #4db6ac;
}

.rotate-animation,
.icon-btn.loading {
  animation: rotate 1s linear infinite;
}

.search-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  background: #17191d;
  border-bottom: 1px solid rgba(150, 160, 180, 0.12);
}

.snapshot-select {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 112px;
  color: #8f98a8;
  font-size: 11px;
}

.search-input {
  flex: 1;
  min-width: 0;
  height: 32px;
  padding: 0 12px;
  color: #f3f5f8;
  background: #22262d;
  border: 1px solid rgba(150, 160, 180, 0.22);
  border-radius: 8px;
  outline: none;
}

.search-input:focus {
  border-color: #4db6ac;
}

.snapshot-input {
  height: 32px;
  padding: 0 10px;
  color: #f3f5f8;
  background: #22262d;
  border: 1px solid rgba(150, 160, 180, 0.22);
  border-radius: 8px;
  outline: none;
}

.snapshot-input:focus {
  border-color: #4db6ac;
}

.config-card {
  padding: 12px 16px 14px;
  background: #17191d;
  border-bottom: 1px solid rgba(150, 160, 180, 0.12);
}

.config-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.config-head strong {
  display: block;
  color: #f3f5f8;
  font-size: 13px;
}

.config-head span {
  display: block;
  margin-top: 3px;
  color: #8f98a8;
  font-size: 11px;
}

.config-actions {
  display: flex;
  gap: 8px;
}

.config-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}

.config-summary span {
  padding: 4px 8px;
  color: #c7ced8;
  font-size: 11px;
  border: 1px solid rgba(150, 160, 180, 0.14);
  border-radius: 999px;
  background: #202329;
}

.config-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin-top: 12px;
}

.config-field {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.config-field.wide {
  grid-column: span 3;
}

.config-field span {
  color: #a8b0bd;
  font-size: 11px;
}

.config-field small {
  color: #717b8d;
  font-size: 10px;
}

.config-field input {
  height: 32px;
  padding: 0 10px;
  color: #f3f5f8;
  background: #22262d;
  border: 1px solid rgba(150, 160, 180, 0.22);
  border-radius: 8px;
  outline: none;
}

.config-field input:focus {
  border-color: #4db6ac;
}

.panel-content {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 14px;
}

.hero-card,
.strategy-card,
.signal-card,
.market-card,
.history-card,
.notice-card {
  margin-bottom: 12px;
  border: 1px solid rgba(150, 160, 180, 0.16);
  border-radius: 10px;
  background: #202329;
}

.hero-card {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 176px;
  gap: 16px;
  padding: 16px;
  border-left: 4px solid #8f98a8;
}

.hero-card.tier-main_confirmed {
  border-left-color: #ff6b6b;
}

.hero-card.tier-ignition_watch {
  border-left-color: #facc15;
}

.hero-card.tier-strong_money {
  border-left-color: #38bdf8;
}

.hero-card.tier-new_watch {
  border-left-color: #2dd4bf;
}

.hero-card.tier-crowded {
  border-left-color: #f8fafc;
}

.hero-card.tier-money_divergence {
  border-left-color: #c084fc;
}

.hero-card.tier-weakening {
  border-left-color: #4db6ac;
}

.hero-card.tier-insufficient {
  border-left-color: #9ca3af;
}

.stock-row,
.decision-row,
.section-head,
.metric-stack div,
.market-grid article,
.signal-grid article,
.context-grid article {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.stock-code {
  font-size: 22px;
  font-weight: 800;
  letter-spacing: 0;
  color: #f6f8fb;
}

.stock-name,
.eyebrow,
.price-block span,
.metric-stack span,
.section-head span,
.context-grid span,
.context-grid small,
.market-grid span,
.signal-grid small,
.notice-card,
.panel-footer {
  color: #8f98a8;
}

.price-block {
  text-align: right;
}

.price-block strong {
  display: block;
  color: #f6f8fb;
  font-size: 18px;
}

.decision-row {
  margin-top: 18px;
}

.decision-row h2 {
  margin: 4px 0 0;
  font-size: 30px;
  line-height: 1.1;
  color: #f6f8fb;
}

.action-badge,
.tag-row span,
.tier-badge {
  border: 1px solid rgba(150, 160, 180, 0.18);
  border-radius: 999px;
  background: #17191d;
}

.action-badge {
  padding: 7px 12px;
  color: #4db6ac;
  font-weight: 700;
  white-space: nowrap;
}

.tag-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 14px;
}

.tag-row span {
  padding: 4px 9px;
  color: #c7ced8;
  font-size: 12px;
}

.hero-right {
  display: grid;
  grid-template-columns: 78px minmax(0, 1fr);
  gap: 14px;
  align-items: center;
}

.confidence-ring {
  color: #4db6ac;
  text-align: center;
}

.confidence-ring svg {
  width: 76px;
  height: 76px;
}

.ring-bg,
.ring-value {
  fill: none;
  stroke-width: 6;
}

.ring-bg {
  stroke: rgba(150, 160, 180, 0.18);
}

.ring-value {
  stroke: currentColor;
  stroke-linecap: round;
  transform: rotate(-90deg);
  transform-origin: 38px 38px;
}

.confidence-ring text {
  fill: currentColor;
  font-size: 15px;
  font-weight: 800;
}

.confidence-ring span {
  display: block;
  margin-top: 2px;
  color: #8f98a8;
  font-size: 11px;
}

.metric-stack {
  display: grid;
  gap: 8px;
}

.metric-stack strong {
  color: #f6f8fb;
}

.strategy-card,
.signal-card,
.market-card,
.history-card,
.notice-card {
  padding: 14px;
}

.section-head {
  margin-bottom: 12px;
}

.section-head.compact {
  margin-bottom: 10px;
}

.section-head h4 {
  margin: 0;
  font-size: 13px;
  color: #f6f8fb;
}

.section-head span,
.section-head small {
  display: block;
  margin-top: 3px;
  font-size: 11px;
  color: #8f98a8;
}

.tier-badge {
  padding: 5px 10px;
  color: #f6f8fb;
  font-size: 12px;
  font-weight: 700;
}

.tier-badge.tier-A_MAIN,
.tier-badge.tier-B_IGNITION {
  color: #ff8f8f;
}

.tier-badge.tier-C_CROWDED {
  color: #f5b84b;
}

.tier-badge.tier-D_EXIT_RISK {
  color: #73d6cb;
}

.context-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.context-grid article,
.market-grid article,
.signal-grid article {
  min-width: 0;
  padding: 10px;
  background: #17191d;
  border: 1px solid rgba(150, 160, 180, 0.12);
  border-radius: 8px;
}

.context-grid article {
  display: block;
}

.context-grid strong {
  display: block;
  margin: 7px 0 4px;
  color: #f6f8fb;
  font-size: 18px;
}

.context-grid small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.momentum-card {
  margin-top: 12px;
  padding: 12px;
  background: #17191d;
  border: 1px solid rgba(150, 160, 180, 0.12);
  border-radius: 8px;
}

.momentum-list {
  display: grid;
  gap: 8px;
}

.momentum-row {
  display: grid;
  grid-template-columns: 58px minmax(0, 1fr) 54px;
  gap: 10px;
  align-items: center;
  font-size: 12px;
}

.momentum-row span {
  color: #a8b0bd;
}

.momentum-row strong {
  text-align: right;
  font-family: Consolas, monospace;
}

.momentum-track {
  height: 7px;
  overflow: hidden;
  background: #2b3038;
  border-radius: 999px;
}

.momentum-track i {
  display: block;
  height: 100%;
  min-width: 4px;
  border-radius: inherit;
}

.momentum-track i.positive {
  background: #ff6b6b;
}

.momentum-track i.negative {
  background: #4db6ac;
}

.momentum-track i.neutral {
  background: #8f98a8;
}

.reason-list {
  display: grid;
  gap: 7px;
  margin-top: 12px;
}

.reason-item {
  padding: 8px 10px;
  color: #cbd2dd;
  background: #17191d;
  border: 1px solid rgba(150, 160, 180, 0.12);
  border-radius: 8px;
  font-size: 12px;
  line-height: 1.45;
}

.signal-grid,
.market-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.signal-grid article,
.market-grid article {
  min-height: 58px;
}

.signal-grid article {
  display: grid;
  grid-template-columns: 1fr auto;
  grid-template-rows: auto auto;
}

.signal-grid span {
  color: #a8b0bd;
}

.signal-grid strong,
.market-grid strong {
  color: #f6f8fb;
}

.signal-grid small {
  grid-column: 1 / -1;
}

.market-grid article {
  display: block;
}

.market-grid strong {
  display: block;
  margin-top: 8px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.history-chart {
  width: 100%;
  height: 150px;
  background: #17191d;
  border: 1px solid rgba(150, 160, 180, 0.12);
  border-radius: 8px;
}

.state-view {
  min-height: 260px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 24px;
  text-align: center;
  color: #8f98a8;
}

.state-view strong {
  color: #f6f8fb;
}

.error-view strong {
  color: #ff8f8f;
}

.loading-spinner {
  width: 34px;
  height: 34px;
  border: 3px solid rgba(150, 160, 180, 0.18);
  border-top-color: #4db6ac;
  border-radius: 50%;
  animation: rotate 1s linear infinite;
}

.panel-footer {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 16px;
  background: #1d2025;
  border-top: 1px solid rgba(150, 160, 180, 0.14);
  font-size: 11px;
}

.positive,
.is-buy {
  color: #ff6b6b !important;
}

.negative,
.is-sell {
  color: #4db6ac !important;
}

.neutral,
.is-hold {
  color: #f5b84b !important;
}

@keyframes rotate {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 640px) {
  .rank-trend-panel {
    width: calc(100vw - 18px);
    max-width: calc(100vw - 18px);
  }

  .search-bar,
  .config-head,
  .config-actions {
    flex-direction: column;
    align-items: stretch;
  }

  .config-grid {
    grid-template-columns: 1fr;
  }

  .config-field.wide {
    grid-column: span 1;
  }

  .hero-card {
    grid-template-columns: 1fr;
  }

  .hero-right {
    grid-template-columns: 86px minmax(0, 1fr);
  }

  .context-grid,
  .signal-grid,
  .market-grid {
    grid-template-columns: 1fr;
  }
}
</style>
