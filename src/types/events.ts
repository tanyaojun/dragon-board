// src/types/events.ts

/**
 * 应用事件定义
 */
export const AppEvents = {
  DATA: {
    MERGED: 'data:merged',
    UPDATED: 'data:updated',
    PLATFORMS_LOADED: 'platforms:loaded',
    QUOTES_UPDATED: 'quotes:updated',
  },

  SECTOR: {
    UPDATED: 'sector:updated',
    READY: 'sector:ready',
    BATCH_UPDATED: 'sector:batch:updated',
    HOT_UPDATED: 'sector:hot:updated',
    ALERT: 'sector:alert',
  },

  DRAGON: {
    UPDATED: 'dragon:updated',
    CHANGED: 'dragon:changed',
  },

  // ===== 新增：龙息事件 =====
  BREATH: {
    UPDATED: 'breath:updated', // 龙息数据更新
    PHASE_CHANGED: 'breath:phase:changed', // 龙息阶段变化
    ALERT: 'breath:alert', // 龙息预警
    FACTORS_UPDATED: 'breath:factors:updated', // 龙息因子更新
  },

  STOCK: {
    SELECTED: 'stock:selected',
    CLEARED: 'stock:cleared',
  },

  UI: {
    PANEL_OPEN: 'ui:panel:open',
    PANEL_CLOSE: 'ui:panel:close',
    TOAST: 'ui:toast',
  },

  REFRESH: {
    STARTED: 'refresh:started',
    COMPLETE: 'refresh:complete',
    FAIL: 'refresh:fail',
  },

  // 新增：协同事件
  SYNERGY: {
    INSIGHT: 'synergy:insight', // 市场洞察
    EMOTION_LEADER: 'synergy:emotion:leader', // 情绪龙头出现
    DRAGON_BREATH: 'synergy:dragon:breath', // 龙头影响情绪
  },
} as const

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

// ===== 关键修复：导出所有接口 =====
export type {
  SectorUpdatedEvent,
  SectorBatchEvent,
  SectorReadyEvent,
  SectorAlertEvent,
  StockSelectedEvent,
  ToastEvent,
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

// ===== 在导出中添加 =====
export type {
  SectorUpdatedEvent,
  SectorBatchEvent,
  SectorReadyEvent,
  SectorAlertEvent,
  StockSelectedEvent,
  ToastEvent,
  // 新增导出
  BreathUpdatedEvent,
  BreathPhaseChangedEvent,
  BreathAlertEvent,
  BreathFactorsUpdatedEvent,
}
