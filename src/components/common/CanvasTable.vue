<!-- src/components/common/CanvasTable.vue -->
<template>
  <div class="canvas-table-container" ref="containerRef">
    <canvas ref="canvasRef" @wheel="handleWheel" @mousedown="handleMouseDown" @mousemove="handleMouseMove"
      @mouseup="handleMouseUp"></canvas>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, getCurrentInstance } from 'vue'
import { EventManager } from '@/utils/eventManager'
import { dataLayer } from '@/services/DataLayer'
import { dragonLifecycle, LIFECYCLE_STAGES } from '@/services/DragonLifecycle'

// ========== 热更新清理 ==========
const instance = getCurrentInstance()
if (import.meta.hot) {
  import.meta.hot.dispose(() => {
    console.log('[CanvasTable] 热更新清理旧实例')
    // 清理全局变量
    if (canvasRef?.value) {
      const oldCanvas = canvasRef.value
      const ctx = oldCanvas.getContext('2d')
      ctx?.clearRect(0, 0, 10000, 10000)
    }
    ctx = null
    stocks = []
    lifecycleCache = new Map()
    observationCache = new Map()
  })
}

// ========== 配置 ==========
const ROW_HEIGHT = 35
const HEADER_HEIGHT = 42
const BUFFER_ROWS = 5

// ========== 列配置 ==========
const columns = [
  { key: 'code', label: '代码', width: 80, align: 'left' },
  { key: 'name', label: '名称', width: 120, align: 'left' },
  { key: 'themes', label: '题材', width: 200, align: 'left' },
  { key: 'lifecycle', label: '生命周期', width: 180, align: 'center' },
  { key: 'price', label: '最新价', width: 80, align: 'right' },
  { key: 'change', label: '涨幅%', width: 80, align: 'right' },
  { key: 'turnoverRate', label: '换手%', width: 80, align: 'right' },
  { key: 'emRank', label: '东财', width: 50, align: 'right' },
  { key: 'thsRank', label: '同花顺', width: 50, align: 'right' },
  { key: 'kplRank', label: '开盘啦', width: 50, align: 'right' },
  { key: 'tdxRank', label: '通达信', width: 50, align: 'right' },
  { key: 'xqRank', label: '雪球', width: 50, align: 'right' },
  { key: 'clsRank', label: '财联社', width: 50, align: 'right' },
  { key: 'tgbRank', label: '淘股吧', width: 50, align: 'right' },
  { key: 'dzhRank', label: '大智慧', width: 50, align: 'right' },
  { key: 'avgRank', label: '热度', width: 60, align: 'right' },
  { key: 'compRank', label: '综合', width: 60, align: 'right' },
  { key: 'rankChange', label: '变化', width: 60, align: 'center' },
  { key: 'zlje', label: '主力净额', width: 90, align: 'right' },
  { key: 'zljzb', label: '主力%', width: 90, align: 'right' },
  { key: 'cddje', label: '超大单', width: 90, align: 'right' },
  { key: 'cddjzb', label: '超大%', width: 90, align: 'right' },
  { key: 'volume', label: '成交量', width: 90, align: 'right' },
  { key: 'turnover', label: '成交额', width: 90, align: 'right' },
]

// ========== 状态 ==========
const containerRef = ref<HTMLElement>()
const canvasRef = ref<HTMLCanvasElement>()
let ctx: CanvasRenderingContext2D | null = null

let stocks: any[] = []
let lifecycleCache = new Map()
let observationCache = new Map()

let containerWidth = 0
let containerHeight = 0
let scrollTop = 0
let isDragging = false
let lastMouseY = 0

// 列位置缓存
let columnPositions: { key: string; x: number; width: number }[] = []

// 选中行
let selectedCode: string | null = null

// 排序
let sortKey = 'compRank'
let sortOrder: 'asc' | 'desc' = 'desc'

// ========== 初始化 ==========
onMounted(() => {
  console.log('[CanvasTable]  mounted')
  initCanvas()
  loadData()
  setupResizeObserver()
  setupEventListeners()
})

onUnmounted(() => {
  if (resizeObserver) resizeObserver.disconnect()
})

// ========== Canvas 初始化 ==========
function initCanvas() {
  // ✅ 如果已经有上下文且不是当前实例，清理
  if (ctx && canvasRef.value && !canvasRef.value.isConnected) {
    console.log('[CanvasTable] 清理失效上下文')
    ctx = null
  }
  const canvas = canvasRef.value!
  const container = containerRef.value!

  if (!canvas || !container) {
    console.error('[CanvasTable] canvas or container not found')
    return
  }

  // ✅ 标记当前实例
  canvas.setAttribute('data-instance', Date.now().toString())

  ctx = canvas.getContext('2d')!

  const updateSize = () => {
    containerWidth = container.clientWidth
    containerHeight = container.clientHeight

    // ✅ 修复：正确设置 canvas 尺寸
    canvas.width = containerWidth * window.devicePixelRatio
    canvas.height = containerHeight * window.devicePixelRatio
    canvas.style.width = containerWidth + 'px'
    canvas.style.height = containerHeight + 'px'

    // ✅ 修复：缩放上下文
    ctx!.setTransform(1, 0, 0, 1, 0, 0) // 重置变换
    ctx!.scale(window.devicePixelRatio, window.devicePixelRatio)

    calculateColumnPositions()
    render()
  }

  updateSize()
  window.addEventListener('resize', updateSize)
}

// ========== 列位置计算 ==========
function calculateColumnPositions() {
  let x = 0
  columnPositions = columns.map(col => {
    const pos = { key: col.key, x, width: col.width }
    x += col.width
    return pos
  })
  console.log('[CanvasTable] column positions:', columnPositions.length)
}

// ========== 数据加载 ==========
function loadData() {
  stocks = dataLayer.getStocks() || []
  console.log('[CanvasTable] loaded stocks:', stocks.length)
  updateLifecycleCache()
}

function updateLifecycleCache() {
  const newCache = new Map()
  const newObsCache = new Map()

  stocks.forEach(stock => {
    const lifecycle = dragonLifecycle.getLifecycle(stock.code)
    if (lifecycle) newCache.set(stock.code, lifecycle)

    const queues = dragonLifecycle.getObservationQueues?.()
    if (queues) {
      const inPrimary = queues.primary.find((q: any) => q.code === stock.code)
      const inSecondary = queues.secondary.find((q: any) => q.code === stock.code)
      const inCold = queues.cold.find((q: any) => q.code === stock.code)
      if (inPrimary || inSecondary || inCold) {
        newObsCache.set(stock.code, {
          queue: inPrimary ? 'primary' : inSecondary ? 'secondary' : 'cold'
        })
      }
    }
  })

  lifecycleCache = newCache
  observationCache = newObsCache
}

// ========== 排序 ==========
function sortedStocks() {
  return [...stocks].sort((a, b) => {
    const aVal = a[sortKey] ?? 0
    const bVal = b[sortKey] ?? 0
    return sortOrder === 'asc' ? aVal - bVal : bVal - aVal
  })
}

// 第150行附近，把这两个函数定义提前

// ========== 渲染函数 ==========
function renderHeader() {
  if (!ctx) return

  ctx.save()

  // 表头背景
  ctx.fillStyle = '#333333'
  ctx.fillRect(0, 0, containerWidth, HEADER_HEIGHT)

  // 表头文字
  ctx.font = 'bold 12px -apple-system, BlinkMacSystemFont, sans-serif'
  ctx.fillStyle = '#ffb142'
  ctx.textBaseline = 'middle'

  columnPositions.forEach(col => {
    const column = columns.find(c => c.key === col.key)!
    let x = col.x
    if (column.align === 'right') x += col.width - 8
    else if (column.align === 'center') x += col.width / 2
    else x += 8

    ctx.textAlign = column.align as CanvasTextAlign
    ctx.fillText(column.label, x, HEADER_HEIGHT / 2)

    // 排序箭头
    if (col.key === sortKey) {
      ctx.font = '10px -apple-system'
      ctx.fillStyle = '#ffb142'
      const arrowX = column.align === 'right' ? x - 12 : x + 25
      ctx.fillText(sortOrder === 'asc' ? '↑' : '↓', arrowX, HEADER_HEIGHT / 2)
    }
  })

  // 绘制边框
  ctx.strokeStyle = '#4a4a4a'
  ctx.lineWidth = 1
  ctx.beginPath()
  ctx.moveTo(0, HEADER_HEIGHT)
  ctx.lineTo(containerWidth, HEADER_HEIGHT)
  ctx.stroke()

  ctx.restore()
}

function renderRows() {
  if (!ctx) return

  const data = sortedStocks()

  if (data.length === 0) {
    ctx.save()
    ctx.font = '14px -apple-system'
    ctx.fillStyle = '#666'
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillText('暂无数据', containerWidth / 2, containerHeight / 2)
    ctx.restore()
    return
  }

  const startRow = Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - BUFFER_ROWS)
  const endRow = Math.min(data.length, Math.ceil((scrollTop + containerHeight - HEADER_HEIGHT) / ROW_HEIGHT) + BUFFER_ROWS)

  for (let i = startRow; i < endRow; i++) {
    const stock = data[i]
    const y = HEADER_HEIGHT + i * ROW_HEIGHT - scrollTop

    // 行背景
    ctx.fillStyle = i % 2 === 0 ? '#1a1a1a' : '#1e1e1e'
    ctx.fillRect(0, y, containerWidth, ROW_HEIGHT - 1)

    // 选中高亮
    if (stock.code === selectedCode) {
      ctx.fillStyle = 'rgba(255, 165, 2, 0.08)'
      ctx.fillRect(0, y, containerWidth, ROW_HEIGHT - 1)
    }

    // 龙头样式
    if (stock.isSectorLeader) {
      ctx.fillStyle = getLeaderColor(stock.leaderLevel)
      ctx.fillRect(0, y, 3, ROW_HEIGHT - 1)
    }

    // 绘制单元格
    columnPositions.forEach(col => {
      const column = columns.find(c => c.key === col.key)!
      const value = stock[col.key]
      let x = col.x
      if (column.align === 'right') x += col.width - 8
      else if (column.align === 'center') x += col.width / 2
      else x += 8

      ctx.textAlign = column.align as CanvasTextAlign
      ctx.textBaseline = 'middle'
      ctx.font = '12px -apple-system, BlinkMacSystemFont, monospace'

      if (col.key === 'themes') {
        const theme = stock.themes?.[0]
        if (theme) {
          // ✅ 修复：从对象中获取 name 属性
          let themeText = ''
          if (theme.name) {
            themeText = theme.name
          } else if (typeof theme === 'string') {
            themeText = theme
          } else {
            themeText = String(theme) || '题材'
          }

          ctx.fillStyle = '#5a5a5a'
          ctx.fillRect(col.x + 4, y + 4, col.width - 8, ROW_HEIGHT - 8)
          ctx.fillStyle = '#e0e0e0'
          ctx.font = '11px -apple-system'
          ctx.fillText(themeText.substring(0, 6), col.x + 8, y + ROW_HEIGHT / 2)
        } else {
          ctx.fillStyle = '#666'
          ctx.fillText('-', x, y + ROW_HEIGHT / 2)
        }
      }
      else if (col.key === 'lifecycle') {
        renderLifecycleCell(stock, col, x, y)
      }
      else {
        ctx.fillStyle = getCellColor(col.key, stock, value)
        ctx.fillText(formatCell(col.key, value), x, y + ROW_HEIGHT / 2)
      }
    })
  }
}

function renderLifecycleCell(stock: any, col: any, x: number, y: number) {
  if (!ctx) return

  const lifecycle = lifecycleCache.get(stock.code)
  const observation = observationCache.get(stock.code)

  if (lifecycle) {
    const stage = lifecycle.currentStage?.toUpperCase()
    const stageInfo = LIFECYCLE_STAGES[stage]
    const text = `${stageInfo?.icon || '🔄'} ${stageInfo?.name || lifecycle.currentStage}`

    ctx.font = '10px -apple-system'
    const metrics = ctx.measureText(text)
    const padding = 8
    const bgWidth = metrics.width + padding

    ctx.fillStyle = (stageInfo?.color || '#666') + '20'
    ctx.fillRect(x - bgWidth / 2, y + 4, bgWidth, ROW_HEIGHT - 8)

    ctx.fillStyle = stageInfo?.color || '#666'
    ctx.fillText(text, x, y + ROW_HEIGHT / 2)
  }
  else if (observation) {
    const queueColors = { primary: '#2ecc71', secondary: '#3498db', cold: '#9b59b6' }
    const color = queueColors[observation.queue as keyof typeof queueColors]
    const text = '⏳ 观察中'

    ctx.font = '10px -apple-system'
    const metrics = ctx.measureText(text)
    const padding = 8
    const bgWidth = metrics.width + padding

    ctx.fillStyle = color + '20'
    ctx.fillRect(x - bgWidth / 2, y + 4, bgWidth, ROW_HEIGHT - 8)
    ctx.fillStyle = color
    ctx.fillText(text, x, y + ROW_HEIGHT / 2)
  }
  else {
    ctx.fillStyle = '#666'
    ctx.fillText('-', x, y + ROW_HEIGHT / 2)
  }
}

// ========== 主渲染函数 ==========
function render() {
  if (!ctx || !canvasRef.value) {
    console.error('[CanvasTable] ctx not ready')
    return
  }

  console.log('[CanvasTable] rendering...', stocks.length)

  // 清空画布
  ctx.clearRect(0, 0, containerWidth, containerHeight)

  // 绘制背景
  ctx.fillStyle = '#1a1a1a'
  ctx.fillRect(0, 0, containerWidth, containerHeight)

  // 绘制表头
  renderHeader()

  // 绘制行
  renderRows()
}

// ========== 格式化 ==========
function formatCell(key: string, value: any): string {
  if (value === undefined || value === null) return '-'

  // 排名列
  if (key.includes('Rank') && key !== 'rankChange') {
    return value === 999 ? '-' : value.toString()
  }

  // 变化列
  if (key === 'rankChange') {
    if (value === 0) return '-'
    return (value > 0 ? '↑' : '↓') + Math.abs(value)
  }

  // 百分比
  if (key.includes('Rate') || key === 'change' || key.includes('zb')) {
    if (!value) return '-'
    const num = Number(value)
    return (num > 0 ? '+' : '') + num.toFixed(2) + '%'
  }

  // 金额
  if (['zlje', 'cddje', 'turnover', 'cirMV', 'totalMV'].includes(key)) {
    return formatMoney(Number(value))
  }

  // 成交量
  if (key === 'volume') return formatVolume(Number(value))

  // 价格
  if (key === 'price') return Number(value).toFixed(2)
  if (key === 'pb') return Number(value).toFixed(2)

  return value?.toString() || '-'
}

function formatMoney(value: number): string {
  if (!value) return '-'
  const abs = Math.abs(value)
  if (abs >= 1e8) return (value / 1e8).toFixed(2) + '亿'
  if (abs >= 1e4) return (value / 1e4).toFixed(2) + '万'
  return value.toString()
}

function formatVolume(value: number): string {
  if (!value) return '-'
  const abs = Math.abs(value)
  if (abs >= 1e8) return (value / 1e8).toFixed(2) + '亿'
  if (abs >= 1e4) return (value / 1e4).toFixed(2) + '万'
  return value.toString()
}


function getCellColor(key: string, stock: any, value: any): string {
  if (key === 'change') {
    return value > 0 ? '#ff4757' : value < 0 ? '#2ed573' : '#e0e0e0'
  }
  if (key === 'rankChange') {
    return value > 0 ? '#ff4757' : value < 0 ? '#2ed573' : '#e0e0e0'
  }
  if (['zlje', 'cddje'].includes(key)) {
    return value > 0 ? '#ff4757' : value < 0 ? '#2ed573' : '#e0e0e0'
  }
  if (['compRank', 'avgRank'].includes(key)) {
    return '#ffa502'
  }
  return '#e0e0e0'
}

function getLeaderColor(level: string): string {
  const colors: Record<string, string> = {
    '总龙头': '#FFD700',
    '连板龙头': '#e74c3c',
    '板块龙头': '#3498db',
    '中军龙头': '#9b59b6',
    '情绪龙头': '#f39c12'
  }
  return colors[level] || '#FFD700'
}

// ========== 事件处理 ==========
function handleWheel(e: WheelEvent) {
  e.preventDefault()
  const maxScroll = Math.max(0, stocks.length * ROW_HEIGHT - containerHeight + HEADER_HEIGHT)
  scrollTop = Math.max(0, Math.min(scrollTop + e.deltaY, maxScroll))
  render()
}

function handleMouseDown(e: MouseEvent) {
  const rect = canvasRef.value!.getBoundingClientRect()
  const x = e.clientX - rect.left
  const y = e.clientY - rect.top

  // 表头点击 - 排序
  if (y < HEADER_HEIGHT) {
    let xPos = 0
    for (const col of columns) {
      if (x >= xPos && x < xPos + col.width) {
        if (sortKey === col.key) {
          sortOrder = sortOrder === 'asc' ? 'desc' : 'asc'
        } else {
          sortKey = col.key
          sortOrder = 'desc'
        }
        render()
        break
      }
      xPos += col.width
    }
    return
  }

  // 行点击 - 选中
  const rowIndex = Math.floor((scrollTop + y - HEADER_HEIGHT) / ROW_HEIGHT)
  const data = sortedStocks()
  if (rowIndex >= 0 && rowIndex < data.length) {
    selectedCode = data[rowIndex].code
    EventManager.emit('stock:selected', { code: selectedCode })
    render()
  }

  // 开始拖动滚动
  isDragging = true
  lastMouseY = e.clientY
}

function handleMouseMove(e: MouseEvent) {
  if (!isDragging) return

  const delta = lastMouseY - e.clientY
  const maxScroll = Math.max(0, stocks.length * ROW_HEIGHT - containerHeight + HEADER_HEIGHT)
  scrollTop = Math.max(0, Math.min(scrollTop + delta, maxScroll))
  lastMouseY = e.clientY
  render()
}

function handleMouseUp() {
  isDragging = false
}

// ========== 事件监听 ==========
function setupEventListeners() {
  // 监听数据更新
  const unsub = dataLayer.subscribe('merged.stocks', () => {
    console.log('[CanvasTable] data updated')
    loadData()
    render()
  })

  EventManager.on('dragon:lifecycle-updated', () => {
    updateLifecycleCache()
    render()
  })

  EventManager.on('dragon:confirmed', () => {
    updateLifecycleCache()
    render()
  })
}

// ========== Resize Observer ==========
let resizeObserver: ResizeObserver
function setupResizeObserver() {
  resizeObserver = new ResizeObserver(() => {
    calculateColumnPositions()
    render()
  })
  resizeObserver.observe(containerRef.value!)
}
</script>

<style scoped>
.canvas-table-container {
  width: 100%;
  height: 100%;
  overflow: hidden;
  background: #1a1a1a;
  cursor: default;
}

canvas {
  display: block;
  width: 100%;
  height: 100%;
}
</style>
