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
          <!-- ① 热榜概览 -->
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

            <div class="card-grid">
              <div v-for="card in overviewCards" :key="card.label" class="metric-card">
                <div class="metric-icon">{{ card.icon }}</div>
                <div class="metric-value" :class="card.toneClass">{{ card.value }}</div>
                <div class="metric-label">{{ card.label }}</div>
              </div>
            </div>

            <div class="sub-block">
              <div class="block-title">🔁 池换手汇总</div>
              <div class="turnover-chips">
                <span class="chip">昨池 {{ turnover.previousPoolSize }}</span>
                <span class="chip">今池 {{ turnover.currentPoolSize }}</span>
                <span class="chip">留存 {{ turnover.retainedFromYesterday }}</span>
                <span class="chip up-text">新入 {{ doc.metrics.comparison.newTop100Count }}</span>
                <span class="chip down-text">剔除 {{ eliminatedCount }}</span>
                <span class="chip">进出明细见「池换手」页签</span>
              </div>
            </div>
          </section>

          <!-- ② 分层结构 -->
          <section v-show="view === 'layers'" class="tab-pane">
            <table class="data-table layers-table">
              <thead>
                <tr>
                  <th>分层</th><th>池/样本</th><th>涨占比</th><th>跌占比</th><th>TRIN</th><th>平均涨幅</th>
                  <th>近涨停</th><th>高涨幅</th><th>高换手</th><th>主力净额</th><th>超大单净额</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in layerRows" :key="row.label">
                  <td class="layer-name">{{ row.label }}</td>
                  <td class="num">{{ row.poolText }}</td>
                  <td class="num">{{ row.upRatio }}</td>
                  <td class="num">{{ row.downRatio }}</td>
                  <td class="num">{{ row.trin }}</td>
                  <td class="num" :class="row.avgTone">{{ row.avgChange }}</td>
                  <td class="num">{{ row.nearLimitUp }}</td>
                  <td class="num">{{ row.highGain }}</td>
                  <td class="num">{{ row.highTurnover }}</td>
                  <td class="num money">{{ row.mainNet }}</td>
                  <td class="num money">{{ row.superNet }}</td>
                </tr>
              </tbody>
            </table>
            <div v-if="!layerRows.length" class="empty-row">分层结构暂无数据（旧结构文档缺字段）</div>
          </section>

          <!-- ③ 涨停证据 -->
          <section v-show="view === 'limit'" class="tab-pane">
            <div class="evidence-columns">
              <div class="sub-block">
                <div class="block-title">🔥 热榜池涨停交集</div>
                <div class="card-grid compact">
                  <div v-for="item in intersectionCards" :key="item.label" class="metric-card">
                    <div class="metric-value">{{ item.value }}</div>
                    <div class="metric-label">{{ item.label }}</div>
                  </div>
                </div>
              </div>
              <div class="sub-block">
                <div class="block-title">🌐 全市场背景（非热榜池口径）</div>
                <div class="card-grid compact">
                  <div v-for="item in marketCards" :key="item.label" class="metric-card">
                    <div class="metric-value">{{ item.value }}</div>
                    <div class="metric-label">{{ item.label }}</div>
                  </div>
                </div>
                <div v-if="marketEvidenceNote" class="note-line">{{ marketEvidenceNote }}</div>
              </div>
              <div class="sub-block">
                <div class="block-title">📜 昨日热榜涨停表现</div>
                <div class="card-grid compact">
                  <div v-for="item in yesterdayLimitCards" :key="item.label" class="metric-card">
                    <div class="metric-value">{{ item.value }}</div>
                    <div class="metric-label">{{ item.label }}</div>
                  </div>
                </div>
              </div>
            </div>
          </section>

          <!-- ③b 池换手（分池+出池合并明细，成分股列表风格） -->
          <section v-show="view === 'turnover'" class="tab-pane">
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
                    <td>{{ row.name || '-' }}</td>
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

          <!-- ④ 状态结构 -->
          <section v-show="view === 'structure'" class="tab-pane">
            <div class="sub-block">
              <div class="block-title">🧭 全池状态结构（今日快照池）</div>
              <div v-for="item in statusItems" :key="item.key" class="status-row">
                <span class="status-label" :class="`stage-${item.key}`">{{ item.label }}</span>
                <div class="status-bar-wrap">
                  <div class="status-bar" :style="{ width: item.sharePct }"></div>
                </div>
                <span class="num status-count">{{ item.count }}</span>
                <span class="num status-share">{{ item.sharePct }}</span>
              </div>
            </div>
            <div class="sub-block">
              <div class="block-title">🔀 阶段迁移（降序前 6）</div>
              <div class="chip-wrap">
                <span v-for="item in transitionItems" :key="item.key" class="chip">{{ item.text }} {{ item.count }}</span>
                <span v-if="!transitionItems.length" class="empty-row">暂无迁移数据</span>
              </div>
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

          <!-- ⑤ 三日对比 -->
          <section v-show="view === 'compare'" class="tab-pane">
            <div class="compare-grid">
              <div v-for="day in historyItems" :key="day.label" class="compare-card">
                <div class="compare-label">{{ day.label }}</div>
                <div class="compare-total">{{ day.total }}</div>
                <div class="compare-sub">
                  冷却 {{ day.cooling }} · 拥挤 {{ day.crowded }} · 风险 {{ day.risk }}
                </div>
              </div>
            </div>
            <div class="sub-block">
              <div class="block-title">📌 池留存与流动</div>
              <div class="chip-wrap">
                <span class="chip">规模环比 {{ formatSigned(comparison?.totalChange1d) }}</span>
                <span class="chip">留榜 {{ comparison?.top100RetainFromYesterday ?? '--' }}（{{ formatShare(comparison?.top100RetainRateFromYesterday) }}）</span>
                <span class="chip">前日留榜 {{ comparison?.top100RetainFromDayBefore ?? '--' }}（{{ formatShare(comparison?.top100RetainRateFromDayBefore) }}）</span>
                <span class="chip up-text">新入 {{ comparison?.newTop100Count ?? 0 }}</span>
                <span class="chip">新入强资 {{ comparison?.newTop100StrongMoneyCount ?? 0 }}</span>
                <span class="chip">昨日拥挤转风险 {{ comparison?.yesterdayCrowdedRiskCount ?? '--' }}</span>
              </div>
            </div>
            <div class="sub-block">
              <div class="block-title">💪 昨日强票今日表现</div>
              <div class="card-grid compact">
                <div v-for="item in strongPerformanceCards" :key="item.label" class="metric-card">
                  <div class="metric-value">{{ item.value }}</div>
                  <div class="metric-label">{{ item.label }}</div>
                </div>
              </div>
            </div>
          </section>

          <!-- ⑥ 日内情绪轨迹 -->
          <section v-show="view === 'track'" class="tab-pane">
            <div v-if="transitionItems.length" class="chip-wrap">
              <span v-for="item in transitionItems" :key="`t${item.key}`" class="chip">{{ item.text }} {{ item.count }}</span>
            </div>
            <div class="slot-track">
              <div v-for="item in trackItems" :key="item.key" class="track-row" :class="{ latest: item.isLatest }">
                <span class="track-time">{{ item.label }}<span v-if="item.isLatest" class="now-chip">当前</span></span>
                <span class="track-stage" :class="`stage-${item.stageClass}`">{{ item.stage }}</span>
                <span v-if="item.drift" class="track-drift" :title="`当帧盘面判定：${item.driftRaw}`">{{ item.drift }}</span>
                <span class="track-metric">池 {{ item.pool }}</span>
                <span class="track-metric">涨 {{ item.upRatio }}</span>
                <span class="track-metric">攻击 {{ item.attack }}</span>
                <span class="track-metric down-text">风险 {{ item.risk }}</span>
                <span class="track-metric">TRIN {{ item.trin }}</span>
              </div>
              <div v-if="!trackItems.length" class="empty-row">当日暂无槽位数据</div>
            </div>
            <div v-if="trackNote" class="note-line">{{ trackNote }}</div>
          </section>

          <!-- ⑦ 证据与风险 -->
          <section v-show="view === 'evidence'" class="tab-pane">
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
        </template>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  fetchHotlistSentimentSeries,
  fetchHotlistSentimentSlots,
  type HotlistSentimentMissingDay,
} from '@/services/hotlist/hotlistSentimentApi'
import {
  HOT_LIST_STAGE_LABELS,
  type HotListDayMetrics,
  type HotListSentimentDayDoc,
  type HotListStageKey,
} from '@/types/hotlistSentiment'

const props = defineProps<{ visible: boolean; triggerRect?: DOMRect | null }>()
const emit = defineEmits<{ (e: 'close'): void }>()

const TABS = [
  { key: 'overview', label: '热榜概览', icon: '📊' },
  { key: 'layers', label: '分层结构', icon: '🧱' },
  { key: 'limit', label: '涨停证据', icon: '🔥' },
  { key: 'turnover', label: '池换手', icon: '🔁' },
  { key: 'structure', label: '状态结构', icon: '🧭' },
  { key: 'compare', label: '三日对比', icon: '🗓️' },
  { key: 'track', label: '日内轨迹', icon: '⏱️' },
  { key: 'evidence', label: '证据与风险', icon: '⚖️' },
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
function formatSigned(value?: number | null): string {
  return typeof value === 'number' && Number.isFinite(value)
    ? `${value > 0 ? '+' : ''}${Math.round(value)}`
    : '--'
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

const overviewCards = computed(() => {
  const layer = allLayer.value
  const comp = comparison.value
  if (!layer) return []
  return [
    { icon: '📊', label: '参与统计', value: formatNullableCount(layer.topN), toneClass: '' },
    { icon: '📈', label: '上涨占比', value: formatShare(layer.upRatio), toneClass: 'up-text' },
    { icon: '📉', label: '下跌占比', value: formatShare(layer.downRatio), toneClass: 'down-text' },
    { icon: '⚖️', label: '热榜 TRIN', value: formatTrin(layer.hotTrin), toneClass: '' },
    { icon: '🔥', label: '近涨停', value: formatNullableCount(layer.nearLimitUpCount), toneClass: '' },
    { icon: '🚀', label: '高涨幅≥7%', value: formatNullableCount(layer.highGainCount), toneClass: '' },
    { icon: '🌀', label: '高换手≥10%', value: formatNullableCount(layer.highTurnoverCount), toneClass: '' },
    { icon: '💰', label: '主力净额', value: formatMoney(layer.mainNetAmount), toneClass: (layer.mainNetAmount ?? 0) >= 0 ? 'up-text' : 'down-text' },
    { icon: '🏦', label: '超大单净额', value: formatMoney(layer.superNetAmount), toneClass: (layer.superNetAmount ?? 0) >= 0 ? 'up-text' : 'down-text' },
    { icon: '🆕', label: '今日新入', value: formatNullableCount(comp?.newTop100Count ?? null), toneClass: '' },
    { icon: '💪', label: '新入强资', value: formatNullableCount(comp?.newTop100StrongMoneyCount ?? null), toneClass: '' },
    { icon: '🔁', label: '昨日强资留榜', value: formatShare(comp?.yesterdayStrongRetainRate ?? null), toneClass: '' },
  ]
})

// ---------- 分层结构 ----------
const layerRows = computed(() => {
  const layers = doc.value?.metrics.layers
  if (!layers) return []
  return [
    { label: '前20', metrics: layers.top20 },
    { label: '前50', metrics: layers.top50 },
    { label: '前100', metrics: layers.top100 },
    { label: '全池', metrics: layers.all },
  ].map(({ label, metrics }) => ({
    label,
    poolText: metrics ? `${formatNullableCount(metrics.total)} / ${formatNullableCount(metrics.topN)}` : '--',
    upRatio: formatShare(metrics?.upRatio),
    downRatio: formatShare(metrics?.downRatio),
    trin: formatTrin(metrics?.hotTrin),
    avgChange: formatPercent(metrics?.avgChange),
    avgTone: (metrics?.avgChange ?? 0) >= 0 ? 'up-text' : 'down-text',
    nearLimitUp: formatNullableCount(metrics?.nearLimitUpCount),
    highGain: formatNullableCount(metrics?.highGainCount),
    highTurnover: formatNullableCount(metrics?.highTurnoverCount),
    mainNet: formatMoney(metrics?.mainNetAmount),
    superNet: formatMoney(metrics?.superNetAmount),
  }))
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
    { label: '池内炸板', value: `${formatNullableCount(it.top100ZhabanCount)}（${formatShare(it.top100ZhabanShare)}）` },
  ]
})
const marketCards = computed(() => {
  const market = limitEvidence.value?.market
  if (!market) return []
  const ths = market.thsPools ?? null
  return [
    { label: '全市场涨停', value: formatNullableCount(market.ztCount) },
    { label: '封板率', value: market.fengbanRate != null ? `${market.fengbanRate.toFixed(0)}%` : '--' },
    { label: '全市场炸板', value: formatNullableCount(market.zhabanCount) },
    { label: '首板', value: formatNullableCount(market.board1) },
    { label: '2板', value: formatNullableCount(market.board2) },
    { label: '3板', value: formatNullableCount(market.board3) },
    { label: '4板+', value: formatNullableCount(market.board4Plus) },
    { label: '最高连板', value: `${formatNullableCount(market.maxContinuousDays)} 板` },
    { label: 'THS 炸板池', value: ths ? formatNullableCount(ths.failedCount) : '--' },
    { label: 'THS 回撤榜', value: ths ? formatNullableCount(ths.drawdownCount) : '--' },
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
    { label: '昨日涨停数', value: formatNullableCount(y.count) },
    { label: '留榜数', value: formatNullableCount(y.retainedTop100Count) },
    { label: '今日均涨', value: formatPercent(y.avgChange) },
    { label: '正收益率', value: formatShare(y.positiveRate) },
    { label: '走弱率', value: formatShare(y.weakeningRate) },
    { label: '冲板失败率', value: formatShare(y.failedOrWeakRate) },
  ]
})

// ---------- 状态结构 ----------
const statusItems = computed(() => {
  const all = allLayer.value
  if (!all?.stageCounts) return []
  return (Object.keys(HOT_LIST_STAGE_LABELS) as HotListStageKey[]).map((key) => ({
    key,
    label: HOT_LIST_STAGE_LABELS[key],
    count: all.stageCounts[key] ?? 0,
    sharePct: formatShare(all.stageShares?.[key]),
  }))
})
const transitionItems = computed(() => {
  const counts = doc.value?.metrics.transitionCounts as Record<string, number> | undefined
  if (!counts) return []
  return Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 6)
    .map(([text, count]) => ({ key: text, text: text.replace('->', '→'), count }))
})

// ---------- 三日对比 ----------
const historyItems = computed(() => {
  const comp = comparison.value
  if (!comp) return []
  const toItem = (label: string, metrics?: HotListDayMetrics | null) => {
    const counts = metrics?.stageCounts
    return {
      label,
      total: metrics ? `${formatNullableCount(metrics.topN)} 只` : '--',
      cooling: counts ? formatNullableCount(counts.cooling) : '--',
      crowded: counts ? formatNullableCount(counts.crowded) : '--',
      risk: counts ? formatNullableCount(counts.reversal + counts.cooling) : '--',
    }
  }
  return [
    toItem('T 今日', comp.today),
    toItem('T-1 昨日', comp.yesterday),
    toItem('T-2 前日', comp.dayBefore),
  ]
})
const strongPerformanceCards = computed(() => {
  const perf = comparison.value?.yesterdayStrongPerformance
  if (!perf) return []
  return [
    { label: '昨日强票数', value: formatNullableCount(perf.count) },
    { label: '可比对数', value: formatNullableCount(perf.matchedCount) },
    { label: '留榜数', value: formatNullableCount(perf.retainedTop100Count) },
    { label: '今日均涨', value: formatPercent(perf.avgChange) },
    { label: '正收益率', value: formatShare(perf.positiveRate) },
    { label: '转弱率', value: formatShare(perf.weakeningRate) },
  ]
})

// ---------- 日内轨迹（情绪路径：确认阶段为主值，分歧人话标注） ----------
function stageDriftText(rawStage: string, confirmedStage: string): string {
  const rawHeat = STAGE_HEAT[rawStage] ?? 1
  const confirmedHeat = STAGE_HEAT[confirmedStage] ?? 1
  if (rawHeat > confirmedHeat) return '短暂走高'
  if (rawHeat < confirmedHeat) return '短暂回落'
  return '盘中波动'
}
const trackItems = computed(() => {
  if (!slots.value.length) return []
  return slots.value.map((slot, index) => {
    const all = slot.metrics?.layers?.all
    const counts = all?.stageCounts
    const rawStage = slot.rawStage || slot.stage
    const drift = rawStage !== slot.stage ? stageDriftText(rawStage, slot.stage) : ''
    return {
      key: slot.slotTime || `slot-${index}`,
      label: slot.slotTime || '--',
      isLatest: index === slots.value.length - 1,
      stage: slot.stage,
      stageClass: `tone-${STAGE_HEAT[slot.stage] ?? 1}`,
      drift,
      driftRaw: rawStage,
      pool: formatNullableCount(slot.metrics?.poolSize ?? all?.total ?? null),
      upRatio: formatShare(all?.upRatio ?? null),
      attack: `${formatNullableCount(counts ? counts.ignition + counts.expansion : null)} / ${formatShare(all ? (all.stageShares?.ignition ?? 0) + (all.stageShares?.expansion ?? 0) : null)}`,
      risk: counts ? formatNullableCount(counts.reversal + counts.cooling) : '--',
      trin: formatTrin(all?.hotTrin),
    }
  })
})
const trackNote = computed(() => {
  if (slotsDegradedReason.value) return slotsDegradedReason.value
  if (!trackItems.value.length) return ''
  return slotsTradingDate.value ? `${slotsTradingDate.value} · 每半小时一帧，随采集更新` : ''
})
</script>

<style scoped>
.hotlist-emotion-panel {
  position: fixed;
  z-index: 1200;
  width: 960px;
  max-width: calc(100vw - 16px);
  max-height: min(78vh, 780px);
  display: flex;
  flex-direction: column;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.35);
  color: var(--text-primary);
  font-family: inherit;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  background: var(--bg-header);
  border-bottom: 1px solid var(--border-color);
  border-radius: 8px 8px 0 0;
}
.header-left { display: flex; align-items: center; gap: 10px; }
.header-left h3 { margin: 0; font-size: 15px; display: flex; align-items: center; gap: 6px; }
.version-badge {
  font-size: 10px;
  color: var(--color-highlight);
  border: 1px solid var(--color-highlight);
  border-radius: 3px;
  padding: 0 3px;
}
.time-badge {
  font-size: 11px;
  color: var(--text-secondary);
  background: var(--bg-secondary);
  border-radius: 3px;
  padding: 1px 6px;
}
.time-badge.warn { color: #d97706; }
.panel-actions { display: flex; gap: 6px; }
.btn-icon {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  color: var(--text-primary);
  padding: 3px 8px;
  cursor: pointer;
  font-size: 12px;
}
.btn-icon:hover { background: var(--bg-hover); }
.btn-icon.loading .rotate-animation { display: inline-block; animation: he-rotate 1s linear infinite; }
@keyframes he-rotate { to { transform: rotate(360deg); } }

.panel-tabs {
  display: flex;
  padding: 6px 10px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-secondary);
}
.tabs-left { display: flex; gap: 4px; flex-wrap: wrap; }
.tab-btn {
  background: transparent;
  border: none;
  color: var(--text-secondary);
  padding: 5px 12px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 13px;
}
.tab-btn.active { background: var(--color-highlight); color: #fff; }
.tab-btn:hover:not(.active) { background: var(--bg-hover); color: var(--text-primary); }

.panel-content { padding: 12px 14px; overflow-y: auto; flex: 1; }
.tab-pane { display: flex; flex-direction: column; gap: 12px; }
.state-block {
  display: flex; align-items: center; gap: 8px;
  padding: 24px; color: var(--text-secondary); justify-content: center;
}
.state-block.error { color: #ef4444; }
.spinner {
  width: 14px; height: 14px; border: 2px solid var(--border-color);
  border-top-color: var(--color-highlight); border-radius: 50%;
  animation: he-rotate 0.8s linear infinite;
}
.retry-btn {
  background: var(--color-highlight); color: #fff; border: none;
  border-radius: 4px; padding: 3px 10px; cursor: pointer;
}

/* 阶段主卡 */
.stage-hero {
  border: 1px solid var(--border-color);
  border-left: 4px solid var(--color-highlight);
  border-radius: 6px;
  background: var(--bg-secondary);
  padding: 12px 14px;
}
.hero-label { font-size: 12px; color: var(--text-secondary); }
.hero-stage { font-size: 30px; font-weight: 700; margin: 2px 0 6px; }
.stage-tone-hot .hero-stage { color: #ef4444; }
.stage-tone-warm .hero-stage { color: #f59e0b; }
.stage-tone-cold .hero-stage { color: #22c55e; }
.hero-meta { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 6px; }
.risk-chip, .conf-chip, .pending-chip {
  font-size: 11px; border-radius: 3px; padding: 1px 8px;
  background: var(--bg-primary); border: 1px solid var(--border-color);
}
.risk-high { color: #ef4444; }
.risk-mid { color: #f59e0b; }
.risk-low { color: #22c55e; }
.pending-chip { color: #d97706; border-style: dashed; cursor: help; }
.hero-summary { font-size: 13px; color: var(--text-secondary); }

/* 指标卡 */
.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(128px, 1fr));
  gap: 8px;
}
.card-grid.compact { grid-template-columns: repeat(auto-fill, minmax(108px, 1fr)); }
.metric-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  padding: 10px 8px;
  text-align: center;
}
.metric-icon { font-size: 15px; margin-bottom: 2px; }
.metric-value { font-size: 19px; font-weight: 700; font-variant-numeric: tabular-nums; }
.metric-label { font-size: 11px; color: var(--text-secondary); margin-top: 2px; }

/* 子块与表格 */
.sub-block {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  padding: 10px 12px;
}
.block-title { font-size: 13px; font-weight: 600; margin-bottom: 8px; }
.note-line { font-size: 11px; color: var(--text-secondary); margin-top: 6px; }
.chip-wrap { display: flex; flex-wrap: wrap; gap: 6px; }
.chip {
  font-size: 11px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  padding: 2px 9px;
}
.chip.diag { color: var(--text-secondary); border-style: dashed; }
.up-text { color: #ef4444; }
.down-text { color: #22c55e; }
.empty-row { color: var(--text-secondary); text-align: center; padding: 8px 0; }

.data-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.data-table th {
  text-align: left; color: var(--text-secondary); font-weight: 500;
  padding: 5px 8px; border-bottom: 1px solid var(--border-color);
  white-space: nowrap;
}
.data-table td { padding: 5px 8px; border-bottom: 1px solid var(--border-color); }
.data-table tbody tr:hover { background: var(--bg-hover); }
.data-table .num { font-variant-numeric: tabular-nums; text-align: right; }
.layers-table .layer-name { font-weight: 600; }
.money { font-variant-numeric: tabular-nums; }

.table-two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.table-col .col-title { font-size: 12px; font-weight: 600; margin-bottom: 6px; }
.reason-chip {
  font-size: 11px; border: 1px solid var(--border-color);
  border-radius: 3px; padding: 0 5px; color: var(--text-secondary);
}

/* 状态结构 */
.status-row { display: flex; align-items: center; gap: 10px; padding: 3px 0; }
.status-label { width: 48px; font-size: 12px; }
.status-bar-wrap { flex: 1; height: 8px; background: var(--bg-primary); border-radius: 4px; overflow: hidden; }
.status-bar { height: 100%; background: var(--color-highlight); border-radius: 4px; min-width: 2px; }
.status-count { width: 36px; text-align: right; }
.status-share { width: 44px; text-align: right; color: var(--text-secondary); }

/* 三日对比 */
.compare-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
.compare-card {
  background: var(--bg-secondary); border: 1px solid var(--border-color);
  border-radius: 6px; padding: 10px; text-align: center;
}
.compare-label { font-size: 12px; color: var(--text-secondary); }
.compare-total { font-size: 22px; font-weight: 700; margin: 2px 0; }
.compare-sub { font-size: 11px; color: var(--text-secondary); }

/* 日内轨迹 */
.slot-track { display: flex; flex-direction: column; gap: 2px; }
.track-row {
  display: flex; align-items: center; gap: 12px;
  padding: 5px 10px; border-radius: 4px; font-size: 12px;
}
.track-row:hover { background: var(--bg-hover); }
.track-row.latest { border: 1px solid var(--color-highlight); }
.track-time { width: 60px; color: var(--text-secondary); font-variant-numeric: tabular-nums; }
.now-chip {
  margin-left: 4px; font-size: 10px; color: #fff;
  background: var(--color-highlight); border-radius: 3px; padding: 0 4px;
}
.track-stage {
  min-width: 44px; text-align: center; border-radius: 3px;
  padding: 1px 6px; background: var(--bg-primary);
  border: 1px solid var(--border-color);
}
.stage-tone-3, .stage-tone-2 { color: #ef4444; }
.stage-tone-1 { color: #f59e0b; }
.stage-tone-0 { color: #22c55e; }
.track-drift {
  color: #d97706; border-bottom: 1px dashed currentColor;
  cursor: help; font-size: 11px;
}
.track-metric { color: var(--text-secondary); font-variant-numeric: tabular-nums; }

/* 证据 */
.evidence-columns { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.evidence-columns.two { align-items: start; }
.evidence-list { margin: 0; padding-left: 16px; line-height: 1.7; font-size: 12px; }
.diag-block {
  display: flex; flex-wrap: wrap; gap: 4px 10px; align-items: baseline;
  border: 1px dashed var(--border-color); border-radius: 4px;
  padding: 4px 8px; font-size: 11px; color: var(--text-secondary);
}
.diag-tag { font-weight: 600; color: #d97706; }

/* 池换手明细（2026-09-24）：对齐 SectorDetail 成分股列表语言 */
.to-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.to-filters { display: flex; gap: 6px; }
.to-filter-btn {
  padding: 4px 14px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  color: var(--text-secondary);
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s;
}
.to-filter-btn:hover { background: var(--bg-hover); color: var(--text-primary); }
.to-filter-btn.active { background: var(--color-highlight); border-color: var(--color-highlight); color: #fff; }
.to-stats {
  font-size: 12px;
  color: var(--text-primary);
  font-weight: 500;
  background: var(--bg-tertiary, var(--bg-secondary));
  border-radius: 8px;
  padding: 6px 12px;
}
.to-table-container {
  max-height: 460px;
  overflow-y: auto;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--bg-primary);
}
.to-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.to-table th {
  position: sticky;
  top: 0;
  background: var(--bg-header);
  padding: 9px 10px;
  text-align: left;
  font-weight: 600;
  color: var(--text-primary);
  border-bottom: 2px solid var(--border-color);
  white-space: nowrap;
  z-index: 1;
}
.to-table td {
  padding: 8px 10px;
  border-bottom: 1px solid var(--border-color);
  white-space: nowrap;
  color: var(--text-primary);
}
.to-table tbody tr:hover { background: var(--bg-hover); }
.to-table tbody tr.entry-row { border-left: 4px solid #2ecc71; }
.to-code {
  color: var(--color-highlight);
  text-decoration: underline;
  text-decoration-color: rgba(255, 127, 80, 0.5);
  font-weight: 500;
}
.to-table .change { font-variant-numeric: tabular-nums; text-align: right; }
.to-table .num { font-variant-numeric: tabular-nums; }
.to-kind-badge {
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 10px;
}
.to-kind-badge.entry {
  background: rgba(46, 204, 113, 0.15);
  border: 1px solid rgba(46, 204, 113, 0.3);
  color: #2ecc71;
}
.to-kind-badge.exit {
  background: rgba(255, 71, 87, 0.15);
  border: 1px solid rgba(255, 71, 87, 0.3);
  color: #ff4757;
}
.to-reason {
  display: inline-block;
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  vertical-align: bottom;
  color: var(--text-secondary);
}

@media (max-width: 720px) {
  .table-two-col, .evidence-columns { grid-template-columns: 1fr; }
  .compare-grid { grid-template-columns: 1fr; }
  .hotlist-emotion-panel { width: calc(100vw - 16px); }
}
</style>
