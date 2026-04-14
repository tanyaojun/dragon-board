<!-- src/components/common/WebSocketStatus.vue -->
<template>
  <span class="ws-status" :class="statusClass">
    <span class="ws-icon">{{ statusIcon }}</span>
    <span class="ws-text">{{ statusText }}</span>
    <span v-if="subscribedCount > 0" class="ws-count">({{ subscribedCount }})</span>
  </span>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { webSocketService } from '@/services/websocket'
import { EventManager } from '@/utils/eventManager'

const status = ref(webSocketService.getStatus())
let interval: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  updateStatus()
  interval = setInterval(updateStatus, 1000)

  // 监听 WebSocket 事件
  EventManager.on('ws:connected', updateStatus)
})

onUnmounted(() => {
  if (interval) clearInterval(interval)
})

function updateStatus() {
  status.value = webSocketService.getStatus()
}

const statusIcon = computed(() => {
  switch (status.value.status) {
    case 'connected': return '✅'
    case 'connecting': return '⏳'
    case 'mock': return '🎮'
    default: return '❌'
  }
})

const statusText = computed(() => {
  switch (status.value.status) {
    case 'connected': return '实时'
    case 'connecting': return '连接中'
    case 'mock': return '模拟'
    default: return '已断开'
  }
})

const statusClass = computed(() => {
  return `ws-${status.value.status}`
})

const subscribedCount = computed(() => status.value.subscribedCount)
</script>

<style scoped>
.ws-status {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: 12px;
  font-size: 11px;
  background: var(--bg-secondary);
}

.ws-connected {
  color: #2ed573;
}

.ws-connecting {
  color: #ffa502;
}

.ws-disconnected {
  color: #ff4757;
}

.ws-mock {
  color: #9b59b6;
}

.ws-icon {
  font-size: 12px;
}

.ws-count {
  color: var(--text-secondary);
  font-size: 10px;
}
</style>
