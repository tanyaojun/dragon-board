<!-- src/components/common/DataTable.vue -->

<template>
  <div class="data-table-container">
    <!-- ✅ 增强的加载状态 -->
    <div v-if="isLoading && !sortedStocks.length" class="loading-state">
      <div class="loading-content">
        <span class="loading-icon">🐉</span>
        <span class="loading-text">{{ loadingMessage }}</span>
        <div class="loading-progress" v-if="loadingProgress > 0">
          <div class="progress-bar" :style="{ width: loadingProgress + '%' }"></div>
          <span class="progress-text">{{ loadingProgress }}%</span>
        </div>
      </div>
    </div>

    <!-- 骨架屏（可选，当有旧数据时显示）-->
    <div v-else-if="isLoading && sortedStocks.length" class="skeleton-overlay">
      <div class="skeleton-loading">
        <span class="loading-icon">🔄</span>
        <span>更新中...</span>
        <div class="loading-progress small" v-if="loadingProgress > 0">
          <div class="progress-bar" :style="{ width: loadingProgress + '%' }"></div>
        </div>
      </div>
    </div>

    <!-- 有数据才显示表格 -->
    <template v-else-if="sortedStocks.length">
      <!-- 表格头部 - 使用 grid 布局，固定列宽 -->
      <div class="table-header" ref="headerRef" :style="{ width: totalWidth + 'px' }">
        <!-- 分组表头 -->
        <div v-if="hasGroups" class="header-group-row" :style="gridTemplateStyle">
          <div v-for="group in visibleGroups" :key="group" class="header-group-cell"
            :style="{ gridColumn: `span ${getGroupColspan(group)}` }">
            {{ getGroupLabel(group) }}
          </div>
        </div>

        <!-- 列表头 -->
        <div class="header-row" :style="gridTemplateStyle">
          <div v-for="col in visibleColumns" :key="col.key" class="header-cell"
            :class="{ sorted: uiStore.sort.field === col.key }" @click="uiStore.toggleSort(col.key as any)">
            <template v-if="col.key === 'rankChange'">
              变化%
            </template>
            <template v-else>
              {{ col.label }}
            </template>
            <span v-if="uiStore.sort.field === col.key" class="sort-icon">
              {{ uiStore.sort.order === 'asc' ? '↑' : '↓' }}
            </span>
          </div>
        </div>
      </div>

      <!-- 表格主体 - 使用 grid 布局，和数据头完全一致 -->
      <div class="table-body" ref="bodyRef" @scroll="handleBodyScroll">
        <div v-for="(stock, index) in sortedStocks" :key="stock.code" :data-code="stock.code" class="data-row" :class="[
          index % 2 === 0 ? 'row-even' : 'row-odd',
          { selected: uiStore.selectedCode === stock.code },
        ]" :title="getRowTitle(stock)" :style="gridTemplateStyle" @click="onRowClick($event, stock.code)"
          @contextmenu.prevent="showContextMenu($event, stock)">

          <!-- 动态渲染所有列，保持和表头一致 -->
          <div v-for="col in visibleColumns" :key="col.key" class="cell" :class="getCellClass(col.key, stock)"
            :data-key="col.key">
            <!-- 题材列 -->
            <template v-if="col.key === 'themes'">
              <div class="themes-cell">
                <span v-if="stock.themes && stock.themes.length > 0" class="themes-badge"
                  :class="getThemeBadgeClass(stock.themes)" :style="getThemeStyle(stock.themes[0]?.name || '')"
                  :title="getThemesTitle(stock.themes)">
                  {{ getThemeDisplay(stock.themes) }}
                </span>
                <span v-else class="themes-empty">-</span>
              </div>
            </template>

            <!-- 平台排名列的特殊渲染-->
            <template v-else-if="isPlatformRankKey(col.key)">
              <span :class="[
                stock[col.key] >= 4 && stock[col.key] <= 10 ? 'rank-4-10' : '',
                getPlatformRankClass(stock[col.key])
              ]">
                {{ formatPlatformRank(stock[col.key]) }}
              </span>
            </template>

            <!-- 变化列 - 显示百分位变化 -->
            <template v-else-if="col.key === 'rankChange'">
              <div class="rank-change-cell">
                <span v-if="stock.rankChange !== undefined && stock.rankChange !== 0"
                  :class="stock.rankChange > 0 ? 'rank-up' : 'rank-down'">
                  {{ stock.rankChange > 0 ? '↑' : '↓' }}{{ Math.abs(Math.round(stock.rankChange)) }}%
                </span>
                <span v-else class="trend-steady">-</span>
              </div>
            </template>

            <!-- 置信度列 - 增强显示 -->
            <template v-else-if="col.key === 'confidence'">
              <div class="confidence-cell" :title="getConfidenceTitle(stock)">
                <!-- 买入信号 -->
                <div v-if="stock.finalSignal === 'buy'" class="signal-badge buy-badge">
                  <span class="signal-percent">{{ Math.round(stock.finalConfidence || 0) }}%</span>
                  <!-- ✅ 只在收盘前显示金叉死叉标记 -->
                  <span v-if="shouldShowMacdSignal(stock) && stock.macdCross === 'golden'" class="macd-badge golden"
                    title="MACD金叉">🔱</span>
                  <span v-if="shouldShowMacdSignal(stock) && stock.macdCross === 'death'" class="macd-badge death"
                    title="MACD死叉">💀</span>
                </div>
                <!-- 卖出信号 -->
                <div v-else-if="stock.finalSignal === 'sell'" class="signal-badge sell-badge">
                  <span class="signal-percent">{{ Math.round(stock.finalConfidence || 0) }}%</span>
                  <!-- ✅ 只在收盘前显示金叉死叉标记 -->
                  <span v-if="shouldShowMacdSignal(stock) && stock.macdCross === 'golden'" class="macd-badge golden"
                    title="MACD金叉">🔱</span>
                  <span v-if="shouldShowMacdSignal(stock) && stock.macdCross === 'death'" class="macd-badge death"
                    title="MACD死叉">💀</span>
                </div>
                <!-- 持有信号 -->
                <div v-else-if="stock.finalSignal === 'hold'" class="signal-badge hold-badge">
                  <span class="signal-percent">{{ Math.round(stock.finalConfidence || 0) }}%</span>
                  <!-- ✅ 只在收盘前显示金叉死叉标记 -->
                  <span v-if="shouldShowMacdSignal(stock) && stock.macdCross === 'golden'" class="macd-badge golden"
                    title="MACD金叉">🔱</span>
                  <span v-if="shouldShowMacdSignal(stock) && stock.macdCross === 'death'" class="macd-badge death"
                    title="MACD死叉">💀</span>
                </div>
                <span v-else class="trend-steady">-</span>
              </div>
            </template>

            <template v-else>
              {{ formatCell(col.key, stock) }}
            </template>


          </div>
        </div>
      </div>
    </template>

    <!-- 空状态 -->
    <div v-else-if="!loading" class="empty-state">
      <span class="empty-icon">📭</span>
      <span>暂无数据</span>
    </div>

    <!-- 右键菜单 -->
    <div v-if="contextMenu.visible" class="context-menu"
      :style="{ left: contextMenu.x + 'px', top: contextMenu.y + 'px' }" ref="contextMenuRef">
      <div class="menu-item" @click="addToFavorite"><span class="menu-icon">⭐</span> 加入自选</div>
      <div class="menu-divider"></div>
      <div class="menu-item" @mouseenter="showBoardMenu" @click.stop>
        <span class="menu-icon">📁</span> 加入板块
        <span class="submenu-indicator">▶</span>
        <div v-if="showBoardSubMenu" class="submenu">
          <div v-if="boardList.length === 0" class="submenu-item disabled">暂无板块</div>
          <div v-for="board in boardList" :key="board.id" class="submenu-item" @click="addToSpecificBoard(board.id)">
            <span class="board-color-dot" :style="{ backgroundColor: board.color }"></span>
            {{ board.name }}
            <span class="board-count">{{ board.count }}</span>
          </div>
          <div class="submenu-divider"></div>
          <div class="submenu-item" @click="createNewBoard">
            <span class="menu-icon">+</span> 新建板块
          </div>
        </div>
      </div>
      <div class="menu-item" @click="copyCode"><span class="menu-icon">📋</span> 复制代码</div>
      <div class="menu-divider"></div>
      <div class="menu-item" @click="viewTheme"><span class="menu-icon">📊</span> 查看题材</div>
      <div class="menu-item" @click="viewDetails"><span class="menu-icon">🔍</span> 查看详情</div>
      <div class="menu-item" @click="openRankTrendForStock">
        <span class="menu-icon">📊</span> 六维信号分析
      </div>
    </div>
    <!-- 六维信号分析面板 -->
    <RankTrendPanel :visible="rankTrendPanelVisible" :triggerRect="rankTrendPanelTriggerRect"
      @update:visible="rankTrendPanelVisible = $event" @close="rankTrendPanelVisible = false" />
  </div>

</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { storeToRefs } from 'pinia'
import type { Stock, Board } from '../../types'
import { EventManager } from '../../utils/eventManager'
import { AppEvents } from '../../types'
import { useUIStore } from '../../stores/ui'
import { useFavoriteStore } from '../../stores/favorite'
import { dataLayer } from '../../services/DataLayer'
import { dataLoader } from '../../services/dataLoader'
import RankTrendPanel from '../../components/panels/RankTrendPanel.vue'
import { rankTrendAnalyzer } from '../../services/RankTrendAnalyzer'
import { isTradingTime } from '../../utils/time'
const props = defineProps<{
  loading?: boolean
}>()

// ========== Stores ==========
const uiStore = useUIStore()
const favoriteStore = useFavoriteStore()
const { sortedStocks } = storeToRefs(uiStore)

// ========== 加载状态 ==========
const isLoading = computed(() => {
  return props.loading !== undefined ? props.loading : dataLoader.isLoading?.value?.active || false
})

const loadingProgress = computed(() => {
  return dataLoader.isLoading?.value?.progress || 0
})

const loadingMessage = computed(() => {
  return dataLoader.isLoading?.value?.message || '加载数据中...'
})

// ========== 状态 ==========
const headerRef = ref<HTMLElement | null>(null)
const bodyRef = ref<HTMLElement | null>(null)

// 右键菜单
const contextMenu = ref({
  visible: false,
  x: 0,
  y: 0,
  stock: null as Stock | null,
})
const contextMenuRef = ref<HTMLElement | null>(null)

// 板块列表状态
const boardList = ref<Board[]>([])
const showBoardSubMenu = ref(false)

// ========== 列配置（保持不变）==========
const columns = [
  { key: 'code', label: '代码', group: 'basic', always: true },
  { key: 'name', label: '名称', group: 'basic', always: true },
  { key: 'themes', label: '题材', group: 'basic', always: true },
  { key: 'price', label: '最新价', group: 'basic', always: true },
  { key: 'change', label: '涨幅%', group: 'basic', always: true },
  { key: 'emRank', label: '东财', group: 'platform', always: true },
  { key: 'thsRank', label: '同花顺', group: 'platform', always: true },
  { key: 'kplRank', label: '开盘啦', group: 'platform', always: true },
  { key: 'tdxRank', label: '通达信', group: 'platform', always: true },
  { key: 'xqRank', label: '雪球', group: 'platform', always: true },
  { key: 'clsRank', label: '财联社', group: 'platform', always: true },
  { key: 'tgbRank', label: '淘股吧', group: 'platform', always: true },
  { key: 'dzhRank', label: '大智慧', group: 'platform', always: true },
  { key: 'avgRank', label: '热度', group: 'comprehensive', always: true },
  { key: 'compRank', label: '综合', group: 'comprehensive', always: true },
  { key: 'rankChange', label: '变化', group: 'comprehensive', always: true },
  { key: 'confidence', label: '置信度', group: 'comprehensive', always: true },
  { key: 'zlje', label: '主力净额', group: 'money', always: true },
  { key: 'zljzb', label: '主力%', group: 'money', always: true },
  { key: 'cddje', label: '超大单', group: 'money', always: true },
  { key: 'cddjzb', label: '超大%', group: 'money', always: true },
  { key: 'volume', label: '成交量', group: 'quote', always: true },
  { key: 'volumeRatio', label: '量比', group: 'quote', always: true },
  { key: 'turnover', label: '成交额', group: 'quote', always: true },
  { key: 'turnoverRate', label: '换手%', group: 'quote', always: true },
  { key: 'cirMV', label: '流通值', group: 'quote', always: true },
  { key: 'pe', label: '市盈率', group: 'quote', always: true },
  { key: 'totalMV', label: '总市值', group: 'quote', always: true },
  { key: 'pb', label: '市净率', group: 'quote', always: true },
]

// ========== 列宽映射==========
const COLUMN_WIDTHS: Record<string, string> = {
  code: '70px',
  name: '90px',
  themes: '140px',
  price: '70px',
  change: '70px',
  emRank: '50px',
  thsRank: '50px',
  kplRank: '50px',
  tdxRank: '50px',
  xqRank: '50px',
  clsRank: '50px',
  tgbRank: '50px',
  dzhRank: '50px',
  avgRank: '50px',
  compRank: '50px',
  rankChange: '50px',
  confidence: '70px',
  zlje: '90px',
  zljzb: '90px',
  cddje: '90px',
  cddjzb: '90px',
  volume: '80px',
  volumeRatio: '70px',        // ✅ 新增量比列宽
  turnover: '80px',
  turnoverRate: '80px',
  cirMV: '80px',
  pe: '80px',
  totalMV: '80px',
  pb: '80px',
}

// ========== 计算属性==========
const visibleColumns = computed(() => columns.filter(col => col.always))
const visibleGroups = computed(() => {
  const groups = new Set<string>()
  visibleColumns.value.forEach(col => groups.add(col.group))
  return Array.from(groups)
})
const hasGroups = computed(() => visibleGroups.value.length > 0)
const totalWidth = computed(() => {
  return visibleColumns.value.reduce((sum, col) => {
    const widthStr = COLUMN_WIDTHS[col.key] || '70px'
    const width = parseInt(widthStr)
    return sum + width
  }, 20)
})
const gridTemplateStyle = computed(() => {
  const widths = visibleColumns.value.map(col => COLUMN_WIDTHS[col.key] || '70px')
  return {
    display: 'grid',
    gridTemplateColumns: widths.join(' '),
    width: 'fit-content',
  }
})

// ========== 从 dataLayer 获取数据的计算属性 ==========

// 所有股票数据
const allStocks = computed(() => dataLayer.getStocks())

// 题材信息
const themesInfoMap = computed(() => {
  const map = new Map()
  allStocks.value.forEach((stock: any) => {
    const themes: any[] = []

    // 获取题材数据
    const themeData = dataLayer.getStockThemes?.(stock.code)
    if (themeData?.length) {
      themes.push(...themeData)
    }

    // 获取标签数据
    const tags = dataLayer.getStockTags?.(stock.code)
    if (tags?.length) {
      tags.forEach((tag: { Name: string }) => {
        themes.push({
          id: `tag_${tag.Name}`,
          name: tag.Name,
          type: 'tag',
          heatScore: 0
        })
      })
    }

    // 去重
    const uniqueThemes = removeDuplicateThemes(themes)
    map.set(stock.code, uniqueThemes)
  })
  return map
})


const viewTheme = () => {
  if (contextMenu.value.stock) {
    const themes = getStockThemes(contextMenu.value.stock)
    if (themes && themes.length > 0) {
      const firstTheme = themes[0]
      const themeName = typeof firstTheme === 'string' ? firstTheme : firstTheme.name
      // ✅ 保留事件发射
      EventManager.emit('sector:show-detail', {
        themeName: themeName,
      })
    } else {
      EventManager.emit(AppEvents.UI.TOAST, {
        message: `📊 ${contextMenu.value.stock.name} 暂无题材数据`,
        duration: 1500,
        type: 'info',
      })
    }
  }
  hideContextMenu()
}

const getStockThemes = (stock: Stock) => {
  return themesInfoMap.value.get(stock.code) || []
}

const getThemeDisplay = (themes: any[]) => {
  if (!themes || themes.length === 0) return '-'

  const normalThemes = themes.filter(t => t.type !== 'tag')
  const tags = themes.filter(t => t.type === 'tag')

  if (normalThemes.length > 0) {
    const firstTheme = normalThemes[0]
    const themeName = firstTheme.name || firstTheme
    const extraCount = normalThemes.length - 1 + tags.length
    return extraCount > 0 ? `${themeName} +${extraCount}` : themeName
  }

  if (tags.length === 1) return `🏷️ ${tags[0].Name}`
  if (tags.length > 1) return `🏷️ ${tags[0].Name} +${tags.length - 1}`
  return '-'
}

const getThemesTitle = (themes: any[]) => {
  if (!themes || themes.length === 0) return ''
  return themes.map(t => {
    if (t.type === 'tag') return `🏷️ ${t.Name}`
    return t.name || t
  }).filter(Boolean).join(' · ')
}

const stringToColor = (str: string) => {
  if (!str) return { bg: 'rgba(107, 114, 128, 0.15)', border: '#6b7280', text: '#9ca3af' }

  let hash = 0
  for (let i = 0; i < str.length; i++) {
    hash = str.charCodeAt(i) + ((hash << 5) - hash)
  }

  const h = Math.abs(hash % 360)
  const s = 60 + (Math.abs(hash >> 4) % 20)
  const l = 65 + (Math.abs(hash >> 8) % 10)

  return {
    bg: `hsla(${h}, ${s}%, ${l}%, 0.15)`,
    border: `hsl(${h}, ${s}%, ${l}%)`,
    text: `hsl(${h}, ${s}%, ${l}%)`,
  }
}

const getThemeStyle = (stock: any) => {
  const themes = getStockThemes(stock)
  if (!themes || themes.length === 0) return {}

  const normalTheme = themes.find((t: any) => t.type !== 'tag')
  if (normalTheme) {
    const themeName = typeof normalTheme === 'string' ? normalTheme : normalTheme.name || ''
    return stringToColor(themeName)
  }

  return {
    bg: 'rgba(156, 39, 176, 0.15)',
    border: '#9c27b0',
    text: '#9c27b0'
  }
}

const getThemeBadgeClass = (themes: any[]) => {
  if (!themes || themes.length === 0) return ''

  const normalThemes = themes.filter(t => t.type !== 'tag')
  const tags = themes.filter(t => t.type === 'tag')

  if (tags.length > 0 && normalThemes.length === 0) return 'theme-tag-only'
  if (themes.length >= 3) return 'theme-multiple'
  if (themes.length === 2) return 'theme-double'
  return 'theme-single'
}

const removeDuplicateThemes = (themes: any[]): any[] => {
  if (!themes || !Array.isArray(themes)) return []

  const themeMap = new Map()
  const tagMap = new Map()

  themes.forEach(theme => {
    if (!theme) return

    if (theme.type === 'tag') {
      const tagName = theme.Name || theme.name
      if (tagName && !tagMap.has(tagName)) {
        tagMap.set(tagName, theme)
      }
      return
    }

    let id: string
    if (typeof theme === 'string') {
      id = theme
    } else {
      id = theme.id || theme.name || JSON.stringify(theme)
    }
    if (!id) return

    if (themeMap.has(id)) {
      const existing = themeMap.get(id)
      if (typeof existing === 'string' && typeof theme === 'object') {
        themeMap.set(id, theme)
      } else if (typeof existing === 'object' && typeof theme === 'object') {
        themeMap.set(id, { ...existing, ...theme })
      }
    } else {
      themeMap.set(id, theme)
    }
  })

  return [...Array.from(themeMap.values()), ...Array.from(tagMap.values())]
}

// 行悬浮提示
const getRowTitle = (stock: Stock) => {
  let title = ''
  let hasContent = false

  title += `${stock.name} (${stock.code})`
  hasContent = true

  // ✅ 直接从 limitUpData 读取标签、原因、连板信息
  const limitUpData = dataLayer.getLimitUpData(stock.code)

  // 标签
  if (limitUpData?.tags && limitUpData.tags.length > 0) {
    const tagNames = limitUpData.tags.map((tag: any) => tag.Name || tag).filter(Boolean)
    if (tagNames.length > 0) {
      title += `\n🏷️ 标签: ${tagNames.join('/')}\n`
    }
  }

  // 关联原因
  if (limitUpData?.reason) {
    title += `\n📋 关联原因:\n`
    let reason = limitUpData.reason
    const sentences = reason.split(/([。；！？])/g)
    const paragraphs: string[] = []
    for (let i = 0; i < sentences.length; i += 2) {
      const sentence = (sentences[i] || '') + (sentences[i + 1] || '')
      if (sentence.trim()) {
        paragraphs.push(sentence.trim())
      }
    }
    paragraphs.slice(0, 5).forEach((para, idx) => {
      const displayPara = para.length > 60 ? para.slice(0, 60) + '...' : para
      title += `   ${idx + 1}. ${displayPara}\n`
    })
    if (paragraphs.length > 5) {
      title += `   ... 共 ${paragraphs.length} 条\n`
    }
  }

  // 连板信息
  const lianbanStr = limitUpData?.lianbanStr || stock.lianbanStr
  if (lianbanStr) {
    title += `\n📈 连板: ${lianbanStr}\n`
  }

  // 排名变化
  if (stock.rankChange !== undefined && stock.rankChange !== 0) {
    const change = Math.abs(Math.round(stock.rankChange))
    title += `\n📊 排名变化: ${stock.rankChange > 0 ? '↑' : '↓'}${change}%\n`
  }

  return title
}


// 置信度悬浮提示
const getConfidenceTitle = (stock: any) => {
  let title = ''

  if (!stock.finalSignal || stock.finalSignal === 'none') return '暂无信号'

  const confidence = Math.round(stock.finalConfidence || 0)
  const signalText = stock.finalSignal === 'buy' ? '买入' : stock.finalSignal === 'sell' ? '卖出' : '持有'
  title = `🎯 综合判断: ${signalText} (置信度: ${confidence}%)\n`
  title += '─'.repeat(30) + '\n'

  // 排名变化
  if (stock.rankChange !== undefined && stock.rankChange !== 0) {
    const change = Math.abs(Math.round(stock.rankChange))
    title += `📊 排名变化: ${stock.rankChange > 0 ? '↑' : '↓'}${change}%\n`
  }

  // MACD
  title += `📈 MACD: ${stock.macdCross === 'golden' ? '金叉 ✅' : stock.macdCross === 'death' ? '死叉' : '无交叉'}\n\n`

  // 3个排名趋势信号
  title += `📊 排名趋势信号:\n`

  const directionText = stock.directionSignal === 'buy' ? '买入' : stock.directionSignal === 'sell' ? '卖出' : '持有'
  title += `   📈 方向一致性: ${directionText} (${stock.directionConfidence || 0}%)\n`

  const accelerationText = stock.accelerationSignal === 'buy' ? '买入' : stock.accelerationSignal === 'sell' ? '卖出' : '持有'
  title += `   ⚡ 动量加速度: ${accelerationText} (${stock.accelerationConfidence || 0}%)\n`

  const crossText = stock.crossSignal === 'buy' ? '买入' : stock.crossSignal === 'sell' ? '卖出' : '持有'
  title += `   🔄 零线交叉: ${crossText} (${stock.crossConfidence || 0}%)\n`

  // MACD详细
  if (stock.macd !== undefined) {
    title += `\n📈 MACD详细: DIF=${stock.macd.toFixed(2)}  DEA=${stock.macdSignal?.toFixed(2)}  柱=${stock.macdHistogram?.toFixed(2)}`
  }

  return title
}

// 判断是否显示金叉死叉标记（非交易时间）
const shouldShowMacdSignal = (stock: any) => {

  //交易时间不显示
  if (isTradingTime()) {
    return
  }

  // 显示金叉死叉标记
  return stock.macdCross === 'golden' || stock.macdCross === 'death'
}

// ========== 格式化函数（保持不变）==========
const formatMoney = (value: number): string => {
  if (!value && value !== 0) return '-'
  const absValue = Math.abs(value)
  if (absValue >= 1e8) return (value / 1e8).toFixed(2) + '亿'
  if (absValue >= 1e4) return (value / 1e4).toFixed(2) + '万'
  return value.toString()
}

const formatVolume = (volume: number): string => {
  if (!volume && volume !== 0) return '-'
  const absVolume = Math.abs(volume)
  if (absVolume >= 1e8) return (volume / 1e8).toFixed(2) + '亿手'
  if (absVolume >= 1e4) return (volume / 1e4).toFixed(2) + '万手'
  return volume.toString() + '手'
}

const formatCell = (key: string, stock: any) => {
  const value = stock[key]
  if (value === undefined || value === null) return '-'

  if (key.includes('Rank') || key === 'compRank') {
    return value === 999 ? '-' : value
  }

  if (key.includes('Rate') || key === 'change' || key.includes('zb')) {
    return value ? (value > 0 ? '+' : '') + Number(value).toFixed(2) + '%' : '-'
  }

  // ✅ 量比格式化：保留两位小数
  if (key === 'volumeRatio') {
    return value ? Number(value).toFixed(2) : '-'
  }

  if (['zlje', 'cddje', 'turnover', 'cirMV', 'totalMV'].includes(key)) {
    return formatMoney(value)
  }

  if (key === 'volume') return formatVolume(value)
  if (key === 'pb') return value ? Number(value).toFixed(2) : '-'
  if (key === 'themes') return Array.isArray(value) ? value.join(', ') || '-' : value || '-'

  return value ?? '-'
}

// ========== 样式类（保持不变==========
const getCellClass = (key: string, stock: any) => {
  const classes = ['cell']

  if (key === 'code') classes.push('code-cell')
  else if (key === 'name') classes.push('name-cell')
  else if (key === 'themes') classes.push('sector-cell')
  else classes.push('number-cell')

  if (key === 'change') {
    const change = stock.change
    if (change > 0) classes.push('color-up')
    else if (change < 0) classes.push('color-down')
  }

  // ✅ 量比颜色样式：大于1.2显示暖色，小于0.8显示冷色
  if (key === 'volumeRatio') {
    const ratio = stock.volumeRatio
    if (ratio && ratio > 1.2) classes.push('volume-ratio-high')
    else if (ratio && ratio < 0.8) classes.push('volume-ratio-low')
  }

  if (key === 'zlje' || key === 'cddje') {
    const value = stock[key]
    if (value > 0) classes.push('money-positive')
    else if (value < 0) classes.push('money-negative')
  }

  if (key === 'compRank' || key === 'avgRank') classes.push('color-highlight')

  if (key === 'rankChange') {
    const change = stock[key]
    if (change > 0) classes.push('rank-up')
    else if (change < 0) classes.push('rank-down')
  }

  return classes.join(' ')
}

const getGroupLabel = (group: string) => {
  const labels: Record<string, string> = {
    basic: '📋 基本信息',
    platform: '📊 热榜排名',
    comprehensive: '🎯 综合',
    money: '💰 资金流向',
    quote: '🔴 行情数据',
  }
  return labels[group] || group
}

// ========== 八平台排名格式化 ==========
const formatPlatformRank = (rank: number): string => {
  if (!rank || rank >= 999) return '-'
  if (rank === 1) return '🥇1'
  if (rank === 2) return '🥈2'
  if (rank === 3) return '🥉3'
  return rank.toString()
}
const getPlatformRankClass = (rank: number): string => {
  if (!rank || rank >= 999) return ''
  if (rank === 1) return 'platform-1st'
  if (rank === 2) return 'platform-2nd'
  if (rank === 3) return 'platform-3rd'
  return ''
}

// 判断是否是平台排名列
const isPlatformRankKey = (key: string): boolean => {
  return ['emRank', 'thsRank', 'kplRank', 'tdxRank', 'xqRank', 'clsRank', 'tgbRank', 'dzhRank'].includes(key)
}

// 信号面板状态
const rankTrendPanelVisible = ref(false)
const rankTrendPanelTriggerRect = ref<DOMRect>()

const openRankTrendForStock = () => {
  // ✅ 添加类型守卫，确保 stock 存在
  if (!contextMenu.value.stock) {
    console.warn('[DataTable] 没有选中的股票，无法打开六维信号分析')
    hideContextMenu()
    return
  }

  const stock = contextMenu.value.stock

  rankTrendPanelVisible.value = true

  setTimeout(() => {
    const panel = document.querySelector('.rank-trend-panel')
    if (!panel) {
      console.warn('[DataTable] 未找到六维信号分析面板')
      return
    }

    const searchInput = panel.querySelector('.search-input') as HTMLInputElement
    if (searchInput) {
      searchInput.value = stock.code
      const inputEvent = new Event('input', { bubbles: true })
      searchInput.dispatchEvent(inputEvent)

      const searchBtn = panel.querySelector('.search-btn') as HTMLButtonElement
      if (searchBtn) {
        searchBtn.click()
      }
    }
  }, 100)

  hideContextMenu()
}

const getGroupColspan = (group: string) => {
  return visibleColumns.value.filter(col => col.group === group).length
}

// ========== 右键菜单 ==========
const onRowClick = (event: MouseEvent, code: string) => {
  const target = event.target as HTMLElement
  if (target.closest('.sector-tag') || target.closest('.sector-tags')) {
    return
  }
  uiStore.selectStock(code)
}

const showContextMenu = (e: MouseEvent, stock: Stock) => {
  contextMenu.value = {
    visible: true,
    x: e.clientX,
    y: e.clientY,
    stock: { ...stock },
  }
}

const hideContextMenu = () => {
  contextMenu.value.visible = false
  showBoardSubMenu.value = false
}

const loadBoardList = () => {
  boardList.value = favoriteStore.boardList
}

const showBoardMenu = () => {
  loadBoardList()
  showBoardSubMenu.value = true
}

const addToSpecificBoard = (boardId: string) => {
  if (contextMenu.value.stock) {
    favoriteStore.addStockToBoard(contextMenu.value.stock.code, boardId)
  }
  hideContextMenu()
}

const createNewBoard = () => {
  if (contextMenu.value.stock) {
    const boardName = prompt('请输入新板块名称：')
    if (boardName && boardName.trim()) {
      const board = favoriteStore.addBoard(boardName.trim())
      if (board) {
        favoriteStore.addStockToBoard(contextMenu.value.stock.code, board.id)
      }
    }
  }
  hideContextMenu()
}

const addToFavorite = () => {
  if (contextMenu.value.stock) {
    favoriteStore.toggleFavorite(contextMenu.value.stock.code, '默认')
  }
  hideContextMenu()
}

const copyCode = () => {
  if (contextMenu.value.stock) {
    navigator.clipboard?.writeText(contextMenu.value.stock.code).then(() => {
      // ✅ 保留事件发射
      EventManager.emit(AppEvents.UI.TOAST, {
        message: `📋 已复制 ${contextMenu.value.stock?.code}`,
        duration: 1500,
        type: 'success',
      })
    })
  }
  hideContextMenu()
}

const viewDetails = () => {
  if (contextMenu.value.stock) {
    // ✅ 保留事件发射
    EventManager.emit(AppEvents.UI.TOAST, {
      message: `🔍 查看 ${contextMenu.value.stock.name} 详情`,
      duration: 1500,
      type: 'info',
    })
  }
  hideContextMenu()
}

// ========== 事件处理 ==========
const handleBodyScroll = (e: Event) => {
  if (headerRef.value) {
    headerRef.value.scrollLeft = (e.target as HTMLElement).scrollLeft
  }
  uiStore.saveScrollPosition((e.target as HTMLElement).scrollTop)
}

const handleClickOutside = (e: MouseEvent) => {
  if (contextMenuRef.value && !contextMenuRef.value.contains(e.target as Node)) {
    hideContextMenu()
  }
}

// ========== 生命周期 ==========
// 添加一个响应式变量
const currentTime = ref(new Date())

// 标志，避免重复触发信号更新
let hasTriggeredSignalUpdate = false

// 启动定时器
let timeTimer: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  document.addEventListener('click', handleClickOutside)

  // 恢复滚动位置
  if (bodyRef.value && uiStore.scrollPosition) {
    bodyRef.value.scrollTop = uiStore.scrollPosition
  }

  // 每秒更新时间，触发界面重新渲染
  timeTimer = setInterval(() => {
    const now = new Date()
    currentTime.value = now

    const hour = now.getHours()
    const minute = now.getMinutes()

    // 14:45 时触发信号刷新
    if (hour === 14 && minute === 45 && !hasTriggeredSignalUpdate) {
      hasTriggeredSignalUpdate = true
      console.log('[DataTable] 14:45 触发信号刷新')

      const stocks = dataLayer.getStocks()
      const rankMap = new Map()
      stocks.forEach((s, i) => rankMap.set(s.code, i + 1))
      rankTrendAnalyzer.getRankTrends(rankMap).catch(console.error)
    }

    // 第二天重置标志（9:00）
    if (hour === 9 && minute === 0) {
      hasTriggeredSignalUpdate = false
    }
  }, 1000)
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)

  if (timeTimer) {
    clearInterval(timeTimer)
    timeTimer = null
  }
})

// 监听 sortedStocks 变化，更新滚动位置（可选）
watch(sortedStocks, () => {
  // 可以在这里处理数据变化后的逻辑
})

defineExpose({
  refreshTable: () => { } // 空函数，保留接口
})
</script>

<style scoped>
.toolbar {
  padding: 8px 16px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-secondary);
  display: flex;
  gap: 12px;
}

.rank-trend-btn {
  padding: 6px 12px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  color: var(--text-primary);
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  gap: 4px;
}

.rank-trend-btn:hover {
  background: var(--bg-hover);
  border-color: var(--color-highlight);
  color: var(--color-highlight);
}

.loading-state {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  padding: 30px;
  background: var(--bg-secondary);
  border-radius: 16px;
  box-shadow: var(--shadow-md);
  min-width: 200px;
  z-index: 10;
}

.loading-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
}

.loading-icon {
  font-size: 48px;
  animation: spin 1s linear infinite;
}

.loading-text {
  font-size: 14px;
  color: var(--text-secondary);
}

.loading-progress {
  width: 180px;
  height: 4px;
  background: var(--border-color);
  border-radius: 2px;
  overflow: hidden;
  position: relative;
}

.progress-bar {
  height: 100%;
  background: var(--color-highlight);
  border-radius: 2px;
  transition: width 0.3s ease;
}

.progress-text {
  position: absolute;
  right: 0;
  top: -18px;
  font-size: 10px;
  color: var(--text-secondary);
}

/* 骨架屏覆盖层 */
.skeleton-overlay {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.3);
  backdrop-filter: blur(2px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 5;
  pointer-events: none;
}

.skeleton-loading {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 20px;
  background: var(--bg-primary);
  border-radius: 24px;
  box-shadow: var(--shadow-md);
  font-size: 13px;
  color: var(--text-secondary);
}

.loading-progress.small {
  width: 80px;
  height: 3px;
}

.loading-progress.small .progress-text {
  display: none;
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }

  to {
    transform: rotate(360deg);
  }
}

.data-table-container {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--bg-primary);
  position: relative;
  overflow-x: auto;
  overflow-y: hidden;
  width: 100%;
}

/* 表头区域 */
.table-header {
  overflow-x: auto;
  overflow-y: visible;
  border-bottom: 2px solid var(--border-color);
  background: var(--bg-header);
  flex-shrink: 0;
  width: 100%;
  position: sticky;
  top: 0;
  z-index: 10;
}

.table-header::-webkit-scrollbar {
  height: 0;
  width: 0;
}

/* 确保表头和表体内容对齐 */
.table-header,
.table-body {
  width: 100%;
  overflow-x: auto;
  overflow-y: hidden;
}

.table-body {
  overflow-y: auto;
}

.data-row {
  box-sizing: border-box;
}

.cell {
  box-sizing: border-box;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 表体区域 */
.table-body {
  flex: 1;
  overflow: auto;
  width: 100%;
}

/* 分组表头行 */
.header-group-row {
  display: grid;
  background: var(--bg-secondary);
  border-bottom: 2px solid var(--border-color);
}

.header-group-cell {
  padding: 10px 8px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-title);
  text-align: center;
  letter-spacing: 0.5px;
  text-transform: uppercase;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 列表头行 */
.header-row {
  display: grid;
  background: var(--bg-header);
  overflow: visible;
}

.header-cell {
  padding: 14px 8px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  white-space: nowrap;
  cursor: pointer;
  user-select: none;
  text-align: center;
  border-bottom: 2px solid var(--border-color);
  transition: all 0.2s ease;
  letter-spacing: 0.3px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  position: relative;
  overflow: visible;
}

.header-cell:hover {
  color: var(--color-highlight);
  background: var(--bg-hover);
}

.header-cell.sorted {
  color: var(--color-highlight);
}

.sort-icon {
  font-size: 10px;
  opacity: 0.8;
}

/* 数据行 */
.data-row {
  display: grid;
  border-bottom: 1px solid var(--border-color);
  height: 48px;
  min-height: 48px;
  align-items: center;
  width: 100%;
  min-width: fit-content;
}

.data-row:hover {
  background: var(--bg-hover);
}

.data-row.selected {
  background: rgba(255, 165, 2, 0.15) !important;
  position: relative;
  z-index: 2;
}

.data-row.selected::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  background: var(--color-highlight) !important;
  box-shadow: 0 0 8px var(--color-highlight) !important;
  z-index: 3;
}

.data-row.selected:hover {
  background: rgba(255, 165, 2, 0.2) !important;
}

/* 奇偶行交替背景 */
.data-row.row-even {
  background: transparent;
}

.data-row.row-odd {
  background: rgba(0, 0, 0, 0.02);
}

/* 单元格通用样式 */
.cell {
  padding: 0 8px;
  font-size: 12px;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 48px;
  height: 48px;
}

/* 文字类单元格左对齐 */
.code-cell,
.name-cell,
.sector-cell {
  text-align: left;
  font-weight: 500;
}

/* 数字单元格右对齐 */
.number-cell {
  text-align: right;
  font-family: 'SF Mono', Monaco, Consolas, monospace;
}

/* 代码列特殊样式 */
.code-cell {
  font-family: 'SF Mono', Monaco, Consolas, monospace;
  font-size: 11px;
  color: var(--color-highlight);
}

/* 名称列特殊样式 */
.name-cell {
  font-weight: 500;
  color: var(--text-primary);
}

/* 题材列 */
.sector-cell {
  padding-left: 8px;
}


/* 涨跌颜色 */
.color-up {
  color: #ff4757 !important;
  font-weight: 600;
}

.color-down {
  color: #2ed573 !important;
  font-weight: 600;
}

.color-highlight {
  color: #ffa502 !important;
  font-weight: 700;
}

.money-positive {
  color: #ff4757 !important;
  font-weight: 600;
}

.money-negative {
  color: #2ed573 !important;
  font-weight: 600;
}

/* 排名变化单元格 */
.rank-change-cell {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  cursor: help;
}

/* 上升颜色 */
.rank-up {
  color: #ff4757 !important;
  font-weight: 600;
}

/* 下降颜色 */
.rank-down {
  color: #2ed573 !important;
  font-weight: 600;
}

/* 无变化 */
.trend-steady {
  color: var(--text-secondary);
}

/* 趋势强度标记 */
.trend-strength {
  font-size: 10px;
  color: #ffa502;
  margin-left: 2px;
}

/* 买入信号 - 红色系 */
.signal-buy {
  font-size: 11px;
  margin-left: 4px;
  padding: 0 6px;
  border-radius: 12px;
  font-weight: 500;
  border: 1px solid;
}

/* 高置信度买入 - 深红色 */
.signal-buy.confidence-high {
  background: rgba(255, 71, 87, 0.25);
  border-color: #ff4757;
  color: #ff4757;
  font-weight: 600;
}

/* 中置信度买入 - 红色 */
.signal-buy.confidence-mid {
  background: rgba(255, 71, 87, 0.15);
  border-color: rgba(255, 71, 87, 0.6);
  color: #ff6b6b;
}

/* 低置信度买入 - 浅红色 */
.signal-buy.confidence-low {
  background: rgba(255, 71, 87, 0.08);
  border-color: rgba(255, 71, 87, 0.3);
  color: #ff8a8a;
}

/* 卖出信号 - 绿色系 */
.signal-sell {
  font-size: 11px;
  margin-left: 4px;
  padding: 0 6px;
  border-radius: 12px;
  font-weight: 500;
  border: 1px solid;
}

/* 高置信度卖出 - 深绿色 */
.signal-sell.confidence-high {
  background: rgba(46, 213, 115, 0.25);
  border-color: #2ed573;
  color: #2ed573;
  font-weight: 600;
}

/* 中置信度卖出 - 绿色 */
.signal-sell.confidence-mid {
  background: rgba(46, 213, 115, 0.15);
  border-color: rgba(46, 213, 115, 0.6);
  color: #5ee08a;
}

/* 低置信度卖出 - 浅绿色 */
.signal-sell.confidence-low {
  background: rgba(46, 213, 115, 0.08);
  border-color: rgba(46, 213, 115, 0.3);
  color: #8ae8aa;
}

/* 右键菜单 */
.context-menu {
  position: fixed;
  width: 200px;
  background: var(--bg-panel);
  backdrop-filter: blur(10px);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  box-shadow: var(--shadow-lg);
  z-index: 10060;
  padding: 6px 0;
  font-size: 13px;
}

.menu-item {
  padding: 8px 16px;
  cursor: pointer;
  color: var(--text-primary);
  transition: all 0.2s;
  display: flex;
  align-items: center;
  gap: 10px;
}

.menu-item:hover {
  background: var(--bg-hover);
  color: var(--color-highlight);
}

.menu-divider {
  height: 1px;
  background: var(--border-color);
  margin: 6px 0;
}

.menu-icon {
  font-size: 16px;
  width: 20px;
  text-align: center;
}

/* 子菜单 */
.submenu {
  position: absolute;
  left: 100%;
  top: 0;
  min-width: 160px;
  background: var(--bg-panel);
  backdrop-filter: blur(10px);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  box-shadow: var(--shadow-lg);
  z-index: 10070;
  padding: 6px 0;
}

.submenu-item {
  padding: 6px 12px;
  cursor: pointer;
  color: var(--text-primary);
  font-size: 12px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.submenu-item:hover {
  background: var(--bg-hover);
  color: var(--color-highlight);
}

.submenu-item.disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.submenu-divider {
  height: 1px;
  background: var(--border-color);
  margin: 6px 0;
}

.board-color-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}

.board-count {
  margin-left: auto;
  font-size: 10px;
  padding: 2px 4px;
  background: var(--badge-bg);
  border-radius: 10px;
  color: var(--badge-text);
}

.submenu-indicator {
  margin-left: auto;
  font-size: 10px;
  opacity: 0.6;
}

/* 滚动条 */
.table-body::-webkit-scrollbar,
.table-header::-webkit-scrollbar {
  width: 8px;
  height: 8px;
}

.table-body::-webkit-scrollbar-track,
.table-header::-webkit-scrollbar-track {
  background: var(--scrollbar-track);
}

.table-body::-webkit-scrollbar-thumb,
.table-header::-webkit-scrollbar-thumb {
  background: var(--scrollbar-thumb);
  border-radius: 4px;
}

.table-body::-webkit-scrollbar-thumb:hover,
.table-header::-webkit-scrollbar-thumb:hover {
  background: var(--scrollbar-thumb-hover);
}

/* 题材点击保护 */
.sector-click-guard {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
}

.sector-cell-wrapper {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
}

.sector-cell :deep(.sector-tags) {
  max-width: 100%;
  overflow-x: auto;
  white-space: nowrap;
  display: flex;
  gap: 4px;
}

/* 空状态 */
.empty-state {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  color: var(--text-tertiary);
  font-size: 14px;
  padding: 30px;
  background: var(--bg-secondary);
  border-radius: 12px;
  box-shadow: var(--shadow-md);
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }

  to {
    transform: rotate(360deg);
  }
}

.empty-icon {
  font-size: 40px;
}

/* 题材单元格 */
.themes-cell {
  text-align: left;
  padding-left: 8px;
  height: 48px;
  display: flex;
  align-items: center;
}

/* 题材徽章 */
.themes-badge {
  display: inline-block;
  padding: 0 8px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 500;
  white-space: nowrap;
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  line-height: 20px;
  height: 20px;
  transition: all 0.2s;
  cursor: context-menu;
}

.themes-badge:hover {
  filter: brightness(1.1);
  max-width: none;
  overflow: visible;
  position: relative;
  z-index: 10;
  transform: scale(1.02);
}

/* 单个题材 - 蓝色系（类似幼苗期） */
.theme-single {
  background: rgba(74, 222, 128, 0.15);
  border-color: #4ade80;
  color: #4ade80;
}

/* 两个题材 - 橙色系（类似成长期） */
.theme-double {
  background: rgba(251, 191, 36, 0.15);
  border-color: #fbbf24;
  color: #fbbf24;
}

/* 多个题材 - 红色系（类似成熟期） */
.theme-multiple {
  background: rgba(239, 68, 68, 0.15);
  border-color: #ef4444;
  color: #ef4444;
  font-weight: 600;
}

/* 不同热度等级 */
.themes-normal {
  background: rgba(100, 100, 100, 0.1);
  border-color: #6b7280;
  color: #9ca3af;
}

.themes-warm {
  background: rgba(251, 191, 36, 0.1);
  border-color: #fbbf24;
  color: #fbbf24;
}

.themes-hot {
  background: rgba(239, 68, 68, 0.1);
  border-color: #ef4444;
  color: #ef4444;
  font-weight: 600;
}

/* 空题材 - 灰色 */
.themes-empty {
  color: var(--text-tertiary);
  font-size: 11px;
}

.theme-tag-only {
  background: rgba(156, 39, 176, 0.15);
  border-color: #9c27b0;
  color: #9c27b0;
}

.theme-tag-only:hover {
  background: rgba(156, 39, 176, 0.25);
}

/* 置信度单元格 */
.confidence-cell {
  text-align: center;
  padding: 4px 8px;
}

.signal-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: 16px;
  font-size: 12px;
  font-weight: 500;
  white-space: nowrap;
}

.signal-percent {
  font-family: 'SF Mono', Monaco, Consolas, monospace;
  font-size: 11px;
  opacity: 0.9;
}

/* 买入徽章 - 红色 */
.buy-badge {
  background: rgba(255, 71, 87, 0.15);
  color: #ff4757;
  border: 1px solid rgba(255, 71, 87, 0.3);
}

/* 卖出徽章 - 绿色 */
.sell-badge {
  background: rgba(46, 213, 115, 0.15);
  color: #2ed573;
  border: 1px solid rgba(46, 213, 115, 0.3);
}

/* 持有徽章 - 橙色 */
.hold-badge {
  background: rgba(243, 156, 18, 0.15);
  color: #f39c12;
  border: 1px solid rgba(243, 156, 18, 0.3);
}

/* MACD 徽章样式 */
.macd-badge {
  font-size: 14px;
  margin-left: 4px;
  display: inline-block;
  vertical-align: middle;
}

.macd-badge.golden {
  color: #ffd700;
  text-shadow: 0 0 3px rgba(255, 215, 0, 0.5);
  filter: drop-shadow(0 0 2px rgba(255, 215, 0, 0.8));
}

.macd-badge.death {
  color: #7f8c8d;
  text-shadow: 0 0 2px rgba(127, 140, 141, 0.5);
}

/* 量比颜色样式 */
.volume-ratio-high {
  color: #ffa502 !important;
  font-weight: 600;
}

.volume-ratio-low {
  color: #4a90e2 !important;
  font-weight: 500;
}

/* 八平台排名前三样式 */
.platform-1st {
  background: linear-gradient(135deg, #ffd700 0%, #ffb300 100%);
  color: #000 !important;
  padding: 0 4px;
  border-radius: 8px;
  font-weight: bold;
  font-size: 10px;
  display: inline-block;
  min-width: 24px;
  text-align: center;
  line-height: 16px;
  height: 16px;
}

.platform-2nd {
  background: linear-gradient(135deg, #c0c0c0 0%, #a0a0a0 100%);
  color: #000 !important;
  padding: 0 4px;
  border-radius: 8px;
  font-weight: bold;
  font-size: 10px;
  display: inline-block;
  min-width: 24px;
  text-align: center;
  line-height: 16px;
  height: 16px;
}

.platform-3rd {
  background: linear-gradient(135deg, #cd7f32 0%, #b87333 100%);
  color: #fff !important;
  padding: 0 4px;
  border-radius: 8px;
  font-weight: bold;
  font-size: 10px;
  display: inline-block;
  min-width: 24px;
  text-align: center;
  line-height: 16px;
  height: 16px;
}

/* 第4-10名排名高亮 */
.cell[data-key="emRank"] .rank-4-10,
.cell[data-key="thsRank"] .rank-4-10,
.cell[data-key="kplRank"] .rank-4-10,
.cell[data-key="tdxRank"] .rank-4-10,
.cell[data-key="xqRank"] .rank-4-10,
.cell[data-key="clsRank"] .rank-4-10,
.cell[data-key="tgbRank"] .rank-4-10,
.cell[data-key="dzhRank"] .rank-4-10 {
  color: #ffa502 !important;
  font-weight: 600;
}
</style>
