<!-- src/components/panels/algorithm/ThresholdsTab.vue  阈值调整 -->
<template>
  <div class="thresholds-tab">
    <!-- 阈值说明 -->
    <div class="info-section">
      <span class="info-icon">🎯</span>
      <span class="info-text">调整各级龙头的评分阈值，评分高于阈值才有可能成为对应级别的龙头</span>
    </div>

    <!-- 阈值列表 -->
    <div class="thresholds-list">
      <div v-for="item in thresholdsConfig" :key="item.key" class="threshold-item">
        <div class="threshold-info">
          <div class="threshold-header">
            <span class="threshold-icon">{{ item.icon }}</span>
            <span class="threshold-name">{{ item.name }}</span>
            <span class="threshold-desc">{{ item.desc }}</span>
          </div>
          <div class="threshold-value-display">
            <span
              class="current-value"
              :style="{ color: getThresholdColor(localThresholds[item.key]) }"
            >
              {{ localThresholds[item.key] }}
            </span>
          </div>
        </div>

        <div class="threshold-control">
          <input
            type="range"
            class="threshold-slider"
            v-model.number="localThresholds[item.key]"
            :min="thresholdRanges[item.key]?.min || 0"
            :max="thresholdRanges[item.key]?.max || 100"
            step="1"
            @input="onThresholdChange"
          />
          <div class="threshold-range">
            <span>{{ thresholdRanges[item.key]?.min || 0 }}</span>
            <span>{{ thresholdRanges[item.key]?.max || 100 }}</span>
          </div>
        </div>

        <!-- 示例说明 -->
        <div class="threshold-example">
          💡 示例: 评分{{ localThresholds[item.key] }}分以上的股票可能成为{{ item.name }}
        </div>
      </div>
    </div>

    <!-- 当前算法的影响 -->
    <div class="impact-section">
      <div class="impact-title">📊 当前算法影响</div>
      <div class="impact-grid">
        <div class="impact-item">
          <span class="impact-label">算法类型</span>
          <span class="impact-value">{{ algorithmNames[algorithm] || algorithm }}</span>
        </div>
        <div class="impact-item">
          <span class="impact-label">总龙头数量</span>
          <span class="impact-value">{{ leaderStats.totalLeadersCount || 0 }}</span>
        </div>
        <div class="impact-item">
          <span class="impact-label">板块龙头</span>
          <span class="impact-value">{{ leaderStats.sectorLeaders || 0 }}</span>
        </div>
        <div class="impact-item">
          <span class="impact-label">连板龙头</span>
          <span class="impact-value">{{ leaderStats.continuousLeaders || 0 }}</span>
        </div>
      </div>
    </div>

    <!-- 底部按钮 -->
    <div class="actions">
      <button class="btn" @click="resetThresholds">重置默认</button>
      <button class="btn btn-primary" @click="saveThresholds">保存阈值</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'
import { EventManager } from '@/utils/eventManager'
import { AppEvents } from '@/types/events'
import { algorithmManager } from '@/services/algorithm'

const props = defineProps<{
  algorithm: string
  weights: Record<string, number>
  thresholds: any
  showAdvanced: boolean
}>()

const emit = defineEmits<{
  (e: 'update-thresholds', thresholds: any): void
}>()

// 阈值配置
const thresholdsConfig = [
  { key: 'totalLeader', name: '总龙头阈值', icon: '👑', desc: '评分高于此值且排名前10' },
  { key: 'sectorLeader', name: '板块龙头阈值', icon: '🏆', desc: '评分高于此值' },
  { key: 'continuousLeader', name: '连板龙头阈值', icon: '📈', desc: '评分高于此值且涨幅>9%' },
  { key: 'middleLeader', name: '中军龙头阈值', icon: '⚔️', desc: '评分高于此值且市值>50亿' },
  { key: 'emotionLeader', name: '情绪龙头阈值', icon: '🔥', desc: '评分高于此值且换手率>15%' },
]

// 本地状态
const localThresholds = ref({ ...props.thresholds })
const thresholdRanges = ref<Record<string, { min: number; max: number }>>({
  totalLeader: { min: 60, max: 95 },
  sectorLeader: { min: 45, max: 85 },
  continuousLeader: { min: 50, max: 90 },
  middleLeader: { min: 40, max: 80 },
  emotionLeader: { min: 35, max: 75 },
})
const leaderStats = ref({
  totalLeadersCount: 0,
  sectorLeaders: 0,
  continuousLeaders: 0,
  middleLeaders: 0,
  emotionLeaders: 0,
})

// 算法名称
const algorithmNames: Record<string, string> = {
  balanced: '平衡型',
  dragonFirst: '龙头优先',
  moneyDriven: '资金驱动',
  techDriven: '技术驱动',
  sentimentDriven: '情绪驱动',
  ml: '机器学习',
}

watch(
  () => props.thresholds,
  (newVal) => {
    localThresholds.value = { ...newVal }
  },
)

// 获取阈值颜色
const getThresholdColor = (value: number): string => {
  if (value >= 80) return '#ff4757'
  if (value >= 70) return '#ff7f50'
  if (value >= 60) return '#f39c12'
  if (value >= 50) return '#3498db'
  return '#7f8c8d'
}

// 阈值变化
const onThresholdChange = () => {
  emit('update-thresholds', localThresholds.value)
}

// 保存阈值
const saveThresholds = () => {
  Object.entries(localThresholds.value).forEach(([key, value]) => {
    algorithmManager.updateThreshold(key, Number(value))
  })

  EventManager.emit(AppEvents.UI.TOAST, {
    message: '✅ 阈值已保存',
    duration: 1500,
    type: 'success',
  })

  // 重新计算龙头
  if ((window as any).DragonAnalyzer) {
    ;(window as any).DragonAnalyzer.recalculateAll()
  }
}

// 重置阈值
const resetThresholds = () => {
  const defaultThresholds = {
    totalLeader: 80,
    sectorLeader: 65,
    continuousLeader: 70,
    middleLeader: 60,
    emotionLeader: 55,
  }

  localThresholds.value = defaultThresholds
  emit('update-thresholds', defaultThresholds)

  EventManager.emit(AppEvents.UI.TOAST, {
    message: '🔄 阈值已重置',
    duration: 1500,
    type: 'info',
  })
}

// 获取龙头统计
const fetchLeaderStats = () => {
  if ((window as any).DragonAnalyzer) {
    const stats = (window as any).DragonAnalyzer.getStats?.()
    if (stats) {
      leaderStats.value = stats
    }
  }
}

onMounted(() => {
  fetchLeaderStats()
})
</script>

<style scoped>
.thresholds-tab {
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
  font-size: 24px;
}

.info-text {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.5;
}

.thresholds-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.threshold-item {
  padding: 16px;
  background: var(--bg-secondary);
  border-radius: 8px;
  border: 1px solid var(--border-color);
}

.threshold-info {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.threshold-header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.threshold-icon {
  font-size: 18px;
}

.threshold-name {
  font-weight: bold;
  color: var(--text-primary);
  font-size: 14px;
}

.threshold-desc {
  font-size: 11px;
  color: var(--text-secondary);
  background: var(--bg-primary);
  padding: 2px 8px;
  border-radius: 12px;
}

.threshold-value-display {
  font-size: 20px;
  font-weight: bold;
  min-width: 45px;
  text-align: right;
}

.current-value {
  transition: color 0.3s;
}

.threshold-control {
  margin-bottom: 12px;
}

.threshold-slider {
  width: 100%;
  height: 6px;
  -webkit-appearance: none;
  background: linear-gradient(
    90deg,
    #7f8c8d 0%,
    #3498db 25%,
    #f39c12 50%,
    #ff7f50 75%,
    #ff4757 100%
  );
  border-radius: 3px;
  margin-bottom: 8px;
}

.threshold-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  width: 18px;
  height: 18px;
  background: var(--color-highlight);
  border-radius: 9px;
  cursor: pointer;
  border: 2px solid white;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
}

.threshold-range {
  display: flex;
  justify-content: space-between;
  font-size: 10px;
  color: var(--text-secondary);
  padding: 0 4px;
}

.threshold-example {
  font-size: 11px;
  color: var(--text-secondary);
  background: var(--bg-primary);
  padding: 8px 12px;
  border-radius: 6px;
  border-left: 3px solid var(--color-highlight);
}

.impact-section {
  padding: 16px;
  background: var(--bg-secondary);
  border-radius: 8px;
  border: 1px solid var(--border-color);
}

.impact-title {
  font-weight: bold;
  color: var(--text-primary);
  margin-bottom: 12px;
  font-size: 13px;
}

.impact-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
}

.impact-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px;
  background: var(--bg-primary);
  border-radius: 6px;
}

.impact-label {
  font-size: 10px;
  color: var(--text-secondary);
}

.impact-value {
  font-size: 16px;
  font-weight: bold;
  color: var(--color-highlight);
}

.actions {
  display: flex;
  gap: 8px;
  margin-top: 8px;
}

.btn {
  flex: 1;
  padding: 8px;
  border: 1px solid var(--border-color);
  background: var(--bg-primary);
  color: var(--text-primary);
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
  transition: all 0.2s;
}

.btn:hover {
  background: var(--bg-hover);
  border-color: var(--color-highlight);
}

.btn-primary {
  background: var(--color-highlight);
  border-color: var(--color-highlight);
  color: #000;
  font-weight: bold;
}

.btn-primary:hover {
  opacity: 0.9;
}
</style>
