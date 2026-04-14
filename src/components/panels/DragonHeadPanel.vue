<!-- src/components/panels/DragonHeadPanel.vue -->
<!-- 优化版：使用组合式函数，统一情绪阶段定义 -->

<template>
  <Teleport to="body">
    <div v-if="visible" class="dragon-panel" :style="panelStyle" ref="panelRef">
      <!-- 加载状态 -->
      <div v-if="loading" class="loading-overlay">
        <div class="loading-spinner"></div>
        <span>加载龙头数据...</span>
      </div>

      <!-- 错误状态 -->
      <div v-else-if="error" class="error-overlay">
        <span class="error-icon">⚠️</span>
        <span>{{ error }}</span>
        <button class="retry-btn" @click="loadData">重试</button>
      </div>

      <template v-else>
        <!-- 头部渐变区域 -->
        <div class="panel-header" :style="{ background: phaseGradient }">
          <div class="header-top">
            <div class="header-left">
              <span class="panel-icon">🐲</span>
              <h2>龙头监测</h2>
            </div>
            <div class="header-actions">
              <button class="btn-icon" @click.stop="openThresholdMultiplierPanel" title="阈值乘数配置"
                :class="{ active: showThresholdPanel }">
                <span class="icon">⚡</span>
              </button>
              <button class="btn-icon" @click="refresh" :class="{ rotating: loading }" title="刷新">
                <span class="icon">↻</span>
              </button>
              <button class="btn-icon close" @click="close" title="关闭">
                <span class="icon">✕</span>
              </button>
            </div>
          </div>

          <!-- 情绪卡片 -->
          <div class="sentiment-card">
            <div class="sentiment-left">
              <span class="phase-icon">{{ phaseIcon }}</span>
              <div class="sentiment-info">
                <div class="sentiment-phase">{{ sentiment.phase }}</div>
                <div class="sentiment-score">情绪指数 {{ sentiment.overall.toFixed(1) }}</div>
              </div>
            </div>
            <div class="sentiment-suggestion">{{ sentiment.suggestion }}</div>
          </div>

          <!-- 统计卡片 -->
          <div class="stats-grid">
            <div v-for="stat in leaderStats" :key="stat.label" class="stat-item">
              <span class="stat-label">{{ stat.label }}</span>
              <span class="stat-value" :style="{ color: stat.color }">{{ stat.value }}</span>
            </div>
          </div>
        </div>

        <!-- 变化区域 -->
        <div class="changes-section" v-if="showChanges">
          <div class="section-header">
            <span class="section-title">
              <span class="title-icon">🔔</span>
              最近变化
            </span>
            <span class="changes-count">{{ changes.length }}</span>
          </div>
          <div class="changes-list">
            <div v-if="changes.length === 0" class="empty-changes">
              <span class="empty-icon">🕒</span>
              <span class="empty-text">暂无变化</span>
            </div>
            <div v-for="(change, index) in changes.slice(0, 5)" :key="change.time + index" class="change-item"
              :class="`type-${change.type}`" @click="selectStock(change.code)">
              <div class="change-left">
                <span class="change-icon">{{ getChangeIcon(change.type) }}</span>
                <div class="change-info">
                  <span class="change-name">{{ change.name || '未知' }}</span>
                  <span class="change-detail" v-if="change.fromLevel && change.toLevel">
                    {{ formatLevel(change.fromLevel) }} → {{ formatLevel(change.toLevel) }}
                  </span>
                  <span class="change-level" v-else>
                    {{ change.level || formatLevel(change.toLevel) || change.type }}
                  </span>
                </div>
              </div>
              <span class="change-time">{{ formatTimeShort(change.time) }}</span>
            </div>
          </div>
        </div>

        <!-- 标签栏 -->
        <div class="tab-bar">
          <button v-for="tab in tabs" :key="tab.value" class="tab-btn" :class="{ active: view === tab.value }"
            @click="view = tab.value">
            <span class="tab-icon">{{ tab.icon }}</span>
            <span class="tab-label">{{ tab.label }}</span>
            <span class="tab-count" v-if="tab.count">{{ tab.count }}</span>
          </button>
        </div>

        <!-- 内容区域 -->
        <div class="panel-content" @click.stop>
          <!-- 列表视图 -->
          <div v-if="view === 'list'" class="list-view">
            <!-- 筛选栏 -->
            <div class="filter-bar">
              <select class="filter-select" v-model="filterLevel">
                <option value="all">全部龙头 ({{ leaders.length }})</option>
                <option v-for="level in levelOptions" :key="level.value" :value="level.value">
                  {{ level.label }}
                </option>
              </select>
              <select class="filter-select" v-model="sortBy">
                <option value="score">综合评分</option>
                <option value="change">涨幅</option>
                <option value="turnover">成交额</option>
                <option value="zlje">主力资金</option>
                <option value="continuousDays">连板天数</option>
              </select>
              <button class="btn-sort" @click="toggleSortOrder">
                <span class="sort-icon">{{ sortOrder === 'desc' ? '↓' : '↑' }}</span>
              </button>
            </div>

            <!-- 龙头列表 -->
            <div class="leaders-list">
              <div v-if="filteredLeaders.length === 0" class="empty-state">
                <span class="empty-icon">🔍</span>
                <span class="empty-text">暂无符合条件的龙头</span>
              </div>
              <div v-for="leader in filteredLeaders" :key="leader.code" class="leader-card"
                :class="{ selected: selectedCode === leader.code }" @click="selectLeader(leader.code)">
                <div class="card-header" :style="{ borderLeftColor: getLevelColor(leader.level) }">
                  <div class="header-left">
                    <span class="stock-code">{{ leader.code }}</span>
                    <span class="stock-name">{{ leader.name }}</span>
                  </div>
                  <div class="header-right">
                    <span class="leader-badge" :style="{
                      background: getLevelColor(leader.level) + '20',
                      color: getLevelColor(leader.level),
                    }">
                      {{ leader.levelName }}
                    </span>
                    <span class="leader-score">{{ Math.round(leader.score) }}</span>
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
                    <span class="metric-label">成交额</span>
                    <span class="metric-value">{{ formatVolume(leader.turnover) }}</span>
                  </div>
                  <div class="metric-item">
                    <span class="metric-label">主力</span>
                    <span class="metric-value" :class="getMoneyClass(leader.zlje)">
                      {{ formatVolume(leader.zlje) }}
                    </span>
                  </div>
                  <div class="metric-item" v-if="leader.continuousDays > 1">
                    <span class="metric-label">连板</span>
                    <span class="metric-value highlight">{{ leader.continuousDays }}</span>
                  </div>
                </div>

                <div class="card-themes" v-if="leader.themes?.length">
                  <span v-for="theme in leader.themes.slice(0, 2)"
                    :key="typeof theme === 'string' ? theme : theme?.name || theme" class="theme-tag">
                    {{ typeof theme === 'string' ? theme : theme?.name || '未知' }}
                  </span>
                  <span v-if="leader.themes.length > 2" class="theme-more">
                    +{{ leader.themes.length - 2 }}
                  </span>
                </div>

                <div class="card-reasons" v-if="leader.reasons?.length">
                  <span v-for="reason in leader.reasons.slice(0, 2)" :key="reason" class="reason-tag">
                    {{ reason }}
                  </span>
                </div>
              </div>
            </div>
          </div>

          <!-- 按级别视图 -->
          <div v-if="view === 'byLevel'" class="bylevel-view">
            <div class="level-tabs">
              <button v-for="level in levelTypes" :key="level.value" class="level-tab"
                :class="{ active: selectedLevel === level.value }" :style="{ color: level.color }"
                @click="selectedLevel = level.value">
                <span class="level-icon">{{ level.icon }}</span>
                <span class="level-name">{{ level.name }}</span>
              </button>
            </div>
            <div class="leaders-list">
              <div v-if="leadersByLevel.length === 0" class="empty-state">
                <span class="empty-icon">👑</span>
                <span class="empty-text">暂无该级别龙头</span>
              </div>
              <div v-for="leader in leadersByLevel" :key="leader.code" class="leader-card mini"
                @click="selectLeader(leader.code)">
                <div class="card-header">
                  <span class="stock-code">{{ leader.code }}</span>
                  <span class="stock-name">{{ leader.name }}</span>
                  <span class="leader-score">{{ Math.round(leader.score) }}</span>
                </div>
                <div class="card-change" :class="getChangeClass(leader.change)">
                  {{ formatChange(leader.change) }}
                </div>
              </div>
            </div>
          </div>

          <!-- 分布视图 -->
          <div v-if="view === 'distribution'" class="distribution-view">
            <div class="dist-section">
              <h4>📊 按级别分布</h4>
              <div class="dist-chart">
                <div v-for="(count, level) in distribution.byLevel" :key="level" class="dist-row">
                  <span class="dist-label" :style="{ color: getLevelColor(level) }">
                    {{ getLevelName(level) }}
                  </span>
                  <div class="dist-bar-container">
                    <div class="dist-bar-fill" :style="{
                      width: (count / (distribution.total || 1)) * 100 + '%',
                      background: getLevelColor(level),
                    }"></div>
                  </div>
                  <span class="dist-count">{{ count }}</span>
                </div>
                <div v-if="Object.keys(distribution.byLevel).length === 0" class="empty-state">
                  暂无级别数据
                </div>
              </div>
            </div>

            <div class="dist-section">
              <h4>🔥 热门题材分布</h4>
              <div class="dist-chart">
                <div v-for="[theme, count] in Object.entries(distribution.byTheme)
                  .filter(([t]) => t && t !== 'undefined' && t !== 'null' && t.trim() !== '')
                  .sort((a, b) => b[1] - a[1])
                  .slice(0, 8)" :key="theme" class="dist-row">
                  <span class="dist-label" :title="theme">{{ truncateText(theme, 12) }}</span>
                  <div class="dist-bar-container">
                    <div class="dist-bar-fill" :style="{
                      width: (count / (distribution.total || 1)) * 100 + '%',
                      background: 'linear-gradient(90deg, #ff7f50, #ff4757)',
                    }"></div>
                  </div>
                  <span class="dist-count">{{ count }}</span>
                </div>
                <div v-if="
                  Object.keys(distribution.byTheme).filter((t) => t && t !== 'undefined')
                    .length === 0
                " class="empty-state">
                  暂无题材数据
                </div>
              </div>
            </div>
          </div>

          <!-- 情绪视图 -->
          <div v-if="view === 'emotion'" class="emotion-view">
            <div class="phase-grid">
              <div v-for="phase in phaseList" :key="phase.value" class="phase-card"
                :class="{ active: sentiment.phase === phase.name }">
                <div class="phase-header">
                  <span class="phase-icon">{{ phase.icon }}</span>
                  <span class="phase-name">{{ phase.name }}</span>
                </div>
                <div class="phase-features">
                  <div v-for="feature in phase.features" :key="feature" class="feature-item">
                    <span class="feature-bullet">•</span>
                    <span class="feature-text">{{ feature }}</span>
                  </div>
                </div>
              </div>
            </div>

            <!-- 因子权重 -->
            <div class="factor-section" v-if="emotionFactors.length">
              <h4>📊 情绪因子权重</h4>
              <div class="factor-list">
                <div v-for="factor in emotionFactors" :key="factor.id" class="factor-row">
                  <span class="factor-name" :title="factor.description">{{ factor.name }}</span>
                  <div class="factor-bar-container">
                    <div class="factor-bar-fill" :style="{
                      width: factor.weight * 100 + '%',
                      background: getFactorColor(factor.id),
                    }"></div>
                  </div>
                  <span class="factor-value">{{ (factor.weight * 100).toFixed(0) }}%</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 底部 -->
        <div class="panel-footer">
          <div class="footer-left">
            <span class="total-count">共 {{ leaders.length }} 个龙头</span>
            <span class="update-time">{{ formatTime(lastUpdate) }} 更新</span>

            <!-- 调试区域 -->
            <div class="debug-actions" v-if="debugMode">
              <button class="debug-btn" @click="forceRepair" :class="{
                loading: repairing,
                success: lastRepairSuccess === true,
                error: lastRepairSuccess === false,
              }" :disabled="repairing">
                <span class="icon">🔧</span>
                {{ repairing ? '修复中...' : '强制修复一致性' }}
              </button>

              <div v-if="showDebugPanel" class="debug-panel">
                <div class="debug-panel-item">
                  <span class="debug-panel-label">上次修复</span>
                  <span class="debug-panel-value">{{ lastRepairTime || '从未' }}</span>
                </div>
                <div class="debug-panel-item">
                  <span class="debug-panel-label">修复次数</span>
                  <span class="debug-panel-value">{{ repairCount || 0 }}</span>
                </div>
                <div class="debug-panel-divider"></div>
                <div class="repair-history">
                  <div v-for="(item, index) in repairHistory.slice(0, 3)" :key="index" class="repair-history-item">
                    <span class="repair-time">{{ formatTimeShort(item.time) }}</span>
                    <span class="repair-count" :class="item.success ? 'success' : 'failed'">
                      {{ item.success ? '✓' : '✗' }}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </div>
          <div class="footer-right">
            <button class="btn-text" @click="exportData"><span class="icon">📥</span> 导出</button>
          </div>
        </div>
      </template>
    </div>

    <ThresholdMultiplierPanel v-if="showThresholdPanel" :visible="showThresholdPanel" :trigger-rect="thresholdBtnRect"
      @update:visible="showThresholdPanel = $event" @close="showThresholdPanel = false" />
  </Teleport>
</template>


<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { dragonAnalyzer } from '@/services/DragonAnalyzer'
import { dragonBreathAnalyzer } from '@/services/DragonBreathAnalyzer'
import { algorithmManager } from '@/services/Algorithm'
import { dataLayer } from '@/services/DataLayer'
import { EventManager } from '@/utils/eventManager'
import { LEADER_LEVELS, AppEvents, BREATH_FACTORS_META, MARKET_PHASES } from '@/types'
import type { LeaderInfo, LeaderStats, LeaderChange, LeaderDistribution } from '@/types'
import ThresholdMultiplierPanel from './ThresholdMultiplierPanel.vue'

// ========== 使用组合式函数 ==========
import { usePanel } from '@/composables/usePanel'
import { usePanelData } from '@/composables/usePanelData'

// 阈值乘数面板状态
const showThresholdPanel = ref(false)
const thresholdBtnRef = ref<HTMLElement | null>(null)
const thresholdBtnRect = ref<DOMRect | undefined>()

// 打开阈值乘数配置面板
const openThresholdMultiplierPanel = (event: MouseEvent) => {
  thresholdBtnRect.value = (event.currentTarget as HTMLElement).getBoundingClientRect()
  showThresholdPanel.value = true
}

const props = defineProps<{
  visible: boolean
  triggerRect?: DOMRect
}>()

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'close'): void
}>()

// ========== 使用 usePanel 处理面板位置和关闭 ==========
const { panelRef, panelStyle } = usePanel({
  name: 'DragonHeadPanel',
  visible: props.visible,
  triggerRect: props.triggerRect,
  triggerSelectors: [
    '[title*="龙头监测"]',
    '[title*="潜龙在渊"]',
    '.nav-center button:nth-child(2)',
  ],
  onClose: close,
})

// ========== 加载状态控制 ==========
const isLoading = ref(false)
const isPanelVisible = ref(false)
const lastLoadTime = ref(0)
const LOAD_COOLDOWN = 1000 // 1秒冷却

// ========== 使用 usePanelData 处理数据加载 ==========
const {
  data,
  loading,
  error,
  loadData: loadPanelData,
  showToast,
} = usePanelData({
  name: 'DragonHeadPanel',
  fetchData: async () => {
    // 防止重复加载
    if (isLoading.value) {

      return data.value
    }

    isLoading.value = true


    try {
      const stocks = dataLayer.getStocks?.() || []

      if (stocks.length === 0) {

        return {
          leaders: [],
          changes: [],
          stats: null,
          distribution: { byLevel: {}, byTheme: {}, total: 0 },
          sentiment: { phase: '未知', overall: 0, riskLevel: '低', suggestion: '暂无数据' },
          emotionFactors: [],
        }
      }

      // 重新计算龙头

      if (dragonAnalyzer.recalculateAll) {
        await dragonAnalyzer.recalculateAll()
      }

      // 获取龙头数据
      const leaders = (dragonAnalyzer.getAllLeaders?.({ limit: 50 }) || []).map((leader) => ({
        ...leader,
        name: leader.name || leader.code || '未知',
      }))


      // 获取变化数据
      const changes = (dragonAnalyzer.getLeaderChanges?.(10) || []).map((change) => {
        // 处理变化数据...
        return change
      })

      // 获取统计和分布
      const stats = dragonAnalyzer.getStats?.() || null
      const distribution = dragonAnalyzer.getLeaderDistribution?.() || {
        byLevel: {},
        byTheme: {},
        total: 0,
      }

      // 获取情绪数据
      const sentiment = dragonBreathAnalyzer.getMarketSentiment?.() || {
        phase: '未知',
        overall: 0,
        riskLevel: '低',
        suggestion: '暂无数据',
      }

      const emotionFactors = loadEmotionFactors()

      return {
        leaders,
        changes,
        stats,
        distribution,
        sentiment,
        emotionFactors,
      }
    } catch (err) {
      console.error('[DragonHeadPanel] 加载数据失败:', err)
      throw err
    } finally {
      isLoading.value = false
      lastLoadTime.value = Date.now()
    }
  },
})

// ========== 从 data 中提取响应式数据 ==========
const leaders = computed(() => data.value?.leaders || [])
const changes = computed(() => data.value?.changes || [])
const stats = computed(() => data.value?.stats || null)
const distribution = computed(
  () => data.value?.distribution || { byLevel: {}, byTheme: {}, total: 0 },
)
const sentiment = computed(
  () =>
    data.value?.sentiment || {
      phase: '未知',
      overall: 0,
      riskLevel: '低',
      suggestion: '暂无数据',
    },
)
const emotionFactors = computed(() => data.value?.emotionFactors || [])

// ========== 从 MARKET_PHASES 常量获取阶段信息 ==========
const currentPhase = computed(() => {
  return Object.values(MARKET_PHASES).find((p) => p.name === sentiment.value.phase)
})

const phaseGradient = computed(() => {
  return currentPhase.value?.gradient || 'linear-gradient(135deg, #2c3e50, #34495e)'
})

const phaseIcon = computed(() => {
  return currentPhase.value?.icon || '🌬️'
})

const phaseList = computed(() => Object.values(MARKET_PHASES))

// ========== 状态 ==========
const view = ref<'list' | 'byLevel' | 'distribution' | 'emotion'>('list')
const showChanges = ref(true)
const selectedLevel = ref<keyof typeof LEADER_LEVELS>('TOTAL')
const filterLevel = ref('all')
const sortBy = ref('score')
const sortOrder = ref<'desc' | 'asc'>('desc')
const selectedCode = ref<string | null>(null)
const debugMode = ref(false)
const lastUpdate = ref(Date.now())
const unsubscribeEvents: (() => void)[] = []

// 调试状态
const repairing = ref(false)
const lastRepairSuccess = ref<boolean | null>(null)
const lastRepairTime = ref<string>('')
const repairCount = ref(0)
const repairHistory = ref<Array<{ time: number; success: boolean }>>([])
const showDebugPanel = ref(false)

// ========== 计算属性 ==========
const levelOptions = computed(() => {
  return Object.entries(LEADER_LEVELS).map(([key, value]) => ({
    value: value.name,
    label: value.name,
  }))
})

const levelTypes = computed(() => {
  return Object.entries(LEADER_LEVELS).map(([key, value]) => ({
    value: key,
    name: value.name,
    icon: value.icon,
    color: value.color,
  }))
})

const leaderStats = computed(() => {
  const s = stats.value || {
    totalLeadersCount: 0,
    continuousLeaders: 0,
    sectorLeaders: 0,
    middleLeaders: 0,
    emotionLeaders: 0,
  }
  return [
    { label: '总龙头', value: s.totalLeadersCount, color: LEADER_LEVELS.TOTAL.color },
    { label: '连板', value: s.continuousLeaders, color: LEADER_LEVELS.CONTINUOUS.color },
    { label: '板块', value: s.sectorLeaders, color: LEADER_LEVELS.SECTOR.color },
    { label: '中军', value: s.middleLeaders, color: LEADER_LEVELS.MIDDLE.color },
    { label: '情绪', value: s.emotionLeaders, color: LEADER_LEVELS.EMOTION.color },
  ]
})

const filteredLeaders = computed(() => {
  let result = leaders.value
  if (filterLevel.value !== 'all') {
    result = result.filter((l) => l.levelName === filterLevel.value)
  }
  return [...result].sort((a, b) => {
    const va = a[sortBy.value as keyof LeaderInfo] || 0
    const vb = b[sortBy.value as keyof LeaderInfo] || 0
    return sortOrder.value === 'desc'
      ? (vb as number) - (va as number)
      : (va as number) - (vb as number)
  })
})

const leadersByLevel = computed(() => {
  return dragonAnalyzer.getLeadersByLevel?.(selectedLevel.value, 20) || []
})

const tabs = computed(() => [
  { value: 'list', icon: '📋', label: '列表', count: leaders.value.length },
  { value: 'byLevel', icon: '👑', label: '级别' },
  { value: 'distribution', icon: '📊', label: '分布' },
  { value: 'emotion', icon: '🌬️', label: '情绪' },
])

// ========== 工具函数（保持不变）==========
function formatLevel(level: any): string {
  if (!level) return ''
  if (typeof level === 'string') return level
  if (typeof level === 'object') {
    return level.name || level.id || JSON.stringify(level)
  }
  return String(level)
}

function getLevelName(levelKey: string): string {
  const levelMap: Record<string, string> = {
    TOTAL: '总龙头',
    CONTINUOUS: '连板龙头',
    SECTOR: '板块龙头',
    MIDDLE: '中军龙头',
    EMOTION: '情绪龙头',
  }
  return levelMap[levelKey] || levelKey
}

function getLevelColor(level: string): string {
  if (!level) return '#7f8c8d'
  const entry = Object.values(LEADER_LEVELS).find((v) => v.name === level || v.name.includes(level))
  return entry?.color || '#7f8c8d'
}

function getFactorColor(factorId: string): string {
  const colors: Record<string, string> = {
    breathPhase: '#9b59b6',
    breathZtCount: '#2ecc71',
    breathDtCount: '#e74c3c',
    breathZhabanRate: '#f39c12',
    breathFengbanRate: '#3498db',
    breathPassRate: '#1abc9c',
    breathMaxDays: '#e67e22',
    breathUpDownRatio: '#95a5a6',
    breathEmotionValue: '#d35400',
    breathMarketScore: '#16a085',
  }
  return colors[factorId] || '#ffa502'
}

function truncateText(text: string, maxLength: number): string {
  if (text.length <= maxLength) return text
  return text.slice(0, maxLength) + '...'
}

function getChangeIcon(type: string): string {
  const icons: Record<string, string> = { 新增: '➕', 消失: '➖', 晋级: '⬆️', 降级: '⬇️' }
  return icons[type] || '🔔'
}

function getChangeClass(change: number): string {
  return change > 0 ? 'up' : change < 0 ? 'down' : ''
}

function getMoneyClass(value: number): string {
  return value > 0 ? 'up' : value < 0 ? 'down' : ''
}

function formatChange(change: number): string {
  if (!change && change !== 0) return '-'
  return (change > 0 ? '+' : '') + change.toFixed(2) + '%'
}

function formatVolume(volume: number): string {
  if (!volume && volume !== 0) return '-'
  const abs = Math.abs(volume)
  if (abs >= 1e8) return (volume / 1e8).toFixed(2) + '亿'
  if (abs >= 1e4) return (volume / 1e4).toFixed(2) + '万'
  return volume.toString()
}

function formatTime(timestamp: number): string {
  const date = new Date(timestamp)
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}

function formatTimeShort(timestamp: number): string {
  const diff = Math.floor((Date.now() - timestamp) / 60000)
  if (diff < 1) return '刚刚'
  if (diff < 60) return diff + '分钟前'
  return Math.floor(diff / 60) + '小时前'
}

// ========== 加载情绪因子 ==========
function loadEmotionFactors() {
  try {
    if (!algorithmManager || typeof algorithmManager.getFactorWeights !== 'function') {
      return []
    }

    const weights = algorithmManager.getFactorWeights() || []
    const weightMap = new Map(weights.map((w) => [w.id, w.weight]))

    const factors = Object.entries(BREATH_FACTORS_META || {})
      .map(([id, meta]) => {
        const weight = weightMap.get(id)
        return {
          id,
          name: meta?.name || id,
          description: meta?.description || '',
          weight: typeof weight === 'number' ? weight : 0.1,
        }
      })
      .filter((f) => f.weight > 0)
      .sort((a, b) => b.weight - a.weight)
      .slice(0, 6)

    return factors
  } catch (error) {
    return []
  }
}

// ========== 操作函数 ==========
function loadData(force = false) {
  const now = Date.now()

  // 如果不是强制加载，检查冷却时间
  if (!force && now - lastLoadTime.value < LOAD_COOLDOWN) {

    return
  }

  // 如果正在加载，跳过
  if (isLoading.value) {

    return
  }
  loadPanelData()
  lastUpdate.value = Date.now()
}

function refresh() {
  loadData(true) // 强制加载
  showToast('数据已刷新', 'success')
}

function close() {
  emit('update:visible', false)
  emit('close')
}

function toggleSortOrder() {
  sortOrder.value = sortOrder.value === 'desc' ? 'asc' : 'desc'
}

function selectLeader(code: string) {
  selectedCode.value = selectedCode.value === code ? null : code
  EventManager.emit(AppEvents.STOCK.SELECTED, { code })
}

function selectStock(code: string) {
  EventManager.emit(AppEvents.STOCK.SELECTED, { code })
  close()
}

function exportData() {
  const exportData = {
    exportTime: new Date().toISOString(),
    leaders: leaders.value,
    stats: stats.value,
    distribution: distribution.value,
    sentiment: sentiment.value,
  }
  const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `龙头数据_${new Date().toISOString().slice(0, 10)}.json`
  a.click()
  URL.revokeObjectURL(url)

  showToast(`已导出 ${leaders.value.length} 条记录`, 'success')
}

async function forceRepair() {
  repairing.value = true
  try {
    const result = await dragonAnalyzer.repairConsistency?.()

    lastRepairSuccess.value = result
    lastRepairTime.value = formatTime(Date.now())
    repairCount.value++

    repairHistory.value.unshift({
      time: Date.now(),
      success: result,
    })

    if (repairHistory.value.length > 10) {
      repairHistory.value.pop()
    }

    showToast(result ? '✅ 修复成功' : '❌ 修复失败', result ? 'success' : 'error')
  } catch (error) {
    lastRepairSuccess.value = false
    showToast('❌ 修复异常', 'error')
  } finally {
    repairing.value = false
  }
}

// ========== 生命周期 ==========
onMounted(() => {


  // 监听面板可见性变化
  const updateVisibility = () => {
    isPanelVisible.value = props.visible
  }
  updateVisibility()

  // 首次加载 - 只在可见时加载
  if (props.visible) {

    loadData(true)
  }

})

// 使用 watch 监听 visible 变化
watch(
  () => props.visible,
  (newVal, oldVal) => {
    isPanelVisible.value = newVal
    if (newVal && !oldVal) {
      // 从关闭到打开时强制加载
      loadData(true)
    }
  }
)

onUnmounted(() => {

  unsubscribeEvents.forEach((unsub) => {
    try {
      unsub()
    } catch (e) {
      console.warn('[DragonHeadPanel] 清理事件订阅失败:', e)
    }
  })
  unsubscribeEvents.length = 0
})
</script>
<style scoped>
.dragon-panel {
  position: fixed;
  width: 480px;
  max-width: calc(100vw - 32px);
  max-height: 85vh;
  overflow-y: auto;
  background: var(--bg-primary);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 24px;
  box-shadow: 0 20px 40px rgba(0, 0, 0, 0.4);
  z-index: 10005;
  font-size: 13px;
  backdrop-filter: blur(20px);
  animation: slideIn 0.2s ease;
}

@keyframes slideIn {
  from {
    opacity: 0;
    transform: translateY(-10px);
  }

  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* 头部样式 */
.panel-header {
  padding: 20px 20px 16px;
  border-radius: 24px 24px 0 0;
  color: white;
}

.header-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.panel-icon {
  font-size: 24px;
}

.panel-header h2 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
}

.live-badge {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  background: rgba(255, 255, 255, 0.2);
  border-radius: 20px;
  font-size: 11px;
  backdrop-filter: blur(4px);
}

.live-dot {
  width: 6px;
  height: 6px;
  background: #2ed573;
  border-radius: 50%;
  animation: pulse 1.5s infinite;
}

@keyframes pulse {

  0%,
  100% {
    opacity: 1;
  }

  50% {
    opacity: 0.4;
  }
}

.header-actions {
  display: flex;
  gap: 6px;
}

.btn-icon {
  width: 32px;
  height: 32px;
  border: none;
  background: rgba(255, 255, 255, 0.15);
  border-radius: 10px;
  color: white;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
  backdrop-filter: blur(4px);
}

.btn-icon:hover {
  background: rgba(255, 255, 255, 0.3);
  transform: scale(1.05);
}

.btn-icon.active {
  background: rgba(46, 213, 115, 0.3);
}

.btn-icon.close:hover {
  background: rgba(255, 71, 87, 0.3);
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

/* 情绪卡片样式 */
.sentiment-card {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin: 16px;
  padding: 16px;
  background: rgba(0, 0, 0, 0.3);
  border-radius: 16px;
  backdrop-filter: blur(8px);
}

.sentiment-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.phase-icon {
  font-size: 32px;
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
  opacity: 0.9;
}

.sentiment-suggestion {
  max-width: 180px;
  padding: 6px 12px;
  background: rgba(255, 255, 255, 0.2);
  border-radius: 20px;
  font-size: 12px;
  text-align: center;
}

/* 统计卡片网格 */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 8px;
  margin: 16px;
}

.stat-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 8px 4px;
  background: rgba(0, 0, 0, 0.2);
  border-radius: 12px;
  backdrop-filter: blur(4px);
}

.stat-label {
  font-size: 10px;
  opacity: 0.7;
  margin-bottom: 4px;
}

.stat-value {
  font-size: 16px;
  font-weight: 600;
}

/* 变化区域 */
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
  padding: 10px 12px;
  background: var(--bg-secondary);
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.2s;
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

.change-name {
  font-weight: 500;
  color: var(--text-primary);
}

.change-detail,
.change-level {
  font-size: 11px;
  color: var(--text-secondary);
}

.change-time {
  font-size: 11px;
  color: var(--text-secondary);
}

.type-新增 .change-icon {
  color: #2ed573;
}

.type-晋级 .change-icon {
  color: #ffd700;
}

.type-消失 .change-icon {
  color: #ff4757;
}

.type-降级 .change-icon {
  color: #ffa502;
}

/* 标签栏 */
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

/* 内容区域 */
.panel-content {
  max-height: 400px;
  overflow-y: auto;
  padding: 0 20px;
}

/* 筛选栏 */
.filter-bar {
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

.filter-select:hover {
  border-color: var(--color-highlight);
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

.btn-sort:hover {
  border-color: var(--color-highlight);
  background: var(--bg-hover);
}

/* 龙头卡片 */
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
  box-shadow: 0 8px 20px rgba(0, 0, 0, 0.2);
}

.leader-card.selected {
  border-color: var(--color-highlight);
  background: rgba(255, 165, 2, 0.05);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  padding-left: 4px;
  border-left: 3px solid transparent;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.stock-code {
  font-family: monospace;
  font-weight: 600;
  color: var(--color-highlight);
  background: rgba(255, 165, 2, 0.1);
  padding: 4px 8px;
  border-radius: 8px;
}

.stock-name {
  font-weight: 500;
  color: var(--text-primary);
}

.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.leader-badge {
  padding: 4px 12px;
  border-radius: 20px;
  font-size: 11px;
  font-weight: 500;
}

.leader-score {
  padding: 4px 8px;
  background: var(--bg-primary);
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
}

/* 指标区域 */
.card-metrics {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
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

.metric-value.up {
  color: #ff4757;
}

.metric-value.down {
  color: #2ed573;
}

.metric-value.highlight {
  color: var(--color-highlight);
}

/* 题材标签 */
.card-themes {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
}

.theme-tag {
  padding: 4px 10px;
  background: rgba(52, 152, 219, 0.1);
  border: 1px solid rgba(52, 152, 219, 0.2);
  border-radius: 20px;
  font-size: 11px;
  color: #3498db;
}

.theme-more {
  padding: 4px 10px;
  background: var(--bg-primary);
  border-radius: 20px;
  font-size: 11px;
  color: var(--text-secondary);
}

/* 理由标签 */
.card-reasons {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.reason-tag {
  padding: 2px 8px;
  background: rgba(46, 213, 115, 0.1);
  border: 1px solid rgba(46, 213, 115, 0.2);
  border-radius: 16px;
  font-size: 10px;
  color: #2ed573;
}

/* 级别视图 */
.level-tabs {
  display: flex;
  gap: 4px;
  padding: 16px 0;
  position: sticky;
  top: 0;
  background: var(--bg-primary);
  z-index: 1;
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

.level-tab:hover {
  background: var(--bg-hover);
}

.level-tab.active {
  background: var(--bg-primary);
  border-bottom: 2px solid currentColor;
}

.leader-card.mini {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
}

.leader-card.mini .card-header {
  margin-bottom: 0;
  border-left: none;
}

.card-change {
  font-weight: 500;
  font-size: 14px;
}

.card-change.up {
  color: #ff4757;
}

.card-change.down {
  color: #2ed573;
}

/* 分布视图 */
.distribution-view {
  padding: 16px 0;
}

.dist-section {
  margin-bottom: 24px;
}

.dist-section h4 {
  margin: 0 0 12px 0;
  color: var(--text-secondary);
  font-size: 12px;
}

.dist-chart {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.dist-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.dist-label {
  width: 80px;
  font-size: 12px;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.dist-bar-container {
  flex: 1;
  height: 8px;
  background: var(--bg-primary);
  border-radius: 4px;
  overflow: hidden;
}

.dist-bar-fill {
  height: 100%;
  border-radius: 4px;
  transition: width 0.3s;
}

.dist-count {
  min-width: 30px;
  font-size: 12px;
  color: var(--text-secondary);
  text-align: right;
  font-weight: 500;
}

/* 情绪视图 */
.emotion-view {
  padding: 16px 0;
}

.phase-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 8px;
  margin-bottom: 24px;
}

.phase-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  padding: 12px 8px;
  opacity: 0.5;
  transition: all 0.2s;
}

.phase-card.active {
  opacity: 1;
  border-color: var(--color-highlight);
  background: var(--bg-hover);
  transform: scale(1.02);
  box-shadow: 0 4px 12px rgba(255, 165, 2, 0.2);
}

.phase-header {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  margin-bottom: 8px;
}

.phase-icon {
  font-size: 20px;
}

.phase-name {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-primary);
}

.phase-features {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.feature-item {
  display: flex;
  align-items: flex-start;
  gap: 4px;
  font-size: 10px;
  line-height: 1.4;
}

.feature-bullet {
  color: var(--color-highlight);
  font-weight: bold;
}

.feature-text {
  color: var(--text-primary);
  font-weight: 500;
}

/* 因子权重 */
.factor-section {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 20px;
  padding: 16px;
}

.factor-section h4 {
  margin: 0 0 12px 0;
  color: var(--text-secondary);
  font-size: 12px;
}

.factor-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.factor-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.factor-name {
  width: 70px;
  font-size: 11px;
  color: var(--text-primary);
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.factor-bar-container {
  flex: 1;
  height: 6px;
  background: var(--bg-primary);
  border-radius: 3px;
  overflow: hidden;
}

.factor-bar-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.3s;
}

.factor-value {
  min-width: 40px;
  font-size: 11px;
  color: var(--color-highlight);
  font-weight: 600;
  text-align: right;
}

/* 底部 */
.panel-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-top: 1px solid var(--border-color);
  background: var(--bg-header);
  position: sticky;
  bottom: 0;
  z-index: 2;
}

.footer-left {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 11px;
  color: var(--text-secondary);
}

.total-count {
  color: var(--color-highlight);
  font-weight: 500;
}

.btn-text {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  background: transparent;
  border: 1px solid var(--border-color);
  border-radius: 20px;
  color: var(--text-primary);
  cursor: pointer;
  transition: all 0.2s;
  font-size: 12px;
}

.btn-text:hover {
  background: var(--color-highlight);
  color: #000;
  border-color: var(--color-highlight);
}

/* 空状态 */
.empty-state,
.empty-changes {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: var(--bg-secondary);
  border-radius: 12px;
  color: var(--text-secondary);
  gap: 8px;
}

.empty-icon {
  font-size: 24px;
  opacity: 0.5;
}

.empty-text {
  font-size: 12px;
}

/* 加载状态 */
.loading-overlay,
.error-overlay {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background: var(--bg-primary);
  border-radius: 24px;
  z-index: 10;
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

/* 滚动条 */
.panel-content::-webkit-scrollbar {
  width: 4px;
}

.panel-content::-webkit-scrollbar-track {
  background: transparent;
}

.panel-content::-webkit-scrollbar-thumb {
  background: var(--border-color);
  border-radius: 2px;
}

.panel-content::-webkit-scrollbar-thumb:hover {
  background: var(--color-highlight);
}

/* 调试按钮容器 */
.debug-actions {
  margin-left: 8px;
  display: inline-flex;
  align-items: center;
}

.debug-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  padding: 4px 10px;
  background: rgba(255, 71, 87, 0.1);
  border: 1px solid rgba(255, 71, 87, 0.3);
  border-radius: 16px;
  color: #ff4757;
  font-size: 11px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
  white-space: nowrap;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
  backdrop-filter: blur(4px);
}

.debug-btn:hover {
  background: rgba(255, 71, 87, 0.2);
  border-color: #ff4757;
  transform: translateY(-1px);
  box-shadow: 0 4px 8px rgba(255, 71, 87, 0.2);
}

.debug-btn:active {
  transform: translateY(0);
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.1);
}

.debug-btn .icon {
  font-size: 12px;
  margin-right: 2px;
}

.debug-btn.success {
  background: rgba(46, 213, 115, 0.1);
  border-color: rgba(46, 213, 115, 0.3);
  color: #2ed573;
}

.debug-btn.success:hover {
  background: rgba(46, 213, 115, 0.2);
  border-color: #2ed573;
  box-shadow: 0 4px 8px rgba(46, 213, 115, 0.2);
}

.debug-btn.error {
  background: rgba(255, 71, 87, 0.15);
  border-color: rgba(255, 71, 87, 0.5);
  color: #ff4757;
  animation: shake 0.3s ease;
}

.debug-btn.loading {
  opacity: 0.7;
  cursor: not-allowed;
  pointer-events: none;
}

.debug-btn.loading .icon {
  animation: rotate 1s infinite linear;
}

@keyframes shake {

  0%,
  100% {
    transform: translateX(0);
  }

  20% {
    transform: translateX(-5px);
  }

  40% {
    transform: translateX(5px);
  }

  60% {
    transform: translateX(-3px);
  }

  80% {
    transform: translateX(3px);
  }
}

.debug-panel {
  position: absolute;
  top: 100%;
  right: 0;
  margin-top: 4px;
  padding: 8px 12px;
  background: var(--bg-panel);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
  font-size: 11px;
  color: var(--text-secondary);
  z-index: 100;
  min-width: 180px;
}

.debug-panel-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 4px 0;
}

.debug-panel-label {
  color: var(--text-tertiary);
}

.debug-panel-value {
  font-weight: 500;
  color: var(--color-highlight);
}

.debug-panel-divider {
  height: 1px;
  background: var(--border-color);
  margin: 6px 0;
}

.repair-history {
  margin-top: 8px;
  font-size: 10px;
  color: var(--text-secondary);
}

.repair-history-item {
  display: flex;
  justify-content: space-between;
  padding: 2px 0;
}

.repair-time {
  color: var(--text-tertiary);
}

.repair-count {
  font-weight: 600;
}

.repair-count.success {
  color: #2ed573;
}

.repair-count.failed {
  color: #ff4757;
}

.btn-icon .icon.⚡ {
  font-size: 16px;
}
</style>
