// src/main.ts（修改版）

import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import { FACTORS } from './config/factors'

// ===== 导入因子常量 =====
import { BREATH_FACTOR_IDS, BREATH_FACTORS_META } from './types'

//========== 统一数据层 ==========
import './services/DataLayer'

// ========== 主题样式 ==========
import '@/assets/theme.css'
import '@/assets/dragon-themes.css'

// ========== 核心工具 ==========
import './utils/errorHandler'
import './utils/eventManager'

// ========== 缓存系统 ==========
import './services/LRUCache'

// ========== API 服务 ==========
import { apiService } from './services/apiService'
import './services/adapters'
import { dataLoader } from './services/dataLoader'

//========== 分析服务 ==========
import { sectorAnalyzer } from './services/sectorAnalyzer'
import { dragonAnalyzer } from './services/DragonAnalyzer'
import { dragonBreathAnalyzer } from './services/DragonBreathAnalyzer'
import { algorithmManager } from './services/Algorithm'
import { algorithmConfigManager } from './services/Algorithm/AlgorithmConfigManager'

// ========== 股票代码管理器 ==========
import { stockCodeManager } from './services/StockCodeManager'

import { themeMapping } from './services/ThemeDataService'

import { themeCorrelationAnalyzer } from './services/ThemeCorrelationAnalyzer'

const app = createApp(App)
const pinia = createPinia()
app.use(pinia)

// ===== 只挂载服务到 window，不初始化 =====
if (typeof window !== 'undefined') {
  // 基础配置
  ;(window as any).FACTORS = FACTORS

  // 分析服务
  ;(window as any).sectorAnalyzer = sectorAnalyzer
  ;(window as any).dragonAnalyzer = dragonAnalyzer
  ;(window as any).dragonBreathAnalyzer = dragonBreathAnalyzer

  //算法服务
  ;(window as any).algorithmManager = algorithmManager
  ;(window as any).algorithmConfigManager = algorithmConfigManager

  //apiService
  ;(window as any).apiService = apiService

  // 数据服务
  ;(window as any).dataLoader = dataLoader

  //题材个股映射服务
  ;(window as any).themeMapping = themeMapping

  // 事件和常量(window as any).AppEvents = AppEvents(window as any).THEME_FACTOR_IDS = THEME_FACTOR_IDS(window as any).THEME_FACTORS_META = THEME_FACTORS_META
  ;(window as any).BREATH_FACTOR_IDS = BREATH_FACTOR_IDS
  ;(window as any).BREATH_FACTORS_META = BREATH_FACTORS_META
  ;(window as any).stockCodeManager = stockCodeManager
  ;(window as any).themeCorrelationAnalyzer = themeCorrelationAnalyzer

  //数据层（已经通过 import 自动挂载）(window as any).dataLayer = (window as any).dataLayer

  console.log('[Main] 📦 服务已挂载到 window')
  console.log('   ├─ sectorAnalyzer: 题材分析')
  console.log('   ├─ dragonAnalyzer: 龙头分析')
  console.log('   ├─ dragonBreathAnalyzer: 情绪分析')
  console.log('   ├─ algorithmManager: 算法管理')
  console.log('   ├─ dataLayer: 统一数据层') // 新增
  console.log('   └─ dataLoader: 八平台数据加载')
  console.log('   └─ stockCodeManager: 股票代码管理')
}

app.mount('#app')

if (typeof window !== 'undefined') {
  window.pinia = pinia
}

console.log('%c🐲 龙头看板系统 Vue3 版启动', 'color: #FFD700; font-size: 16px;')
console.log('✅ App 已挂载，等待 App.vue 初始化...')
