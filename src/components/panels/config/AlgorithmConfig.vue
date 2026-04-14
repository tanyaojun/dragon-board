<!-- src/components/panels/config/AlgorithmConfig.vue -->
<template>
  <div class="config-section">
    <h4>🧠 当前算法</h4>
    <div class="config-item">
      <span class="config-label">算法</span>
      <select class="config-select" v-model="local.algorithm.current" @change="emitChange">
        <option value="balanced">平衡型</option>
        <option value="dragonFirst">龙头优先</option>
        <option value="moneyDriven">资金驱动</option>
        <option value="techDriven">技术驱动</option>
        <option value="sentimentDriven">情绪驱动</option>
        <option value="ml">机器学习</option>
      </select>
    </div>
  </div>

  <div class="config-section">
    <h4>🎯 阈值配置</h4>
    <div v-for="(value, key) in local.algorithm.thresholds" :key="key" class="config-item">
      <span class="config-label">{{ getThresholdName(key) }}</span>
      <input 
        type="range" 
        class="config-slider" 
        v-model.number="local.algorithm.thresholds[key]"
        :min="getThresholdRange(key).min"
        :max="getThresholdRange(key).max"
        @input="emitChange"
      >
      <span class="config-value">{{ local.algorithm.thresholds[key] }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'

const props = defineProps<{
  config: any
}>()

const emit = defineEmits<{
  (e: 'change', data: any): void
}>()

const local = ref({ ...props.config })

watch(() => props.config, (newVal) => {
  local.value = { ...newVal }
}, { deep: true })

const thresholdNames: Record<string, string> = {
  totalLeader: '总龙头',
  sectorLeader: '板块龙头',
  continuousLeader: '连板龙头',
  middleLeader: '中军龙头',
  emotionLeader: '情绪龙头'
}

const thresholdRanges: Record<string, { min: number; max: number }> = {
  totalLeader: { min: 60, max: 95 },
  sectorLeader: { min: 45, max: 85 },
  continuousLeader: { min: 50, max: 90 },
  middleLeader: { min: 40, max: 80 },
  emotionLeader: { min: 35, max: 75 }
}

function getThresholdName(key: string): string {
  return thresholdNames[key] || key
}

function getThresholdRange(key: string): { min: number; max: number } {
  return thresholdRanges[key] || { min: 0, max: 100 }
}

function emitChange() {
  emit('change', { algorithm: local.value.algorithm })
}
</script>

<style scoped>
.config-section {
  margin-bottom: 24px;
  padding: 16px;
  background: var(--bg-secondary);
  border-radius: 8px;
}

.config-section h4 {
  margin: 0 0 16px 0;
  font-size: 14px;
  color: var(--color-highlight);
}

.config-item {
  display: flex;
  align-items: center;
  margin-bottom: 12px;
  padding: 4px 0;
}

.config-label {
  width: 100px;
  color: var(--text-secondary);
  font-size: 12px;
}

.config-select {
  width: 200px;
  padding: 6px 10px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  color: var(--text-primary);
  font-size: 12px;
}

.config-slider {
  width: 200px;
  margin-right: 12px;
}

.config-value {
  min-width: 40px;
  color: var(--text-primary);
  font-weight: 500;
}
</style>