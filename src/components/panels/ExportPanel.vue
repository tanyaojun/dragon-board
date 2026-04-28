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
import { dragonAnalyzer } from '@/services/DragonAnalyzer'
import { dragonBreathAnalyzer } from '@/services/DragonBreathAnalyzer'
import { sectorAnalyzer } from '@/services/sectorAnalyzer'
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
  return {
    top: props.triggerRect.bottom + 5 + 'px',
    right: '10px',
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
    const byLevel = dragonAnalyzer.getStats()
    stats.push(
      { label: '总龙头', value: byLevel.totalLeadersCount },
      { label: '板块龙头', value: byLevel.sectorLeaders },
      { label: '连板龙头', value: byLevel.continuousLeaders },
    )
  }

  if (previewData.value.sectors) {
    stats.push(
      { label: '题材总数', value: previewData.value.sectors.length },
      { label: '热门题材', value: sectorAnalyzer.getHotThemes?.(5).length || 0 },
    )
  }

  if (previewData.value.market) {
    stats.push(
      { label: '情绪指数', value: previewData.value.market.sentiment.overall + '分' },
      { label: '市场阶段', value: previewData.value.market.sentiment.phase },
    )
  }

  return stats
})

function isLeaderStock(code: string): boolean {
  const leaders = dragonAnalyzer.getAllLeaders?.() || []
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
          previewData.value = { sectors: sectorAnalyzer.getHotThemes?.(50) || [] }
          break
        case 'market':
          previewData.value = {
            market: {
              sentiment: dragonBreathAnalyzer.getMarketSentiment(),
              marketData: dragonBreathAnalyzer.getMarketData(),
              leaders: dragonAnalyzer.getStats(),
            },
          }
          break
        case 'all':
          previewData.value = {
            stocks: dataLayer.getStocks(),
            leaders: dataLayer.getStocks().filter(s => isLeaderStock(s.code)),
            sectors: sectorAnalyzer.getHotThemes?.(50) || [],
            market: {
              sentiment: dragonBreathAnalyzer.getMarketSentiment(),
              marketData: dragonBreathAnalyzer.getMarketData(),
              leaders: dragonAnalyzer.getStats(),
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
/* 样式保持不变，添加状态样式 */
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

/* 其他样式保持不变 */
</style>
