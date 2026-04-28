<!-- src/components/panels/algorithm/WeightsTab.vue -->
<template>
  <div class="weights-tab">
    <div class="tab-header">
      <h4>⚖️ 因子权重配置</h4>
      <div class="header-actions">
        <span class="total-weight" :class="{ 'weight-ok': Math.abs(totalWeight - 1) < 0.01 }">
          总和: {{ (totalWeight * 100).toFixed(0) }}%
        </span>
        <button class="btn-icon-small" @click="normalizeWeights" title="归一化权重">🔄 归一</button>
      </div>
    </div>

    <div class="weights-list">
      <div v-for="factor in sortedFactors" :key="factor.id" class="weight-item">
        <div class="factor-info">
          <span class="factor-name" :title="factor.description">
            {{ factor.name }}
            <span v-if="factor.unit" class="factor-unit">({{ factor.unit }})</span>
          </span>
          <span class="factor-category" :class="factor.category">
            {{ categoryNames[factor.category] || factor.category }}
          </span>
        </div>

        <div class="weight-control">
          <input
            type="range"
            class="weight-slider"
            :min="factor.min || 0"
            :max="factor.max || 0.5"
            :step="0.01"
            :value="getWeight(factor.id)"
            @input="updateWeight(factor.id, parseFloat(($event.target as HTMLInputElement).value))"
          />
          <div class="weight-value">
            <input
              type="number"
              class="weight-input"
              :min="factor.min || 0"
              :max="factor.max || 0.5"
              :step="0.01"
              :value="getWeight(factor.id)"
              @change="
                updateWeight(factor.id, parseFloat(($event.target as HTMLInputElement).value))
              "
            />
            <span class="weight-percent">{{ (getWeight(factor.id) * 100).toFixed(0) }}%</span>
          </div>
        </div>

        <div class="factor-preview">
          <div class="preview-bar">
            <div
              class="preview-fill"
              :style="{ width: getWeight(factor.id) * 100 + '%' }"
              :class="getLevelClass(getWeight(factor.id))"
            ></div>
          </div>
        </div>

        <div v-if="showAdvanced" class="factor-advanced">
          <label class="checkbox-label">
            <input
              type="checkbox"
              :checked="isFactorEnabled(factor.id)"
              @change="toggleFactor(factor.id, ($event.target as HTMLInputElement).checked)"
            />
            启用
          </label>
          <span class="range-hint">
            范围: {{ (factor.min || 0) * 100 }}%-{{ (factor.max || 50) * 100 }}%
          </span>
        </div>
      </div>
    </div>

    <div class="weights-tip">
      <span class="tip-icon">💡</span>
      <span class="tip-text">拖动滑块调整因子权重，总和应接近100%</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { FACTORS } from '@/config/factors'
import { algorithmManager } from '@/services/algorithm'

const props = defineProps<{
  algorithm: string
  weights: Record<string, number>
  thresholds: any
  showAdvanced: boolean
}>()

const emit = defineEmits<{
  (e: 'update-weights', weights: Record<string, number>): void
}>()

// 分类名称映射
const categoryNames: Record<string, string> = {
  market: '市场',
  money: '资金',
  fundamental: '基本面',
  technical: '技术',
  sector: '题材',
  macro: '宏观',
  rank: '排名',
  sentiment: '情绪',
}

// 获取因子权重
const getWeight = (factorId: string): number => {
  return props.weights[factorId] || 0
}

// 检查因子是否启用（权重 > 0）
const isFactorEnabled = (factorId: string): boolean => {
  return (props.weights[factorId] || 0) > 0
}

// 切换因子启用状态
const toggleFactor = (factorId: string, enabled: boolean) => {
  if (enabled) {
    // 启用时设置为推荐权重
    const factor = FACTORS[factorId]
    const recommended = getRecommendedWeight(factorId)
    updateWeight(factorId, recommended)
  } else {
    // 禁用时设置为0
    updateWeight(factorId, 0)
  }
}

// 获取推荐权重
const getRecommendedWeight = (factorId: string): number => {
  const recommendations: Record<string, number> = {
    compRank: 0.15,
    zlje: 0.12,
    turnoverRate: 0.08,
    change: 0.08,
    themeHeat: 0.1,
    themeMomentum: 0.08,
    breathPhase: 0.08,
    breathZtCount: 0.06,
  }
  return recommendations[factorId] || 0.05
}

// ========== 获取权重级别样式 ==========
const getLevelClass = (weight: number): string => {
  if (weight >= 0.2) return 'level-high'
  if (weight >= 0.1) return 'level-medium'
  return 'level-low'
}

// 更新权重
const updateWeight = (factorId: string, value: number) => {
  // 确保值在有效范围内
  const factor = FACTORS[factorId]
  const min = factor?.min || 0
  const max = factor?.max || 0.5
  const clampedValue = Math.min(max, Math.max(min, value))

  // 更新本地权重
  const newWeights = {
    ...props.weights,
    [factorId]: clampedValue,
  }

  emit('update-weights', newWeights)

  // 同步到算法管理器
  try {
    algorithmManager.updateFactorWeight(factorId, clampedValue)
  } catch (error) {
    console.warn(`[WeightsTab] 同步权重失败: ${factorId}`, error)
  }
}

// 计算总权重
const totalWeight = computed(() => {
  return Object.values(props.weights).reduce((sum, w) => sum + w, 0)
})

// 归一化权重
// ========== 归一化权重（一次到位） ==========
const normalizeWeights = () => {
  if (totalWeight.value === 0) return

  // 直接等比缩放到1
  const factor = 1 / totalWeight.value
  const newWeights: Record<string, number> = {}

  // 第一步：等比缩放
  Object.entries(props.weights).forEach(([id, weight]) => {
    newWeights[id] = weight * factor
  })

  // 第二步：检查是否超出范围，并记录超出情况
  const limits: Record<string, { min: number; max: number }> = {}
  const fixedWeights: Record<string, number> = {}
  let fixedSum = 0
  const adjustableIds: string[] = []

  Object.keys(newWeights).forEach((id) => {
    const min = FACTORS[id]?.min || 0
    const max = FACTORS[id]?.max || 0.5
    limits[id] = { min, max }

    if (newWeights[id] > max) {
      fixedWeights[id] = max
      fixedSum += max
    } else if (newWeights[id] < min) {
      fixedWeights[id] = min
      fixedSum += min
    } else {
      adjustableIds.push(id)
    }
  })

  // 第三步：如果没有需要调整的因子，直接返回
  if (adjustableIds.length === 0) {
    Object.keys(newWeights).forEach((id) => {
      newWeights[id] = Math.round(newWeights[id] * 10000) / 10000
    })
    emit('update-weights', newWeights)
    return
  }

  // 第四步：计算剩余可分配权重
  const remaining = 1 - fixedSum

  // 如果剩余权重为负（不可能），强制压缩
  if (remaining < 0) {
    const compressFactor = 1 / fixedSum
    Object.keys(fixedWeights).forEach((id) => {
      fixedWeights[id] *= compressFactor
    })
    emit('update-weights', fixedWeights)
    return
  }

  // 第五步：按原始比例分配剩余权重
  const adjustableTotal = adjustableIds.reduce((sum, id) => sum + newWeights[id], 0)

  adjustableIds.forEach((id) => {
    const ratio = newWeights[id] / adjustableTotal
    fixedWeights[id] = remaining * ratio
  })

  // 第六步：四舍五入到4位小数
  Object.keys(fixedWeights).forEach((id) => {
    fixedWeights[id] = Math.round(fixedWeights[id] * 10000) / 10000
  })

  // 第七步：最终检查总和，微调确保为1
  const finalSum = Object.values(fixedWeights).reduce((a, b) => a + b, 0)
  if (Math.abs(finalSum - 1) > 0.0001) {
    const diff = 1 - finalSum
    // 找到权重最大的可调整因子进行微调
    const sortedIds = adjustableIds.sort((a, b) => fixedWeights[b] - fixedWeights[a])
    if (sortedIds.length > 0) {
      fixedWeights[sortedIds[0]] += diff
      fixedWeights[sortedIds[0]] = Math.round(fixedWeights[sortedIds[0]] * 10000) / 10000
    }
  }

  emit('update-weights', fixedWeights)
}

// 排序后的因子列表
const sortedFactors = computed(() => {
  try {
    // 获取当前算法的因子权重
    const factorWeightsList = algorithmManager.getFactorWeights(props.algorithm) || []

    // 创建已启用因子的映射
    const enabledFactors = new Map(
      factorWeightsList.filter((f) => f.enabled !== false).map((f) => [f.id, f]),
    )

    // 过滤并排序因子
    return Object.entries(FACTORS)
      .filter(([id]) => enabledFactors.has(id))
      .map(([id, factor]) => {
        const config = enabledFactors.get(id)
        return {
          id,
          ...factor,
          currentWeight:
            props.weights[id] ||
            (typeof config?.weight === 'number' ? config.weight : config?.baseWeight || 0),
          min: config?.min || factor.min || 0,
          max: config?.max || factor.max || 0.5,
        }
      })
      .sort((a, b) => {
        // 按分类排序
        if (a.category !== b.category) {
          return (a.category || '').localeCompare(b.category || '')
        }
        // 同分类按权重降序
        return b.currentWeight - a.currentWeight
      })
  } catch (error) {
    console.error('[WeightsTab] 获取因子列表失败:', error)
    return []
  }
})
</script>

<style scoped>
.weights-tab {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.tab-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.tab-header h4 {
  margin: 0;
  font-size: 14px;
  color: var(--text-primary);
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.total-weight {
  font-size: 12px;
  padding: 4px 8px;
  background: var(--bg-secondary);
  border-radius: 12px;
  color: var(--text-secondary);
}

.total-weight.weight-ok {
  background: rgba(46, 213, 115, 0.2);
  color: #2ed573;
}

.btn-icon-small {
  width: 28px;
  height: 28px;
  border: 1px solid var(--border-color);
  background: transparent;
  border-radius: 6px;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 12px;
  transition: all 0.2s;
}

.btn-icon-small:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
  border-color: var(--color-highlight);
}

.weights-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  max-height: 400px;
  overflow-y: auto;
  padding-right: 4px;
}

.weight-item {
  background: var(--bg-secondary);
  border-radius: 8px;
  padding: 12px;
  border: 1px solid var(--border-color);
}

.factor-info {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.factor-name {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-primary);
  cursor: help;
}

.factor-unit {
  font-size: 10px;
  color: var(--text-tertiary);
  margin-left: 4px;
}

.factor-category {
  font-size: 10px;
  padding: 2px 6px;
  border-radius: 10px;
  background: var(--bg-primary);
}

.factor-category.market {
  color: #3498db;
}
.factor-category.money {
  color: #2ed573;
}
.factor-category.sector {
  color: #f39c12;
}
.factor-category.sentiment {
  color: #ff7f50;
}
.factor-category.technical {
  color: #9b59b6;
}

.weight-control {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
}

.weight-slider {
  flex: 1;
  height: 4px;
  -webkit-appearance: none;
  background: var(--border-color);
  border-radius: 2px;
  outline: none;
}

.weight-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: var(--color-highlight);
  cursor: pointer;
  transition: all 0.2s;
}

.weight-slider::-webkit-slider-thumb:hover {
  transform: scale(1.2);
}

.weight-value {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 100px;
}

.weight-input {
  width: 60px;
  padding: 4px 6px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  color: var(--text-primary);
  font-size: 12px;
  text-align: right;
}

.weight-percent {
  min-width: 40px;
  font-size: 12px;
  color: var(--text-secondary);
}

.factor-preview {
  margin-top: 4px;
}

.preview-bar {
  height: 4px;
  background: var(--border-color);
  border-radius: 2px;
  overflow: hidden;
}

.preview-fill {
  height: 100%;
  transition: width 0.2s;
}

.preview-fill.level-high {
  background: #2ed573;
}
.preview-fill.level-medium {
  background: #f39c12;
}
.preview-fill.level-low {
  background: #ff7f50;
}

.factor-advanced {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed var(--border-color);
  font-size: 11px;
  color: var(--text-tertiary);
}

.checkbox-label {
  display: flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
}

.range-hint {
  color: var(--text-tertiary);
}

.weights-tip {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: var(--bg-secondary);
  border-radius: 6px;
  font-size: 11px;
  color: var(--text-secondary);
  border: 1px solid var(--border-color);
}

.tip-icon {
  font-size: 14px;
}
</style>
