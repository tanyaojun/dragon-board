<!-- src/components/theme/DragonThemeToggle.vue -->
<template>
  <div class="dragon-theme-toggle">
    <!-- 龙族主题开关 -->
    <button 
      class="dragon-toggle-btn" 
      :class="{ active: dragonEnabled }"
      @click="toggleDragonTheme"
      :title="dragonEnabled ? '切换到普通主题' : '切换到龙族主题'"
    >
      <span class="btn-icon">{{ dragonEnabled ? '🐉' : '🎨' }}</span>
      <span class="btn-text">{{ dragonEnabled ? '龙族' : '普通' }}</span>
    </button>

    <!-- 龙子选择器（仅在龙族模式显示） -->
    <div v-if="dragonEnabled" class="dragon-selector">
      <button 
        v-for="theme in dragonThemes" 
        :key="theme.id"
        class="dragon-option"
        :class="{ active: currentDragon === theme.id }"
        @click="selectDragonTheme(theme.id)"
        :title="`${theme.name} · ${theme.element} · ${theme.power.name}`"
      >
        <span class="option-icon">{{ theme.icon }}</span>
        <span class="option-name">{{ theme.name }}</span>
        <span class="option-element" :class="'element-' + theme.element.toLowerCase()">{{ theme.element }}</span>
      </button>
    </div>

    <!-- 普通主题切换（非龙族模式） -->
    <div v-else class="normal-theme-selector">
      <button 
        v-for="theme in normalThemes" 
        :key="theme.id"
        class="theme-option"
        :class="{ active: currentNormal === theme.id }"
        @click="selectNormalTheme(theme.id)"
        :title="theme.name"
      >
        <span class="option-icon">{{ theme.icon }}</span>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useThemeStore } from '@/stores/theme'
import { dragonThemes } from '@/themes/dragon-themes'
import { EventManager } from '@/utils/eventManager'
import { AppEvents } from '@/types'

const themeStore = useThemeStore()

// 普通主题配置
const normalThemes = [
  { id: 'dark', name: '暗夜', icon: '🌙' },
  { id: 'light', name: '白昼', icon: '☀️' },
  { id: 'matrix', name: '矩阵', icon: '💻' },
  { id: 'cream', name: '奶油', icon: '🍦' }
]

// 计算属性
const dragonEnabled = computed(() => themeStore.dragonThemeEnabled)
const currentDragon = computed(() => themeStore.currentDragonTheme)
const currentNormal = computed(() => themeStore.currentTheme)

// 事件监听管理器（模仿 App.vue 的方式）
const eventListeners = new Map<string, Set<Function>>()

function addEventListener(event: string, callback: Function) {
  if (!eventListeners.has(event)) {
    eventListeners.set(event, new Set())
  }
  eventListeners.get(event)!.add(callback)
  EventManager.on(event, callback as any)
}

function removeAllListeners() {
  eventListeners.forEach((callbacks, event) => {
    callbacks.forEach((callback) => {
      EventManager.off(event, callback as any)
    })
  })
  eventListeners.clear()
}

// 显示 Toast 的统一方法
function showToast(message: string, type: 'success' | 'info' | 'error' | 'dragon' = 'info') {
  EventManager.emit(AppEvents.UI.TOAST, {
    message,
    duration: type === 'error' ? 2000 : 1500,
    type,
  })
}

// 方法
function toggleDragonTheme() {
  console.log('[DragonTheme] 切换主题模式:', !dragonEnabled.value ? '龙族' : '普通')
  themeStore.enableDragonTheme(!dragonEnabled.value)
  
  // 使用统一事件方式触发 Toast
  if (!dragonEnabled.value) {
    showToast('🐉 龙族主题已启用 · 九子护体', 'dragon')
  } else {
    showToast('🎨 已切换到普通主题', 'success')
  }
  
  // 触发主题模式变更事件
  EventManager.emit('theme-mode-changed', { 
    dragonEnabled: !dragonEnabled.value 
  })
}

function selectDragonTheme(themeId: string) {
  console.log('[DragonTheme] 选择龙子:', themeId)
  themeStore.setDragonTheme(themeId)
  
  // 显示龙子提示
  const theme = dragonThemes.find(t => t.id === themeId)
  if (theme) {
    showToast(`🐉 ${theme.name} · ${theme.power.name}`, 'dragon')
    
    // 触发龙族主题变更事件
    EventManager.emit('dragon-theme-change', { 
      theme: themeId,
      themeData: theme
    })
  }
}

function selectNormalTheme(themeId: string) {
  console.log('[DragonTheme] 选择普通主题:', themeId)
  themeStore.setTheme(themeId as any)
  
  // 触发普通主题变更事件
  EventManager.emit('theme-changed', { 
    theme: themeId 
  })
}

// 监听主题状态变化（可选）
function onThemeModeChanged(data: any) {
  console.log('[DragonTheme] 主题模式已变更:', data)
}

function onDragonThemeChanged(data: any) {
  console.log('[DragonTheme] 龙子已变更:', data)
}

// 生命周期
onMounted(() => {
  // 添加事件监听 - 模仿 App.vue 的方式
  addEventListener('theme-mode-changed', onThemeModeChanged)
  addEventListener('dragon-theme-change', onDragonThemeChanged)
  
  console.log('[DragonTheme] 事件监听已注册')
})

onUnmounted(() => {
  removeAllListeners()
})
</script>

<style scoped>
/* 样式保持不变，与之前相同 */
.dragon-theme-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0 4px;
}

.dragon-toggle-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border: 1px solid var(--border-color);
  border-radius: 30px;
  background: var(--bg-secondary);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
  font-size: 13px;
  font-weight: 500;
  position: relative;
  overflow: hidden;
}

.dragon-toggle-btn::before {
  content: '';
  position: absolute;
  top: 0;
  left: -100%;
  width: 100%;
  height: 100%;
  background: linear-gradient(90deg, transparent, rgba(255,215,0,0.2), transparent);
  transition: left 0.5s ease;
}

.dragon-toggle-btn:hover::before {
  left: 100%;
}

.dragon-toggle-btn:hover {
  border-color: var(--color-accent);
  color: var(--text-primary);
  transform: translateY(-1px);
  box-shadow: 0 4px 8px rgba(0,0,0,0.1);
}

.dragon-toggle-btn.active {
  background: linear-gradient(135deg, var(--color-accent), #ffd700);
  color: #000;
  border-color: var(--color-accent);
  box-shadow: 0 0 15px var(--color-accent);
}

.btn-icon {
  font-size: 18px;
  animation: pulse 2s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { transform: scale(1); }
  50% { transform: scale(1.1); }
}

.btn-text {
  font-size: 12px;
  letter-spacing: 0.5px;
}

.dragon-selector {
  display: flex;
  gap: 2px;
  padding: 3px;
  background: var(--bg-panel);
  border: 1px solid var(--border-color);
  border-radius: 40px;
  backdrop-filter: blur(10px);
  box-shadow: var(--shadow-sm);
}

.dragon-option {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border: none;
  background: transparent;
  border-radius: 30px;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.2s ease;
  font-size: 12px;
  position: relative;
  overflow: hidden;
}

.dragon-option::after {
  content: '';
  position: absolute;
  bottom: 0;
  left: 50%;
  transform: translateX(-50%);
  width: 0;
  height: 2px;
  background: var(--color-accent);
  transition: width 0.2s ease;
}

.dragon-option:hover::after {
  width: 80%;
}

.dragon-option:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
  transform: translateY(-1px);
}

.dragon-option.active {
  background: var(--color-accent);
  color: #000;
  box-shadow: 0 2px 8px var(--color-accent);
}

.option-icon {
  font-size: 14px;
  filter: drop-shadow(0 2px 2px rgba(0,0,0,0.2));
}

.option-name {
  font-weight: 500;
}

.option-element {
  font-size: 9px;
  padding: 2px 5px;
  border-radius: 12px;
  background: rgba(0,0,0,0.1);
  font-weight: 600;
}

.element-木 { color: #27ae60; background: rgba(39, 174, 96, 0.2); }
.element-火 { color: #e67e22; background: rgba(230, 126, 34, 0.2); }
.element-土 { color: #7f8c8d; background: rgba(127, 140, 141, 0.2); }
.element-金 { color: #f39c12; background: rgba(243, 156, 18, 0.2); }
.element-水 { color: #2980b9; background: rgba(41, 128, 185, 0.2); }

.normal-theme-selector {
  display: flex;
  gap: 2px;
  padding: 3px;
  background: var(--bg-panel);
  border: 1px solid var(--border-color);
  border-radius: 30px;
}

.theme-option {
  width: 32px;
  height: 32px;
  border: none;
  background: transparent;
  border-radius: 50%;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.2s ease;
  font-size: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.theme-option:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
  transform: scale(1.1);
}

.theme-option.active {
  background: var(--color-accent);
  color: #000;
  box-shadow: 0 0 10px var(--color-accent);
}

@media (max-width: 1200px) {
  .option-name {
    display: none;
  }
  
  .dragon-option {
    padding: 4px 8px;
  }
}

@media (max-width: 768px) {
  .dragon-theme-toggle {
    position: relative;
  }
  
  .dragon-selector,
  .normal-theme-selector {
    position: absolute;
    top: 100%;
    right: 0;
    margin-top: 8px;
    background: var(--bg-panel);
    border-radius: 12px;
    padding: 8px;
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 4px;
    min-width: 200px;
    z-index: 1000;
    box-shadow: var(--shadow-lg);
    opacity: 0;
    visibility: hidden;
    transform: translateY(-10px);
    transition: all 0.2s ease;
  }
  
  .dragon-theme-toggle:hover .dragon-selector,
  .dragon-theme-toggle:hover .normal-theme-selector {
    opacity: 1;
    visibility: visible;
    transform: translateY(0);
  }
}
</style>