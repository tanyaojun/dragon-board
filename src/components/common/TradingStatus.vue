<!-- src/components/common/TradingStatus.vue -->
<template>
  <div class="trading-status" :class="{ active: isTradingTime }">
    <span class="status-dot"></span>
    <span class="status-text">{{ isTradingTime ? '交易中' : '已收盘' }}</span>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  time?: Date
}>()

const isTradingTime = computed(() => {
  const now = props.time || new Date()
  const day = now.getDay()
  const hour = now.getHours()
  const minute = now.getMinutes()
  const time = hour * 100 + minute
  
  // 周末休市
  if (day === 0 || day === 6) return false
  
  // 交易时间：9:30-11:30, 13:00-15:00
  return (time >= 930 && time <= 1130) || (time >= 1300 && time <= 1500)
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