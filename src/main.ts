// src/main.ts
// 启动引导：只负责 createApp/mount 与功能性链路启动；window 诊断服务由
// App.vue lazyLoadServices 空闲批统一挂载（服务清单单一来源，2026-09-26）。

import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'

// 主题样式（首帧前必须就绪）
import '@/themes/app-theme.css'
import '@/themes/dragon-theme.css'

// 统一数据层（模块单例；window.dataLayer 由模块自身挂载）
import './services/DataLayer'

// 快照运行时（facade 顶层 start() 启动快照守卫/备份同步，功能性副作用）
import './services/snapshot/facade'

// 竞价弱转强实时检测（功能性链路，启动即开）
import { openingRealtimeEventBridge } from './services/hotlist/OpeningRealtimeEventBridge'

const app = createApp(App)
const pinia = createPinia()
app.use(pinia)

// 控制台/devtools 手工检查 Pinia 状态的调试入口
;(window as any).pinia = pinia

openingRealtimeEventBridge.start()

console.log('[Main] 🐲 龙头看板启动')

app.mount('#app')
