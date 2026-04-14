<!-- src/components/panels/SectorAlert.vue -->
<!-- src/components/panels/SectorAlert.vue -->
<!-- 纯响应式版本：完全依赖 dataLayer，自动响应数据变化 -->

<template>
  <Teleport to="body">
    <div v-if="visible" class="sector-alert-panel" :style="panelStyle" ref="panelRef">
      <!-- 头部 -->
      <div class="panel-header">
        <div class="header-left">
          <h3>
            ⚠️ 题材预警 <span class="version-badge">v{{ version }}</span>
          </h3>
          <div class="stats-badge" v-if="stats">
            <span>{{ totalAlerts }}个预警</span>
            <span class="dot">•</span>
            <span class="danger-count" v-if="dangerCount">{{ dangerCount }}个危险</span>
          </div>
        </div>
        <div class="panel-actions">
          <button class="btn-icon" @click.stop="refresh" :class="{ loading }" title="刷新">
            <span :class="{ 'rotate-animation': loading }">🔄</span>
          </button>
          <button class="btn-icon" @click.stop="markAllAsRead" title="全部标为已读" v-if="hasUnread">
            ✅
          </button>
          <button class="btn-icon" @click.stop="close" title="关闭">✕</button>
        </div>
      </div>

      <!-- 标签页 -->
      <div class="panel-tabs">
        <div class="tabs-left">
          <button class="tab-btn" :class="{ active: view === 'all' }" @click="view = 'all'">
            📋 全部预警
            <span class="tab-count">{{ totalAlerts }}</span>
          </button>
          <button class="tab-btn" :class="{ active: view === 'critical' }" @click="view = 'critical'">
            🔴 严重
            <span class="tab-count">{{ stats?.critical || 0 }}</span>
          </button>
          <button class="tab-btn" :class="{ active: view === 'warning' }" @click="view = 'warning'">
            🟡 警告
            <span class="tab-count">{{ stats?.warning || 0 }}</span>
          </button>
          <button class="tab-btn" :class="{ active: view === 'info' }" @click="view = 'info'">
            🔵 提示
            <span class="tab-count">{{ stats?.info || 0 }}</span>
          </button>
        </div>
      </div>

      <!-- 内容区域 -->
      <div class="panel-content" ref="contentRef">
        <!-- 加载状态 -->
        <div v-if="loading" class="loading-state">
          <div class="loading-spinner"></div>
          <span>加载预警数据...</span>
        </div>

        <!-- 错误状态 -->
        <div v-else-if="error" class="error-state">
          <span class="error-icon">⚠️</span>
          <span>{{ error }}</span>
          <button class="retry-btn" @click="loadData">重试</button>
        </div>

        <!-- 空状态 -->
        <div v-else-if="filteredAlerts.length === 0" class="empty-state">
          <div class="empty-icon">✅</div>
          <div class="empty-text">暂无预警信息</div>
          <div class="empty-desc">一切正常，继续保持</div>
        </div>

        <template v-else>
          <!-- 预警列表 -->
          <div class="alerts-list">
            <div v-for="(alert, index) in paginatedAlerts" :key="alert.id" class="alert-item"
              :class="'alert-' + alert.level">
              <!-- 左侧时间线 -->
              <div class="alert-timeline">
                <div class="timeline-dot" :class="'dot-' + alert.level"></div>
                <div class="timeline-line" v-if="index < paginatedAlerts.length - 1"></div>
              </div>

              <!-- 预警内容 -->
              <div class="alert-content" :class="{ unread: alert.status === 'pending' }">
                <div class="alert-header">
                  <div class="alert-type">
                    <span class="type-icon">{{ getAlertIcon(alert.type) }}</span>
                    <span class="type-name">{{ getAlertTypeName(alert.type) }}</span>
                  </div>
                  <div class="alert-level" :class="'level-' + alert.level">
                    {{ alert.level === 'critical' ? '严重' : alert.level === 'warning' ? '警告' : '提示' }}
                  </div>
                  <div class="alert-time">{{ formatTimeAgo(alert.timestamp) }}</div>
                  <button v-if="alert.status === 'pending'" class="alert-mark-btn" @click.stop="markAsRead(alert.id)">
                    标为已读
                  </button>
                </div>

                <div class="alert-title">{{ alert.title }}</div>
                <div class="alert-message">{{ alert.message }}</div>

                <!-- 预警快照数据 -->
                <div class="alert-snapshot" v-if="alert.snapshot && Object.keys(alert.snapshot).length > 0">
                  <div class="snapshot-grid">
                    <div v-if="alert.snapshot.strength" class="snapshot-item">
                      <span class="snapshot-label">强度</span>
                      <span class="snapshot-value">{{ alert.snapshot.strength }}</span>
                    </div>
                    <div v-if="alert.snapshot.ztCount" class="snapshot-item">
                      <span class="snapshot-label">涨停</span>
                      <span class="snapshot-value">{{ alert.snapshot.ztCount }}</span>
                    </div>
                    <div v-if="alert.snapshot.netInflow" class="snapshot-item">
                      <span class="snapshot-label">主力</span>
                      <span class="snapshot-value" :class="alert.snapshot.netInflow > 0 ? 'inflow' : 'outflow'">
                        {{ formatMoney(alert.snapshot.netInflow) }}
                      </span>
                    </div>
                    <div v-if="alert.snapshot.volumeRatio" class="snapshot-item">
                      <span class="snapshot-label">量比</span>
                      <span class="snapshot-value">{{ alert.snapshot.volumeRatio.toFixed(2) }}</span>
                    </div>
                    <div v-if="alert.snapshot.change" class="snapshot-item">
                      <span class="snapshot-label">涨幅</span>
                      <span class="snapshot-value" :class="alert.snapshot.change >= 0 ? 'up' : 'down'">
                        {{ alert.snapshot.change > 0 ? '+' : '' }}{{ alert.snapshot.change.toFixed(2) }}%
                      </span>
                    </div>
                    <div v-if="alert.snapshot.price" class="snapshot-item">
                      <span class="snapshot-label">价格</span>
                      <span class="snapshot-value">{{ alert.snapshot.price.toFixed(2) }}</span>
                    </div>
                  </div>
                </div>

                <!-- 关联对象 -->
                <div class="alert-meta" v-if="alert.themeName || alert.name">
                  <span v-if="alert.themeName" class="alert-theme" @click.stop="showSectorDetail(alert.themeName)">
                    🔗 {{ alert.themeName }}
                  </span>
                  <span v-if="alert.name" class="alert-stock" @click.stop="selectStock(alert.code!)">
                    📈 {{ alert.name }}
                  </span>
                </div>

                <!-- 状态标签 -->
                <div class="alert-status" :class="alert.status">
                  {{ alert.status === 'pending' ? '未读' : alert.status === 'read' ? '已读' : '已解决' }}
                </div>
              </div>
            </div>
          </div>

          <!-- 加载更多 -->
          <div v-if="hasMore" class="load-more">
            <button class="load-more-btn" @click="loadMore">加载更多 ({{ remainingCount }}条)</button>
          </div>
        </template>
      </div>

      <!-- 底部统计 -->
      <div class="panel-footer" v-if="!loading && !error">
        <div class="footer-left">
          <span>📊 实时监控中</span>
          <span class="dot">•</span>
          <span>⏱️ 最后更新: {{ formatTimeAgo(lastUpdate) }}</span>
        </div>
        <div class="footer-right">
          <span class="stats-summary" v-if="stats">
            🔴 {{ stats.critical }} 🟡 {{ stats.warning }} 🔵 {{ stats.info }}
          </span>
          <button class="clear-btn" @click="clearRead" v-if="hasRead" title="清除所有已读预警">
            🗑️ 清除已读
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { dataLayer } from '@/services/DataLayer'
import { usePanel } from '@/composables/usePanel'
import type { StockAlert } from '@/types/core'
import { ALERT_TYPE_DISPLAY } from '@/config/constants'

const props = defineProps<{
  visible: boolean
  triggerRect?: DOMRect
}>()

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'close'): void
  (e: 'show-detail', sectorName: string): void
}>()

// ========== 版本号 ==========
const version = '6.0.0'

// ========== 视图状态 ==========
const view = ref<'all' | 'critical' | 'warning' | 'info'>('all')
const loading = ref(false)
const error = ref<string | null>(null)
const currentPage = ref(1)
const pageSize = 20
const unsubscribeFns: (() => void)[] = []

// ========== 面板位置 ==========
const { panelRef, panelStyle } = usePanel({
  name: 'SectorAlert',
  visible: props.visible,
  triggerRect: props.triggerRect,
  triggerSelectors: ['[title*="预警"]', '[title*="题材预警"]'],
  onClose: close,
})

// ========== 从 dataLayer 获取预警数据 ==========

// 所有预警
const allAlerts = computed<StockAlert[]>(() => {
  const state = (dataLayer as any).state
  return state?.analysis?.alerts?.items || []
})

// 预警统计
const stats = computed(() => {
  const state = (dataLayer as any).state
  return state?.analysis?.alerts?.stats || {
    total: 0,
    critical: 0,
    warning: 0,
    info: 0,
    byType: {},
    lastUpdate: 0,
  }
})

// 最后更新时间
const lastUpdate = computed(() => {
  const state = (dataLayer as any).state
  return state?.analysis?.alerts?.lastUpdate || Date.now()
})

// 总预警数
const totalAlerts = computed(() => allAlerts.value.length)

// 危险计数（严重级别）
const dangerCount = computed(() => stats.value?.critical || 0)

// 是否有未读预警
const hasUnread = computed(() => allAlerts.value.some(a => a.status === 'pending'))

// 是否有已读预警
const hasRead = computed(() => allAlerts.value.some(a => a.status === 'read'))

// 按级别统计（从数据实时计算，确保准确）
const countByLevel = computed(() => ({
  critical: allAlerts.value.filter(a => a.level === 'critical').length,
  warning: allAlerts.value.filter(a => a.level === 'warning').length,
  info: allAlerts.value.filter(a => a.level === 'info').length,
}))

// 过滤后的预警
const filteredAlerts = computed(() => {
  let filtered = allAlerts.value

  if (view.value !== 'all') {
    filtered = filtered.filter(a => a.level === view.value)
  }

  // 按时间倒序
  return filtered.sort((a, b) => b.timestamp - a.timestamp)
})

// 分页后的预警
const paginatedAlerts = computed(() => {
  return filteredAlerts.value.slice(0, currentPage.value * pageSize)
})

// 是否有更多
const hasMore = computed(() => {
  return paginatedAlerts.value.length < filteredAlerts.value.length
})

// 剩余数量
const remainingCount = computed(() => {
  return filteredAlerts.value.length - paginatedAlerts.value.length
})

// ========== 加载数据 ==========
const loadData = async () => {
  loading.value = true
  error.value = null

  // 模拟加载延迟（实际数据通过计算属性自动响应）
  await new Promise(resolve => setTimeout(resolve, 300))

  if (allAlerts.value.length === 0) {
    // 没有预警不报错，只是空状态
  }

  loading.value = false
}

// ========== 操作函数 ==========
function refresh() {
  // 触发数据刷新
  currentPage.value = 1
  loadData()
}

function close() {
  emit('update:visible', false)
  emit('close')
}

function loadMore() {
  if (hasMore.value) {
    currentPage.value++
  }
}

function markAsRead(alertId: string) {
  // 直接修改 dataLayer 中的数据
  const state = (dataLayer as any).state
  const alert = state?.analysis?.alerts?.items?.find((a: StockAlert) => a.id === alertId)
  if (alert && alert.status === 'pending') {
    alert.status = 'read'
    alert.readTime = Date.now()

    // 更新统计
    updateAlertStats()
  }
}

function markAllAsRead() {
  const state = (dataLayer as any).state
  state?.analysis?.alerts?.items?.forEach((alert: StockAlert) => {
    if (alert.status === 'pending') {
      alert.status = 'read'
      alert.readTime = Date.now()
    }
  })

  // 更新统计
  updateAlertStats()
}

function clearRead() {
  const state = (dataLayer as any).state
  const items = state?.analysis?.alerts?.items || []

  // 过滤掉已读的预警
  state.analysis.alerts.items = items.filter((alert: StockAlert) => alert.status !== 'read')

  // 更新统计
  updateAlertStats()
}

// 更新预警统计
function updateAlertStats() {
  const state = (dataLayer as any).state
  const items = state?.analysis?.alerts?.items || []

  const stats = {
    total: items.length,
    critical: items.filter((a: StockAlert) => a.level === 'critical').length,
    warning: items.filter((a: StockAlert) => a.level === 'warning').length,
    info: items.filter((a: StockAlert) => a.level === 'info').length,
    byType: {} as Record<string, number>,
    lastUpdate: Date.now(),
  }

  items.forEach((alert: StockAlert) => {
    stats.byType[alert.type] = (stats.byType[alert.type] || 0) + 1
  })

  if (state?.analysis?.alerts) {
    state.analysis.alerts.stats = stats
  }
}

function showSectorDetail(themeName: string) {
  emit('show-detail', themeName)
  close()
}

function selectStock(code: string) {
  // 通过事件触发股票选择
  window.dispatchEvent(new CustomEvent('stock:selected', { detail: { code } }))
  close()
}

// ========== 工具函数 ==========

// 预警图标
function getAlertIcon(type: string): string {
  return ALERT_TYPE_DISPLAY[type as keyof typeof ALERT_TYPE_DISPLAY]?.icon || '⚠️'
}

// 预警类型名称
function getAlertTypeName(type: string): string {
  return ALERT_TYPE_DISPLAY[type as keyof typeof ALERT_TYPE_DISPLAY]?.name || type
}

// 金额格式化
function formatMoney(value: number): string {
  if (!value && value !== 0) return '-'
  const absValue = Math.abs(value)
  if (absValue >= 100000000) {
    return (value / 100000000).toFixed(2) + '亿'
  }
  if (absValue >= 10000) {
    return (value / 10000).toFixed(2) + '万'
  }
  return value.toString()
}

// 时间格式化
function formatTimeAgo(timestamp: number): string {
  if (!timestamp) return '未知'
  const diff = Math.floor((Date.now() - timestamp) / 1000)
  if (diff < 60) return diff + '秒前'
  if (diff < 3600) return Math.floor(diff / 60) + '分钟前'
  if (diff < 86400) return Math.floor(diff / 3600) + '小时前'
  return Math.floor(diff / 86400) + '天前'
}

// ========== 监听数据更新 ==========
function handleDataUpdate() {
  // 数据已响应式，不需要额外操作
  // 但可以触发一些UI更新
}

// ========== 生命周期 ==========
onMounted(() => {
  if (props.visible) {
    loadData()
  }

  // 订阅数据更新
  const unsubAlerts = dataLayer.subscribe('analysis.alerts', handleDataUpdate)
  unsubscribeFns.push(unsubAlerts)
})

onUnmounted(() => {
  unsubscribeFns.forEach(fn => fn())
})

// 监听可见性变化
watch(() => props.visible, (newVal) => {
  if (newVal) {
    loadData()
    currentPage.value = 1
  }
})
</script>

<style scoped>
/* 样式保持不变，添加新样式 */
.version-info {
  margin-left: 4px;
  padding: 0 4px;
  background: var(--bg-primary);
  border-radius: 4px;
  font-size: 9px;
  color: var(--text-secondary);
}

.sector-alert-panel {
  position: fixed;
  width: 520px;
  max-width: calc(100vw - 40px);
  max-height: 80vh;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
  z-index: 10007;
  font-size: 12px;
  overflow: hidden;
  backdrop-filter: blur(10px);
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-header);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.panel-header h3 {
  margin: 0;
  font-size: 16px;
  color: #ff4757;
  display: flex;
  align-items: center;
  gap: 8px;
}

.version-badge {
  font-size: 10px;
  background: #ff4757;
  color: #000;
  padding: 2px 6px;
  border-radius: 12px;
}

.stats-badge {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 20px;
  font-size: 10px;
  color: var(--text-secondary);
}

.danger-count {
  color: #ff4757;
  font-weight: 500;
}

.dot {
  opacity: 0.5;
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
  border-radius: 8px;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 16px;
  transition: all 0.2s;
}

.btn-icon:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
  border-color: #ff4757;
}

.panel-tabs {
  display: flex;
  gap: 4px;
  padding: 12px 20px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-secondary);
}

.tabs-left {
  display: flex;
  gap: 4px;
  flex: 1;
}

.tab-btn {
  flex: 1;
  padding: 8px 4px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  border-radius: 8px;
  font-size: 11px;
  transition: all 0.2s;
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
}

.tab-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.tab-btn.active {
  background: #ff4757;
  color: #000;
  font-weight: 500;
}

.tab-count {
  padding: 2px 4px;
  background: rgba(0, 0, 0, 0.1);
  border-radius: 8px;
  font-size: 9px;
}

.panel-content {
  padding: 20px;
  max-height: calc(80vh - 140px);
  overflow-y: auto;
}

/* 预警列表 */
.alerts-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
  position: relative;
}

.alert-item {
  display: flex;
  gap: 16px;
  position: relative;
}

/* 时间线 */
.alert-timeline {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 16px;
}

.timeline-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  z-index: 1;
}

.timeline-dot.dot-info {
  background: #3498db;
  box-shadow: 0 0 0 2px #3498db20;
}

.timeline-dot.dot-warning {
  background: #f39c12;
  box-shadow: 0 0 0 2px #f39c1220;
}

.timeline-dot.dot-critical {
  background: #ff4757;
  box-shadow: 0 0 0 2px #ff475720;
}

.timeline-line {
  width: 2px;
  flex: 1;
  background: var(--border-color);
  margin: 4px 0;
}

/* 预警内容 */
.alert-content {
  flex: 1;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 16px;
  transition: all 0.2s;
  position: relative;
}

.alert-content.unread {
  border-left: 4px solid #ff4757;
}

.alert-item:hover .alert-content {
  border-color: currentColor;
}

.alert-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}

.alert-type {
  display: flex;
  align-items: center;
  gap: 4px;
}

.type-icon {
  font-size: 14px;
}

.type-name {
  font-size: 11px;
  font-weight: 500;
  color: var(--text-primary);
}

.alert-level {
  padding: 2px 8px;
  border-radius: 12px;
  font-size: 9px;
  font-weight: 500;
  text-transform: uppercase;
}

.alert-level.level-info {
  background: #3498db20;
  color: #3498db;
  border: 1px solid #3498db;
}

.alert-level.level-warning {
  background: #f39c1220;
  color: #f39c12;
  border: 1px solid #f39c12;
}

.alert-level.level-critical {
  background: #ff475720;
  color: #ff4757;
  border: 1px solid #ff4757;
}

.alert-time {
  flex: 1;
  text-align: right;
  font-size: 10px;
  color: var(--text-secondary);
}

.alert-mark-btn {
  padding: 2px 8px;
  background: transparent;
  border: 1px solid var(--border-color);
  border-radius: 10px;
  color: var(--text-secondary);
  font-size: 9px;
  cursor: pointer;
}

.alert-mark-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.alert-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-title);
  margin-bottom: 4px;
}

.alert-message {
  font-size: 12px;
  color: var(--text-primary);
  margin-bottom: 12px;
  line-height: 1.4;
}

/* 快照数据 */
.alert-snapshot {
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 12px;
}

.snapshot-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
}

.snapshot-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}

.snapshot-label {
  font-size: 8px;
  color: var(--text-secondary);
}

.snapshot-value {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-primary);
}

.snapshot-value.inflow {
  color: #ff4757;
}

.snapshot-value.outflow {
  color: #3498db;
}

.snapshot-value.up {
  color: #ff4757;
}

.snapshot-value.down {
  color: #2ed573;
}

/* 关联对象 */
.alert-meta {
  display: flex;
  gap: 12px;
  margin-bottom: 8px;
}

.alert-theme,
.alert-stock {
  font-size: 10px;
  padding: 2px 8px;
  background: var(--bg-primary);
  border-radius: 10px;
  color: var(--text-secondary);
  cursor: pointer;
}

.alert-theme:hover,
.alert-stock:hover {
  background: var(--bg-hover);
  color: var(--color-highlight);
}

/* 状态标签 */
.alert-status {
  position: absolute;
  top: 16px;
  right: 16px;
  font-size: 9px;
  padding: 2px 8px;
  border-radius: 10px;
  background: var(--bg-primary);
}

.alert-status.pending {
  color: #ff4757;
  border: 1px solid #ff4757;
}

.alert-status.read {
  color: #3498db;
  border: 1px solid #3498db;
}

.alert-status.resolved {
  color: #2ed573;
  border: 1px solid #2ed573;
}

/* 加载更多 */
.load-more {
  display: flex;
  justify-content: center;
  padding: 20px 0;
}

.load-more-btn {
  padding: 8px 20px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 20px;
  color: var(--text-secondary);
  font-size: 11px;
  cursor: pointer;
  transition: all 0.2s;
}

.load-more-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
  border-color: #ff4757;
}

/* 底部 */
.panel-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 20px;
  border-top: 1px solid var(--border-color);
  background: var(--bg-header);
  font-size: 10px;
  color: var(--text-secondary);
}

.footer-left {
  display: flex;
  align-items: center;
  gap: 4px;
}

.footer-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.stats-summary {
  font-size: 10px;
  color: var(--text-secondary);
}

.clear-btn {
  padding: 4px 12px;
  background: transparent;
  border: 1px solid var(--border-color);
  border-radius: 16px;
  color: var(--text-secondary);
  font-size: 10px;
  cursor: pointer;
  transition: all 0.2s;
}

.clear-btn:hover {
  background: #ff475720;
  border-color: #ff4757;
  color: #ff4757;
}

/* 加载状态 */
.loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  gap: 16px;
}

.loading-spinner {
  width: 40px;
  height: 40px;
  border: 3px solid var(--border-color);
  border-top-color: #ff4757;
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  gap: 12px;
}

.empty-icon {
  font-size: 48px;
  opacity: 0.5;
}

.empty-text {
  font-size: 16px;
  font-weight: 500;
  color: var(--text-title);
}

.empty-desc {
  font-size: 12px;
  color: var(--text-secondary);
}

.error-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 60px 20px;
  gap: 12px;
}

.error-icon {
  font-size: 32px;
}

.retry-btn {
  padding: 8px 16px;
  background: #ff4757;
  border: none;
  border-radius: 20px;
  color: #000;
  font-size: 12px;
  cursor: pointer;
}

.rotate-animation {
  animation: rotate 1s infinite linear;
  display: inline-block;
}

@keyframes rotate {
  from {
    transform: rotate(0deg);
  }

  to {
    transform: rotate(360deg);
  }
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
