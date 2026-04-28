<!-- src/components/panels/AlgorithmPanel.vue -->

<template>
  <Teleport to="body">
    <div v-if="visible" class="algorithm-panel" :style="panelStyle" ref="panelRef">
      <!-- 头部 -->
      <div class="panel-header">
        <h3>
          <span>🧠 算法中心</span>
          <span class="version-badge">v3.1.0</span>
        </h3>
        <div class="panel-actions">
          <button
            class="btn-icon"
            @click.stop="refresh"
            :class="{ rotating: loading }"
            title="刷新"
          >
            <span>🔄</span>
          </button>
          <button class="btn-icon" @click.stop="toggleAdvanced" title="高级选项">⚙️</button>
          <button class="btn-icon" @click.stop="exportConfig" title="导出配置">📥</button>
          <button class="btn-icon" @click.stop="close" title="关闭">✕</button>
        </div>
      </div>

      <!-- 错误提示 -->
      <div v-if="loadError" class="error-banner">
        <span class="error-icon">⚠️</span>
        <span>{{ loadError }}</span>
        <button class="retry-btn" @click="loadData">重试</button>
      </div>

      <!-- 算法选择 -->
      <div class="algorithm-selector">
        <select
          v-model="safeCurrentAlgorithm"
          class="filter-select"
          @change="handleAlgorithmChange"
        >
          <option v-for="algo in algorithmList" :key="algo.id" :value="algo.id">
            {{ algo.icon }} {{ algo.name }}
            <span v-if="algo.isCustom" class="custom-badge">自定义</span>
          </option>
        </select>
        <button class="btn-primary" @click="applyAlgorithm" :disabled="applying">
          {{ applying ? '应用中...' : '应用' }}
        </button>
      </div>

      <!-- 统计信息 -->
      <div v-if="stats" class="stats-brief">
        <div class="stat-item">
          <span class="stat-label">因子数量</span>
          <span class="stat-value">{{ stats.factorCount }}</span>
        </div>
        <div class="stat-item">
          <span class="stat-label">总权重</span>
          <span class="stat-value" :class="{ 'weight-ok': isWeightNormalized }">
            {{ formattedTotalWeight }}
          </span>
        </div>
        <div class="stat-item">
          <span class="stat-label">最后更新</span>
          <span class="stat-value">{{ stats.lastUpdate }}</span>
        </div>
      </div>

      <!-- 标签栏 -->
      <div class="panel-tabs">
        <button
          v-for="tab in tabs"
          :key="tab.value"
          class="tab-btn"
          :class="{ active: activeTab === tab.value }"
          @click="activeTab = tab.value"
        >
          {{ tab.icon }} {{ tab.label }}
        </button>
      </div>

      <!-- 加载状态 -->
      <div v-if="isLoading" class="loading-overlay">
        <div class="loading-spinner" />
        <span>加载中...</span>
      </div>

      <!-- 内容区域 -->
      <div class="panel-content">
        <div v-if="loading" class="loading-state">
          <span class="loading-spinner">⚙️</span>
          <span>加载算法配置中...</span>
        </div>

        <template v-else>
          <!-- 权重配置 -->
          <div v-if="activeTab === 'weights'" class="weights-container">
            <div class="weights-header">
              <h4>⚖️ 因子权重配置</h4>
              <div class="header-actions">
                <button
                  class="btn-normalize"
                  @click="handleNormalize"
                  :disabled="loading"
                  :title="`当前总和: ${formattedTotalWeight}`"
                >
                  <span class="icon">🎯</span>
                  归一化
                </button>
                <button class="btn-edit-factors" @click="openFactorSelector">
                  <span class="icon">✏️</span>
                  <span>编辑因子</span>
                </button>
              </div>
            </div>
            <WeightsTab
              :algorithm="safeCurrentAlgorithm"
              :weights="localWeights"
              :thresholds="localThresholds"
              :show-advanced="showAdvanced"
              @update-weights="updateWeights"
            />
          </div>

          <!-- 阈值配置 -->
          <ThresholdsTab
            v-else-if="activeTab === 'thresholds'"
            :algorithm="safeCurrentAlgorithm"
            :weights="localWeights"
            :thresholds="localThresholds"
            :show-advanced="showAdvanced"
            @update-thresholds="updateThresholds"
          />

          <!-- 性能统计 -->
          <PerformanceTab
            v-else-if="activeTab === 'performance'"
            :algorithm="safeCurrentAlgorithm"
            :weights="localWeights"
            :thresholds="localThresholds"
            :show-advanced="showAdvanced"
          />

          <!-- 算法对比 -->
          <CompareTab
            v-else-if="activeTab === 'compare'"
            :algorithm="safeCurrentAlgorithm"
            :weights="localWeights"
            :thresholds="localThresholds"
            :show-advanced="showAdvanced"
          />
        </template>
      </div>

      <!-- 底部按钮 -->
      <div class="panel-footer">
        <button class="btn-text" @click="resetWeights" :disabled="loading">重置权重</button>
        <button class="btn-text" @click="resetThresholds" :disabled="loading">重置阈值</button>
        <button class="btn-text" @click="exportConfig" :disabled="loading">导出配置</button>
        <button class="btn-text btn-apply" @click="applyAlgorithm" :disabled="loading || applying">
          {{ applying ? '应用中...' : '应用修改' }}
        </button>
      </div>
    </div>

    <!-- 因子选择器弹窗 -->
    <FactorSelector
      v-if="showFactorSelector"
      :algorithm-id="currentAlgorithm"
      :available-factors="availableFactors"
      :current-factors="currentFactorConfigs"
      @apply="handleFactorConfig"
      @cancel="showFactorSelector = false"
    />
  </Teleport>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { EventManager } from '@/utils/eventManager'
import { AppEvents } from '@/types'

import { algorithmManager } from '@/services/algorithm'
import { algorithmConfigManager } from '@/services/algorithm/AlgorithmConfigManager'

import WeightsTab from './algorithm/WeightsTab.vue'
import ThresholdsTab from './algorithm/ThresholdsTab.vue'
import PerformanceTab from './algorithm/PerformanceTab.vue'
import CompareTab from './algorithm/CompareTab.vue'
import FactorSelector from './algorithm/FactorSelector.vue'

// ========== 使用组合式函数 ==========
import { usePanel } from '@/composables/usePanel'
import { usePanelData } from '@/composables/usePanelData'

interface Factor {
  id: string
  name: string
  type: string
  category: string
  weight?: number
  enabled?: boolean
  min?: number
  max?: number
  baseWeight?: number
}

interface FactorConfig {
  weight: number
  enabled: boolean
  min: number
  max: number
}

const props = defineProps<{
  visible: boolean
  triggerRect?: DOMRect
}>()

const updateTimeout = ref<ReturnType<typeof setTimeout> | null>(null)
const batchUpdateTimer = ref<ReturnType<typeof setTimeout> | null>(null)
const refreshTimer = ref<ReturnType<typeof setInterval> | null>(null)

// 添加加载状态
const isLoading = ref(false)
const loadError = ref<string | null>(null)

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'close'): void
}>()

// ========== 先定义 close 函数 ==========
function close() {
  emit('update:visible', false)
  emit('close')
  EventManager.emit(AppEvents.UI.PANEL_CLOSE, { panel: 'algorithm' })
}

// ========== 再使用 usePanel ==========
const { panelRef, panelStyle } = usePanel({
  name: 'AlgorithmPanel',
  visible: props.visible,
  triggerRect: props.triggerRect,
  triggerSelectors: ['[title*="算法中心"]', '.algorithm-core-btn', '.nav-center button'],
  onClose: close,
})

// ========== 状态 ==========
const activeTab = ref('weights')
const showAdvanced = ref(false)
const showFactorSelector = ref(false)
const applying = ref(false)

// ========== 事件订阅清理 ==========
const unsubscribers: (() => void)[] = []

// ========== 使用 usePanelData 处理数据加载 ==========
const {
  data,
  loading,
  error,
  loadData: loadPanelData,
  showToast,
} = usePanelData({
  name: 'AlgorithmPanel',

  fetchData: async () => {
    // 获取算法列表
    const algorithms = algorithmConfigManager.getAlgorithmList?.() || []
    const algorithmList = algorithms.map((a) => ({
      id: a.id,
      name: a.name,
      icon: a.icon,
      isCustom: a.isCustom,
    }))

    // 获取当前算法
    const current = algorithmManager.getCurrentAlgorithm?.() || { id: 'balanced' }
    const currentAlgorithm = current.id // 直接返回字符串，不是 ref

    // 直接从算法管理器获取因子权重
    const factorWeights = algorithmManager.getFactorWeights?.() || []
    const localWeights: Record<string, number> = {}
    factorWeights.forEach((f: any) => {
      if (f.weight > 0) {
        localWeights[f.id] = f.weight
      }
    })

    // 获取算法详情中的因子配置（用于因子选择器）
    const algorithmDetail = algorithmConfigManager.getAlgorithmDetail?.(current.id)
    // 使用普通对象，不是 ref
    const currentFactorConfigs: Record<string, FactorConfig> = {}

    if (algorithmDetail) {
      algorithmDetail.factors.forEach((f: any) => {
        currentFactorConfigs[f.id] = {
          weight: f.weight,
          enabled: f.enabled,
          min: f.min,
          max: f.max,
        }
      })
    }

    const fetchedThresholds = algorithmManager.getThresholds?.() || {
      totalLeader: 80,
      sectorLeader: 65,
      continuousLeader: 70,
      middleLeader: 60,
      emotionLeader: 55,
    }

    // 获取可用因子列表
    const availableFactors = (algorithmConfigManager.getAvailableFactors?.() || []).map((f) => ({
      id: f.id,
      name: f.name,
      type: f.type,
      category: f.category,
    }))

    // 更新统计
    const factorCount = Object.keys(localWeights).length
    const totalWeight = Object.values(localWeights).reduce((a: number, b: number) => a + b, 0)
    const stats = {
      factorCount,
      totalWeight,
      lastUpdate: new Date().toLocaleTimeString(),
    }

    return {
      algorithmList,
      currentAlgorithm: current.id, // 字符串
      localWeights, // 普通对象
      localThresholds: fetchedThresholds,
      availableFactors, // 数组
      currentFactorConfigs, // 普通对象，不是 ref
      stats, // 普通对象
    }
  },
})
// ========== 从 data 中提取响应式数据 ==========
const algorithmList = ref<any[]>([])
const currentAlgorithm = ref('balanced')
const localWeights = ref<Record<string, number>>({})
const localThresholds = ref<Record<string, number>>({})
const defaultThresholds: Record<string, number> = {
  totalLeader: 80,
  sectorLeader: 65,
  continuousLeader: 70,
  middleLeader: 60,
  emotionLeader: 55,
}
const availableFactors = ref<any[]>([])
const currentFactorConfigs = ref<Record<string, FactorConfig>>({})
const stats = ref<{ factorCount: number; totalWeight: number; lastUpdate: string }>({
  factorCount: 0,
  totalWeight: 0,
  lastUpdate: '-',
})
watch(
  data,
  (newData) => {
    if (!newData) return

    // 使用 ref 的 value 赋值，并添加空值保护
    if (newData.algorithmList) algorithmList.value = newData.algorithmList
    if (newData.currentAlgorithm) currentAlgorithm.value = newData.currentAlgorithm
    if (newData.localWeights) localWeights.value = { ...newData.localWeights }
    if (newData.localThresholds) localThresholds.value = { ...newData.localThresholds }
    if (newData.availableFactors) availableFactors.value = [...newData.availableFactors]
    if (newData.currentFactorConfigs)
      currentFactorConfigs.value = { ...newData.currentFactorConfigs }
    if (newData.stats) stats.value = { ...newData.stats }

    // ✅ 确保 currentAlgorithm 始终有值
    if (!currentAlgorithm.value && newData.algorithmList?.[0]) {
      currentAlgorithm.value = newData.algorithmList[0].id
    }
  },
  { immediate: true, deep: true },
)

const safeCurrentAlgorithm = computed(() => {
  return currentAlgorithm.value || 'balanced'
})

// ========== 应用算法 ==========
const applyAlgorithm = async () => {
  applying.value = true
  try {
    const success = algorithmManager.setAlgorithm?.(safeCurrentAlgorithm.value)
    if (success) {
      const algoName = algorithmList.value.find((a) => a.id === safeCurrentAlgorithm.value)?.name
      showToast(`✅ 已切换到 ${algoName}`, 'success')

      // 获取新算法的默认权重
      const newWeights = getDefaultWeights(safeCurrentAlgorithm.value)
      localWeights.value = newWeights

      // 更新统计
      if (stats.value) {
        stats.value = {
          ...stats.value,
          factorCount: Object.keys(newWeights).length,
          totalWeight: Object.values(newWeights).reduce((a, b) => a + b, 0),
          lastUpdate: new Date().toLocaleTimeString(),
        }
      }
    }
  } catch (error) {
    showToast('❌ 算法切换失败', 'error')
  } finally {
    applying.value = false
  }
}

// ========== 算法切换 ==========
const handleAlgorithmChange = () => {
  const newAlgorithmId = safeCurrentAlgorithm.value

  // 调用管理器切换算法
  algorithmManager.setAlgorithm?.(newAlgorithmId)

  // 直接从 manager 获取最新的权重
  const newWeights = algorithmManager.getFactorWeights?.() || []
  const weightsObj: Record<string, number> = {}
  newWeights.forEach((f: any) => {
    if (f.weight > 0) {
      weightsObj[f.id] = f.weight
    }
  })

  // 更新本地显示
  localWeights.value = weightsObj

  // 更新统计信息
  if (stats.value) {
    stats.value = {
      ...stats.value,
      factorCount: Object.keys(weightsObj).length,
      totalWeight: Object.values(weightsObj).reduce((a, b) => a + b, 0),
      lastUpdate: new Date().toLocaleTimeString(),
    }
  }
}

// 获取算法的默认权重
function getDefaultWeights(algorithmId: string): Record<string, number> {
  const factorWeights = algorithmManager.getFactorWeights?.(algorithmId) || []
  const weights: Record<string, number> = {}
  factorWeights.forEach((f: any) => {
    if (f.weight > 0) {
      weights[f.id] = f.weight
    }
  })
  return weights
}

// ========== 权重管理 ==========
const updateWeights = (weights: Record<string, number>) => {
  if (updateTimeout.value) {
    clearTimeout(updateTimeout.value)
  }

  Object.entries(weights).forEach(([factorId, weight]) => {
    algorithmManager.updateFactorWeight?.(factorId, weight)
  })
}
// ========== 阈值管理 ==========
const updateThresholds = (thresholds: any) => {
  localThresholds.value = thresholds
  Object.entries(thresholds).forEach(([key, value]) => {
    algorithmManager.updateThreshold?.(key, value as number)
  })
}

const handleNormalize = async () => {
  if (loading.value) return

  try {
    const currentTotal = stats.value?.totalWeight || 0
    if (Math.abs(currentTotal - 1) < 0.01) {
      showToast('✓ 权重已经是100%', 'success')
      return
    }

    // 直接从当前权重计算归一化值
    const weights = { ...localWeights.value }
    const total = Object.values(weights).reduce((a, b) => a + b, 0)
    const factor = 1 / total

    // 更新每个权重
    Object.keys(weights).forEach((key) => {
      weights[key] = weights[key] * factor
    })

    // 调用管理器的更新方法
    let success = false
    Object.entries(weights).forEach(([factorId, weight]) => {
      const updated = algorithmManager.updateFactorWeight?.(factorId, weight)
      if (updated) success = true
    })

    if (success) {
      // ✅ 立即更新本地统计信息
      if (stats.value) {
        stats.value.totalWeight = 1
        stats.value.lastUpdate = new Date().toLocaleTimeString()
      }
      // ✅ 更新本地权重显示
      localWeights.value = weights

      showToast('✅ 权重已归一化到100%', 'success')
      // 不需要调用 loadData，因为已经更新了本地状态
    } else {
      showToast('⚠️ 归一化失败', 'info')
    }
  } catch (error) {
    console.error('[AlgorithmPanel] 归一化失败:', error)
    showToast('❌ 归一化失败', 'error')
  }
}

// ========== 重置功能 ==========
const resetWeights = () => {
  if (confirm('确定要重置当前算法的权重吗？')) {
    algorithmManager.resetWeights?.()
    showToast('🔄 权重已重置', 'info')
  }
}

const resetThresholds = () => {
  if (confirm('确定要重置所有阈值吗？')) {
    Object.entries(defaultThresholds).forEach(([key, value]) => {
      algorithmManager.updateThreshold?.(key, Number(value))
    })
    localThresholds.value = { ...defaultThresholds }
    showToast('🔄 阈值已重置', 'info')
  }
}

// ========== 导出配置 ==========
const exportConfig = () => {
  try {
    const config = algorithmConfigManager.exportConfig?.()
    const blob = new Blob([JSON.stringify(config, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `algorithm_config_${new Date().toISOString().slice(0, 10)}.json`
    a.click()
    URL.revokeObjectURL(url)
    showToast('📥 配置已导出', 'success')
  } catch (error) {
    showToast('❌ 导出失败', 'error')
  }
}

// ========== UI 操作 ==========
const toggleAdvanced = () => {
  showAdvanced.value = !showAdvanced.value
}

const refresh = async () => {
  try {
    await loadData()
    showToast('🔄 数据已刷新', 'info')
  } catch (error) {
    showToast('❌ 刷新失败', 'error')
  }
}

const loadData = async () => {
  if (isLoading.value) return

  isLoading.value = true
  loadError.value = null

  try {
    await loadPanelData()
  } catch (error) {
    loadError.value = '加载失败，请重试'
    showToast('❌ 加载失败', 'error')
  } finally {
    isLoading.value = false
  }
}

// ========== 因子选择器 ==========
const openFactorSelector = () => {
  showFactorSelector.value = true
}

const handleFactorConfig = (config: any) => {
  showFactorSelector.value = false

  if (currentAlgorithm.value.startsWith('custom_')) {
    try {
      algorithmConfigManager.updateCustomAlgorithm?.(currentAlgorithm.value, {
        factors: config.factors,
      })
      showToast('✅ 自定义算法已更新', 'success')
    } catch (error) {
      showToast('❌ 更新失败', 'error')
    }
  }
  loadData()
}

// 标签配置
const tabs = [
  { value: 'weights', icon: '⚖️', label: '权重配置' },
  { value: 'thresholds', icon: '🎯', label: '阈值配置' },
  { value: 'performance', icon: '📊', label: '性能统计' },
  { value: 'compare', icon: '📈', label: '算法对比' },
]

// 格式化总权重
const formattedTotalWeight = computed(() => {
  const total = stats.value?.totalWeight || 0
  return `${(total * 100).toFixed(0)}%`
})

// 权重是否归一化
const isWeightNormalized = computed(() => {
  const total = stats.value?.totalWeight || 0
  return Math.abs(total - 1) < 0.01
})

// ========== 生命周期 ==========
onMounted(() => {
  unsubscribers.push(
    // 初始化事件
    EventManager.on('algorithm:initialized', () => {
      loadData()
    }),

    // ✅ 保存事件 - 只更新统计，不重新加载
    EventManager.on('algorithm:config-saved', (data: any) => {
      if (stats.value) {
        stats.value.lastUpdate = new Date().toLocaleTimeString()
      }
    }),

    // ✅ 批量更新事件 - 重新加载（从管理器获取最新数据）
    EventManager.on('algorithm:batch-updated', (data: any) => {
      loadData()
    }),

    // ✅ 配置变更事件 - 重新加载
    EventManager.on('algorithm:config-changed', () => {
      loadData()
    }),
  )
})

onUnmounted(() => {
  // 清理事件监听
  unsubscribers.forEach((fn) => {
    try {
      fn()
    } catch (e) {
      console.warn('[AlgorithmPanel] 清理事件监听失败:', e)
    }
  })
  unsubscribers.length = 0

  // 清理定时器
  if (refreshTimer.value) {
    clearInterval(refreshTimer.value)
    refreshTimer.value = null
  }

  // 清理防抖定时器
  if (batchUpdateTimer.value) {
    clearTimeout(batchUpdateTimer.value)
    batchUpdateTimer.value = null
  }
})

// ✅ 打开面板时不主动加载，依赖事件
let visibleTimeout: ReturnType<typeof setTimeout> | null = null

watch(
  () => props.visible,
  (newVal) => {
    if (visibleTimeout) {
      clearTimeout(visibleTimeout)
    }

    if (newVal) {
      visibleTimeout = setTimeout(() => {
        if (algorithmManager.getStatus?.().initialized) {
          loadData()
        }
        visibleTimeout = null
      }, 100) // 100ms 防抖
    }
  },
)
</script>

<style scoped>
.algorithm-panel {
  position: fixed;
  width: 580px;
  max-width: calc(100vw - 40px);
  max-height: 80vh;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
  z-index: 10004;
  font-size: 12px;
  backdrop-filter: blur(10px);
}

.custom-badge {
  font-size: 10px;
  background: var(--color-highlight);
  color: #000;
  padding: 2px 6px;
  border-radius: 10px;
  margin-left: 8px;
}

.weights-container {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.weights-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  background: var(--bg-secondary);
  border-radius: 8px;
  border: 1px solid var(--border-color);
}

.weights-header h4 {
  margin: 0;
  font-size: 13px;
  color: var(--text-primary);
}

.btn-edit-factors {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  background: var(--color-highlight);
  border: none;
  border-radius: 6px;
  color: #000;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: opacity 0.2s;
}

.btn-edit-factors:hover {
  opacity: 0.9;
}

.btn-edit-factors .icon {
  font-size: 14px;
}

.algorithm-panel {
  position: fixed;
  width: 580px;
  max-width: calc(100vw - 40px);
  max-height: 80vh;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
  z-index: 10004;
  font-size: 12px;
  backdrop-filter: blur(10px);
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-header);
}

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

.panel-actions {
  display: flex;
  gap: 8px;
}

.btn-icon {
  width: 32px;
  height: 32px;
  border: 1px solid var(--border-color);
  background: transparent;
  border-radius: 8px;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 16px;
  transition: all 0.2s;
}

.btn-icon:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
  border-color: var(--color-highlight);
}

.btn-icon.loading {
  animation: pulse 1s infinite;
}

.algorithm-selector {
  display: flex;
  gap: 8px;
  padding: 12px 20px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-secondary);
}

.filter-select {
  flex: 1;
  padding: 8px 12px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 20px;
  color: var(--text-primary);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.filter-select:hover {
  border-color: var(--color-highlight);
  box-shadow: 0 0 10px rgba(255, 215, 0, 0.2);
}

.filter-select option {
  background: var(--bg-primary);
  color: var(--text-primary);
  padding: 8px;
}

.btn-primary {
  padding: 8px 20px;
  background: linear-gradient(135deg, var(--color-highlight) 0%, #ff9f7f 100%);
  border: none;
  border-radius: 20px;
  color: #000;
  font-weight: bold;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s;
  box-shadow: 0 2px 8px rgba(255, 215, 0, 0.3);
}

.btn-primary:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(255, 215, 0, 0.4);
}

.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  box-shadow: none;
}

.btn-primary:hover:not(:disabled) {
  opacity: 0.9;
}

.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.stats-brief {
  display: flex;
  justify-content: space-around;
  align-items: center;
  padding: 12px 20px;
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border-color);
  font-size: 13px;
  font-weight: 500;
  gap: 20px;
}

.stat-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 12px;
  border-radius: 20px;
  background: var(--bg-primary);
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
}

.stat-label {
  color: var(--text-tertiary);
  font-size: 11px;
  font-weight: 400;
  letter-spacing: 0.3px;
}

.stat-value {
  font-weight: 600;
  font-size: 16px;
}

/* 因子数量 - 金色 */
.stat-item:first-child::before {
  content: '📊'; /* 统计图表 */
  font-size: 16px;
  opacity: 0.9;
  margin-right: 4px;
}

/* 总权重 - 绿色 */
.stat-item:nth-child(2)::before {
  content: '⚖️'; /* 天平 */
  font-size: 16px;
  opacity: 0.9;
  margin-right: 4px;
}

.stat-value.weight-ok {
  color: #2ed573 !important;
  position: relative;
}

.stat-value.weight-ok::after {
  content: ' ✓';
  font-size: 14px;
  font-weight: bold;
}

.stat-value:not(.weight-ok) {
  color: #faf7f7 !important;
}

/* 最后更新 - 蓝色 */
.stat-item:last-child::before {
  content: '⏱️'; /* 计时器（改用更常见的） */
  font-size: 16px;
  opacity: 0.9;
  margin-right: 4px;
}

/* 警告闪烁动画 */
@keyframes pulse-warning {
  0% {
    opacity: 1;
    text-shadow: 0 0 0 rgba(255, 71, 87, 0.4);
  }
  50% {
    opacity: 0.9;
    text-shadow: 0 0 10px rgba(255, 71, 87, 0.5);
  }
  100% {
    opacity: 1;
    text-shadow: 0 0 0 rgba(255, 71, 87, 0.4);
  }
}

/* 响应式调整 */
@media (max-width: 768px) {
  .stats-brief {
    flex-wrap: wrap;
    gap: 12px;
  }

  .stat-item {
    flex: 1;
    min-width: 120px;
  }
}

.panel-tabs {
  display: flex;
  gap: 4px;
  padding: 12px 20px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-secondary);
}

.tab-btn {
  flex: 1;
  padding: 8px 4px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  border-radius: 20px;
  font-size: 12px;
  font-weight: 500;
  transition: all 0.2s;
  position: relative;
  overflow: hidden;
}

.tab-btn:hover:not(:disabled) {
  background: var(--bg-hover);
  color: var(--text-primary);
  transform: translateY(-1px);
}

.tab-btn.active {
  background: linear-gradient(135deg, var(--color-highlight) 0%, #ff9f7f 100%);
  color: #000;
  font-weight: 600;
  box-shadow: 0 2px 8px rgba(255, 215, 0, 0.3);
}
.tab-btn.active::before {
  content: '';
  position: absolute;
  top: -2px;
  left: -2px;
  right: -2px;
  bottom: -2px;
  background: linear-gradient(135deg, var(--color-highlight) 0%, #ff9f7f 100%);
  border-radius: 22px;
  z-index: -1;
  opacity: 0.5;
  filter: blur(4px);
}

.tab-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.panel-content {
  padding: 20px;
  max-height: calc(80vh - 240px);
  overflow-y: auto;
}

.loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px;
  gap: 12px;
  color: var(--text-secondary);
}

.loading-spinner {
  font-size: 24px;
  animation: rotate 1s infinite linear;
}

.panel-footer {
  display: flex;
  justify-content: space-between;
  padding: 12px 20px;
  border-top: 1px solid var(--border-color);
  background: var(--bg-header);
}

.btn-text {
  padding: 4px 8px;
  background: transparent;
  border: none;
  color: var(--color-highlight);
  cursor: pointer;
  font-size: 12px;
  border-radius: 4px;
  transition: all 0.2s;
}

.btn-text:hover:not(:disabled) {
  background: var(--bg-hover);
}

.btn-text:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

@keyframes pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.5;
  }
}

.rotate-animation {
  animation: rotate 1s infinite linear;
  display: inline-block;
}

@keyframes rotate {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

.weights-container {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.weights-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  background: var(--bg-secondary);
  border-radius: 8px;
  border: 1px solid var(--border-color);
}

.weights-header h4 {
  margin: 0;
  font-size: 13px;
  color: var(--text-primary);
}

.btn-edit-factors {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  background: var(--color-highlight);
  border: none;
  border-radius: 6px;
  color: #000;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: opacity 0.2s;
}

.btn-edit-factors:hover {
  opacity: 0.9;
}

.btn-edit-factors .icon {
  font-size: 14px;
}

/* 添加错误样式 */
.error-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  background: rgba(255, 71, 87, 0.1);
  border-bottom: 1px solid #ff4757;
  color: #ff4757;
  font-size: 12px;
}

.error-icon {
  font-size: 14px;
}

.retry-btn {
  margin-left: auto;
  padding: 4px 12px;
  background: #ff4757;
  border: none;
  border-radius: 4px;
  color: white;
  font-size: 11px;
  cursor: pointer;
}

.retry-btn:hover {
  background: #ff6b81;
}

.loading-overlay {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.7);
  z-index: 10;
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

.header-actions {
  display: flex;
  gap: 8px;
}

.btn-normalize {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 6px 12px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border: none;
  border-radius: 6px;
  color: white;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
  box-shadow: 0 2px 4px rgba(102, 126, 234, 0.3);
}

.btn-normalize:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 4px 8px rgba(102, 126, 234, 0.4);
}

.btn-normalize:active:not(:disabled) {
  transform: translateY(0);
}

.btn-normalize:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-normalize .icon {
  font-size: 14px;
}
</style>
