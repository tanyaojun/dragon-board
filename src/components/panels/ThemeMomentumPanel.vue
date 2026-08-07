<!-- src/components/panels/ThemeMomentumPanel.vue -->
<!-- 题材动量 v2 面板外壳：浮窗模式（Teleport + usePanel）与嵌入式模式共用 ThemeMomentumBody -->

<template>
  <Teleport to="body" v-if="!embedded">
    <div v-if="visible" class="theme-momentum-frame" :style="panelStyle" ref="panelRef">
      <div class="frame-header">
        <div class="header-left">
          <h3>📊 题材动量 <span class="version-badge">v{{ version }}</span></h3>
          <div class="stats-badge" v-if="summary">
            <span>强势 {{ stats.up }}</span><span class="dot">·</span>
            <span>退潮 {{ stats.down }}</span><span class="dot">·</span>
            <span>中性 {{ stats.neutral }}</span>
          </div>
        </div>
        <div class="panel-actions">
          <button class="btn-icon" @click.stop="loadData(true)" :class="{ loading }" title="刷新">
            <span :class="{ 'rotate-animation': loading }">🔄</span>
          </button>
          <button class="btn-icon" @click.stop="close" title="关闭">✕</button>
        </div>
      </div>
      <ThemeMomentumBody :summary="summary" :loading="loading" :error="error" :computed-at-text="computedAtText"
        @retry="loadData(true)" />
    </div>
  </Teleport>

  <!-- 嵌入式模式：直接渲染到父容器（题材树形面板内），无浮窗外壳 -->
  <ThemeMomentumBody v-else :summary="summary" :loading="loading" :error="error" :computed-at-text="computedAtText"
    @retry="loadData(true)" />
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import { usePanel } from '@/composables/usePanel'
import ThemeMomentumBody from './ThemeMomentumBody.vue'
import {
  themeFacade,
  type ThemeMomentumSummary,
} from '@/services/theme/ThemeFacade'
import { DEFAULT_RANK_TREND_SNAPSHOT_TYPE } from '@/types/rankTrendDefaults'

const props = defineProps<{
  visible?: boolean
  triggerRect?: DOMRect
  /** 嵌入模式：不使用 Teleport/浮窗外壳，直接流式渲染到父容器（题材树形面板内） */
  embedded?: boolean
}>()

const emit = defineEmits<{ (event: 'close'): void; (event: 'update:visible', value: boolean): void }>()

const version = '1.0.0'
const { panelRef, panelStyle } = usePanel({
  name: 'ThemeMomentumPanel',
  visible: props.visible ?? false,
  triggerRect: props.triggerRect,
  onClose: close,
})

const loading = ref(false)
const error = ref<string | null>(null)
const summary = ref<ThemeMomentumSummary | null>(null)

const stats = computed(() => {
  const factors = summary.value?.factors || []
  return {
    up: factors.filter((f) => f.direction === 'up').length,
    down: factors.filter((f) => f.direction === 'down').length,
    neutral: factors.filter((f) => f.direction === 'neutral').length,
  }
})

const computedAtText = computed(() => {
  const ts = summary.value?.computedAt
  if (!ts) return ''
  const date = new Date(ts)
  if (Number.isNaN(date.getTime())) return ''
  return `${date.getMonth() + 1}-${date.getDate()} ${String(date.getHours()).padStart(2, '0')}:${String(
    date.getMinutes(),
  ).padStart(2, '0')}`
})

async function loadData(force = false) {
  if (loading.value && !force) return
  loading.value = true
  error.value = null
  try {
    const result = await themeFacade.getThemeMomentumSummary({
      snapshotType: DEFAULT_RANK_TREND_SNAPSHOT_TYPE,
    })
    if (result) summary.value = result
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

function close() {
  emit('close')
  emit('update:visible', false)
}

onMounted(() => {
  if (props.visible || props.embedded) loadData()
})

// 浮窗常驻挂载（Teleport 到 body），visible 变化时按需加载/刷新
watch(
  () => props.visible,
  (visible) => {
    if (visible) loadData()
  },
)
</script>

<style scoped>
/* ========== 浮窗外壳（非嵌入模式） ========== */
.theme-momentum-frame {
  position: fixed;
  z-index: 1001;
  width: 1080px;
  max-width: calc(100vw - 32px);
  max-height: min(82vh, 760px);
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.45);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  color: var(--text-primary);
  font-size: 13px;
}

.frame-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-header, var(--bg-secondary));
  flex-shrink: 0;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.frame-header h3 {
  margin: 0;
  font-size: 14px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  color: var(--text-title);
}

.version-badge {
  font-size: 10px;
  background: var(--bg-tertiary, var(--bg-secondary));
  color: var(--text-secondary);
  border-radius: 4px;
  padding: 1px 5px;
  vertical-align: middle;
}

.stats-badge {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--text-secondary);
}

.dot {
  opacity: 0.5;
}

.panel-actions {
  display: flex;
  gap: 6px;
}

.btn-icon {
  width: 28px;
  height: 28px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  color: var(--text-secondary);
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
}

.btn-icon:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
  border-color: var(--color-highlight);
}

.rotate-animation {
  display: inline-block;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
