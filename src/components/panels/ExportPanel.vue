<!-- src/components/panels/ExportPanel.vue -->
<template>
  <Teleport to="body">
    <div v-if="visible" class="export-panel" :style="panelStyle" ref="panelRef">
      <div class="panel-header">
        <h3>📤 数据导出</h3>
        <div class="panel-actions">
          <button class="btn-icon" @click.stop="close" title="关闭">✕</button>
        </div>
      </div>

      <div class="panel-content">
        <div class="export-section">
          <h4>📊 导出选项</h4>

          <div class="form-group">
            <label>数据范围</label>
            <select v-model="range" class="form-select">
              <option value="stocks">全部股票</option>
              <option value="leaders">龙头股票</option>
              <option value="sectors">题材数据</option>
              <option value="market">市场情绪</option>
              <option value="all">完整数据</option>
            </select>
          </div>

          <div class="form-group">
            <label>文件格式</label>
            <div class="format-options">
              <label class="radio-label">
                <input type="radio" v-model="format" value="csv" />
                <span>CSV</span>
              </label>
              <label class="radio-label">
                <input type="radio" v-model="format" value="json" />
                <span>JSON</span>
              </label>
              <label class="radio-label">
                <input type="radio" v-model="format" value="excel" />
                <span>Excel</span>
              </label>
            </div>
          </div>

          <div class="form-group">
            <label>文件名</label>
            <input type="text" v-model="filename" class="form-input" placeholder="自定义文件名" />
          </div>

          <div class="form-group" v-if="format === 'csv'">
            <label>
              <input type="checkbox" v-model="includeHeaders" />
              包含表头
            </label>
          </div>

          <div class="preview-section" v-if="previewData">
            <h4>👀 数据预览</h4>
            <div class="preview-stats">
              <div class="stat-item" v-for="stat in previewStats" :key="stat.label">
                <span class="stat-label">{{ stat.label }}</span>
                <span class="stat-value">{{ stat.value }}</span>
              </div>
            </div>
          </div>
        </div>

        <div class="export-actions">
          <button class="btn btn-primary" @click="handleExport" :disabled="exporting">
            <span v-if="exporting" class="spinner">⏳</span>
            <span v-else>📥 导出数据</span>
          </button>
          <button class="btn" @click="preview" :disabled="previewing">
            <span v-if="previewing" class="spinner">⏳</span>
            <span v-else>👀 预览</span>
          </button>
          <button class="btn" @click="close">取消</button>
        </div>

        <div v-if="lastExport" class="export-status">
          <div class="status-message" :class="{ success: lastExport.success, error: !lastExport.success }">
            <span v-if="lastExport.success">✅ 导出成功</span>
            <span v-else>❌ 导出失败</span>
            <span class="status-detail">{{ lastExport.message }}</span>
          </div>
        </div>

        <div v-if="exportHistory.length" class="export-history">
          <h4>📋 最近导出</h4>
          <div class="history-item" v-for="item in exportHistory" :key="item.time">
            <span class="history-name">{{ item.name }}</span>
            <span class="history-time">{{ formatTime(item.time) }}</span>
            <span class="history-size">{{ item.size }}</span>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { exportService } from '@/services/exportService'
import { dragonReviewService } from '@/services/dragon/DragonReviewService'
import { dragonBreathAnalyzer } from '@/services/DragonBreathAnalyzer'
import { sectorAnalyzer } from '@/services/sectorAnalyzer'
import { themeFacade } from '@/services/theme/ThemeFacade'
import { dataLayer } from '@/services/DataLayer'
import { EventManager } from '@/utils/eventManager'
import { AppEvents } from '@/types'

const props = defineProps<{
  visible: boolean
  triggerRect?: DOMRect
}>()

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'close'): void
}>()

// ========== 状态 ==========
const panelRef = ref<HTMLElement | null>(null)
const range = ref('stocks')
const format = ref('csv')
const filename = ref('')
const includeHeaders = ref(true)
const exporting = ref(false)
const previewing = ref(false)
const lastExport = ref<any>(null)
const previewData = ref<any>(null)
const exportTimer = ref<ReturnType<typeof setTimeout> | null>(null)

const exportHistory = ref<Array<{ name: string; time: number; size: string }>>([])

// ========== 计算属性 ==========
const panelStyle = computed(() => {
  if (!props.triggerRect) {
    return { top: '100px', right: '20px' }
  }
  const top = Math.min(props.triggerRect.bottom + 8, window.innerHeight - 520)
  return {
    top: Math.max(64, top) + 'px',
    right: '20px',
  }
})

const previewStats = computed(() => {
  if (!previewData.value) return []

  const stats = []

  if (previewData.value.stocks) {
    const stocks = previewData.value.stocks
    const leaders = stocks.filter((s: any) => isLeaderStock(s.code))
    stats.push(
      { label: '股票总数', value: stocks.length },
      { label: '龙头数量', value: leaders.length },
    )
  }

  if (previewData.value.leaders) {
    const byLevel = dragonReviewService.getStats()
    stats.push(
      { label: '总龙头', value: byLevel.totalLeadersCount },
      { label: '板块龙头', value: byLevel.sectorLeaders },
      { label: '连板龙头', value: byLevel.continuousLeaders },
    )
  }

  if (previewData.value.sectors) {
    stats.push(
      { label: '题材总数', value: previewData.value.sectors.length },
      { label: '热门题材', value: themeFacade.getHotThemes?.(5).length || 0 },
    )
  }

  if (previewData.value.market) {
    const sentiment = previewData.value.market.sentiment || {}
    stats.push(
      { label: '情绪阶段', value: sentiment.phaseName || sentiment.phase || '-' },
      { label: '风险等级', value: sentiment.riskLevel || '-' },
    )
  }

  return stats
})

function isLeaderStock(code: string): boolean {
  const leaders = dragonReviewService.getAllLeaders?.() || []
  return leaders.some((leader: any) => leader.code === code)
}

// ========== 方法 ==========
async function preview() {
  if (previewing.value) return
  previewing.value = true

  if (exportTimer.value) {
    clearTimeout(exportTimer.value)
  }

  exportTimer.value = setTimeout(async () => {
    try {
      switch (range.value) {
        case 'stocks':
          previewData.value = { stocks: dataLayer.getStocks() }
          break
        case 'leaders':
          previewData.value = {
            leaders: dataLayer.getStocks().filter(s => isLeaderStock(s.code))
          }
          break
        case 'sectors':
          previewData.value = { sectors: themeFacade.getHotThemes?.(50) || [] }
          break
        case 'market':
          previewData.value = {
            market: {
              sentiment: dragonBreathAnalyzer.getMarketSentiment(),
              marketData: dragonBreathAnalyzer.getMarketData(),
              leaders: dragonReviewService.getStats(),
            },
          }
          break
        case 'all':
          previewData.value = {
            stocks: dataLayer.getStocks(),
            leaders: dataLayer.getStocks().filter(s => isLeaderStock(s.code)),
            sectors: themeFacade.getHotThemes?.(50) || [],
            market: {
              sentiment: dragonBreathAnalyzer.getMarketSentiment(),
              marketData: dragonBreathAnalyzer.getMarketData(),
              leaders: dragonReviewService.getStats(),
            },
          }
          break
      }

      EventManager.emit(AppEvents.UI.TOAST, {
        message: '👀 预览数据已更新',
        duration: 1000,
        type: 'info',
      })
    } catch (error) {
      console.error('[ExportPanel] 预览失败:', error)
      EventManager.emit(AppEvents.UI.TOAST, {
        message: '❌ 预览失败',
        duration: 1500,
        type: 'error',
      })
    } finally {
      previewing.value = false
      exportTimer.value = null
    }
  }, 300)
}

async function handleExport() {
  if (exporting.value) {
    EventManager.emit(AppEvents.UI.TOAST, {
      message: '⏳ 正在导出中，请稍候',
      duration: 1500,
      type: 'info',
    })
    return
  }

  if (exportTimer.value) {
    clearTimeout(exportTimer.value)
  }

  exportTimer.value = setTimeout(async () => {
    exporting.value = true

    try {
      const options = {
        format: format.value as any,
        filename: filename.value || undefined,
        includeHeaders: includeHeaders.value,
      }

      let result
      switch (range.value) {
        case 'stocks':
          result = await exportService.exportStocks(options)
          break
        case 'leaders':
          result = await exportService.exportLeaders(options)
          break
        case 'sectors':
          result = await exportService.exportSectors(options)
          break
        case 'market':
          result = await exportService.exportMarket(options)
          break
        case 'all':
          result = await exportService.exportAll(options)
          break
      }

      if (!result) {
        throw new Error('导出未返回结果')
      }

      const sizeStr = result.size ? `${(result.size / 1024).toFixed(1)}KB` : '--'
      exportHistory.value.unshift({
        name: filename.value || `${range.value}_${new Date().toLocaleString()}`,
        time: Date.now(),
        size: sizeStr,
      })

      if (exportHistory.value.length > 10) {
        exportHistory.value = exportHistory.value.slice(0, 10)
      }

      lastExport.value = { success: true, message: `已导出 ${sizeStr}` }

      EventManager.emit(AppEvents.UI.TOAST, {
        message: '✅ 数据导出成功',
        duration: 1500,
        type: 'success',
      })

      close()
    } catch (error: any) {
      console.error('[ExportPanel] 导出失败:', error)
      lastExport.value = { success: false, message: error.message || '未知错误' }
      EventManager.emit(AppEvents.UI.TOAST, {
        message: '❌ 导出失败',
        duration: 1500,
        type: 'error',
      })
    } finally {
      exporting.value = false
      exportTimer.value = null
    }
  }, 300)
}

function close() {
  if (exportTimer.value) {
    clearTimeout(exportTimer.value)
    exportTimer.value = null
  }
  exportService.cancelAll?.()
  emit('update:visible', false)
  emit('close')
  EventManager.emit(AppEvents.UI.PANEL_CLOSE, { panel: 'export' })
}

function formatTime(timestamp: number): string {
  const date = new Date(timestamp)
  return `${date.getHours()}:${String(date.getMinutes()).padStart(2, '0')}`
}

function handleClickOutside(e: MouseEvent) {
  if (panelRef.value && !panelRef.value.contains(e.target as Node)) {
    close()
  }
}

onMounted(() => {
  setTimeout(() => {
    document.addEventListener('click', handleClickOutside)
  }, 100)
  EventManager.emit(AppEvents.UI.PANEL_OPEN, { panel: 'export' })
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
  if (exportTimer.value) {
    clearTimeout(exportTimer.value)
  }
})
</script>

<style scoped>
.export-panel {
  position: fixed;
  z-index: 1300;
  width: min(420px, calc(100vw - 32px));
  max-height: calc(100vh - 96px);
  color: var(--text-primary);
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  box-shadow: 0 18px 42px rgb(0 0 0 / 42%);
  overflow: hidden;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border-color);
}

.panel-header h3,
.export-section h4,
.preview-section h4,
.export-history h4 {
  margin: 0;
}

.panel-header h3 {
  font-size: 15px;
  font-weight: 700;
}

.panel-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.btn-icon {
  width: 28px;
  height: 28px;
  color: var(--text-secondary);
  background: transparent;
  border: 1px solid transparent;
  border-radius: 6px;
  cursor: pointer;
}

.btn-icon:hover {
  color: var(--text-primary);
  background: var(--bg-hover);
  border-color: var(--border-color);
}

.panel-content {
  max-height: calc(100vh - 152px);
  padding: 16px;
  overflow-y: auto;
}

.export-section {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.export-section h4,
.preview-section h4,
.export-history h4 {
  font-size: 13px;
  font-weight: 700;
  color: var(--text-primary);
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.form-group label {
  font-size: 12px;
  color: var(--text-secondary);
}

.form-select,
.form-input {
  width: 100%;
  height: 34px;
  padding: 0 10px;
  color: var(--text-primary);
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  outline: none;
}

.form-select:focus,
.form-input:focus {
  border-color: var(--color-highlight);
  box-shadow: 0 0 0 2px rgb(255 139 58 / 18%);
}

.format-options {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
}

.radio-label {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-height: 34px;
  padding: 0 10px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  cursor: pointer;
}

.radio-label:has(input:checked) {
  color: var(--color-highlight);
  border-color: var(--color-highlight);
  background: rgb(255 139 58 / 10%);
}

.preview-section {
  margin-top: 2px;
  padding: 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
}

.preview-stats {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin-top: 10px;
}

.stat-item {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  font-size: 12px;
}

.stat-label {
  color: var(--text-secondary);
}

.stat-value {
  font-weight: 700;
  color: var(--color-highlight);
}

.export-actions {
  display: flex;
  gap: 8px;
  margin-top: 16px;
}

.btn {
  min-width: 76px;
  height: 34px;
  padding: 0 12px;
  color: var(--text-primary);
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  cursor: pointer;
}

.btn:hover:not(:disabled) {
  background: var(--bg-hover);
}

.btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.btn-primary {
  color: #fff;
  background: var(--color-highlight);
  border-color: var(--color-highlight);
}

.spinner {
  display: inline-block;
}

.export-status {
  margin-top: 16px;
  padding: 12px;
  background: var(--bg-secondary);
  border-radius: 8px;
}

.status-message {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}

.status-message.success {
  color: #2ecc71;
}

.status-message.error {
  color: #e74c3c;
}

.status-detail {
  margin-left: auto;
  font-size: 11px;
  color: var(--text-secondary);
}

.export-history {
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid var(--border-color);
}

.history-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  gap: 10px;
  align-items: center;
  padding: 8px 0;
  font-size: 12px;
  border-bottom: 1px solid var(--border-color);
}

.history-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.history-time,
.history-size {
  color: var(--text-secondary);
}

@media (max-width: 520px) {
  .export-panel {
    left: 16px;
    right: 16px !important;
    width: auto;
  }

  .format-options,
  .preview-stats {
    grid-template-columns: 1fr;
  }

  .export-actions {
    flex-wrap: wrap;
  }
}
</style>
