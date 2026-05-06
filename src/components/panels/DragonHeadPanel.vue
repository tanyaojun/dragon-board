<template>
  <Teleport to="body">
    <div v-if="props.visible" ref="panelRef" class="dragon-panel" :style="panelStyle" @click.stop>
      <div class="panel-header" :style="{ background: phaseGradient }">
        <div class="header-top">
          <div class="header-left">
            <span class="panel-icon">🐲</span>
            <div class="header-title">
              <h2>龙头复盘</h2>
              <div class="header-subtitle">旧版轻面板结构，直接吃当前真龙复盘兼容数据</div>
            </div>
          </div>

          <div class="header-actions">
            <button class="btn-icon" type="button" title="刷新复盘" :disabled="loading" @click="refresh">
              <span class="icon">{{ loading ? '⟳' : '↻' }}</span>
            </button>
            <button class="btn-icon" type="button" title="导出复盘" :disabled="!leaders.length" @click="exportData">
              <span class="icon">⤓</span>
            </button>
            <button class="btn-icon close" type="button" title="关闭" @click="close">
              <span class="icon">✕</span>
            </button>
          </div>
        </div>

        <div class="sentiment-card">
          <div class="sentiment-left">
            <span class="phase-icon">{{ phaseIcon }}</span>
            <div class="sentiment-info">
              <div class="sentiment-phase">{{ sentiment.phaseName }}</div>
              <div class="sentiment-score">
                情绪阶段 · {{ reviewCompleteness }}
              </div>
            </div>
          </div>
          <div class="sentiment-suggestion">{{ sentiment.suggestion }}</div>
        </div>

        <div v-if="marketCoreSummary" class="core-banner">
          <span class="core-label">市场总龙头</span>
          <button class="core-stock" type="button" @click="openStockDetail(marketCoreSummary.code)">
            {{ marketCoreSummary.name }}
          </button>
          <span class="core-meta">{{ marketCoreSummary.theme }}</span>
          <span class="core-meta">{{ marketCoreSummary.tradeability }}</span>
        </div>

        <div class="stats-grid">
          <div v-for="stat in leaderStats" :key="stat.label" class="stat-item">
            <span class="stat-label">{{ stat.label }}</span>
            <span class="stat-value" :style="{ color: stat.color }">{{ stat.value }}</span>
          </div>
        </div>
      </div>

      <div v-if="error" class="inline-alert">{{ error }}</div>

      <div class="changes-section" v-if="recentChanges.length">
        <div class="section-header">
          <span class="section-title">
            <span class="title-icon">🔔</span>
            最近变化
          </span>
          <span class="changes-count">{{ recentChanges.length }}</span>
        </div>

        <div class="changes-list">
          <button
            v-for="change in recentChanges"
            :key="`${change.code}-${change.timestamp}-${change.type}`"
            class="change-item"
            :class="change.className"
            type="button"
            @click="openStockDetail(change.code)"
          >
            <div class="change-left">
              <span class="change-icon">{{ change.icon }}</span>
              <div class="change-info">
                <span class="change-name">{{ change.name }}</span>
                <span class="change-detail">{{ change.detail }}</span>
              </div>
            </div>
            <span class="change-time">{{ formatTime(change.timestamp) }}</span>
          </button>
        </div>
      </div>

      <div class="tab-bar">
        <button
          v-for="tab in tabs"
          :key="tab.value"
          class="tab-btn"
          :class="{ active: view === tab.value }"
          type="button"
          @click="view = tab.value"
        >
          <span class="tab-icon">{{ tab.icon }}</span>
          <span class="tab-label">{{ tab.label }}</span>
          <span class="tab-count" v-if="tab.count">{{ tab.count }}</span>
        </button>
      </div>

      <div class="panel-content">
        <div v-if="loading && !leaders.length" class="loading-state">
          <span class="loading-icon">🧭</span>
          <span class="loading-text">正在重建龙头复盘...</span>
        </div>

        <div v-else-if="!leaders.length" class="empty-state">
          <span class="empty-icon">📭</span>
          <span class="empty-text">当前没有可展示的龙头复盘结果</span>
          <button class="retry-btn" type="button" @click="refresh">重新加载</button>
        </div>

        <template v-else-if="view === 'list'">
          <div class="filter-bar">
            <select v-model="filterLevel" class="filter-select">
              <option value="all">全部角色 ({{ leaders.length }})</option>
              <option v-for="level in levelOptions" :key="level.value" :value="level.value">
                {{ level.label }} ({{ level.count }})
              </option>
            </select>

            <select v-model="sortBy" class="filter-select">
              <option value="score">复盘口径分</option>
              <option value="change">涨幅</option>
              <option value="turnover">成交额</option>
              <option value="zlje">主力净额</option>
              <option value="continuousDays">连板</option>
              <option value="hotness">热度</option>
            </select>

            <button class="btn-sort" type="button" @click="toggleSortOrder">
              <span class="sort-icon">{{ sortOrder === 'desc' ? '↓' : '↑' }}</span>
            </button>
          </div>

          <div class="leaders-list">
            <div v-for="leader in filteredLeaders" :key="leader.code" class="leader-card" :class="{ selected: selectedCode === leader.code }" @click="selectLeader(leader.code)">
              <div class="card-header" :style="{ borderLeftColor: leader.levelColor }">
                <div class="header-left">
                  <span class="stock-code">{{ leader.code }}</span>
                  <button class="stock-name-btn" type="button" @click.stop="openStockDetail(leader.code)">
                    {{ leader.name }}
                  </button>
                </div>
                <div class="header-right">
                  <span class="leader-badge" :style="{ background: `${leader.levelColor}20`, color: leader.levelColor }">
                    {{ leader.levelName }}
                  </span>
                  <span class="source-badge" :class="leader.source">{{ leader.sourceLabel }}</span>
                  <span class="authority-badge">{{ leader.authority }}</span>
                  <span class="leader-score">{{ leader.score }}</span>
                </div>
              </div>

              <div class="card-metrics">
                <div class="metric-item">
                  <span class="metric-label">涨幅</span>
                  <span class="metric-value" :class="getChangeClass(leader.change)">
                    {{ formatChange(leader.change) }}
                  </span>
                </div>
                <div class="metric-item">
                  <span class="metric-label">热度</span>
                  <span class="metric-value highlight">{{ formatInteger(leader.hotness) }}</span>
                </div>
                <div class="metric-item">
                  <span class="metric-label">成交额</span>
                  <span class="metric-value">{{ formatVolume(leader.turnover) }}</span>
                </div>
                <div class="metric-item">
                  <span class="metric-label">主力</span>
                  <span class="metric-value" :class="getMoneyClass(leader.zlje)">
                    {{ formatVolume(leader.zlje) }}
                  </span>
                </div>
                <div class="metric-item">
                  <span class="metric-label">连板</span>
                  <span class="metric-value highlight">{{ leader.continuousDays }}</span>
                </div>
                <div class="metric-item">
                  <span class="metric-label">操作</span>
                  <span class="metric-value">{{ leader.tradeability }}</span>
                </div>
              </div>

              <div class="card-themes" v-if="leader.themes.length || leader.themeName">
                <span v-for="theme in leader.themes.slice(0, 2)" :key="theme.key" class="theme-tag">
                  {{ theme.label }}
                </span>
                <span v-if="!leader.themes.length && leader.themeName" class="theme-tag">
                  {{ leader.themeName }}
                </span>
                <span v-if="leader.themes.length > 2" class="theme-more">+{{ leader.themes.length - 2 }}</span>
              </div>

              <div class="card-reasons" v-if="leader.reasons.length">
                <span v-for="reason in leader.reasons.slice(0, 3)" :key="reason" class="reason-tag">
                  {{ reason }}
                </span>
              </div>

              <div class="research-explain">
                <span>{{ themeResearch.leaderConfirmationText }}</span>
                <span>{{ themeResearch.riskText }}</span>
              </div>
            </div>
          </div>
        </template>

        <template v-else>
          <div class="level-tabs">
            <button
              v-for="level in levelTypes"
              :key="level.value"
              class="level-tab"
              :class="{ active: selectedLevel === level.value }"
              :style="{ color: level.color }"
              type="button"
              @click="selectedLevel = level.value"
            >
              <span class="level-icon">{{ level.icon }}</span>
              <span class="level-name">{{ level.label }}</span>
              <span class="tab-count">{{ level.count }}</span>
            </button>
          </div>

          <div class="leaders-list">
            <div v-if="!leadersByLevel.length" class="empty-state">
              <span class="empty-icon">👑</span>
              <span class="empty-text">当前角色下没有确认真龙</span>
            </div>

            <div v-for="leader in leadersByLevel" :key="leader.code" class="leader-card mini" @click="selectLeader(leader.code)">
              <div class="mini-main">
                <button class="stock-name-btn" type="button" @click.stop="openStockDetail(leader.code)">
                  {{ leader.name }}
                </button>
                <span class="mini-code">{{ leader.code }}</span>
                <span class="source-badge" :class="leader.source">{{ leader.sourceLabel }}</span>
                <span class="mini-authority">{{ leader.authority }}</span>
              </div>
              <div class="mini-side">
                <span class="mini-score">{{ leader.score }}</span>
                <span class="card-change" :class="getChangeClass(leader.change)">
                  {{ formatChange(leader.change) }}
                </span>
              </div>
            </div>
          </div>
        </template>
      </div>

      <div class="panel-footer">
        <div class="footer-left">
          <span class="total-count">共 {{ leaders.length }} 条复盘记录</span>
          <span>确认真龙 {{ trueLeaderRecords.length }} 只</span>
          <span class="update-time">更新 {{ lastUpdateLabel }}</span>
        </div>
        <div class="footer-right">
          <span v-if="reviewData?.summaryLines?.length">{{ reviewData.summaryLines[0] }}</span>
          <span v-else>高标不等于龙头，热度不等于领导权。</span>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { AppEvents } from '@/types'
import { EMOTION_PHASE_BY_NAME, EMOTION_PHASE_LIST } from '@/types/emotion'
import { dataLayer } from '@/services/DataLayer'
import { dragonReviewService } from '@/services/dragon/DragonReviewService'
import {
  authorityLabel,
  roleLabel,
  tradeabilityLabel,
} from '@/services/dragon/labels'
import type {
  AuthorityClass,
  DragonReviewResult,
  LeaderRecord,
  LeaderRole,
  LeaderTransition,
} from '@/services/dragon/types'
import { EventManager } from '@/utils/eventManager'
import {
  buildThemeResearchExplanation,
  loadThemeResearchExplanation,
  type ThemeResearchExplanation,
} from '@/services/theme/themeResearchSummary'

type ViewMode = 'list' | 'byLevel'
type SortKey = 'score' | 'change' | 'turnover' | 'zlje' | 'continuousDays' | 'hotness'

interface PanelLeader {
  code: string
  name: string
  score: number
  level: LeaderRole
  roles: LeaderRole[]
  levelName: string
  levelColor: string
  authority: string
  tradeability: string
  themeName: string
  change: number
  turnover: number
  zlje: number
  continuousDays: number
  hotness: number
  themes: Array<{ key: string; label: string }>
  reasons: string[]
  source: 'true' | 'height' | 'attention'
  sourceLabel: string
}

const themeResearch = ref<ThemeResearchExplanation>(buildThemeResearchExplanation({ available: false, reason: 'not_loaded' }))

const ROLE_META: Record<LeaderRole, { label: string; icon: string; color: string }> = {
  MARKET_CORE: { label: '市场总龙头', icon: '👑', color: '#f6c453' },
  THEME_CORE: { label: '题材真龙', icon: '🎯', color: '#4da3ff' },
  SPACE_CORE: { label: '空间龙头', icon: '📈', color: '#ff6b6b' },
  TREND_CORE: { label: '趋势中军', icon: '⚔️', color: '#69db7c' },
  EMOTION_CORE: { label: '情绪核心', icon: '🔥', color: '#ffa94d' },
}

const AUTHORITY_SCORE_MAP: Record<AuthorityClass, number> = {
  TRUE_LEADER: 95,
  THEME_COMMANDER: 82,
  CARRY_PROXY: 68,
  HEIGHT_ONLY: 56,
  HEAT_ONLY: 52,
  PSEUDO_LEADER: 35,
}

const props = defineProps<{
  visible: boolean
  triggerRect?: DOMRect
}>()

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'close'): void
}>()

const panelRef = ref<HTMLElement | null>(null)
const reviewData = ref<DragonReviewResult | null>(dragonReviewService.getLatestReview?.() || dataLayer.getDragonReview())
const loading = ref(false)
const error = ref('')
const view = ref<ViewMode>('list')
const filterLevel = ref<'all' | LeaderRole>('all')
const selectedLevel = ref<LeaderRole>('MARKET_CORE')
const sortBy = ref<SortKey>('score')
const sortOrder = ref<'desc' | 'asc'>('desc')
const selectedCode = ref<string | null>(null)
const lastUpdate = ref<number | null>(null)

let outsideListenerTimer: ReturnType<typeof setTimeout> | null = null
let globalListenersBound = false
const unsubscribeFns: Array<() => void> = []

const sentiment = computed(() => {
  const breath = (dataLayer as any).state?.analysis?.breath
  return {
    phase: breath?.sentiment?.phase || 'start',
    phaseName: breath?.sentiment?.phaseName || breath?.sentiment?.phase || '启动',
    overall: Number(breath?.sentiment?.overall || 50),
    suggestion: breath?.sentiment?.suggestion || '等待真龙确认，不追无效热度',
  }
})

const currentPhase = computed(() => {
  return (
    EMOTION_PHASE_BY_NAME[sentiment.value.phaseName] ||
    EMOTION_PHASE_BY_NAME[sentiment.value.phase] ||
    EMOTION_PHASE_LIST.find((item) => item.name === '启动') ||
    {
      icon: '🌬️',
      gradient: 'linear-gradient(135deg, #2c3e50, #34495e)',
    }
  )
})

const phaseGradient = computed(() => currentPhase.value?.gradient || 'linear-gradient(135deg, #2c3e50, #34495e)')
const phaseIcon = computed(() => currentPhase.value?.icon || '🌬️')
const reviewCompleteness = computed(() => (reviewData.value?.reviewCompleteness === 'complete' ? '完整复盘' : '部分复盘'))
const lastUpdateLabel = computed(() => formatTime(lastUpdate.value || Date.now()))

const SOURCE_PRIORITY: Record<PanelLeader['source'], number> = {
  true: 1,
  height: 2,
  attention: 3,
}

const SOURCE_LABELS: Record<PanelLeader['source'], string> = {
  true: '真龙榜',
  height: '高标榜',
  attention: '热度榜',
}

const panelStyle = computed(() => {
  const margin = 16
  const width = Math.min(540, Math.max(360, window.innerWidth - margin * 2))
  const estimatedHeight = 720
  const rect = props.triggerRect

  let top = 88
  let left = window.innerWidth - width - margin

  if (rect) {
    top = rect.bottom + 8
    left = Math.min(window.innerWidth - width - margin, Math.max(margin, rect.right - width))

    if (top + estimatedHeight > window.innerHeight - margin) {
      top = Math.max(margin, rect.top - estimatedHeight - 8)
    }
  }

  return {
    top: `${top}px`,
    left: `${left}px`,
    width: `${width}px`,
  }
})

const trueLeaderRecords = computed<LeaderRecord[]>(() => {
  const result = reviewData.value || dragonReviewService.getLatestReview?.() || dataLayer.getDragonReview()
  if (!result) return []

  const deduped = new Map<string, LeaderRecord>()
  const addRecord = (record?: LeaderRecord | null) => {
    if (!record || deduped.has(record.code)) return
    deduped.set(record.code, record)
  }

  ;(result.trueLeaders || []).forEach(addRecord)
  if (result.marketCore && !deduped.has(result.marketCore.code)) {
    addRecord(result.marketCore)
  }

  return Array.from(deduped.values())
})

const leaderRecords = computed<Array<{ record: LeaderRecord; source: PanelLeader['source'] }>>(() => {
  const result = reviewData.value || dragonReviewService.getLatestReview?.() || dataLayer.getDragonReview()
  if (!result) return []

  const deduped = new Map<string, { record: LeaderRecord; source: PanelLeader['source'] }>()
  const addRecord = (record: LeaderRecord | null | undefined, source: PanelLeader['source']) => {
    if (!record) return
    const existing = deduped.get(record.code)
    if (!existing || SOURCE_PRIORITY[source] < SOURCE_PRIORITY[existing.source]) {
      deduped.set(record.code, { record, source })
    }
  }

  ;(result.trueLeaders || []).forEach((record) => addRecord(record, 'true'))
  ;(result.heightBoard || []).forEach((record) => addRecord(record, 'height'))
  ;(result.attentionBoard || []).forEach((record) => addRecord(record, 'attention'))
  if (result.marketCore) addRecord(result.marketCore, 'true')

  return Array.from(deduped.values())
})

const leaders = computed<PanelLeader[]>(() => {
  return leaderRecords.value
    .map(({ record, source }) => {
      const stock = dataLayer.getStock(record.code)
      const levelMeta = ROLE_META[record.primaryRole]
      const themeEntries = (stock?.themes || record.themes || []).map((theme: any, index: number) => ({
        key: `${record.code}-theme-${index}-${typeof theme === 'string' ? theme : theme?.name || 'unknown'}`,
        label: typeof theme === 'string' ? theme : theme?.name || '未知题材',
      }))

      return {
        code: record.code,
        name: record.name || stock?.name || record.code,
        score: AUTHORITY_SCORE_MAP[record.authority] || 50,
        level: record.primaryRole,
        roles: [...record.roles],
        levelName: levelMeta?.label || roleLabel(record.primaryRole),
        levelColor: levelMeta?.color || '#7f8c8d',
        authority: authorityLabel(record.authority),
        tradeability: tradeabilityLabel(record.tradeability),
        themeName: record.themeName || stock?.mainTheme || '',
        change: Number(stock?.change ?? record.change ?? 0),
        turnover: Number(stock?.turnover ?? record.turnover ?? 0),
        zlje: Number(stock?.zlje ?? record.zlje ?? 0),
        continuousDays: Number(stock?.continuousDays ?? record.continuousDays ?? 0),
        hotness: Number(stock?.hotness ?? record.hotness ?? 0),
        themes: themeEntries,
        reasons: collectReasons(record),
        source,
        sourceLabel: SOURCE_LABELS[source],
      }
    })
    .sort((a, b) => b.score - a.score)
})

const marketCoreSummary = computed(() => {
  const record = reviewData.value?.marketCore
  if (!record) return null

  return {
    code: record.code,
    name: record.name,
    theme: record.themeName || ROLE_META[record.primaryRole]?.label || roleLabel(record.primaryRole),
    tradeability: tradeabilityLabel(record.tradeability),
  }
})

const statsByLevel = computed(() => {
  const base: Record<LeaderRole, number> = {
    MARKET_CORE: 0,
    THEME_CORE: 0,
    SPACE_CORE: 0,
    TREND_CORE: 0,
    EMOTION_CORE: 0,
  }

  trueLeaderRecords.value.forEach((record) => {
    record.roles.forEach((role) => {
      base[role] += 1
    })
  })

  return base
})

const leaderStats = computed(() =>
  (Object.keys(ROLE_META) as LeaderRole[]).map((role) => ({
    label: ROLE_META[role].label,
    value: statsByLevel.value[role],
    color: ROLE_META[role].color,
  })),
)

const recentChanges = computed(() => {
  return (reviewData.value?.transitions || []).slice(0, 8).map((transition) => ({
    code: transition.code,
    name: transition.name || transition.code,
    type: transition.type,
    icon: getChangeIcon(transition.type),
    className: `type-${transition.type}`,
    detail: `${getTransitionLabel(transition)} · ${transition.reason}`,
    timestamp: transition.timestamp,
  }))
})

const filteredLeaders = computed(() => {
  let result = leaders.value
  if (filterLevel.value !== 'all') {
    result = result.filter((leader) => leader.roles.includes(filterLevel.value as LeaderRole))
  }

  return [...result].sort((a, b) => {
    const aValue = Number(a[sortBy.value] || 0)
    const bValue = Number(b[sortBy.value] || 0)
    return sortOrder.value === 'desc' ? bValue - aValue : aValue - bValue
  })
})

const leadersByLevel = computed(() => {
  return leaders.value
    .filter((leader) => leader.source === 'true' && leader.roles.includes(selectedLevel.value))
    .sort((a, b) => b.score - a.score)
})

const tabs = computed(() => [
  { value: 'list' as ViewMode, icon: '📋', label: '列表', count: leaders.value.length },
  { value: 'byLevel' as ViewMode, icon: '👑', label: '分角色', count: trueLeaderRecords.value.length },
])

const levelOptions = computed(() =>
  (Object.keys(ROLE_META) as LeaderRole[]).map((role) => ({
    value: role,
    label: ROLE_META[role].label,
    count: statsByLevel.value[role],
  })),
)

const levelTypes = computed(() =>
  (Object.keys(ROLE_META) as LeaderRole[]).map((role) => ({
    value: role,
    label: ROLE_META[role].label,
    icon: ROLE_META[role].icon,
    color: ROLE_META[role].color,
    count: statsByLevel.value[role],
  })),
)

function close() {
  emit('update:visible', false)
  emit('close')
}

async function loadReview(force = false) {
  if (loading.value) return
  loading.value = true
  error.value = ''

  try {
    let result = dragonReviewService.getLatestReview?.() || dataLayer.getDragonReview()
    if (!result || force) {
      await dragonReviewService.runFullUpdate?.()
      result = dragonReviewService.getLatestReview?.() || dataLayer.getDragonReview()
    }

    reviewData.value = result || null
    lastUpdate.value = Date.now()

    if (!reviewData.value) {
      error.value = '当前没有可用的龙头复盘结果'
    }
  } catch (err) {
    error.value = err instanceof Error ? err.message : '龙头复盘加载失败'
  } finally {
    loading.value = false
  }
}

function refresh() {
  void loadReview(true)
}

function toggleSortOrder() {
  sortOrder.value = sortOrder.value === 'desc' ? 'asc' : 'desc'
}

function syncSelectedStock(code: string) {
  EventManager.emit(AppEvents.STOCK.SELECTED, {
    code,
    timestamp: Date.now(),
    source: 'dragon-head-panel',
  })
}

function selectLeader(code: string) {
  selectedCode.value = selectedCode.value === code ? null : code
  if (selectedCode.value) {
    syncSelectedStock(code)
  }
}

function openStockDetail(code: string) {
  const stock = dataLayer.getStock(code)
  syncSelectedStock(code)
  EventManager.emit('stock:show-detail', {
    code,
    name: stock?.name || code,
    source: 'dragon-head-panel',
  })
  close()
}

function exportData() {
  const payload = {
    exportTime: new Date().toISOString(),
    review: reviewData.value,
    leaders: leaders.value,
    sentiment: sentiment.value,
  }
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `龙头复盘_${new Date().toISOString().slice(0, 10)}.json`
  anchor.click()
  URL.revokeObjectURL(url)
}

function collectReasons(record: LeaderRecord): string[] {
  const support = record.evidence
    .filter((item) => item.verdict === 'support')
    .map((item) => item.note || item.label)
  const playbook = (record.playbook || []).filter(Boolean)
  const reasons = [...support, ...playbook]
  return [...new Set(reasons)].slice(0, 4)
}

function getTransitionLabel(transition: LeaderTransition): string {
  switch (transition.type) {
    case 'candidate':
      return '进入候选'
    case 'confirm':
      return '真龙确认'
    case 'command':
      return '取得主导'
    case 'weaken':
      return '领导权走弱'
    case 'replace':
      return '主角切换'
    case 'depose':
      return '退出主位'
    default:
      return transition.type
  }
}

function getChangeIcon(type: LeaderTransition['type']): string {
  switch (type) {
    case 'candidate':
      return '➕'
    case 'confirm':
      return '✅'
    case 'command':
      return '👑'
    case 'weaken':
      return '⚠️'
    case 'replace':
      return '🔁'
    case 'depose':
      return '➖'
    default:
      return '🔔'
  }
}

function getChangeClass(change: number): string {
  if (change > 0) return 'up'
  if (change < 0) return 'down'
  return ''
}

function getMoneyClass(value: number): string {
  if (value > 0) return 'up'
  if (value < 0) return 'down'
  return ''
}

function formatChange(change: number): string {
  if (!Number.isFinite(change)) return '-'
  return `${change > 0 ? '+' : ''}${change.toFixed(2)}%`
}

function formatVolume(value: number): string {
  if (!Number.isFinite(value)) return '-'
  const abs = Math.abs(value)
  if (abs >= 1e8) return `${(value / 1e8).toFixed(2)}亿`
  if (abs >= 1e4) return `${(value / 1e4).toFixed(2)}万`
  return value.toFixed(0)
}

function formatInteger(value: number): string {
  if (!Number.isFinite(value)) return '0'
  return String(Math.round(value))
}

function formatTime(timestamp: number): string {
  if (!timestamp) return '--'
  const date = new Date(timestamp)
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}

function handleDocumentClick(event: MouseEvent) {
  const target = event.target as Node | null
  if (!props.visible || !target) return
  if (panelRef.value?.contains(target)) return
  close()
}

function handleDocumentKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && props.visible) {
    close()
  }
}

function bindGlobalListeners() {
  if (globalListenersBound) return
  document.addEventListener('mousedown', handleDocumentClick)
  document.addEventListener('keydown', handleDocumentKeydown)
  globalListenersBound = true
}

function unbindGlobalListeners() {
  if (!globalListenersBound) return
  document.removeEventListener('mousedown', handleDocumentClick)
  document.removeEventListener('keydown', handleDocumentKeydown)
  globalListenersBound = false
}

async function refreshThemeResearch() {
  themeResearch.value = await loadThemeResearchExplanation()
}

watch(
  () => props.visible,
  (visible) => {
    if (outsideListenerTimer) {
      clearTimeout(outsideListenerTimer)
      outsideListenerTimer = null
    }

    if (visible) {
      outsideListenerTimer = setTimeout(() => {
        bindGlobalListeners()
        outsideListenerTimer = null
      }, 0)
      void loadReview(false)
      void refreshThemeResearch()
    } else {
      unbindGlobalListeners()
    }
  },
  { immediate: true },
)

onMounted(() => {
  unsubscribeFns.push(
    EventManager.on(AppEvents.DRAGON.UPDATED, (payload: any) => {
      reviewData.value = payload?.result || dragonReviewService.getLatestReview?.() || dataLayer.getDragonReview()
      lastUpdate.value = payload?.timestamp || Date.now()
    }),
  )

  unsubscribeFns.push(
    dataLayer.subscribe('review.result', (result: DragonReviewResult) => {
      reviewData.value = result
      lastUpdate.value = Date.now()
    }),
  )

  unsubscribeFns.push(
    dataLayer.subscribe('merged.stocks', () => {
      lastUpdate.value = Date.now()
    }),
  )

  if (props.visible) {
    void loadReview(false)
    void refreshThemeResearch()
  }
})

onUnmounted(() => {
  if (outsideListenerTimer) {
    clearTimeout(outsideListenerTimer)
    outsideListenerTimer = null
  }
  unbindGlobalListeners()
  unsubscribeFns.forEach((unsubscribe) => unsubscribe())
})
</script>

<style scoped>
.dragon-panel {
  position: fixed;
  max-width: calc(100vw - 32px);
  max-height: calc(100vh - 32px);
  overflow: hidden;
  background: var(--bg-primary);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 24px;
  box-shadow: 0 20px 40px rgba(0, 0, 0, 0.4);
  z-index: 10005;
  font-size: 13px;
  backdrop-filter: blur(20px);
  animation: slide-in 0.18s ease;
}

@keyframes slide-in {
  from {
    opacity: 0;
    transform: translateY(-8px);
  }

  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.panel-header {
  padding: 20px 20px 16px;
  color: #fff;
}

.header-top {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
}

.header-left {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}

.panel-icon {
  font-size: 24px;
  line-height: 1;
}

.header-title h2 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
}

.header-subtitle {
  margin-top: 4px;
  font-size: 12px;
  opacity: 0.86;
}

.header-actions {
  display: flex;
  gap: 6px;
}

.btn-icon {
  width: 32px;
  height: 32px;
  border: none;
  background: rgba(255, 255, 255, 0.14);
  border-radius: 10px;
  color: #fff;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
}

.btn-icon:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.26);
  transform: scale(1.04);
}

.btn-icon:disabled {
  opacity: 0.55;
  cursor: default;
}

.btn-icon.close:hover {
  background: rgba(255, 71, 87, 0.32);
}

.sentiment-card {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 14px;
  margin-top: 16px;
  padding: 16px;
  background: rgba(0, 0, 0, 0.26);
  border-radius: 16px;
}

.sentiment-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.phase-icon {
  font-size: 30px;
}

.sentiment-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.sentiment-phase {
  font-size: 16px;
  font-weight: 600;
}

.sentiment-score {
  font-size: 12px;
  opacity: 0.92;
}

.sentiment-suggestion {
  max-width: 200px;
  padding: 7px 12px;
  background: rgba(255, 255, 255, 0.18);
  border-radius: 20px;
  font-size: 12px;
  text-align: center;
}

.core-banner {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 12px;
  padding: 10px 12px;
  background: rgba(0, 0, 0, 0.22);
  border-radius: 14px;
}

.core-label {
  font-size: 11px;
  opacity: 0.72;
}

.core-stock {
  border: none;
  background: none;
  color: #fff8d6;
  font-weight: 600;
  cursor: pointer;
}

.core-stock:hover {
  text-decoration: underline;
}

.core-meta {
  font-size: 12px;
  opacity: 0.88;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 8px;
  margin-top: 16px;
}

.stat-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 8px 4px;
  background: rgba(0, 0, 0, 0.2);
  border-radius: 12px;
}

.stat-label {
  font-size: 10px;
  opacity: 0.76;
  margin-bottom: 4px;
}

.stat-value {
  font-size: 16px;
  font-weight: 600;
}

.inline-alert {
  padding: 10px 20px;
  background: rgba(255, 87, 87, 0.12);
  color: #ffb5b5;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.changes-section {
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-color);
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.section-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  color: var(--text-title);
}

.changes-count {
  padding: 2px 10px;
  background: var(--color-highlight);
  color: #000;
  border-radius: 20px;
  font-size: 11px;
  font-weight: 600;
}

.changes-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.change-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
  padding: 10px 12px;
  background: var(--bg-secondary);
  border: none;
  border-radius: 12px;
  color: var(--text-primary);
  cursor: pointer;
  transition: all 0.2s;
  text-align: left;
}

.change-item:hover {
  background: var(--bg-hover);
  transform: translateX(4px);
}

.change-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.change-icon {
  font-size: 16px;
}

.change-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.change-name {
  font-weight: 500;
}

.change-detail {
  font-size: 11px;
  color: var(--text-secondary);
}

.change-time {
  font-size: 11px;
  color: var(--text-secondary);
}

.type-confirm .change-icon,
.type-command .change-icon {
  color: #ffd700;
}

.type-candidate .change-icon {
  color: #2ed573;
}

.type-weaken .change-icon {
  color: #ffa502;
}

.type-replace .change-icon,
.type-depose .change-icon {
  color: #ff6b6b;
}

.tab-bar {
  display: flex;
  gap: 4px;
  padding: 12px 20px;
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border-color);
}

.tab-btn {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 12px;
  border: none;
  background: transparent;
  border-radius: 12px;
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

.tab-count {
  padding: 2px 6px;
  background: rgba(0, 0, 0, 0.1);
  border-radius: 12px;
  font-size: 11px;
}

.panel-content {
  max-height: min(58vh, 540px);
  overflow-y: auto;
  padding: 0 20px;
}

.loading-state,
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  margin: 20px 0;
  padding: 28px 20px;
  background: var(--bg-secondary);
  border-radius: 16px;
  color: var(--text-secondary);
}

.loading-icon,
.empty-icon {
  font-size: 24px;
}

.retry-btn {
  padding: 8px 14px;
  border: 1px solid var(--border-color);
  background: var(--bg-header);
  border-radius: 12px;
  color: var(--text-primary);
  cursor: pointer;
}

.filter-bar,
.level-tabs {
  display: flex;
  gap: 8px;
  padding: 16px 0;
  position: sticky;
  top: 0;
  background: var(--bg-primary);
  z-index: 1;
}

.filter-select {
  flex: 1;
  padding: 8px 12px;
  background: var(--bg-header);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  color: var(--text-primary);
  font-size: 12px;
  outline: none;
  cursor: pointer;
}

.btn-sort {
  width: 36px;
  height: 36px;
  border: 1px solid var(--border-color);
  background: var(--bg-header);
  border-radius: 12px;
  color: var(--text-primary);
  cursor: pointer;
}

.leaders-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding-bottom: 16px;
}

.leader-card {
  padding: 16px;
  background: var(--bg-header);
  border-radius: 20px;
  cursor: pointer;
  transition: all 0.2s;
  border: 1px solid transparent;
}

.leader-card:hover {
  transform: translateY(-2px);
  border-color: var(--color-highlight);
  box-shadow: 0 8px 20px rgba(0, 0, 0, 0.18);
}

.leader-card.selected {
  border-color: var(--color-highlight);
  background: rgba(255, 165, 2, 0.05);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
  padding-left: 6px;
  border-left: 3px solid transparent;
}

.stock-code,
.mini-code {
  font-family: Consolas, monospace;
  font-weight: 600;
  color: var(--color-highlight);
  background: rgba(255, 165, 2, 0.12);
  padding: 4px 8px;
  border-radius: 8px;
}

.stock-name-btn {
  border: none;
  background: none;
  color: var(--text-primary);
  cursor: pointer;
  font-weight: 500;
  padding: 0;
}

.stock-name-btn:hover {
  color: var(--color-highlight);
}

.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.leader-badge,
.source-badge,
.authority-badge,
.mini-authority {
  padding: 4px 10px;
  border-radius: 18px;
  font-size: 11px;
  background: var(--bg-secondary);
}

.source-badge {
  border: 1px solid transparent;
}

.source-badge.true {
  color: #f6c453;
  border-color: rgba(246, 196, 83, 0.28);
  background: rgba(246, 196, 83, 0.12);
}

.source-badge.height {
  color: #ff8a5b;
  border-color: rgba(255, 138, 91, 0.28);
  background: rgba(255, 138, 91, 0.1);
}

.source-badge.attention {
  color: #ffa94d;
  border-color: rgba(255, 169, 77, 0.28);
  background: rgba(255, 169, 77, 0.1);
}

.authority-badge,
.mini-authority {
  color: var(--text-secondary);
}

.leader-score,
.mini-score {
  padding: 4px 8px;
  background: var(--bg-primary);
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
}

.card-metrics {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin-bottom: 12px;
}

.metric-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: 6px;
  background: var(--bg-primary);
  border-radius: 10px;
}

.metric-label {
  font-size: 10px;
  color: var(--text-secondary);
}

.metric-value {
  font-size: 12px;
  font-weight: 500;
}

.metric-value.up,
.card-change.up {
  color: #ff6b6b;
}

.metric-value.down,
.card-change.down {
  color: #69db7c;
}

.metric-value.highlight {
  color: var(--color-highlight);
}

.card-themes,
.card-reasons,
.research-explain {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.card-themes {
  margin-bottom: 8px;
}

.theme-tag,
.reason-tag,
.theme-more {
  padding: 4px 10px;
  border-radius: 16px;
  font-size: 11px;
}

.theme-tag {
  background: rgba(52, 152, 219, 0.1);
  border: 1px solid rgba(52, 152, 219, 0.22);
  color: #4da3ff;
}

.theme-more {
  background: var(--bg-primary);
  color: var(--text-secondary);
}

.reason-tag {
  background: rgba(46, 213, 115, 0.1);
  border: 1px solid rgba(46, 213, 115, 0.22);
  color: #69db7c;
}

.research-explain {
  margin-top: 8px;
  padding: 8px 10px;
  border-radius: 10px;
  background: rgba(77, 163, 255, 0.08);
  border: 1px solid rgba(77, 163, 255, 0.18);
  color: var(--text-secondary);
  font-size: 11px;
}

.level-tab {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 4px;
  border: none;
  background: var(--bg-header);
  border-radius: 12px;
  cursor: pointer;
  font-size: 12px;
}

.level-tab.active {
  background: var(--bg-secondary);
  box-shadow: inset 0 -2px currentColor;
}

.leader-card.mini {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}

.mini-main,
.mini-side {
  display: flex;
  align-items: center;
  gap: 10px;
}

.panel-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  padding: 16px 20px;
  border-top: 1px solid var(--border-color);
  background: var(--bg-header);
}

.footer-left,
.footer-right {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 11px;
  color: var(--text-secondary);
}

.footer-right {
  justify-content: flex-end;
}

.total-count {
  color: var(--color-highlight);
  font-weight: 500;
}

.panel-content::-webkit-scrollbar {
  width: 5px;
}

.panel-content::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.16);
  border-radius: 999px;
}

@media (max-width: 768px) {
  .dragon-panel {
    left: 16px !important;
    right: 16px;
    width: auto !important;
    max-height: calc(100vh - 24px);
  }

  .sentiment-card,
  .core-banner,
  .panel-footer {
    flex-direction: column;
    align-items: flex-start;
  }

  .stats-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .card-metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .level-tabs {
    overflow-x: auto;
  }

  .level-tab {
    min-width: 120px;
  }
}
</style>
