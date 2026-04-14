<!-- src/components/panels/ThresholdMultiplierPanel.vue -->
<template>
  <Teleport to="body">
    <div v-if="visible" class="threshold-panel" :style="panelStyle" ref="panelRef">
      <div class="panel-header">
        <h3>⚡ 阈值乘数配置</h3>
        <button class="btn-close" @click="close">✕</button>
      </div>
      
      <div class="panel-content">
        <div class="info-tip">
          <span class="tip-icon">ℹ️</span>
          <span>阈值乘数影响龙头判定标准：值越大，该阶段龙头门槛越高</span>
        </div>
        
        <div v-for="(multiplier, phase) in multipliers" :key="phase" class="phase-card">
          <div class="phase-header" :style="{ background: getPhaseGradient(phase) }">
            <span class="phase-icon">{{ getPhaseIcon(phase) }}</span>
            <span class="phase-name">{{ phase }}</span>
          </div>
          
          <div class="multiplier-grid">
            <div v-for="key in multiplierKeys" :key="key" class="multiplier-item">
              <label>{{ getLevelName(key) }}</label>
              <div class="slider-container">
                <input 
                  type="range" 
                  v-model.number="multiplier[key]" 
                  :min="0.5" 
                  :max="1.5" 
                  :step="0.05"
                  @change="updateMultiplier(phase, key, multiplier[key])"
                >
                <span class="value">{{ (multiplier[key] * 100).toFixed(0) }}%</span>
              </div>
              <div class="preset-buttons">
                <button class="preset-btn" @click="setPreset(phase, key, 0.8)">-20%</button>
                <button class="preset-btn" @click="setPreset(phase, key, 1.0)">标准</button>
                <button class="preset-btn" @click="setPreset(phase, key, 1.2)">+20%</button>
              </div>
            </div>
          </div>
          
          <div class="phase-actions">
            <button class="btn-reset" @click="resetPhase(phase)">重置本阶段</button>
          </div>
        </div>
      </div>
      
      <div class="panel-footer">
        <button class="btn-reset-all" @click="resetAll">全部重置为默认值</button>
        <button class="btn-save" @click="saveAndClose">保存并关闭</button>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { EventManager } from '@/utils/eventManager'
import { dragonBreathAnalyzer } from '@/services/DragonBreathAnalyzer'
import { MARKET_PHASES } from '@/types'
import { usePanel } from '@/composables/usePanel'

const props = defineProps<{
  visible: boolean
  triggerRect?: DOMRect
}>()

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'close'): void
}>()

// 关闭函数
const close = () => {
  emit('update:visible', false)
  emit('close')
}

// 使用 usePanel
const { panelRef, panelStyle } = usePanel({
  name: 'ThresholdMultiplierPanel',
  visible: props.visible,
  triggerRect: props.triggerRect,
  triggerSelectors: ['[title*="阈值乘数"]'],
  onClose: close,
})

// 阈值乘数数据
const multipliers = ref<Record<string, any>>({})
const multiplierKeys = ['totalLeader', 'continuousLeader', 'sectorLeader', 'middleLeader', 'emotionLeader']

// 加载数据
const loadData = () => {
  multipliers.value = JSON.parse(JSON.stringify(dragonBreathAnalyzer.getAllThresholdMultipliers?.() || {}))
}

// 更新乘数
const updateMultiplier = (phase: string, key: string, value: number) => {
  const current = { ...multipliers.value[phase] }
  current[key] = value
  multipliers.value[phase] = current
  dragonBreathAnalyzer.updateThresholdMultiplier?.(phase, current)
}

// 设置预设值
const setPreset = (phase: string, key: string, value: number) => {
  updateMultiplier(phase, key, value)
}

// 重置单个阶段
const resetPhase = (phase: string) => {
  dragonBreathAnalyzer.resetThresholdMultiplier?.(phase)
  loadData()
}

// 重置所有
const resetAll = () => {
  dragonBreathAnalyzer.resetAllThresholdMultipliers?.()
  loadData()
}

// 保存并关闭
const saveAndClose = () => {
  close()
}

// 获取阶段图标
const getPhaseIcon = (phase: string): string => {
  return Object.values(MARKET_PHASES).find(p => p.name === phase)?.icon || '🌬️'
}

// 获取阶段渐变
const getPhaseGradient = (phase: string): string => {
  return Object.values(MARKET_PHASES).find(p => p.name === phase)?.gradient || 'linear-gradient(135deg, #2c3e50, #34495e)'
}

// 获取级别名称
const getLevelName = (key: string): string => {
  const names: Record<string, string> = {
    totalLeader: '总龙头',
    continuousLeader: '连板龙头',
    sectorLeader: '板块龙头',
    middleLeader: '中军龙头',
    emotionLeader: '情绪龙头'
  }
  return names[key] || key
}

// 监听更新事件
onMounted(() => {
  loadData()
  EventManager.on('threshold-multipliers-updated', loadData)
})

onUnmounted(() => {
  EventManager.off('threshold-multipliers-updated', loadData)
})
</script>

<style scoped>
.threshold-panel {
  position: fixed;
  width: 560px;
  max-width: calc(100vw - 40px);
  max-height: 85vh;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
  z-index: 10010;
  font-size: 12px;
  backdrop-filter: blur(10px);
  display: flex;
  flex-direction: column;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-header);
  border-radius: 16px 16px 0 0;
}

.panel-header h3 {
  margin: 0;
  font-size: 16px;
  color: var(--color-highlight);
  display: flex;
  align-items: center;
  gap: 8px;
}

.btn-close {
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

.btn-close:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
  border-color: var(--color-highlight);
}

.panel-content {
  padding: 20px;
  overflow-y: auto;
  max-height: calc(85vh - 120px);
}

.info-tip {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  background: rgba(52, 152, 219, 0.1);
  border: 1px solid rgba(52, 152, 219, 0.3);
  border-radius: 8px;
  margin-bottom: 20px;
  color: var(--text-secondary);
  font-size: 12px;
}

.tip-icon {
  font-size: 14px;
}

.phase-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  margin-bottom: 20px;
  overflow: hidden;
}

.phase-header {
  padding: 12px 16px;
  color: white;
  display: flex;
  align-items: center;
  gap: 8px;
}

.phase-icon {
  font-size: 18px;
}

.phase-name {
  font-size: 14px;
  font-weight: 600;
}

.multiplier-grid {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.multiplier-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.multiplier-item label {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-primary);
}

.slider-container {
  display: flex;
  align-items: center;
  gap: 12px;
}

.slider-container input {
  flex: 1;
  height: 4px;
  -webkit-appearance: none;
  background: var(--bg-primary);
  border-radius: 2px;
  outline: none;
}

.slider-container input::-webkit-slider-thumb {
  -webkit-appearance: none;
  width: 16px;
  height: 16px;
  background: var(--color-highlight);
  border-radius: 50%;
  cursor: pointer;
  transition: all 0.2s;
}

.slider-container input::-webkit-slider-thumb:hover {
  transform: scale(1.2);
}

.slider-container .value {
  min-width: 45px;
  text-align: right;
  font-weight: 600;
  color: var(--color-highlight);
}

.preset-buttons {
  display: flex;
  gap: 8px;
  margin-top: 4px;
}

.preset-btn {
  flex: 1;
  padding: 4px 8px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  color: var(--text-secondary);
  font-size: 11px;
  cursor: pointer;
  transition: all 0.2s;
}

.preset-btn:hover {
  background: var(--bg-hover);
  border-color: var(--color-highlight);
  color: var(--color-highlight);
}

.phase-actions {
  padding: 12px 16px;
  border-top: 1px solid var(--border-color);
  display: flex;
  justify-content: flex-end;
}

.btn-reset {
  padding: 6px 12px;
  background: transparent;
  border: 1px solid var(--border-color);
  border-radius: 4px;
  color: var(--text-secondary);
  font-size: 11px;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-reset:hover {
  background: var(--bg-hover);
  border-color: #ff4757;
  color: #ff4757;
}

.panel-footer {
  display: flex;
  justify-content: space-between;
  padding: 16px 20px;
  border-top: 1px solid var(--border-color);
  background: var(--bg-header);
  border-radius: 0 0 16px 16px;
}

.btn-reset-all {
  padding: 8px 16px;
  background: transparent;
  border: 1px solid var(--border-color);
  border-radius: 20px;
  color: var(--text-secondary);
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-reset-all:hover {
  background: var(--bg-hover);
  border-color: #ff4757;
  color: #ff4757;
}

.btn-save {
  padding: 8px 24px;
  background: linear-gradient(135deg, var(--color-highlight) 0%, #ff9f7f 100%);
  border: none;
  border-radius: 20px;
  color: #000;
  font-weight: 600;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s;
  box-shadow: 0 2px 8px rgba(255, 215, 0, 0.3);
}

.btn-save:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(255, 215, 0, 0.4);
}
</style>