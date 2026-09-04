<!-- src/components/panels/ThemeSortControl.vue -->
<!-- 题材排序控件：多键排序器，配置经 ThemeFacade 持久化并广播给全部题材列表消费方 -->
<template>
  <div class="theme-sort-control" ref="rootRef">
    <button class="sort-trigger" @click.stop="togglePanel" :title="'排序规则：' + summaryText">
      <span class="trigger-icon">⇅</span>
      <span class="trigger-text">{{ summaryText }}</span>
    </button>
    <div v-if="open" class="sort-popover" @click.stop>
      <div class="sort-row" v-for="(step, i) in spec" :key="i">
        <span class="step-index">{{ i + 1 }}</span>
        <select class="field-select" :value="step.field" @change="handleFieldChange(i, $event)">
          <option v-for="f in THEME_SORT_FIELDS" :key="f" :value="f">
            {{ THEME_SORT_FIELD_LABELS[f] }}
          </option>
        </select>
        <button class="dir-btn" @click="toggleDirection(i)">
          {{ step.direction === 'desc' ? '↓ 降序' : '↑ 升序' }}
        </button>
        <button class="remove-btn" @click="removeStep(i)" :disabled="spec.length <= 1" title="移除该键">✕</button>
      </div>
      <div class="sort-actions">
        <button class="action-btn" v-if="spec.length < THEME_SORT_MAX_STEPS" @click="addStep">
          + 添加排序键
        </button>
        <button class="action-btn" @click="resetSpec">恢复默认</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import {
  THEME_SORT_FIELDS,
  THEME_SORT_FIELD_LABELS,
  THEME_SORT_MAX_STEPS,
  type ThemeSortSpec,
  type ThemeSortStep,
} from '@/services/theme/themeSortConfig'
import { themeFacade } from '@/services/theme/ThemeFacade'

const rootRef = ref<HTMLElement>()
const open = ref(false)

const spec = computed<ThemeSortSpec>(() => themeFacade.getThemeSortSpec())

const summaryText = computed(() =>
  spec.value
    .map((step) => `${THEME_SORT_FIELD_LABELS[step.field]}${step.direction === 'desc' ? '↓' : '↑'}`)
    .join('›'),
)

function commit(next: ThemeSortSpec) {
  themeFacade.setThemeSortSpec(next)
}

function togglePanel() {
  open.value = !open.value
}

function handleFieldChange(index: number, event: Event) {
  const nextField = (event.target as HTMLSelectElement).value as ThemeSortStep['field']
  const steps = spec.value.map((step) => ({ ...step }))
  const target = steps[index]
  if (!target || target.field === nextField) return
  // 选择已占用的字段时与该行交换，避免 normalize 静默剔除
  const owner = steps.findIndex((step) => step.field === nextField)
  if (owner >= 0) {
    steps[owner].field = target.field
  }
  target.field = nextField
  commit(steps)
}

function toggleDirection(index: number) {
  const steps = spec.value.map((step) => ({ ...step }))
  const target = steps[index]
  if (!target) return
  target.direction = target.direction === 'desc' ? 'asc' : 'desc'
  commit(steps)
}

function removeStep(index: number) {
  if (spec.value.length <= 1) return
  const steps = spec.value.filter((_, i) => i !== index)
  commit(steps)
}

function addStep() {
  if (spec.value.length >= THEME_SORT_MAX_STEPS) return
  const used = new Set(spec.value.map((step) => step.field))
  const nextField = THEME_SORT_FIELDS.find((field) => !used.has(field))
  if (!nextField) return
  commit([...spec.value, { field: nextField, direction: 'desc' }])
}

function resetSpec() {
  themeFacade.resetThemeSortSpec()
  open.value = false
}

// 点击面板外部时收起下拉
function handleDocClick(event: MouseEvent) {
  if (open.value && rootRef.value && !rootRef.value.contains(event.target as Node)) {
    open.value = false
  }
}

onMounted(() => {
  document.addEventListener('click', handleDocClick, true)
})

onBeforeUnmount(() => {
  document.removeEventListener('click', handleDocClick, true)
})
</script>

<style scoped>
.theme-sort-control {
  position: relative;
  display: inline-flex;
}

.sort-trigger {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  color: var(--text-secondary);
  font-size: 11px;
  cursor: pointer;
  transition: all 0.2s;
  white-space: nowrap;
}

.sort-trigger:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
  border-color: var(--color-highlight);
}

.trigger-icon {
  font-size: 12px;
  line-height: 1;
}

.trigger-text {
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.sort-popover {
  position: absolute;
  top: calc(100% + 6px);
  right: 0;
  z-index: 10010;
  min-width: 240px;
  padding: 10px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.sort-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.step-index {
  width: 16px;
  text-align: center;
  font-size: 10px;
  color: var(--text-secondary);
  flex-shrink: 0;
}

.field-select {
  flex: 1;
  min-width: 0;
  padding: 4px 6px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  color: var(--text-primary);
  font-size: 11px;
  cursor: pointer;
}

.field-select:focus {
  outline: none;
  border-color: var(--color-highlight);
}

.dir-btn,
.remove-btn,
.action-btn {
  padding: 4px 6px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  color: var(--text-secondary);
  font-size: 10px;
  cursor: pointer;
  transition: all 0.2s;
  white-space: nowrap;
}

.dir-btn:hover,
.remove-btn:hover:not(:disabled),
.action-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
  border-color: var(--color-highlight);
}

.remove-btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.sort-actions {
  display: flex;
  gap: 6px;
  justify-content: flex-end;
  padding-top: 2px;
}
</style>
