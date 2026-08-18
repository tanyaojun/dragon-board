<script setup lang="ts">
/**
 * 档位徽章（2026-08-18 全量图标化替换）。
 *
 * S/A/B/C/D/E 档位用语义 SVG 图标（lucide 风格，ISC 许可可内联）替代字母：
 * S=flame（火焰·强买）/ A=arrow-up（上箭头·买入）/ B=trending-up（折线上行·弱买）/
 * C=minus（横线·中性）/ D=trending-down（折线下行·回避）/ E=ban（禁止·否决）。
 * 颜色沿用 tierBadgeClass（tier-s/a/b/c/d/e），stroke 继承 currentColor。
 */
import { computed } from 'vue'
import type { RankTrendSignalTier } from '@/services/rankTrend/types'
import { tierBadgeClass } from '@/services/rankTrend/tierDisplay'

const props = defineProps<{ tier: RankTrendSignalTier | null | undefined }>()

const badgeClass = computed(() => tierBadgeClass(props.tier))
const showIcon = computed(() => props.tier && props.tier !== 'unknown')
</script>

<template>
  <span class="tier-badge" :class="badgeClass">
    <svg
      v-if="showIcon"
      class="tier-icon"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="2"
      stroke-linecap="round"
      stroke-linejoin="round"
      aria-hidden="true"
    >
      <!-- S: flame -->
      <template v-if="tier === 'S'">
        <path d="M12 3q1 4 4 6.5t3 5.5a1 1 0 0 1-14 0 5 5 0 0 1 1-3 1 1 0 0 0 5 0c0-2-1.5-3-1.5-5q0-2 2.5-4" />
      </template>
      <!-- A: arrow-up -->
      <template v-else-if="tier === 'A'">
        <path d="m5 12 7-7 7 7" />
        <path d="M12 19V5" />
      </template>
      <!-- B: trending-up -->
      <template v-else-if="tier === 'B'">
        <path d="M16 7h6v6" />
        <path d="m22 7-8.5 8.5-5-5L2 17" />
      </template>
      <!-- C: minus -->
      <template v-else-if="tier === 'C'">
        <path d="M5 12h14" />
      </template>
      <!-- D: trending-down -->
      <template v-else-if="tier === 'D'">
        <path d="M16 17h6v-6" />
        <path d="m22 17-8.5-8.5-5 5L2 7" />
      </template>
      <!-- E: ban -->
      <template v-else-if="tier === 'E'">
        <circle cx="12" cy="12" r="10" />
        <path d="M4.929 4.929 19.07 19.071" />
      </template>
    </svg>
    <template v-else>--</template>
  </span>
</template>
