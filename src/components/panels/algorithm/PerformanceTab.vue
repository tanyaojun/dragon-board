<!-- src/components/panels/algorithm/PerformanceTab.vue 性能统计 -->
<template>
  <div class="performance-tab">
    <!-- 统计卡片 -->
    <div class="stats-grid">
      <div class="stat-card">
        <span class="stat-icon">📊</span>
        <div class="stat-content">
          <span class="stat-label">使用次数</span>
          <span class="stat-value">{{ currentStats.count || 0 }}</span>
        </div>
      </div>

      <div class="stat-card">
        <span class="stat-icon">⭐</span>
        <div class="stat-content">
          <span class="stat-label">平均得分</span>
          <span class="stat-value">{{ (currentStats.avgScore || 0).toFixed(1) }}</span>
        </div>
      </div>

      <div class="stat-card">
        <span class="stat-icon">✅</span>
        <div class="stat-content">
          <span class="stat-label">成功率</span>
          <span class="stat-value">{{ currentStats.successRate || '0%' }}</span>
        </div>
      </div>

      <div class="stat-card">
        <span class="stat-icon">🔢</span>
        <div class="stat-content">
          <span class="stat-label">因子数量</span>
          <span class="stat-value">{{ factorCount }}</span>
          <span v-if="sentimentFactorCount > 0" class="stat-badge"
            >🔥{{ sentimentFactorCount }}</span
          >
        </div>
      </div>
    </div>

    <!-- 评分趋势图表 -->
    <div class="trend-section">
      <div class="section-header">
        <span class="section-title">📈 评分趋势</span>
        <span class="section-subtitle">最近{{ performanceHistory.length }}次计算</span>
      </div>

      <div class="trend-chart">
        <div v-for="(item, index) in performanceHistory" :key="index" class="trend-bar-container">
          <div
            class="trend-bar"
            :style="{
              height: Math.max(30, (item.score || 30) * 0.8) + 'px',
              background: item.success
                ? 'linear-gradient(180deg, #2ed573, #7bed9f)'
                : 'linear-gradient(180deg, #ff4757, #ff6b81)',
            }"
            :title="`评分: ${item.score?.toFixed(1)}\n${new Date(item.timestamp).toLocaleTimeString()}`"
          >
            <span class="bar-score">{{ Math.round(item.score) }}</span>
          </div>
          <span class="bar-time">{{ formatTime(item.timestamp) }}</span>
        </div>
        <div v-if="performanceHistory.length === 0" class="no-data">暂无历史数据</div>
      </div>
    </div>

    <!-- 算法性能对比 -->
    <div class="compare-section">
      <div class="section-header">
        <span class="section-title">🔄 算法性能对比</span>
      </div>

      <div class="compare-list">
        <div
          v-for="[algoId, stat] in allStatsEntries"
          :key="algoId"
          class="compare-item"
          :class="{ current: algoId === algorithm }"
          @click="switchToAlgorithm(algoId)"
        >
          <div class="compare-header">
            <span class="algo-icon">{{ algorithmIcons[algoId] || '⚙️' }}</span>
            <span class="algo-name">{{ algorithmNames[algoId] || algoId }}</span>
            <span v-if="algoId === algorithm" class="current-badge">当前</span>
          </div>

          <div class="compare-stats">
            <div class="compare-stat">
              <span class="stat-label">次数</span>
              <span class="stat-number">{{ stat.count || 0 }}</span>
            </div>
            <div class="compare-stat">
              <span class="stat-label">平均分</span>
              <span class="stat-number">{{ (stat.avgScore || 0).toFixed(1) }}</span>
            </div>
            <div class="compare-stat">
              <span class="stat-label">成功率</span>
              <span class="stat-number" :style="{ color: getSuccessRateColor(stat.successRate) }">
                {{ stat.successRate || '0%' }}
              </span>
            </div>
          </div>

          <div class="compare-progress">
            <div
              class="progress-bar"
              :style="{
                width: stat.successRate ? stat.successRate : '0%',
                background: getSuccessRateColor(stat.successRate),
              }"
            ></div>
          </div>
        </div>
      </div>
    </div>

    <!-- 因子贡献分析 -->
    <div class="factors-section" v-if="topFactors.length > 0">
      <div class="section-header">
        <span class="section-title">🔍 因子贡献分析</span>
        <span class="section-subtitle">最近一次计算中贡献最大的因子</span>
      </div>

      <div class="factors-list">
        <div v-for="(factor, index) in topFactors" :key="factor.id" class="factor-item">
          <span class="factor-rank">{{ index + 1 }}</span>
          <span class="factor-name">{{ factor.name }}</span>
          <span class="factor-contribution">+{{ factor.contribution.toFixed(1) }}</span>
          <div class="factor-bar">
            <div
              class="factor-bar-fill"
              :style="{ width: (factor.contribution / 50) * 100 + '%' }"
            ></div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { algorithmManager } from '@/services/Algorithm'
import { EventManager } from '@/utils/eventManager'
import { AppEvents } from '@/types'

const props = defineProps<{
  algorithm: string
  weights: Record<string, number>
  thresholds: any
  showAdvanced: boolean
}>()

// 算法信息
const algorithmIcons: Record<string, string> = {
  balanced: '⚖️',
  dragonFirst: '👑',
  moneyDriven: '💰',
  sentimentDriven: '🔥',
  ml: '🤖',
}

const algorithmNames: Record<string, string> = {
  balanced: '平衡型',
  dragonFirst: '龙头优先',
  moneyDriven: '资金驱动',
  sentimentDriven: '情绪驱动',
  ml: '机器学习',
}

// 性能数据
const performanceHistory = ref<any[]>([])
const allStats = ref<Record<string, any>>({})
const currentStats = ref<any>({})
const topFactors = ref<any[]>([])

// 计算属性
const allStatsEntries = computed(() => {
  return Object.entries(allStats.value)
})

const factorCount = computed(() => {
  try {
    const weights = algorithmManager.getFactorWeights(props.algorithm)
    return weights.filter((f) => f.enabled !== false).length
  } catch {
    return 0
  }
})

const sentimentFactorCount = computed(() => {
  try {
    const weights = algorithmManager.getFactorWeights(props.algorithm)
    return weights.filter((f) => {
      const factor = FACTORS?.[f.id]
      return factor?.category === 'sentiment' && f.enabled !== false
    }).length
  } catch {
    return 0
  }
})

// 获取所有统计
const fetchStats = () => {
  try {
    // 获取性能统计
    const stats = algorithmManager.getPerformanceStats?.() || {}

    if (stats && typeof stats === 'object') {
      allStats.value = stats
      currentStats.value = stats[props.algorithm] || {
        count: 0,
        avgScore: 0,
        successRate: '0%',
      }
    }

    // 获取历史数据（如果有）
    const fullStatus = algorithmManager.getFullStatus?.()
    if (fullStatus?.performance?.history) {
      performanceHistory.value = fullStatus.performance.history.slice(-10)
    } else {
      performanceHistory.value = []
    }
  } catch (error) {
    console.error('[PerformanceTab] 获取统计失败:', error)
  }
}

// 获取最近一次计算的因子贡献
const fetchTopFactors = () => {
  try {
    // 尝试获取最近的计算结果
    const lastScore = (window as any).__LAST_SCORE__

    if (lastScore?.details) {
      topFactors.value = Object.entries(lastScore.details)
        .map(([id, detail]: [string, any]) => ({
          id,
          name: detail.name || id,
          contribution: detail.contribution || 0,
        }))
        .sort((a, b) => b.contribution - a.contribution)
        .slice(0, 5)
    } else {
      // 尝试计算一个测试股票
      const testStock = {
        code: '000001',
        name: '平安银行',
        price: 10.5,
        change: 2.5,
        turnover: 100000000,
        compRank: 15,
      }

      const result = algorithmManager.calculateScore(testStock)
      // 保存到window供后续使用
      ;(window as any).__LAST_SCORE__ = result

      if (result?.details) {
        topFactors.value = Object.entries(result.details)
          .map(([id, detail]: [string, any]) => ({
            id,
            name: detail.name || id,
            contribution: detail.contribution || 0,
          }))
          .sort((a, b) => b.contribution - a.contribution)
          .slice(0, 5)
      } else {
        topFactors.value = []
      }
    }
  } catch (error) {
    console.error('[PerformanceTab] 获取因子贡献失败:', error)
    topFactors.value = []
  }
}

// 格式化时间
const formatTime = (timestamp: number): string => {
  if (!timestamp) return ''
  const date = new Date(timestamp)
  return `${date.getHours().toString().padStart(2, '0')}:${date.getMinutes().toString().padStart(2, '0')}`
}

// 获取成功率颜色
const getSuccessRateColor = (rate: string): string => {
  if (!rate) return '#7f8c8d'
  const num = parseFloat(rate)
  if (num >= 70) return '#2ed573'
  if (num >= 50) return '#f39c12'
  return '#ff4757'
}

// 切换到算法
const switchToAlgorithm = (algoId: string) => {
  if (algoId === props.algorithm) return

  algorithmManager.setAlgorithm(algoId)

  EventManager.emit(AppEvents.UI.TOAST, {
    message: `已切换到 ${algorithmNames[algoId] || algoId}`,
    duration: 1500,
    type: 'success',
  })
}

// 事件处理
const handlePerformanceUpdate = () => {
  fetchStats()
}

onMounted(() => {
  fetchStats()
  fetchTopFactors()

  // 监听性能更新事件
  EventManager.on('algorithm:performance-updated', handlePerformanceUpdate)
})

onUnmounted(() => {
  EventManager.off('algorithm:performance-updated', handlePerformanceUpdate)
})
</script>

<style scoped>
.performance-tab {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
}

.stat-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px;
  background: var(--bg-secondary);
  border-radius: 8px;
  border: 1px solid var(--border-color);
}

.stat-icon {
  font-size: 24px;
}

.stat-content {
  flex: 1;
  display: flex;
  flex-direction: column;
}

.stat-label {
  font-size: 10px;
  color: var(--text-secondary);
}

.stat-value {
  font-size: 18px;
  font-weight: bold;
  color: var(--text-primary);
}

.stat-badge {
  position: absolute;
  top: -8px;
  right: -8px;
  font-size: 10px;
  background: #ff7f50;
  color: #000;
  padding: 2px 6px;
  border-radius: 10px;
}

.trend-section {
  padding: 16px;
  background: var(--bg-secondary);
  border-radius: 8px;
  border: 1px solid var(--border-color);
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.section-title {
  font-weight: bold;
  color: var(--text-primary);
  font-size: 13px;
}

.section-subtitle {
  font-size: 10px;
  color: var(--text-secondary);
}

.trend-chart {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  height: 100px;
  padding: 8px 0;
}

.trend-bar-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}

.trend-bar {
  width: 100%;
  min-width: 20px;
  border-radius: 4px 4px 0 0;
  position: relative;
  transition: height 0.3s;
}

.bar-score {
  position: absolute;
  top: -16px;
  left: 50%;
  transform: translateX(-50%);
  font-size: 9px;
  color: var(--text-secondary);
}

.bar-time {
  font-size: 8px;
  color: var(--text-secondary);
  transform: rotate(-45deg);
  white-space: nowrap;
}

.compare-section {
  padding: 16px;
  background: var(--bg-secondary);
  border-radius: 8px;
  border: 1px solid var(--border-color);
}

.compare-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.compare-item {
  padding: 12px;
  background: var(--bg-primary);
  border-radius: 8px;
  border: 2px solid transparent;
  cursor: pointer;
  transition: all 0.2s;
}

.compare-item:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
}

.compare-item.current {
  border-color: var(--color-highlight);
}

.compare-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.algo-icon {
  font-size: 16px;
}

.algo-name {
  font-weight: bold;
  color: var(--text-primary);
  font-size: 13px;
}

.current-badge {
  margin-left: auto;
  padding: 2px 8px;
  background: var(--color-highlight);
  color: #000;
  border-radius: 12px;
  font-size: 10px;
}

.compare-stats {
  display: flex;
  gap: 16px;
  margin-bottom: 8px;
}

.compare-stat {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.compare-stat .stat-label {
  font-size: 9px;
  color: var(--text-secondary);
}

.compare-stat .stat-number {
  font-size: 14px;
  font-weight: bold;
  color: var(--text-primary);
}

.compare-progress {
  height: 4px;
  background: var(--border-color);
  border-radius: 2px;
  overflow: hidden;
}

.progress-bar {
  height: 100%;
  transition: width 0.3s;
}

.factors-section {
  padding: 16px;
  background: var(--bg-secondary);
  border-radius: 8px;
  border: 1px solid var(--border-color);
}

.factors-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.factor-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: var(--bg-primary);
  border-radius: 6px;
}

.factor-rank {
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--color-highlight);
  color: #000;
  border-radius: 10px;
  font-size: 10px;
  font-weight: bold;
}

.factor-name {
  flex: 1;
  font-size: 12px;
  color: var(--text-primary);
}

.factor-contribution {
  font-size: 11px;
  font-weight: bold;
  color: var(--color-highlight);
  margin-right: 8px;
}

.factor-bar {
  width: 80px;
  height: 4px;
  background: var(--border-color);
  border-radius: 2px;
  overflow: hidden;
}

.factor-bar-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--color-highlight), #ff4757);
  transition: width 0.3s;
}

.no-data {
  width: 100%;
  text-align: center;
  padding: 40px;
  color: var(--text-secondary);
  font-size: 12px;
}
</style>
