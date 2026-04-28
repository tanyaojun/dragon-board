<!-- src/components/panels/algorithm/FactorSelector.vue -->
<template>
  <div class="factor-selector-overlay" @click.self="cancel">
    <div class="factor-selector-panel">
      <div class="panel-header">
        <h3>📦 因子选择器</h3>
        <button class="close-btn" @click="cancel">✕</button>
      </div>

      <!-- 统计栏 -->
      <div class="stats-bar">
        <span>已选: {{ selectedFactors.length }} / {{ allFactors.length }}</span>
        <span>总权重: {{ (totalWeight * 100).toFixed(0) }}%</span>
        <span class="weight-status" :class="{ 'weight-ok': Math.abs(totalWeight - 1) < 0.01 }">
          {{ Math.abs(totalWeight - 1) < 0.01 ? '✅ 平衡' : '权重和应为100%' }}
        </span>
      </div>

      <!-- 双栏选择器 -->
      <div class="selector-grid">
        <!-- 左侧可用因子 -->
        <div class="factor-pool">
          <div class="pool-header">
            <h4>📋 可用因子 ({{ availableFactors.length }})</h4>
            <input v-model="searchKeyword" placeholder="搜索因子..." class="search-input" />
          </div>
          <div class="factor-list">
            <div
              v-for="factor in availableFactors"
              :key="factor.id"
              class="factor-item"
              @click="addFactor(factor.id)"
            >
              <div class="factor-info">
                <span class="factor-name">{{ factor.name }}</span>
                <span class="factor-category" :class="`category-${factor.category}`">
                  {{ getCategoryName(factor.category) }}
                </span>
              </div>
              <div class="factor-meta">
                <span class="factor-desc">{{ factor.description }}</span>
                <button class="add-btn">+ 添加</button>
              </div>
            </div>
            <div v-if="availableFactors.length === 0" class="empty-state">没有匹配的因子</div>
          </div>
        </div>

        <!-- 右侧已选因子 -->
        <div class="factor-pool">
          <div class="pool-header">
            <h4>⚙️ 已选因子 ({{ selectedFactors.length }})</h4>
            <button v-if="selectedFactors.length > 0" class="btn-clear" @click="clearAll">
              清空全部
            </button>
          </div>
          <div class="factor-list selected">
            <div v-for="factorId in selectedFactors" :key="factorId" class="factor-item selected">
              <div class="factor-info">
                <span class="factor-name">{{ getFactorName(factorId) }}</span>
                <span class="factor-category" :class="`category-${getFactorCategory(factorId)}`">
                  {{ getCategoryName(getFactorCategory(factorId)) }}
                </span>
              </div>

              <div class="weight-control">
                <input
                  type="range"
                  class="weight-slider"
                  :min="getFactorMin(factorId)"
                  :max="getFactorMax(factorId)"
                  :step="0.01"
                  :value="getFactorWeight(factorId)"
                  @input="
                    updateWeight(factorId, parseFloat(($event.target as HTMLInputElement).value))
                  "
                />
                <div class="weight-value">
                  <input
                    type="number"
                    class="weight-input"
                    :min="getFactorMin(factorId)"
                    :max="getFactorMax(factorId)"
                    :step="0.01"
                    :value="getFactorWeight(factorId)"
                    @change="
                      updateWeight(factorId, parseFloat(($event.target as HTMLInputElement).value))
                    "
                  />
                  <span class="weight-percent"
                    >{{ (getFactorWeight(factorId) * 100).toFixed(0) }}%</span
                  >
                </div>
                <button class="remove-btn" @click="removeFactor(factorId)" title="移除">✕</button>
              </div>
            </div>

            <div v-if="selectedFactors.length === 0" class="empty-state">点击左侧因子添加</div>
          </div>
        </div>
      </div>

      <!-- 权重分布图 -->
      <div v-if="selectedFactors.length > 0" class="weight-distribution">
        <h4>📊 权重分布</h4>
        <div class="distribution-bars">
          <div v-for="factorId in selectedFactors" :key="factorId" class="distribution-item">
            <span class="dist-factor-name" :title="getFactorName(factorId)">
              {{ getFactorShortName(factorId) }}
            </span>
            <div class="dist-bar-container">
              <div
                class="dist-bar"
                :style="{
                  width: getFactorWeight(factorId) * 100 + '%',
                  backgroundColor: getFactorColor(factorId),
                }"
              ></div>
            </div>
            <span class="dist-weight">{{ (getFactorWeight(factorId) * 100).toFixed(0) }}%</span>
          </div>
        </div>
      </div>

      <!-- 底部按钮 -->
      <div class="panel-footer">
        <button class="btn-secondary" @click="cancel">取消</button>
        <button class="btn-primary" @click="applyConfig" :disabled="!isValid">应用配置</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { debugLog } from '@/utils/logger'
import { ref, computed, onMounted } from 'vue'
import { FACTORS } from '@/config/factors'
import { algorithmManager } from '@/services/algorithm'

const props = defineProps<{
  algorithmId: string
}>()

const emit = defineEmits<{
  (e: 'apply', config: any): void
  (e: 'cancel'): void
}>()

// ========== 状态 ==========
const searchKeyword = ref('')
const selectedFactors = ref<string[]>([])
const factorWeights = ref<Record<string, number>>({})
const loading = ref(true)

// ========== 计算属性 ==========
// 所有因子
const allFactors = computed(() => {
  return Object.entries(FACTORS).map(([id, factor]) => ({
    id,
    name: factor.name,
    category: factor.category,
    description: factor.description,
    min: factor.min || 0,
    max: factor.max || 0.5,
  }))
})

// 可用因子（未选中的）
const availableFactors = computed(() => {
  return allFactors.value
    .filter((f) => !selectedFactors.value.includes(f.id))
    .filter(
      (f) =>
        f.name.toLowerCase().includes(searchKeyword.value.toLowerCase()) ||
        f.description?.toLowerCase().includes(searchKeyword.value.toLowerCase()),
    )
})

// 总权重
const totalWeight = computed(() => {
  return Object.values(factorWeights.value).reduce((sum, w) => sum + w, 0)
})

// 配置是否有效
const isValid = computed(() => {
  return Math.abs(totalWeight.value - 1) < 0.01 && selectedFactors.value.length > 0
})

// ========== 方法 ==========
// 加载当前算法的已选因子
const loadCurrentFactors = () => {
  loading.value = true
  try {
    // 使用 getFactorWeights 获取因子权重
    const factorWeightsList = algorithmManager.getFactorWeights(props.algorithmId)

    if (factorWeightsList && Array.isArray(factorWeightsList)) {
      // 筛选启用的因子
      selectedFactors.value = factorWeightsList.filter((f) => f.enabled !== false).map((f) => f.id)

      // 构建权重对象
      const weights: Record<string, number> = {}
      factorWeightsList.forEach((f) => {
        if (f.enabled !== false) {
          // 处理权重值
          if (typeof f.weight === 'number') {
            weights[f.id] = f.weight
          } else if (f.baseWeight) {
            weights[f.id] = f.baseWeight
          } else {
            weights[f.id] = 0.1 // 默认值
          }
        }
      })
      factorWeights.value = weights

      debugLog('[FactorSelector] 加载因子配置成功:', {
        selected: selectedFactors.value.length,
        weights: Object.keys(weights).length,
      })
    } else {
      // 如果没有数据，使用空数组
      selectedFactors.value = []
      factorWeights.value = {}
    }
  } catch (error) {
    console.error('[FactorSelector] 加载因子配置失败:', error)
    selectedFactors.value = []
    factorWeights.value = {}
  } finally {
    loading.value = false
  }
}

// 添加因子
const addFactor = (factorId: string) => {
  if (selectedFactors.value.includes(factorId)) return

  selectedFactors.value.push(factorId)
  // 设置默认权重
  factorWeights.value[factorId] = 0.1
}

// 移除因子
const removeFactor = (factorId: string) => {
  selectedFactors.value = selectedFactors.value.filter((id) => id !== factorId)
  const newWeights = { ...factorWeights.value }
  delete newWeights[factorId]
  factorWeights.value = newWeights
}

// 更新权重
const updateWeight = (factorId: string, weight: number) => {
  const factor = FACTORS[factorId]
  const min = factor?.min || 0
  const max = factor?.max || 0.5
  factorWeights.value[factorId] = Math.min(max, Math.max(min, weight))
}

// 清空所有
const clearAll = () => {
  selectedFactors.value = []
  factorWeights.value = {}
}

// 获取因子权重
const getFactorWeight = (factorId: string): number => {
  return factorWeights.value[factorId] || 0
}

// 获取因子名称
const getFactorName = (factorId: string): string => {
  return FACTORS[factorId]?.name || factorId
}

// 获取因子类别
const getFactorCategory = (factorId: string): string => {
  return FACTORS[factorId]?.category || 'other'
}

// 获取因子最小权重
const getFactorMin = (factorId: string): number => {
  return FACTORS[factorId]?.min || 0
}

// 获取因子最大权重
const getFactorMax = (factorId: string): number => {
  return FACTORS[factorId]?.max || 0.5
}

// 获取类别名称
const getCategoryName = (category: string): string => {
  const names: Record<string, string> = {
    market: '市场',
    money: '资金',
    technical: '技术',
    sector: '题材',
    sentiment: '情绪',
    fundamental: '基本面',
    rank: '排名',
  }
  return names[category] || category
}

// 获取因子颜色
const getFactorColor = (factorId: string): string => {
  const category = getFactorCategory(factorId)
  const colors: Record<string, string> = {
    market: '#3498db',
    money: '#2ed573',
    technical: '#ffa502',
    sector: '#9b59b6',
    sentiment: '#ff7f50',
    fundamental: '#95a5a6',
    rank: '#f1c40f',
  }
  return colors[category] || '#7f8c8d'
}

// 获取因子简称
const getFactorShortName = (factorId: string): string => {
  const name = getFactorName(factorId)
  if (name.length <= 4) return name
  if (name.includes('综合')) return '排名'
  if (name.includes('主力')) return '主力'
  if (name.includes('龙息')) return name.substring(0, 2)
  if (name.includes('涨幅')) return '涨幅'
  if (name.includes('成交')) return '成交'
  if (name.includes('换手')) return '换手'
  return name.substring(0, 4)
}

// 应用配置
const applyConfig = () => {
  if (!isValid.value) return

  // 构建配置对象
  const config = {
    algorithmId: props.algorithmId,
    factors: selectedFactors.value.reduce(
      (acc, factorId) => {
        acc[factorId] = {
          weight: factorWeights.value[factorId] || 0.1,
          enabled: true,
        }
        return acc
      },
      {} as Record<string, any>,
    ),
  }

  emit('apply', config)
}

const cancel = () => {
  emit('cancel')
}

// 初始化
onMounted(() => {
  loadCurrentFactors()
})
</script>

<style scoped>
.factor-selector-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 10005;
}

.factor-selector-panel {
  width: 800px;
  max-width: 90vw;
  max-height: 90vh;
  background: var(--bg-primary);
  border-radius: 12px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
  display: flex;
  flex-direction: column;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-color);
}

.panel-header h3 {
  margin: 0;
  font-size: 16px;
  color: var(--color-highlight);
}

.close-btn {
  width: 32px;
  height: 32px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 16px;
  border-radius: 6px;
}

.close-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.stats-bar {
  display: flex;
  gap: 24px;
  padding: 12px 20px;
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border-color);
  font-size: 13px;
  font-weight: 500;
  align-items: center;
}

.stats-bar span {
  color: var(--text-primary);
  opacity: 0.9;
}

/* 已选因子数量 - 金色高亮 */
.stats-bar span:first-child {
  color: #ffd700;
  font-weight: 600;
  text-shadow: 0 0 5px rgba(255, 215, 0, 0.3);
}

.stats-bar span:first-child::before {
  content: '✓ ';
  opacity: 0.8;
}

/* 总权重 - 亮绿色 */
.stats-bar span:nth-child(2) {
  color: #2ed573;
  font-weight: 600;
  text-shadow: 0 0 5px rgba(46, 213, 115, 0.3);
}

/* 权重状态标签 */
.weight-status {
  padding: 4px 12px;
  border-radius: 20px;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.3px;
  margin-left: auto;
}
.stats-bar span:nth-child(2)::before {
  content: '∑ ';
  opacity: 0.8;
}

/* 权重平衡状态 - 绿色 */
.weight-status.weight-ok {
  color: #2ed573 !important;
  background: rgba(46, 213, 115, 0.2);
  border: 1px solid rgba(46, 213, 115, 0.3);
}

/* 权重不平衡状态 - 红色 */
.weight-status:not(.weight-ok) {
  color: #ff4757 !important;
  background: rgba(255, 71, 87, 0.2);
  border: 1px solid rgba(255, 71, 87, 0.3);
  animation: pulse-warning 2s infinite;
}

.weight-status:not(.weight-ok)::before {
  content: '⚠️ ';
  font-size: 12px;
}

.selector-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  padding: 20px;
  min-height: 400px;
}

.weight-status.weight-ok::before {
  content: '✓ ';
  font-size: 14px;
}

.factor-pool {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  overflow: hidden;
}

.pool-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px;
  background: var(--bg-header);
  border-bottom: 1px solid var(--border-color);
}

.pool-header h4 {
  margin: 0;
  font-size: 13px;
  color: var(--text-primary);
}

.search-input {
  padding: 4px 8px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  color: var(--text-primary);
  font-size: 12px;
  width: 150px;
}

.btn-clear {
  padding: 4px 8px;
  background: transparent;
  border: 1px solid var(--border-color);
  border-radius: 4px;
  color: var(--text-secondary);
  font-size: 11px;
  cursor: pointer;
}

.btn-clear:hover {
  background: var(--bg-hover);
  color: #ff4757;
}

.factor-list {
  flex: 1;
  padding: 8px;
  overflow-y: auto;
  max-height: 400px;
}

.factor-item {
  padding: 8px;
  margin-bottom: 4px;
  background: var(--bg-secondary);
  border-radius: 6px;
  border: 1px solid transparent;
  cursor: pointer;
  transition: all 0.2s;
}

.factor-item:hover {
  border-color: var(--color-highlight);
  transform: translateX(2px);
}

.factor-item.selected {
  background: var(--bg-primary);
  border-color: var(--color-highlight);
  cursor: default;
}

.factor-info {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}

.factor-name {
  font-weight: 500;
  color: var(--text-primary);
  font-size: 12px;
}

.factor-category {
  font-size: 10px;
  padding: 2px 6px;
  border-radius: 10px;
  background: var(--bg-primary);
}

.category-market {
  color: #3498db;
}
.category-money {
  color: #2ed573;
}
.category-technical {
  color: #ffa502;
}
.category-sector {
  color: #9b59b6;
}
.category-sentiment {
  color: #ff7f50;
}

.factor-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.factor-desc {
  font-size: 10px;
  color: var(--text-tertiary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 200px;
}

.add-btn {
  padding: 2px 8px;
  background: var(--color-highlight);
  border: none;
  border-radius: 4px;
  color: #000;
  font-size: 10px;
  cursor: pointer;
  opacity: 0.8;
}

.add-btn:hover {
  opacity: 1;
}

.weight-control {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
}

.weight-slider {
  flex: 1;
  height: 4px;
  -webkit-appearance: none;
  background: var(--border-color);
  border-radius: 2px;
}

.weight-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: var(--color-highlight);
  cursor: pointer;
}

.weight-value {
  display: flex;
  align-items: center;
  gap: 4px;
  min-width: 80px;
}

.weight-input {
  width: 50px;
  padding: 2px 4px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  color: var(--text-primary);
  font-size: 11px;
}

.weight-percent {
  font-size: 11px;
  color: var(--text-secondary);
  min-width: 35px;
}

.remove-btn {
  width: 20px;
  height: 20px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 12px;
  border-radius: 4px;
}

.remove-btn:hover {
  background: rgba(255, 71, 87, 0.2);
  color: #ff4757;
}

.empty-state {
  padding: 40px;
  text-align: center;
  color: var(--text-tertiary);
  font-size: 12px;
}

.weight-distribution {
  padding: 16px 20px;
  background: var(--bg-secondary);
  border-top: 1px solid var(--border-color);
}

.weight-distribution h4 {
  margin: 0 0 12px 0;
  font-size: 13px;
  color: var(--text-primary);
}

.distribution-bars {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.distribution-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

.dist-factor-name {
  width: 60px;
  font-size: 11px;
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dist-bar-container {
  flex: 1;
  height: 8px;
  background: var(--bg-primary);
  border-radius: 4px;
  overflow: hidden;
}

.dist-bar {
  height: 100%;
  border-radius: 4px;
  transition: width 0.3s;
}

.dist-weight {
  width: 45px;
  font-size: 11px;
  color: var(--text-secondary);
  text-align: right;
}

.panel-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding: 16px 20px;
  border-top: 1px solid var(--border-color);
}

.btn-primary {
  padding: 8px 24px;
  background: var(--color-highlight);
  border: none;
  border-radius: 6px;
  color: #000;
  font-weight: bold;
  cursor: pointer;
}

.btn-primary:hover:not(:disabled) {
  opacity: 0.9;
}

.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-secondary {
  padding: 8px 24px;
  background: transparent;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  color: var(--text-secondary);
  cursor: pointer;
}

.btn-secondary:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

/* 警告闪烁动画 */
@keyframes pulse-warning {
  0% {
    opacity: 1;
    box-shadow: 0 0 0 0 rgba(255, 71, 87, 0.4);
  }
  50% {
    opacity: 0.9;
    box-shadow: 0 0 10px 2px rgba(255, 71, 87, 0.3);
  }
  100% {
    opacity: 1;
    box-shadow: 0 0 0 0 rgba(255, 71, 87, 0.4);
  }
}

/* 响应式调整 */
@media (max-width: 768px) {
  .stats-bar {
    flex-wrap: wrap;
    gap: 12px;
  }

  .weight-status {
    margin-left: 0;
    width: 100%;
    text-align: center;
  }
}

/* 因子名称 - 亮色 */
.factor-name {
  color: var(--text-primary);
  font-weight: 500;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.1);
}

/* 因子类别标签 */
.factor-category {
  font-size: 10px;
  padding: 2px 8px;
  border-radius: 12px;
  font-weight: 500;
  background: var(--bg-primary);
  border: 1px solid currentColor;
}

/* 各类别颜色 */
.category-market {
  color: #3498db;
  background: rgba(52, 152, 219, 0.1);
}
.category-money {
  color: #2ed573;
  background: rgba(46, 213, 115, 0.1);
}
.category-technical {
  color: #ffa502;
  background: rgba(255, 165, 2, 0.1);
}
.category-sector {
  color: #9b59b6;
  background: rgba(155, 89, 182, 0.1);
}
.category-sentiment {
  color: #ff7f50;
  background: rgba(255, 127, 80, 0.1);
}

/* 权重输入框 */
.weight-input {
  color: var(--text-primary);
  font-weight: 500;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
}

.weight-percent {
  color: #ffd700;
  font-weight: 600;
}

/* 空状态提示 */
.empty-state {
  color: var(--text-tertiary);
  font-style: italic;
  padding: 40px;
  text-align: center;
  background: var(--bg-secondary);
  border-radius: 8px;
}

/* 分布图标签 */
.dist-factor-name {
  color: var(--text-primary);
  font-weight: 500;
}

.dist-weight {
  color: #ffd700;
  font-weight: 600;
}
</style>
