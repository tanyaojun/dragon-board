<!-- src/components/panels/ConfigPanel.vue -->
<!-- 重构版：基于 config store，移除冗余状态 -->

<template>
  <Teleport to="body">
    <div v-if="visible" class="config-panel" :style="panelStyle" ref="panelRef">
      <div class="panel-header">
        <h3>
          ⚙️ 配置管理 <span class="version-badge">v{{ configStore.system.version }}</span>
        </h3>
        <div class="panel-actions">
          <button class="btn-icon" @click.stop="refresh" title="刷新">🔄</button>
          <button class="btn-icon" @click.stop="exportConfig" title="导出配置">📥</button>
          <button class="btn-icon" @click.stop="importConfig" title="导入配置">📤</button>
          <button class="btn-icon" @click.stop="close" title="关闭">✕</button>
        </div>
      </div>

      <div class="panel-tabs">
        <button
          v-for="(tab, key) in TABS"
          :key="key"
          class="tab-btn"
          :class="{ active: activeTab === key }"
          @click.stop="activeTab = key"
        >
          {{ tab.icon }} {{ tab.name }}
        </button>
      </div>

      <div class="panel-content">
        <component
          :is="currentTabComponent"
          :config="configStore.fullConfig"
          @change="handleConfigChange"
        />
      </div>

      <div class="panel-footer">
        <button class="btn-text" @click.stop="resetCurrentTab">↺ 重置当前配置</button>
        <button class="btn-text" @click.stop="resetAll">↻ 重置所有</button>
        <button class="btn-text" style="color: #2ed573" @click.stop="applyChanges">
          ✓ 应用修改
        </button>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useConfigStore } from '@/stores/config'
import { EventManager } from '@/utils/eventManager'
import { AppEvents } from '@/types'

// ========== 使用组合式函数 ==========
import { usePanel } from '@/composables/usePanel'

// 导入标签页组件
import SystemConfig from './config/SystemConfig.vue'
import UserConfig from './config/UserConfig.vue'
import CacheConfig from './config/CacheConfig.vue'
import AlgorithmConfig from './config/AlgorithmConfig.vue'
import AboutConfig from './config/AboutConfig.vue'

const TABS = {
  system: { name: '系统配置', icon: '⚙️', component: SystemConfig },
  user: { name: '用户配置', icon: '👤', component: UserConfig },
  cache: { name: '缓存配置', icon: '💾', component: CacheConfig },
  algorithm: { name: '算法配置', icon: '🧠', component: AlgorithmConfig },
  about: { name: '关于', icon: 'ℹ️', component: AboutConfig },
}

const props = defineProps<{
  visible: boolean
  triggerRect?: DOMRect
}>()

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'close'): void
}>()

// ========== 使用 config store ==========
const configStore = useConfigStore()

// ========== 先定义 close 函数 ==========
function close() {
  emit('update:visible', false)
  emit('close')
  EventManager.emit(AppEvents.UI.PANEL_CLOSE, { panel: 'config' })
}

// ========== 再使用 usePanel ==========
const { panelRef, panelStyle } = usePanel({
  name: 'ConfigPanel',
  visible: props.visible,
  triggerRect: props.triggerRect,
  triggerSelectors: ['[title*="配置管理"]', '.dropdown-item'],
  onClose: close,
})

// ========== 状态 ==========
const activeTab = ref<keyof typeof TABS>('system')
const pendingChanges = ref<Record<string, any>>({})

// ========== 计算属性 ==========
const currentTabComponent = computed(() => TABS[activeTab.value].component)

// ========== 方法 ==========
function refresh() {
  // 重新从 store 加载配置
  configStore.loadConfig()

  EventManager.emit(AppEvents.UI.TOAST, {
    message: '🔄 配置已刷新',
    duration: 1000,
    type: 'info',
  })
}

function handleConfigChange(data: any) {
  // 收集待处理的更改
  pendingChanges.value = {
    ...pendingChanges.value,
    ...data,
  }
}

function applyChanges() {
  try {
    // 应用系统配置更改
    if (pendingChanges.value.system) {
      Object.entries(pendingChanges.value.system).forEach(([key, value]) => {
        configStore.setSystemConfig(key as any, value as any)
      })
    }

    // 应用用户配置更改
    if (pendingChanges.value.user) {
      Object.entries(pendingChanges.value.user).forEach(([key, value]) => {
        configStore.setUserConfig(key as any, value as any)
      })
    }

    // 应用算法配置更改
    if (pendingChanges.value.algorithm) {
      if (pendingChanges.value.algorithm.current) {
        configStore.setAlgorithm(pendingChanges.value.algorithm.current)
      }
      if (pendingChanges.value.algorithm.thresholds) {
        Object.entries(pendingChanges.value.algorithm.thresholds).forEach(([key, value]) => {
          configStore.setThreshold(key as any, value as number)
        })
      }
    }

    // 清空待处理更改
    pendingChanges.value = {}

    EventManager.emit(AppEvents.UI.TOAST, {
      message: '✅ 配置已应用',
      duration: 1500,
      type: 'success',
    })
  } catch (error) {
    console.error('[ConfigPanel] 应用配置失败:', error)
    EventManager.emit(AppEvents.UI.TOAST, {
      message: '❌ 配置应用失败',
      duration: 1500,
      type: 'error',
    })
  }
}

function resetCurrentTab() {
  if (confirm(`确定要重置当前标签的配置吗？`)) {
    // TODO: 根据当前标签重置对应的配置
    EventManager.emit(AppEvents.UI.TOAST, {
      message: '🔄 配置已重置',
      duration: 1500,
      type: 'info',
    })
  }
}

function resetAll() {
  if (confirm(`确定要重置所有配置吗？这将恢复默认值。`)) {
    configStore.resetToDefaults()
    EventManager.emit(AppEvents.UI.TOAST, {
      message: '🔄 所有配置已重置',
      duration: 1500,
      type: 'info',
    })
  }
}

function exportConfig() {
  configStore.saveConfig() // 先保存
  const config = configStore.fullConfig

  const blob = new Blob([JSON.stringify(config, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `config_${new Date().toISOString().slice(0, 10)}.json`
  a.click()
  URL.revokeObjectURL(url)

  EventManager.emit(AppEvents.UI.TOAST, {
    message: '📥 配置已导出',
    duration: 1500,
    type: 'success',
  })
}

function importConfig() {
  const input = document.createElement('input')
  input.type = 'file'
  input.accept = '.json'

  input.onchange = (e: any) => {
    const file = e.target.files[0]
    const reader = new FileReader()

    reader.onload = (event) => {
      try {
        const imported = JSON.parse(event.target?.result as string)

        // 这里需要根据导入的配置更新 store
        // 由于 store 没有直接提供导入方法，需要逐个设置
        if (imported.system) {
          Object.entries(imported.system).forEach(([key, value]) => {
            configStore.setSystemConfig(key as any, value as any)
          })
        }

        if (imported.user) {
          Object.entries(imported.user).forEach(([key, value]) => {
            configStore.setUserConfig(key as any, value as any)
          })
        }

        if (imported.algorithm) {
          if (imported.algorithm.current) {
            configStore.setAlgorithm(imported.algorithm.current)
          }
          if (imported.algorithm.thresholds) {
            Object.entries(imported.algorithm.thresholds).forEach(([key, value]) => {
              configStore.setThreshold(key as any, value as number)
            })
          }
        }

        EventManager.emit(AppEvents.UI.TOAST, {
          message: '📤 配置已导入',
          duration: 1500,
          type: 'success',
        })
      } catch (err) {
        EventManager.emit(AppEvents.UI.TOAST, {
          message: '❌ 导入失败',
          duration: 1500,
          type: 'error',
        })
      }
    }

    reader.readAsText(file)
  }

  input.click()
}

// ========== 生命周期 ==========
onMounted(() => {
  EventManager.emit(AppEvents.UI.PANEL_OPEN, { panel: 'config' })
})
</script>

<style scoped>
/* 样式保持不变 */
.config-panel {
  position: fixed;
  width: 520px;
  max-width: calc(100vw - 40px);
  max-height: 80vh;
  overflow-y: auto;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.3);
  z-index: 10002;
  font-size: 12px;
  backdrop-filter: blur(10px);
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-header);
  position: sticky;
  top: 0;
  z-index: 2;
}

.panel-header h3 {
  margin: 0;
  font-size: 16px;
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--text-title);
}

.version-badge {
  font-size: 10px;
  background: var(--color-highlight);
  color: #000;
  padding: 2px 6px;
  border-radius: 12px;
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

.panel-tabs {
  display: flex;
  gap: 2px;
  padding: 10px 20px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-secondary);
  position: sticky;
  top: 61px;
  z-index: 1;
}

.tab-btn {
  flex: 1;
  padding: 8px 4px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  border-radius: 6px;
  font-size: 11px;
  transition: all 0.2s;
}

.tab-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.tab-btn.active {
  background: var(--color-highlight);
  color: #000;
}

.panel-content {
  padding: 20px;
  max-height: calc(80vh - 120px);
  overflow-y: auto;
}

.panel-footer {
  display: flex;
  justify-content: space-between;
  padding: 12px 20px;
  border-top: 1px solid var(--border-color);
  background: var(--bg-header);
  position: sticky;
  bottom: 0;
  z-index: 2;
}

.btn-text {
  background: transparent;
  border: none;
  color: var(--color-highlight);
  cursor: pointer;
  font-size: 12px;
  padding: 4px 8px;
  border-radius: 4px;
}

.btn-text:hover {
  background: var(--bg-hover);
}
</style>
