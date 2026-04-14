<!-- src/components/common/ThemeDebug.vue -->
<template>
  <div v-if="visible" class="theme-debug">
    <h4>🎨 主题调试</h4>
    <div class="debug-content">
      <div class="debug-row">
        <span>当前主题:</span>
        <span :style="{ color: themeStore.themeConfig.colors['--color-highlight'] }">
          {{ themeStore.themeConfig.name }} {{ themeStore.themeIcon }}
        </span>
      </div>
      <div class="debug-row">
        <span>跟随系统:</span>
        <span :class="{ enabled: themeStore.followSystem }">
          {{ themeStore.followSystem ? '✅' : '❌' }}
        </span>
      </div>
      <div class="debug-row">
        <span>系统主题:</span>
        <span>{{ themeStore.systemTheme === 'dark' ? '🌙 暗黑' : '☀️ 明亮' }}</span>
      </div>
      <div class="debug-buttons">
        <button @click="themeStore.toggleTheme">切换</button>
        <button @click="themeStore.toggleFollowSystem">
          {{ themeStore.followSystem ? '取消跟随' : '跟随系统' }}
        </button>
      </div>
      <div class="debug-colors">
        <div class="color-sample" 
             v-for="(value, key) in themeStore.themeConfig.colors" 
             :key="key"
             :style="{ backgroundColor: value }"
             :title="`${key}: ${value}`">
        </div>
      </div>
    </div>
  </div>
  <button v-else class="debug-toggle" @click="visible = true">🎨</button>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useThemeStore } from '@/stores/theme'

const visible = ref(false)
const themeStore = useThemeStore()
</script>

<style scoped>
.theme-debug {
  position: fixed;
  bottom: 20px;
  right: 20px;
  width: 300px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 12px;
  z-index: 9999;
  font-size: 12px;
  box-shadow: 0 4px 12px rgba(0,0,0,0.3);
}

.theme-debug h4 {
  margin: 0 0 12px 0;
  color: var(--text-title);
}

.debug-content {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.debug-row {
  display: flex;
  justify-content: space-between;
  color: var(--text-secondary);
}

.debug-row .enabled {
  color: #2ed573;
}

.debug-buttons {
  display: flex;
  gap: 8px;
  margin-top: 8px;
}

.debug-buttons button {
  flex: 1;
  padding: 6px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  color: var(--text-primary);
  border-radius: 4px;
  cursor: pointer;
  font-size: 11px;
}

.debug-buttons button:hover {
  background: var(--bg-hover);
  border-color: var(--color-highlight);
}

.debug-colors {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--border-color);
}

.color-sample {
  width: 24px;
  height: 24px;
  border-radius: 4px;
  border: 1px solid var(--border-color);
  cursor: pointer;
  transition: transform 0.2s;
}

.color-sample:hover {
  transform: scale(1.2);
  z-index: 1;
}

.debug-toggle {
  position: fixed;
  bottom: 20px;
  right: 20px;
  width: 40px;
  height: 40px;
  border-radius: 20px;
  background: var(--color-highlight);
  border: none;
  color: #000;
  font-size: 20px;
  cursor: pointer;
  box-shadow: 0 4px 12px rgba(0,0,0,0.3);
  z-index: 9998;
}

.debug-toggle:hover {
  opacity: 0.9;
  transform: scale(1.1);
}
</style>