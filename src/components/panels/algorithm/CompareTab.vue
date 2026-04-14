<!-- src/components/panels/algorithm/CompareTab.vue 算法对比-->
<template>
  <div class="compare-tab">
    <!-- 对比说明 -->
    <div class="info-section">
      <span class="info-icon">📊</span>
      <span class="info-text">对比不同算法的特点、因子构成和性能表现，点击可快速切换</span>
    </div>

    <!-- 算法对比列表 -->
    <div class="compare-grid">
      <div
        v-for="algo in algorithmList"
        :key="algo.id"
        class="compare-card"
        :class="{
          active: algo.id === currentAlgorithm,
          recommended: algo.id === 'balanced',
        }"
        @click="switchToAlgorithm(algo.id)"
      >
        <!-- 卡片头部 -->
        <div
          class="card-header"
          :style="{ background: `${algo.color}20`, borderLeftColor: algo.color }"
        >
          <div class="algo-icon" :style="{ color: algo.color }">{{ algo.icon }}</div>
          <div class="algo-info">
            <span class="algo-name">{{ algo.name }}</span>
            <span v-if="algo.id === currentAlgorithm" class="active-badge">当前</span>
            <span v-else-if="algo.id === 'balanced'" class="recommended-badge">推荐</span>
          </div>
        </div>

        <!-- 算法描述 -->
        <div class="card-desc">{{ algo.description }}</div>

        <!-- 因子统计 -->
        <div class="factor-stats">
          <div class="factor-count">
            <span class="count-number">{{ algo.factorCount }}</span>
            <span class="count-label">因子数</span>
          </div>
          <div class="factor-tags">
            <span
              v-for="cat in getTopCategories(algo)"
              :key="cat"
              class="factor-tag"
              :class="`tag-${cat}`"
            >
              {{ getCategoryIcon(cat) }} {{ getCategoryName(cat) }}
            </span>
          </div>
        </div>

        <!-- 性能指标（如果有数据） -->
        <div v-if="algoStats[algo.id]" class="performance-metrics">
          <div class="metric">
            <span class="metric-label">使用次数</span>
            <span class="metric-value">{{ algoStats[algo.id].count || 0 }}</span>
          </div>
          <div class="metric">
            <span class="metric-label">平均分</span>
            <span class="metric-value">{{ (algoStats[algo.id].avgScore || 0).toFixed(1) }}</span>
          </div>
          <div class="metric">
            <span class="metric-label">成功率</span>
            <span
              class="metric-value"
              :style="{ color: getSuccessRateColor(algoStats[algo.id].successRate) }"
            >
              {{ algoStats[algo.id].successRate || '0%' }}
            </span>
          </div>
        </div>

        <!-- 因子权重预览（简化版） -->
        <div class="weight-preview">
          <div v-for="(factor, index) in getTopFactors(algo)" :key="factor.id" class="weight-item">
            <span class="weight-name">{{ getFactorShortName(factor.id) }}</span>
            <span class="weight-bar">
              <span
                class="weight-bar-fill"
                :style="{
                  width: getFactorWeight(algo, factor.id) + '%',
                  background: algo.color,
                }"
              ></span>
            </span>
            <span class="weight-value">{{ getFactorWeight(algo, factor.id) }}%</span>
          </div>
        </div>

        <!-- 特性标签 -->
        <div class="feature-tags">
          <span v-if="algo.id === 'ml'" class="feature-tag adaptive">🔄 自适应</span>
          <span v-if="hasSentimentFactors(algo)" class="feature-tag sentiment">🔥 情绪因子</span>
          <span v-if="hasMoneyFactors(algo)" class="feature-tag money">💰 资金因子</span>
          <span v-if="algo.id === 'dragonFirst'" class="feature-tag leader">👑 龙头优先</span>
        </div>

        <!-- 切换按钮（悬浮效果） -->
        <div class="switch-overlay">
          <button class="switch-btn" :style="{ background: algo.color }">
            {{ algo.id === currentAlgorithm ? '当前算法' : '切换至此' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 详细对比表格（高级模式） -->
    <div v-if="showAdvanced" class="detail-table">
      <div class="table-header">
        <span class="header-item">算法</span>
        <span class="header-item">因子数</span>
        <span class="header-item">排名因子</span>
        <span class="header-item">资金因子</span>
        <span class="header-item">技术因子</span>
        <span class="header-item">板块因子</span>
        <span class="header-item">情绪因子</span>
        <span class="header-item">使用次数</span>
        <span class="header-item">成功率</span>
      </div>

      <div v-for="algo in algorithmList" :key="algo.id" class="table-row">
        <span class="row-item" :style="{ color: algo.color }">
          {{ algo.icon }} {{ algo.name }}
        </span>
        <span class="row-item">{{ algo.factorCount }}</span>
        <span class="row-item">{{ getCategoryCount(algo, 'market') }}</span>
        <span class="row-item">{{ getCategoryCount(algo, 'money') }}</span>
        <span class="row-item">{{ getCategoryCount(algo, 'technical') }}</span>
        <span class="row-item">{{ getCategoryCount(algo, 'sector') }}</span>
        <span class="row-item">{{ getCategoryCount(algo, 'sentiment') }}</span>
        <span class="row-item">{{ algoStats[algo.id]?.count || 0 }}</span>
        <span
          class="row-item"
          :style="{ color: getSuccessRateColor(algoStats[algo.id]?.successRate) }"
        >
          {{ algoStats[algo.id]?.successRate || '0%' }}
        </span>
      </div>
    </div>

    <!-- 切换高级模式按钮 -->
    <div class="advanced-toggle" @click="toggleAdvanced">
      <span>{{ showAdvanced ? '收起详细对比' : '展开详细对比' }}</span>
      <span class="toggle-icon">{{ showAdvanced ? '▲' : '▼' }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { EventManager } from '@/utils/eventManager'
import { AppEvents } from '@/types'
import { algorithmManager } from '@/services/Algorithm'
import { ALGORITHMS } from '@/config/algorithms'
import { FACTORS } from '@/config/factors'

const props = defineProps<{
  algorithm: string
  weights: Record<string, number>
  thresholds: any
  showAdvanced: boolean
}>()

const emit = defineEmits<{
  (e: 'update:showAdvanced', value: boolean): void
}>()

// 本地状态
const showAdvancedLocal = ref(props.showAdvanced)
const algoStats = ref<Record<string, any>>({})

// 算法列表
const algorithmList = computed(() => {
  return Object.entries(ALGORITHMS).map(([id, algo]) => ({
    id,
    name: algo.name,
    icon: algo.icon,
    description: algo.description,
    color: algo.color,
    factorCount: Object.keys(algo.factors).length,
    factors: algo.factors,
  }))
})

const currentAlgorithm = computed(() => props.algorithm)

// 切换高级模式
const toggleAdvanced = () => {
  showAdvancedLocal.value = !showAdvancedLocal.value
  emit('update:showAdvanced', showAdvancedLocal.value)
}

// 切换到算法
const switchToAlgorithm = (algoId: string) => {
  if (algoId === props.algorithm) return

  algorithmManager.setAlgorithm(algoId)

  EventManager.emit(AppEvents.UI.TOAST, {
    message: `✅ 已切换到 ${ALGORITHMS[algoId].name}`,
    duration: 1500,
    type: 'success',
  })
}

// 获取顶部因子
const getTopFactors = (algo: any) => {
  const factors = Object.entries(algo.factors)
    .filter(([_, config]: [string, any]) => config.enabled !== false)
    .map(([id, config]: [string, any]) => ({
      id,
      weight: config.weight === 'dynamic' ? config.baseWeight || 0.1 : config.weight,
    }))
    .sort((a, b) => b.weight - a.weight)
    .slice(0, 4)

  return factors
}

// 获取因子权重
const getFactorWeight = (algo: any, factorId: string): number => {
  const config = algo.factors[factorId]
  if (!config) return 0
  const weight = config.weight === 'dynamic' ? config.baseWeight || 0.1 : config.weight
  return Math.round(weight * 100)
}

// 获取因子简称
const getFactorShortName = (factorId: string): string => {
  const factor = FACTORS[factorId]
  if (!factor) return factorId.substring(0, 4)

  const name = factor.name
  if (name.length <= 4) return name
  if (name.includes('排名')) return '排名'
  if (name.includes('市值')) return '市值'
  if (name.includes('主力')) return '主力'
  if (name.includes('涨幅')) return '涨幅'
  if (name.includes('成交')) return '成交'
  if (name.includes('换手')) return '换手'
  if (name.includes('板块')) return '板块'
  if (name.includes('情绪')) return '情绪'
  return name.substring(0, 4)
}

// 获取顶部类别
const getTopCategories = (algo: any): string[] => {
  const categories = new Map<string, number>()

  Object.keys(algo.factors).forEach((factorId) => {
    const factor = FACTORS[factorId]
    if (factor) {
      const count = categories.get(factor.category) || 0
      categories.set(factor.category, count + 1)
    }
  })

  return Array.from(categories.entries())
    .sort((a, b) => b[1] - a[1])
    .slice(0, 2)
    .map(([cat]) => cat)
}

// 获取类别图标
const getCategoryIcon = (category: string): string => {
  const icons: Record<string, string> = {
    market: '🏆',
    fundamental: '💰',
    money: '💸',
    technical: '📈',
    sector: '📊',
    sentiment: '🔥',
  }
  return icons[category] || '📌'
}

// 获取类别名称
const getCategoryName = (category: string): string => {
  const names: Record<string, string> = {
    market: '排名',
    fundamental: '市值',
    money: '资金',
    technical: '技术',
    sector: '板块',
    sentiment: '情绪',
  }
  return names[category] || category
}

// 获取类别数量
const getCategoryCount = (algo: any, category: string): number => {
  let count = 0
  Object.keys(algo.factors).forEach((factorId) => {
    const factor = FACTORS[factorId]
    if (factor?.category === category) count++
  })
  return count
}

// 判断是否包含情绪因子
const hasSentimentFactors = (algo: any): boolean => {
  return Object.keys(algo.factors).some((factorId) => {
    const factor = FACTORS[factorId]
    return factor?.category === 'sentiment'
  })
}

// 判断是否包含资金因子
const hasMoneyFactors = (algo: any): boolean => {
  return Object.keys(algo.factors).some((factorId) => {
    const factor = FACTORS[factorId]
    return factor?.category === 'money'
  })
}

// 获取成功率颜色
const getSuccessRateColor = (rate: string): string => {
  if (!rate) return '#7f8c8d'
  const num = parseFloat(rate)
  if (num >= 70) return '#2ed573'
  if (num >= 50) return '#f39c12'
  return '#ff4757'
}

// 获取统计信息
const fetchStats = () => {
  try {
    const stats = algorithmManager.getPerformanceStats?.() || {}

    if (stats && typeof stats === 'object') {
      algoStats.value = stats
    }
  } catch (error) {
    console.error('[CompareTab] 获取统计失败:', error)
  }
}

onMounted(() => {
  fetchStats()
})
</script>

<style scoped>
.compare-tab {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.info-section {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px;
  background: var(--bg-secondary);
  border-radius: 8px;
  border-left: 4px solid var(--color-highlight);
}

.info-icon {
  font-size: 20px;
}

.info-text {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.5;
}

.compare-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 16px;
}

.compare-card {
  position: relative;
  padding: 16px;
  background: var(--bg-secondary);
  border-radius: 12px;
  border: 2px solid transparent;
  transition: all 0.3s;
  cursor: pointer;
  overflow: hidden;
}

.compare-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.3);
}

.compare-card.active {
  border-color: var(--color-highlight);
  box-shadow: 0 0 0 2px rgba(255, 127, 80, 0.2);
}

.compare-card.recommended {
  position: relative;
}

.compare-card.recommended::after {
  content: '🌟';
  position: absolute;
  top: 8px;
  right: 8px;
  font-size: 16px;
  opacity: 0.5;
}

.card-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px;
  margin: -16px -16px 12px -16px;
  border-left: 4px solid transparent;
  border-radius: 12px 12px 0 0;
}

.algo-icon {
  font-size: 24px;
}

.algo-info {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 8px;
}

.algo-name {
  font-weight: bold;
  font-size: 16px;
  color: var(--text-primary);
}

.active-badge {
  padding: 2px 8px;
  background: var(--color-highlight);
  color: #000;
  border-radius: 12px;
  font-size: 10px;
}

.recommended-badge {
  padding: 2px 8px;
  background: #f39c12;
  color: #000;
  border-radius: 12px;
  font-size: 10px;
}

.card-desc {
  font-size: 12px;
  color: var(--text-secondary);
  margin-bottom: 16px;
  line-height: 1.5;
  min-height: 36px;
}

.factor-stats {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}

.factor-count {
  display: flex;
  flex-direction: column;
  align-items: center;
  min-width: 50px;
  padding: 8px;
  background: var(--bg-primary);
  border-radius: 8px;
}

.count-number {
  font-size: 20px;
  font-weight: bold;
  color: var(--color-highlight);
}

.count-label {
  font-size: 10px;
  color: var(--text-secondary);
}

.factor-tags {
  flex: 1;
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}

.factor-tag {
  padding: 2px 8px;
  border-radius: 12px;
  font-size: 10px;
  background: var(--bg-primary);
}

.factor-tag.tag-market {
  color: #3498db;
}

.factor-tag.tag-money {
  color: #2ed573;
}

.factor-tag.tag-technical {
  color: #ffa502;
}

.factor-tag.tag-sector {
  color: #9b59b6;
}

.factor-tag.tag-sentiment {
  color: #ff7f50;
}

.performance-metrics {
  display: flex;
  gap: 12px;
  padding: 12px;
  background: var(--bg-primary);
  border-radius: 8px;
  margin-bottom: 16px;
}

.metric {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}

.metric-label {
  font-size: 9px;
  color: var(--text-secondary);
}

.metric-value {
  font-size: 14px;
  font-weight: bold;
  color: var(--text-primary);
}

.weight-preview {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 16px;
}

.weight-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
}

.weight-name {
  width: 40px;
  color: var(--text-secondary);
}

.weight-bar {
  flex: 1;
  height: 4px;
  background: var(--bg-primary);
  border-radius: 2px;
  overflow: hidden;
}

.weight-bar-fill {
  display: block;
  height: 100%;
  transition: width 0.3s;
}

.weight-value {
  width: 35px;
  text-align: right;
  color: var(--text-secondary);
  font-size: 10px;
}

.feature-tags {
  display: flex;
  gap: 4px;
  margin-bottom: 16px;
}

.feature-tag {
  padding: 2px 8px;
  border-radius: 12px;
  font-size: 10px;
  font-weight: bold;
}

.feature-tag.adaptive {
  background: #9b59b6;
  color: white;
}

.feature-tag.sentiment {
  background: #ff7f50;
  color: #000;
}

.feature-tag.money {
  background: #2ed573;
  color: #000;
}

.feature-tag.leader {
  background: #ffd700;
  color: #000;
}

.switch-overlay {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  padding: 16px;
  background: linear-gradient(to top, var(--bg-secondary), transparent);
  transform: translateY(100%);
  transition: transform 0.3s;
  pointer-events: none;
}

.compare-card:hover .switch-overlay {
  transform: translateY(0);
  pointer-events: auto;
}

.switch-btn {
  width: 100%;
  padding: 10px;
  border: none;
  border-radius: 6px;
  color: #000;
  font-weight: bold;
  font-size: 12px;
  cursor: pointer;
  transition: opacity 0.2s;
}

.switch-btn:hover {
  opacity: 0.9;
}

.detail-table {
  background: var(--bg-secondary);
  border-radius: 8px;
  overflow-x: auto;
  font-size: 11px;
}

.table-header {
  display: grid;
  grid-template-columns: 100px repeat(9, 1fr);
  gap: 8px;
  padding: 12px;
  background: var(--bg-header);
  font-weight: bold;
  color: var(--text-primary);
  border-bottom: 1px solid var(--border-color);
}

.table-row {
  display: grid;
  grid-template-columns: 100px repeat(9, 1fr);
  gap: 8px;
  padding: 10px 12px;
  border-bottom: 1px solid var(--border-color);
}

.table-row:last-child {
  border-bottom: none;
}

.header-item,
.row-item {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.row-item {
  color: var(--text-secondary);
}

.advanced-toggle {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 12px;
  background: var(--bg-secondary);
  border-radius: 8px;
  cursor: pointer;
  font-size: 12px;
  color: var(--color-highlight);
  transition: all 0.2s;
}

.advanced-toggle:hover {
  background: var(--bg-hover);
}

.toggle-icon {
  font-size: 12px;
}
</style>
