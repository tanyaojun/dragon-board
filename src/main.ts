// src/main.ts
// 启动原则：主入口只保留首屏必需依赖；分析服务在首帧空闲后动态加载挂载（2026-09-26）。

import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import { FACTORS } from './config/factors'

// ===== 导入运行时常量 =====
import {
  AppEvents,
  BREATH_FACTOR_IDS,
  BREATH_FACTORS_META,
  LEADER_LEVELS,
  MARKET_PHASES,
  THEME_FACTOR_IDS,
  THEME_FACTORS_META,
} from './types/config'

//========== 统一数据层 ==========
import './services/DataLayer'
import './services/snapshot/facade'

// ========== 主题样式 ==========
import '@/themes/app-theme.css'
import '@/themes/dragon-theme.css'

// ========== 核心工具 ==========
import './utils/errorHandler'
import './utils/eventManager'

// ========== 缓存系统 ==========
import './services/LRUCache'

// ========== API 服务 ==========
import { apiService } from './services/apiService'
import './services/adapters'
import { dataLoader } from './services/dataLoader'

// ========== 股票代码管理器 ==========
import { stockCodeManager } from './services/StockCodeManager'

// ========== 竞价弱转强实时检测（功能性链路，启动即开） ==========
import { openingRealtimeEventBridge } from './services/hotlist/OpeningRealtimeEventBridge'

const app = createApp(App)
const pinia = createPinia()
app.use(pinia)

// ===== 只挂载首屏必需服务到 window，不初始化 =====
if (typeof window !== 'undefined') {
  // 控制台/devtools 手工检查 Pinia 状态的调试入口
  ;(window as any).pinia = pinia

  // 基础配置
  ;(window as any).FACTORS = FACTORS

  //apiService
  ;(window as any).apiService = apiService

  // 数据服务
  ;(window as any).dataLoader = dataLoader

  // 事件和常量
  ;(window as any).AppEvents = AppEvents
  ;(window as any).LEADER_LEVELS = LEADER_LEVELS
  ;(window as any).THEME_FACTOR_IDS = THEME_FACTOR_IDS
  ;(window as any).THEME_FACTORS_META = THEME_FACTORS_META
  ;(window as any).BREATH_FACTOR_IDS = BREATH_FACTOR_IDS
  ;(window as any).BREATH_FACTORS_META = BREATH_FACTORS_META
  ;(window as any).MARKET_PHASES = MARKET_PHASES
  ;(window as any).stockCodeManager = stockCodeManager

  //数据层（已经通过 import 自动挂载）(window as any).dataLayer = (window as any).dataLayer
  openingRealtimeEventBridge.start()
  ;(window as any).openingRealtimeEventBridge = openingRealtimeEventBridge

  console.log('[Main] 📦 服务已挂载到 window')
  console.log('   ├─ dataLayer: 统一数据层')
  console.log('   ├─ dataLoader: 八平台数据加载')
  console.log('   └─ stockCodeManager: 股票代码管理')

  // ===== 诊断/分析服务：首帧空闲后动态加载挂载（生产消费方为控制台诊断脚本） =====
  const installGlobalServices = async () => {
    const [
      { sectorAnalyzer },
      { dragonReviewService },
      { dragonBreathAnalyzer },
      { themeMapping },
      { themeCorrelationAnalyzer },
      { themeFacade },
      { themeSyncAdapter },
    ] = await Promise.all([
      import('./services/sectorAnalyzer'),
      import('./services/dragon/DragonReviewService'),
      import('./services/DragonBreathAnalyzer'),
      import('./services/ThemeDataService'),
      import('./services/ThemeCorrelationAnalyzer'),
      import('./services/theme/ThemeFacade'),
      import('./services/theme/ThemeSyncAdapter'),
    ])

    ;(window as any).sectorAnalyzer = sectorAnalyzer
    ;(window as any).dragonReviewService = dragonReviewService
    ;(window as any).dragonBreathAnalyzer = dragonBreathAnalyzer
    ;(window as any).themeMapping = themeMapping
    ;(window as any).themeFacade = themeFacade
    ;(window as any).themeRuntime = themeSyncAdapter
    ;(window as any).themeCorrelationAnalyzer = themeCorrelationAnalyzer

    console.log('[Main] 📦 分析服务已挂载到 window（首帧空闲）')
    console.log('   ├─ sectorAnalyzer: 题材分析')
    console.log('   ├─ themeFacade: 题材领域 facade')
    console.log('   ├─ themeRuntime: 题材运行态同步')
    console.log('   ├─ themeMapping: 题材静态映射')
    console.log('   ├─ themeCorrelationAnalyzer: 题材联动分析')
    console.log('   ├─ dragonReviewService: 龙头分析')
    console.log('   └─ dragonBreathAnalyzer: 情绪分析')
  }

  const idle = (cb: () => void) => {
    if (window.requestIdleCallback) {
      window.requestIdleCallback(() => void cb(), { timeout: 2000 })
    } else {
      setTimeout(() => void cb(), 200)
    }
  }
  idle(() => {
    void installGlobalServices()
  })
}

app.mount('#app')
