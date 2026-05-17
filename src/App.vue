<!-- src/App.vue -->

<template>
  <!-- 启动界面 -->
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

        <!-- 题材分析 -->
        <button ref="sectorBtnRef" class="btn-icon" title="题材分析 (Ctrl+S)" @click="openPanel('sector', $event)">
          <span class="icon">📊</span>
        </button>

        <button ref="themeRiskBtnRef" class="btn-icon" title="题材风险看板" @click="openPanel('themeRisk', $event)">
          <span class="icon">🎯</span>
        </button>

        <button ref="eventMonitorBtnRef" class="btn-icon" title="异动监控" @click="openPanel('eventMonitor', $event)">
          <span class="icon">🔔</span>
        </button>

        <!-- 龙头监测 -->
        <button ref="dragonBtnRef" class="btn-icon" title="龙头监测 (Ctrl+D)" @click="openPanel('dragon', $event)">
          <span class="icon">🐲</span>
        </button>

        <!-- 龙息分析 -->
        <button ref="breathBtnRef" class="btn-icon" title="龙息分析 (Ctrl+B)" @click="openPanel('breath', $event)">
          <span class="icon">🔥</span>
        </button>

        <!-- 算法中心 -->
        <button ref="algorithmBtnRef" class="btn-icon algorithm-core-btn" title="算法中心 (Ctrl+Shift+A)"
          @click="openPanel('algorithm', $event)">
          <span class="icon">🧠</span>
        </button>

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
            <div class="dropdown-item" @click="openSettings('algorithm')">
              <span class="item-icon">🧠</span>算法中心
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
              <span class="item-icon">📓</span>交易日记
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
    <AlgorithmPanel v-model:visible="panels.algorithm" :trigger-rect="panelRects.algorithm"
      @close="panels.algorithm = false" />
    <SectorPanel v-model:visible="panels.sector" :trigger-rect="panelRects.sector" @close="panels.sector = false"
      @show-detail="openSectorDetail" />
    <DragonHeadPanel v-model:visible="panels.dragon" :trigger-rect="panelRects.dragon" @close="panels.dragon = false" />
    <DragonBreathPanel v-model:visible="panels.breath" :trigger-rect="panelRects.breath"
      @close="panels.breath = false" />
    <KeyboardHelpPanel v-model:visible="panels.help" @close="panels.help = false" />
    <ExportPanel v-model:visible="panels.export" :trigger-rect="panelRects.export" @close="panels.export = false" />
    <FavoritePanel v-model:visible="panels.favorite" @close="panels.favorite = false" />
    <CandidatePoolPanel v-model:visible="panels.candidatePool" @close="panels.candidatePool = false" />
    <TradeJournalPanel v-model:visible="panels.journal" @close="panels.journal = false" />
    <HotStockEventMonitorPanel v-model:visible="panels.eventMonitor" :trigger-rect="panelRects.eventMonitor"
      @close="panels.eventMonitor = false" @select-stock="handleSelectStock" />
    <StockL2DetailPanel :visible="panels.stockDetail" :stock-code="selectedStockCode"
      :stock-name="selectedStockName" :trigger-rect="panelRects.stockDetail"
      @close="panels.stockDetail = false" />

    <!-- 题材相关面板 -->
    <SectorDetail v-model:visible="panels.sectorDetail" :sector-name="sectorDetailName"
      :trigger-rect="panelRects.sectorDetail" @close="panels.sectorDetail = false" @select-theme="openSectorDetail" />
    <SectorAlert v-model:visible="panels.sectorAlert" :trigger-rect="panelRects.sectorAlert"
      @close="panels.sectorAlert = false" @show-detail="openSectorDetail" />
    <SectorRotation v-model:visible="panels.sectorRotation" :trigger-rect="panelRects.sectorRotation"
      @close="panels.sectorRotation = false" @show-detail="openSectorDetail" />
    <ThemeRiskDashboard v-model:visible="panels.themeRisk" :trigger-rect="panelRects.themeRisk"
      @close="panels.themeRisk = false" />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, defineAsyncComponent, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { storeToRefs } from 'pinia'

// 通用组件
import DragonThemeToggle from './components/theme/DragonThemeToggle.vue'
import Toast from './components/common/Toast.vue'
import SplashScreen from './components/common/SplashScreen.vue'
import NavTabs from './components/common/NavTabs.vue'
import TradingStatus from './components/common/TradingStatus.vue'
import SearchBox from './components/common/SearchBox.vue'
import DataTable from './components/common/DataTable.vue'
import DataFreshness from './components/common/DataFreshness.vue'

// 面板组件体积较大，按需异步加载，降低首屏 chunk 体积。
const SettingsPanel = defineAsyncComponent(() => import('./components/panels/SettingsPanel.vue'))
const ConfigPanel = defineAsyncComponent(() => import('./components/panels/ConfigPanel.vue'))
const AlgorithmPanel = defineAsyncComponent(() => import('./components/panels/AlgorithmPanel.vue'))
const SectorPanel = defineAsyncComponent(() => import('./components/panels/SectorPanel.vue'))
const DragonHeadPanel = defineAsyncComponent(() => import('./components/panels/DragonHeadPanel.vue'))
const DragonBreathPanel = defineAsyncComponent(() => import('./components/panels/DragonBreathPanel.vue'))
const KeyboardHelpPanel = defineAsyncComponent(() => import('./components/panels/KeyboardHelpPanel.vue'))
const ExportPanel = defineAsyncComponent(() => import('./components/panels/ExportPanel.vue'))
const FavoritePanel = defineAsyncComponent(() => import('./components/panels/FavoritePanel.vue'))
const CandidatePoolPanel = defineAsyncComponent(() => import('./components/panels/CandidatePoolPanel.vue'))
const StockL2DetailPanel = defineAsyncComponent(() => import('./components/panels/StockL2DetailPanel.vue'))
const SectorDetail = defineAsyncComponent(() => import('./components/panels/SectorDetail.vue'))
const SectorAlert = defineAsyncComponent(() => import('./components/panels/SectorAlert.vue'))
const SectorRotation = defineAsyncComponent(() => import('./components/panels/SectorRotation.vue'))
const ThemeRiskDashboard = defineAsyncComponent(() => import('./components/panels/ThemeRiskDashboard.vue'))
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


// ========== 2. 数据加载服务（依赖 dataLayer）==========
import { themeMapping } from './services/ThemeDataService'    // 题材静态映射
import { dataLoader } from './services/dataLoader'            // 八平台数据加载

// ========== 3. 业务分析服务（依赖 dataLayer + dataLoader）==========
import { sectorAnalyzer } from './services/sectorAnalyzer'    // 题材分析
import { themeSyncAdapter } from './services/theme/ThemeSyncAdapter'
import { dragonBreathAnalyzer } from './services/DragonBreathAnalyzer' // 情绪分析
import { dragonReviewService } from './services/dragon/DragonReviewService'  // 龙头分析
import { rotationService } from './services/rotationService'  // 轮动分析
import { ThemeCorrelationAnalyzer } from './services/ThemeCorrelationAnalyzer' // 联动分析
import { RankTrendAnalyzer } from './services/RankTrendAnalyzer' // 排名趋势分析
import { stockCodeManager } from './services/StockCodeManager'

// ========== 4. 算法服务 ==========
import { algorithmManager } from './services/algorithm'       // 算法管理

// ========== 5. 刷新和更新服务 ==========
import { refreshCoordinator } from './services/RefreshCoordinator'
import { RefreshManager } from './services/RefreshManager'

// ========== 6. 通知服务（最上层）==========
import { alertService } from './services/alertService'        // 预警服务


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
const currentTab = ref('market')
const searchKeyword = ref('')
const modeSwitching = ref(false)
const showDropdown = ref(false)
const sectorDetailName = ref('')
const selectedStockCode = ref('')
const selectedStockName = ref('')
const lastUpdateTime = ref<number | null>(null)


// 按钮引用
const refreshBtnRef = ref<HTMLElement>()
const sectorBtnRef = ref<HTMLElement>()
const dragonBtnRef = ref<HTMLElement>()
const breathBtnRef = ref<HTMLElement>()
const algorithmBtnRef = ref<HTMLElement>()
const favoriteBtnRef = ref<HTMLElement>()
const dropdownRef = ref<HTMLElement | null>(null)
const themeRiskBtnRef = ref<HTMLElement>()
const eventMonitorBtnRef = ref<HTMLElement>()

// 导航标签
const navTabs = [
  { id: 'market', label: '行情总览', icon: '📊' },
  { id: 'dragon', label: '龙头监测', icon: '🐲' },
  { id: 'emotion', label: '龙息监测', icon: '📈' },
  { id: 'sector', label: '题材热点', icon: '🎯' },
  { id: 'events', label: '异动监控', icon: '🔔' },
  { id: 'algorithm', label: '算法中心', icon: '🧠' },
]

// 面板管理
const panels = ref({
  settings: false,
  config: false,
  algorithm: false,
  sector: false,
  dragon: false,
  breath: false,
  help: false,
  export: false,
  favorite: false,
  sectorDetail: false,
  sectorAlert: false,
  sectorRotation: false,
  themeRisk: false,
  stockDetail: false,
  candidatePool: false,
  journal: false,
  eventMonitor: false,
})

const panelRects = ref<Record<string, DOMRect | undefined>>({})

// 定时器
const eventUnsubscribers: (() => void)[] = []
let disposeUIStore: (() => void) | undefined

// ========== 计算属性 ==========
const stockCount = computed(() => dataLayer.getStocks().length)

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
  if (triggerRef) {
    panelRects.value[panelName] = triggerRef.getBoundingClientRect()
  }
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
    : sectorBtnRef.value?.getBoundingClientRect()
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

const openSettings = (type: string) => {
  showDropdown.value = false
  if (type === 'refresh') panels.value.settings = true
  else if (type === 'config') panels.value.config = true
  else if (type === 'algorithm') panels.value.algorithm = true
}

const focusSearchInput = () => {
  const input = document.querySelector('.status-center .search-input') as HTMLInputElement | null
  input?.focus()
  input?.select()
}

useKeyboardShortcuts({
  onDragon: () => openPanelFromShortcut('dragon', dragonBtnRef.value),
  onSector: () => openPanelFromShortcut('sector', sectorBtnRef.value),
  onBreath: () => openPanelFromShortcut('breath', breathBtnRef.value),
  onFavorite: () => openPanelFromShortcut('favorite', favoriteBtnRef.value),
  onAlgorithm: () => openPanelFromShortcut('algorithm', algorithmBtnRef.value),
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
    dragon: 'dragon',
    emotion: 'breath',
    sector: 'sector',
    events: 'eventMonitor',
    algorithm: 'algorithm',
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
  showToast('⏳ 正在刷新全部数据...', 'info')

  try {
    await RefreshManager.manualRefresh('full')
  } catch (error) {
    showToast('❌ 刷新失败', 'error')
  }
}

// ========== 更新最后时间 ==========
const updateLastTime = () => {
  lastUpdateTime.value = Date.now()
}

// ========== 优化启动流程 ==========
const initializeAll = async () => {
  try {
    await updateSplash('加载平台数据...', 15, async () => {
      await dataLoader.bootstrapInitialData({ force: false })
    })

    // ========== 第3步：完成基础启动 ==========
    splashProgress.value = 100
    splashStatus.value = '准备就绪'
    lastUpdateTime.value = Date.now()

    // 延迟关闭启动画面
    setTimeout(() => {
      showSplash.value = false
    }, 500)

    // ========== 后台加载其他服务 ==========
    lazyLoadServices()

  } catch (error) {
    console.error('[App] ❌ 启动失败:', error)
    splashStatus.value = `启动失败: ${error instanceof Error ? error.message : '未知错误'}`
    setTimeout(() => {
      showSplash.value = false
    }, 2000)
  }
}

// ========== 后台懒加载其他服务 ==========
const lazyLoadServices = () => {

  // 使用 requestIdleCallback 在浏览器空闲时执行
  const idleCallback = window.requestIdleCallback || ((cb) => setTimeout(cb, 50))

  idleCallback(() => {
    // 第1批：核心分析服务（延迟0.5秒）
    setTimeout(() => {
      // 题材分析 - 加载板块列表
      safeExecute(sectorAnalyzer, 'init', '题材分析器')

      if (themeMapping && typeof themeMapping.waitForLoaded === 'function') {
        themeMapping.waitForLoaded().then(() => {
        })
      }

      // 旧龙头分析保留兼容；真龙复盘结果才是新主结论
      safeExecute(dragonReviewService, 'recalculateAll', '旧龙头兼容计算').then(() => {})
    }, 500)

    // 第2批：辅助分析服务（延迟1.5秒）
    setTimeout(() => {
      // 龙息分析
      safeExecute(dragonBreathAnalyzer, 'init', '龙息分析器')

      // 真龙复盘
      safeExecute(dragonReviewService, 'runFullUpdate', '真龙复盘')

      // 算法中心
      safeExecute(algorithmManager, 'init', '算法中心')
    }, 1500)

    // 第4批：刷新相关服务（延迟3.5秒）
    setTimeout(() => {
      // 刷新管理器
      safeExecute(RefreshManager, 'init', '刷新管理器')
      safeExecute(RefreshManager, 'start', '启动刷新')

    }, 3500)

    // 第5批：注册服务（延迟4.5秒）
    setTimeout(() => {
      if (refreshCoordinator?.registerService) {
        const services = [
          { name: 'dataLoader', instance: dataLoader },
          { name: 'themeRuntime', instance: themeSyncAdapter },
          { name: 'sectorAnalyzer', instance: sectorAnalyzer },
          { name: 'dragonBreathAnalyzer', instance: dragonBreathAnalyzer },
          { name: 'dragonReviewService', instance: dragonReviewService },
        ]
        services.forEach(({ name, instance }) => {
          if (instance) {
            refreshCoordinator.registerService(name, instance)
          }
        })
      }
    }, 4500)
  })
}

// ========== 辅助函数 ==========

/**
 * 更新启动画面状态并执行任务
 */
async function updateSplash(status: string, progress: number, task: () => Promise<void> | void) {
  splashStatus.value = status
  splashProgress.value = progress

  try {
    await task()
  } catch (error) {
    console.error(`[App] ❌ ${status}失败:`, error)
    throw error // 重新抛出，让外层 catch 处理
  }
}

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
  void stockCodeManager.getAllStocks()

  // 执行主初始化
  await initializeAll()

  // 其他设置
  selectorStore.registerKeyboardListener()
  selectorStore.init()

  document.addEventListener('click', handleClickOutside)

  // 事件监听
  const events = [
    [AppEvents.DATA.MERGED, updateLastTime],
    [AppEvents.REFRESH.COMPLETE, updateLastTime],
    [AppEvents.DRAGON.UPDATED, updateLastTime],
    [
      'stock:show-detail',
      (data: any) => {
        openStockDetail(data)
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
  sectorAnalyzer.destroy?.()
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
  justify-content: center;
  min-width: 200px;
  max-width: 400px;
  margin: 0 auto;
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
    max-width: 300px;
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
    max-width: 100%;
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

  .main-content {
    padding: 16px;
  }
}

@media (max-width: 480px) {

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
