<!-- src/components/panels/config/UserConfig.vue -->
<template>
  <div class="config-section">
    <h4>🎨 主题设置</h4>
    <div class="config-item">
      <span class="config-label">当前主题</span>
      <select class="config-select" v-model="local.user.theme" @change="emitChange">
        <option value="dark">暗黑</option>
        <option value="light">明亮</option>
        <option value="matrix">矩阵</option>
        <option value="cream">淡黄</option>
      </select>
    </div>
    <div class="config-item">
      <span class="config-label">跟随系统</span>
      <label class="switch">
        <input type="checkbox" v-model="local.user.followSystemTheme" @change="emitChange">
        <span class="slider round"></span>
      </label>
    </div>
  </div>

  <div class="config-section">
    <h4>🔄 刷新设置</h4>
    <div class="config-item">
      <span class="config-label">刷新策略</span>
      <select class="config-select" v-model="local.user.refreshStrategy" @change="emitChange">
        <option value="balanced">平衡型</option>
        <option value="aggressive">激进型</option>
        <option value="conservative">保守型</option>
        <option value="recovery">恢复模式</option>
      </select>
    </div>
    <div class="config-item">
      <span class="config-label">自动刷新</span>
      <label class="switch">
        <input type="checkbox" v-model="local.user.refreshEnabled" @change="emitChange">
        <span class="slider round"></span>
      </label>
    </div>
    <div class="config-item">
      <span class="config-label">交易时间限制</span>
      <label class="switch">
        <input type="checkbox" v-model="local.user.tradingTimeOnly" @change="emitChange">
        <span class="slider round"></span>
      </label>
    </div>
    <div class="config-item">
      <span class="config-label">全量间隔</span>
      <input 
        type="number" 
        class="config-input" 
        v-model.number="fullIntervalMinutes"
        @input="updateFullInterval"
        min="5"
        max="240"
      >
      <span class="config-unit">分钟</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, computed } from 'vue'

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

const fullIntervalMinutes = computed({
  get: () => Math.round(local.value.user.fullRefreshInterval / 60000),
  set: (val) => { local.value.user.fullRefreshInterval = val * 60000 }
})

function updateFullInterval() {
  local.value.user.fullRefreshInterval = fullIntervalMinutes.value * 60000
  emitChange()
}

function emitChange() {
  emit('change', { user: local.value.user })
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

.config-value {
  flex: 1;
  color: var(--text-primary);
  font-weight: 500;
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

.config-input {
  width: 200px;
  padding: 6px 10px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  color: var(--text-primary);
  font-size: 12px;
}

.config-input:focus {
  border-color: var(--color-highlight);
  outline: none;
}

.config-unit {
  margin-left: 8px;
  color: var(--text-secondary);
  font-size: 11px;
}

.switch {
  position: relative;
  display: inline-block;
  width: 48px;
  height: 24px;
  margin-right: 8px;
}

.switch input {
  opacity: 0;
  width: 0;
  height: 0;
}

.slider {
  position: absolute;
  cursor: pointer;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: var(--border-color);
  transition: .3s;
  border-radius: 24px;
}

.slider:before {
  position: absolute;
  content: "";
  height: 20px;
  width: 20px;
  left: 2px;
  bottom: 2px;
  background-color: white;
  transition: .3s;
  border-radius: 50%;
}

input:checked + .slider {
  background-color: var(--color-highlight);
}

input:checked + .slider:before {
  transform: translateX(24px);
}
</style>
