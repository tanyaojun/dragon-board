// src/types/algorithm.ts
// 算法相关类型定义（完整版）

import type { Stock, ScoreResult } from './core'

// ========== 性能监控类型 ==========
export interface PerformanceMetrics {
  avgCalcTime: number // 平均计算时间
  p95CalcTime: number // 95分位计算时间
  cacheHitRate: number // 缓存命中率
  queueWaitTime: number // 队列等待时间
  factorPerformance: Map<string, FactorPerformance>
  timestamp: number
}

export interface FactorPerformance {
  factorId: string
  factorName: string
  avgTime: number
  callCount: number
  errorRate: number
  contribution: number
  stability: number
  isHealthy: boolean
  suggestions?: string[]
}

// ========== 健康检查类型 ==========
export interface FactorHealth {
  id: string
  name: string
  callCount: number
  avgTime: number
  errorRate: number
  contribution: number
  stability: number
  lastCheck: number
  isHealthy: boolean
  suggestions?: string[]
}

export interface HealthCheckResult {
  valid: boolean
  issues: string[]
  warnings: string[]
  suggestions: string[]
  timestamp: number
}

export interface RepairTask {
  module: string
  type: string
  issues: string[]
  timestamp: number
}

export interface RepairResult {
  success: boolean
  fixedCount: number
  module: string
  details?: Record<string, any>
  error?: string
}

export type RepairHandler = (issues: string[]) => Promise<RepairResult> | RepairResult

// ========== 预热策略类型 ==========
export type WarmupSchedule = 'onStart' | 'onIdle' | 'periodic'
export type Priority = 'high' | 'medium' | 'low'

export interface WarmupStrategy {
  enabled: boolean
  schedule: WarmupSchedule
  interval?: number // 当 schedule = 'periodic' 时有效
  priority: Priority
  batchSize: number
  maxItems?: number
  concurrency?: number // 并发数，默认3
  retryCount?: number // 重试次数，默认2
}

export interface WarmupTarget {
  type: 'hotThemes' | 'leaders' | 'popularStocks' | 'custom'
  getStocks: () => Promise<Stock[]> | Stock[]
  priority: Priority
  batchSize: number
}

// ========== AB测试类型 ==========
export type ABTestStatus = 'draft' | 'running' | 'completed' | 'stopped'

export interface ABTest {
  id: string
  name: string
  description: string
  controlAlgorithm: string
  testAlgorithm: string
  traffic: number // 0-100
  startTime: number
  endTime?: number
  metrics: {
    controlAvgScore: number
    testAvgScore: number
    controlSuccessRate: number
    testSuccessRate: number
    sampleSize: number
    confidence: number
  }
  status: ABTestStatus
  createdBy?: string
  tags?: string[]
}

export interface ABTestResult {
  testId: string
  algorithmId: string
  stockCode: string
  score: number
  success: boolean
  timestamp: number
}

// ========== 情绪反馈相关类型 ==========
export interface EmotionAdjustment {
  factorId: string
  delta: number
  reason: string
  timestamp: number
}

export interface PhaseAdjustmentConfig {
  [phase: string]: {
    [factorId: string]: number // 正数增加，负数减少
  }
}

// ========== 配置类型 ==========
export interface AlgorithmConfig {
  version: number
  currentAlgorithm: string
  thresholds: Record<string, number>
  customWeights: Record<string, number> | null
  abTests: ABTest[]
  warmupStrategies: Record<string, WarmupStrategy>
  performanceConfig: {
    enableMetrics: boolean
    metricsInterval: number // 毫秒
    historySize: number
  }
  healthCheckConfig: {
    enabled: boolean
    interval: number // 毫秒
    autoRepair: boolean
  }
}

// ========== 配置存储类型 ==========
export interface StoredAlgorithmConfig {
  algorithmId: string
  weights: Record<string, number>
  thresholds: Record<string, number>
  enabledFactors: string[]
  lastUpdate: string
  version: string
}

// ========== 事件类型 ==========
export interface AlgorithmEvents {
  'algorithm:performance-updated': { metrics: PerformanceMetrics; timestamp: number }
  'algorithm:health-checked': HealthCheckResult
  'algorithm:warmup-started': { strategy: string; total: number }
  'algorithm:warmup-progress': { strategy: string; loaded: number; total: number }
  'algorithm:warmup-completed': { strategy: string; loaded: number; duration: number }
  'algorithm:ab-test-started': ABTest
  'algorithm:ab-test-completed': ABTest
  'algorithm:factor-health-warning': { factorId: string; health: FactorHealth }
  'algorithm:weights-adjusted': {
    phase: string
    adjustments: Array<{ factorId: string; oldWeight: number; newWeight: number }>
    timestamp: number
  }
  'algorithm:emotion-feedback-received': EmotionFeedback
}
