<template>
  <Teleport to="body">
    <div v-if="visible" ref="panelRef" class="backtest-panel" :style="panelStyle">
      <header class="panel-header">
        <div>
          <h3>排名趋势策略回测 v2</h3>
          <p>候选池后验验证优先，交易模拟仅作辅助</p>
        </div>
        <button class="btn-icon" type="button" @click="close">×</button>
      </header>

      <section class="control-bar">
        <label>
          快照类型
          <select v-model="snapshotType">
            <option v-for="type in snapshotTypes" :key="type" :value="type">
              {{ snapshotTypeLabel(type) }}
            </option>
          </select>
        </label>
        <label>
          开始日期
          <input v-model="startDate" type="date" />
        </label>
        <label>
          结束日期
          <input v-model="endDate" type="date" />
        </label>
        <label class="check-line">
          <input v-model="enableTradeSimulation" type="checkbox" />
          交易模拟
        </label>
        <button class="btn-run" type="button" :disabled="loading" @click="runBacktest">
          {{ loading ? '运行中...' : '运行回测' }}
        </button>
      </section>

      <nav class="panel-tabs">
        <button
          v-for="tab in tabs"
          :key="tab.value"
          type="button"
          :class="{ active: activeTab === tab.value }"
          @click="activeTab = tab.value"
        >
          {{ tab.label }}
        </button>
      </nav>

      <main class="panel-content">
        <div v-if="errorMessage" class="notice error">{{ errorMessage }}</div>

        <div v-if="!result && !loading" class="empty-state">
          选择快照范围后运行回测。
        </div>

        <div v-if="loading" class="empty-state">
          正在按历史快照重放排名趋势策略...
        </div>

        <template v-if="result && !loading">
          <section v-show="activeTab === 'quality'" class="view-stack">
            <div class="summary-grid">
              <article class="metric-card">
                <span class="metric-label">样本质量</span>
                <strong :class="qualityClass">{{ qualityText }}</strong>
              </article>
              <article class="metric-card">
                <span class="metric-label">快照数量</span>
                <strong>{{ result.meta.snapshotCount }}</strong>
              </article>
              <article class="metric-card">
                <span class="metric-label">交易日覆盖</span>
                <strong>{{ result.meta.tradingDateCount }}</strong>
              </article>
              <article class="metric-card">
                <span class="metric-label">候选信号</span>
                <strong>{{ result.distribution.totalSignals }}</strong>
              </article>
            </div>

            <section class="report-section">
              <h4>样本信息</h4>
              <div class="info-grid">
                <span>快照类型</span>
                <strong>{{ result.meta.snapshotTypeUsed ? snapshotTypeLabel(result.meta.snapshotTypeUsed) : '-' }}</strong>
                <span>日期范围</span>
                <strong>{{ dateRangeText }}</strong>
                <span>delayed/restored</span>
                <strong>{{ result.meta.delayedCount }} / {{ result.meta.restoredCount }}</strong>
                <span>空热榜/低热榜</span>
                <strong>{{ result.meta.emptyHotlistCount }} / {{ result.meta.lowHotlistCount }}</strong>
                <span>投影覆盖</span>
                <strong>{{ result.meta.featureCoverage }}</strong>
              </div>
            </section>

            <section v-if="allWarnings.length" class="report-section">
              <h4>质量警告</h4>
              <ul class="warning-list">
                <li v-for="warning in allWarnings" :key="warning">{{ warning }}</li>
              </ul>
            </section>

            <section class="core-conclusions">
              <article v-for="card in conclusionCards" :key="card.key" class="conclusion-card">
                <span>{{ card.label }}</span>
                <strong>{{ card.value }}</strong>
                <small>{{ card.detail }}</small>
              </article>
            </section>
          </section>

          <section v-show="activeTab === 'distribution'" class="view-stack">
            <section class="report-section">
              <h4>候选池分布</h4>
              <div class="tier-bars">
                <div v-for="row in result.distribution.byTier" :key="row.key" class="tier-row">
                  <span>{{ tierLabel(row.key) }}</span>
                  <div class="bar-track">
                    <i :style="{ width: `${row.share * 100}%` }"></i>
                  </div>
                  <strong>{{ row.count }}</strong>
                  <em>{{ formatPercent(row.share) }}</em>
                </div>
              </div>
            </section>

            <section class="report-section">
              <h4>市场环境</h4>
              <div class="compact-table">
                <div class="table-head four-cols">
                  <span>环境</span>
                  <span>数量</span>
                  <span>占比</span>
                  <span>说明</span>
                </div>
                <div v-for="row in result.distribution.byRegime" :key="row.key" class="table-row four-cols">
                  <span>{{ regimeLabel(row.key) }}</span>
                  <strong>{{ row.count }}</strong>
                  <span>{{ formatPercent(row.share) }}</span>
                  <span>{{ row.key === 'weak' || row.key === 'retreat' ? 'A/B 应收缩' : '可正常观察' }}</span>
                </div>
              </div>
            </section>

            <section class="report-section">
              <h4>每日分布</h4>
              <div class="compact-table">
                <div class="table-head daily-cols">
                  <span>日期</span>
                  <span>总数</span>
                  <span>A</span>
                  <span>B</span>
                  <span>C</span>
                  <span>D</span>
                  <span>N</span>
                </div>
                <div
                  v-for="day in result.distribution.daily.slice(-20)"
                  :key="day.tradingDate"
                  class="table-row daily-cols"
                >
                  <span>{{ day.tradingDate }}</span>
                  <strong>{{ day.total }}</strong>
                  <span>{{ day.tiers.A_MAIN }}</span>
                  <span>{{ day.tiers.B_IGNITION }}</span>
                  <span>{{ day.tiers.C_CROWDED }}</span>
                  <span>{{ day.tiers.D_EXIT_RISK }}</span>
                  <span>{{ day.tiers.N_NEUTRAL }}</span>
                </div>
              </div>
            </section>
          </section>

          <section v-show="activeTab === 'validation'" class="view-stack">
            <section class="report-section">
              <h4>核心转化</h4>
              <div class="summary-grid small">
                <article class="metric-card">
                  <span class="metric-label">B 转 A</span>
                  <strong>{{ formatPercent(result.forwardValidation.bToATransitionRate) }}</strong>
                </article>
                <article class="metric-card">
                  <span class="metric-label">D 后续衰退</span>
                  <strong>{{ formatPercent(result.forwardValidation.dDecayRate) }}</strong>
                </article>
                <article class="metric-card">
                  <span class="metric-label">弱市 A/B</span>
                  <strong>{{ formatPercent(result.distribution.weakRetreatABShare) }}</strong>
                </article>
              </div>
            </section>

            <section
              v-for="horizon in result.forwardValidation.horizons"
              :key="horizon.horizon"
              class="report-section"
            >
              <h4>后续 {{ horizon.horizon }} 个快照点</h4>
              <div class="compact-table">
                <div class="table-head outcome-cols">
                  <span>分层</span>
                  <span>样本</span>
                  <span>留榜</span>
                  <span>排名变化</span>
                  <span>分位变化</span>
                  <span>涨跌幅</span>
                  <span>前50</span>
                </div>
                <div v-for="row in horizon.byTier" :key="row.groupKey" class="table-row outcome-cols">
                  <span>{{ tierLabel(row.groupKey) }}</span>
                  <strong>{{ row.sampleCount }}</strong>
                  <span>{{ formatPercent(row.foundRate) }}</span>
                  <span :class="deltaClass(row.avgRankDelta)">{{ formatSigned(row.avgRankDelta) }}</span>
                  <span :class="deltaClass(row.avgPercentileDelta)">{{ formatSigned(row.avgPercentileDelta) }}</span>
                  <span :class="deltaClass(row.avgPriceReturn)">{{ formatSigned(row.avgPriceReturn, '%') }}</span>
                  <span>{{ formatPercent(row.stayedTop50Rate) }}</span>
                </div>
              </div>
            </section>
          </section>

          <section v-show="activeTab === 'trading'" class="view-stack">
            <div v-if="!result.tradeSimulation" class="empty-state">
              勾选交易模拟后重新运行。
            </div>
            <template v-else>
              <div class="summary-grid">
                <article class="metric-card">
                  <span class="metric-label">模拟收益</span>
                  <strong :class="deltaClass(result.tradeSimulation.totalReturn)">
                    {{ formatSigned(result.tradeSimulation.totalReturn, '%') }}
                  </strong>
                </article>
                <article class="metric-card">
                  <span class="metric-label">最大回撤</span>
                  <strong class="negative">{{ formatSigned(result.tradeSimulation.maxDrawdown, '%') }}</strong>
                </article>
                <article class="metric-card">
                  <span class="metric-label">胜率</span>
                  <strong>{{ result.tradeSimulation.winRate.toFixed(1) }}%</strong>
                </article>
                <article class="metric-card">
                  <span class="metric-label">交易数</span>
                  <strong>{{ result.tradeSimulation.tradeCount }}</strong>
                </article>
              </div>

              <section class="report-section">
                <h4>交易记录</h4>
                <div class="compact-table">
                  <div class="table-head trade-cols">
                    <span>代码</span>
                    <span>名称</span>
                    <span>收益</span>
                    <span>利润</span>
                    <span>原因</span>
                  </div>
                  <div
                    v-for="trade in result.tradeSimulation.trades.slice(-30)"
                    :key="`${trade.code}-${trade.entrySnapshotId}-${trade.exitSnapshotId}`"
                    class="table-row trade-cols"
                  >
                    <span>{{ trade.code }}</span>
                    <strong>{{ trade.name }}</strong>
                    <span :class="deltaClass(trade.netReturn)">{{ formatSigned(trade.netReturn, '%') }}</span>
                    <span :class="deltaClass(trade.profit)">{{ formatSigned(trade.profit) }}</span>
                    <span>{{ trade.reason }}</span>
                  </div>
                </div>
              </section>
            </template>
          </section>
        </template>
      </main>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { usePanel } from '@/composables/usePanel'
import {
  DEFAULT_RANK_TREND_SNAPSHOT_TYPE,
  getRankTrendSnapshotLabel,
  RANK_TREND_SNAPSHOT_TYPES,
  type RankTrendSnapshotType,
} from '@/type/rankTrendDefaults'
import {
  strategyBacktest,
  type StrategyBacktestReport,
} from '@/services/strategyBacktest'

const props = defineProps<{ visible: boolean; triggerRect?: DOMRect }>()
const emit = defineEmits<{ (e: 'update:visible', value: boolean): void; (e: 'close'): void }>()

const { panelRef, panelStyle } = usePanel({
  name: 'BacktestPanel',
  visible: props.visible,
  triggerRect: props.triggerRect,
  triggerSelectors: ['[title*="回测"]'],
  onClose: () => close(),
})

const tabs = [
  { value: 'quality', label: '样本质量' },
  { value: 'distribution', label: '候选池分布' },
  { value: 'validation', label: '后验验证' },
  { value: 'trading', label: '交易模拟' },
] as const

const snapshotTypes = RANK_TREND_SNAPSHOT_TYPES
const activeTab = ref<(typeof tabs)[number]['value']>('quality')
const snapshotType = ref<RankTrendSnapshotType>(DEFAULT_RANK_TREND_SNAPSHOT_TYPE)
const startDate = ref('')
const endDate = ref('')
const enableTradeSimulation = ref(false)
const loading = ref(false)
const errorMessage = ref('')
const result = ref<StrategyBacktestReport | null>(null)

const qualityText = computed(() => {
  if (!result.value) return '-'
  const map = { ok: '良好', degraded: '降级', insufficient: '不足' }
  return map[result.value.meta.sampleQuality]
})

const qualityClass = computed(() => {
  if (!result.value) return ''
  return result.value.meta.sampleQuality === 'ok'
    ? 'positive'
    : result.value.meta.sampleQuality === 'degraded'
      ? 'warning'
      : 'negative'
})

const dateRangeText = computed(() => {
  const range = result.value?.meta.tradingDateRange
  if (!range) return '-'
  return `${range.start || '-'} 至 ${range.end || '-'}`
})

const allWarnings = computed(() => {
  if (!result.value) return []
  return [...result.value.meta.warnings, ...result.value.distribution.warnings]
})

const conclusionCards = computed(() => {
  if (!result.value) return []
  const horizon3 = result.value.forwardValidation.horizons.find((item) => item.horizon === 3)
  const a = horizon3?.byTier.find((row) => row.groupKey === 'A_MAIN')
  const b = horizon3?.byTier.find((row) => row.groupKey === 'B_IGNITION')
  const d = horizon3?.byTier.find((row) => row.groupKey === 'D_EXIT_RISK')
  return [
    {
      key: 'a',
      label: 'A_MAIN 后验',
      value: a ? formatSigned(a.avgPercentileDelta) : '-',
      detail: `样本 ${a?.sampleCount || 0}，前50 ${formatPercent(a?.stayedTop50Rate || 0)}`,
    },
    {
      key: 'b',
      label: 'B_IGNITION 转化',
      value: formatPercent(result.value.forwardValidation.bToATransitionRate),
      detail: `样本 ${b?.sampleCount || 0}`,
    },
    {
      key: 'd',
      label: 'D_EXIT_RISK 衰退',
      value: formatPercent(result.value.forwardValidation.dDecayRate),
      detail: `样本 ${d?.sampleCount || 0}`,
    },
  ]
})

function snapshotTypeLabel(type: RankTrendSnapshotType): string {
  return getRankTrendSnapshotLabel(type)
}

async function runBacktest() {
  loading.value = true
  errorMessage.value = ''
  try {
    result.value = await strategyBacktest.run({
      snapshotTypes: [snapshotType.value],
      startDate: startDate.value || undefined,
      endDate: endDate.value || undefined,
      enableTradeSimulation: enableTradeSimulation.value,
    })
    activeTab.value = 'quality'
  } catch (error) {
    console.error('[BacktestPanel] 回测失败:', error)
    errorMessage.value = error instanceof Error ? error.message : '回测失败'
  } finally {
    loading.value = false
  }
}

function close() {
  emit('update:visible', false)
  emit('close')
}

function formatPercent(value: number): string {
  return `${((Number(value) || 0) * 100).toFixed(1)}%`
}

function formatSigned(value: number | null | undefined, suffix = ''): string {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '-'
  const n = Number(value)
  return `${n > 0 ? '+' : ''}${n.toFixed(2)}${suffix}`
}

function deltaClass(value: number | null | undefined): string {
  const n = Number(value)
  if (!Number.isFinite(n) || n === 0) return ''
  return n > 0 ? 'positive' : 'negative'
}

function tierLabel(key: string): string {
  const map: Record<string, string> = {
    A_MAIN: 'A 主升',
    B_IGNITION: 'B 点火',
    C_CROWDED: 'C 拥挤',
    D_EXIT_RISK: 'D 风险',
    N_NEUTRAL: 'N 震荡',
  }
  return map[key] || key
}

function regimeLabel(key: string): string {
  const map: Record<string, string> = {
    strong: '强势',
    normal: '常态',
    weak: '弱势',
    retreat: '退潮',
  }
  return map[key] || key
}
</script>

<style scoped>
.backtest-panel {
  position: fixed;
  width: 920px;
  max-width: 94vw;
  max-height: 86vh;
  overflow: hidden;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  box-shadow: 0 14px 34px rgba(0, 0, 0, 0.38);
  color: var(--text-primary);
  z-index: 10006;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 18px;
  border-bottom: 1px solid var(--border-color);
}

.panel-header h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
}

.panel-header p {
  margin: 4px 0 0;
  color: var(--text-secondary);
  font-size: 12px;
}

.btn-icon {
  width: 30px;
  height: 30px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  background: var(--bg-secondary);
  color: var(--text-primary);
  cursor: pointer;
}

.control-bar {
  display: grid;
  grid-template-columns: 150px 150px 150px 110px 1fr;
  gap: 10px;
  align-items: end;
  padding: 12px 18px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-secondary);
}

.control-bar label {
  display: flex;
  flex-direction: column;
  gap: 5px;
  font-size: 11px;
  color: var(--text-secondary);
}

.control-bar select,
.control-bar input[type='date'] {
  min-width: 0;
  height: 32px;
  padding: 0 8px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  background: var(--bg-primary);
  color: var(--text-primary);
}

.check-line {
  flex-direction: row !important;
  align-items: center;
  height: 32px;
  color: var(--text-primary) !important;
}

.btn-run {
  height: 34px;
  border: none;
  border-radius: 6px;
  background: var(--color-highlight);
  color: #111;
  font-weight: 700;
  cursor: pointer;
}

.btn-run:disabled {
  opacity: 0.65;
  cursor: wait;
}

.panel-tabs {
  display: flex;
  gap: 6px;
  padding: 10px 18px;
  border-bottom: 1px solid var(--border-color);
}

.panel-tabs button {
  height: 30px;
  padding: 0 12px;
  border: 1px solid transparent;
  border-radius: 6px;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
}

.panel-tabs button.active {
  border-color: var(--border-color);
  background: var(--bg-secondary);
  color: var(--text-primary);
}

.panel-content {
  max-height: calc(86vh - 174px);
  overflow: auto;
  padding: 16px 18px 20px;
}

.view-stack {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.summary-grid.small {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.metric-card,
.conclusion-card,
.report-section {
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--bg-secondary);
}

.metric-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 12px;
}

.metric-label,
.conclusion-card span {
  font-size: 12px;
  color: var(--text-secondary);
}

.metric-card strong,
.conclusion-card strong {
  font-size: 20px;
  line-height: 1.2;
}

.report-section {
  padding: 12px;
}

.report-section h4 {
  margin: 0 0 10px;
  font-size: 13px;
}

.info-grid {
  display: grid;
  grid-template-columns: 120px 1fr 120px 1fr;
  gap: 9px 12px;
  font-size: 12px;
}

.info-grid span {
  color: var(--text-secondary);
}

.warning-list {
  margin: 0;
  padding-left: 18px;
  color: #d5962d;
  font-size: 12px;
}

.core-conclusions {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.conclusion-card {
  display: flex;
  flex-direction: column;
  gap: 7px;
  padding: 12px;
}

.conclusion-card small {
  color: var(--text-secondary);
}

.tier-bars {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.tier-row {
  display: grid;
  grid-template-columns: 82px 1fr 52px 58px;
  gap: 10px;
  align-items: center;
  font-size: 12px;
}

.bar-track {
  height: 8px;
  overflow: hidden;
  border-radius: 4px;
  background: var(--bg-primary);
}

.bar-track i {
  display: block;
  height: 100%;
  background: var(--color-highlight);
}

.compact-table {
  overflow: auto;
  border: 1px solid var(--border-color);
  border-radius: 6px;
}

.table-head,
.table-row {
  display: grid;
  gap: 10px;
  align-items: center;
  min-width: 640px;
  padding: 8px 10px;
  font-size: 12px;
}

.table-head {
  position: sticky;
  top: 0;
  background: var(--bg-primary);
  color: var(--text-secondary);
  font-weight: 700;
}

.table-row {
  border-top: 1px solid var(--border-color);
}

.four-cols {
  grid-template-columns: 1fr 80px 80px 1.4fr;
}

.daily-cols {
  grid-template-columns: 120px 70px repeat(5, 54px);
}

.outcome-cols {
  grid-template-columns: 100px 70px 70px 90px 90px 80px 70px;
}

.trade-cols {
  grid-template-columns: 86px 1fr 80px 90px 1.4fr;
}

.empty-state,
.notice {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 160px;
  border: 1px dashed var(--border-color);
  border-radius: 8px;
  color: var(--text-secondary);
  background: var(--bg-secondary);
  font-size: 13px;
}

.notice.error {
  min-height: auto;
  justify-content: flex-start;
  padding: 10px 12px;
  color: #e07070;
  border-style: solid;
}

.positive {
  color: #d84f45;
}

.negative {
  color: #1f9d67;
}

.warning {
  color: #d5962d;
}

@media (max-width: 760px) {
  .control-bar,
  .summary-grid,
  .summary-grid.small,
  .core-conclusions,
  .info-grid {
    grid-template-columns: 1fr;
  }
}
</style>
