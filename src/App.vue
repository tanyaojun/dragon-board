<!-- src/App.vue -->

<template>
  <!-- 启动界面（数据就绪前遮住主界面，避免空态列表闪现） -->
  <SplashScreen v-model:visible="showSplash" v-model:progress="splashProgress" v-model:status="splashStatus" />

  <!-- 主界面 -->
  <div v-show="!showSplash" class="app" :class="themeStore.themeClass">
    <!-- 顶部导航栏 -->
    <div class="navbar">
      <div class="nav-left">
        <div class="logo">
          <span class="logo-icon">🐲</span>
          <span class="logo-text">龙头看板</span>
          <span class="version-badge">v6.0.0</span>
        </div>
      </div>

      <div class="nav-center">
        <NavTabs v-model="currentTab" :tabs="navTabs" @update:modelValue="handleTabChange" />
      </div>

      <div class="nav-right">
        <!-- 刷新按钮 -->
        <button ref="refreshBtnRef" class="btn-icon" title="刷新数据 (F5)" @click="handleRefresh">
          <span class="icon">↻</span>
        </button>

        <DragonThemeToggle />

        <!-- 自选股 -->
        <button ref="favoriteBtnRef" class="btn-icon" title="自选股 (Ctrl+F)" @click="openPanel('favorite', $event)"
          data-favorite-trigger>
          <span class="icon">⭐</span>
        </button>

        <!-- 下拉菜单 -->
        <div class="dropdown" ref="dropdownRef">
          <button class="btn-icon" @click.stop="toggleDropdown">
            <span class="icon">⋯</span>
          </button>

          <div class="dropdown-menu" :class="{ show: showDropdown }">
            <div class="dropdown-header">设置</div>
            <div class="dropdown-item" @click="openSettings('refresh')">
              <span class="item-icon">⏱️</span>刷新设置
            </div>
            <div class="dropdown-item" @click="openSettings('config')">
              <span class="item-icon">⚙️</span>配置管理
            </div>
            <div class="dropdown-divider"></div>
            <div class="dropdown-item" @click="panels.help = true">
              <span class="item-icon">⌨️</span>快捷键帮助
            </div>
            <div class="dropdown-item" @click="openExportPanel($event)">
              <span class="item-icon">📤</span>数据导出
            </div>
            <div class="dropdown-divider"></div>
            <div class="dropdown-item" @click.stop="panels.candidatePool = true">
              <span class="item-icon">🎯</span>候选池
            </div>
            <div class="dropdown-item" @click.stop="panels.journal = true">
              <span class="item-icon">🎯</span>交易池
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 状态栏 -->
    <div class="status-bar">
      <div class="status-left">
        <div class="status-group">
          <span class="status-label">主题</span>
          <span class="status-value">{{ themeStore.themeConfig.name }}</span>
          <span class="theme-icon">{{ themeStore.themeIcon }}</span>
          <span v-if="themeStore.followSystem" class="status-badge">系统</span>
        </div>

        <DataFreshness />

        <div class="status-group">
          <span class="status-label">股票</span>
          <span class="status-value">{{ stockCount }}</span>
          <span class="status-unit">只</span>
          <span class="status-label">东财:<span class="status-value">{{ marketSummary.eastmoney }}</span></span>
          <span class="status-label">THS:<span class="status-value">{{ marketSummary.ths }}</span></span>
          <span class="status-label">KPL:<span class="status-value">{{ marketSummary.kpl }}</span></span>
          <span class="status-label">TDX:<span class="status-value">{{ marketSummary.tdx }}</span></span>
          <span class="status-label">雪球:<span class="status-value">{{ marketSummary.xueqiu }}</span></span>
          <span class="status-label">财联:<span class="status-value">{{ marketSummary.cls }}</span></span>
          <span class="status-label">淘股吧:<span class="status-value">{{ marketSummary.tgb }}</span></span>
          <span class="status-label">大智慧:<span class="status-value">{{ marketSummary.dzh }}</span></span>
          <span class="status-label">行情:<span class="status-value">{{ marketSummary.quotes }}</span></span>
        </div>
      </div>

      <div class="status-center">
        <SearchBox v-model="searchKeyword" placeholder="搜索股票代码/名称/拼音..." @search="handleSearch"
          @select="handleSearchSelect" />
      </div>

      <div class="status-right">
        <div class="status-group">
          <span class="status-label">更新时间</span>
          <span v-if="lastUpdateTime" class="status-value time">
            {{ formatTime(lastUpdateTime) }}
          </span>
        </div>

        <div class="status-group">
          <span class="status-label">交易状态</span>
          <TradingStatus />
        </div>
      </div>
    </div>

    <!-- 主要内容区 -->
    <main class="main-content">
      <DataTable @select="handleSelectStock" />
    </main>

    <!-- Toast 提示 -->
    <Toast />

    <!-- 所有面板 -->
    <SettingsPanel v-model:visible="panels.settings" :trigger-rect="panelRects.settings"
      @close="panels.settings = false" />
    <ConfigPanel v-model:visible="panels.config" :trigger-rect="panelRects.config" @close="panels.config = false" />
    <SectorPanel v-model:visible="panels.sector" :trigger-rect="panelRects.sector" @close="panels.sector = false"
      @show-detail="openSectorDetail" />
    <DragonBreathPanel v-model:visible="panels.breath" :trigger-rect="panelRects.breath"
      @close="panels.breath = false" />
    <HotlistEmotionPanel v-model:visible="panels.hotlistEmotion" :trigger-rect="panelRects.hotlistEmotion"
      @close="panels.hotlistEmotion = false" />
    <JevNarrativePanel v-model:visible="panels.jevNarrative" :trigger-rect="panelRects.jevNarrative"
      @close="panels.jevNarrative = false" />
    <KeyboardHelpPanel v-model:visible="panels.help" @close="panels.help = false" />
    <ExportPanel v-model:visible="panels.export" :trigger-rect="panelRects.export" @close="panels.export = false" />
    <FavoritePanel v-model:visible="panels.favorite" @close="panels.favorite = false" />
    <CandidatePoolPanel v-model:visible="panels.candidatePool" ref="candidatePoolPanelRef"
      @close="panels.candidatePool = false" />
    <TradeJournalPanel v-model:visible="panels.journal" @close="panels.journal = false" />
    <HotStockEventMonitorPanel v-model:visible="panels.eventMonitor" :trigger-rect="panelRects.eventMonitor"
      @close="panels.eventMonitor = false" @select-stock="handleSelectStock" />
    <StockL2DetailPanel :visible="panels.stockDetail" :stock-code="selectedStockCode" :stock-name="selectedStockName"
      :trigger-rect="panelRects.stockDetail" @close="panels.stockDetail = false" />
    <RankTrendPanel :visible="panels.rankTrend" :stock-code="rankTrendStockCode" :trigger-rect="panelRects.rankTrend"
      @update:visible="panels.rankTrend = $event" @close="panels.rankTrend = false" />

    <!-- 题材相关面板 -->
    <SectorDetail v-model:visible="panels.sectorDetail" :sector-name="sectorDetailName"
      :trigger-rect="panelRects.sectorDetail" @close="panels.sectorDetail = false" @select-theme="openSectorDetail" />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, defineAsyncComponent, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { storeToRefs } from 'pinia'

// 通用组件
import DragonThemeToggle from './components/theme/DragonThemeToggle.vue'
import SplashScreen from './components/common/SplashScreen.vue'
import Toast from './components/common/Toast.vue'
import NavTabs from './components/common/NavTabs.vue'
import TradingStatus from './components/common/TradingStatus.vue'
import SearchBox from './components/common/SearchBox.vue'
import DataTable from './components/common/DataTable.vue'
import DataFreshness from './components/common/DataFreshness.vue'
import type { CandidatePoolOpenPayload } from './types/candidatePoolOpenPayload'

// 面板组件体积较大，按需异步加载，降低首屏 chunk 体积。
const RankTrendPanel = defineAsyncComponent(() => import('./components/panels/RankTrendPanel.vue'))
const SettingsPanel = defineAsyncComponent(() => import('./components/panels/SettingsPanel.vue'))
const ConfigPanel = defineAsyncComponent(() => import('./components/panels/ConfigPanel.vue'))
const SectorPanel = defineAsyncComponent(() => import('./components/panels/SectorPanel.vue'))
const DragonBreathPanel = defineAsyncComponent(() => import('./components/panels/DragonBreathPanel.vue'))
const HotlistEmotionPanel = defineAsyncComponent(() => import('./components/panels/HotlistEmotionPanel.vue'))
const JevNarrativePanel = defineAsyncComponent(() => import('./components/panels/JevNarrativePanel.vue'))
const KeyboardHelpPanel = defineAsyncComponent(() => import('./components/panels/KeyboardHelpPanel.vue'))
const ExportPanel = defineAsyncComponent(() => import('./components/panels/ExportPanel.vue'))
const FavoritePanel = defineAsyncComponent(() => import('./components/panels/FavoritePanel.vue'))
const CandidatePoolPanel = defineAsyncComponent(() => import('./components/panels/CandidatePoolPanel.vue'))
const StockL2DetailPanel = defineAsyncComponent(() => import('./components/panels/StockL2DetailPanel.vue'))
const SectorDetail = defineAsyncComponent(() => import('./components/panels/SectorDetail.vue'))
const HotStockEventMonitorPanel = defineAsyncComponent(() => import('./components/panels/HotStockEventMonitorPanel.vue'))
import TradeJournalPanel from './components/panels/TradeJournalPanel.vue'

// Stores
import { useThemeStore } from './stores/theme'
import { useUIStore } from './stores/ui'
import { useSelectorStore } from './stores/selector'
import { useFavoriteStore } from './stores/favorite'
import { useConfigStore } from './stores/config'
import { useKeyboardShortcuts } from './composables/useKeyboardShortcuts'

// 核心服务
// ========== 1. 核心基础设施（最底层）==========
import { EventManager } from './utils/eventManager'           // 事件总线
import { AppEvents } from './types'
import { cacheManager } from '@/services/LRUCache'            // 缓存管理
import { dataLayer } from './services/DataLayer'              // 数据存储层（最基础）
import { PLATFORM_FAILURE_THRESHOLD } from './services/dataLoader/constants'


// ========== 2. 数据加载服务（依赖 dataLayer）==========
// 注意：themeMapping/分析服务改为 lazyLoadServices 内动态 import，
// 不进首屏 bundle（见阶段化启动编排，2026-09-26）。
import { dataLoader } from './services/dataLoader'            // 八平台数据加载
import { stockCodeManager } from './services/StockCodeManager'

// ========== 5. 刷新和更新服务 ==========
import { refreshCoordinator } from './services/RefreshCoordinator'
import { RefreshManager } from './services/RefreshManager'


// ========== Stores ==========
const themeStore = useThemeStore()
const uiStore = useUIStore()
const selectorStore = useSelectorStore()
const favoriteStore = useFavoriteStore()
const configStore = useConfigStore()

// ========== 状态 ==========
const showSplash = ref(true)
const splashProgress = ref(0)
const splashStatus = ref('初始化中...')
const splashClosing = ref(false)
const currentTab = ref('market')
const searchKeyword = ref('')
const modeSwitching = ref(false)
const showDropdown = ref(false)
const sectorDetailName = ref('')
const selectedStockCode = ref('')
const selectedStockName = ref('')
const rankTrendStockCode = ref('')
const lastUpdateTime = ref<number | null>(null)
const marketSummaryVersion = ref(0)


// 按钮引用
const refreshBtnRef = ref<HTMLElement>()
const favoriteBtnRef = ref<HTMLElement>()
const dropdownRef = ref<HTMLElement | null>(null)
const candidatePoolPanelRef = ref<{
  openCandidate: (data?: CandidatePoolOpenPayload) => Promise<void>
} | null>(null)

// 导航标签
const navTabs = [
  { id: 'market', label: '行情总览', icon: '📊' },
  { id: 'emotion', label: '龙息监测', icon: '📈' },
  { id: 'sector', label: '题材分析', icon: '🎯' },
  { id: 'events', label: '异动雷达', icon: '🔔' },
  { id: 'hotlistEmotion', label: '热榜情绪', icon: '🔥' },
  { id: 'jevNarrative', label: 'JEV叙事', icon: '🌡️' },
]

// 面板管理
const panels = ref({
  settings: false,
  config: false,
  hotlistEmotion: false,
  jevNarrative: false,
  sector: false,
  breath: false,
  help: false,
  export: false,
  favorite: false,
  sectorDetail: false,
  stockDetail: false,
  rankTrend: false,
  candidatePool: false,
  journal: false,
  eventMonitor: false,
})

const panelRects = ref<Record<string, DOMRect | undefined>>({})

// 定时器
const eventUnsubscribers: (() => void)[] = []
let disposeUIStore: (() => void) | undefined

// ========== 计算属性 ==========
const stockCount = computed(() => {
  marketSummaryVersion.value
  return dataLayer.getStocks().length
})

const marketSummary = computed(() => {
  marketSummaryVersion.value
  const platforms = dataLayer.getRawPlatforms() || {}
  const status = dataLayer.getPlatformStatus() || {}
  const count = (key: string) => (Array.isArray(platforms[key]) ? platforms[key].length : 0)
  const value = (key: string) => {
    const platformStatus = status[key]
    if (platformStatus && platformStatus.success === false) {
      const failures = platformStatus.consecutiveFailures
      // 连续失败未达阈值：显示“重试中”；达到阈值才显示“失败”，任何一次成功即恢复
      if (failures !== undefined && failures < PLATFORM_FAILURE_THRESHOLD) {
        return '重试中'
      }
      return '失败'
    }
    return count(key)
  }

  return {
    totalStocks: dataLayer.getStocks().length,
    eastmoney: value('eastmoney'),
    ths: value('ths'),
    kpl: value('kpl'),
    tdx: value('tdx'),
    xueqiu: value('xueqiu'),
    cls: value('cls'),
    tgb: value('tgb'),
    dzh: value('dzh'),
    quotes: dataLayer.getQuotesCount(),
  }
})

// ========== 工具函数 ==========
const formatTime = (timestamp: number) => {
  return new Date(timestamp).toLocaleTimeString()
}

const showToast = (message: string, type: 'success' | 'info' | 'error' = 'info') => {
  EventManager.emit(AppEvents.UI.TOAST, { message, duration: type === 'error' ? 2000 : 1500, type })
}

// ========== 面板操作 ==========
const openPanel = (panelName: keyof typeof panels.value, event: MouseEvent) => {
  const rect = (event.currentTarget as HTMLElement).getBoundingClientRect()
  panelRects.value[panelName] = rect
  panels.value[panelName] = true
}

const openPanelFromShortcut = (panelName: keyof typeof panels.value, triggerRef?: HTMLElement) => {
  // 无触发源（顶栏图标已移除）时清掉旧 rect，让面板走默认定位
  panelRects.value[panelName] = triggerRef?.getBoundingClientRect()
  panels.value[panelName] = true
}

const openExportPanel = (event?: MouseEvent) => {
  if (event?.currentTarget) {
    panelRects.value.export = (event.currentTarget as HTMLElement).getBoundingClientRect()
  }
  showDropdown.value = false
  panels.value.export = true
}

const openSectorDetail = (sectorName: string, event?: MouseEvent) => {
  panelRects.value.sectorDetail = event?.currentTarget
    ? (event.currentTarget as HTMLElement).getBoundingClientRect()
    : undefined
  sectorDetailName.value = sectorName
  panels.value.sectorDetail = true
}

const openStockDetail = (data: { code?: string; name?: string; triggerRect?: DOMRect }) => {
  const code = String(data?.code || '').trim()
  if (!code) return

  const stock = dataLayer.getStock(code)
  selectedStockCode.value = code
  selectedStockName.value = data?.name || stock?.name || code
  panelRects.value.stockDetail = data?.triggerRect
  panels.value.stockDetail = true
}

const openCandidatePool = async (data: CandidatePoolOpenPayload = {}) => {
  panels.value.candidatePool = true
  await nextTick()
  await candidatePoolPanelRef.value?.openCandidate(data)
}

const openRankTrend = (data: { stockCode?: string; code?: string; triggerRect?: DOMRect } = {}) => {
  const code = String(data.stockCode || data.code || '').replace(/\D/g, '').padStart(6, '0').slice(-6)
  if (!code) return
  rankTrendStockCode.value = code
  panelRects.value.rankTrend = data.triggerRect
  panels.value.rankTrend = true
}

const openSettings = (type: string) => {
  showDropdown.value = false
  if (type === 'refresh') panels.value.settings = true
  else if (type === 'config') panels.value.config = true
}

const focusSearchInput = () => {
  const input = document.querySelector('.status-center .search-input') as HTMLInputElement | null
  input?.focus()
  input?.select()
}

useKeyboardShortcuts({
  onSector: () => openPanelFromShortcut('sector'),
  onBreath: () => openPanelFromShortcut('breath'),
  onFavorite: () => openPanelFromShortcut('favorite', favoriteBtnRef.value),
  onExport: () => openPanelFromShortcut('export'),
  onRefresh: () => handleRefresh(),
  onHelp: () => {
    panels.value.help = !panels.value.help
  },
  onSearch: focusSearchInput,
})

// ========== 下拉菜单 ==========
const toggleDropdown = () => (showDropdown.value = !showDropdown.value)

const handleClickOutside = (e: MouseEvent) => {
  if (dropdownRef.value && !dropdownRef.value.contains(e.target as Node)) {
    showDropdown.value = false
  }
}

// ========== 标签切换 ==========
const handleTabChange = (tabId: string) => {
  const panelMap: Record<string, keyof typeof panels.value> = {
    emotion: 'breath',
    sector: 'sector',
    events: 'eventMonitor',
    hotlistEmotion: 'hotlistEmotion',
    jevNarrative: 'jevNarrative',
  }
  if (panelMap[tabId]) {
    panels.value[panelMap[tabId]] = true
  }
}

// ========== 搜索处理 ==========
const handleSearch = (keyword: string) => {
  const normalizedKeyword = keyword.trim()
  if (uiStore.filters.searchKeyword) {
    uiStore.updateFilters({ searchKeyword: '' })
  }

  const results = selectorStore.search(normalizedKeyword)
  if (results.length > 0) {
    selectorStore.selectStock(results[0].stock.code, { source: 'search', scroll: true })
  }
  EventManager.emit('search:keyword', normalizedKeyword)
}

// ========== 搜索处理 ==========
const handleSearchSelect = (code: string) => {
  uiStore.selectStock(code)
  selectorStore.selectStock(code, { source: 'search' })

  // 更新选中的股票
  const stock = dataLayer.getStock(code)
  if (stock) {
    selectedStockCode.value = code
    selectedStockName.value = stock.name || code
  }

  setTimeout(() => selectorStore.scrollToSelected(), 100)
}

// ========== 股票选择 ==========
const handleSelectStock = (code: string) => {
  uiStore.selectStock(code)
  selectorStore.selectStock(code, { source: 'table' })

  // 更新选中的股票
  const stock = dataLayer.getStock(code)
  if (stock) {
    selectedStockCode.value = code
    selectedStockName.value = stock.name || code
  }
}

// ========== 手动刷新 ==========
const handleRefresh = async () => {
  showToast('⏳ 正在刷新行情列表...', 'info')

  try {
    await dataLoader.refreshMarketList({ force: true, source: 'manual' })
  } catch (error) {
    console.error('[App] 手动刷新行情列表失败:', error)
    showToast('❌ 行情列表刷新失败', 'error')
  }
}

// ========== 更新最后时间 ==========
const updateLastTime = () => {
  lastUpdateTime.value = Date.now()
}

const splashStatusByPhase: Record<string, string> = {
  platform: '加载八平台热榜数据...',
  merge: '整理基础数据...',
  quote: '加载热榜行情数据...',
  signal: '计算排名趋势信号...',
  done: '准备就绪',
  error: '启动失败',
}

const syncSplashFromDataLoader = () => {
  if (!showSplash.value || splashClosing.value) return

  const status = dataLoader.isLoading?.value
  if (!status?.active) return

  splashProgress.value = Math.max(splashProgress.value, status.progress || 0)
  splashStatus.value = status.message || splashStatusByPhase[status.phase || ''] || '加载平台数据...'
}

watch(
  () => dataLoader.isLoading?.value,
  () => syncSplashFromDataLoader(),
  { deep: true },
)

// ========== 启动流程 ==========
// 启动画面遮住主界面直至数据就绪；缓存命中（快路径）150ms 收起，慢路径保留缓冲让"准备就绪"可见
const initializeAll = async () => {
  try {
    splashStatus.value = '加载平台数据...'
    splashProgress.value = 5
    const summary = await dataLoader.bootstrapInitialData({ force: false })

    // ========== 完成基础启动 ==========
    splashProgress.value = 100
    splashStatus.value = '准备就绪'
    lastUpdateTime.value = Date.now()
    splashClosing.value = true

    setTimeout(() => {
      showSplash.value = false
    }, summary?.fromCache ? 150 : 500)

    // ========== 后台加载分析服务 ==========
    lazyLoadServices()

  } catch (error) {
    console.error('[App] ❌ 启动失败:', error)
    splashStatus.value = `启动失败: ${error instanceof Error ? error.message : '未知错误'}`
    splashClosing.value = true
    setTimeout(() => {
      showSplash.value = false
    }, 2000)
  }
}

// 空闲时机执行（保留主线程让出语义，替代原固定 500/1500/3500ms 延迟；timeout 兜底防止长任务无限顺延）
const nextIdle = (): Promise<void> =>
  new Promise((resolve) => {
    if (window.requestIdleCallback) {
      window.requestIdleCallback(() => resolve(), { timeout: 2000 })
    } else {
      setTimeout(resolve, 50)
    }
  })

// 动态加载的题材分析器实例（unmount 时若已加载则销毁）
let loadedSectorAnalyzer: { destroy?: () => void } | null = null

// ========== 后台懒加载分析服务（动态 import，不进首屏 bundle） ==========
const lazyLoadServices = () => {
  void (async () => {
    // 第1批：核心分析服务（首个空闲时机）
    await nextIdle()
    const [{ sectorAnalyzer }, { themeMapping }] = await Promise.all([
      import('./services/sectorAnalyzer'),
      import('./services/ThemeDataService'),
    ])

    // 题材分析 - 加载板块列表
    safeExecute(sectorAnalyzer, 'init', '题材分析器')
    loadedSectorAnalyzer = sectorAnalyzer

    if (themeMapping && typeof themeMapping.waitForLoaded === 'function') {
      void themeMapping.waitForLoaded()
    }

    // window 诊断挂载（原 main.ts 职责并入；消费方仅控制台诊断脚本）
    ;(window as any).sectorAnalyzer = sectorAnalyzer
    ;(window as any).themeMapping = themeMapping

    // 热门题材因子周期刷新（theme.runtime 任务，交易时段限定；显式启动）
    const { themeFacade: facadeForRefresh } = await import('./services/theme/ThemeFacade')
    facadeForRefresh.startRuntimeRefresh()

    // 第2批：辅助分析服务
    await nextIdle()
    const [{ dragonBreathAnalyzer }] = await Promise.all([
      import('./services/DragonBreathAnalyzer'),
    ])

    // 龙息分析
    safeExecute(dragonBreathAnalyzer, 'init', '龙息分析器')
    ;(window as any).dragonBreathAnalyzer = dragonBreathAnalyzer

    // 第3批：刷新体系（服务实例就绪即注册；RefreshManager.start 只设定时器，不会立即拉数据）
    await nextIdle()
    if (refreshCoordinator?.registerService) {
      const services = [
        { name: 'dataLoader', instance: dataLoader },
        { name: 'sectorAnalyzer', instance: sectorAnalyzer },
        { name: 'dragonBreathAnalyzer', instance: dragonBreathAnalyzer },
      ]
      services.forEach(({ name, instance }) => {
        if (instance) {
          refreshCoordinator.registerService(name, instance)
        }
      })
    }

    // 全市场股票列表后台补齐（不与首屏数据抢带宽）
    void stockCodeManager.getAllStocks()

    // 刷新管理器
    safeExecute(RefreshManager, 'init', '刷新管理器')
    safeExecute(RefreshManager, 'start', '启动刷新')

    // 第4批：window 常量与调试服务挂载（原 main.ts 职责并入，消费方仅控制台诊断）
    await nextIdle()
    const [
      { FACTORS },
      constants,
      { apiService },
      { themeFacade },
      { openingRealtimeEventBridge },
    ] = await Promise.all([
      import('@/config/factors'),
      import('./types/config'),
      import('./services/apiService'),
      import('./services/theme/ThemeFacade'),
      import('./services/hotlist/OpeningRealtimeEventBridge'),
    ])
    ;(window as any).FACTORS = FACTORS
    ;(window as any).AppEvents = constants.AppEvents
    ;(window as any).LEADER_LEVELS = constants.LEADER_LEVELS
    ;(window as any).THEME_FACTOR_IDS = constants.THEME_FACTOR_IDS
    ;(window as any).THEME_FACTORS_META = constants.THEME_FACTORS_META
    ;(window as any).BREATH_FACTOR_IDS = constants.BREATH_FACTOR_IDS
    ;(window as any).BREATH_FACTORS_META = constants.BREATH_FACTORS_META
    ;(window as any).MARKET_PHASES = constants.MARKET_PHASES
    ;(window as any).apiService = apiService
    ;(window as any).dataLoader = dataLoader
    ;(window as any).stockCodeManager = stockCodeManager
    ;(window as any).themeFacade = themeFacade
    ;(window as any).openingRealtimeEventBridge = openingRealtimeEventBridge

    console.log('[App] 📦 诊断服务已挂载到 window（空闲批）')
  })()
}

// ========== 辅助函数 ==========


/**
 * 安全执行对象方法
 * @param obj 目标对象
 * @param methodName 方法名
 * @param context 上下文描述（用于日志）
 * @param defaultValue 方法不存在或失败时的默认返回值
 */
async function safeExecute(obj: any, methodName: string, context: string, defaultValue?: any) {
  if (!obj) {
    console.warn(`[App] ⚠️ ${context} 不存在，跳过`)
    return defaultValue
  }

  const method = obj[methodName]
  if (typeof method !== 'function') {
    console.warn(`[App] ⚠️ ${context}.${methodName} 不是函数，跳过`)
    return defaultValue
  }

  try {
    const result = await method.call(obj)
    return result ?? defaultValue
  } catch (error) {
    console.error(`[App] ❌ ${context}.${methodName} 执行失败:`, error)
    // 不抛出错误，让初始化继续
    return defaultValue
  }
}


// ========== 生命周期 ==========
onMounted(async () => {
  themeStore.init()
  disposeUIStore = uiStore.init()
  favoriteStore.init()

  for (const path of ['raw.platforms', 'raw.platformStatus', 'merged.stocks', 'quotes:batch']) {
    eventUnsubscribers.push(dataLayer.subscribe(path, () => marketSummaryVersion.value++))
  }

  // 执行主初始化
  await initializeAll()
  marketSummaryVersion.value++

  // 其他设置
  selectorStore.registerKeyboardListener()
  selectorStore.init()

  document.addEventListener('click', handleClickOutside)

  // 事件监听
  const events = [
    [AppEvents.DATA.MERGED, updateLastTime],
    [AppEvents.REFRESH.COMPLETE, updateLastTime],
    [
      'candidate-pool:open',
      (data: any) => {
        void openCandidatePool(data)
      },
    ],
    [
      'stock:show-detail',
      (data: any) => {
        openStockDetail(data)
      },
    ],
    [
      'rank-trend:open',
      (data: any) => {
        openRankTrend(data)
      },
    ],
    [
      'sector:show-detail',
      (data: any) => {
        if (data.event?.currentTarget) {
          panelRects.value.sector = data.event.currentTarget.getBoundingClientRect()
          panelRects.value.sectorDetail = data.event.currentTarget.getBoundingClientRect()
        }
        if (data.themeName) sectorDetailName.value = data.themeName
        panels.value.sector = true
        panels.value.sectorDetail = true
      },
    ],
    [
      'theme:clicked',
      (data: any) => {
        if (data.theme?.name) sectorDetailName.value = data.theme.name
        panels.value.sector = true
      },
    ],
  ]

  events.forEach(([event, handler]) => {
    EventManager.on(event as string, handler as any)
    eventUnsubscribers.push(() => EventManager.off(event as string, handler as any))
  })
})

onUnmounted(() => {
  disposeUIStore?.()
  document.removeEventListener('click', handleClickOutside)
  eventUnsubscribers.forEach((fn) => fn())
  eventUnsubscribers.length = 0
  loadedSectorAnalyzer?.destroy?.()
})
</script>

<style scoped>
/* 样式保持不变 */
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  font-family:
    -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
  font-size: 14px;
  overflow: hidden;
}

.app {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background-color: var(--bg-primary);
  color: var(--text-primary);
  transition:
    background-color 0.3s,
    color 0.3s;
}

.navbar {
  height: 60px;
  background-color: var(--bg-header);
  backdrop-filter: blur(var(--blur-amount));
  border-bottom: 1px solid var(--border-color);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  position: sticky;
  top: 0;
  z-index: 100;
  box-shadow: var(--shadow-sm);
}

.nav-left {
  flex: 0 0 auto;
}

.logo {
  display: flex;
  align-items: center;
  gap: 10px;
}

.logo-icon {
  font-size: 28px;
  line-height: 1;
  filter: drop-shadow(0 2px 4px rgba(0, 0, 0, 0.2));
}

.logo-text {
  font-size: 18px;
  font-weight: 600;
  background: linear-gradient(135deg, var(--color-highlight) 0%, #ff9f7f 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.version-badge {
  padding: 2px 8px;
  background-color: var(--tag-bg);
  color: var(--tag-text);
  border-radius: 12px;
  font-size: 11px;
  font-weight: 500;
  letter-spacing: 0.3px;
}

.nav-center {
  flex: 1 1 auto;
  display: flex;
  justify-content: center;
}

.nav-right {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 2px;
}

.btn-icon {
  width: 36px;
  height: 36px;
  border: none;
  background: none;
  border-radius: 8px;
  color: var(--text-secondary);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s ease;
  font-size: 16px;
}

.btn-icon:hover {
  background-color: var(--bg-hover);
  color: var(--text-primary);
  transform: translateY(-1px);
}

.btn-icon:active {
  transform: translateY(0);
}

.icon {
  font-size: 18px;
  line-height: 1;
}

.dropdown {
  position: relative;
}

.dropdown-menu {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  min-width: 200px;
  background-color: var(--bg-panel);
  backdrop-filter: blur(var(--blur-amount));
  border: 1px solid var(--border-color);
  border-radius: 12px;
  box-shadow: var(--shadow-lg);
  opacity: 0;
  visibility: hidden;
  transform: translateY(-8px);
  transition: all 0.2s ease;
  z-index: 1000;
  overflow: hidden;
}

.dropdown-menu.show {
  opacity: 1;
  visibility: visible;
  transform: translateY(0);
}

.dropdown-header {
  padding: 12px 16px 8px;
  color: var(--text-tertiary);
  font-size: 11px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  border-bottom: 1px solid var(--border-light);
}

.dropdown-item {
  padding: 10px 16px;
  display: flex;
  align-items: center;
  gap: 12px;
  color: var(--text-primary);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.dropdown-item:hover {
  background-color: var(--bg-hover);
  color: var(--color-highlight);
  padding-left: 20px;
}

.item-icon {
  font-size: 16px;
  width: 20px;
  text-align: center;
}

.dropdown-divider {
  height: 1px;
  background-color: var(--border-light);
  margin: 4px 0;
}

.status-bar {
  height: 44px;
  background-color: var(--bg-secondary);
  border-bottom: 1px solid var(--border-color);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  font-size: 13px;
  gap: 20px;
}

.status-left,
.status-right {
  display: flex;
  align-items: center;
  gap: 32px;
  flex-shrink: 0;
}

.status-center {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
  min-width: 0;
}

.status-center :deep(.search-box) {
  flex: 0 0 320px;
  width: 320px;
  min-width: 200px;
}

.status-center :deep(.search-input) {
  box-sizing: border-box;
}

.status-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.status-label {
  color: var(--text-tertiary);
  font-size: 12px;
  font-weight: 400;
}

.status-value {
  color: var(--text-primary);
  font-weight: 500;
}

.status-value.time {
  font-family: 'SF Mono', Monaco, Consolas, monospace;
  font-size: 12px;
}

.status-unit {
  color: var(--text-tertiary);
  font-size: 12px;
  margin-left: -4px;
}

.status-badge {
  padding: 2px 8px;
  background-color: var(--badge-bg);
  color: var(--badge-text);
  border-radius: 12px;
  font-size: 10px;
  font-weight: 500;
  letter-spacing: 0.3px;
}

.theme-icon {
  font-size: 14px;
  margin-left: -4px;
}

.main-content {
  flex: 1;
  padding: 20px 24px;
  overflow-y: auto;
  background-color: var(--bg-primary);
}

.platform-summary {
  display: flex;
  align-items: center;
  flex: 1 1 auto;
  gap: 0;
  min-width: 0;
  min-height: 28px;
  overflow-x: auto;
  color: var(--text-tertiary);
  font-family: 'SF Mono', Monaco, Consolas, monospace;
  font-size: 11px;
  white-space: nowrap;
  scrollbar-width: thin;
}

.platform-summary span+span::before {
  content: '|';
  margin: 0 2px;
  color: var(--border-color);
}

.platform-summary-total {
  color: var(--text-secondary);
  font-weight: 600;
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }

  to {
    transform: rotate(360deg);
  }
}

.main-content::-webkit-scrollbar {
  width: 10px;
  height: 10px;
}

.main-content::-webkit-scrollbar-track {
  background: var(--scrollbar-track);
  border-radius: 5px;
}

.main-content::-webkit-scrollbar-thumb {
  background: var(--scrollbar-thumb);
  border-radius: 5px;
}

.main-content::-webkit-scrollbar-thumb:hover {
  background: var(--scrollbar-thumb-hover);
}

@media (max-width: 1200px) {
  .nav-center {
    display: none;
  }

  .status-center {
    gap: 12px;
  }
}

@media (max-width: 992px) {
  .status-bar {
    flex-wrap: wrap;
    height: auto;
    padding: 8px 16px;
  }

  .status-center {
    order: 3;
    width: 100%;
  }

  .status-left,
  .status-right {
    flex-wrap: wrap;
    gap: 16px;
  }
}

@media (max-width: 768px) {
  .navbar {
    padding: 0 16px;
    height: 56px;
  }

  .logo-text {
    display: none;
  }

  .status-left,
  .status-right {
    width: 100%;
    justify-content: space-between;
  }

  .status-center {
    order: 2;
  }

  .status-center :deep(.search-box) {
    flex-basis: 200px;
    width: 200px;
  }

  .main-content {
    padding: 16px;
  }
}

@media (max-width: 480px) {

  .status-center :deep(.search-box) {
    flex-basis: 160px;
    min-width: 160px;
    width: 160px;
  }

  .status-left,
  .status-right {
    flex-direction: column;
    align-items: flex-start;
    gap: 8px;
  }

  .btn-icon {
    width: 32px;
    height: 32px;
  }
}
</style>
