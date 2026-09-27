<template>
  <div class="sector-rotation-tab">
    <div class="rotation-toolbar">
      <span class="rotation-updated">{{ dataTimeText }}</span>
      <button class="refresh-btn" :class="{ loading }" title="刷新" @click="loadData(true)">
        <span :class="{ 'rotate-animation': loading }">🔄</span>
      </button>
    </div>

    <div v-if="error" class="rotation-error">
      <span>⚠️</span>
      <span>{{ error }}</span>
      <button class="retry-btn" @click="loadData(true)">重试</button>
    </div>
    <div v-else-if="!summary" class="rotation-empty">
      <span>{{ loading ? '加载中…' : '暂无轮动数据' }}</span>
      <button v-if="!loading" class="retry-btn" @click="loadData(true)">重试</button>
    </div>

    <template v-else>
      <section class="rotation-summary">
        <div class="summary-row phase-row">
          <span class="phase-badge" :class="phaseTone">{{ phaseLabel }}</span>
          <span class="summary-metric">轮动速度 {{ formatNumber(rotationSummary?.rotationSpeed, 2) }}</span>
          <span class="summary-metric">主线集中度 {{ formatPercent(rotationSummary?.mainlineConcentration) }}</span>
          <span class="summary-metric">最高连板 {{ formatNumber(rotationSummary?.maxBoardHeight, 0) }}</span>
        </div>
        <div class="summary-row">
          <span class="row-label">主线</span>
          <template v-if="mainLineNames.length">
            <span v-for="name in mainLineNames" :key="name" class="theme-chip chip-mainline">{{ name }}</span>
          </template>
          <span v-else class="no-mainline">引擎判定无主线</span>
        </div>
      </section>

      <section class="rotation-tree-section">
        <SectorRotationTree
          :statuses="statuses"
          :category="stateFilter"
          @update:category="stateFilter = $event"
        />
      </section>


    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  getRotationSummary,
  type ThemeRotationStatusRow,
  type ThemeRotationSummary,
} from '@/services/theme/ThemeFacade'
import { MARKET_PHASE_META, marketPhaseLabel, type RotationCategory } from '@/services/theme/rotationDisplay'
import SectorRotationTree from './SectorRotationTree.vue'

const loading = ref(false)
const error = ref<string | null>(null)
const summary = ref<ThemeRotationSummary | null>(null)
const stateFilter = ref<RotationCategory>('all')

async function loadData(force = false) {
  if (loading.value && !force) return
  loading.value = true
  error.value = null
  try {
    const result = await getRotationSummary({ snapshotType: 'half_hour' })
    if (result) summary.value = result
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  if (!summary.value) loadData()
})

const rotationSummary = computed(() => summary.value?.frame.rotationSummary ?? null)
const dataTimeText = computed(() => {
  const frame = summary.value?.frame
  return frame ? `数据 ${frame.tradingDate} ${frame.slotTime}` : '未加载'
})
const phaseLabel = computed(() => marketPhaseLabel(rotationSummary.value?.marketPhase))
const phaseTone = computed(() => {
  const phase = rotationSummary.value?.marketPhase
  return (phase && MARKET_PHASE_META[phase]?.tone) || 'phase-unknown'
})
const mainLineNames = computed(() => rotationSummary.value?.mainLines.map((m) => m.themeName) ?? [])
const statuses = computed(() => summary.value?.statuses ?? [])
function formatNumber(value: number | null | undefined, digits = 1): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : '—'
}

function formatPercent(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? `${(value * 100).toFixed(2)}%` : '—'
}

</script>

<style scoped>
.sector-rotation-tab {
  display: flex;
  flex-direction: column;
  gap: 10px;
  height: 100%;
  overflow-y: auto;
}
.rotation-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.rotation-updated {
  font-size: 12px;
  color: var(--text-secondary, #9aa5b1);
}
.refresh-btn,
.retry-btn,
.table-toggle {
  background: var(--bg-tertiary, transparent);
  border: 1px solid var(--border-color);
  color: var(--text-primary);
  border-radius: 4px;
  padding: 3px 10px;
  cursor: pointer;
  font-size: 12px;
}
.refresh-btn:hover,
.retry-btn:hover,
.table-toggle:hover {
  border-color: var(--accent-color, #4a9eff);
}
.rotation-error,
.rotation-empty {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 16px;
  color: var(--text-secondary, #9aa5b1);
  font-size: 13px;
}
.rotation-summary {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px 12px;
  background: var(--bg-secondary, rgba(255, 255, 255, 0.03));
  border: 1px solid var(--border-color);
  border-radius: 6px;
}
.summary-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  font-size: 12px;
}
.row-label {
  color: var(--text-secondary, #9aa5b1);
  min-width: 30px;
}
.phase-badge {
  padding: 2px 10px;
  border-radius: 10px;
  font-weight: 600;
  border: 1px solid var(--border-color);
}
.phase-cooling { color: #5ba3f5; border-color: #5ba3f5; }
.phase-climax { color: #f55b5b; border-color: #f55b5b; }
.phase-rising { color: #f58b5b; border-color: #f58b5b; }
.phase-ice { color: #7fd4ff; border-color: #7fd4ff; }
.phase-chaos { color: #d4a0ff; border-color: #d4a0ff; }
.phase-neutral { color: var(--text-primary); }
.phase-unknown { color: var(--text-secondary, #9aa5b1); }
.summary-metric {
  color: var(--text-primary);
}
.theme-chip {
  padding: 1px 8px;
  border-radius: 8px;
  border: 1px solid var(--border-color);
}
.chip-mainline { color: #f5c15b; border-color: #f5c15b; }
.rotate-animation { display: inline-block; animation: rotation-spin 1s linear infinite; }
@keyframes rotation-spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
