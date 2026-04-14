<!-- src/components/panels/risk/RiskBlock.vue -->
<template>
  <div class="risk-block">
    <div class="risk-header" @click="$emit('toggle')">
      <div class="header-left">
        <span class="risk-icon">{{ icon }}</span>
        <span class="risk-title">{{ title }}</span>
        <span class="risk-count">{{ risks.length }}</span>
      </div>
      <span class="toggle">{{ expanded ? '▼' : '▶' }}</span>
    </div>

    <div v-show="expanded" class="risk-body">
      <div v-for="risk in risks" :key="risk.id" class="risk-item" :class="level">
        <div class="risk-main">
          <span class="risk-name">{{ risk.name || risk.title }}</span>
          <span class="risk-desc">{{ risk.message || risk.desc }}</span>
        </div>
        <div class="risk-action">
          <span class="risk-advice">{{ risk.action || risk.advice }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  title: string
  icon: string
  risks: any[]
  expanded: boolean
  level: string
}>()

defineEmits<{
  (e: 'toggle'): void
}>()
</script>

<style scoped>
.risk-block {
  margin-bottom: 8px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  overflow: hidden;
}

.risk-header {
  padding: 10px 12px;
  background: var(--bg-header);
  display: flex;
  justify-content: space-between;
  align-items: center;
  cursor: pointer;
}

.risk-header:hover {
  background: var(--bg-hover);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.risk-icon {
  font-size: 14px;
}

.risk-title {
  font-size: 13px;
  font-weight: 500;
}

.risk-count {
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

.risk-body {
  padding: 12px;
  background: var(--bg-primary);
}

.risk-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 12px;
  margin-bottom: 6px;
  background: var(--bg-secondary);
  border-left: 3px solid transparent;
  border-radius: 6px;
}

.risk-item:last-child {
  margin-bottom: 0;
}

.risk-item.critical {
  border-left-color: #ff4757;
}

.risk-item.warning {
  border-left-color: #f39c12;
}

.risk-item.info {
  border-left-color: #3498db;
}

.risk-main {
  flex: 1;
}

.risk-name {
  display: block;
  font-weight: 500;
  margin-bottom: 2px;
}

.risk-desc {
  font-size: 11px;
  color: var(--text-secondary);
}

.risk-action {
  font-size: 11px;
  padding: 4px 8px;
  background: var(--bg-primary);
  border-radius: 12px;
  color: var(--color-highlight);
}
</style>