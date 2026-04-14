<!-- src/components/common/NavTabs.vue -->
<template>
  <div class="nav-tabs">
    <button
      v-for="tab in tabs"
      :key="tab.id"
      class="nav-tab"
      :class="{ active: modelValue === tab.id }"
      @click="$emit('update:modelValue', tab.id)"
    >
      <span class="tab-icon">{{ tab.icon }}</span>
      <span class="tab-text">{{ tab.label }}</span>
    </button>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  modelValue: string
  tabs: Array<{ id: string; label: string; icon: string }>
}>()

defineEmits<{
  (e: 'update:modelValue', value: string): void
}>()
</script>

<style scoped>
.nav-tabs {
  display: flex;
  gap: 4px;
  background-color: var(--tab-bg);
  padding: 2px;
  border-radius: 8px;
  backdrop-filter: blur(4px);
}

.nav-tab {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border: none;
  background: none;
  color: var(--text-secondary);
  font-size: 13px;
  font-weight: 500;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s ease;
  white-space: nowrap;
}

.nav-tab:hover {
  color: var(--text-primary);
  background-color: var(--tab-hover);
  transform: translateY(-1px);
}

.nav-tab.active {
  background-color: var(--tab-active);
  color: var(--color-highlight);
  box-shadow: var(--shadow-sm);
}

.tab-icon {
  font-size: 16px;
}

@media (max-width: 768px) {
  .tab-text {
    display: none;
  }
  
  .nav-tab {
    padding: 6px 10px;
  }
}
</style>