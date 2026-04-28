<!-- src/components/common/LeaderBadge.vue -->
<template>
  <span v-if="stock.isSectorLeader" class="leader-badge" :style="badgeStyle" :title="badgeTitle">
    {{ levelConfig?.icon }} {{ levelConfig?.name }}
    <span
      v-if="stock.leaderLevel === '连板龙头' && stock.continuousDays > 1"
      class="continuous-days"
      :style="{ background: levelConfig?.color }"
    >
      {{ stock.continuousDays }}
    </span>
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { Stock } from '@/types'

const props = defineProps<{
  stock: Stock
}>()

const leaderLevels: Record<string, { icon: string; name: string; color: string; bg: string }> = {
  总龙头: {
    icon: '👑',
    name: '总龙头',
    color: '#FFD700',
    bg: 'rgba(255, 215, 0, 0.1)',
  },
  连板龙头: {
    icon: '📈',
    name: '连板龙头',
    color: '#e74c3c',
    bg: 'rgba(231, 76, 60, 0.1)',
  },
  板块龙头: {
    icon: '🏆',
    name: '板块龙头',
    color: '#3498db',
    bg: 'rgba(52, 152, 219, 0.1)',
  },
  中军龙头: {
    icon: '⚔️',
    name: '中军龙头',
    color: '#9b59b6',
    bg: 'rgba(155, 89, 182, 0.1)',
  },
  情绪龙头: {
    icon: '🔥',
    name: '情绪龙头',
    color: '#f39c12',
    bg: 'rgba(243, 156, 18, 0.1)',
  },
}

const levelConfig = computed(() => {
  if (!props.stock.isSectorLeader) return null
  return leaderLevels[props.stock.leaderLevel] || leaderLevels['板块龙头']
})

const badgeStyle = computed(() => {
  if (!levelConfig.value) return {}
  return {
    color: levelConfig.value.color,
    background: levelConfig.value.bg,
    borderColor: `${levelConfig.value.color}30`,
  }
})

const badgeTitle = computed(() => {
  if (!props.stock.isSectorLeader) return ''
  const reasons = (props.stock as any).leaderReasons || []
  return reasons.length > 0
    ? reasons.join('\n')
    : `${props.stock.leaderLevel} · 评分${Math.round(props.stock.leaderScore || 0)}`
})
</script>

<style scoped>
.leader-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: 12px;
  font-size: 11px;
  font-weight: 500;
  white-space: nowrap;
  cursor: help;
  transition: all 0.2s;
  border: 1px solid transparent;
  margin: 0 2px;
  line-height: 1.4;
}

.leader-badge:hover {
  transform: translateY(-1px);
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
}

.continuous-days {
  display: inline-block;
  padding: 0px 6px;
  border-radius: 10px;
  color: white;
  font-size: 10px;
  font-weight: bold;
  margin-left: 2px;
}
</style>
