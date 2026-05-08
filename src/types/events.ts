// src/types/events.ts
export { AppEvents } from './config'
import { AppEvents } from './config'

export type AppEventType =
  (typeof AppEvents)[keyof typeof AppEvents][keyof (typeof AppEvents)[keyof typeof AppEvents]]

/**
 * 题材更新事件
 */
export interface SectorUpdatedEvent {
  count: number
  hotCount: number
  rotationCount?: number
  timestamp: number
}

/**
 * 题材批量加载事件
 */
export interface SectorBatchEvent {
  progress: number
  loaded: number
  total: number
}

/**
 * 题材就绪事件
 */
export interface SectorReadyEvent {
  themeCount: number
  cachedCount: number
  stockMapped: number
}

/**
 * 题材预警事件
 */
export interface SectorAlertEvent {
  themeId: string
  type: 'heat_surge' | 'momentum_break' | 'leader_change' | 'rotation_signal'
  level: 'info' | 'warning' | 'danger'
  message: string
  data: any
  timestamp: number
}

/**
 * 股票选中事件
 */
export interface StockSelectedEvent {
  code: string
  source?: 'click' | 'search' | 'keyboard'
}

/**
 * 提示事件
 */
export interface ToastEvent {
  message: string
  duration?: number
  type: 'info' | 'success' | 'warning' | 'error'
}

// ===== 新增：龙息事件接口 =====

/**
 * 龙息更新事件
 */
export interface BreathUpdatedEvent {
  sentiment: {
    overall: number
    phase: string
    riskLevel: string
    suggestion: string
  }
  marketData: {
    upCount: number
    downCount: number
    ztCount: number
    dtCount: number
    zhabanRate: number
  }
  themeImpact?: number
  dragonImpact?: number
  timestamp: number
}

/**
 * 龙息阶段变化事件
 */
export interface BreathPhaseChangedEvent {
  from: string
  to: string
  timestamp: number
}

/**
 * 龙息预警事件
 */
export interface BreathAlertEvent {
  type: 'phase_change' | 'extreme_value' | 'divergence'
  level: 'info' | 'warning' | 'danger'
  message: string
  data: any
  timestamp: number
}

/**
 * 龙息因子更新事件
 */
export interface BreathFactorsUpdatedEvent {
  factors: Record<string, number>
  weights: Record<string, number>
  timestamp: number
}
