<!-- src/components/panels/risk/StageBlock.vue -->
<template>
  <div class="stage-block">
    <div class="stage-header" @click="$emit('toggle')">
      <div class="header-left">
        <span class="stage-icon">{{ icon }}</span>
        <span class="stage-name">{{ stage }}</span>
        <span class="stage-count">{{ themes.length }}</span>
      </div>
      <span class="toggle">{{ expanded ? '▼' : '▶' }}</span>
    </div>

    <div v-show="expanded" class="stage-body">
      <div v-for="theme in themes" :key="theme.name" class="theme-item">
        <div class="theme-title">{{ theme.name }}</div>
        <slot :theme="theme"></slot>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  stage: string
  icon: string
  themes: any[]
  expanded: boolean
  phase?: any
}>()

defineEmits<{
  (e: 'toggle'): void
}>()
</script>

<style scoped>
.stage-block {
  margin-bottom: 8px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  overflow: hidden;
}

.stage-header {
  padding: 10px 12px;
  background: var(--bg-header);
  display: flex;
  justify-content: space-between;
  align-items: center;
  cursor: pointer;
}

.stage-header:hover {
  background: var(--bg-hover);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.stage-icon {
  font-size: 14px;
}

.stage-name {
  font-size: 13px;
  font-weight: 500;
}

.stage-count {
  font-size: 11px;
  padding: 2px 6px;
  background: var(--bg-primary);
  border-radius: 12px;
  color: var(--text-secondary);
}

.toggle {
  font-size: 11px;
  color: var(--text-tertiary);
}

.stage-body {
  padding: 12px;
  background: var(--bg-primary);
}

.theme-item {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 8px;
}

.theme-item:last-child {
  margin-bottom: 0;
}

.theme-title {
  font-weight: 500;
  margin-bottom: 8px;
  font-size: 13px;
}
</style>