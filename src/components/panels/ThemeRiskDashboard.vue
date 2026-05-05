<!-- src/components/panels/ThemeRiskDashboard.vue -->
<!-- 题材风险看板 - 多标签页，参照 SectorPanel 设计风格 -->

<template>
  <div v-if="visible" class="risk-panel" :style="panelStyle" ref="panelRef">
    <!-- 头部 -->
    <div class="panel-header">
      <div class="header-left">
        <h3>题材风险看板 <span class="version-badge">v3.0</span></h3>
        <div class="stats-badge">
          <span>{{ phaseText }}</span>
          <span class="dot">·</span>
          <span>高风险 {{ riskLevels.high.length }}</span>
          <span class="dot">·</span>
          <span>预警 {{ events.length }}条</span>
        </div>
      </div>
      <div class="panel-actions">
        <button class="btn-icon" :class="{ loading }" :disabled="loading" @click="doRefresh" title="刷新">
          <span :class="{ 'rotate-animation': loading }">&#x21bb;</span>
        </button>
        <button class="btn-icon" @click="close" title="关闭">&#x2715;</button>
      </div>
    </div>

    <!-- 标签页 -->
    <div class="panel-tabs">
      <button class="tab-btn" :class="{ active: view === 'overview' }" @click="view = 'overview'">
        市场概览
        <span class="tab-dot" :style="{ background: phaseColor }"></span>
      </button>
      <button class="tab-btn" :class="{ active: view === 'layers' }" @click="view = 'layers'">
        风险分层
        <span v-if="riskLevels.high.length" class="tab-count critical">{{ riskLevels.high.length }}</span>
      </button>
      <button class="tab-btn" :class="{ active: view === 'alerts' }" @click="view = 'alerts'">
        实时预警
        <span v-if="events.length" class="tab-count warning">{{ events.length }}</span>
      </button>
    </div>

    <!-- 内容区 -->
    <div class="panel-content">
      <!-- 加载态 -->
      <div v-if="loading && !hasData" class="state-box">
        <div class="loading-spinner"></div>
        <span>加载题材风险数据...</span>
      </div>

      <!-- 空数据 -->
      <div v-else-if="!hasData && !loading" class="state-box">
        <span class="state-icon">--</span>
        <span>暂无题材风险数据</span>
        <span class="state-hint">请等待题材因子刷新或检查后端连接</span>
        <button class="retry-btn" @click="doRefresh">重试</button>
      </div>

      <!-- ====== 市场概览 ====== -->
      <template v-else-if="view === 'overview'">
        <!-- 情绪阶段卡 -->
        <div class="phase-card" :class="phaseClass">
          <div class="phase-header">
            <span class="phase-icon">{{ phaseIcon }}</span>
            <span class="phase-name">{{ phaseText }}</span>
            <span class="phase-risk">{{ riskLevelText }}</span>
          </div>
          <div class="phase-desc">{{ phaseDesc }}</div>
          <div class="phase-suggestion">{{ phaseSuggestion }}</div>
        </div>

        <!-- 市场数据网格 -->
        <div class="market-grid">
          <div class="market-item">
            <span class="market-label">涨停家数</span>
            <span class="market-value up">{{ marketStats.ztCount }}</span>
          </div>
          <div class="market-item">
            <span class="market-label">跌停家数</span>
            <span class="market-value down">{{ marketStats.dtCount }}</span>
          </div>
          <div class="market-item">
            <span class="market-label">炸板率</span>
            <span class="market-value">{{ marketStats.zhabanRate }}%</span>
          </div>
          <div class="market-item">
            <span class="market-label">涨跌比</span>
            <span class="market-value">{{ marketStats.upDownRatio }}</span>
          </div>
          <div class="market-item">
            <span class="market-label">连板高度</span>
            <span class="market-value">{{ marketStats.maxLianban }}板</span>
          </div>
          <div class="market-item">
            <span class="market-label">晋级率</span>
            <span class="market-value">{{ marketStats.passRate }}%</span>
          </div>
        </div>

        <!-- 风险分布摘要 -->
        <div class="summary-cards">
          <div class="summary-card critical">
            <span class="summary-count">{{ riskLevels.high.length }}</span>
            <span class="summary-label">高风险题材</span>
            <span class="summary-desc">拥挤≥70 / 降温 / 数据异常</span>
          </div>
          <div class="summary-card warning">
            <span class="summary-count">{{ riskLevels.warn.length }}</span>
            <span class="summary-label">警示题材</span>
            <span class="summary-desc">拥挤≥50 / 质量告警</span>
          </div>
          <div class="summary-card safe">
            <span class="summary-count">{{ riskLevels.safe.length }}</span>
            <span class="summary-label">安全题材</span>
            <span class="summary-desc">风险可控</span>
          </div>
        </div>
      </template>

      <!-- ====== 风险分层 ====== -->
      <div v-else-if="view === 'layers'" class="layers-view">
        <!-- 高风险 -->
        <div v-if="riskLevels.high.length" class="layer-section">
          <div class="layer-header critical">
            <span>高风险题材</span>
            <span class="layer-count">{{ riskLevels.high.length }}</span>
          </div>
          <div class="layer-cards">
            <div v-for="t in riskLevels.high" :key="t.themeId" class="theme-card critical">
              <div class="theme-card-header">
                <span class="theme-name">{{ t.themeName }}</span>
                <span class="theme-rank">#{{ t.rank }}</span>
              </div>
              <div class="theme-card-stats">
                <div class="stat-item">
                  <span class="stat-label">拥挤度</span>
                  <span class="stat-value" :class="t.crowdingRisk >= 80 ? 'critical' : 'warning'">
                    {{ t.crowdingRisk }}
                  </span>
                </div>
                <div class="stat-item">
                  <span class="stat-label">热度</span>
                  <span class="stat-value">{{ t.heatScore }}</span>
                </div>
                <div class="stat-item">
                  <span class="stat-label">动量</span>
                  <span class="stat-value">{{ t.momentumScore }}</span>
                </div>
                <div class="stat-item">
                  <span class="stat-label">龙头</span>
                  <span class="stat-value">{{ t.leaderCount }}</span>
                </div>
                <div class="stat-item">
                  <span class="stat-label">涨停</span>
                  <span class="stat-value">{{ t.ztCount }}</span>
                </div>
                <div class="stat-item">
                  <span class="stat-label">状态</span>
                  <span class="stat-value state-tag" :class="t.rotationState">{{ stateLabel(t.rotationState) }}</span>
                </div>
              </div>
              <div v-if="t.qualityFlags.length" class="theme-card-flags">
                <span v-for="f in t.qualityFlags" :key="f.code" class="flag-tag" :class="f.level">
                  {{ f.message || f.code }}
                </span>
              </div>
            </div>
          </div>
        </div>

        <!-- 警示 -->
        <div v-if="riskLevels.warn.length" class="layer-section">
          <div class="layer-header warning">
            <span>警示题材</span>
            <span class="layer-count">{{ riskLevels.warn.length }}</span>
          </div>
          <div class="layer-cards">
            <div v-for="t in riskLevels.warn" :key="t.themeId" class="theme-card warning">
              <div class="theme-card-header">
                <span class="theme-name">{{ t.themeName }}</span>
                <span class="theme-rank">#{{ t.rank }}</span>
              </div>
              <div class="theme-card-stats">
                <div class="stat-item">
                  <span class="stat-label">拥挤度</span>
                  <span class="stat-value">{{ t.crowdingRisk }}</span>
                </div>
                <div class="stat-item">
                  <span class="stat-label">热度</span>
                  <span class="stat-value">{{ t.heatScore }}</span>
                </div>
                <div class="stat-item">
                  <span class="stat-label">动量</span>
                  <span class="stat-value">{{ t.momentumScore }}</span>
                </div>
                <div class="stat-item">
                  <span class="stat-label">状态</span>
                  <span class="stat-value state-tag" :class="t.rotationState">{{ stateLabel(t.rotationState) }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 安全 -->
        <div v-if="riskLevels.safe.length" class="layer-section">
          <div class="layer-header safe">
            <span>安全题材</span>
            <span class="layer-count">{{ riskLevels.safe.length }}</span>
          </div>
          <div class="safe-list">
            <span v-for="t in riskLevels.safe.slice(0, 20)" :key="t.themeId" class="safe-chip">
              {{ t.themeName }}
              <small>{{ t.heatScore }}</small>
            </span>
          </div>
        </div>

        <div v-if="!riskLevels.high.length && !riskLevels.warn.length && !riskLevels.safe.length" class="state-box">
          <span>暂无分层数据</span>
        </div>
      </div>

      <!-- ====== 实时预警 ====== -->
      <div v-else-if="view === 'alerts'" class="alerts-view">
        <div v-if="events.length === 0" class="state-box">
          <span class="state-icon">&#x2713;</span>
          <span>暂无预警信息</span>
        </div>
        <div v-else class="alerts-list">
          <div v-for="event in events.slice(0, 30)" :key="event.id" class="alert-card" :class="event.level">
            <div class="alert-card-header">
              <span class="alert-type">{{ eventTypeLabel(event.type) }}</span>
              <span class="alert-level-tag" :class="event.level">{{ event.level === 'warning' ? '告警' : '提醒' }}</span>
              <span class="alert-time">{{ formatTime(event.timestamp) }}</span>
            </div>
            <div class="alert-card-body">
              <span class="alert-theme-name">{{ event.themeName }}</span>
              <span class="alert-reason">{{ event.reasons[0] || '' }}</span>
            </div>
            <div v-if="event.stockCodes.length" class="alert-card-stocks">
              关联个股: {{ event.stockCodes.slice(0, 5).join(' / ') }}
              <span v-if="event.stockCodes.length > 5"> 等{{ event.stockCodes.length }}只</span>
            </div>
          </div>
          <div v-if="events.length > 30" class="more-hint">
            还有 {{ events.length - 30 }} 条预警...
          </div>
        </div>
      </div>
    </div>

    <!-- 底部 -->
    <div class="panel-footer">
      <span>数据来源: themeFacade + DragonBreath</span>
      <span>{{ formatTime(lastUpdate) }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { dataLayer } from '@/services/DataLayer'
import { themeFacade } from '@/services/theme/ThemeFacade'
import { usePanel } from '@/composables/usePanel'
import { EMOTION_PHASE_BY_NAME } from '@/types/emotion'
import type { ThemeFactorSnapshot, ThemeEvent, ThemeQualityFlag } from '@/services/theme/types'

// ========== 对外接口 ==========
const props = defineProps<{
  visible: boolean
  triggerRect?: DOMRect
}>()

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'close'): void
}>()

const { panelRef, panelStyle } = usePanel({
  name: 'ThemeRiskDashboard',
  visible: props.visible,
  triggerRect: props.triggerRect,
  onClose: () => emit('close'),
})

// ========== 视图状态 ==========
const view = ref<'overview' | 'layers' | 'alerts'>('overview')
const loading = ref(false)
const lastUpdate = ref(Date.now())

// ========== 情绪呼吸数据 ==========
const breathSentiment = computed(() => {
  try { return (dataLayer as any).state?.analysis?.breath?.sentiment }
  catch { return null }
})

const breathMarket = computed(() => {
  try { return (dataLayer as any).state?.analysis?.breath?.marketData }
  catch { return null }
})

const phaseText = computed(() => breathSentiment.value?.phaseName || '--')
const phaseDesc = computed(() => breathSentiment.value?.phaseInfo?.desc || '等待数据')
const phaseSuggestion = computed(() => breathSentiment.value?.suggestion || '')

const phaseInfo = computed(() => {
  const name = breathSentiment.value?.phaseName
  return name ? EMOTION_PHASE_BY_NAME[name] : null
})

const phaseIcon = computed(() => phaseInfo.value?.icon || '')
const phaseColor = computed(() => phaseInfo.value?.color || '#7f8c8d')
const phaseClass = computed(() => phaseInfo.value?.value || 'ice')

const riskLevelText = computed(() => {
  const p = phaseText.value
  if (p === '高潮' || p === '退潮') return '高风险'
  if (p === '发酵') return '中风险'
  return '低风险'
})

const marketStats = computed(() => {
  const m = breathMarket.value
  const s = breathSentiment.value

  const upCount = m?.upCount
  const downCount = m?.downCount
  const upDownRatio =
    typeof upCount === 'number' && typeof downCount === 'number' && downCount > 0
      ? (upCount / downCount).toFixed(2)
      : '--'

  const zhabanRate =
    typeof m?.zhaban?.rate === 'number'
      ? m.zhaban.rate.toFixed(2)
      : '--'

  // 连板高度: 优先 maxContinuousDays, 其次 phaseInfo.metrics, 再降级 limitData
  const maxLianban =
    m?.maxContinuousDays ||
    s?.phaseInfo?.metrics?.maxContinuousDays ||
    s?.metrics?.maxContinuousDays ||
    (m?.limitData?.sibanPlus ? `${m.limitData.sibanPlus}+` : undefined) ||
    '--'

  const passRate =
    m?.passRate && typeof m.passRate.to2 === 'number'
      ? Math.round((m.passRate.to2 + (m.passRate.to3 || 0) + (m.passRate.to4 || 0)) / 3)
      : '--'

  return { ztCount: m?.ztCount ?? '--', dtCount: m?.dtCount ?? '--', zhabanRate, upDownRatio, maxLianban, passRate }
})

// ========== 题材因子 (从 themeFacade) ==========
const factors = computed<ThemeFactorSnapshot[]>(() => {
  try { return themeFacade.getThemeFactors() || [] }
  catch { return [] }
})

const events = computed<ThemeEvent[]>(() => {
  try { return themeFacade.getThemeEvents() || [] }
  catch { return [] }
})

const hasData = computed(() => factors.value.length > 0)

// ========== 风险分层 ==========
interface RiskTheme {
  themeId: string
  themeName: string
  heatScore: number
  momentumScore: number
  crowdingRisk: number
  rotationState: string
  ztCount: number
  leaderCount: number
  rank: number
  qualityFlags: ThemeQualityFlag[]
}

const riskLevels = computed(() => {
  const high: RiskTheme[] = []
  const warn: RiskTheme[] = []
  const safe: RiskTheme[] = []

  factors.value.forEach((f, i) => {
    const item: RiskTheme = {
      themeId: f.themeId,
      themeName: f.themeName,
      heatScore: Math.round(f.heatScore),
      momentumScore: Math.round(f.momentumScore),
      crowdingRisk: Math.round(f.crowdingRisk),
      rotationState: f.rotationState,
      ztCount: f.ztCount,
      leaderCount: f.leaderCount,
      rank: i + 1,
      qualityFlags: f.qualityFlags || [],
    }

    if (f.crowdingRisk >= 70 || f.rotationState === 'cooling' || f.qualityFlags.some((q) => q.level === 'fatal')) {
      high.push(item)
    } else if (f.crowdingRisk >= 50 || f.qualityFlags.some((q) => q.level === 'warning') || f.heatScore >= 75) {
      warn.push(item)
    } else {
      safe.push(item)
    }
  })

  high.sort((a, b) => b.crowdingRisk - a.crowdingRisk)
  warn.sort((a, b) => b.heatScore - a.heatScore)
  safe.sort((a, b) => b.heatScore - a.heatScore)

  return { high, warn, safe }
})

// ========== 辅助函数 ==========
function stateLabel(s: string): string {
  const m: Record<string, string> = {
    mainline: '主线', inflow: '流入', outflow: '流出',
    cooling: '降温', quick: '快轮', neutral: '中性',
  }
  return m[s] || s
}

function eventTypeLabel(t: string): string {
  const m: Record<string, string> = {
    theme_mainline_started: '主线启动',
    theme_strength_surge: '强度上升',
    theme_fund_inflow: '资金流入',
    theme_crowding_high: '拥挤预警',
    theme_cooling: '降温预警',
    theme_leader_fall: '龙头回落',
    theme_mapping_quality_warning: '数据质量',
  }
  return m[t] || t
}

function formatTime(ts: number): string {
  if (!ts) return '--:--'
  const d = new Date(ts)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

// ========== 操作 ==========
async function doRefresh() {
  loading.value = true
  try {
    themeFacade.refreshThemeFacadeState()
    lastUpdate.value = Date.now()
  } catch { /* 静默 */ }
  finally {
    setTimeout(() => { loading.value = false }, 400)
  }
}

function close() {
  emit('update:visible', false)
  emit('close')
}

watch(() => props.visible, (v) => { if (v) doRefresh() })
</script>

<style scoped>
/* ====== 面板容器 ====== */
.risk-panel {
  position: fixed;
  width: 560px;
  max-width: calc(100vw - 40px);
  max-height: 82vh;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
  z-index: 10011;
  font-size: 12px;
  overflow: hidden;
  color: var(--text-primary);
  display: flex;
  flex-direction: column;
}

/* ====== 头部 ====== */
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

.stats-badge {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 20px;
  font-size: 10px;
  color: var(--text-secondary);
}

.dot { opacity: 0.5; }

.panel-actions { display: flex; gap: 8px; }

.btn-icon {
  width: 32px; height: 32px;
  border: 1px solid var(--border-color);
  background: transparent;
  border-radius: 8px;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
}
.btn-icon:hover:not(:disabled) {
  background: var(--bg-hover);
  color: var(--text-primary);
  border-color: var(--color-highlight);
}
.btn-icon:disabled { opacity: 0.5; cursor: not-allowed; }

/* ====== 标签页 ====== */
.panel-tabs {
  display: flex;
  padding: 12px 20px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-secondary);
  gap: 4px;
}

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
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
}

.tab-btn:hover { background: var(--bg-hover); color: var(--text-primary); }

.tab-btn.active {
  background: var(--color-highlight);
  color: #000;
  font-weight: 500;
}

.tab-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }

.tab-count {
  font-size: 10px;
  padding: 0 6px;
  border-radius: 8px;
  line-height: 18px;
}
.tab-count.critical { background: rgba(255,71,87,0.2); color: #ff4757; }
.tab-count.warning { background: rgba(243,156,18,0.2); color: #f39c12; }

/* ====== 内容区 ====== */
.panel-content {
  padding: 20px;
  max-height: calc(82vh - 130px);
  overflow-y: auto;
  flex: 1;
}

/* ====== 通用状态 ====== */
.state-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  gap: 12px;
  color: var(--text-secondary);
}

.state-icon { font-size: 40px; opacity: 0.4; }
.state-hint { font-size: 11px; opacity: 0.6; }

.loading-spinner {
  width: 40px; height: 40px;
  border: 3px solid var(--border-color);
  border-top-color: var(--color-highlight);
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

.retry-btn {
  padding: 6px 16px;
  background: var(--color-highlight);
  border: none;
  border-radius: 16px;
  color: #000;
  font-size: 11px;
  cursor: pointer;
}

@keyframes spin { to { transform: rotate(360deg); } }
.rotate-animation { animation: rotate 1s infinite linear; display: inline-block; }
@keyframes rotate { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }

/* ====== 情绪阶段卡 (overview) ====== */
.phase-card {
  padding: 20px;
  border-radius: 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-left: 4px solid #7f8c8d;
  margin-bottom: 16px;
}
.phase-card.ice    { border-left-color: #7f8c8d; }
.phase-card.start  { border-left-color: #3498db; }
.phase-card.ferment { border-left-color: #f39c12; }
.phase-card.climax { border-left-color: #e74c3c; }
.phase-card.retreat { border-left-color: #9b59b6; }

.phase-header { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.phase-icon { font-size: 28px; }
.phase-name { font-size: 16px; font-weight: 600; }
.phase-risk {
  margin-left: auto;
  padding: 4px 12px;
  border-radius: 12px;
  font-size: 11px;
  font-weight: 500;
  background: var(--bg-primary);
}
.phase-desc { font-size: 12px; color: var(--text-secondary); margin-bottom: 6px; }
.phase-suggestion { font-size: 12px; color: var(--color-highlight); font-weight: 500; }

/* ====== 市场数据网格 (overview) ====== */
.market-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  margin-bottom: 16px;
}

.market-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 14px 8px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 10px;
}

.market-label { font-size: 10px; color: var(--text-secondary); margin-bottom: 4px; }
.market-value { font-size: 20px; font-weight: 700; }
.market-value.up { color: #ff4757; }
.market-value.down { color: #2ed573; }

/* ====== 摘要卡片 (overview) ====== */
.summary-cards {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
}

.summary-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 16px 8px;
  border-radius: 10px;
  border: 1px solid var(--border-color);
  background: var(--bg-secondary);
}

.summary-card.critical { border-top: 3px solid #ff4757; }
.summary-card.warning  { border-top: 3px solid #f39c12; }
.summary-card.safe     { border-top: 3px solid #7f8c8d; }

.summary-count { font-size: 26px; font-weight: 700; }
.summary-card.critical .summary-count { color: #ff4757; }
.summary-card.warning  .summary-count { color: #f39c12; }
.summary-card.safe     .summary-count { color: #7f8c8d; }

.summary-label { font-size: 11px; color: var(--text-secondary); margin-top: 2px; }
.summary-desc  { font-size: 9px;  color: var(--text-tertiary, #666); margin-top: 4px; text-align: center; }

/* ====== 风险分层 (layers) ====== */
.layers-view { display: flex; flex-direction: column; gap: 20px; }

.layer-section { display: flex; flex-direction: column; gap: 10px; }

.layer-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
  font-weight: 600;
}
.layer-header.critical { color: #ff4757; }
.layer-header.warning  { color: #f39c12; }
.layer-header.safe     { color: #7f8c8d; }

.layer-count {
  padding: 2px 10px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  font-size: 11px;
  color: var(--text-secondary);
  font-weight: 400;
}

.layer-cards { display: flex; flex-direction: column; gap: 10px; }

.theme-card {
  padding: 16px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  transition: all 0.2s;
}

.theme-card.critical { border-left: 4px solid #ff4757; }
.theme-card.warning  { border-left: 4px solid #f39c12; }

.theme-card:hover {
  transform: translateY(-2px);
  border-color: var(--color-highlight);
  box-shadow: 0 4px 12px rgba(255,177,66,0.15);
}

.theme-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.theme-name { font-size: 15px; font-weight: 600; }
.theme-rank { font-size: 11px; color: var(--text-secondary); padding: 2px 6px; background: var(--bg-primary); border-radius: 8px; }

.theme-card-stats {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
}

.stat-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 8px 4px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
}

.stat-label { font-size: 10px; color: var(--text-secondary); margin-bottom: 2px; }
.stat-value { font-size: 15px; font-weight: 600; }
.stat-value.critical { color: #ff4757; }
.stat-value.warning  { color: #f39c12; }

.state-tag {
  font-size: 12px !important;
  padding: 2px 6px;
  border-radius: 6px;
}
.state-tag.mainline { color: #2ed573; background: rgba(46,213,115,0.1); }
.state-tag.cooling   { color: #ff4757; background: rgba(255,71,87,0.1); }
.state-tag.inflow    { color: #f39c12; background: rgba(243,156,18,0.1); }
.state-tag.outflow   { color: #3498db; background: rgba(52,152,219,0.1); }
.state-tag.quick     { color: #9b59b6; background: rgba(155,89,182,0.1); }
.state-tag.neutral   { color: #7f8c8d; background: rgba(127,140,141,0.1); }

.theme-card-flags { display: flex; gap: 4px; flex-wrap: wrap; margin-top: 10px; }

.flag-tag {
  font-size: 10px;
  padding: 2px 8px;
  border-radius: 10px;
}
.flag-tag.fatal   { background: rgba(255,71,87,0.12);  color: #ff4757; }
.flag-tag.warning { background: rgba(243,156,18,0.12);  color: #f39c12; }
.flag-tag.info    { background: rgba(52,152,219,0.12);  color: #3498db; }

/* 安全区 - 紧凑 chip 列表 */
.safe-list { display: flex; flex-wrap: wrap; gap: 6px; }
.safe-chip {
  padding: 4px 10px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 14px;
  font-size: 11px;
  color: var(--text-secondary);
}
.safe-chip small { margin-left: 4px; opacity: 0.6; font-size: 10px; }

/* ====== 预警 (alerts) ====== */
.alerts-view { display: flex; flex-direction: column; gap: 12px; }
.alerts-list { display: flex; flex-direction: column; gap: 8px; }

.alert-card {
  padding: 14px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  border-left: 4px solid transparent;
}

.alert-card.warning { border-left-color: #f39c12; }
.alert-card.info    { border-left-color: #3498db; }

.alert-card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.alert-type { font-size: 12px; font-weight: 500; }
.alert-level-tag {
  font-size: 10px;
  padding: 1px 8px;
  border-radius: 10px;
}
.alert-level-tag.warning { background: rgba(243,156,18,0.15); color: #f39c12; }
.alert-level-tag.info    { background: rgba(52,152,219,0.15); color: #3498db; }

.alert-time { margin-left: auto; font-size: 10px; color: var(--text-secondary); }

.alert-card-body { display: flex; gap: 8px; align-items: baseline; }
.alert-theme-name { font-size: 13px; font-weight: 500; }
.alert-reason { font-size: 11px; color: var(--text-secondary); }

.alert-card-stocks {
  margin-top: 6px;
  font-size: 10px;
  color: var(--text-secondary);
  padding: 4px 8px;
  background: var(--bg-primary);
  border-radius: 6px;
}

.more-hint {
  padding: 8px;
  text-align: center;
  font-size: 11px;
  color: var(--text-secondary);
  border-top: 1px dashed var(--border-color);
}

/* ====== 页脚 ====== */
.panel-footer {
  padding: 12px 20px;
  border-top: 1px solid var(--border-color);
  background: var(--bg-header);
  font-size: 10px;
  color: var(--text-secondary);
  display: flex;
  justify-content: space-between;
}

/* ====== 滚动条 ====== */
.panel-content::-webkit-scrollbar { width: 4px; }
.panel-content::-webkit-scrollbar-track { background: transparent; }
.panel-content::-webkit-scrollbar-thumb { background: var(--border-color); border-radius: 2px; }
.panel-content::-webkit-scrollbar-thumb:hover { background: var(--color-highlight); }
</style>
