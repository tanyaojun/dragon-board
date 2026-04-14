<!-- src/components/panels/config/SystemConfig.vue -->
<template>
  <div class="config-section">
    <h4>📋 系统信息</h4>
    <div class="config-item">
      <span class="config-label">版本</span>
      <span class="config-value">{{ config.system.version }}</span>
    </div>
    <div class="config-item">
      <span class="config-label">环境</span>
      <span class="config-value" :class="config.system.env">{{ config.system.env }}</span>
    </div>
    <div class="config-item">
      <span class="config-label">调试模式</span>
      <span class="config-value">{{ config.system.debug ? '✅ 开启' : '❌ 关闭' }}</span>
    </div>
  </div>

  <div class="config-section">
    <h4>🌐 网络配置</h4>
    <div class="config-item">
      <span class="config-label">代理地址</span>
      <input 
        type="text" 
        class="config-input" 
        v-model="local.system.proxyUrl"
        @input="emitChange"
      >
    </div>
    <div class="config-item">
      <span class="config-label">超时时间</span>
      <input 
        type="number" 
        class="config-input" 
        v-model.number="local.system.timeout"
        @input="emitChange"
      >
      <span class="config-unit">ms</span>
    </div>
    <div class="config-item">
      <span class="config-label">重试次数</span>
      <input 
        type="number" 
        class="config-input" 
        v-model.number="local.system.retryCount"
        @input="emitChange"
      >
    </div>
    <div class="config-item">
      <span class="config-label">WebSocket模拟</span>
      <label class="switch">
        <input 
          type="checkbox" 
          v-model="local.system.useMockWebSocket"
          @change="emitChange"
        >
        <span class="slider round"></span>
      </label>
      <span class="config-hint">开发测试用</span>
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

function emitChange() {
  emit('change', { system: local.value.system })
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

.config-value.development {
  color: #2ed573;
}

.config-value.production {
  color: #ff4757;
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

.config-hint {
  margin-left: 10px;
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