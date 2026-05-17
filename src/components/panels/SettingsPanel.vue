<!-- src/components/panels/SettingsPanel.vue -->
<!-- 已移除增量更新器相关代码 -->

<template>
  <Teleport to="body">
    <div v-if="visible" class="settings-panel" :style="panelStyle" ref="panelRef">
      <div class="panel-header">
        <h3>⚙️ 刷新设置 <span class="version-badge">v3.0.0</span></h3>
        <div class="panel-actions">
          <button class="btn-icon" @click="refreshStatus" title="刷新状态">🔄</button>
          <button class="btn-icon" @click="close" title="关闭">✕</button>
        </div>
      </div>

      <div class="panel-content">
        <div v-if="loading" class="loading-state">加载配置中...</div>
        <template v-else>
          <!-- 策略显示提示 -->
          <div v-if="!isConfigConsistent" class="config-warning">
            <span class="warning-icon">⚠️</span>
            <span class="warning-text">
              当前为自定义配置，与所选"{{ STRATEGIES[config.strategy]?.name || config.strategy }}"策略不一致
              <a href="#" @click.prevent="resetToCurrentStrategy">点击恢复策略默认值</a>
            </span>
          </div>

          <!-- 基本设置 -->
          <div class="settings-section">
            <h4>⚙️ 基本设置</h4>
            <div class="setting-item">
              <span class="setting-label">自动刷新</span>
              <label class="switch">
                <input type="checkbox" :checked="config.enabled" @change="toggleEnabled" />
                <span class="slider round"></span>
              </label>
            </div>
            <div class="setting-item">
              <span class="setting-label">交易时间限制</span>
              <label class="switch">
                <input type="checkbox" :checked="config.tradingTimeOnly" @change="toggleTradingTime" />
                <span class="slider round"></span>
              </label>
            </div>
            <div class="setting-item">
              <span class="setting-label">允许手动刷新</span>
              <label class="switch">
                <input type="checkbox" :checked="config.allowManualRefresh" @change="toggleManualRefresh" />
                <span class="slider round"></span>
              </label>
              <span class="setting-hint">非交易时间也可手动刷新</span>
            </div>
          </div>

          <!-- 刷新策略 -->
          <div class="settings-section">
            <h4>🎯 刷新策略</h4>
            <div class="strategy-selector">
              <div v-for="(strategy, key) in STRATEGIES" :key="key" class="strategy-option"
                :class="{ active: config.strategy === key }" :style="{ borderColor: strategy.color }">
                <div class="strategy-main" @click="setStrategy(key as RefreshStrategy)">
                  <div class="strategy-icon" :style="{ background: strategy.color + '20', color: strategy.color }">
                    {{ strategy.icon }}
                  </div>
                  <div class="strategy-info">
                    <div class="strategy-name">{{ strategy.name }}</div>
                    <div class="strategy-desc">{{ strategy.desc }}</div>
                    <div class="strategy-preset" v-if="config.strategy === key">
                      推荐: 全量{{ formatPresetInterval(key as RefreshStrategy, 'full') }}
                    </div>
                  </div>
                </div>
                <button class="strategy-name-only" @click.stop="setStrategyNameOnly(key as RefreshStrategy)" :title="config.strategy === key
                  ? '只切换名称，保留当前自定义值'
                  : '切换策略并保留当前自定义值'
                  ">
                  ⚙️
                </button>
                <span v-if="config.strategy === key" class="check-mark">✓</span>
              </div>
            </div>
          </div>

          <!-- 刷新间隔 -->
          <div class="settings-section">
            <h4>⏱️ 刷新间隔</h4>
            <div class="setting-item">
              <span class="setting-label">全量刷新</span>
              <select class="interval-select" :value="config.fullRefreshInterval" @change="setFullInterval">
                <option v-for="option in FULL_REFRESH_OPTIONS" :key="option.value" :value="option.value">
                  {{ option.label }}
                  <span v-if="'strategy' in option" class="option-hint">({{ STRATEGIES[option.strategy]?.name }})</span>
                </option>
              </select>
            </div>
          </div>

          <!-- 运行状态 -->
          <div class="settings-section">
            <h4>📊 运行状态</h4>
            <div class="status-indicator">
              <span class="status-label">刷新管理器:</span>
              <span :class="getStatusClass">
                {{ getStatusText }}
              </span>
            </div>
          </div>

          <!-- 刷新统计 -->
          <div class="settings-section">
            <h4>📈 刷新统计</h4>
            <div class="stats-grid">
              <div class="stat-item">
                <span class="stat-label">全量刷新</span>
                <span class="stat-value">{{ stats.fullRefreshes }}</span>
              </div>
              <div class="stat-item">
                <span class="stat-label">手动刷新</span>
                <span class="stat-value">{{ stats.manualRefreshes }}</span>
              </div>
              <div class="stat-item">
                <span class="stat-label">失败次数</span>
                <span class="stat-value" :class="{ 'color-down': stats.failedRefreshes > 0 }">
                  {{ stats.failedRefreshes }}
                </span>
              </div>
            </div>

            <div class="refresh-history" v-if="refreshHistory.length">
              <h5>🕒 最近刷新记录</h5>
              <div class="history-list">
                <div v-for="(item, idx) in refreshHistory" :key="idx" class="history-item"
                  :class="{ 'history-item-error': item.type === 'failed' }">
                  <span class="history-type" :class="'type-' + item.type">
                    {{ item.type === 'full' ? '全量' : '失败' }}
                  </span>
                  <span class="history-time">{{ formatTime(item.timestamp) }}</span>
                  <span class="history-duration" v-if="item.type !== 'failed'">{{ item.duration }}ms</span>
                  <span class="history-error" v-else :title="item.error">{{ item.error }}</span>
                </div>
              </div>
            </div>

            <div class="time-info">
              <div class="time-item">
                <span>最后刷新:</span>
                <span>{{ formatTime(stats.lastRefreshTime) }}</span>
              </div>
              <div class="time-item">
                <span>最后全量:</span>
                <span>{{ formatTime(stats.lastFullRefreshTime) }}</span>
              </div>
            </div>
          </div>

          <!-- 错误信息 -->
          <div v-if="lastError" class="error-section">
            <div class="error-title">❌ 最后错误</div>
            <div class="error-message">{{ lastError }}</div>
          </div>

          <!-- 操作按钮 -->
          <div class="settings-actions">
            <button class="btn btn-primary" @click="manualRefresh('full')">🔄 全量刷新</button>
            <button class="btn" @click="resetConfig">↺ 重置默认</button>
          </div>

          <!-- 当前时间提示 -->
          <div class="trading-tip" v-if="!isTradingTime && config.tradingTimeOnly">
            <span class="tip-icon">⏰</span>
            <span class="tip-text">当前非交易时间，自动刷新已暂停</span>
          </div>
          <div class="trading-tip" v-else-if="!isTradingTime && !config.tradingTimeOnly">
            <span class="tip-icon">⏰</span>
            <span class="tip-text">非交易时间，但手动刷新仍可用</span>
          </div>
        </template>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { EventManager } from '@/utils/eventManager'
import { AppEvents } from '@/types'
import { RefreshManager } from '@/services/RefreshManager'
import { isTradingTime } from '@/utils/time'
import {
  REFRESH_STRATEGY_CONFIGS,
  FULL_REFRESH_OPTIONS,
  type RefreshConfig,
  type RefreshStrategy,
} from '@/types/config'

import { usePanel } from '@/composables/usePanel'

const unsubscribeFns: (() => void)[] = []

const STRATEGIES: Record<RefreshStrategy, { name: string; icon: string; desc: string; color: string }> = {
  conservative: {
    name: '保守模式',
    icon: '🐢',
    desc: '减少请求，保护服务器',
    color: '#3498db',
  },
  balanced: {
    name: '均衡模式',
    icon: '⚖️',
    desc: '平衡性能与时效性',
    color: '#2ed573',
  },
  aggressive: {
    name: '激进模式',
    icon: '🐇',
    desc: '极致刷新，数据实时',
    color: '#ff4757',
  },
  recovery: {
    name: '恢复模式',
    icon: '🔄',
    desc: '失败后快速恢复',
    color: '#f39c12',
  },
}

type SettingsRefreshConfig = RefreshConfig & {
  isRunning?: boolean
  isRefreshing?: boolean
}

const props = defineProps<{
  visible: boolean
  triggerRect?: DOMRect
}>()

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'close'): void
}>()

function close() {
  emit('update:visible', false)
  emit('close')
  EventManager.emit(AppEvents.UI.PANEL_CLOSE, { panel: 'settings' })
}

const { panelRef, panelStyle } = usePanel({
  name: 'SettingsPanel',
  visible: props.visible,
  triggerRect: props.triggerRect,
  triggerSelectors: ['[title*="刷新设置"]', '.dropdown-item'],
  onClose: close,
})

// ========== 状态 ==========
const loading = ref(true)
const config = ref<SettingsRefreshConfig>({} as SettingsRefreshConfig)
const stats = ref(RefreshManager.getStats())
const lastError = ref<string | null>(null)
const refreshHistory = ref<Array<{ type: string, timestamp: number, duration: number, error?: string }>>([])

// ========== 计算属性 ==========
const getStatusClass = computed(() => {
  if (!config.value.isRunning) return 'status-stopped'
  if (config.value.isRefreshing) return 'status-refreshing'
  if (!isTradingTime() && config.value.tradingTimeOnly) return 'status-paused'
  return 'status-running'
})

const getStatusText = computed(() => {
  if (!config.value.isRunning) return '已停止'
  if (config.value.isRefreshing) return '刷新中...'
  if (!isTradingTime() && config.value.tradingTimeOnly) return '非交易时间暂停'
  return '运行中'
})

const isConfigConsistent = computed(() => {
  const preset = REFRESH_STRATEGY_CONFIGS[config.value.strategy]
  return (
    config.value.fullRefreshInterval === preset.fullRefreshInterval &&
    config.value.tradingTimeOnly === preset.tradingTimeOnly
  )
})

// ========== 方法 ==========
async function loadStatus() {
  loading.value = true
  try {
    const status = RefreshManager.getStatus()

    if (status.initialized) {
      updateConfigFromStatus(status)
      loading.value = false
      return
    }

    const timeout = setTimeout(() => {
      updateConfigFromStatus(RefreshManager.getStatus())
      loading.value = false
    }, 5000)

    const unsubscribe = EventManager.on(AppEvents.REFRESH.INITIALIZED, (data: any) => {
      clearTimeout(timeout)
      updateConfigFromStatus(RefreshManager.getStatus())
      unsubscribe()
      loading.value = false
    })
    unsubscribeFns.push(unsubscribe)
  } catch (error) {
    console.error('[SettingsPanel] 加载状态失败:', error)
    lastError.value = (error as Error).message
    showToast('❌ 加载状态失败', 'error')
    loading.value = false
  }
}

function updateConfigFromStatus(status: any) {
  config.value = {
    enabled: status.enabled,
    strategy: status.strategy,
    tradingTimeOnly: status.tradingTimeOnly,
    allowManualRefresh: status.allowManualRefresh,
    fullRefreshInterval: status.fullRefreshInterval,
    incrementalRefreshInterval: status.incrementalRefreshInterval,
    retryOnFailure: status.retryOnFailure,
    isRunning: status.isRunning,
    isRefreshing: status.isRefreshing,
    hotStocksLimit: status.hotStocksLimit ?? 100,
  } as any

  stats.value = RefreshManager.getStats()
}

function refreshStatus() {
  loadStatus()
  showToast('🔄 状态已刷新', 'info')
}

function toggleEnabled(e: Event) {
  const enabled = (e.target as HTMLInputElement).checked
  RefreshManager.toggleEnabled(enabled)
  config.value.enabled = enabled
  showToast(`自动刷新已${enabled ? '开启' : '关闭'}`, 'info')
}

function toggleTradingTime(e: Event) {
  const enabled = (e.target as HTMLInputElement).checked
  RefreshManager.toggleTradingTimeOnly(enabled)
  config.value.tradingTimeOnly = enabled
  showToast(`交易时间限制已${enabled ? '开启' : '关闭'}`, 'info')
}

function toggleManualRefresh(e: Event) {
  const enabled = (e.target as HTMLInputElement).checked
  RefreshManager.toggleAllowManualRefresh(enabled)
  config.value.allowManualRefresh = enabled
  showToast(`手动刷新已${enabled ? '允许' : '禁止'}`, 'info')
}

function setStrategy(strategy: RefreshStrategy) {
  RefreshManager.setStrategy(strategy as any, true)

  const status = RefreshManager.getStatus()
  config.value = {
    ...config.value,
    enabled: status.enabled,
    strategy: status.strategy,
    tradingTimeOnly: status.tradingTimeOnly,
    allowManualRefresh: status.allowManualRefresh,
    fullRefreshInterval: status.fullRefreshInterval,
    incrementalRefreshInterval: status.incrementalRefreshInterval,
    retryOnFailure: status.retryOnFailure,
    isRunning: status.isRunning,
    isRefreshing: status.isRefreshing,
    hotStocksLimit: (status as any).hotStocksLimit,
  }

  showToast(`已切换到 ${STRATEGIES[strategy].name} 策略`, 'success')
}

function setStrategyNameOnly(strategy: RefreshStrategy) {
  RefreshManager.setStrategy(strategy as any, false)
  const status = RefreshManager.getStatus()
  config.value.strategy = status.strategy
  showToast(`策略已切换为 ${STRATEGIES[strategy].name}，保留自定义配置`, 'info')
}

function resetToCurrentStrategy() {
  const strategy = config.value.strategy
  RefreshManager.setStrategy(strategy as any, true)
  showToast(`已恢复 ${STRATEGIES[strategy].name} 默认值`, 'success')
}

function setFullInterval(e: Event) {
  const interval = parseInt((e.target as HTMLSelectElement).value)
  RefreshManager.updateConfig({ fullRefreshInterval: interval })
  config.value.fullRefreshInterval = interval
  showToast(`全量间隔已设置为 ${interval / 60000}分钟`, 'info')
}

async function manualRefresh(type: 'full') {
  const result = await RefreshManager.requestRefresh({
    kind: type,
    source: 'settings-panel',
    trigger: 'manual',
    force: true,
  })
  if (result.success) {
    showToast(`🔄 开始全量刷新`, 'info')
    setTimeout(loadStatus, 1000)
  } else if (result.busy) {
    showToast(`⏳ 刷新进行中`, 'info')
  } else {
    showToast(`❌ 刷新失败`, 'error')
  }
}

function resetConfig() {
  if (confirm('确定要重置所有配置到默认值吗？')) {
    RefreshManager.reset()
    loadStatus()
    showToast('配置已重置为默认值', 'success')
  }
}

function formatTime(timestamp: number | null): string {
  if (!timestamp) return '无'
  const date = new Date(timestamp)
  const now = new Date()

  if (date.toDateString() === now.toDateString()) {
    return date.toLocaleTimeString('zh-CN', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
  }

  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function formatPresetInterval(strategy: RefreshStrategy, type: 'full'): string {
  const preset = REFRESH_STRATEGY_CONFIGS[strategy]
  const minutes = preset.fullRefreshInterval / 60000
  return minutes >= 60 ? `${minutes / 60}小时` : `${minutes}分钟`
}

function showToast(message: string, type: 'success' | 'info' | 'error' = 'info') {
  EventManager.emit(AppEvents.UI.TOAST, {
    message,
    duration: type === 'error' ? 2000 : 1500,
    type,
  })
}

// 添加刷新历史
function addRefreshHistory(data: any) {
  refreshHistory.value.unshift({
    type: data.type,
    timestamp: data.timestamp,
    duration: data.duration,
    error: data.error
  })

  if (refreshHistory.value.length > 10) {
    refreshHistory.value.pop()
  }
}

// 事件处理
function handleFullRefreshComplete(data: any) {
  loadStatus()
  addRefreshHistory(data)
  showToast(`✅ 全量刷新完成，耗时 ${data.duration}ms`, 'success')
}

function handleRefreshFailed(data: any) {
  lastError.value = data.error
  loadStatus()
  addRefreshHistory(data)
  showToast(`❌ 刷新失败: ${data.error}`, 'error')
}

function handleConfigChanged() {
  loadStatus()
}

// ========== 生命周期 ==========
onMounted(() => {
  loadStatus()

  const unsubFullComplete = EventManager.on(AppEvents.REFRESH.FULL_COMPLETE, handleFullRefreshComplete)
  unsubscribeFns.push(unsubFullComplete)

  const unsubFailed = EventManager.on(AppEvents.REFRESH.FAILED, handleRefreshFailed)
  unsubscribeFns.push(unsubFailed)

  const unsubConfig = EventManager.on(AppEvents.REFRESH.CHANGED, handleConfigChanged)
  unsubscribeFns.push(unsubConfig)

  EventManager.emit(AppEvents.UI.PANEL_OPEN, { panel: 'settings' })
})

onUnmounted(() => {
  unsubscribeFns.forEach((fn) => {
    try {
      fn()
    } catch (e) {
      console.warn('[SettingsPanel] 清理订阅失败:', e)
    }
  })
  unsubscribeFns.length = 0
})
</script>

<style scoped>
.strategy-option {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px 8px 8px;
  background: var(--bg-secondary);
  border-left: 4px solid;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
  position: relative;
}

.strategy-main {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
  cursor: pointer;
}

.strategy-name-only {
  width: 28px;
  height: 28px;
  border: none;
  background: transparent;
  color: var(--text-tertiary);
  cursor: pointer;
  font-size: 16px;
  opacity: 0.5;
  transition: all 0.2s;
  padding: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 4px;
}

.strategy-name-only:hover {
  opacity: 1;
  color: var(--color-highlight);
  background: var(--bg-hover);
  transform: none;
  /* 去掉旋转，保持简单 */
}

/* 当前激活的策略，辅助按钮稍微突出一点 */
.strategy-option.active .strategy-name-only {
  opacity: 0.8;
  color: var(--color-highlight);
}

/* 添加新样式 */
.config-warning {
  margin-bottom: 16px;
  padding: 10px;
  background: rgba(243, 156, 18, 0.1);
  border: 1px solid rgba(243, 156, 18, 0.3);
  border-radius: 8px;
  font-size: 12px;
  color: #f39c12;
  display: flex;
  align-items: center;
  gap: 8px;
}

.warning-icon {
  font-size: 14px;
}

.warning-text a {
  color: #f39c12;
  text-decoration: underline;
  margin-left: 8px;
}

.strategy-preset {
  font-size: 10px;
  color: var(--text-tertiary);
  margin-top: 4px;
}

.option-hint {
  font-size: 10px;
  color: var(--text-tertiary);
  margin-left: 4px;
}

.incremental-stats {
  margin-top: 12px;
  padding: 10px;
  background: var(--bg-primary);
  border-radius: 8px;
}

.incremental-stats h5 {
  margin: 0 0 8px 0;
  font-size: 12px;
  color: var(--text-secondary);
}

.stats-mini-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 8px;
}

.stat-mini-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 11px;
  padding: 4px 0;
  border-bottom: 1px dashed var(--border-color);
}

.stat-mini-label {
  color: var(--text-tertiary);
}

.stat-mini-value {
  color: var(--color-highlight);
  font-weight: 500;
  font-family: monospace;
}

/* 其他样式保持不变 */
.settings-panel {
  position: fixed;
  width: 480px;
  max-width: calc(100vw - 40px);
  max-height: 80vh;
  overflow-y: auto;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.3);
  z-index: 10001;
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

.panel-content {
  padding: 20px;
}

.settings-section {
  margin-bottom: 24px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--border-color);
}

.settings-section h4 {
  margin: 0 0 16px 0;
  font-size: 14px;
  color: var(--text-secondary);
  font-weight: normal;
}

.setting-item {
  display: flex;
  align-items: center;
  margin-bottom: 16px;
  padding: 0 4px;
  flex-wrap: wrap;
  gap: 8px;
}

.setting-label {
  color: var(--text-primary);
  font-size: 13px;
  min-width: 100px;
}

.setting-hint {
  font-size: 10px;
  color: var(--text-tertiary);
  margin-left: 8px;
}

.switch {
  position: relative;
  display: inline-block;
  width: 48px;
  height: 24px;
  margin-right: 8px;
}

.switch input {
  opacity: 0;
  width: 0;
  height: 0;
}

.slider {
  position: absolute;
  cursor: pointer;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: var(--border-color);
  transition: 0.3s;
  border-radius: 24px;
}

.slider:before {
  position: absolute;
  content: '';
  height: 20px;
  width: 20px;
  left: 2px;
  bottom: 2px;
  background-color: white;
  transition: 0.3s;
  border-radius: 50%;
}

input:checked+.slider {
  background-color: var(--color-highlight);
}

input:checked+.slider:before {
  transform: translateX(24px);
}

.strategy-selector {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.strategy-option {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px;
  background: var(--bg-secondary);
  border-left: 4px solid;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
  position: relative;
}

.strategy-option:hover {
  background: var(--bg-hover);
  transform: translateX(2px);
}

.strategy-option.active {
  background: var(--bg-hover);
}

.strategy-icon {
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 18px;
  font-size: 18px;
}

.strategy-info {
  flex: 1;
}

.strategy-name {
  font-weight: bold;
  margin-bottom: 2px;
  color: var(--text-primary);
}

.strategy-desc {
  font-size: 10px;
  color: var(--text-secondary);
}

.check-mark {
  position: absolute;
  right: 12px;
  color: var(--color-highlight);
  font-weight: bold;
  font-size: 16px;
}

.interval-select {
  width: 140px;
  padding: 6px 10px;
  background: var(--bg-header);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  color: var(--text-primary);
  font-size: 12px;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
  margin-bottom: 16px;
}

.stat-item {
  text-align: center;
  padding: 12px;
  background: var(--bg-secondary);
  border-radius: 8px;
}

.stat-item.full {
  grid-column: span 2;
}

.stat-label {
  display: block;
  font-size: 10px;
  color: var(--text-secondary);
  margin-bottom: 4px;
}

.stat-value {
  font-size: 18px;
  font-weight: bold;
  color: var(--text-primary);
}

.color-down {
  color: #ff4757;
}

.status-indicator {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px;
  background: var(--bg-secondary);
  border-radius: 8px;
  margin-bottom: 12px;
}

.status-label {
  color: var(--text-secondary);
}

.status-running {
  color: #2ed573;
  font-weight: bold;
}

.status-stopped {
  color: #ff4757;
  font-weight: bold;
}

.status-refreshing {
  color: #3498db;
  font-weight: bold;
  animation: pulse 1.5s infinite;
}

.status-paused {
  color: #f39c12;
  font-weight: bold;
}

.status-detail {
  background: var(--bg-primary);
  border-radius: 6px;
  padding: 8px;
  font-size: 11px;
}

.detail-item {
  display: flex;
  justify-content: space-between;
  margin-bottom: 4px;
  color: var(--text-secondary);
}

.detail-item span:last-child {
  color: var(--text-primary);
  font-weight: 500;
}

.time-info {
  background: var(--bg-primary);
  border-radius: 6px;
  padding: 8px;
  font-size: 11px;
}

.time-item {
  display: flex;
  justify-content: space-between;
  margin-bottom: 4px;
  color: var(--text-secondary);
}

.time-item span:last-child {
  color: var(--color-highlight);
  font-family: monospace;
}

.error-section {
  margin-top: 16px;
  padding: 12px;
  background: rgba(255, 71, 87, 0.1);
  border: 1px solid #ff4757;
  border-radius: 8px;
}

.error-title {
  color: #ff4757;
  font-weight: bold;
  margin-bottom: 8px;
}

.error-message {
  font-size: 11px;
  color: var(--text-primary);
  word-break: break-word;
}

.settings-actions {
  display: flex;
  gap: 8px;
  margin-top: 20px;
}

.btn {
  flex: 1;
  padding: 10px;
  border: 1px solid var(--border-color);
  background: var(--bg-secondary);
  color: var(--text-primary);
  border-radius: 6px;
  cursor: pointer;
  font-size: 12px;
  transition: all 0.2s;
}

.btn:hover {
  background: var(--bg-hover);
  border-color: var(--color-highlight);
}

.btn-primary {
  background: var(--color-highlight);
  border-color: var(--color-highlight);
  color: #000;
}

.btn-primary:hover {
  opacity: 0.9;
}

.trading-tip {
  margin-top: 16px;
  padding: 10px;
  background: rgba(243, 156, 18, 0.1);
  border-radius: 8px;
  display: flex;
  align-items: center;
  gap: 8px;
  border: 1px solid rgba(243, 156, 18, 0.3);
}

.tip-icon {
  font-size: 16px;
}

.tip-text {
  font-size: 12px;
  color: #f39c12;
}

.loading-state {
  padding: 60px 20px;
  text-align: center;
  color: var(--text-secondary);
  font-size: 13px;
}

@keyframes pulse {

  0%,
  100% {
    opacity: 1;
  }

  50% {
    opacity: 0.5;
  }
}

.status-action-btn {
  width: 24px;
  height: 24px;
  border: 1px solid var(--border-color);
  background: var(--bg-secondary);
  border-radius: 4px;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 12px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  margin-left: 8px;
  transition: all 0.2s;
}


.queue-badges {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}

.queue-badge {
  display: inline-block;
  min-width: 20px;
  height: 20px;
  padding: 0 4px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  font-size: 10px;
  line-height: 18px;
  text-align: center;
  color: var(--text-secondary);
  cursor: help;
}

.stats-type-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 6px;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed var(--border-color);
}

.stat-type-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 10px;
  padding: 2px 0;
}

.stat-type-label {
  color: var(--text-tertiary);
}

.stat-type-value {
  color: var(--color-highlight);
  font-family: monospace;
}

.btn-success {
  background: #2ed573;
  border-color: #2ed573;
  color: #000;
}


.btn-warning {
  background: #f39c12;
  border-color: #f39c12;
  color: #000;
}


.service-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px;
  background: var(--bg-secondary);
  border-radius: 6px;
  margin-bottom: 6px;
  font-size: 11px;
  flex-wrap: wrap;
}

.service-label {
  color: var(--text-secondary);
  min-width: 100px;
}

.service-interval {
  color: var(--text-tertiary);
  font-size: 10px;
}

.service-lastrun {
  color: var(--color-highlight);
  font-size: 10px;
  margin-left: auto;
}


.status-action-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
  border-color: var(--color-highlight);
}

/* 添加到 style 中 */
.refresh-history {
  margin-top: 12px;
  padding: 10px;
  background: var(--bg-primary);
  border-radius: 8px;
}

.refresh-history h5 {
  margin: 0 0 8px 0;
  font-size: 12px;
  color: var(--text-secondary);
}

.history-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.history-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px;
  background: var(--bg-secondary);
  border-radius: 4px;
  font-size: 11px;
}

.history-type {
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 10px;
  font-weight: bold;
}

.history-item-error {
  background: rgba(255, 71, 87, 0.1);
  border-left: 2px solid #ff4757;
}

.history-type.type-full {
  background: var(--color-highlight);
  color: #000;
}

.history-type.type-incremental {
  background: #3498db;
  color: #fff;
}

.history-time {
  color: var(--text-secondary);
  flex: 1;
}

.history-type.type-failed {
  background: #ff4757;
  color: #fff;
}

.history-error {
  color: #ff4757;
  font-size: 10px;
  max-width: 150px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.history-duration {
  color: var(--color-highlight);
  font-family: monospace;
}

.btn-success:hover .btn-warning:hover {
  opacity: 0.9;
}
</style>
