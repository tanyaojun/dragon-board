<!-- src/components/panels/ThemeRiskDashboard.vue -->
<!-- 重构版：统一情绪阶段，简洁实用设计 -->

<template>
  <Teleport to="body">
    <div v-if="visible" class="risk-panel" :style="panelStyle" ref="panelRef">
      <!-- 头部 - 简洁 -->
      <div class="panel-header">
        <div class="header-left">
          <span class="panel-icon">📊</span>
          <h3>题材风险看板</h3>
          <span class="version-badge">v2.0</span>
        </div>
        <div class="header-actions">
          <button class="btn-icon" @click="refresh" :class="{ rotating: loading }" title="刷新">↻</button>
          <button class="btn-icon close" @click="close" title="关闭">✕</button>
        </div>
      </div>

      <!-- 加载状态 -->
      <div v-if="loading" class="loading-state">
        <div class="loading-spinner"></div>
        <span>加载数据...</span>
      </div>

      <!-- 主要内容 -->
      <div class="panel-content" v-else>
        <!-- ===== 市场概览卡片 ===== -->
        <div class="overview-grid">
          <!-- 市场阶段 -->
          <div class="info-card" :class="marketStatus.phaseClass">
            <div class="card-header">
              <span class="card-icon">📈</span>
              <span class="card-title">市场阶段</span>
            </div>
            <div class="card-value">{{ marketStatus.phase }}</div>
            <div class="card-desc">{{ marketStatus.phaseDesc }}</div>
          </div>

          <!-- 风险等级 -->
          <div class="info-card" :class="marketStatus.riskClass">
            <div class="card-header">
              <span class="card-icon">⚠️</span>
              <span class="card-title">风险等级</span>
            </div>
            <div class="card-value">{{ marketStatus.riskLevel }}</div>
            <div class="card-desc">{{ marketStatus.riskDesc }}</div>
          </div>

          <!-- 情绪阶段 -->
          <div class="info-card">
            <div class="card-header">
              <span class="card-icon">🌡️</span>
              <span class="card-title">情绪阶段</span>
            </div>
            <div class="card-value">{{ sentimentStage }}</div>
            <div class="card-desc">{{ sentimentSuggestion }}</div>
          </div>
        </div>

        <!-- ===== 题材阶段监控 ===== -->
        <div class="section-card">
          <div class="section-header">
            <h4>📌 题材阶段</h4>
            <div class="stage-indicators">
              <span class="stage-badge" v-for="stat in stageStats" :key="stat.name" :class="stat.class">
                {{ stat.name }} {{ stat.count }}
              </span>
            </div>
          </div>

          <!-- 萌芽期 -->
          <div v-if="themeStages.sprout.length" class="stage-block" data-stage="sprout">
            <div class="stage-header" @click="toggleStage('sprout')">
              <div class="header-left">
                <span class="stage-icon">🌱</span>
                <span class="stage-name">萌芽期</span>
                <span class="stage-count">{{ themeStages.sprout.length }}</span>
              </div>
              <span class="toggle">{{ expanded.sprout ? '▼' : '▶' }}</span>
            </div>
            <div v-show="expanded.sprout" class="stage-body">
              <div v-for="theme in themeStages.sprout" :key="theme.name" class="theme-item">
                <div class="theme-title">{{ theme.name }}</div>
                <div class="theme-metrics">
                  <span class="metric" v-for="signal in theme.signals" :key="signal">{{ signal }}</span>
                </div>
              </div>
            </div>
          </div>

          <!-- 发酵期 -->
          <div v-if="themeStages.ferment.length" class="stage-block" data-stage="ferment">
            <div class="stage-header" @click="toggleStage('ferment')">
              <div class="header-left">
                <span class="stage-icon">🔥</span>
                <span class="stage-name">发酵期</span>
                <span class="stage-count">{{ themeStages.ferment.length }}</span>
              </div>
              <span class="toggle">{{ expanded.ferment ? '▼' : '▶' }}</span>
            </div>
            <div v-show="expanded.ferment" class="stage-body">
              <div v-for="theme in themeStages.ferment" :key="theme.name" class="theme-item">
                <div class="theme-title">{{ theme.name }}</div>
                <div class="theme-stats">
                  <div class="stat-row">
                    <span>涨停 {{ theme.ztCount }}只</span>
                    <span :class="theme.moneyFlow > 0 ? 'inflow' : 'outflow'">
                      {{ formatMoney(theme.moneyFlow) }}
                    </span>
                  </div>
                  <div v-if="theme.leader" class="leader-row">
                    <span class="leader-label">龙头</span>
                    <span class="leader-name">{{ theme.leader.name }}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- 爆发期 -->
          <div v-if="themeStages.explode.length" class="stage-block" data-stage="explode">
            <div class="stage-header" @click="toggleStage('explode')">
              <div class="header-left">
                <span class="stage-icon">⚡</span>
                <span class="stage-name">爆发期</span>
                <span class="stage-count">{{ themeStages.explode.length }}</span>
              </div>
              <span class="toggle">{{ expanded.explode ? '▼' : '▶' }}</span>
            </div>
            <div v-show="expanded.explode" class="stage-body">
              <div v-for="theme in themeStages.explode" :key="theme.name" class="theme-item">
                <div class="theme-title">{{ theme.name }}</div>
                <div class="theme-stats">
                  <div class="stat-row">
                    <span>涨停 {{ theme.ztCount }}只</span>
                    <span class="inflow">{{ formatMoney(theme.moneyFlow) }}</span>
                  </div>
                  <div class="stat-row" v-if="theme.leader">
                    <span>龙头 {{ theme.leader.name }}</span>
                    <span class="badge">{{ theme.leader.level }}板</span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- 衰退期 -->
          <div v-if="themeStages.decline.length" class="stage-block" data-stage="decline">
            <div class="stage-header" @click="toggleStage('decline')">
              <div class="header-left">
                <span class="stage-icon">📉</span>
                <span class="stage-name">衰退期</span>
                <span class="stage-count">{{ themeStages.decline.length }}</span>
              </div>
              <span class="toggle">{{ expanded.decline ? '▼' : '▶' }}</span>
            </div>
            <div v-show="expanded.decline" class="stage-body">
              <div v-for="theme in themeStages.decline" :key="theme.name" class="theme-item">
                <div class="theme-title">{{ theme.name }}</div>
                <div class="theme-stats">
                  <div class="stat-row">
                    <span>涨停 {{ theme.ztCount }}只</span>
                    <span class="outflow">{{ formatMoney(theme.moneyFlow) }}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- ===== 风险预警 ===== -->
        <div class="section-card">
          <div class="section-header">
            <h4>⚠️ 实时预警</h4>
            <span class="alert-count">{{ totalAlerts }}条</span>
          </div>

          <!-- 持仓风险 -->
          <div v-if="positionRisks.length" class="risk-block">
            <div class="risk-header" @click="toggleRisk('position')">
              <div class="header-left">
                <span class="risk-icon">🔴</span>
                <span class="risk-title">持仓风险</span>
                <span class="risk-count">{{ positionRisks.length }}</span>
              </div>
              <span class="toggle">{{ expanded.position ? '▼' : '▶' }}</span>
            </div>
            <div v-show="expanded.position" class="risk-body">
              <div v-for="risk in positionRisks" :key="risk.id" class="risk-item critical">
                <div class="risk-main">
                  <span class="risk-name">{{ risk.name }}</span>
                  <span class="risk-desc">{{ risk.message }}</span>
                </div>
                <div class="risk-action">{{ risk.action }}</div>
              </div>
            </div>
          </div>

          <!-- 市场风险 -->
          <div v-if="marketRisks.length" class="risk-block">
            <div class="risk-header" @click="toggleRisk('market')">
              <div class="header-left">
                <span class="risk-icon">🟡</span>
                <span class="risk-title">市场风险</span>
                <span class="risk-count">{{ marketRisks.length }}</span>
              </div>
              <span class="toggle">{{ expanded.market ? '▼' : '▶' }}</span>
            </div>
            <div v-show="expanded.market" class="risk-body">
              <div v-for="risk in marketRisks" :key="risk.id" class="risk-item warning">
                <div class="risk-main">
                  <span class="risk-name">{{ risk.title }}</span>
                  <span class="risk-desc">{{ risk.desc }}</span>
                </div>
                <div class="risk-action">{{ risk.advice }}</div>
              </div>
            </div>
          </div>

          <!-- 机会预警 -->
          <div v-if="opportunities.length" class="risk-block">
            <div class="risk-header" @click="toggleRisk('opportunity')">
              <div class="header-left">
                <span class="risk-icon">🟢</span>
                <span class="risk-title">机会预警</span>
                <span class="risk-count">{{ opportunities.length }}</span>
              </div>
              <span class="toggle">{{ expanded.opportunity ? '▼' : '▶' }}</span>
            </div>
            <div v-show="expanded.opportunity" class="risk-body">
              <div v-for="op in opportunities" :key="op.id" class="risk-item info">
                <div class="risk-main">
                  <span class="risk-name">{{ op.name }}</span>
                  <span class="risk-desc">{{ op.desc }}</span>
                </div>
                <div class="risk-action">{{ op.action }}</div>
              </div>
            </div>
          </div>

          <div v-if="totalAlerts === 0" class="empty-alerts">
            <span class="empty-icon">✅</span>
            <span>暂无预警</span>
          </div>
        </div>
      </div>

      <!-- 底部 - 简洁 -->
      <div class="panel-footer">
        <span class="update-time">⏱️ {{ formatTime(lastUpdate) }}</span>
        <span class="advice">{{ adviceText }}</span>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { dataLayer } from '@/services/DataLayer'
import { themeFacade } from '@/services/theme/ThemeFacade'
import { usePanel } from '@/composables/usePanel'
import { EMOTION_PHASE_BY_NAME } from '@/types/emotion'
import StageBlock from './risk/StageBlock.vue'
import RiskBlock from './risk/RiskBlock.vue'

const props = defineProps<{
  visible: boolean
  triggerRect?: DOMRect
  embedded?: boolean
}>()

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'close'): void
}>()

// ========== 面板定位 ==========
const { panelRef, panelStyle } = usePanel({
  name: 'ThemeRiskDashboard',
  visible: props.visible,
  triggerRect: props.triggerRect,
  onClose: () => emit('close')
})

// ========== 状态 ==========
const loading = ref(false)
const lastUpdate = ref(Date.now())

// ========== 展开控制 ==========
const expanded = ref({
  sprout: true,
  ferment: true,
  explode: true,
  decline: true,
  position: true,
  market: true,
  opportunity: true
})

const toggleStage = (stage: keyof typeof expanded.value) => {
  expanded.value[stage] = !expanded.value[stage]
}

const toggleRisk = (risk: 'position' | 'market' | 'opportunity') => {
  expanded.value[risk] = !expanded.value[risk]
}

// ========== 从 dataLayer 获取情绪数据 ==========
const breathData = computed(() => {
  return (dataLayer as any).state?.analysis?.breath
})

const currentSentiment = computed(() => {
  return breathData.value?.sentiment || {}
})

const currentPhase = computed(() => {
  const phaseName = currentSentiment.value.phaseName || '启动'
  return EMOTION_PHASE_BY_NAME[phaseName] || null
})

const sentimentStage = computed(() => {
  return currentSentiment.value.phaseName || currentSentiment.value.phase || '启动'
})

const sentimentSuggestion = computed(() => {
  return currentSentiment.value.suggestion || '观望为主'
})

// ========== 市场状态 ==========
const marketStatus = computed(() => {
  const phase = currentPhase.value

  let phaseClass = 'start'
  let riskClass = 'warning'
  let riskLevel = '中风险'
  let riskDesc = '正常操作'

  if (phase) {
    phaseClass = phase.value || 'start'
  }

  if (phase?.name === '高潮' || phase?.name === '退潮') {
    riskLevel = '高风险'
    riskDesc = '注意风险控制'
    riskClass = 'critical'
  } else if (phase?.name === '冰点' || phase?.name === '启动') {
    riskLevel = '低风险'
    riskDesc = '轻仓试错'
    riskClass = 'low'
  }

  return {
    phase: currentSentiment.value.phaseName || '启动',
    phaseDesc: currentSentiment.value.suggestion || '观望为主',
    phaseClass,
    riskLevel,
    riskDesc,
    riskClass
  }
})

// ========== 工具函数 ==========
const formatTime = (timestamp: number) => {
  const date = new Date(timestamp)
  return `${date.getHours().toString().padStart(2, '0')}:${date.getMinutes().toString().padStart(2, '0')}`
}

const formatMoney = (value: number) => {
  if (!value && value !== 0) return '-'
  const absValue = Math.abs(value)
  if (absValue >= 100000000) {
    return (value / 100000000).toFixed(2) + '亿'
  }
  if (absValue >= 10000) {
    return (value / 10000).toFixed(2) + '万'
  }
  return value.toString()
}

// ========== 题材阶段识别 ==========
const themeStages = computed(() => {
  const blocks = themeFacade.getJxbkBlocksCompat()
  const stockMap = themeFacade.getThemeStockMapCompat()

  const stages = {
    sprout: [] as any[],
    ferment: [] as any[],
    explode: [] as any[],
    decline: [] as any[]
  }

  blocks.forEach(block => {
    const ztStocks = Object.values(stockMap).filter((s: any) =>
      s.blocks?.includes(block.name) && (s.change || 0) > 9.5
    )

    const leader = Object.values(stockMap).find((s: any) =>
      s.blocks?.includes(block.name) && s.leadStatus?.includes('龙')
    ) as any

    const ztCount = ztStocks.length
    const moneyFlow = block.mainNetInflow || 0

    // 根据情绪阶段调整判断阈值
    const multiplier = currentPhase.value?.thresholdMultiplier?.themeHeat || 1.0
    const adjustedZtThreshold = Math.floor(2 * multiplier)
    const adjustedMoneyThreshold = 50000000 * multiplier

    let stage = 'decline'
    if (ztCount >= 5 && moneyFlow > 200000000) {
      stage = 'explode'
    } else if (ztCount >= adjustedZtThreshold && moneyFlow > adjustedMoneyThreshold) {
      stage = 'ferment'
    } else if (ztCount >= 1 || block.change > 3) {
      stage = 'sprout'
    }

    stages[stage as keyof typeof stages].push({
      name: block.name,
      ztCount,
      moneyFlow,
      leader: leader ? {
        name: leader.name,
        level: leader.lianban?.match(/\d+/)?.[0] || 1
      } : null,
      signals: generateSignals(block, ztStocks)
    })
  })

  return stages
})

const stageStats = computed(() => {
  return [
    { name: '萌芽', count: themeStages.value.sprout.length, class: 'sprout' },
    { name: '发酵', count: themeStages.value.ferment.length, class: 'ferment' },
    { name: '爆发', count: themeStages.value.explode.length, class: 'explode' },
    { name: '衰退', count: themeStages.value.decline.length, class: 'decline' }
  ]
})

const generateSignals = (block: any, ztStocks: any[]) => {
  const signals = []
  if (ztStocks.length >= 3) signals.push('批量涨停')
  if (block.mainNetInflow > 100000000) signals.push('资金涌入')
  if (block.volumeRatio > 2) signals.push('放量')
  return signals.slice(0, 2)
}

// ========== 风险预警 ==========
const positionRisks = computed(() => {
  const alerts = dataLayer.getAlerts?.() || []
  return alerts
    .filter((a: any) => a.level === 'critical')
    .map((a: any) => ({
      id: a.id,
      code: a.code || a.themeId,
      name: a.name || a.themeName,
      message: a.message,
      action: '减仓'
    }))
    .slice(0, 3)
})

const marketRisks = computed(() => {
  const risks = []
  const blocks = themeFacade.getJxbkBlocksCompat()

  // 炸板风险
  const explodeBlocks = blocks.filter(b => b.ztCount === 0 && b.change > 5)
  if (explodeBlocks.length > 2) {
    risks.push({
      id: 'explode',
      title: '批量炸板',
      desc: `${explodeBlocks.length}个板块冲高回落`,
      advice: '暂停追高'
    })
  }

  // 轮动风险
  const quickRotation = blocks.filter(b => Math.abs(b.change) > 5).length
  if (quickRotation > 8) {
    risks.push({
      id: 'rotation',
      title: '轮动过快',
      desc: '多个板块脉冲式上涨',
      advice: '不追涨'
    })
  }

  return risks
})

const opportunities = computed(() => {
  return themeStages.value.ferment.slice(0, 3).map(t => ({
    id: t.name,
    name: t.leader?.name || t.name,
    theme: t.name,
    desc: `${t.ztCount}只涨停，资金${formatMoney(t.moneyFlow)}`,
    action: '关注'
  }))
})

const totalAlerts = computed(() => {
  return positionRisks.value.length + marketRisks.value.length + opportunities.value.length
})

// ========== 底部建议 ==========
const adviceText = computed(() => {
  const phase = currentSentiment.value.suggestion || '观望为主'
  return `${marketStatus.value.phase} · ${phase}`
})

// ========== 操作 ==========
const refresh = () => {
  loading.value = true
  setTimeout(() => {
    lastUpdate.value = Date.now()
    loading.value = false
  }, 300)
}

const close = () => emit('close')

onMounted(() => {
  if (props.visible) refresh()
})
</script>

<style scoped>
/* ========== 实用主义样式 - 有层次的配色 ========== */
.risk-panel {
  position: fixed;
  width: 600px;
  max-width: calc(100vw - 40px);
  max-height: 80vh;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
  z-index: 10011;
  font-size: 13px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
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
  gap: 10px;
}

.panel-icon {
  font-size: 20px;
}

.panel-header h3 {
  margin: 0;
  font-size: 16px;
  color: var(--text-primary);
}

.version-badge {
  font-size: 10px;
  background: var(--bg-secondary);
  color: var(--text-secondary);
  padding: 2px 6px;
  border-radius: 12px;
}

.header-actions {
  display: flex;
  gap: 8px;
}

.btn-icon {
  width: 32px;
  height: 32px;
  border: 1px solid var(--border-color);
  background: transparent;
  border-radius: 6px;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 16px;
  transition: all 0.2s;
}

.btn-icon:hover {
  background: var(--bg-hover);
  border-color: var(--color-highlight);
  color: var(--text-primary);
}

/* 内容区域 */
.panel-content {
  flex: 1;
  padding: 16px;
  overflow-y: auto;
  max-height: calc(80vh - 120px);
}

/* ===== 概览卡片网格 - 有层次的颜色 ===== */
.overview-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin-bottom: 20px;
}

.info-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 16px 12px;
  transition: all 0.2s;
}

/* 市场阶段卡片 - 不同阶段不同颜色 */
.info-card.start {
  border-left: 3px solid #3498db;
  background: linear-gradient(to right, rgba(52, 152, 219, 0.05), var(--bg-secondary));
}

.info-card.climax {
  border-left: 3px solid #ffd700;
  background: linear-gradient(to right, rgba(255, 215, 0, 0.05), var(--bg-secondary));
}

.info-card.retreat {
  border-left: 3px solid #9b59b6;
  background: linear-gradient(to right, rgba(155, 89, 182, 0.05), var(--bg-secondary));
}

.info-card.ice {
  border-left: 3px solid #7f8c8d;
  background: linear-gradient(to right, rgba(127, 140, 141, 0.05), var(--bg-secondary));
}

.info-card.ferment {
  border-left: 3px solid #f39c12;
  background: linear-gradient(to right, rgba(243, 156, 18, 0.05), var(--bg-secondary));
}

/* 风险等级卡片 - 不同风险不同颜色 */
.info-card.critical {
  border-left: 3px solid #ff4757;
  background: linear-gradient(to right, rgba(255, 71, 87, 0.05), var(--bg-secondary));
}

.info-card.warning {
  border-left: 3px solid #f39c12;
  background: linear-gradient(to right, rgba(243, 156, 18, 0.05), var(--bg-secondary));
}

.info-card.low {
  border-left: 3px solid #2ed573;
  background: linear-gradient(to right, rgba(46, 213, 115, 0.05), var(--bg-secondary));
}

.card-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
  color: var(--text-secondary);
  font-size: 11px;
}

.card-value {
  font-size: 22px;
  font-weight: 600;
  margin-bottom: 4px;
}

/* 卡片值的颜色 - 与左侧边框呼应 */
.info-card.start .card-value {
  color: #3498db;
}

.info-card.climax .card-value {
  color: #ffd700;
}

.info-card.retreat .card-value {
  color: #9b59b6;
}

.info-card.ice .card-value {
  color: #7f8c8d;
}

.info-card.ferment .card-value {
  color: #f39c12;
}

.info-card.critical .card-value {
  color: #ff4757;
}

.info-card.warning .card-value {
  color: #f39c12;
}

.info-card.low .card-value {
  color: #2ed573;
}

.card-desc {
  font-size: 11px;
  color: var(--text-secondary);
}

/* ===== 区块卡片 ===== */
.section-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 16px;
  margin-bottom: 16px;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.section-header h4 {
  margin: 0;
  font-size: 14px;
  color: var(--text-primary);
}

/* 阶段指示器 */
.stage-indicators {
  display: flex;
  gap: 8px;
}

.stage-badge {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: 12px;
  font-size: 11px;
  background: var(--bg-primary);
}

.stage-badge.sprout {
  color: #4a90e2;
  border-left: 2px solid #4a90e2;
}

.stage-badge.ferment {
  color: #f39c12;
  border-left: 2px solid #f39c12;
}

.stage-badge.explode {
  color: #ff4757;
  border-left: 2px solid #ff4757;
}

.stage-badge.decline {
  color: #7f8c8d;
  border-left: 2px solid #7f8c8d;
}

/* 阶段块 */
.stage-block {
  margin-bottom: 8px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  overflow: hidden;
}

.stage-header {
  padding: 10px 12px;
  background: var(--bg-header);
  display: flex;
  justify-content: space-between;
  align-items: center;
  cursor: pointer;
  transition: all 0.2s;
}

.stage-header:hover {
  background: var(--bg-hover);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.stage-icon {
  font-size: 14px;
}

.stage-name {
  font-size: 13px;
  font-weight: 500;
}

.stage-count {
  font-size: 11px;
  padding: 2px 6px;
  background: var(--bg-primary);
  border-radius: 12px;
  color: var(--text-secondary);
}

.toggle {
  font-size: 11px;
  color: var(--text-tertiary);
}

.stage-body {
  padding: 12px;
  background: var(--bg-primary);
}

/* 题材卡片 - 不同阶段不同颜色 */
.theme-item {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 8px;
  transition: all 0.2s;
}

.theme-item:last-child {
  margin-bottom: 0;
}

.theme-item:hover {
  transform: translateX(2px);
}

/* 萌芽期 */
.stage-block[data-stage="sprout"] .theme-item {
  border-left: 2px solid #4a90e2;
}

/* 发酵期 */
.stage-block[data-stage="ferment"] .theme-item {
  border-left: 2px solid #f39c12;
}

/* 爆发期 */
.stage-block[data-stage="explode"] .theme-item {
  border-left: 2px solid #ff4757;
}

/* 衰退期 */
.stage-block[data-stage="decline"] .theme-item {
  border-left: 2px solid #7f8c8d;
  opacity: 0.8;
}

.theme-title {
  font-weight: 500;
  margin-bottom: 8px;
  font-size: 13px;
  color: var(--text-primary);
}

/* 统计行 */
.stat-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
  font-size: 12px;
  color: var(--text-secondary);
}

.inflow {
  color: #ff4757;
  font-weight: 500;
}

.outflow {
  color: #2ed573;
  font-weight: 500;
}

.leader-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 8px;
  background: var(--bg-primary);
  border-radius: 4px;
  font-size: 11px;
}

.leader-label {
  color: var(--text-tertiary);
}

.leader-name {
  color: var(--color-highlight);
  font-weight: 500;
}

.badge {
  padding: 2px 6px;
  background: rgba(255, 165, 2, 0.2);
  border-radius: 10px;
  color: var(--color-highlight);
  font-size: 10px;
}

.metric {
  display: inline-block;
  padding: 2px 8px;
  margin-right: 6px;
  background: var(--bg-primary);
  border-radius: 12px;
  font-size: 10px;
  color: var(--text-secondary);
}

/* ===== 风险区块 ===== */
.risk-block {
  margin-bottom: 8px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  overflow: hidden;
}

.risk-header {
  padding: 10px 12px;
  background: var(--bg-header);
  display: flex;
  justify-content: space-between;
  align-items: center;
  cursor: pointer;
  transition: all 0.2s;
}

.risk-header:hover {
  background: var(--bg-hover);
}

.risk-body {
  padding: 12px;
  background: var(--bg-primary);
}

.risk-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 12px;
  margin-bottom: 6px;
  background: var(--bg-secondary);
  border-left: 3px solid transparent;
  border-radius: 6px;
  transition: all 0.2s;
}

.risk-item:last-child {
  margin-bottom: 0;
}

.risk-item:hover {
  transform: translateX(2px);
}

/* 不同风险级别颜色 */
.risk-item.critical {
  border-left-color: #ff4757;
  background: linear-gradient(to right, rgba(255, 71, 87, 0.03), var(--bg-secondary));
}

.risk-item.warning {
  border-left-color: #f39c12;
  background: linear-gradient(to right, rgba(243, 156, 18, 0.03), var(--bg-secondary));
}

.risk-item.info {
  border-left-color: #3498db;
  background: linear-gradient(to right, rgba(52, 152, 219, 0.03), var(--bg-secondary));
}

.risk-main {
  flex: 1;
}

.risk-name {
  display: block;
  font-weight: 500;
  margin-bottom: 2px;
  color: var(--text-primary);
}

.risk-desc {
  font-size: 11px;
  color: var(--text-secondary);
}

.risk-action {
  font-size: 11px;
  padding: 4px 8px;
  background: var(--bg-primary);
  border-radius: 12px;
  color: var(--color-highlight);
  white-space: nowrap;
}

/* 空状态 */
.empty-alerts {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 32px;
  color: var(--text-secondary);
  gap: 8px;
}

.empty-icon {
  font-size: 24px;
  opacity: 0.3;
}

/* 底部 */
.panel-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 20px;
  border-top: 1px solid var(--border-color);
  background: var(--bg-header);
  font-size: 11px;
  color: var(--text-secondary);
}

.update-time {
  font-family: monospace;
}

.advice {
  color: var(--color-highlight);
}

/* 加载状态 */
.loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 60px;
  gap: 12px;
}

.loading-spinner {
  width: 32px;
  height: 32px;
  border: 3px solid var(--border-color);
  border-top-color: var(--color-highlight);
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.rotating {
  animation: rotate 1s linear infinite;
}

@keyframes rotate {
  from {
    transform: rotate(0deg);
  }

  to {
    transform: rotate(360deg);
  }
}

/* 滚动条美化 */
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
