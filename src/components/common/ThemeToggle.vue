<!-- src/components/common/ThemeToggle.vue -->
<template>
  <button 
    class="btn btn-icon theme-toggle" 
    :title="`${themeConfig.name}主题${followSystem ? '（跟随系统）' : ''}`"
    @click="handleClick"
  >
    {{ themeIcon }}
    <span v-if="showLabel" class="theme-label">{{ themeConfig.name }}</span>
  </button>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useThemeStore } from '@/stores/theme'

const props = defineProps<{
  showLabel?: boolean
}>()

const themeStore = useThemeStore()

const themeConfig = computed(() => themeStore.themeConfig)
const themeIcon = computed(() => themeStore.themeIcon)
const followSystem = computed(() => themeStore.followSystem)

function handleClick() {
  themeStore.toggleTheme()
}
</script>

<style scoped>
.theme-toggle {
  position: relative;
  transition: all 0.2s;
}

.theme-toggle:hover {
  transform: rotate(30deg);
}

.theme-label {
  margin-left: 4px;
  font-size: 12px;
}
</style>