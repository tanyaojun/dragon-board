<!-- src/components/panels/DragonLifecyclePanel.vue -->
<!-- 龙头生命周期追踪面板 - 专业版 v2.0 (集成DataLayer) -->

<template>
  <Teleport to="body">
    <div v-if="visible" class="lifecycle-panel" :style="panelStyle" ref="panelRef">
      <!-- 面板头部 -->
      <div class="panel-header">
        <div class="header-left">
          <span class="panel-icon">🐉</span>
          <h3>真龙天子 · 生命周期</h3>
          <span class="version-badge">v2.0.0</span>
        </div>
        <div class="header-actions">
          <button class="btn-icon" @click="refresh" title="刷新" :disabled="loading">
            <span class="icon" :class="{ rotating: loading }">↻</span>
          </button>
          <button class="btn-icon close" @click="close" title="关闭" :disabled="loading">
            <span class="icon">✕</span>
          </button>
        </div>
      </div>

      <!-- 加载覆盖层 -->
      <div v-if="loading" class="loading-overlay">
        <div class="loading-spinner"></div>
        <span>加载真龙数据中...</span>
      </div>

      <!-- 面板内容 -->
      <div class="panel-content" :class="{ 'content-blur': loading }">
        <!-- 统计卡片 -->
        <div class="stats-grid">
          <div class="stat-card">
            <span class="stat-label">📊 追踪龙头</span>
            <span class="stat-value">{{ stats.totalTracked }}</span>
          </div>
          <div class="stat-card">
            <span class="stat-label">👑 活跃真龙</span>
            <span class="stat-value">{{ stats.activeCount }}</span>
          </div>
          <div class="stat-card">
            <span class="stat-label">⏱️ 平均寿命</span>
            <span class="stat-value">{{ stats.averageLifespan.toFixed(1) }}天</span>
          </div>
          <div class="stat-card">
            <span class="stat-label">🧬 基因均值</span>
            <span class="stat-value">{{ stats.averageGenesScore.toFixed(1) }}</span>
          </div>
        </div>

        <!-- 观察队列状态 -->
        <div class="queue-section">
          <div class="queue-tabs">
            <button class="queue-tab" :class="{ active: activeQueue === 'primary' }" @click="activeQueue = 'primary'">
              主队列 <span class="queue-badge">{{ observationStats.primary }}</span>
            </button>
            <button class="queue-tab" :class="{ active: activeQueue === 'secondary' }"
              @click="activeQueue = 'secondary'">
              次队列 <span class="queue-badge">{{ observationStats.secondary }}</span>
            </button>
            <button class="queue-tab" :class="{ active: activeQueue === 'cold' }" @click="activeQueue = 'cold'">
              冷备 <span class="queue-badge">{{ observationStats.cold }}</span>
            </button>
          </div>

          <!-- 主队列详情 - 使用增强数据 -->
          <div v-if="activeQueue === 'primary'" class="queue-detail">
            <div v-for="(item, index) in enhancedPrimaryQueue" :key="item?.code || index" class="queue-item-detail">
              <div class="queue-item-header">
                <span class="queue-item-code">{{ item?.code || '--' }}</span>
                <span class="queue-item-name">{{ item?.name || '--' }}</span>
                <span v-if="item?.rating" class="queue-item-rating" :class="`rating-${item.rating}`">
                  {{ item.rating }}
                </span>
              </div>
              <div class="queue-item-genes">
                <span class="gene" title="资金">💰 {{ item?.genes?.money || 0 }}</span>
                <span class="gene" title="技术">📈 {{ item?.genes?.technical || 0 }}</span>
                <span class="gene" title="题材">🎯 {{ item?.genes?.theme || 0 }}</span>
                <span class="gene" title="情绪">🔥 {{ item?.genes?.sentiment || 0 }}</span>
              </div>
              <div class="queue-item-meta">
                <span class="meta-time">⏱️ {{ item?.firstSeen ? formatTime(item.firstSeen) : '--' }}</span>
                <span class="meta-count">📊 {{ item?.appearances || 0 }}次</span>
                <span class="meta-score">⭐ {{ item?.score?.toFixed(1) || '0.0' }}</span>
              </div>
              <!-- 实时行情数据 -->
              <div v-if="item?.price" class="queue-item-realtime">
                <span class="realtime-price">💰 {{ item.price.toFixed(2) }}</span>
                <span class="realtime-change" :class="item.change >= 0 ? 'up' : 'down'">
                  {{ item.change > 0 ? '+' : '' }}{{ item.change?.toFixed(2) }}%
                </span>
                <span v-if="item.zlje" class="realtime-zlje">
                  主力 {{ formatAmount(item.zlje) }}
                </span>
              </div>
            </div>
            <div v-if="!enhancedPrimaryQueue?.length" class="queue-empty">
              主队列暂无种子
            </div>
          </div>

          <!-- 次队列详情 - 使用增强数据 -->
          <div v-if="activeQueue === 'secondary'" class="queue-detail">
            <div v-for="(item, index) in enhancedSecondaryQueue" :key="item?.code || index" class="queue-item-detail">
              <div class="queue-item-header">
                <span class="queue-item-code">{{ item?.code || '--' }}</span>
                <span class="queue-item-name">{{ item?.name || '--' }}</span>
                <span v-if="item?.rating" class="queue-item-rating" :class="`rating-${item.rating}`">
                  {{ item.rating }}
                </span>
              </div>
              <div class="queue-item-genes">
                <span class="gene" title="资金">💰 {{ item?.genes?.money || 0 }}</span>
                <span class="gene" title="技术">📈 {{ item?.genes?.technical || 0 }}</span>
                <span class="gene" title="题材">🎯 {{ item?.genes?.theme || 0 }}</span>
                <span class="gene" title="情绪">🔥 {{ item?.genes?.sentiment || 0 }}</span>
              </div>
              <div class="queue-item-meta">
                <span class="meta-time">⏱️ {{ item?.firstSeen ? formatTime(item.firstSeen) : '--' }}</span>
                <span class="meta-count">📊 {{ item?.appearances || 0 }}次</span>
                <span class="meta-score">⭐ {{ item?.score?.toFixed(1) || '0.0' }}</span>
              </div>
              <!-- 实时行情数据 -->
              <div v-if="item?.price" class="queue-item-realtime">
                <span class="realtime-price">💰 {{ item.price.toFixed(2) }}</span>
                <span class="realtime-change" :class="item.change >= 0 ? 'up' : 'down'">
                  {{ item.change > 0 ? '+' : '' }}{{ item.change?.toFixed(2) }}%
                </span>
                <span v-if="item.zlje" class="realtime-zlje">
                  主力 {{ formatAmount(item.zlje) }}
                </span>
              </div>
            </div>
            <div v-if="!enhancedSecondaryQueue?.length" class="queue-empty">
              次队列暂无种子
            </div>
          </div>

          <!-- 冷备队列详情 - 使用增强数据 -->
          <div v-if="activeQueue === 'cold'" class="queue-detail">
            <div v-for="(item, index) in enhancedColdQueue" :key="item?.code || index" class="queue-item-detail">
              <div class="queue-item-header">
                <span class="queue-item-code">{{ item?.code || '--' }}</span>
                <span class="queue-item-name">{{ item?.name || '--' }}</span>
                <span v-if="item?.rating" class="queue-item-rating" :class="`rating-${item.rating}`">
                  {{ item.rating }}
                </span>
              </div>
              <div class="queue-item-genes">
                <span class="gene" title="资金">💰 {{ item?.genes?.money || 0 }}</span>
                <span class="gene" title="技术">📈 {{ item?.genes?.technical || 0 }}</span>
                <span class="gene" title="题材">🎯 {{ item?.genes?.theme || 0 }}</span>
                <span class="gene" title="情绪">🔥 {{ item?.genes?.sentiment || 0 }}</span>
              </div>
              <div class="queue-item-meta">
                <span class="meta-time">⏱️ {{ item?.firstSeen ? formatTime(item.firstSeen) : '--' }}</span>
                <span class="meta-count">📊 {{ item?.appearances || 0 }}次</span>
                <span class="meta-score">⭐ {{ item?.score?.toFixed(1) || '0.0' }}</span>
              </div>
              <!-- 实时行情数据 -->
              <div v-if="item?.price" class="queue-item-realtime">
                <span class="realtime-price">💰 {{ item.price.toFixed(2) }}</span>
                <span class="realtime-change" :class="item.change >= 0 ? 'up' : 'down'">
                  {{ item.change > 0 ? '+' : '' }}{{ item.change?.toFixed(2) }}%
                </span>
                <span v-if="item.zlje" class="realtime-zlje">
                  主力 {{ formatAmount(item.zlje) }}
                </span>
              </div>
            </div>
            <div v-if="!enhancedColdQueue?.length" class="queue-empty">
              冷备队列暂无种子
            </div>
          </div>
        </div>

        <!-- 评级分布 -->
        <div class="section-card">
          <div class="section-header">
            <h4>🏆 真龙评级分布</h4>
            <span class="header-count">{{ Object.keys(ratingDistribution).length }}级</span>
          </div>
          <div class="rating-grid">
            <div v-for="(count, rating) in ratingDistribution" :key="rating" class="rating-item"
              :class="`rating-${rating}`">
              <span class="rating-badge">{{ rating }}</span>
              <div class="rating-bar-container">
                <div class="rating-bar" :style="{
                  width: (count / stats.confirmedCount * 100) + '%',
                  background: getRatingColor(rating)
                }"></div>
              </div>
              <span class="rating-count">{{ count }}只</span>
            </div>
          </div>
        </div>

        <!-- 阶段分布 -->
        <div class="section-card">
          <div class="section-header">
            <h4>🌱 生命周期阶段</h4>
            <span class="header-count">{{ Object.keys(stageDistribution).length }}阶段</span>
          </div>
          <div class="stages-timeline">
            <div v-for="(count, stage) in stageDistribution" :key="stage" class="stage-item"
              @click="filterByStage(stage)">
              <div class="stage-header">
                <span class="stage-icon" :style="{ color: LIFECYCLE_STAGES[stage]?.color }">
                  {{ LIFECYCLE_STAGES[stage]?.icon }}
                </span>
                <span class="stage-name">{{ LIFECYCLE_STAGES[stage]?.name }}</span>
                <span class="stage-count">{{ count }}只</span>
              </div>
              <div class="stage-progress">
                <div class="progress-track">
                  <div class="progress-fill" :style="{
                    width: (count / stats.activeCount * 100) + '%',
                    background: LIFECYCLE_STAGES[stage]?.color
                  }"></div>
                </div>
              </div>
              <div class="stage-signals" v-if="stageSignals[stage]">
                <span v-for="signal in stageSignals[stage].slice(0, 2)" :key="signal" class="signal-tag">
                  {{ signal }}
                </span>
              </div>
            </div>
          </div>
        </div>

        <!-- 存活率曲线 -->
        <div class="section-card">
          <div class="section-header">
            <h4>📈 真龙存活曲线</h4>
            <span class="header-count">10天存活率 {{ survivalRate10 }}%</span>
          </div>
          <div class="curve-container">
            <canvas ref="curveCanvas" width="400" height="150"></canvas>
            <div class="curve-markers">
              <div v-for="point in survivalCurve" :key="point.day" class="curve-marker"
                :style="{ left: (point.day - 1) * 10 + '%' }">
                <span class="marker-value">{{ point.rate.toFixed(0) }}%</span>
                <span class="marker-label">{{ point.day }}天</span>
              </div>
            </div>
          </div>
        </div>

        <!-- 真龙列表 -->
        <div class="section-card">
          <div class="section-header">
            <h4>👑 当前真龙</h4>
            <div class="header-tabs">
              <button class="tab-btn" :class="{ active: leaderFilter === 'all' }" @click="leaderFilter = 'all'">
                全部({{ enhancedLeaders.length }})
              </button>
              <button class="tab-btn" :class="{ active: leaderFilter === 'sss' }" @click="leaderFilter = 'sss'">
                SSS({{enhancedLeaders.filter(l => l.genetics?.rating === 'SSS').length}})
              </button>
              <button class="tab-btn" :class="{ active: leaderFilter === 'ss' }" @click="leaderFilter = 'ss'">
                SS({{enhancedLeaders.filter(l => l.genetics?.rating === 'SS').length}})
              </button>
              <button class="tab-btn" :class="{ active: leaderFilter === 's' }" @click="leaderFilter = 's'">
                S({{enhancedLeaders.filter(l => l.genetics?.rating === 'S').length}})
              </button>
            </div>
          </div>

          <!-- 调试信息 -->
          <div v-if="enhancedLeaders.length === 0" class="debug-info"
            style="padding: 20px; text-align: center; color: #ffd700;">
            🐉 暂无真龙数据，等待观察期股票确认...
          </div>

          <!-- 真龙列表 - 使用增强数据 -->
          <div class="leaders-list">
            <div v-for="leader in filteredLeaders" :key="leader.code" class="leader-card" @click="selectLeader(leader)">
              <div class="leader-header">
                <div class="leader-title">
                  <span class="leader-code">{{ leader.code }}</span>
                  <span class="leader-name">{{ leader.name }}</span>
                </div>
                <span class="leader-rating" :class="`rating-${leader.genetics?.rating}`">
                  {{ leader.genetics?.rating }}
                </span>
              </div>

              <div class="leader-body">
                <div class="leader-stage-indicator">
                  <div v-for="(stage, idx) in leader.stages.slice(-3)" :key="idx" class="stage-dot"
                    :style="{ background: LIFECYCLE_STAGES[stage.stage]?.color }"
                    :title="`${LIFECYCLE_STAGES[stage.stage]?.name}: ${formatDuration(stage)}`">
                  </div>
                </div>

                <div class="leader-genes">
                  <div class="gene-item" :title="`资金强度: ${leader.genetics?.genes.money.score}`">
                    <span class="gene-icon">💰</span>
                    <span class="gene-value">{{ leader.genetics?.genes.money.score }}</span>
                  </div>
                  <div class="gene-item" :title="`技术强度: ${leader.genetics?.genes.technical.score}`">
                    <span class="gene-icon">📈</span>
                    <span class="gene-value">{{ leader.genetics?.genes.technical.score }}</span>
                  </div>
                  <div class="gene-item" :title="`题材强度: ${leader.genetics?.genes.theme.score}`">
                    <span class="gene-icon">🎯</span>
                    <span class="gene-value">{{ leader.genetics?.genes.theme.score }}</span>
                  </div>
                  <div class="gene-item" :title="`情绪强度: ${leader.genetics?.genes.sentiment.score}`">
                    <span class="gene-icon">🔥</span>
                    <span class="gene-value">{{ leader.genetics?.genes.sentiment.score }}</span>
                  </div>
                </div>

                <!-- 实时行情数据 -->
                <div class="leader-realtime" v-if="leader.price">
                  <span class="realtime-price">💰 {{ leader.price.toFixed(2) }}</span>
                  <span class="realtime-change" :class="leader.change >= 0 ? 'up' : 'down'">
                    {{ leader.change > 0 ? '+' : '' }}{{ leader.change?.toFixed(2) }}%
                  </span>
                  <span v-if="leader.zlje" class="realtime-zlje">
                    主力 {{ formatAmount(leader.zlje) }}
                  </span>
                </div>

                <div class="leader-stats">
                  <div class="stat">
                    <span class="stat-label">连板</span>
                    <span class="stat-value">{{ leader.stages[leader.stages.length - 1]?.continuousDays || 1 }}板</span>
                  </div>
                  <div class="stat">
                    <span class="stat-label">得分</span>
                    <span class="stat-value">{{ leader.peakScore.toFixed(1) }}</span>
                  </div>
                  <div class="stat">
                    <span class="stat-label">寿命</span>
                    <span class="stat-value">{{ formatAge(leader) }}</span>
                  </div>
                </div>

                <!-- 潜力预测 -->
                <div class="leader-potential" v-if="leader.genetics?.potential">
                  <div class="potential-bar">
                    <div class="potential-fill" :style="{
                      width: leader.genetics.potential.confidence + '%',
                      background: getConfidenceColor(leader.genetics.potential.confidence)
                    }"></div>
                  </div>
                  <span class="potential-text">
                    预期{{ leader.genetics.potential.maxDays }}板 · 目标{{ formatPrice(leader.genetics.potential.targetPrice)
                    }}
                  </span>
                </div>
              </div>

              <!-- 家族关系 -->
              <div class="leader-family" v-if="getFamily(leader.code)">
                <div class="family-row" v-if="getFamily(leader.code).parents.length">
                  <span class="family-label">👆 前任</span>
                  <span class="family-names">{{ getLeaderNames(getFamily(leader.code).parents.slice(0, 2)) }}</span>
                </div>
                <div class="family-row" v-if="getFamily(leader.code).children.length">
                  <span class="family-label">👇 继任</span>
                  <span class="family-names">{{ getLeaderNames(getFamily(leader.code).children.slice(0, 2)) }}</span>
                </div>
              </div>
            </div>

            <div v-if="filteredLeaders.length === 0 && enhancedLeaders.length > 0" class="empty-state">
              暂无符合条件的真龙
            </div>
          </div>
        </div>

        <!-- 传承链 -->
        <div class="section-card">
          <div class="section-header">
            <h4>🔄 真龙传承</h4>
            <span class="header-count">{{ successionChains.length }}条</span>
          </div>
          <div class="succession-list">
            <div v-for="chain in successionChains.slice(0, 3)" :key="chain.predecessor.code + chain.successor.code"
              class="succession-item">
              <div class="succession-chain">
                <span class="chain-predecessor" :class="`rating-${chain.predecessor.genetics?.rating}`">
                  {{ chain.predecessor.name }}
                </span>
                <span class="chain-arrow">→</span>
                <span class="chain-successor" :class="`rating-${chain.successor.genetics?.rating}`">
                  {{ chain.successor.name }}
                </span>
              </div>
              <div class="chain-meta">
                <span class="chain-gap" :class="{ 'smooth': chain.smooth }">
                  {{ formatGap(chain.gap) }}
                </span>
                <span class="chain-quality" :class="chain.quality">
                  {{ chain.quality }}
                </span>
              </div>
            </div>
          </div>
        </div>

        <!-- 最近变化 -->
        <div class="section-card">
          <div class="section-header">
            <h4>⏱️ 实时动态</h4>
            <span class="header-count">{{ recentTransitions.length }}条</span>
          </div>
          <div class="transitions-stream">
            <div v-for="(t, index) in recentTransitions.slice(0, 5)" :key="t.code + '-' + t.timestamp + '-' + index"
              class="transition-item">
              <span class="transition-time">{{ formatTime(t.timestamp) }}</span>
              <span class="transition-name">{{ t.name }}</span>
              <span class="transition-evolution">
                <span class="evolution-from" :style="{ color: LIFECYCLE_STAGES[t.fromStage]?.color }">
                  {{ LIFECYCLE_STAGES[t.fromStage]?.icon }}
                </span>
                <span class="evolution-arrow">➡️</span>
                <span class="evolution-to" :style="{ color: LIFECYCLE_STAGES[t.toStage]?.color }">
                  {{ LIFECYCLE_STAGES[t.toStage]?.icon }}
                </span>
              </span>
              <span class="transition-reason">{{ t.reason }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 底部 -->
      <div class="panel-footer">
        <div class="footer-left">
          <span class="update-time">⏱️ {{ formatTime(lastUpdate) }}</span>
          <span class="observation-badge">
            📡 观察中 {{ observationStats.total }}
          </span>
        </div>
        <div class="footer-right">
          <button class="btn-text" @click="showFullReport">📊 完整报告</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { dragonLifecycle, LIFECYCLE_STAGES } from '@/services/DragonLifecycle'
import { dataLayer } from '@/services/DataLayer'  // 导入 dataLayer
import { EventManager } from '@/utils/eventManager'
import { usePanel } from '@/composables/usePanel'

const props = defineProps<{
  visible: boolean
  triggerRect?: DOMRect
}>()

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'close'): void
}>()

// ========== 面板定位 ==========
const { panelRef, panelStyle } = usePanel({
  name: 'DragonLifecyclePanel',
  visible: props.visible,
  triggerRect: props.triggerRect,
  onClose: () => emit('close')
})

// ========== 数据 ==========
const loading = ref(false)
const lastUpdate = ref(Date.now())
const activeQueue = ref('primary')

// 基础数据
const baseStats = ref<any>({})
const observationStats = ref({ primary: 0, secondary: 0, cold: 0, total: 0 })
const stageDistribution = ref<Record<string, number>>({})
const ratingDistribution = ref<Record<string, number>>({})
const survivalCurve = ref<Array<{ day: number; rate: number }>>([])
const recentTransitions = ref<any[]>([])
const successionChains = ref<any[]>([])
const confirmedLeaders = ref<any[]>([])
const activeLeaders = ref<any[]>([])

// 队列数据
const primaryQueue = ref<any[]>([])
const secondaryQueue = ref<any[]>([])
const coldQueue = ref<any[]>([])

const curveCanvas = ref<HTMLCanvasElement>()
const leaderFilter = ref('all')

// ========== 从 dataLayer 获取增强数据 ==========
const getStockData = (code: string) => {
  return dataLayer.getStock(code) || {}
}

const getStockQuote = (code: string) => {
  return dataLayer.getQuote(code) || {}
}

// 增强后的龙头列表
const enhancedLeaders = computed(() => {
  return confirmedLeaders.value.map(leader => {
    const stockData = getStockData(leader.code)
    const quote = getStockQuote(leader.code)

    return {
      ...leader,
      ...stockData,
      ...quote,
      price: quote.price || stockData.price || leader.price,
      change: quote.change || stockData.change || leader.change,
      zlje: quote.zlje || stockData.zlje || leader.zlje,
      turnover: quote.turnover || stockData.turnover || leader.turnover,
    }
  })
})

// 增强后的主队列
const enhancedPrimaryQueue = computed(() => {
  return primaryQueue.value.map(item => {
    const stockData = getStockData(item.code)
    const quote = getStockQuote(item.code)
    return {
      ...item,
      ...stockData,
      ...quote,
      price: quote.price || stockData.price,
      change: quote.change || stockData.change,
      zlje: quote.zlje || stockData.zlje,
    }
  })
})

// 增强后的次队列
const enhancedSecondaryQueue = computed(() => {
  return secondaryQueue.value.map(item => {
    const stockData = getStockData(item.code)
    const quote = getStockQuote(item.code)
    return {
      ...item,
      ...stockData,
      ...quote,
      price: quote.price || stockData.price,
      change: quote.change || stockData.change,
      zlje: quote.zlje || stockData.zlje,
    }
  })
})

// 增强后的冷备队列
const enhancedColdQueue = computed(() => {
  return coldQueue.value.map(item => {
    const stockData = getStockData(item.code)
    const quote = getStockQuote(item.code)
    return {
      ...item,
      ...stockData,
      ...quote,
      price: quote.price || stockData.price,
      change: quote.change || stockData.change,
      zlje: quote.zlje || stockData.zlje,
    }
  })
})

// ========== 统计信息 ==========
const stats = computed(() => {
  const confirmed = enhancedLeaders.value
  const active = confirmed.filter(l => l.currentStage !== 'death')

  // 计算平均存活时间（天）
  let avgLifespan = 0
  if (active.length > 0) {
    const total = active.reduce((sum, l) => sum + (Date.now() - l.birthTime), 0)
    avgLifespan = total / active.length / (1000 * 60 * 60 * 24)
  }

  // 计算平均基因得分
  let avgGenesScore = 0
  if (confirmed.length > 0) {
    const total = confirmed.reduce((sum, l) => sum + (l.genetics?.totalScore || 0), 0)
    avgGenesScore = total / confirmed.length
  }

  return {
    totalTracked: confirmed.length,
    activeCount: active.length,
    averageLifespan: avgLifespan,
    averageGenesScore: avgGenesScore,
    confirmedCount: confirmed.length
  }
})

// 存活率
const survivalRate10 = computed(() => {
  const point = survivalCurve.value.find(p => p.day === 10)
  return point?.rate.toFixed(1) || '0'
})

// 筛选后的龙头
const filteredLeaders = computed(() => {
  if (!enhancedLeaders.value || enhancedLeaders.value.length === 0) {
    return []
  }

  let leaders = enhancedLeaders.value

  if (leaderFilter.value !== 'all') {
    leaders = leaders.filter(l =>
      l.genetics?.rating?.toLowerCase() === leaderFilter.value.toLowerCase()
    )
  }

  return leaders.slice(0, 20)
})

// 阶段信号
const stageSignals = ref({
  sprout: ['首次涨停', '放量突破'],
  seedling: ['二连板', '缩量加速'],
  growth: ['三连板', '带动板块'],
  maturity: ['五连板', '市场总龙头'],
  aging: ['高位放量', '跟风掉队'],
  decline: ['断板', '亏钱效应'],
  death: ['退出榜单']
})

// ========== 工具函数 ==========
const formatAmount = (val: number) => {
  if (!val) return '-'
  const absVal = Math.abs(val)
  if (absVal >= 100000000) return (val / 100000000).toFixed(2) + '亿'
  if (absVal >= 10000) return (val / 10000).toFixed(1) + '万'
  return val.toFixed(0)
}

// ========== 刷新方法 ==========
const refresh = () => {
  loading.value = true
  try {
    console.log('[DragonLifecyclePanel] 刷新数据...')

    // 获取基础数据
    baseStats.value = dragonLifecycle.getStats() || {}

    // 获取观察队列统计
    const obsStats = dragonLifecycle.getObservationStats()
    observationStats.value = {
      primary: obsStats?.primary || 0,
      secondary: obsStats?.secondary || 0,
      cold: obsStats?.cold || 0,
      total: obsStats?.total || 0
    }

    // 获取分布数据
    stageDistribution.value = dragonLifecycle.getStageDistribution() || {}
    ratingDistribution.value = dragonLifecycle.getRatingDistribution() || {}

    // 获取存活曲线
    survivalCurve.value = dragonLifecycle.getSurvivalCurve() || []

    // 获取最近变化
    recentTransitions.value = dragonLifecycle.getRecentTransitions() || []

    // 获取传承链
    successionChains.value = dragonLifecycle.getSuccessionChain() || []

    // 获取龙头列表
    confirmedLeaders.value = dragonLifecycle.getConfirmedLeaders() || []
    activeLeaders.value = dragonLifecycle.getActiveLeaders() || []

    // 获取观察队列详情
    refreshQueues()

    lastUpdate.value = Date.now()

    console.log('[DragonLifecyclePanel] 数据刷新完成', {
      已确认: confirmedLeaders.value.length,
      活跃: activeLeaders.value.length,
      观察队列: observationStats.value
    })

    // 绘制曲线
    nextTick(() => drawCurve())
  } catch (error) {
    console.error('[DragonLifecyclePanel] 刷新失败:', error)
  } finally {
    loading.value = false
  }
}

// 刷新队列数据
const refreshQueues = () => {
  try {
    const queues = dragonLifecycle.getObservationQueues()
    console.log('[DragonLifecyclePanel] 原始队列数据:', queues)

    primaryQueue.value = queues?.primary || []
    secondaryQueue.value = queues?.secondary || []
    coldQueue.value = queues?.cold || []

    console.log('[DragonLifecyclePanel] 处理后队列:', {
      primary: primaryQueue.value.length,
      secondary: secondaryQueue.value.length,
      cold: coldQueue.value.length
    })
  } catch (e) {
    console.warn('[DragonLifecyclePanel] 刷新队列失败', e)
    primaryQueue.value = []
    secondaryQueue.value = []
    coldQueue.value = []
  }
}

const close = () => {
  emit('close')
}

const selectLeader = (leader: any) => {
  EventManager.emit('dragon:show-detail', {
    code: leader.code,
    name: leader.name,
    genetics: leader.genetics
  })
}

const filterByStage = (stage: string) => {
  leaderFilter.value = 'all'
  EventManager.emit('dragon:filter-stage', { stage })
}

const showFullReport = () => {
  EventManager.emit('dragon:show-full-report', {
    stats: stats.value,
    successionChains: successionChains.value
  })
}

const getFamily = (code: string) => {
  return dragonLifecycle.getFamily(code) || { parents: [], children: [] }
}

const getLeaderNames = (codes: string[]): string => {
  return codes
    .map(c => dragonLifecycle.getLifecycle(c)?.name)
    .filter(Boolean)
    .join(', ')
}

// 格式化时间
const formatTime = (timestamp: number) => {
  if (!timestamp) return '--:--:--'
  const date = new Date(timestamp)
  return `${date.getHours().toString().padStart(2, '0')}:${date.getMinutes().toString().padStart(2, '0')}:${date.getSeconds().toString().padStart(2, '0')}`
}

const formatDuration = (stage: any) => {
  if (!stage || !stage.endTime) return '进行中'
  const hours = Math.round((stage.endTime - stage.startTime) / (1000 * 60 * 60))
  return `${hours}h`
}

const formatAge = (leader: any) => {
  if (!leader) return '0h'
  const now = Date.now()
  const end = leader.deathTime || now
  const hours = Math.round((end - leader.birthTime) / (1000 * 60 * 60))
  if (hours < 24) return `${hours}h`
  const days = Math.floor(hours / 24)
  const remainingHours = hours % 24
  return `${days}d${remainingHours}h`
}

const formatPrice = (price: number) => {
  if (!price) return '-'
  if (price > 100) return price.toFixed(0) + '元'
  if (price > 10) return price.toFixed(1) + '元'
  return price.toFixed(2) + '元'
}

const formatGap = (gap: number) => {
  const hours = Math.round(Math.abs(gap) / (1000 * 60 * 60))
  if (gap < 0) return `重叠${hours}h`
  if (hours === 0) return '无缝衔接'
  return `${hours}h后`
}

const getRatingColor = (rating: string): string => {
  const colors: Record<string, string> = {
    SSS: '#ffd700',
    SS: '#c0c0c0',
    S: '#cd7f32',
    A: '#4ade80',
    B: '#60a5fa',
    C: '#9ca3af'
  }
  return colors[rating] || '#9ca3af'
}

const getConfidenceColor = (confidence: number): string => {
  if (confidence >= 80) return '#4ade80'
  if (confidence >= 60) return '#fbbf24'
  return '#f87171'
}

// 绘制存活曲线
const drawCurve = async () => {
  await nextTick()
  if (!curveCanvas.value || !survivalCurve.value || survivalCurve.value.length === 0) return

  const ctx = curveCanvas.value.getContext('2d')
  if (!ctx) return

  const width = 400
  const height = 150
  const points = survivalCurve.value

  ctx.clearRect(0, 0, width, height)

  // 绘制网格
  ctx.strokeStyle = '#2a3342'
  ctx.lineWidth = 0.5
  ctx.beginPath()
  for (let i = 0; i <= 10; i++) {
    const x = i * 40
    ctx.moveTo(x, 0)
    ctx.lineTo(x, height)
  }
  for (let i = 0; i <= 5; i++) {
    const y = i * 30
    ctx.moveTo(0, y)
    ctx.lineTo(width, y)
  }
  ctx.stroke()

  // 绘制曲线
  ctx.beginPath()
  ctx.strokeStyle = '#ffd700'
  ctx.lineWidth = 2

  points.forEach((point, index) => {
    const x = index * 40
    const y = height - (point.rate / 100) * height

    if (index === 0) {
      ctx.moveTo(x, y)
    } else {
      ctx.lineTo(x, y)
    }
  })

  ctx.stroke()

  // 绘制点
  points.forEach((point, index) => {
    const x = index * 40
    const y = height - (point.rate / 100) * height

    ctx.beginPath()
    ctx.fillStyle = '#ffd700'
    ctx.arc(x, y, 3, 0, Math.PI * 2)
    ctx.fill()
    ctx.strokeStyle = '#000'
    ctx.lineWidth = 1
    ctx.stroke()
  })
}

// ========== 生命周期 ==========
onMounted(() => {
  console.log('[DragonLifecyclePanel] 挂载')
  refresh()

  // 监听生命周期更新
  const unsub = EventManager.on('dragon:lifecycle-updated', () => {
    console.log('[DragonLifecyclePanel] 收到更新事件')
    refresh()
  })

  // 监听数据合并事件
  const unsubMerged = EventManager.on(AppEvents.DATA.MERGED, () => {
    console.log('[DragonLifecyclePanel] 数据合并完成，刷新显示')
    refresh()
  })

  onUnmounted(() => {
    unsub()
    unsubMerged()
  })
})

watch(() => props.visible, (visible) => {
  if (visible) {
    refresh()
  }
})

// 调试输出
watch([confirmedLeaders, primaryQueue, secondaryQueue, coldQueue], () => {
  console.log('[DragonLifecyclePanel] 数据状态:', {
    已确认龙头: confirmedLeaders.value.length,
    主队列: primaryQueue.value.length,
    次队列: secondaryQueue.value.length,
    冷备: coldQueue.value.length
  })
}, { immediate: true })
</script>

<style scoped>
/* 添加实时数据样式 */
.queue-item-realtime {
  display: flex;
  gap: 8px;
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px dashed var(--border-color);
  font-size: 10px;
}

.realtime-price {
  color: #ffd700;
  font-weight: 600;
}

.realtime-change.up {
  color: #ff4757;
}

.realtime-change.down {
  color: #2ed573;
}

.realtime-zlje {
  color: #60a5fa;
}

.leader-realtime {
  display: flex;
  gap: 12px;
  margin: 6px 0;
  padding: 4px 8px;
  background: var(--bg-primary);
  border-radius: 6px;
  font-size: 11px;
}

.lifecycle-panel {
  position: fixed;
  width: 520px;
  max-width: 95vw;
  max-height: 85vh;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  box-shadow: var(--shadow-lg);
  z-index: 10010;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  backdrop-filter: blur(20px);
  animation: slideIn 0.2s ease;
  color: #e5e7eb;
}

/* 确保所有文本元素继承或单独设置亮色 */
.stat-label,
.stat-value,
.queue-label,
.queue-count,
.queue-desc,
.stage-name,
.stage-count,
.transition-time,
.transition-name,
.transition-reason,
.leader-code,
.leader-name,
.gene-value,
.potential-text,
.family-label,
.family-names,
.update-time,
.observation-badge,
.header-count,
.tab-btn,
.empty-state {
  color: #e5e7eb;
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

/* 头部 */
.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-color);
  background: linear-gradient(to right, var(--bg-header), var(--bg-primary));
}

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.panel-icon {
  font-size: 24px;
  filter: drop-shadow(0 0 8px #ffd700);
}

.panel-header h3 {
  margin: 0;
  font-size: 16px;
  background: linear-gradient(135deg, #ffd700, #ff8c00);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}

.version-badge {
  padding: 2px 8px;
  background: var(--tag-bg);
  border-radius: 12px;
  font-size: 10px;
  color: var(--text-secondary);
}

.header-actions {
  display: flex;
  gap: 4px;
}

.btn-icon {
  width: 32px;
  height: 32px;
  border: 1px solid var(--border-color);
  background: transparent;
  border-radius: 6px;
  color: var(--text-secondary);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
}

.btn-icon:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
  border-color: #ffd700;
}

.btn-icon.close:hover {
  background: rgba(255, 71, 87, 0.1);
  color: #ff4757;
  border-color: #ff4757;
}

/* 内容区域 */
.panel-content {
  flex: 1;
  padding: 16px;
  overflow-y: auto;
  max-height: calc(85vh - 120px);
}

/* 统计卡片 */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
  margin-bottom: 16px;
}

.stat-card {
  background: linear-gradient(145deg, var(--bg-secondary), var(--bg-primary));
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 12px 4px;
  text-align: center;
  box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
}

.stat-label {
  display: block;
  font-size: 11px;
  color: var(--text-tertiary);
  margin-bottom: 4px;
}

.stat-value {
  font-size: 20px;
  font-weight: 700;
  background: linear-gradient(135deg, #ffd700, #ffa502);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}

.lifecycle-panel,
.lifecycle-panel * {
  color: #e5e7eb;
}

/* 然后单独恢复需要特殊颜色的元素 */
.lifecycle-panel .stat-value,
.lifecycle-panel .leader-code,
.lifecycle-panel .gene-value,
.lifecycle-panel .queue-count,
.lifecycle-panel .stage-count,
.lifecycle-panel .rating-badge.rating-SSS {
  color: #ffd700;
}

/* 队列状态 */
.queue-status {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  margin-bottom: 16px;
}

.queue-item {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  padding: 10px;
  text-align: center;
  position: relative;
  overflow: hidden;
}

.queue-item::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 2px;
}

.queue-item.primary::before {
  background: linear-gradient(90deg, #ffd700, #ffa502);
}

.queue-item.secondary::before {
  background: linear-gradient(90deg, #c0c0c0, #e5e5e5);
}

.queue-item.cold::before {
  background: linear-gradient(90deg, #4ade80, #86efac);
}

.queue-label {
  display: block;
  font-size: 11px;
  color: var(--text-tertiary);
  margin-bottom: 4px;
}

.queue-count {
  font-size: 20px;
  font-weight: 700;
  color: var(--color-highlight);
  display: block;
}

.queue-desc {
  font-size: 9px;
  color: var(--text-tertiary);
}

/* 评级分布 */
.rating-grid {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.rating-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

.rating-badge {
  width: 40px;
  font-size: 12px;
  font-weight: 700;
  text-align: center;
}

.rating-item.rating-SSS .rating-badge {
  color: #ffd700;
  text-shadow: 0 0 5px #ffd700;
}

.rating-item.rating-SS .rating-badge {
  color: #c0c0c0;
  text-shadow: 0 0 5px #c0c0c0;
}

.rating-item.rating-S .rating-badge {
  color: #cd7f32;
  text-shadow: 0 0 5px #cd7f32;
}

.rating-bar-container {
  flex: 1;
  height: 8px;
  background: var(--bg-primary);
  border-radius: 4px;
  overflow: hidden;
}

.rating-bar {
  height: 100%;
  border-radius: 4px;
  transition: width 0.3s;
}

.rating-count {
  width: 40px;
  font-size: 11px;
  color: var(--text-secondary);
  text-align: right;
}

/* 阶段时间线 */
.stages-timeline {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.stage-item {
  cursor: pointer;
  padding: 8px;
  background: var(--bg-primary);
  border-radius: 8px;
  transition: all 0.2s;
}

.stage-item:hover {
  background: var(--bg-hover);
  transform: translateX(4px);
}

.stage-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.stage-icon {
  font-size: 16px;
}

.stage-name {
  flex: 1;
  font-size: 12px;
  font-weight: 500;
}

.stage-count {
  font-size: 12px;
  color: var(--color-highlight);
}

.stage-progress {
  margin-bottom: 4px;
}

.progress-track {
  height: 4px;
  background: var(--bg-secondary);
  border-radius: 2px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  border-radius: 2px;
  transition: width 0.3s;
}

.stage-signals {
  display: flex;
  gap: 4px;
}

.signal-tag {
  padding: 2px 6px;
  background: var(--tag-bg);
  border-radius: 10px;
  font-size: 9px;
  color: var(--text-tertiary);
}

/* 存活曲线 */
.curve-container {
  position: relative;
  height: 150px;
  margin: 10px 0;
}

.curve-container canvas {
  width: 100%;
  height: 100%;
  background: var(--bg-primary);
  border-radius: 8px;
}

.curve-markers {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  pointer-events: none;
}

.curve-marker {
  position: absolute;
  bottom: -20px;
  transform: translateX(-50%);
  text-align: center;
}

.marker-value {
  display: block;
  font-size: 9px;
  color: #ffd700;
  white-space: nowrap;
}

.marker-label {
  display: block;
  font-size: 8px;
  color: var(--text-tertiary);
  white-space: nowrap;
}

/* 龙头卡片 */
.leaders-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  max-height: 400px;
  overflow-y: auto;
}

.leader-card {
  background: linear-gradient(145deg, var(--bg-primary), var(--bg-secondary));
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 12px;
  cursor: pointer;
  transition: all 0.2s;
}

.leader-card:hover {
  border-color: #ffd700;
  transform: translateY(-2px);
  box-shadow: 0 8px 12px rgba(255, 215, 0, 0.1);
}

.leader-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.leader-title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.leader-code {
  font-family: monospace;
  color: #ffd700;
  font-size: 13px;
}

.leader-name {
  font-size: 14px;
  font-weight: 500;
}

.leader-rating {
  padding: 2px 8px;
  border-radius: 12px;
  font-size: 11px;
  font-weight: 700;
}

.leader-rating.rating-SSS {
  background: rgba(255, 215, 0, 0.2);
  color: #ffd700;
  border: 1px solid #ffd700;
}

.leader-rating.rating-SS {
  background: rgba(192, 192, 192, 0.2);
  color: #c0c0c0;
  border: 1px solid #c0c0c0;
}

.leader-rating.rating-S {
  background: rgba(205, 127, 50, 0.2);
  color: #cd7f32;
  border: 1px solid #cd7f32;
}

.leader-body {
  margin-bottom: 8px;
}

.leader-stage-indicator {
  display: flex;
  gap: 4px;
  margin-bottom: 8px;
}

.stage-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  box-shadow: 0 0 5px currentColor;
}

.leader-genes {
  display: flex;
  gap: 12px;
  margin-bottom: 8px;
}

.gene-item {
  display: flex;
  align-items: center;
  gap: 2px;
}

.gene-icon {
  font-size: 11px;
}

.gene-value {
  font-size: 10px;
  font-weight: 600;
  color: #ffd700;
}

.leader-stats {
  display: flex;
  gap: 16px;
  margin-bottom: 8px;
}

.leader-stats .stat {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.leader-stats .stat-label {
  font-size: 9px;
  color: var(--text-tertiary);
}

.leader-stats .stat-value {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.leader-potential {
  background: var(--bg-primary);
  border-radius: 6px;
  padding: 6px;
}

.potential-bar {
  height: 3px;
  background: var(--bg-secondary);
  border-radius: 2px;
  overflow: hidden;
  margin-bottom: 4px;
}

.potential-fill {
  height: 100%;
  border-radius: 2px;
  transition: width 0.3s;
}

.potential-text {
  font-size: 9px;
  color: var(--text-tertiary);
}

.leader-family {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed var(--border-color);
  font-size: 10px;
}

.family-row {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-bottom: 2px;
}

.family-label {
  color: var(--text-tertiary);
  min-width: 40px;
}

.family-names {
  color: #ffd700;
}

/* 传承链 */
.succession-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.succession-item {
  background: var(--bg-primary);
  border-radius: 8px;
  padding: 8px;
}

.succession-chain {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.chain-predecessor,
.chain-successor {
  font-size: 12px;
  font-weight: 500;
  padding: 2px 6px;
  border-radius: 10px;
}

.chain-predecessor.rating-SSS,
.chain-successor.rating-SSS {
  background: rgba(255, 215, 0, 0.1);
  color: #ffd700;
}

.chain-predecessor.rating-SS,
.chain-successor.rating-SS {
  background: rgba(192, 192, 192, 0.1);
  color: #c0c0c0;
}

.chain-arrow {
  color: var(--text-tertiary);
}

.chain-meta {
  display: flex;
  justify-content: space-between;
  font-size: 9px;
}

.chain-gap {
  padding: 2px 6px;
  background: var(--bg-secondary);
  border-radius: 10px;
}

.chain-gap.smooth {
  background: rgba(46, 213, 115, 0.2);
  color: #2ed573;
}

.chain-quality {
  padding: 2px 6px;
  border-radius: 10px;
}

.chain-quality.王者传承 {
  background: rgba(255, 215, 0, 0.2);
  color: #ffd700;
}

.chain-quality.优质传承 {
  background: rgba(192, 192, 192, 0.2);
  color: #c0c0c0;
}

/* 实时动态流 */
.transitions-stream {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 150px;
  overflow-y: auto;
}

.transition-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px;
  background: var(--bg-primary);
  border-radius: 6px;
  font-size: 11px;
  animation: fadeIn 0.3s;
}

@keyframes fadeIn {
  from {
    opacity: 0;
    transform: translateX(-10px);
  }

  to {
    opacity: 1;
    transform: translateX(0);
  }
}

.transition-time {
  color: var(--text-tertiary);
  min-width: 45px;
  font-size: 10px;
}

.transition-name {
  min-width: 70px;
  font-weight: 500;
}

.transition-evolution {
  display: flex;
  align-items: center;
  gap: 4px;
  min-width: 50px;
}

.evolution-from,
.evolution-to {
  font-size: 12px;
}

.evolution-arrow {
  color: var(--text-tertiary);
  font-size: 10px;
}

.transition-reason {
  flex: 1;
  color: var(--text-secondary);
  font-size: 10px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 头部标签页 */
.header-tabs {
  display: flex;
  gap: 4px;
}

.tab-btn {
  padding: 2px 8px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  color: var(--text-secondary);
  font-size: 10px;
  cursor: pointer;
  transition: all 0.2s;
}

.tab-btn:hover {
  background: var(--bg-hover);
  border-color: #ffd700;
}

.tab-btn.active {
  background: #ffd700;
  color: #000;
  border-color: #ffd700;
}

/* 底部 */
.panel-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-top: 1px solid var(--border-color);
  background: var(--bg-header);
  font-size: 11px;
}

.footer-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.update-time {
  color: var(--text-tertiary);
  font-family: monospace;
}

.observation-badge {
  padding: 2px 8px;
  background: var(--tag-bg);
  border-radius: 12px;
  color: var(--text-secondary);
}

.footer-right .btn-text {
  background: none;
  border: none;
  color: #ffd700;
  cursor: pointer;
  font-size: 11px;
  padding: 4px 8px;
  border-radius: 4px;
}

.footer-right .btn-text:hover {
  background: rgba(255, 215, 0, 0.1);
}

/* 空状态 */
.empty-state {
  padding: 30px;
  text-align: center;
  color: var(--text-tertiary);
  font-size: 13px;
}

/* 滚动条 */
.panel-content::-webkit-scrollbar,
.leaders-list::-webkit-scrollbar,
.transitions-stream::-webkit-scrollbar {
  width: 4px;
}

.panel-content::-webkit-scrollbar-track,
.leaders-list::-webkit-scrollbar-track,
.transitions-stream::-webkit-scrollbar-track {
  background: var(--scrollbar-track);
}

.panel-content::-webkit-scrollbar-thumb,
.leaders-list::-webkit-scrollbar-thumb,
.transitions-stream::-webkit-scrollbar-thumb {
  background: var(--scrollbar-thumb);
  border-radius: 2px;
}

.panel-content::-webkit-scrollbar-thumb:hover,
.leaders-list::-webkit-scrollbar-thumb:hover,
.transitions-stream::-webkit-scrollbar-thumb:hover {
  background: #ffd700;
}

/* 队列区域 */
.queue-section {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  margin-bottom: 16px;
  overflow: hidden;
}

.queue-tabs {
  display: flex;
  border-bottom: 1px solid var(--border-color);
}

.queue-tab {
  flex: 1;
  padding: 10px;
  background: transparent;
  border: none;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 12px;
  position: relative;
}

.queue-tab.active {
  color: #ffd700;
  background: var(--bg-hover);
}

.queue-tab.active::after {
  content: '';
  position: absolute;
  bottom: -1px;
  left: 0;
  right: 0;
  height: 2px;
  background: #ffd700;
}

.queue-badge {
  display: inline-block;
  padding: 2px 6px;
  background: var(--bg-primary);
  border-radius: 10px;
  font-size: 10px;
  margin-left: 4px;
  color: var(--text-primary);
}

.queue-detail {
  padding: 12px;
  max-height: 300px;
  overflow-y: auto;
}

.queue-item-detail {
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 10px;
  margin-bottom: 8px;
}

.queue-item-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.queue-item-code {
  font-family: monospace;
  color: #ffd700;
  font-size: 12px;
}

.queue-item-name {
  font-size: 13px;
  font-weight: 500;
  flex: 1;
}

.queue-item-rating {
  padding: 2px 6px;
  border-radius: 10px;
  font-size: 10px;
  font-weight: 600;
}

.queue-item-rating.rating-SSS {
  background: rgba(255, 215, 0, 0.2);
  color: #ffd700;
  border: 1px solid #ffd700;
}

.queue-item-rating.rating-SS {
  background: rgba(192, 192, 192, 0.2);
  color: #c0c0c0;
  border: 1px solid #c0c0c0;
}

.queue-item-rating.rating-S {
  background: rgba(205, 127, 50, 0.2);
  color: #cd7f32;
  border: 1px solid #cd7f32;
}

.queue-item-rating.rating-A {
  background: rgba(74, 222, 128, 0.2);
  color: #4ade80;
  border: 1px solid #4ade80;
}

.queue-item-genes {
  display: flex;
  gap: 12px;
  margin-bottom: 6px;
}

.gene {
  font-size: 11px;
  color: var(--text-secondary);
}

.queue-item-meta {
  display: flex;
  gap: 12px;
  font-size: 10px;
  color: var(--text-tertiary);
}

.meta-score {
  color: #ffd700;
}

.queue-empty {
  padding: 30px;
  text-align: center;
  color: var(--text-tertiary);
  font-size: 12px;
}

.loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 50px;
  color: var(--text-secondary);
}



/* 加载覆盖层 */
.loading-overlay {
  position: absolute;
  top: 60px;
  /* 头部高度 */
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.7);
  backdrop-filter: blur(4px);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  z-index: 10;
  border-radius: 0 0 16px 16px;
}

.loading-spinner {
  width: 40px;
  height: 40px;
  border: 3px solid var(--border-color);
  border-top-color: #ffd700;
  border-radius: 50%;
  animation: spin 1s linear infinite;
  margin-bottom: 12px;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

/* 刷新按钮旋转动画 */
.rotating {
  animation: spin 1s linear infinite;
}

/* 禁用状态的按钮 */
.btn-icon:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.content-blur {
  filter: blur(2px);
  opacity: 0.6;
  pointer-events: none;
}
</style>
