<!-- src/components/panels/HotlistEmotionPanel.vue -->
<!-- 独立热榜情绪面板（2026-09-24）：与 DragonBreathPanel 完全脱钩，只消费热榜池口径
     （docs/hotlist-emotion-panel/01-口径梳理.md 全量）。展现方式对齐 SectorPanel/SectorDetail
     的界面语言（panel-header / 页签行 / 指标卡 / 表格），配色全部走主题 CSS 变量，随亮暗主题。 -->
<template>
  <Teleport to="body">
    <div v-if="visible" class="hotlist-emotion-panel" :style="panelStyle" ref="panelRef">
      <div class="panel-header">
        <div class="header-left">
          <h3>📊 热榜情绪 <span class="version-badge">v{{ version }}</span></h3>
          <span v-if="dataTimeLabel" class="time-badge" :title="timeBadgeTitle">{{ dataTimeLabel }}</span>
          <span v-if="missingDays.length" class="time-badge warn" :title="missingDaysTitle">
            窗口缺失 {{ missingDays.length }} 日
          </span>
        </div>
        <div class="panel-actions">
          <button class="btn-icon" :class="{ loading }" :disabled="loading" title="刷新" @click="loadAll">
            <span :class="{ 'rotate-animation': loading }">🔄</span>
          </button>
          <button class="btn-icon" title="关闭" @click="close">✕</button>
        </div>
      </div>

      <div class="panel-tabs">
        <div class="tabs-left">
          <button v-for="tab in TABS" :key="tab.key" class="tab-btn" :class="{ active: view === tab.key }"
            @click="view = tab.key">
            {{ tab.icon }} {{ tab.label }}
          </button>
        </div>
      </div>

      <div class="panel-content">
        <div v-if="loading && !doc" class="state-block"><span class="spinner"></span>正在加载热榜情绪…</div>
        <div v-else-if="loadError && !doc" class="state-block error">
          ⚠️ {{ loadError }}
          <button class="retry-btn" @click="loadAll">重试</button>
        </div>
        <div v-else-if="!doc" class="state-block">暂无热榜情绪数据</div>

        <template v-else>
          <!-- ① 市场概览（含涨停证据三容器 + 证据与风险 + 数据诊断） -->
          <section v-show="view === 'overview'" class="tab-pane">
            <div class="stage-hero" :class="`stage-tone-${stageTone}`">
              <div class="hero-main">
                <div class="hero-label">市场情绪阶段</div>
                <div class="hero-stage">{{ confirmedStageName }}</div>
                <div class="hero-meta">
                  <span class="risk-chip" :class="`risk-${riskTone}`">{{ doc.riskLevel }}风险</span>
                  <span class="conf-chip">盘面置信 {{ doc.confidence }}%</span>
                  <span v-if="pendingBadge" class="pending-chip"
                    :title="`盘中出现「${pendingBadge.rawStage}」迹象（自 ${pendingBadge.pendingSince} 起），连续 ${pendingBadge.confirmSlots} 槽成立后切换`">
                    情绪波动：现{{ pendingBadge.rawStage }}迹象
                  </span>
                </div>
                <div class="hero-summary">盘面证据：{{ doc.summary }}</div>
              </div>
            </div>

            <div class="metrics-grid">
              <div v-for="card in primaryCards" :key="card.label" class="metric-card">
                <div class="metric-icon">{{ card.icon }}</div>
                <div class="metric-content">
                  <div class="metric-label">{{ card.label }}</div>
                  <div class="metric-value" :class="card.toneClass">{{ card.value }}</div>
                </div>
              </div>
            </div>

            <div class="funds-grid">
              <div v-for="card in fundCards" :key="card.label" class="fund-card">
                <div class="fund-icon">{{ card.icon }}</div>
                <div class="fund-content">
                  <div class="fund-label">{{ card.label }}</div>
                  <div class="fund-value" :class="card.toneClass">{{ card.value }}</div>
                </div>
              </div>
            </div>

            <div class="stats-grid">
              <div v-for="card in statCards" :key="card.label" class="stat-card">
                <div class="stat-icon">{{ card.icon }}</div>
                <div class="stat-value" :class="card.toneClass">{{ card.value }}</div>
                <div class="stat-label">{{ card.label }}</div>
              </div>
            </div>

            <div class="sub-block clickable" @click="openLimitStocks('pool', $event)">
              <div class="block-header">
                <span class="block-title">🔥 热榜池涨停交集</span>
                <span class="section-count">{{ intersectionCards.length }}</span>
              </div>
              <div class="grid-4">
                <div v-for="item in intersectionCards" :key="item.label" class="fund-card">
                  <div class="fund-content">
                    <div class="fund-label">{{ item.label }}</div>
                    <div class="fund-value" :class="item.toneClass">{{ item.value }}</div>
                  </div>
                </div>
              </div>
            </div>

            <div class="sub-block clickable" @click="openLimitStocks('market', $event)">
              <div class="block-header">
                <span class="block-title">🌐 全市场背景（非热榜池口径）</span>
                <span class="section-count">{{ marketCards.length }}</span>
              </div>
              <div class="grid-6">
                <div v-for="item in marketCards" :key="item.label" class="fund-card">
                  <div class="fund-content">
                    <div class="fund-label">{{ item.label }}</div>
                    <div class="fund-value" :class="item.toneClass">{{ item.value }}</div>
                  </div>
                </div>
              </div>
              <div v-if="marketEvidenceNote" class="note-line">{{ marketEvidenceNote }}</div>
            </div>

            <div class="sub-block clickable" @click="openLimitStocks('yesterday', $event)">
              <div class="block-header">
                <span class="block-title">📜 昨日热榜涨停表现</span>
                <span class="section-count">{{ yesterdayLimitCards.length }}</span>
              </div>
              <div class="grid-6">
                <div v-for="item in yesterdayLimitCards" :key="item.label" class="fund-card">
                  <div class="fund-content">
                    <div class="fund-label">{{ item.label }}</div>
                    <div class="fund-value" :class="item.toneClass">{{ item.value }}</div>
                  </div>
                </div>
              </div>
            </div>

            <div class="evidence-columns two">
              <div class="sub-block">
                <div class="block-title up-text">✅ 强证据</div>
                <ul class="evidence-list">
                  <li v-for="signal in doc.signals" :key="signal">{{ signal }}</li>
                  <li v-if="!doc.signals.length" class="empty-row">暂无强证据</li>
                </ul>
              </div>
              <div class="sub-block">
                <div class="block-title down-text">⚠️ 风险提示</div>
                <ul class="evidence-list">
                  <li v-for="warning in doc.warnings" :key="warning">{{ warning }}</li>
                  <li v-if="!doc.warnings.length" class="empty-row">暂无风险提示</li>
                </ul>
              </div>
            </div>
            <div v-if="diagnostics.length" class="diag-block">
              <span class="diag-tag">数据诊断</span>
              <span v-for="item in diagnostics" :key="item" class="diag-item">{{ item }}</span>
            </div>
          </section>

          <!-- ② 分层结构（ECharts：多日分层对比，语言同情绪趋势/历史对比；超大单净额全 0 不展示） -->
          <section v-show="view === 'layers'" class="tab-pane">
            <div class="time-range-selector">
              <button v-for="range in LAYER_RANGES" :key="range.key" class="time-btn"
                :class="{ active: layersRange === range.key }" @click="setLayersRange(range.key)">
                {{ range.label }}
              </button>
            </div>
            <div class="indicator-selector">
              <button v-for="layer in LAYERS" :key="layer.key" class="indicator-btn"
                :class="{ active: layersLayer === layer.key }" @click="setLayersLayer(layer.key)">
                🧱 {{ layer.label }}
              </button>
            </div>
            <div class="indicator-selector">
              <button v-for="ind in LAYER_INDICATORS" :key="ind.key" class="indicator-btn"
                :class="{ active: layersIndicators.includes(ind.key) }" @click="toggleLayerIndicator(ind.key)">
                {{ ind.icon }} {{ ind.label }}
              </button>
            </div>
            <div v-if="layersNote" class="note-line">{{ layersNote }}</div>
            <div v-if="!layerPoints.length" class="empty-row">暂无分层数据</div>
            <template v-else>
              <div class="trend-chart" ref="layersChartRef"></div>
              <div class="trend-stats-grid">
                <div v-for="card in layerStats" :key="card.label" class="trend-stat-card">
                  <div class="stat-label">{{ card.label }}</div>
                  <div class="stat-value">{{ card.value }}</div>
                  <div class="stat-time">{{ card.sub }}</div>
                </div>
              </div>
            </template>
          </section>

          <!-- ③b 池换手（分池+出池合并明细，成分股列表风格） -->
          <section v-show="view === 'turnover'" class="tab-pane">
            <div class="sub-block">
              <div class="block-title">🔁 池换手汇总</div>
              <div class="turnover-chips">
                <span class="chip">昨池 {{ turnover.previousPoolSize }}</span>
                <span class="chip">今池 {{ turnover.currentPoolSize }}</span>
                <span class="chip">留存 {{ turnover.retainedFromYesterday }}</span>
                <span class="chip up-text">新入 {{ doc.metrics.comparison.newTop100Count }}</span>
                <span class="chip down-text">剔除 {{ eliminatedCount }}</span>
              </div>
            </div>
            <div class="to-header">
              <div class="to-filters">
                <button class="to-filter-btn" :class="{ active: turnoverFilter === 'all' }"
                  @click="turnoverFilter = 'all'">全部</button>
                <button class="to-filter-btn" :class="{ active: turnoverFilter === 'entry' }"
                  @click="turnoverFilter = 'entry'">新入</button>
                <button class="to-filter-btn" :class="{ active: turnoverFilter === 'exit' }"
                  @click="turnoverFilter = 'exit'">剔除</button>
              </div>
              <span class="to-stats">
                新入 {{ entryDetails.length }} · 剔除 {{ exitDetails.length }} · 显示 {{ filteredTurnoverRows.length }} 只
              </span>
            </div>
            <div class="to-table-container" v-if="filteredTurnoverRows.length">
              <table class="to-table">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>代码</th>
                    <th>名称</th>
                    <th>涨跌幅</th>
                    <th>排名</th>
                    <th>变动</th>
                    <th>变动原因</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(row, i) in filteredTurnoverRows" :key="`${row.kind}-${row.code}`"
                    :class="{ 'entry-row': row.kind === 'entry' }">
                    <td>{{ i + 1 }}</td>
                    <td><span class="to-code">{{ row.code }}</span></td>
                    <td>{{ resolveStockName(row) }}</td>
                    <td class="num change" :class="row.changePct >= 0 ? 'up-text' : 'down-text'">
                      {{ row.changePct > 0 ? '+' : '' }}{{ (row.changePct || 0).toFixed(2) }}%
                    </td>
                    <td class="num">{{ row.rank }}</td>
                    <td>
                      <span class="to-kind-badge" :class="row.kind === 'entry' ? 'entry' : 'exit'">
                        {{ row.kind === 'entry' ? '新入' : '剔除' }}
                      </span>
                    </td>
                    <td>
                      <span class="to-reason" :title="row.reasonDetail || ''">{{ row.reasonDetail || '--' }}</span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div v-else class="empty-row">暂无换手明细</div>
          </section>

          <!-- ④ 阶段分布（左环形图 + 右排序明细列表） -->
          <section v-show="view === 'structure'" class="tab-pane">
            <div class="sub-block">
              <div class="block-header">
                <span class="block-title">🧭 全池阶段分布（今日快照池）</span>
                <span class="section-count">{{ formatNullableCount(allLayer?.topN) }}</span>
              </div>
              <div v-if="stagePieData.length" class="stage-layout">
                <div class="stage-pie">
                  <div ref="stageChartRef" class="stage-pie-canvas"></div>
                  <div class="stage-pie-center">
                    <span class="stage-pie-total">{{ stageTotal }}</span>
                    <span class="stage-pie-unit">总样本</span>
                  </div>
                </div>
                <div class="stage-detail">
                  <div v-for="item in stageList" :key="item.key" class="stage-row">
                    <span class="stage-dot" :style="{ background: item.color }"></span>
                    <span class="stage-name">{{ item.name }}</span>
                    <div class="stage-bar"><div class="stage-bar-fill" :style="{ width: item.pctText, background: item.color }"></div></div>
                    <span class="stage-count">{{ item.count }}</span>
                    <span class="stage-pct">{{ item.pctText }}</span>
                  </div>
                </div>
              </div>
              <div v-else class="empty-row">暂无阶段分布数据</div>
            </div>
            <div class="sub-block">
              <div class="block-header">
                <span class="block-title">🔀 阶段迁移（降序前 6）</span>
              </div>
              <div v-if="transitionItems.length" class="transition-grid">
                <div v-for="item in transitionItems" :key="item.key" class="metric-card">
                  <div class="metric-icon">🔀</div>
                  <div class="metric-content">
                    <div class="metric-label">{{ item.text }}</div>
                    <div class="metric-value">{{ item.count }}<span class="metric-unit">次</span></div>
                  </div>
                </div>
              </div>
              <div v-else class="empty-row">暂无迁移数据</div>
            </div>
            <div class="sub-block">
              <div class="block-title">🧾 判定来源</div>
              <div class="chip-wrap">
                <span class="chip">golden 判定 {{ statusSource.displayStatus }}</span>
                <span class="chip">fallback 接管 {{ statusSource.fallback }}</span>
                <span v-for="item in diagnostics" :key="item" class="chip diag">{{ item }}</span>
              </div>
            </div>
          </section>

          <!-- ⑤ 历史对比（ECharts：池流转/留榜/强票表现多日趋势，语言同情绪趋势） -->
          <section v-show="view === 'compare'" class="tab-pane">
            <div class="time-range-selector">
              <button v-for="range in COMPARE_RANGES" :key="range.key" class="time-btn"
                :class="{ active: compareRange === range.key }" @click="setCompareRange(range.key)">
                {{ range.label }}
              </button>
            </div>
            <div class="indicator-selector">
              <button v-for="ind in COMPARE_INDICATORS" :key="ind.key" class="indicator-btn"
                :class="{ active: compareIndicators.includes(ind.key) }" @click="toggleCompareIndicator(ind.key)">
                {{ ind.icon }} {{ ind.label }}
              </button>
            </div>
            <div v-if="compareNote" class="note-line">{{ compareNote }}</div>
            <div v-if="!comparePoints.length" class="empty-row">暂无历史对比数据</div>
            <template v-else>
              <div class="trend-chart" ref="compareChartRef"></div>
              <div class="trend-stats-grid">
                <div v-for="card in compareStats" :key="card.label" class="trend-stat-card">
                  <div class="stat-label">{{ card.label }}</div>
                  <div class="stat-value">{{ card.value }}</div>
                  <div class="stat-time">{{ card.sub }}</div>
                </div>
              </div>
            </template>
          </section>

          <!-- ⑥ 情绪趋势（ECharts：SectorDetail 历史趋势图表语言——时间范围 + 阶段铺底 + 指标开关 + 图下统计卡） -->
          <section v-show="view === 'track'" class="tab-pane">
            <div class="time-range-selector">
              <button v-for="range in TIME_RANGES" :key="range.key" class="time-btn"
                :class="{ active: timeRange === range.key }" @click="setTimeRange(range.key)">
                {{ range.label }}
              </button>
            </div>
            <div class="indicator-selector">
              <button v-for="ind in TREND_INDICATORS" :key="ind.key" class="indicator-btn"
                :class="{ active: trendIndicators.includes(ind.key) }" @click="toggleTrendIndicator(ind.key)">
                {{ ind.icon }} {{ ind.label }}
              </button>
            </div>
            <div v-if="trackNote" class="note-line">{{ trackNote }}</div>
            <div v-if="!trendPoints.length" class="empty-row">暂无趋势数据</div>
            <template v-else>
              <div class="trend-chart" ref="trendChartRef"></div>
              <div class="trend-stats-grid">
                <div v-for="card in trendStats" :key="card.label" class="trend-stat-card">
                  <div class="stat-label">{{ card.label }}</div>
                  <div class="stat-value">{{ card.value }}</div>
                  <div class="stat-time">{{ card.sub }}</div>
                </div>
              </div>
            </template>
          </section>

        </template>
      </div>

      <!-- 涨停池明细面板（Teleport 自身挂 body，层级 10007 高于本面板） -->
      <HotlistLimitStocksPanel v-if="limitStocksDetail" :visible="limitStocksDetail.visible"
        :initial-kind="limitStocksDetail.kind" :summary="doc?.metrics?.limitEvidence ?? null"
        :trigger-rect="limitStocksDetail.rect" @close="limitStocksDetail = null" />
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { dataLayer } from '@/services/DataLayer'
import {
  fetchHotlistSentimentSeries,
  fetchHotlistSentimentSlots,
  type HotlistLimitStockKind,
  type HotlistSentimentMissingDay,
} from '@/services/hotlist/hotlistSentimentApi'
import HotlistLimitStocksPanel from '@/components/panels/HotlistLimitStocksPanel.vue'
import {
  HOT_LIST_STAGE_LABELS,
  type HotListSentimentDayDoc,
  type HotListStageKey,
} from '@/types/hotlistSentiment'

const props = defineProps<{ visible: boolean; triggerRect?: DOMRect | null }>()
const emit = defineEmits<{ (e: 'close'): void }>()

const TABS = [
  { key: 'overview', label: '市场概览', icon: '📊' },
  { key: 'layers', label: '分层结构', icon: '🧱' },
  { key: 'turnover', label: '池换手', icon: '🔁' },
  { key: 'structure', label: '阶段分布', icon: '🧭' },
  { key: 'compare', label: '历史对比', icon: '🗓️' },
  { key: 'track', label: '情绪趋势', icon: '📈' },
] as const
type ViewKey = (typeof TABS)[number]['key']

const ENTRY_REASON_TEXT: Record<string, string> = {
  limit_up: '涨停入选', strong_money: '强资入选', rank_surge: '排名跃升', new_high_volume: '放量新高',
}
const EXIT_REASON_TEXT: Record<string, string> = {
  rank_out_of_range: '跌出榜单', weakening: '转弱', limit_down: '跌停',
}
// 阶段冷热两档（交易者语感）：分歧小标据此给「短暂走高/短暂回落/盘中波动」
const STAGE_HEAT: Record<string, number> = { 冰点: 0, 退潮: 0, 启动: 1, 发酵: 2, 高潮: 3 }

const view = ref<ViewKey>('overview')
const loading = ref(false)
const loadError = ref<string | null>(null)
const doc = ref<HotListSentimentDayDoc | null>(null)
const slots = ref<HotListSentimentDayDoc[]>([])
const slotsTradingDate = ref('')
const slotsDegradedReason = ref<string | null>(null)
const missingDays = ref<HotlistSentimentMissingDay[]>([])

const version = '6.0.0'

function close() {
  emit('close')
}

// ---------- 涨停池明细面板（市场概览三容器点击进入，SectorPanel→SectorDetail 交互语言） ----------
const limitStocksDetail = ref<{ visible: boolean; kind: HotlistLimitStockKind; rect: DOMRect | null } | null>(null)

function openLimitStocks(kind: HotlistLimitStockKind, event?: MouseEvent) {
  const rect = event ? (event.currentTarget as HTMLElement).getBoundingClientRect() : null
  limitStocksDetail.value = { visible: true, kind, rect }
}

const panelStyle = computed(() => {
  const rect = props.triggerRect
  if (!rect) return {}
  const width = 960
  const left = Math.max(8, Math.min(window.innerWidth - width - 8, rect.left + rect.width / 2 - width / 2))
  return { left: `${left}px`, top: `${Math.min(rect.bottom + 8, window.innerHeight - 520)}px` }
})

async function loadAll() {
  if (loading.value) return
  loading.value = true
  loadError.value = null
  try {
    const [series, slotResult] = await Promise.all([
      fetchHotlistSentimentSeries(3),
      fetchHotlistSentimentSlots().catch((err) => ({
        items: [], tradingDate: '', degraded: true, reason: err?.message || '加载失败',
      })),
    ])
    if (series.degraded || !series.items.length) {
      doc.value = null
      loadError.value = series.reason || '热榜情绪数据暂不可用'
      missingDays.value = series.missingDays
      slots.value = []
      return
    }
    missingDays.value = series.missingDays
    doc.value = series.items[series.items.length - 1]
    // 仅在缓存仍是最初 3 日窗口时覆盖：用户已切更长档位（loaded>3）时覆盖会让
    // 长窗口静默降级（seriesDaysLoaded 只增不减），此时保留长窗口缓存不动
    if (seriesDaysLoaded.value <= 3) {
      seriesDocs.value = series.items
      seriesDaysLoaded.value = 3
      seriesMissingDays.value = series.missingDays
    }
    slots.value = slotResult.items
    slotsTradingDate.value = slotResult.tradingDate
    slotsDegradedReason.value = slotResult.degraded ? slotResult.reason : null
  } catch (err) {
    loadError.value = err instanceof Error ? err.message : '加载失败'
    doc.value = null
  } finally {
    loading.value = false
  }
}

watch(
  () => props.visible,
  (visible) => {
    if (visible && !doc.value) loadAll()
  },
  { immediate: true },
)

// ---------- 基础格式化（fail-visible：缺失显示 --，不伪造 0） ----------
function formatNullableCount(value?: number | null): string {
  return typeof value === 'number' && Number.isFinite(value) ? String(Math.round(value)) : '--'
}
function formatShare(value?: number | null): string {
  return typeof value === 'number' && Number.isFinite(value) ? `${Math.round(value * 100)}%` : '--'
}
function formatPercent(value?: number | null): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '--'
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`
}
function formatTrin(value?: number | null): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(2) : '--'
}
function formatMoney(value?: number | null): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '--'
  const abs = Math.abs(value)
  if (abs >= 1e8) return `${(value / 1e8).toFixed(2)}亿`
  if (abs >= 1e4) return `${(value / 1e4).toFixed(0)}万`
  return String(Math.round(value))
}

// ---------- 顶层口径 ----------
const confirmedStageName = computed(() => doc.value?.stage ?? '--')
const stageTone = computed(() => {
  const heat = STAGE_HEAT[doc.value?.stage ?? ''] ?? 1
  return heat >= 2 ? 'hot' : heat >= 1 ? 'warm' : 'cold'
})
const riskTone = computed(() => (doc.value?.riskLevel === '高' ? 'high' : doc.value?.riskLevel === '低' ? 'low' : 'mid'))
const pendingBadge = computed(() => {
  const state = doc.value?.stageConfirmState
  if (!state?.pending || !doc.value?.rawStage) return null
  return {
    rawStage: doc.value.rawStage,
    pendingSince: state.pendingSince || '--',
    confirmSlots: state.confirmSlots,
  }
})
const diagnostics = computed(() => doc.value?.diagnostics ?? [])
const statusSource = computed(() => doc.value?.metrics.statusSourceCounts ?? { displayStatus: 0, fallback: 0 })
const turnover = computed(
  () => doc.value?.turnover ?? { previousPoolSize: 0, currentPoolSize: 0, retainedFromYesterday: 0, newEntries: [], eliminated: [], newEntryDetails: [], eliminatedDetails: [] },
)
// 名称兜底（2026-09-24）：采集行 name 可能为 "-" 占位，用行情列表名称回填展示
const stockNameMap = computed(() => {
  const map = new Map<string, string>()
  for (const stock of dataLayer.getStocks()) {
    const name = stock.name?.trim() ?? ''
    if (stock.code && name && name !== '-') map.set(stock.code, name)
  }
  return map
})
function resolveStockName(row: { code: string; name?: string | null }): string {
  const raw = (row.name || '').trim()
  if (raw && raw !== '-') return raw
  return stockNameMap.value.get(row.code) || raw || '-'
}
const entryDetails = computed(() => turnover.value.newEntryDetails ?? [])
const exitDetails = computed(() => turnover.value.eliminatedDetails ?? [])
const eliminatedCount = computed(() => turnover.value.eliminated?.length ?? 0)

// 池换手明细（分池+出池合并单表）：新入在前按涨幅降序，剔除在后按排名升序
const turnoverFilter = ref<'all' | 'entry' | 'exit'>('all')
const mergedTurnoverRows = computed(() => {
  const entries = entryDetails.value
    .slice()
    .sort((a, b) => (b.changePct ?? 0) - (a.changePct ?? 0))
    .map((row) => ({ ...row, kind: 'entry' as const, reasonDetail: ENTRY_REASON_TEXT[row.entryReason] || row.entryReason }))
  const exits = exitDetails.value
    .slice()
    .sort((a, b) => (a.rank ?? 999) - (b.rank ?? 999))
    .map((row) => ({ ...row, kind: 'exit' as const, reasonDetail: EXIT_REASON_TEXT[row.exitReason] || row.exitReason }))
  return [...entries, ...exits]
})
const filteredTurnoverRows = computed(() =>
  turnoverFilter.value === 'all'
    ? mergedTurnoverRows.value
    : mergedTurnoverRows.value.filter((row) => row.kind === turnoverFilter.value),
)
const comparison = computed(() => doc.value?.metrics.comparison ?? null)
const allLayer = computed(() => doc.value?.metrics.layers.all ?? null)

const dataTimeLabel = computed(() => {
  const slot = doc.value?.slotTime
  const anchored = doc.value?.anchoredSlotTime
  if (!doc.value) return ''
  return slot === 'EOD' ? `${doc.value.tradingDate} · 锚定 ${anchored || '--'}` : `${doc.value.tradingDate} ${slot}`
})
const timeBadgeTitle = computed(() => {
  const parts = [`snapshotId: ${doc.value?.snapshotId || '--'}`]
  if (doc.value?.stageConfirmState) parts.push(`historyStatus: ${doc.value.stageConfirmState.historyStatus}`)
  return parts.join('\n')
})
const missingDaysTitle = computed(() =>
  missingDays.value.map((d) => `${d.tradingDate || '未知日期'}：${d.reason || '缺失'}`).join('；'),
)

// 概览三级卡组（SectorDetail 概览结构）：主指标 2×2 大卡 + 资金中卡 + 统计小卡
const primaryCards = computed(() => {
  const layer = allLayer.value
  if (!layer) return []
  return [
    { icon: '📈', label: '上涨占比', value: formatShare(layer.upRatio), toneClass: 'up' },
    { icon: '📉', label: '下跌占比', value: formatShare(layer.downRatio), toneClass: 'down' },
    { icon: '⚖️', label: '热榜 TRIN', value: formatTrin(layer.hotTrin), toneClass: '' },
    { icon: '💰', label: '主力净额', value: formatMoney(layer.mainNetAmount), toneClass: (layer.mainNetAmount ?? 0) >= 0 ? 'up' : 'down' },
  ]
})
const fundCards = computed(() => {
  const layer = allLayer.value
  if (!layer) return []
  return [
    { icon: '🔥', label: '近涨停', value: formatNullableCount(layer.nearLimitUpCount), toneClass: '' },
    { icon: '🚀', label: '高涨幅≥7%', value: formatNullableCount(layer.highGainCount), toneClass: '' },
    { icon: '🌀', label: '高换手≥10%', value: formatNullableCount(layer.highTurnoverCount), toneClass: '' },
  ]
})
const statCards = computed(() => {
  const layer = allLayer.value
  const comp = comparison.value
  if (!layer) return []
  return [
    { icon: '📊', label: '参与统计', value: formatNullableCount(layer.topN), toneClass: '' },
    { icon: '🆕', label: '今日新入', value: formatNullableCount(comp?.newTop100Count ?? null), toneClass: '' },
    { icon: '💪', label: '新入强资', value: formatNullableCount(comp?.newTop100StrongMoneyCount ?? null), toneClass: '' },
    { icon: '🔁', label: '昨日强资留榜', value: formatShare(comp?.yesterdayStrongRetainRate ?? null), toneClass: '' },
  ]
})

// ---------- 分层结构（ECharts：多日分层对比，语言同历史对比；超大单净额全 0 不展示） ----------
const LAYERS = [
  { key: 'top20', label: '前20' },
  { key: 'top50', label: '前50' },
  { key: 'top100', label: '前100' },
  { key: 'all', label: '全池' },
] as const
type LayerKey = (typeof LAYERS)[number]['key']
// 分层结构时间范围：1天=最新交易日盘中半小时槽位（slots 接口对非交易日自动回落上一交易日），
// 3日/1周/1月=日线 EOD 终值
const LAYER_RANGES = [
  { key: '1d', label: '1天' },
  { key: '3d', label: '3日' },
  { key: '1w', label: '1周' },
  { key: '1m', label: '1月' },
] as const
type LayerTimeRange = (typeof LAYER_RANGES)[number]['key']
const layersRange = ref<LayerTimeRange>('1d')
const layersLayer = ref<LayerKey>('top100')
const layersChartRef = ref<HTMLElement | null>(null)
let layersChart: echarts.ECharts | null = null

// 指标开关：% 类走 % 轴，计数走数量轴，TRIN/金额各占独立轴
const LAYER_INDICATORS = [
  { key: 'upRatio', label: '涨占比', icon: '📈' },
  { key: 'downRatio', label: '跌占比', icon: '📉' },
  { key: 'avgChange', label: '平均涨幅', icon: '💹' },
  { key: 'trin', label: 'TRIN', icon: '⚖️' },
  { key: 'nearLimitUp', label: '近涨停', icon: '🔥' },
  { key: 'highGain', label: '高涨幅≥7%', icon: '🚀' },
  { key: 'highTurnover', label: '高换手≥10%', icon: '🌀' },
  { key: 'mainNet', label: '主力净额', icon: '💰' },
] as const
type LayerIndicatorKey = (typeof LAYER_INDICATORS)[number]['key']
const layersIndicators = ref<LayerIndicatorKey[]>(['upRatio', 'nearLimitUp', 'mainNet'])

// 每日/每槽位所选分层的数值点：null 缺失直传图表断线，不补 0。
// 1天=slots 最新交易日盘中槽位（label=槽位时间）；多日=series 日线 EOD 文档（label=交易日 MM-DD）
const layerPoints = computed(() => {
  const days = RANGE_DAYS[layersRange.value]
  const intraday = days === 1
  const source = intraday ? slots.value : seriesDocs.value.slice(-days)
  if (!source.length) return []
  const pct = (rate?: number | null) => (typeof rate === 'number' ? Math.round(rate * 1000) / 10 : null)
  return source.map((item, index) => {
    const m = item.metrics?.layers?.[layersLayer.value]
    return {
      label: intraday
        ? item.slotTime || `slot-${index}`
        : (item.tradingDate || '').slice(5) || `d-${index}`,
      title: intraday ? item.slotTime || `slot-${index}` : item.tradingDate || `d-${index}`,
      stage: item.stage,
      sample: m?.topN ?? null,
      upRatioPct: pct(m?.upRatio),
      downRatioPct: pct(m?.downRatio),
      avgChange: typeof m?.avgChange === 'number' ? m.avgChange : null,
      trin: typeof m?.hotTrin === 'number' ? m.hotTrin : null,
      nearLimitUp: m?.nearLimitUpCount ?? null,
      highGain: m?.highGainCount ?? null,
      highTurnover: m?.highTurnoverCount ?? null,
      mainNet: typeof m?.mainNetAmount === 'number' ? m.mainNetAmount : null,
    }
  })
})

function setLayersRange(range: LayerTimeRange) {
  if (layersRange.value === range) return
  layersRange.value = range
  void ensureSeriesDays(RANGE_DAYS[range]).then(() => nextTick(() => renderLayersChart()))
}

function setLayersLayer(layer: LayerKey) {
  if (layersLayer.value === layer) return
  layersLayer.value = layer
  nextTick(() => renderLayersChart())
}

function toggleLayerIndicator(key: LayerIndicatorKey) {
  const current = layersIndicators.value
  if (current.includes(key)) {
    if (current.length === 1) return // 至少保留一个序列，避免图表空白
    layersIndicators.value = current.filter((k) => k !== key)
  } else {
    // 按声明顺序重排，保持图例顺序稳定
    layersIndicators.value = LAYER_INDICATORS.map((i) => i.key).filter((k) => current.includes(k) || k === key)
  }
  nextTick(() => renderLayersChart())
}

const LAYER_AXIS_FMT: Record<string, (v: number | null) => string> = {
  涨占比: (v) => (v === null ? '--' : `${v.toFixed(1)}%`),
  跌占比: (v) => (v === null ? '--' : `${v.toFixed(1)}%`),
  平均涨幅: (v) => (v === null ? '--' : formatPercent(v)),
  TRIN: (v) => formatTrin(v),
  近涨停: (v) => formatNullableCount(v),
  '高涨幅≥7%': (v) => formatNullableCount(v),
  '高换手≥10%': (v) => formatNullableCount(v),
  主力净额: (v) => formatMoney(v),
}

function renderLayersChart() {
  if (!layersChartRef.value || !layerPoints.value.length) return
  // 空态 v-if 切换会卸载并重挂图表容器：旧实例绑定的 DOM 已分离，必须 dispose 后重建
  if (layersChart && layersChart.getDom() !== layersChartRef.value) {
    layersChart.dispose()
    layersChart = null
  }
  if (!layersChart) {
    layersChart = echarts.init(layersChartRef.value)
  }

  const points = layerPoints.value
  const indicators = layersIndicators.value
  const series: any[] = []
  if (indicators.includes('upRatio')) {
    series.push({
      name: '涨占比', type: 'line', data: points.map((p) => p.upRatioPct),
      smooth: true, symbol: 'circle', symbolSize: 5, connectNulls: false,
      lineStyle: { color: '#ff4757', width: 2 }, yAxisIndex: 0,
    })
  }
  if (indicators.includes('downRatio')) {
    series.push({
      name: '跌占比', type: 'line', data: points.map((p) => p.downRatioPct),
      smooth: true, symbol: 'circle', symbolSize: 5, connectNulls: false,
      lineStyle: { color: '#2ed573', width: 2 }, yAxisIndex: 0,
    })
  }
  if (indicators.includes('avgChange')) {
    series.push({
      name: '平均涨幅', type: 'line', data: points.map((p) => p.avgChange),
      smooth: true, symbol: 'diamond', symbolSize: 4, connectNulls: false,
      lineStyle: { color: '#ff7f50', width: 1.5, type: 'dashed' }, yAxisIndex: 0,
    })
  }
  if (indicators.includes('trin')) {
    series.push({
      name: 'TRIN', type: 'line', data: points.map((p) => p.trin),
      smooth: true, symbol: 'diamond', symbolSize: 4, connectNulls: false,
      lineStyle: { color: '#3498db', width: 1.5, type: 'dashed' }, yAxisIndex: 2,
    })
  }
  if (indicators.includes('nearLimitUp')) {
    series.push({ name: '近涨停', type: 'bar', data: points.map((p) => p.nearLimitUp), itemStyle: { color: '#ff4757' }, barWidth: 8, yAxisIndex: 1 })
  }
  if (indicators.includes('highGain')) {
    series.push({ name: '高涨幅≥7%', type: 'bar', data: points.map((p) => p.highGain), itemStyle: { color: '#ff7f50' }, barWidth: 8, yAxisIndex: 1 })
  }
  if (indicators.includes('highTurnover')) {
    series.push({ name: '高换手≥10%', type: 'bar', data: points.map((p) => p.highTurnover), itemStyle: { color: '#4a90e2' }, barWidth: 8, yAxisIndex: 1 })
  }
  if (indicators.includes('mainNet')) {
    series.push({ name: '主力净额', type: 'bar', data: points.map((p) => p.mainNet), itemStyle: { color: '#ffb142' }, barWidth: 8, yAxisIndex: 3 })
  }
  if (series.length) {
    series[0].markArea = { silent: true, data: buildStageMarkArea(points) }
  }

  const textColor = cssVar('--text-secondary', '#9aa0a6')
  const borderColor = cssVar('--border-color', '#333333')

  layersChart.setOption(
    {
      grid: { left: '8%', right: '8%', top: '15%', bottom: '10%', containLabel: true },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        confine: true,
        formatter: (params: any) => {
          const list = Array.isArray(params) ? params : [params]
          if (!list.length) return ''
          const point = points[list[0].dataIndex]
          if (!point) return ''
          const rows = list
            .map((it: any) => {
              const fmt = LAYER_AXIS_FMT[it.seriesName]
              const value = typeof it.value === 'object' ? it.value?.value : it.value
              return `<div>${it.marker}${it.seriesName}：${fmt ? fmt(value ?? null) : String(value)}</div>`
            })
            .join('')
          const stageColor = STAGE_TREND_META[point.stage]?.fg || textColor
          return [
            `<div style="font-weight:600;margin-bottom:4px;">${point.title}</div>`,
            `<div style="color:${stageColor};margin-bottom:4px;">阶段：${point.stage} · 样本 ${formatNullableCount(point.sample)}</div>`,
            rows,
          ].join('')
        },
      },
      legend: {
        data: series.map((s) => s.name),
        bottom: 0,
        itemWidth: 12,
        itemHeight: 8,
        textStyle: { color: textColor, fontSize: 10 },
      },
      xAxis: {
        type: 'category',
        data: points.map((p) => p.label),
        axisLabel: { color: textColor, fontSize: 10, rotate: 30 },
        axisLine: { lineStyle: { color: borderColor } },
      },
      yAxis: [
        {
          type: 'value',
          name: '%',
          nameTextStyle: { color: textColor, fontSize: 9 },
          splitLine: { lineStyle: { color: borderColor, type: 'dashed' } },
          axisLabel: { color: textColor },
        },
        {
          type: 'value',
          name: '数量',
          nameTextStyle: { color: textColor, fontSize: 9 },
          splitLine: { show: false },
          axisLabel: { color: textColor },
        },
        {
          type: 'value',
          name: 'TRIN',
          nameTextStyle: { color: textColor, fontSize: 9 },
          splitLine: { show: false },
          axisLabel: { color: textColor },
        },
        {
          type: 'value',
          name: '金额',
          nameTextStyle: { color: textColor, fontSize: 9 },
          splitLine: { show: false },
          axisLabel: { color: textColor },
        },
      ],
      series,
      backgroundColor: 'transparent',
    },
    // 指标开关减少序列时必须整体替换，merge 模式下旧序列会残留
    { notMerge: true },
  )
  layersChart.resize()
}

// 图下统计卡：所选分层多日均值/峰值，缺失 '--'
const layerStats = computed(() => {
  const pts = layerPoints.value
  const avgOf = (values: Array<number | null>) => {
    const nums = values.filter((v): v is number => v !== null)
    return nums.length ? nums.reduce((a, b) => a + b, 0) / nums.length : null
  }
  const avgUp = avgOf(pts.map((p) => p.upRatioPct))
  const avgMain = avgOf(pts.map((p) => p.mainNet))
  const avgTrin = avgOf(pts.map((p) => p.trin))
  const nearPeaks = pts.map((p) => p.nearLimitUp).filter((v): v is number => v !== null)
  const maxNear = nearPeaks.length ? Math.max(...nearPeaks) : null
  const unit = layersRange.value === '1d' ? '槽' : '日'
  const sub = pts.length ? `共 ${pts.length} ${unit}` : ''
  return [
    { label: '平均涨占比', value: avgUp === null ? '--' : `${avgUp.toFixed(1)}%`, sub },
    { label: '近涨停峰值', value: maxNear === null ? '--' : String(maxNear), sub },
    { label: '平均主力净额', value: avgMain === null ? '--' : formatMoney(avgMain), sub },
    { label: '平均TRIN', value: avgTrin === null ? '--' : avgTrin.toFixed(2), sub },
  ]
})

const layersNote = computed(() => {
  if (seriesLoading.value) return '正在加载多日序列…'
  if (seriesError.value && RANGE_DAYS[layersRange.value] > seriesDaysLoaded.value) {
    return `多日序列不可用：${seriesError.value}`
  }
  if (!layerPoints.value.length) return ''
  if (layersRange.value === '1d') {
    // slots 接口对非交易日回落上一交易日，注记里显式标出实际交易日
    if (slotsDegradedReason.value) return slotsDegradedReason.value
    return slotsTradingDate.value ? `${slotsTradingDate.value} · 盘中半小时一帧，随采集更新` : ''
  }
  return dailyRangeNote(layerPoints.value)
})

// ---------- 涨停证据 ----------
const limitEvidence = computed(() => doc.value?.metrics.limitEvidence ?? null)
const intersectionCards = computed(() => {
  const it = limitEvidence.value?.intersection
  if (!it) return []
  return [
    { label: '全池涨停', value: `${formatNullableCount(it.top100LimitUpCount)}（${formatShare(it.top100LimitUpShare)}）` },
    { label: '近涨停', value: formatNullableCount(it.top100NearLimitUpCount) },
    { label: '二板以上', value: formatNullableCount(it.top100Board2PlusCount) },
    { label: '最高板', value: `${formatNullableCount(it.top100MaxBoardHeight)} 板` },
    { label: '前50 涨停', value: formatNullableCount(it.top50LimitUpCount) },
    { label: '前20 涨停', value: formatNullableCount(it.top20LimitUpCount) },
    { label: '池内炸板', value: `${formatNullableCount(it.top100ZhabanCount)}（${formatShare(it.top100ZhabanShare)}）`, toneClass: 'down' },
  ]
})
const marketCards = computed(() => {
  const market = limitEvidence.value?.market
  if (!market) return []
  const ths = market.thsPools ?? null
  return [
    { label: '全市场涨停', value: formatNullableCount(market.ztCount), toneClass: '' },
    { label: '封板率', value: market.fengbanRate != null ? `${market.fengbanRate.toFixed(0)}%` : '--', toneClass: '' },
    { label: '全市场炸板', value: formatNullableCount(market.zhabanCount), toneClass: 'down' },
    { label: '首板', value: formatNullableCount(market.board1), toneClass: '' },
    { label: '2板', value: formatNullableCount(market.board2), toneClass: '' },
    { label: '3板', value: formatNullableCount(market.board3), toneClass: '' },
    { label: '4板+', value: formatNullableCount(market.board4Plus), toneClass: '' },
    { label: '最高连板', value: `${formatNullableCount(market.maxContinuousDays)} 板`, toneClass: '' },
    { label: 'THS 炸板池', value: ths ? formatNullableCount(ths.failedCount) : '--', toneClass: 'down' },
    { label: 'THS 回撤榜', value: ths ? formatNullableCount(ths.drawdownCount) : '--', toneClass: 'down' },
  ]
})
const marketEvidenceNote = computed(() => {
  const diagnosticsList = diagnostics.value.find((item) => item.includes('limitSummary'))
  return diagnosticsList || '全市场口径来自采集链 limitSummary，仅作背景参考'
})
const yesterdayLimitCards = computed(() => {
  const y = limitEvidence.value?.yesterdayHotLimit
  if (!y) return []
  return [
    { label: '昨日涨停数', value: formatNullableCount(y.count), toneClass: '' },
    { label: '留榜数', value: formatNullableCount(y.retainedTop100Count), toneClass: '' },
    { label: '今日均涨', value: formatPercent(y.avgChange), toneClass: '' },
    { label: '正收益率', value: formatShare(y.positiveRate), toneClass: 'up' },
    { label: '走弱率', value: formatShare(y.weakeningRate), toneClass: 'down' },
    { label: '冲板失败率', value: formatShare(y.failedOrWeakRate), toneClass: 'down' },
  ]
})

// ---------- 阶段分布（ECharts 饼图：全池六态占比） ----------
// 六态配色沿用面板语义色：点火红/扩散橙/拥挤琥珀/反转绿(风险)/冷却蓝(降温)/无阶段灰
const STAGE_PIE_COLORS: Record<string, string> = {
  ignition: '#ff4757',
  expansion: '#ff7f50',
  crowded: '#ffb142',
  reversal: '#2ed573',
  cooling: '#3498db',
  unknown: '#7f8c8d',
}

const stageChartRef = ref<HTMLElement | null>(null)
let stageChart: echarts.ECharts | null = null

// 饼图数据：0 值阶段不进扇区（tooltip/图例随之收敛），缺失字段时列表为空走空态
const stagePieData = computed(() => {
  const all = allLayer.value
  if (!all?.stageCounts) return []
  return (Object.keys(HOT_LIST_STAGE_LABELS) as HotListStageKey[])
    .map((key) => ({ key, name: HOT_LIST_STAGE_LABELS[key], value: all.stageCounts[key] ?? 0 }))
    .filter((item) => item.value > 0)
})

const stageTotal = computed(() => stagePieData.value.reduce((sum, item) => sum + item.value, 0))

// 右侧明细列表：按数量降序，含占比与比例条
const stageList = computed(() => {
  const total = stageTotal.value
  return stagePieData.value
    .map((item) => {
      const pct = total > 0 ? (item.value / total) * 100 : 0
      return { ...item, count: item.value, color: STAGE_PIE_COLORS[item.key] || '#7f8c8d', pctText: `${pct.toFixed(1)}%` }
    })
    .sort((a, b) => b.value - a.value)
})

function renderStageChart() {
  if (!stageChartRef.value || !stagePieData.value.length) return
  // 空态 v-if 切换会卸载并重挂图表容器：旧实例绑定的 DOM 已分离，必须 dispose 后重建
  if (stageChart && stageChart.getDom() !== stageChartRef.value) {
    stageChart.dispose()
    stageChart = null
  }
  if (!stageChart) {
    stageChart = echarts.init(stageChartRef.value)
  }

  const sliceColor = cssVar('--bg-secondary', '#222222')

  stageChart.setOption(
    {
      tooltip: {
        trigger: 'item',
        confine: true,
        formatter: (params: any) =>
          `${params.marker}${params.name}：${params.value}（${params.percent}%）`,
      },
      series: [
        {
          type: 'pie',
          // 细环 + 中心总样本（HTML 覆层），明细走右侧列表
          radius: ['62%', '86%'],
          center: ['50%', '50%'],
          avoidLabelOverlap: true,
          itemStyle: { borderColor: sliceColor, borderWidth: 3 },
          label: { show: false },
          labelLine: { show: false },
          emphasis: { scale: true, scaleSize: 5 },
          data: stagePieData.value.map((item) => ({
            name: item.name,
            value: item.value,
            itemStyle: { color: STAGE_PIE_COLORS[item.key] || '#7f8c8d' },
          })),
        },
      ],
      backgroundColor: 'transparent',
    },
    // 数据刷新时整体替换，避免旧扇区残留
    { notMerge: true },
  )
  stageChart.resize()
}
// 迁移键中文表述（行级六态），单段为当日延续；与后端 cycle.transition 原始串 "a->b" 对应
const STAGE_TRANSITION_ZH: Record<string, string> = {
  ignition: '点火',
  expansion: '扩散',
  crowded: '拥挤',
  reversal: '反转',
  cooling: '冷却',
  unknown: '无阶段',
}

function transitionZh(text: string): string {
  return text
    .split('->')
    .map((segment) => STAGE_TRANSITION_ZH[segment.trim()] || segment)
    .join('→')
}

const transitionItems = computed(() => {
  const counts = doc.value?.metrics.transitionCounts as Record<string, number> | undefined
  if (!counts) return []
  return Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 6)
    .map(([text, count]) => ({ key: text, text: transitionZh(text), count }))
})

// ---------- 历史对比（ECharts：池流转/留榜/强票表现多日趋势，语言同情绪趋势） ----------
// 时间范围与多日缓存（seriesDocs/ensureSeriesDays）与情绪趋势页签共享
const COMPARE_RANGES = [
  { key: '3d', label: '3日' },
  { key: '1w', label: '1周' },
  { key: '1m', label: '1月' },
] as const
type CompareTimeRange = (typeof COMPARE_RANGES)[number]['key']
const compareRange = ref<CompareTimeRange>('3d')
const compareChartRef = ref<HTMLElement | null>(null)
let compareChart: echarts.ECharts | null = null

// 指标开关：池流转三类走数量轴，留榜/强票表现走 % 轴
const COMPARE_INDICATORS = [
  { key: 'pool', label: '池规模', icon: '📊' },
  { key: 'new', label: '新入', icon: '🆕' },
  { key: 'retainRate', label: '留榜率', icon: '🔁' },
  { key: 'risk', label: '风险数', icon: '⚠️' },
  { key: 'positiveRate', label: '正收益率', icon: '💪' },
  { key: 'weakenRate', label: '转弱率', icon: '📉' },
] as const
type CompareIndicatorKey = (typeof COMPARE_INDICATORS)[number]['key']
const compareIndicators = ref<CompareIndicatorKey[]>(['pool', 'new', 'retainRate'])

// 每日数值点：null 缺失直传图表断线，不补 0
const comparePoints = computed(() => {
  const source = seriesDocs.value.slice(-RANGE_DAYS[compareRange.value])
  if (!source.length) return []
  const pct = (rate?: number | null) => (typeof rate === 'number' ? Math.round(rate * 1000) / 10 : null)
  return source.map((item, index) => {
    const all = item.metrics?.layers?.all
    const counts = all?.stageCounts
    const comp = item.metrics?.comparison
    const strong = comp?.yesterdayStrongPerformance
    return {
      label: (item.tradingDate || '').slice(5) || `d-${index}`,
      title: item.tradingDate || `d-${index}`,
      stage: item.stage,
      pool: all?.topN ?? comp?.today?.topN ?? null,
      newCount: comp?.newTop100Count ?? null,
      retainRatePct: pct(comp?.top100RetainRateFromYesterday),
      risk: counts ? counts.reversal + counts.cooling : null,
      positiveRatePct: pct(strong?.positiveRate),
      weakenRatePct: pct(strong?.weakeningRate),
      strong: strong
        ? {
            count: strong.count ?? null,
            matched: strong.matchedCount ?? null,
            retained: strong.retainedTop100Count ?? null,
            avgChange: typeof strong.avgChange === 'number' ? strong.avgChange : null,
          }
        : null,
    }
  })
})

function toggleCompareIndicator(key: CompareIndicatorKey) {
  const current = compareIndicators.value
  if (current.includes(key)) {
    if (current.length === 1) return // 至少保留一个序列，避免图表空白
    compareIndicators.value = current.filter((k) => k !== key)
  } else {
    // 按声明顺序重排，保持图例顺序稳定
    compareIndicators.value = COMPARE_INDICATORS.map((i) => i.key).filter((k) => current.includes(k) || k === key)
  }
  nextTick(() => renderCompareChart())
}

async function setCompareRange(range: CompareTimeRange) {
  if (compareRange.value === range) return
  compareRange.value = range
  await ensureSeriesDays(RANGE_DAYS[range])
  nextTick(() => renderCompareChart())
}

const COMPARE_AXIS_FMT: Record<string, (v: number | null) => string> = {
  池规模: (v) => formatNullableCount(v),
  新入: (v) => formatNullableCount(v),
  留榜率: (v) => (v === null ? '--' : `${v.toFixed(1)}%`),
  风险数: (v) => formatNullableCount(v),
  正收益率: (v) => (v === null ? '--' : `${v.toFixed(1)}%`),
  转弱率: (v) => (v === null ? '--' : `${v.toFixed(1)}%`),
}

function renderCompareChart() {
  if (!compareChartRef.value || !comparePoints.value.length) return
  // 空态 v-if 切换会卸载并重挂图表容器：旧实例绑定的 DOM 已分离，必须 dispose 后重建
  if (compareChart && compareChart.getDom() !== compareChartRef.value) {
    compareChart.dispose()
    compareChart = null
  }
  if (!compareChart) {
    compareChart = echarts.init(compareChartRef.value)
  }

  const points = comparePoints.value
  const indicators = compareIndicators.value
  const series: any[] = []
  if (indicators.includes('pool')) {
    series.push({ name: '池规模', type: 'bar', data: points.map((p) => p.pool), itemStyle: { color: '#ffd700' }, barWidth: 8, yAxisIndex: 0 })
  }
  if (indicators.includes('new')) {
    series.push({ name: '新入', type: 'bar', data: points.map((p) => p.newCount), itemStyle: { color: '#ff7f50' }, barWidth: 8, yAxisIndex: 0 })
  }
  if (indicators.includes('risk')) {
    series.push({ name: '风险数', type: 'bar', data: points.map((p) => p.risk), itemStyle: { color: '#2ed573' }, barWidth: 8, yAxisIndex: 0 })
  }
  if (indicators.includes('retainRate')) {
    series.push({
      name: '留榜率', type: 'line', data: points.map((p) => p.retainRatePct),
      smooth: true, symbol: 'circle', symbolSize: 5, connectNulls: false,
      lineStyle: { color: '#4a90e2', width: 2 }, yAxisIndex: 1,
    })
  }
  if (indicators.includes('positiveRate')) {
    series.push({
      name: '正收益率', type: 'line', data: points.map((p) => p.positiveRatePct),
      smooth: true, symbol: 'circle', symbolSize: 5, connectNulls: false,
      lineStyle: { color: '#ff4757', width: 2 }, yAxisIndex: 1,
    })
  }
  if (indicators.includes('weakenRate')) {
    series.push({
      name: '转弱率', type: 'line', data: points.map((p) => p.weakenRatePct),
      smooth: true, symbol: 'diamond', symbolSize: 4, connectNulls: false,
      lineStyle: { color: '#2ed573', width: 1.5, type: 'dashed' }, yAxisIndex: 1,
    })
  }
  if (series.length) {
    series[0].markArea = { silent: true, data: buildStageMarkArea(points) }
  }

  const textColor = cssVar('--text-secondary', '#9aa0a6')
  const borderColor = cssVar('--border-color', '#333333')

  compareChart.setOption(
    {
      grid: { left: '8%', right: '8%', top: '15%', bottom: '10%', containLabel: true },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        confine: true,
        formatter: (params: any) => {
          const list = Array.isArray(params) ? params : [params]
          if (!list.length) return ''
          const point = points[list[0].dataIndex]
          if (!point) return ''
          const rows = list
            .map((it: any) => {
              const fmt = COMPARE_AXIS_FMT[it.seriesName]
              const value = typeof it.value === 'object' ? it.value?.value : it.value
              return `<div>${it.marker}${it.seriesName}：${fmt ? fmt(value ?? null) : String(value)}</div>`
            })
            .join('')
          const stageColor = STAGE_TREND_META[point.stage]?.fg || textColor
          const strongLine = point.strong
            ? `<div style="margin-top:4px;color:${textColor};">强票：${formatNullableCount(point.strong.count)} 只 · 可比 ${formatNullableCount(point.strong.matched)} · 留榜 ${formatNullableCount(point.strong.retained)} · 均涨 ${point.strong.avgChange === null ? '--' : formatPercent(point.strong.avgChange)}</div>`
            : ''
          return [
            `<div style="font-weight:600;margin-bottom:4px;">${point.title}</div>`,
            `<div style="color:${stageColor};margin-bottom:4px;">阶段：${point.stage}</div>`,
            rows,
            strongLine,
          ].join('')
        },
      },
      legend: {
        data: series.map((s) => s.name),
        bottom: 0,
        itemWidth: 12,
        itemHeight: 8,
        textStyle: { color: textColor, fontSize: 10 },
      },
      xAxis: {
        type: 'category',
        data: points.map((p) => p.label),
        axisLabel: { color: textColor, fontSize: 10, rotate: 30 },
        axisLine: { lineStyle: { color: borderColor } },
      },
      yAxis: [
        {
          type: 'value',
          name: '数量',
          nameTextStyle: { color: textColor, fontSize: 9 },
          splitLine: { lineStyle: { color: borderColor, type: 'dashed' } },
          axisLabel: { color: textColor },
        },
        {
          type: 'value',
          name: '%',
          nameTextStyle: { color: textColor, fontSize: 9 },
          splitLine: { show: false },
          axisLabel: { color: textColor },
        },
      ],
      series,
      backgroundColor: 'transparent',
    },
    // 指标开关减少序列时必须整体替换，merge 模式下旧序列会残留
    { notMerge: true },
  )
  compareChart.resize()
}

// 图下统计卡：多日均值口径，缺失 '--'
const compareStats = computed(() => {
  const pts = comparePoints.value
  const avgOf = (values: Array<number | null>) => {
    const nums = values.filter((v): v is number => v !== null)
    return nums.length ? nums.reduce((a, b) => a + b, 0) / nums.length : null
  }
  const avgPool = avgOf(pts.map((p) => p.pool))
  const avgNew = avgOf(pts.map((p) => p.newCount))
  const avgRetain = avgOf(pts.map((p) => p.retainRatePct))
  const avgPositive = avgOf(pts.map((p) => p.positiveRatePct))
  const sub = pts.length ? `共 ${pts.length} 日` : ''
  return [
    { label: '平均池规模', value: avgPool === null ? '--' : formatNullableCount(avgPool), sub },
    { label: '平均新入', value: avgNew === null ? '--' : formatNullableCount(avgNew), sub },
    { label: '平均留榜率', value: avgRetain === null ? '--' : `${avgRetain.toFixed(1)}%`, sub },
    { label: '平均正收益率', value: avgPositive === null ? '--' : `${avgPositive.toFixed(1)}%`, sub },
  ]
})

const compareNote = computed(() => {
  if (seriesLoading.value) return '正在加载多日序列…'
  if (seriesError.value && RANGE_DAYS[compareRange.value] > seriesDaysLoaded.value) {
    return `多日序列不可用：${seriesError.value}`
  }
  if (!comparePoints.value.length) return ''
  return dailyRangeNote(comparePoints.value)
})

// ---------- 情绪趋势（ECharts：确认阶段铺底 + 指标开关多序列，分歧人话进 tooltip） ----------
function stageDriftText(rawStage: string, confirmedStage: string): string {
  const rawHeat = STAGE_HEAT[rawStage] ?? 1
  const confirmedHeat = STAGE_HEAT[confirmedStage] ?? 1
  if (rawHeat > confirmedHeat) return '短暂走高'
  if (rawHeat < confirmedHeat) return '短暂回落'
  return '盘中波动'
}

// 情绪趋势指标开关（SectorDetail 历史趋势语言：pill 开关式多序列）
const TREND_INDICATORS = [
  { key: 'upRatio', label: '涨占比', icon: '📈' },
  { key: 'attack', label: '攻击', icon: '🚀' },
  { key: 'risk', label: '风险', icon: '⚠️' },
  { key: 'trin', label: 'TRIN', icon: '⚖️' },
  { key: 'pool', label: '池规模', icon: '📊' },
] as const
type TrendIndicatorKey = (typeof TREND_INDICATORS)[number]['key']

// 阶段铺底色：冷→热语义色，10% alpha 底 + 实色标签（与 STAGE_HEAT 冷热语感一致）
const STAGE_TREND_META: Record<string, { bg: string; fg: string }> = {
  冰点: { bg: 'rgba(74, 144, 226, 0.10)', fg: '#4a90e2' },
  退潮: { bg: 'rgba(127, 140, 141, 0.12)', fg: '#7f8c8d' },
  启动: { bg: 'rgba(255, 177, 66, 0.10)', fg: '#ffb142' },
  发酵: { bg: 'rgba(255, 127, 80, 0.12)', fg: '#ff7f50' },
  高潮: { bg: 'rgba(255, 71, 87, 0.10)', fg: '#ff4757' },
}

const trendChartRef = ref<HTMLElement | null>(null)
let trendChart: echarts.ECharts | null = null
const trendIndicators = ref<TrendIndicatorKey[]>(['upRatio', 'attack', 'risk'])

// 时间范围（SectorDetail 历史趋势语言）：1天=日内半小时槽位，3日/1周/1月=日线 EOD 终值
const TIME_RANGES = [
  { key: '1d', label: '1天' },
  { key: '3d', label: '3日' },
  { key: '1w', label: '1周' },
  { key: '1m', label: '1月' },
] as const
type TrendTimeRange = (typeof TIME_RANGES)[number]['key']
const RANGE_DAYS: Record<TrendTimeRange, number> = { '1d': 1, '3d': 3, '1w': 5, '1m': 20 }
const timeRange = ref<TrendTimeRange>('1d')
const seriesDocs = ref<HotListSentimentDayDoc[]>([])
const seriesDaysLoaded = ref(0)
const seriesMissingDays = ref<HotlistSentimentMissingDay[]>([])
const seriesError = ref<string | null>(null)
const seriesLoading = ref(false)

// 每槽位/每日数值点：null 缺失直传图表断线（connectNulls: false），不补 0。
// 1天=slots 日内槽位（label=槽位时间）；多日=series 日线 EOD 文档（label=交易日 MM-DD）
const trendPoints = computed(() => {
  const days = RANGE_DAYS[timeRange.value]
  const intraday = days === 1
  const source = intraday ? slots.value : seriesDocs.value.slice(-days)
  if (!source.length) return []
  return source.map((item, index) => {
    const all = item.metrics?.layers?.all
    const counts = all?.stageCounts
    const rawStage = item.rawStage || item.stage
    const drift = rawStage !== item.stage ? stageDriftText(rawStage, item.stage) : ''
    return {
      label: intraday
        ? item.slotTime || `slot-${index}`
        : (item.tradingDate || '').slice(5) || `d-${index}`,
      title: intraday ? item.slotTime || `slot-${index}` : item.tradingDate || `d-${index}`,
      stage: item.stage,
      drift,
      driftRaw: rawStage,
      pool: item.metrics?.poolSize ?? all?.total ?? null,
      upRatioPct: typeof all?.upRatio === 'number' ? Math.round(all.upRatio * 1000) / 10 : null,
      attack: counts ? counts.ignition + counts.expansion : null,
      risk: counts ? counts.reversal + counts.cooling : null,
      trin: typeof all?.hotTrin === 'number' ? all.hotTrin : null,
    }
  })
})

// 窗口超过已加载天数时拉更长序列（后端 cap 30 日），缺失日结构化收集不吞掉；
// seriesDocs 缓存与加载态由情绪趋势/历史对比/分层结构三页签共享。
// 代际守卫：快速连切档位时旧响应直接丢弃，最新请求独占缓存写入权
let seriesReqId = 0

async function ensureSeriesDays(days: number) {
  if (days <= seriesDaysLoaded.value) return
  const reqId = ++seriesReqId
  seriesLoading.value = true
  seriesError.value = null
  try {
    const result = await fetchHotlistSentimentSeries(days)
    if (reqId !== seriesReqId) return
    if (result.degraded) {
      seriesError.value = result.reason || '多日序列不可用'
    } else {
      seriesDocs.value = result.items
      seriesDaysLoaded.value = days
      seriesMissingDays.value = result.missingDays
    }
  } catch (err) {
    if (reqId !== seriesReqId) return
    seriesError.value = err instanceof Error ? err.message : '加载多日序列失败'
  } finally {
    if (reqId === seriesReqId) seriesLoading.value = false
  }
}

async function setTimeRange(range: TrendTimeRange) {
  if (timeRange.value === range) return
  timeRange.value = range
  await ensureSeriesDays(RANGE_DAYS[range])
  nextTick(() => renderTrendChart())
}

// 图下统计卡（SectorDetail historyStats 语言：峰值带时间，均值带样本数，缺失 '--'）
const trendStats = computed(() => {
  const pts = trendPoints.value
  const maxOf = (values: Array<number | null>): number | null => {
    const nums = values.filter((v): v is number => v !== null)
    return nums.length ? Math.max(...nums) : null
  }
  const timeOfValue = (pick: (p: (typeof pts)[number]) => number | null, target: number | null): string => {
    if (target === null) return ''
    return pts.find((p) => pick(p) === target)?.label || ''
  }
  const ups = pts.map((p) => p.upRatioPct).filter((v): v is number => v !== null)
  const trins = pts.map((p) => p.trin).filter((v): v is number => v !== null)
  const maxAttack = maxOf(pts.map((p) => p.attack))
  const maxRisk = maxOf(pts.map((p) => p.risk))
  const avgUp = ups.length ? ups.reduce((a, b) => a + b, 0) / ups.length : null
  const avgTrin = trins.length ? trins.reduce((a, b) => a + b, 0) / trins.length : null
  const unit = timeRange.value === '1d' ? '槽' : '日'
  return [
    { label: '平均涨占比', value: avgUp === null ? '--' : `${avgUp.toFixed(1)}%`, sub: ups.length ? `共 ${ups.length} ${unit}` : '' },
    { label: '攻击峰值', value: maxAttack === null ? '--' : String(maxAttack), sub: timeOfValue((p) => p.attack, maxAttack) },
    { label: '风险峰值', value: maxRisk === null ? '--' : String(maxRisk), sub: timeOfValue((p) => p.risk, maxRisk) },
    { label: 'TRIN 均值', value: avgTrin === null ? '--' : avgTrin.toFixed(2), sub: trins.length ? `共 ${trins.length} ${unit}` : '' },
  ]
})

function toggleTrendIndicator(key: TrendIndicatorKey) {
  const current = trendIndicators.value
  if (current.includes(key)) {
    if (current.length === 1) return // 至少保留一个序列，避免图表空白
    trendIndicators.value = current.filter((k) => k !== key)
  } else {
    // 按声明顺序重排，保持图例顺序稳定
    trendIndicators.value = TREND_INDICATORS.map((i) => i.key).filter((k) => current.includes(k) || k === key)
  }
  nextTick(() => renderTrendChart())
}

// ECharts 画布不解析 CSS 变量，渲染时取计算值（主题切换后下一次渲染生效）
function cssVar(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return value || fallback
}

// tooltip 内各序列的展示格式（fail-visible：null 显示 --）
const TREND_AXIS_FMT: Record<string, (v: number | null) => string> = {
  涨占比: (v) => (v === null ? '--' : `${v.toFixed(1)}%`),
  攻击: (v) => formatNullableCount(v),
  风险: (v) => formatNullableCount(v),
  TRIN: (v) => formatTrin(v),
  池规模: (v) => formatNullableCount(v),
}

// 阶段铺底：连续同阶段点合并成一段 markArea，≥2 点才显示阶段名，避免窄段文字挤压（两图表共用）
function buildStageMarkArea(
  points: Array<{ label: string; stage: string }>,
): Array<[Record<string, unknown>, Record<string, unknown>]> {
  const data: Array<[Record<string, unknown>, Record<string, unknown>]> = []
  let runStage = ''
  let runStart = ''
  let runEnd = ''
  let runLen = 0
  const flushRun = () => {
    const meta = STAGE_TREND_META[runStage]
    if (meta && runLen > 0) {
      data.push([
        {
          xAxis: runStart,
          itemStyle: { color: meta.bg },
          label: { show: runLen >= 2, position: 'insideTop', fontSize: 9, color: meta.fg, formatter: runStage },
        },
        { xAxis: runEnd },
      ])
    }
    runLen = 0
  }
  for (const p of points) {
    if (runLen > 0 && p.stage === runStage) {
      runEnd = p.label
      runLen += 1
    } else {
      flushRun()
      runStage = p.stage
      runStart = p.label
      runEnd = p.label
      runLen = 1
    }
  }
  flushRun()
  return data
}

function renderTrendChart() {
  if (!trendChartRef.value || !trendPoints.value.length) return
  // 空态 v-if 切换会卸载并重挂图表容器：旧实例绑定的 DOM 已分离，必须 dispose 后重建
  if (trendChart && trendChart.getDom() !== trendChartRef.value) {
    trendChart.dispose()
    trendChart = null
  }
  if (!trendChart) {
    trendChart = echarts.init(trendChartRef.value)
  }

  const points = trendPoints.value
  const indicators = trendIndicators.value
  const series: any[] = []

  if (indicators.includes('upRatio')) {
    series.push({
      name: '涨占比',
      type: 'line',
      data: points.map((p) => p.upRatioPct),
      smooth: true,
      symbol: 'circle',
      symbolSize: 5,
      connectNulls: false,
      lineStyle: { color: '#ff7f50', width: 2 },
      areaStyle: {
        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: 'rgba(255, 127, 80, 0.25)' },
          { offset: 1, color: 'rgba(255, 127, 80, 0)' },
        ]),
      },
      yAxisIndex: 0,
    })
  }
  if (indicators.includes('attack')) {
    series.push({
      name: '攻击',
      type: 'bar',
      data: points.map((p) => p.attack),
      itemStyle: { color: '#ff4757' },
      barWidth: 8,
      yAxisIndex: 1,
    })
  }
  if (indicators.includes('risk')) {
    series.push({
      name: '风险',
      type: 'bar',
      data: points.map((p) => p.risk),
      itemStyle: { color: '#2ed573' },
      barWidth: 8,
      yAxisIndex: 1,
    })
  }
  if (indicators.includes('trin')) {
    series.push({
      name: 'TRIN',
      type: 'line',
      data: points.map((p) => p.trin),
      smooth: true,
      connectNulls: false,
      lineStyle: { color: '#3498db', width: 1.5, type: 'dashed' },
      symbol: 'diamond',
      symbolSize: 4,
      yAxisIndex: 2,
    })
  }
  if (indicators.includes('pool')) {
    series.push({
      name: '池规模',
      type: 'line',
      data: points.map((p) => p.pool),
      smooth: true,
      connectNulls: false,
      symbol: 'none',
      lineStyle: { color: '#4a90e2', width: 1.5 },
      areaStyle: {
        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: 'rgba(74, 144, 226, 0.15)' },
          { offset: 1, color: 'rgba(74, 144, 226, 0)' },
        ]),
      },
      yAxisIndex: 3,
    })
  }

  if (series.length) {
    series[0].markArea = { silent: true, data: buildStageMarkArea(points) }
  }

  const textColor = cssVar('--text-secondary', '#9aa0a6')
  const borderColor = cssVar('--border-color', '#333333')

  trendChart.setOption(
    {
      grid: { left: '8%', right: '8%', top: '15%', bottom: '10%', containLabel: true },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        confine: true,
        formatter: (params: any) => {
          const list = Array.isArray(params) ? params : [params]
          if (!list.length) return ''
          const point = points[list[0].dataIndex]
          if (!point) return ''
          const rows = list
            .map((it: any) => {
              const fmt = TREND_AXIS_FMT[it.seriesName]
              const value = typeof it.value === 'object' ? it.value?.value : it.value
              return `<div>${it.marker}${it.seriesName}：${fmt ? fmt(value ?? null) : String(value)}</div>`
            })
            .join('')
          const stageColor = STAGE_TREND_META[point.stage]?.fg || textColor
          const driftText = point.drift ? `（${point.drift}，当帧判定 ${point.driftRaw}）` : ''
          return [
            `<div style="font-weight:600;margin-bottom:4px;">${point.title}</div>`,
            `<div style="color:${stageColor};margin-bottom:4px;">阶段：${point.stage}${driftText}</div>`,
            rows,
          ].join('')
        },
      },
      legend: {
        data: series.map((s) => s.name),
        bottom: 0,
        itemWidth: 12,
        itemHeight: 8,
        textStyle: { color: textColor, fontSize: 10 },
      },
      xAxis: {
        type: 'category',
        data: points.map((p) => p.label),
        axisLabel: { color: textColor, fontSize: 10, rotate: 30 },
        axisLine: { lineStyle: { color: borderColor } },
      },
      yAxis: [
        {
          type: 'value',
          name: '涨占比%',
          nameTextStyle: { color: textColor, fontSize: 9 },
          splitLine: { lineStyle: { color: borderColor, type: 'dashed' } },
          axisLabel: { color: textColor },
        },
        {
          type: 'value',
          name: '数量',
          nameTextStyle: { color: textColor, fontSize: 9 },
          splitLine: { show: false },
          axisLabel: { color: textColor },
        },
        {
          type: 'value',
          name: 'TRIN',
          nameTextStyle: { color: textColor, fontSize: 9 },
          splitLine: { show: false },
          axisLabel: { color: textColor },
        },
        {
          type: 'value',
          name: '池规模',
          nameTextStyle: { color: textColor, fontSize: 9 },
          splitLine: { show: false },
          axisLabel: { color: textColor },
        },
      ],
      series,
      backgroundColor: 'transparent',
    },
    // 指标开关减少序列时必须整体替换，merge 模式下旧序列会残留
    { notMerge: true },
  )
  trendChart.resize()
}

// 具名 handler：卸载时移除，避免面板反复开关累积监听器
function handleChartsResize() {
  if (trendChart) {
    trendChart.resize()
  }
  if (compareChart) {
    compareChart.resize()
  }
  if (layersChart) {
    layersChart.resize()
  }
  if (stageChart) {
    stageChart.resize()
  }
}
onMounted(() => {
  window.addEventListener('resize', handleChartsResize)
})
onUnmounted(() => {
  window.removeEventListener('resize', handleChartsResize)
  if (trendChart) {
    trendChart.dispose()
    trendChart = null
  }
  if (compareChart) {
    compareChart.dispose()
    compareChart = null
  }
  if (layersChart) {
    layersChart.dispose()
    layersChart = null
  }
  if (stageChart) {
    stageChart.dispose()
    stageChart = null
  }
})

// 页签进入或数据刷新时渲染（v-show 切换后需等 nextTick 拿到可见容器尺寸）
watch(view, (v) => {
  if (v === 'track' && trendPoints.value.length) {
    nextTick(() => renderTrendChart())
  }
  if (v === 'compare' && comparePoints.value.length) {
    nextTick(() => renderCompareChart())
  }
  if (v === 'layers' && layerPoints.value.length) {
    nextTick(() => renderLayersChart())
  }
  if (v === 'structure' && stagePieData.value.length) {
    nextTick(() => renderStageChart())
  }
})
watch(trendPoints, () => {
  if (view.value === 'track') {
    nextTick(() => renderTrendChart())
  }
})
watch(comparePoints, () => {
  if (view.value === 'compare') {
    nextTick(() => renderCompareChart())
  }
})
watch(layerPoints, () => {
  if (view.value === 'layers') {
    nextTick(() => renderLayersChart())
  }
})
watch(stagePieData, () => {
  if (view.value === 'structure') {
    nextTick(() => renderStageChart())
  }
})

// 多日窗口注记（历史对比/情绪趋势多日档共用）：日期区间 + 口径 + 缺失日标注
function dailyRangeNote(pts: Array<{ label: string }>): string {
  const rangeLabel = pts.length > 1 ? `${pts[0].label} ~ ${pts[pts.length - 1].label}` : pts[0].label
  const missingSuffix = seriesMissingDays.value.length ? ` · 窗口缺失 ${seriesMissingDays.value.length} 日` : ''
  return `${rangeLabel} · 日线口径（EOD 终值）${missingSuffix}`
}

const trackNote = computed(() => {
  if (seriesLoading.value) return '正在加载多日序列…'
  // 取数失败只在所选窗口无法满足时提示，不影响已加载窗口的正常展示
  if (seriesError.value && RANGE_DAYS[timeRange.value] > seriesDaysLoaded.value) {
    return `多日序列不可用：${seriesError.value}`
  }
  if (!trendPoints.value.length) return ''
  if (timeRange.value === '1d') {
    if (slotsDegradedReason.value) return slotsDegradedReason.value
    return slotsTradingDate.value ? `${slotsTradingDate.value} · 每半小时一帧，随采集更新` : ''
  }
  return dailyRangeNote(trendPoints.value)
})
</script>

<style scoped>
/* ========== 面板基础（token 对齐 SectorPanel/SectorDetail，2026-09-24 重写） ========== */
.hotlist-emotion-panel {
  position: fixed;
  width: 960px;
  max-width: calc(100vw - 40px);
  max-height: 80vh;
  display: flex;
  flex-direction: column;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
  z-index: 10006;
  font-size: 12px;
  overflow: hidden;
  backdrop-filter: blur(10px);
  color: var(--text-primary);
}

/* ========== 头部 ========== */
.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-header);
}
.header-left { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.panel-header h3 {
  margin: 0;
  font-size: 16px;
  color: var(--color-highlight);
  display: flex;
  align-items: center;
  gap: 8px;
}
.version-badge {
  font-size: 10px;
  background: var(--color-highlight);
  color: #000;
  padding: 2px 6px;
  border-radius: 12px;
}
.time-badge {
  font-size: 10px;
  background: var(--bg-secondary);
  color: var(--text-secondary);
  padding: 2px 6px;
  border-radius: 12px;
  cursor: help;
}
.time-badge.warn { color: #ff4757; }
.panel-actions { display: flex; gap: 8px; }
.btn-icon {
  width: 32px;
  height: 32px;
  border: 1px solid var(--border-color);
  background: transparent;
  border-radius: 8px;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 16px;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  justify-content: center;
}
.btn-icon:hover:not(:disabled) {
  background: var(--bg-hover);
  color: var(--text-primary);
  border-color: var(--color-highlight);
}
.btn-icon:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-icon.loading .rotate-animation { display: inline-block; animation: he-rotate 1s linear infinite; }
@keyframes he-rotate { to { transform: rotate(360deg); } }

/* ========== 页签 ========== */
.panel-tabs {
  display: flex;
  padding: 12px 20px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-secondary);
}
.tabs-left { display: flex; gap: 4px; flex: 1; }
.tab-btn {
  flex: 1;
  padding: 8px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  border-radius: 8px;
  font-size: 12px;
  transition: all 0.2s;
}
.tab-btn:hover { background: var(--bg-hover); color: var(--text-primary); }
.tab-btn.active { background: var(--color-highlight); color: #000; font-weight: 500; }

/* ========== 内容区 ========== */
.panel-content {
  padding: 20px;
  max-height: calc(80vh - 120px);
  overflow-y: auto;
}
.tab-pane { display: flex; flex-direction: column; gap: 16px; }
.state-block {
  display: flex; align-items: center; gap: 8px;
  padding: 24px; color: var(--text-secondary); justify-content: center;
}
.state-block.error { color: #ff4757; }
.spinner {
  width: 14px; height: 14px; border: 2px solid var(--border-color);
  border-top-color: var(--color-highlight); border-radius: 50%;
  animation: he-rotate 0.8s linear infinite;
}
.retry-btn {
  background: var(--color-highlight); color: #000; border: none;
  border-radius: 16px; padding: 4px 12px; cursor: pointer; font-size: 12px;
}

/* ========== 概览：阶段主卡（info-card 语言） ========== */
.stage-hero {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 16px;
}
.hero-label { font-size: 11px; color: var(--text-secondary); margin-bottom: 4px; }
.hero-stage { font-size: 28px; font-weight: bold; color: var(--text-title); line-height: 1.2; margin-bottom: 8px; }
.hero-meta { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 8px; }
.risk-chip, .conf-chip, .pending-chip {
  font-size: 10px; border-radius: 10px; padding: 2px 8px; display: inline-block;
}
.risk-high { background: rgba(255, 71, 87, 0.15); color: #ff4757; }
.risk-mid { background: rgba(255, 177, 66, 0.15); color: #ffb142; }
.risk-low { background: rgba(46, 213, 115, 0.15); color: #2ed573; }
.conf-chip { background: var(--bg-primary); border: 1px solid var(--border-color); color: var(--text-secondary); }
.pending-chip {
  background: rgba(255, 177, 66, 0.15);
  color: #ffb142;
  cursor: help;
}
.hero-summary { font-size: 12px; color: var(--text-secondary); }

/* ========== 三级卡片体系（SectorDetail 概览结构） ========== */
/* 主指标 4 列大卡：横向 + 48px 圆形图标底座 */
.metrics-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
.metric-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
}
.metric-icon {
  font-size: 28px;
  width: 48px;
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-primary);
  border-radius: 24px;
  flex-shrink: 0;
}
.metric-content { flex: 1; min-width: 0; }
.metric-label { font-size: 11px; color: var(--text-secondary); margin-bottom: 4px; }
.metric-value { font-size: 22px; font-weight: bold; line-height: 1.2; font-variant-numeric: tabular-nums; }
.metric-value.up { color: #ff4757; }
.metric-value.down { color: #2ed573; }
.metric-unit { font-size: 11px; font-weight: normal; color: var(--text-secondary); margin-left: 2px; }
/* 阶段迁移卡（metric-card 语言，3×2） */
.transition-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }

/* 资金/证据中卡 3-4 列：横向 + 32px 圆形底座 */
.funds-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
.fund-card {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 10px;
}
.fund-icon {
  font-size: 20px;
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-primary);
  border-radius: 16px;
  flex-shrink: 0;
}
.fund-content { flex: 1; min-width: 0; }
.fund-label { font-size: 10px; color: var(--text-secondary); margin-bottom: 2px; }
.fund-value { font-size: 14px; font-weight: bold; font-variant-numeric: tabular-nums; }
.fund-value.up { color: #ff4757; }
.fund-value.down { color: #2ed573; }

/* 涨停证据容器网格：交集 4 列 / 全市场背景与昨日表现 6 列 */
.grid-4 { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
.grid-6 { display: grid; grid-template-columns: repeat(6, 1fr); gap: 8px; }

/* 统计小卡 4 列：竖排居中 */
.stats-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
.stat-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 10px;
}
.stat-icon { font-size: 18px; margin-bottom: 4px; }
.stat-value { font-size: 18px; font-weight: bold; color: var(--text-title); font-variant-numeric: tabular-nums; }
.stat-value.up { color: #ff4757; }
.stat-value.down { color: #2ed573; }
.stat-label { font-size: 10px; color: var(--text-secondary); margin-top: 2px; text-align: center; }

/* ========== 子块（leaders-section 语言） ========== */
.sub-block {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 16px;
}
.block-title { font-size: 14px; font-weight: 500; color: var(--text-title); margin-bottom: 12px; }
/* 市场概览三容器可点击（sector-card 悬浮语言） */
.sub-block.clickable { cursor: pointer; transition: all 0.2s; }
.sub-block.clickable:hover {
  transform: translateY(-2px);
  border-color: var(--color-highlight);
  box-shadow: 0 4px 12px rgba(255, 177, 66, 0.2);
}
/* 块标题行：标题居左 + 计数徽章居右（SectorDetail section-header 语言） */
.block-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.block-header .block-title { margin-bottom: 0; }
.section-count {
  padding: 2px 8px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  font-size: 10px;
  color: var(--text-secondary);
}
.note-line { font-size: 11px; color: var(--text-secondary); margin-top: 8px; }
.chip-wrap { display: flex; flex-wrap: wrap; gap: 6px; }
.chip {
  font-size: 10px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 2px 8px;
  color: var(--text-secondary);
}
.chip.diag { border-style: dashed; }
.up-text { color: #ff4757; }
.down-text { color: #2ed573; }
.empty-row { color: var(--text-secondary); text-align: center; padding: 8px 0; }

/* ========== 池换手明细（stocks-table 语言） ========== */
.to-header { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.to-filters { display: flex; gap: 4px; }
.to-filter-btn {
  padding: 6px 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  color: var(--text-secondary);
  font-size: 11px;
  cursor: pointer;
  transition: all 0.2s;
}
.to-filter-btn:hover { background: var(--bg-hover); color: var(--text-primary); }
.to-filter-btn.active { background: var(--color-highlight); border-color: var(--color-highlight); color: #000; }
.to-stats {
  font-size: 12px;
  color: var(--text-primary);
  font-weight: 500;
  background: var(--bg-tertiary, var(--bg-secondary));
  border-radius: 8px;
  padding: 8px 12px;
}
.to-table-container {
  max-height: 500px;
  overflow-y: auto;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--bg-primary);
}
.to-table { border-collapse: collapse; font-size: 12px; width: auto; min-width: 100%; table-layout: auto; }
.to-table th {
  position: sticky;
  top: 0;
  background: var(--bg-header);
  padding: 10px 6px;
  text-align: left;
  font-weight: 600;
  color: var(--text-primary);
  border-bottom: 2px solid var(--border-color);
  white-space: nowrap;
  z-index: 1;
}
.to-table td {
  padding: 8px 6px;
  border-bottom: 1px solid var(--border-color);
  white-space: nowrap;
}
.to-table tbody tr:hover { background: var(--bg-hover); }
.to-table tbody tr.entry-row { border-left: 4px solid #2ed573; }
.to-code {
  color: var(--color-highlight);
  text-decoration: underline;
  text-decoration-color: rgba(255, 127, 80, 0.5);
  font-weight: 500;
}
.to-table .change { font-variant-numeric: tabular-nums; text-align: right; }
.to-table .num { font-variant-numeric: tabular-nums; }
/* 涨红跌绿：特异性压过 td color（与成分股列表一致） */
.to-table .up-text { color: #ff4757; }
.to-table .down-text { color: #2ed573; }
.to-kind-badge {
  padding: 2px 6px;
  border-radius: 10px;
  font-size: 10px;
}
.to-kind-badge.entry { background: rgba(46, 213, 115, 0.15); color: #2ed573; }
.to-kind-badge.exit { background: rgba(255, 71, 87, 0.15); color: #ff4757; }
.to-reason {
  display: inline-block;
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  vertical-align: bottom;
  color: var(--text-secondary);
}

/* ========== 阶段分布（左环形图 + 右排序明细） ========== */
.stage-layout { display: flex; align-items: center; gap: 32px; }
.stage-pie { position: relative; width: 240px; height: 240px; flex-shrink: 0; }
.stage-pie-canvas { position: absolute; inset: 0; }
.stage-pie-center {
  position: absolute; inset: 0;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  pointer-events: none;
}
.stage-pie-total { font-size: 26px; font-weight: bold; color: var(--text-title); font-variant-numeric: tabular-nums; line-height: 1.2; }
.stage-pie-unit { font-size: 10px; color: var(--text-secondary); margin-top: 2px; }
.stage-detail { flex: 1; display: flex; flex-direction: column; gap: 14px; min-width: 0; }
.stage-row { display: flex; align-items: center; gap: 10px; }
.stage-dot { width: 10px; height: 10px; border-radius: 3px; flex-shrink: 0; }
.stage-name { width: 52px; font-size: 12px; color: var(--text-primary); flex-shrink: 0; }
.stage-bar { flex: 1; height: 6px; background: var(--bg-primary); border-radius: 3px; overflow: hidden; }
.stage-bar-fill { height: 100%; border-radius: 3px; transition: width 0.3s; }
.stage-count {
  width: 40px; text-align: right; font-size: 12px; font-weight: 600;
  color: var(--text-title); font-variant-numeric: tabular-nums;
}
.stage-pct {
  width: 52px; text-align: right; font-size: 11px; font-weight: 600;
  color: var(--color-highlight); font-variant-numeric: tabular-nums;
}

/* ========== 情绪趋势 / 历史对比 / 分层结构（SectorDetail 历史趋势图表语言，三图表共用） ========== */
.time-range-selector, .indicator-selector { display: flex; gap: 8px; flex-wrap: wrap; }
.time-btn, .indicator-btn {
  padding: 4px 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  color: var(--text-secondary);
  font-size: 11px;
  cursor: pointer;
  transition: all 0.2s;
}
.time-btn:hover, .indicator-btn:hover { background: var(--bg-hover); color: var(--text-primary); }
.time-btn.active, .indicator-btn.active { background: var(--color-highlight); border-color: var(--color-highlight); color: #000; }
.trend-chart {
  height: 250px;
  width: 100%;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 10px;
}
.trend-stats-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
.trend-stat-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  padding: 12px;
  text-align: center;
}
.trend-stat-card .stat-label { font-size: 10px; color: var(--text-secondary); margin-bottom: 4px; }
.trend-stat-card .stat-value {
  font-size: 18px; font-weight: bold; color: var(--text-title);
  line-height: 1.2; font-variant-numeric: tabular-nums;
}
.trend-stat-card .stat-time { font-size: 9px; color: var(--text-secondary); margin-top: 4px; min-height: 12px; }

/* ========== 证据与风险 ========== */
.evidence-columns { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.evidence-columns.two { align-items: start; }
.evidence-list { margin: 0; padding-left: 16px; line-height: 1.7; font-size: 12px; }
.diag-block {
  display: flex; flex-wrap: wrap; gap: 4px 10px; align-items: baseline;
  border: 1px dashed var(--border-color); border-radius: 8px;
  padding: 8px 12px; font-size: 11px; color: var(--text-secondary);
}
.diag-tag { font-weight: 600; color: #ffb142; }

@media (max-width: 720px) {
  .evidence-columns { grid-template-columns: 1fr; }
  .metrics-grid, .grid-4 { grid-template-columns: repeat(2, 1fr); }
  .grid-6 { grid-template-columns: repeat(3, 1fr); }
  .trend-stats-grid { grid-template-columns: repeat(2, 1fr); }
  .stage-layout { flex-direction: column; }
  .stage-pie { width: 200px; height: 200px; }
  .hotlist-emotion-panel { width: calc(100vw - 16px); }
}
</style>
