<!-- src/components/panels/DragonHeadPanel.vue -->
<!-- 纯响应式版本：只依赖 dataLayer，自动响应数据变化 -->

<template>
  <Teleport to="body">
    <div v-if="visible" class="dragon-panel" :style="panelStyle" ref="panelRef">
      <!-- 头部渐变区域 -->
      <div class="panel-header" :style="{ background: phaseGradient }">
        <div class="header-top">
          <div class="header-left">
            <span class="panel-icon">🐲</span>
            <h2>龙头监测</h2>
          </div>
          <div class="header-actions">
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
              <div class="sentiment-phase">{{ sentiment.phaseName || sentiment.phase || '未知' }}</div>
              <div class="sentiment-score">情绪指数 {{ sentiment.overall?.toFixed(1) || '0' }}</div>
            </div>
          </div>
          <div class="sentiment-suggestion">{{ sentiment.suggestion || '暂无建议' }}</div>
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
      <div class="changes-section" v-if="recentChanges.length">
        <div class="section-header">
          <span class="section-title">
            <span class="title-icon">🔔</span>
            最近变化
          </span>
          <span class="changes-count">{{ recentChanges.length }}</span>
        </div>
        <div class="changes-list">
          <div v-for="(change, index) in recentChanges" :key="change.time + index" class="change-item"
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
      <div class="panel-content">
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
      </div>

      <!-- 底部 -->
      <div class="panel-footer">
        <div class="footer-left">
          <span class="total-count">共 {{ leaders.length }} 个龙头</span>
          <span class="update-time">{{ formatTime(lastUpdate) }} 更新</span>
        </div>
        <div class="footer-right">
          <button class="btn-text" @click="exportData"><span class="icon">📥</span> 导出</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { dataLayer } from '@/services/DataLayer'
import { LEADER_LEVELS, AppEvents } from '@/types'
import { EMOTION_PHASE_LIST, EMOTION_PHASE_BY_NAME } from '@/types/emotion'
import type { LeaderInfo, LeaderChange } from '@/types'
import { usePanel } from '@/composables/usePanel'

const props = defineProps<{
  visible: boolean
  triggerRect?: DOMRect
}>()

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'close'): void
  (e: 'select-stock', code: string): void
}>()

// ========== 面板定位 ==========
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

// ========== UI 状态 ==========
const view = ref<'list' | 'byLevel' | 'distribution' | 'emotion'>('list')
const selectedLevel = ref<keyof typeof LEADER_LEVELS>('TOTAL')
const filterLevel = ref('all')
const sortBy = ref('score')
const sortOrder = ref<'desc' | 'asc'>('desc')
const selectedCode = ref<string | null>(null)
const lastUpdate = ref(Date.now())
const unsubscribeFns: (() => void)[] = []

// ========== 从 dataLayer 获取数据（纯响应式）==========

// 情绪数据
const sentiment = computed(() => {
  const breath = (dataLayer as any).state?.analysis?.breath
  return {
    phase: breath?.sentiment?.phase || 'unknown',
    phaseName: breath?.sentiment?.phaseName || '未知',
    overall: breath?.sentiment?.overall || 50,
    riskLevel: breath?.sentiment?.riskLevel || '中',
    suggestion: breath?.sentiment?.suggestion || '观望为主',
  }
})

// 龙头数据
const leaders = computed(() => {
  // 从 merged.stocks 中筛选出龙头股
  const stocks = dataLayer.getStocks() || []
  return stocks
    .filter(s => s.isSectorLeader)
    .map(s => ({
      code: s.code,
      name: s.name || s.code,
      score: s.leaderScore || 0,
      level: s.leaderLevel || 'unknown',
      levelName: s.leaderLevel || '未知',
      price: s.price || 0,
      change: s.change || 0,
      turnover: s.turnover || 0,
      zlje: s.zlje || 0,
      continuousDays: s.continuousDays || 1,
      themes: s.themes || [],
      reasons: [], // 可以从其他地方获取
    }))
    .sort((a, b) => b.score - a.score)
})

// 按级别分组
const leadersByLevel = computed(() => {
  return leaders.value
    .filter(l => l.level === selectedLevel.value)
    .slice(0, 20)
})

// 按级别统计
const statsByLevel = computed(() => {
  const stats = {
    totalLeadersCount: 0,
    continuousLeaders: 0,
    sectorLeaders: 0,
    middleLeaders: 0,
    emotionLeaders: 0,
  }

  leaders.value.forEach(l => {
    if (l.level === 'TOTAL') stats.totalLeadersCount++
    else if (l.level === 'CONTINUOUS') stats.continuousLeaders++
    else if (l.level === 'SECTOR') stats.sectorLeaders++
    else if (l.level === 'MIDDLE') stats.middleLeaders++
    else if (l.level === 'EMOTION') stats.emotionLeaders++
  })

  return stats
})

// 统计卡片
const leaderStats = computed(() => {
  const s = statsByLevel.value
  return [
    { label: '总龙头', value: s.totalLeadersCount, color: LEADER_LEVELS.TOTAL.color },
    { label: '连板', value: s.continuousLeaders, color: LEADER_LEVELS.CONTINUOUS.color },
    { label: '板块', value: s.sectorLeaders, color: LEADER_LEVELS.SECTOR.color },
    { label: '中军', value: s.middleLeaders, color: LEADER_LEVELS.MIDDLE.color },
    { label: '情绪', value: s.emotionLeaders, color: LEADER_LEVELS.EMOTION.color },
  ]
})

// 最近变化（从 dataLayer 获取）
const recentChanges = computed(() => {
  // 可以从 dataLayer 的某个地方获取变化记录
  // 这里先用空数组，后续可以从分析器获取
  return [] as LeaderChange[]
})

// 情绪阶段信息
const currentPhase = computed(() => {
  const phaseName = sentiment.value.phaseName
  return EMOTION_PHASE_BY_NAME[phaseName] || EMOTION_PHASE_LIST.find(p => p.name === '震荡期')
})

const phaseGradient = computed(() => {
  return currentPhase.value?.gradient || 'linear-gradient(135deg, #2c3e50, #34495e)'
})

const phaseIcon = computed(() => {
  return currentPhase.value?.icon || '🌬️'
})

// 过滤后的龙头
const filteredLeaders = computed(() => {
  let result = leaders.value
  if (filterLevel.value !== 'all') {
    result = result.filter(l => l.levelName === filterLevel.value)
  }
  return [...result].sort((a, b) => {
    const va = a[sortBy.value as keyof typeof a] || 0
    const vb = b[sortBy.value as keyof typeof b] || 0
    return sortOrder.value === 'desc'
      ? (vb as number) - (va as number)
      : (va as number) - (vb as number)
  })
})

// 标签页
const tabs = computed(() => [
  { value: 'list', icon: '📋', label: '列表', count: leaders.value.length },
  { value: 'byLevel', icon: '👑', label: '级别' },
])

// 级别选项
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

// ========== 工具函数 ==========
function formatLevel(level: any): string {
  if (!level) return ''
  if (typeof level === 'string') return level
  if (typeof level === 'object') return level.name || level.id || ''
  return String(level)
}

function getLevelColor(level: string): string {
  if (!level) return '#7f8c8d'
  const entry = Object.values(LEADER_LEVELS).find(v => v.name === level || v.name.includes(level))
  return entry?.color || '#7f8c8d'
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

// ========== 操作方法 ==========
function close() {
  emit('update:visible', false)
  emit('close')
}

function toggleSortOrder() {
  sortOrder.value = sortOrder.value === 'desc' ? 'asc' : 'desc'
}

function selectLeader(code: string) {
  selectedCode.value = selectedCode.value === code ? null : code
  emit('select-stock', code)
}

function selectStock(code: string) {
  emit('select-stock', code)
  close()
}

function getFactorShortName(id: string): string {
  const names: Record<string, string> = {
    breathPhase: '阶段',
    breathZtCount: '涨停',
    breathDtCount: '跌停',
    breathZhabanRate: '炸板',
    breathFengbanRate: '封板',
    breathPassRate: '晋级',
    breathMaxDays: '连板',
    breathUpDownRatio: '涨跌比',
    breathEmotionValue: '情绪',
    breathMarketScore: '总分',
  }
  return names[id] || id.substring(0, 4)
}

function exportData() {
  const exportData = {
    exportTime: new Date().toISOString(),
    leaders: leaders.value,
    stats: statsByLevel.value,
    sentiment: sentiment.value,
  }
  const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `龙头数据_${new Date().toISOString().slice(0, 10)}.json`
  a.click()
  URL.revokeObjectURL(url)
}

// ========== 监听数据更新 ==========
function refreshFromDataLayer() {
  lastUpdate.value = Date.now()
}

onMounted(() => {
  // 监听数据更新事件
  const unsubMerged = dataLayer.subscribe('merged.stocks', refreshFromDataLayer)
  const unsubLeader = dataLayer.subscribe('leader.updated', refreshFromDataLayer)
  const unsubBreath = dataLayer.subscribe('analysis.breath', refreshFromDataLayer)

  unsubscribeFns.push(unsubMerged, unsubLeader, unsubBreath)

  // 初始加载
  refreshFromDataLayer()
})

onUnmounted(() => {
  unsubscribeFns.forEach(fn => fn())
})
</script>

<style scoped>
/* 样式保持不变，删除了调试相关样式 */
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

.btn-icon.close:hover {
  background: rgba(255, 71, 87, 0.3);
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

.weight-total {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed var(--border-color);
  font-weight: bold;
}

.weight-total .weight-name {
  color: var(--color-highlight);
}

.weight-total .weight-value {
  color: var(--color-highlight);
  font-weight: bold;
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
.empty-state {
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
</style>
