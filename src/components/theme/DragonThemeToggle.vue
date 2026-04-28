<!-- src/components/theme/DragonThemeToggle.vue -->
<template>
  <div class="theme-switcher" role="group" aria-label="主题切换">
    <button
      v-for="theme in themes"
      :key="theme.id"
      class="theme-button"
      :class="{ active: currentTheme === theme.id }"
      type="button"
      :title="`切换到${theme.name}主题`"
      :aria-label="`切换到${theme.name}主题`"
      :aria-pressed="currentTheme === theme.id"
      @click="selectTheme(theme.id)"
    >
      <span class="theme-icon">{{ theme.icon }}</span>
    </button>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useThemeStore } from '@/stores/theme'
import { EventManager } from '@/utils/eventManager'
import { AppEvents } from '@/types'
import type { ThemeType } from '@/types/theme'

const themeStore = useThemeStore()

const themes: Array<{ id: ThemeType; name: string; icon: string }> = [
  { id: 'dark', name: '暗黑', icon: '🌙' },
  { id: 'light', name: '明亮', icon: '☀️' },
  { id: 'matrix', name: '矩阵', icon: '💻' },
  { id: 'cream', name: '淡黄', icon: '🍦' },
]

const currentTheme = computed(() => themeStore.currentTheme)

function selectTheme(themeId: ThemeType) {
  themeStore.setTheme(themeId)
  EventManager.emit(AppEvents.UI.TOAST, {
    message: `已切换到${themeStore.themeConfig.name}主题`,
    duration: 1200,
    type: 'success',
  })
}
</script>

<style scoped>
.theme-switcher {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px;
  border: 1px solid var(--border-color);
  border-radius: 18px;
  background: var(--bg-panel);
  box-shadow: var(--shadow-sm);
}

.theme-button {
  width: 28px;
  height: 28px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  transition:
    background-color 0.15s ease,
    color 0.15s ease,
    transform 0.15s ease,
    box-shadow 0.15s ease;
}

.theme-button:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.theme-button.active {
  background: var(--color-highlight);
  color: #101010;
  box-shadow: 0 0 0 1px var(--color-highlight);
}

.theme-button:focus-visible {
  outline: 2px solid var(--color-highlight);
  outline-offset: 2px;
}

.theme-icon {
  font-size: 15px;
  line-height: 1;
}
</style>
