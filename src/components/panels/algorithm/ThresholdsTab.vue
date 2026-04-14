<!-- src/components/panels/algorithm/ThresholdsTab.vue -->
<template>
  <div class="thresholds-tab">
    <div class="tab-header">
      <h4>🎯 龙头阈值配置</h4>
      <button class="btn-icon-small" @click="resetToDefaults" title="恢复默认">
        🔄 恢复默认
      </button>
    </div>

    <div class="thresholds-list">
      <div v-for="item in thresholdItems" :key="item.key" class="threshold-item">
        <div class="threshold-info">
          <span class="threshold-name" :title="item.description">
            {{ item.name }}
          </span>
          <span class="threshold-badge" :class="getLevelClass(item.value)">
            {{ getLevelText(item.value, item.thresholds) }}
          </span>
        </div>

        <div class="threshold-control">
          <input
            type="range"
            class="threshold-slider"
            :min="item.min"
            :max="item.max"
            :step="1"
            :value="item.value"
            @input="updateThreshold(item.key, parseInt(($event.target as HTMLInputElement).value))"
          />
          <div class="threshold-value">
            <input
              type="number"
              class="threshold-input"
              :min="item.min"
              :max="item.max"
              :step="1"
              :value="item.value"
              @change="updateThreshold(item.key, parseInt(($event.target as HTMLInputElement).value))"
            />
            <span class="threshold-unit">分</span>
          </div>
        </div>

        <div class="threshold-scale">
          <div class="scale-mark" :style="{ left: '0%' }">{{ item.min }}</div>
          <div class="scale-mark" :style="{ left: '25%' }">{{ Math.round((item.max - item.min) * 0.25 + item.min) }}</div>
          <div class="scale-mark" :style="{ left: '50%' }">{{ Math.round((item.max - item.min) * 0.5 + item.min) }}</div>
          <div class="scale-mark" :style="{ left: '75%' }">{{ Math.round((item.max - item.min) * 0.75 + item.min) }}</div>
          <div class="scale-mark" :style="{ left: '100%' }">{{ item.max }}</div>
        </div>

        <div v-if="showAdvanced" class="threshold-impact">
          <span class="impact-label">影响说明：</span>
          <span class="impact-text">{{ getImpactDescription(item.key, item.value) }}</span>
        </div>
      </div>
    </div>

    <div class="thresholds-preview">
      <div class="preview-header">
        <span>📊 当前阈值效果预览</span>
        <span class="preview-hint">数值越高，筛选越严格</span>
      </div>
      <div class="preview-bars">
        <div
          v-for="item in thresholdItems"
          :key="item.key"
          class="preview-item"
          :title="`${item.name}: ${item.value}分`"
        >
          <div class="preview-label">{{ item.shortName }}</div>
          <div class="preview-bar-container">
            <div
              class="preview-bar"
              :style="{
                width: ((item.value - item.min) / (item.max - item.min)) * 100 + '%',
                backgroundColor: getBarColor(item.value, item.thresholds)
              }"
            ></div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  algorithm: string
  weights: Record<string, number>
  thresholds: any
  showAdvanced: boolean
}>()

const emit = defineEmits<{
  (e: 'update-thresholds', thresholds: any): void
}>()

// 阈值项定义
const thresholdItems = computed(() => [
  {
    key: 'totalLeader',
    name: '总龙头阈值',
    shortName: '总龙头',
    description: '总龙头的最低得分要求，得分越高代表市场地位越强',
    min: 60,
    max: 95,
    value: props.thresholds?.totalLeader || 80,
    thresholds: [60, 70, 80, 90]
  },
  {
    key: 'continuousLeader',
    name: '连板龙头阈值',
    shortName: '连板',
    description: '连板龙头的最低得分要求，连板高度和强度',
    min: 50,
    max: 90,
    value: props.thresholds?.continuousLeader || 70,
    thresholds: [50, 60, 70, 80]
  },
  {
    key: 'sectorLeader',
    name: '板块龙头阈值',
    shortName: '板块',
    description: '板块龙头的最低得分要求，板块内领涨地位',
    min: 45,
    max: 85,
    value: props.thresholds?.sectorLeader || 65,
    thresholds: [45, 55, 65, 75]
  },
  {
    key: 'middleLeader',
    name: '中军龙头阈值',
    shortName: '中军',
    description: '中军龙头的最低得分要求，市值和趋势强度',
    min: 40,
    max: 80,
    value: props.thresholds?.middleLeader || 60,
    thresholds: [40, 50, 60, 70]
  },
  {
    key: 'emotionLeader',
    name: '情绪龙头阈值',
    shortName: '情绪',
    description: '情绪龙头的最低得分要求，换手和情绪驱动',
    min: 35,
    max: 75,
    value: props.thresholds?.emotionLeader || 55,
    thresholds: [35, 45, 55, 65]
  }
])

// 更新阈值
const updateThreshold = (key: string, value: number) => {
  const newThresholds = {
    ...props.thresholds,
    [key]: value
  }
  emit('update-thresholds', newThresholds)
}

// 恢复默认值
const resetToDefaults = () => {
  const defaults = {
    totalLeader: 80,
    continuousLeader: 70,
    sectorLeader: 65,
    middleLeader: 60,
    emotionLeader: 55
  }
  emit('update-thresholds', defaults)
}

// 获取级别文本
const getLevelText = (value: number, thresholds: number[]): string => {
  if (value >= thresholds[3]) return '严格'
  if (value >= thresholds[2]) return '适中'
  if (value >= thresholds[1]) return '宽松'
  return '极松'
}

// 获取级别样式
const getLevelClass = (value: number): string => {
  if (value >= 80) return 'level-strict'
  if (value >= 65) return 'level-medium'
  return 'level-loose'
}

// 获取条形图颜色
const getBarColor = (value: number, thresholds: number[]): string => {
  if (value >= thresholds[3]) return '#ff4757'
  if (value >= thresholds[2]) return '#f39c12'
  if (value >= thresholds[1]) return '#2ed573'
  return '#7f8c8d'
}

// 获取影响说明
const getImpactDescription = (key: string, value: number): string => {
  switch (key) {
    case 'totalLeader':
      if (value >= 90) return '只有最顶尖的个股才能成为总龙头，数量极少'
      if (value >= 80) return '正常标准，市场会选出1-2只总龙头'
      if (value >= 70) return '标准较宽松，可能出现多只总龙头'
      return '标准极松，容易产生过多总龙头'
    
    case 'continuousLeader':
      if (value >= 80) return '只保留4板以上的高度板'
      if (value >= 70) return '3板以上可入选'
      if (value >= 60) return '2板以上可入选'
      return '首板也可能入选'
    
    case 'sectorLeader':
      if (value >= 75) return '每个板块只选最强的1只'
      if (value >= 65) return '每个板块1-2只龙头'
      if (value >= 55) return '板块内多只个股可入选'
      return '板块效应较弱时也能入选'
    
    case 'middleLeader':
      if (value >= 70) return '只选超大市值趋势股'
      if (value >= 60) return '中大盘趋势股'
      if (value >= 50) return '中小盘趋势股'
      return '趋势不明显也可能入选'
    
    case 'emotionLeader':
      if (value >= 65) return '只在情绪高潮期出现'
      if (value >= 55) return '情绪驱动明显'
      if (value >= 45) return '有一定情绪驱动'
      return '任何情绪阶段都可能出现'
    
    default:
      return ''
  }
}
</script>

<style scoped>
.thresholds-tab {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.tab-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.tab-header h4 {
  margin: 0;
  font-size: 14px;
  color: var(--text-primary);
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

.thresholds-list {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.threshold-item {
  background: var(--bg-secondary);
  border-radius: 8px;
  padding: 16px;
  border: 1px solid var(--border-color);
}

.threshold-info {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.threshold-name {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
  cursor: help;
}

.threshold-badge {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 12px;
  font-weight: 500;
}

.threshold-badge.level-strict {
  background: rgba(255, 71, 87, 0.2);
  color: #ff4757;
}

.threshold-badge.level-medium {
  background: rgba(243, 156, 18, 0.2);
  color: #f39c12;
}

.threshold-badge.level-loose {
  background: rgba(46, 213, 115, 0.2);
  color: #2ed573;
}

.threshold-control {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 12px;
}

.threshold-slider {
  flex: 1;
  height: 4px;
  -webkit-appearance: none;
  background: linear-gradient(
    to right,
    #2ed573 0%,
    #f39c12 50%,
    #ff4757 100%
  );
  border-radius: 2px;
  outline: none;
}

.threshold-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: white;
  border: 2px solid var(--color-highlight);
  cursor: pointer;
  box-shadow: 0 2px 4px rgba(0,0,0,0.2);
}

.threshold-value {
  display: flex;
  align-items: center;
  gap: 4px;
  min-width: 80px;
}

.threshold-input {
  width: 50px;
  padding: 4px 6px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  color: var(--text-primary);
  font-size: 12px;
  text-align: right;
}

.threshold-unit {
  font-size: 11px;
  color: var(--text-tertiary);
}

.threshold-scale {
  position: relative;
  height: 16px;
  margin: 8px 0 4px;
}

.scale-mark {
  position: absolute;
  transform: translateX(-50%);
  font-size: 9px;
  color: var(--text-tertiary);
  white-space: nowrap;
}

.threshold-impact {
  margin-top: 12px;
  padding: 8px 12px;
  background: var(--bg-primary);
  border-radius: 6px;
  font-size: 11px;
  border-left: 3px solid var(--color-highlight);
}

.impact-label {
  color: var(--text-tertiary);
  margin-right: 4px;
}

.impact-text {
  color: var(--text-secondary);
}

.thresholds-preview {
  background: var(--bg-secondary);
  border-radius: 8px;
  padding: 16px;
  border: 1px solid var(--border-color);
}

.preview-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  font-size: 12px;
  color: var(--text-primary);
}

.preview-hint {
  font-size: 10px;
  color: var(--text-tertiary);
}

.preview-bars {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.preview-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

.preview-label {
  width: 40px;
  font-size: 11px;
  color: var(--text-secondary);
}

.preview-bar-container {
  flex: 1;
  height: 8px;
  background: var(--border-color);
  border-radius: 4px;
  overflow: hidden;
}

.preview-bar {
  height: 100%;
  border-radius: 4px;
  transition: width 0.2s;
}
</style>