<!-- src/components/common/EventMonitor.vue -->
<template>
  <Teleport to="body">
    <div v-if="visible" class="event-monitor" :style="panelStyle" ref="panelRef">
      <div class="monitor-header">
        <h3>📡 事件监控</h3>
        <button class="close-btn" @click="close">✕</button>
      </div>
      
      <div class="monitor-content">
        <!-- 统计卡片 -->
        <div class="stats-grid">
          <div class="stat-card">
            <span class="stat-label">总事件数</span>
            <span class="stat-value">{{ totalEvents }}</span>
          </div>
          <div class="stat-card">
            <span class="stat-label">监听器数</span>
            <span class="stat-value">{{ listenerCount }}</span>
          </div>
          <div class="stat-card">
            <span class="stat-label">历史记录</span>
            <span class="stat-value">{{ history.length }}</span>
          </div>
          <div class="stat-card">
            <span class="stat-label">事件类型</span>
            <span class="stat-value">{{ eventTypes }}</span>
          </div>
        </div>

        <!-- 事件统计 -->
        <div class="section">
          <div class="section-title">📊 事件统计</div>
          <div class="stats-list">
            <div v-for="(stat, event) in eventStats" :key="event" class="stat-row">
              <span class="stat-event">{{ event }}</span>
              <span class="stat-count">{{ stat.count }}次</span>
              <span class="stat-time">{{ stat.lastTime }}</span>
            </div>
          </div>
        </div>

        <!-- 实时事件流 -->
        <div class="section">
          <div class="section-title">
            <span>📋 实时事件流</span>
            <button class="clear-btn" @click="clearHistory">清除</button>
          </div>
          <div class="event-stream" ref="streamRef">
            <div v-for="(item, index) in displayHistory" :key="index" class="event-item">
              <span class="event-time">{{ formatTime(item.timestamp) }}</span>
              <span class="event-name">{{ item.event }}</span>
              <span class="event-data">{{ formatData(item.data) }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { EventManager } from '@/utils/eventManager'

const props = defineProps<{
  visible: boolean
  triggerRect?: DOMRect
}>()

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
}>()

const history = ref<any[]>([])
const streamRef = ref<HTMLElement>()

// 计算属性
const totalEvents = computed(() => {
  const stats = EventManager.getStats()
  return Object.values(stats).reduce((sum, s) => sum + s.count, 0)
})

const listenerCount = computed(() => EventManager.getListenerCount())

const eventTypes = computed(() => {
  const stats = EventManager.getStats()
  return Object.keys(stats).length
})

const eventStats = computed(() => EventManager.getStats())

const displayHistory = computed(() => history.value.slice(-50).reverse())

// 样式
const panelStyle = computed(() => ({
  position: 'fixed',
  top: props.triggerRect ? props.triggerRect.bottom + 5 + 'px' : '100px',
  right: props.triggerRect
    ? Math.max(10, window.innerWidth - props.triggerRect.right) + 'px'
    : '20px',
  width: '500px',
  maxHeight: '80vh',
  overflow: 'auto',
}))

// 工具函数
function formatTime(timestamp: number): string {
  const date = new Date(timestamp)
  return `${date.getHours().toString().padStart(2, '0')}:${date.getMinutes().toString().padStart(2, '0')}:${date.getSeconds().toString().padStart(2, '0')}`
}

function formatData(data: any): string {
  if (!data) return ''
  if (typeof data === 'object') {
    try {
      return JSON.stringify(data).slice(0, 50)
    } catch {
      return String(data)
    }
  }
  return String(data).slice(0, 50)
}

function clearHistory() {
  EventManager.clearHistory()
  updateHistory()
}

function updateHistory() {
  history.value = EventManager.getHistory()
  
  // 自动滚动到底部
  setTimeout(() => {
    if (streamRef.value) {
      streamRef.value.scrollTop = streamRef.value.scrollHeight
    }
  }, 100)
}

function close() {
  emit('update:visible', false)
}

// 生命周期
onMounted(() => {
  updateHistory()
  
  // 每秒更新
  const timer = setInterval(updateHistory, 1000)
  
  onUnmounted(() => {
    clearInterval(timer)
  })
})
</script>

<style scoped>
.event-monitor {
  position: fixed;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
  z-index: 10020;
  font-size: 12px;
  backdrop-filter: blur(10px);
}

.monitor-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-header);
}

.monitor-header h3 {
  margin: 0;
  font-size: 16px;
  color: var(--color-highlight);
}

.close-btn {
  width: 32px;
  height: 32px;
  border: 1px solid var(--border-color);
  background: transparent;
  border-radius: 8px;
  color: var(--text-secondary);
  cursor: pointer;
}

.close-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.monitor-content {
  padding: 20px;
  max-height: calc(80vh - 70px);
  overflow-y: auto;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
  margin-bottom: 20px;
}

.stat-card {
  padding: 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  text-align: center;
}

.stat-label {
  display: block;
  font-size: 10px;
  color: var(--text-secondary);
  margin-bottom: 4px;
}

.stat-value {
  font-size: 18px;
  font-weight: bold;
  color: var(--text-primary);
}

.section {
  margin-bottom: 20px;
}

.section-title {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 14px;
  font-weight: 500;
  color: var(--text-title);
  margin-bottom: 12px;
}

.stats-list {
  max-height: 200px;
  overflow-y: auto;
}

.stat-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px;
  border-bottom: 1px solid var(--border-color);
  font-size: 11px;
}

.stat-row:last-child {
  border-bottom: none;
}

.stat-event {
  flex: 2;
  color: var(--text-primary);
  font-family: monospace;
}

.stat-count {
  flex: 1;
  color: var(--color-highlight);
  text-align: center;
}

.stat-time {
  flex: 1;
  color: var(--text-secondary);
  text-align: right;
}

.event-stream {
  height: 300px;
  overflow-y: auto;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 8px;
}

.event-item {
  padding: 6px;
  border-bottom: 1px solid var(--border-color);
  font-size: 10px;
  font-family: monospace;
}

.event-item:last-child {
  border-bottom: none;
}

.event-time {
  color: var(--text-secondary);
  margin-right: 8px;
}

.event-name {
  color: var(--color-highlight);
  font-weight: 500;
  margin-right: 8px;
}

.event-data {
  color: var(--text-tertiary);
}

.clear-btn {
  padding: 4px 8px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  font-size: 10px;
  color: var(--text-secondary);
  cursor: pointer;
}

.clear-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}
</style>