<!-- src/components/common/TradingStatus.vue -->
<template>
  <div
    class="trading-status"
    :class="{ active: ['trading', 'call_auction', 'after_hours'].includes(status) }"
  >
    <span class="status-dot"></span>
    <span class="status-text">{{ statusLabel }}</span>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { getTradingStatus, refreshCalendar, TRADING_STATUS_LABEL } from '@/utils/time'
import type { TradingStatus } from '@/utils/time'

const props = defineProps<{
  time?: Date
}>()

const clockTick = ref(Date.now())
let clockTimer: ReturnType<typeof setInterval> | null = null

const status = computed<TradingStatus>(() => {
  const current = props.time || new Date(clockTick.value)
  return getTradingStatus(current)
})
const statusLabel = computed(() => TRADING_STATUS_LABEL[status.value])

onMounted(() => {
  const refresh = async () => {
    await refreshCalendar(props.time || new Date())
    clockTick.value = Date.now()
  }
  void refresh()
  clockTimer = setInterval(() => {
    clockTick.value = Date.now()
    void refresh()
  }, 60_000)
})

onUnmounted(() => {
  if (clockTimer) clearInterval(clockTimer)
})
</script>

<style scoped>
.trading-status {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  background-color: var(--badge-bg);
  border-radius: 20px;
  font-size: 12px;
  color: var(--text-secondary);
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background-color: var(--text-secondary);
  transition: all 0.3s ease;
}

.trading-status.active .status-dot {
  background-color: var(--color-success);
  box-shadow: 0 0 8px var(--color-success);
}

.trading-status.active .status-text {
  color: var(--color-success);
}
</style>
