<!-- src/components/panels/config/CacheConfig.vue -->
<template>
  <div class="config-section">
    <h4>📦 缓存统计</h4>
    <div class="config-item">
      <span class="config-label">股票缓存</span>
      <span class="config-value">{{ cacheStats.stock }} 条</span>
    </div>
    <div class="config-item">
      <span class="config-label">龙头缓存</span>
      <span class="config-value">{{ cacheStats.leader }} 条</span>
    </div>
    <div class="config-item">
      <span class="config-label">题材缓存</span>
      <span class="config-value">{{ cacheStats.sector }} 条</span>
    </div>
    <div class="config-item">
      <span class="config-label">行情缓存</span>
      <span class="config-value">{{ cacheStats.quote }} 条</span>
    </div>
  </div>

  <div class="config-section">
    <h4>⚙️ 缓存参数</h4>
    <div v-for="(value, key) in config.cache" :key="key" class="config-item">
      <span class="config-label">{{ key }}</span>
      <span class="config-value">容量: {{ value.capacity }}, TTL: {{ value.ttl / 60000 }}分钟</span>
    </div>
  </div>

  <div class="config-actions">
    <button class="btn" @click="clearAllCache">🧹 清空所有缓存</button>
    <button class="btn" @click="clearStockCache">📦 清空股票缓存</button>
    <button class="btn" @click="clearQuoteCache">📊 清空行情缓存</button>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { EventManager } from '@/utils/eventManager'
import { AppEvents } from '@/types'

const props = defineProps<{
  config: any
}>()

const emit = defineEmits<{
  (e: 'change', data: any): void
}>()

const cacheStats = ref({
  stock: 0,
  leader: 0,
  sector: 0,
  quote: 0,
})

function clearAllCache() {
  // TODO: 调用 LRUCache
  EventManager.emit(AppEvents.UI.TOAST, {
    message: '🧹 所有缓存已清空',
    duration: 1500,
    type: 'success',
  })
}

function clearStockCache() {
  EventManager.emit(AppEvents.UI.TOAST, {
    message: '📦 股票缓存已清空',
    duration: 1500,
    type: 'success',
  })
}

function clearQuoteCache() {
  EventManager.emit(AppEvents.UI.TOAST, {
    message: '📊 行情缓存已清空',
    duration: 1500,
    type: 'success',
  })
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

.config-actions {
  display: flex;
  gap: 8px;
  margin-top: 16px;
}

.btn {
  flex: 1;
  padding: 8px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  color: var(--text-primary);
  cursor: pointer;
  font-size: 12px;
}

.btn:hover {
  background: var(--bg-hover);
  border-color: var(--color-highlight);
}
</style>
