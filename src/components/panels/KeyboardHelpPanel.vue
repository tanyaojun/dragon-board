<!-- src/components/panels/KeyboardHelpPanel.vue -->
<template>
  <Teleport to="body">
    <div
      v-if="visible"
      class="help-panel"
      :style="panelStyle"
      ref="panelRef"
      @mousedown="startDrag"
      @mousemove="drag"
      @mouseup="stopDrag"
      @mouseleave="stopDrag"
    >
      <div class="panel-header">
        <h3>⌨️ 键盘快捷键</h3>
        <div class="panel-actions">
          <button class="btn-icon" @click.stop="close" title="关闭">✕</button>
        </div>
      </div>

      <div class="panel-content">
        <div v-for="category in categories" :key="category" class="shortcut-section">
          <div class="section-title">{{ getCategoryName(category) }}</div>
          <div class="shortcut-list">
            <div
              v-for="shortcut in getShortcuts(category)"
              :key="shortcut.key"
              class="shortcut-item"
            >
              <span class="shortcut-key">{{ shortcut.key }}</span>
              <span class="shortcut-desc">{{ shortcut.description }}</span>
            </div>
          </div>
        </div>
      </div>

      <div class="panel-footer">
        <span class="hint">💡 可拖拽移动面板</span>
        <button class="btn-text" @click="close">关闭</button>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { keyboardService } from '@/services/keyboardService'
import { EventManager } from '@/utils/eventManager'
import { AppEvents } from '@/types'

const props = defineProps<{
  visible: boolean
}>()

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'close'): void
}>()

// ========== 拖拽状态 ==========
const panelRef = ref<HTMLElement | null>(null)
const dragging = ref(false)
const dragOffset = ref({ x: 0, y: 0 })
const position = ref({ x: 100, y: 100 })

// ========== 计算属性 ==========
const panelStyle = computed(() => ({
  left: position.value.x + 'px',
  top: position.value.y + 'px',
}))

const categories = computed(() => keyboardService.getCategories())

// ========== 方法 ==========
function getCategoryName(category: string): string {
  return keyboardService.getCategoryName(category)
}

function getShortcuts(category: string) {
  return keyboardService.getShortcutsByCategory(category)
}

function close() {
  emit('update:visible', false)
  emit('close')
  EventManager.emit(AppEvents.UI.PANEL_CLOSE, { panel: 'help' })
}

// ========== 拖拽逻辑 ==========
function startDrag(e: MouseEvent) {
  if (!panelRef.value) return
  if ((e.target as HTMLElement).closest('.btn-icon, .btn-text')) return

  dragging.value = true
  const rect = panelRef.value.getBoundingClientRect()
  dragOffset.value = {
    x: e.clientX - rect.left,
    y: e.clientY - rect.top,
  }
  panelRef.value.style.cursor = 'grabbing'
}

function drag(e: MouseEvent) {
  if (!dragging.value || !panelRef.value) return

  e.preventDefault()

  let x = e.clientX - dragOffset.value.x
  let y = e.clientY - dragOffset.value.y

  // 边界限制
  const maxX = window.innerWidth - panelRef.value.offsetWidth
  const maxY = window.innerHeight - panelRef.value.offsetHeight

  x = Math.max(0, Math.min(x, maxX))
  y = Math.max(0, Math.min(y, maxY))

  position.value = { x, y }
}

function stopDrag() {
  if (!dragging.value || !panelRef.value) return
  dragging.value = false
  panelRef.value.style.cursor = ''
}

// ========== ESC 关闭 ==========
function handleKeyDown(e: KeyboardEvent) {
  if (e.key === 'Escape' && props.visible) {
    close()
  }
}

onMounted(() => {
  document.addEventListener('keydown', handleKeyDown)
  EventManager.emit(AppEvents.UI.PANEL_OPEN, { panel: 'help' })
})

onUnmounted(() => {
  document.removeEventListener('keydown', handleKeyDown)
})
</script>

<style scoped>
.help-panel {
  position: fixed;
  width: 400px;
  max-width: calc(100vw - 40px);
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.3);
  z-index: 10050;
  font-size: 12px;
  backdrop-filter: blur(10px);
  user-select: none;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-header);
  cursor: grab;
}

.panel-header:active {
  cursor: grabbing;
}

.panel-header h3 {
  margin: 0;
  font-size: 16px;
  color: var(--text-title);
}

.panel-actions {
  display: flex;
  gap: 8px;
}

.btn-icon {
  width: 32px;
  height: 32px;
  border: 1px solid var(--border-color);
  background: transparent;
  border-radius: 6px;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 16px;
  transition: all 0.2s;
}

.btn-icon:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
  border-color: var(--color-highlight);
}

.panel-content {
  padding: 20px;
  max-height: 60vh;
  overflow-y: auto;
}

.shortcut-section {
  margin-bottom: 20px;
}

.section-title {
  font-size: 14px;
  font-weight: bold;
  color: var(--color-highlight);
  margin-bottom: 12px;
  padding-bottom: 4px;
  border-bottom: 1px solid var(--border-color);
}

.shortcut-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.shortcut-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 6px 8px;
  background: var(--bg-secondary);
  border-radius: 6px;
  transition: all 0.2s;
}

.shortcut-item:hover {
  background: var(--bg-hover);
  transform: translateX(4px);
}

.shortcut-key {
  min-width: 80px;
  padding: 4px 8px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  font-family: monospace;
  font-weight: bold;
  color: var(--color-highlight);
  text-align: center;
}

.shortcut-desc {
  flex: 1;
  color: var(--text-primary);
}

.panel-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 20px;
  border-top: 1px solid var(--border-color);
  background: var(--bg-header);
}

.hint {
  color: var(--text-secondary);
  font-size: 11px;
}

.btn-text {
  background: transparent;
  border: 1px solid var(--border-color);
  color: var(--color-highlight);
  padding: 4px 12px;
  border-radius: 16px;
  cursor: pointer;
  font-size: 11px;
  transition: all 0.2s;
}

.btn-text:hover {
  background: var(--color-highlight);
  color: #000;
  border-color: var(--color-highlight);
}
</style>
