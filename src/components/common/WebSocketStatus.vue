<!-- src/components/common/WebSocketStatus.vue -->
<template>
  <span class="ws-status" :class="statusClass">
    <span class="ws-icon">{{ statusIcon }}</span>
    <span class="ws-text">{{ statusText }}</span>
    <span v-if="subscribedCount > 0" class="ws-count">({{ subscribedCount }})</span>
  </span>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { AppEvents } from '@/types'
import { webSocketService } from '@/services/websocket'
import { EventManager } from '@/utils/eventManager'

const status = ref(webSocketService.getStatus())
let unsubscribe: (() => void) | null = null

function updateStatus() {
  status.value = webSocketService.getStatus()
}

onMounted(() => {
  updateStatus()
  unsubscribe = EventManager.on(AppEvents.WEBSOCKET.STATUS_CHANGED, updateStatus)
})

onUnmounted(() => {
  if (unsubscribe) unsubscribe()
})

const wsPrimaryActive = computed(() => {
  void status.value
  return webSocketService.isPrimaryActive()
})

const tdxRealtimeHealthy = computed(() => {
  void status.value
  return webSocketService.isTdxRealtimeHealthy()
})

const statusIcon = computed(() => {
  if (tdxRealtimeHealthy.value) return '✅'
  if (wsPrimaryActive.value) return '🟡'
  return '🟠'
})

const statusText = computed(() => {
  if (tdxRealtimeHealthy.value) return 'TDX实时'
  if (wsPrimaryActive.value) return 'TDX恢复中'
  return 'HTTP备用'
})

const statusClass = computed(() => {
  if (tdxRealtimeHealthy.value) return 'ws-connected'
  if (wsPrimaryActive.value) return 'ws-recovering'
  return 'ws-fallback'
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

.ws-recovering,
.ws-stale,
.ws-fallback {
  color: #e67e22;
}

.ws-disconnected {
  color: #ff4757;
}

.ws-icon {
  font-size: 12px;
}

.ws-count {
  color: var(--text-secondary);
  font-size: 10px;
}
</style>
