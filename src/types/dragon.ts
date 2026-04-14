// src/types/dragon.ts
// 龙头相关类型定义

import type { FactorDetail } from './core'
import type { LEADER_LEVELS } from './config'

export type LeaderLevelType = keyof typeof LEADER_LEVELS

// ========== 龙头稳定性配置 ==========
export const STABILITY_CONFIG = {
  // 时间阈值（毫秒）
  THRESHOLDS: {
    CANDIDATE: 30000,    // 30秒候选期
    CONFIRMED: 120000,   // 2分钟确认期
    STABLE: 300000,      // 5分钟稳定期
  },

  // 计数阈值
  COUNTS: {
    MIN_APPEARANCES: 3,      // 最少出现次数
    CONTINUOUS_CONFIRM: 2,   // 连续确认次数
  },

  // 平滑参数
  SMOOTHING: {
    DECAY_FACTOR: 0.8,       // 衰减因子
    HISTORY_SIZE: 10,        // 历史记录数
  },

  // 显示控制
  DISPLAY: {
    SHOW_CANDIDATE: false,    // 是否显示候选龙头
    SHOW_CONFIRMED: true,     // 是否显示确认龙头
    SHOW_STABLE: true,        // 是否显示稳定龙头
    HIGHLIGHT_NEW: true,      // 高亮新增
  }
} as const

// ========== 稳定性状态 ==========
export type LeaderStability = 'candidate' | 'confirmed' | 'stable'

// ========== 候选龙头接口 ==========
export interface CandidateLeader {
  info: LeaderInfo
  firstSeen: number
  lastSeen: number
  appearances: number[]      // 历史出现时间戳
  totalAppearances: number   // 总出现次数
  maxContinuous: number      // 最长连续出现次数
  scores: number[]           // 历史分数（用于平滑计算）
}

// ========== 稳定龙头接口 ==========
export interface StableLeader extends LeaderInfo {
  firstSeen: number          // 首次成为龙头的时间
  lastSeen: number           // 最后确认仍是龙头的时间
  confirmCount: number       // 连续确认次数
  stability: LeaderStability // 稳定性状态
  averageScore: number       // 平均分数（平滑后）
  appearanceRate: number     // 出现频率（次/分钟）
  expectedDuration: number   // 预期持续时间（毫秒）
}

// ========== 龙头信息接口 ==========
export interface LeaderInfo {
  code: string
  name: string
  score: number
  level: LeaderLevelType
  levelName: string
  reasons: string[]
  factorDetails: Record<string, FactorDetail>

  price: number
  change: number
  turnover: number
  turnoverRate: number
  compRank: number
  zlje: number
  zljzb: number
  totalMV: number
  cirMV: number

  themes: Array<{
    name: string
    heatScore?: number
    heatLevel?: string
    isLeader?: boolean
  }>
  mainTheme: {
    name: string
    heatScore?: number
    heatLevel?: string
  } | null
  themeHeat: number
  themeLevel: string

  sentimentInfo?: {
    overall: number
    phase: string
    ztCount?: number
    dtCount?: number
  }

  firstSeen: number
  lastSeen: number
  updateTime: number
  continuousDays: number
}

// ========== 龙头变化接口 ==========
export interface LeaderChange {
  type: '新增' | '消失' | '晋级' | '降级' | '题材变化' | '稳定' | '退化'
  code: string
  name: string
  level?: string
  fromLevel?: string
  toLevel?: string
  score?: number
  theme?: string
  time: number
  stability?: LeaderStability     // 变化时的稳定性状态
  duration?: number               // 已持续时间
}

// ========== 龙头统计接口 ==========
export interface LeaderStats {
  totalLeaders: number
  totalLeadersCount: number
  sectorLeaders: number
  continuousLeaders: number
  middleLeaders: number
  emotionLeaders: number
  themeLeaders: number
  lastUpdate: number | null

  // 稳定性统计
  stableLeaders: number           // 稳定龙头数量
  confirmedLeaders: number        // 确认龙头数量
  candidateLeaders: number        // 候选龙头数量
  averageDuration: number         // 平均持续时间（毫秒）
}

// ========== 龙头分布接口 ==========
export interface LeaderDistribution {
  byLevel: Record<string, number>
  byTheme: Record<string, number>
  total: number

  // 稳定性分布
  byStability: Record<LeaderStability, number>
}

// ========== 龙头阈值接口 ==========
export interface LeaderThresholds {
  totalLeader: number
  sectorLeader: number
  continuousLeader: number
  middleLeader: number
  emotionLeader: number
}

// ========== 阈值乘数接口 ==========
export interface ThresholdMultiplier {
  totalLeader: number
  continuousLeader: number
  sectorLeader: number
  middleLeader: number
  emotionLeader: number
}

// ========== 工具函数：平滑分数计算 ==========
export function calculateSmoothScore(
  currentScore: number,
  history: number[],
  decayFactor: number = STABILITY_CONFIG.SMOOTHING.DECAY_FACTOR
): number {
  if (history.length === 0) return currentScore

  let totalWeight = 0
  let weightedSum = 0

  // 当前分数权重最高
  weightedSum += currentScore * 1.0
  totalWeight += 1.0

  // 历史分数权重递减
  const recentHistory = history.slice(-STABILITY_CONFIG.SMOOTHING.HISTORY_SIZE)
  recentHistory.forEach((score, index) => {
    const weight = Math.pow(decayFactor, index + 1)
    weightedSum += score * weight
    totalWeight += weight
  })

  return Number((weightedSum / totalWeight).toFixed(2))
}

// ========== 工具函数：稳定性判断 ==========
export function determineStability(
  firstSeen: number,
  lastSeen: number,
  maxContinuous: number,
  totalAppearances: number
): LeaderStability {
  const now = Date.now()
  const totalTime = now - firstSeen
  const continuousTime = now - lastSeen

  // 如果最近超过30秒没出现，退化
  if (continuousTime > STABILITY_CONFIG.THRESHOLDS.CANDIDATE) {
    return 'candidate'
  }

  // 稳定期判断
  if (totalTime > STABILITY_CONFIG.THRESHOLDS.STABLE &&
      maxContinuous >= STABILITY_CONFIG.COUNTS.CONTINUOUS_CONFIRM * 2) {
    return 'stable'
  }

  // 确认期判断
  if (totalTime > STABILITY_CONFIG.THRESHOLDS.CONFIRMED &&
      maxContinuous >= STABILITY_CONFIG.COUNTS.CONTINUOUS_CONFIRM) {
    return 'confirmed'
  }

  return 'candidate'
}

// ========== 工具函数：计算出现频率 ==========
export function calculateAppearanceRate(
  firstSeen: number,
  totalAppearances: number
): number {
  const now = Date.now()
  const minutes = (now - firstSeen) / 60000
  return minutes > 0 ? totalAppearances / minutes : 0
}

// ========== 工具函数：计算预期持续时间 ==========
export function calculateExpectedDuration(
  firstSeen: number,
  lastSeen: number,
  maxContinuous: number
): number {
  const totalTime = lastSeen - firstSeen
  const baseDuration = totalTime * 1.5 // 基于已持续时间的预测

  // 根据连续出现次数加成
  const continuousBonus = maxContinuous * 30000 // 每次连续加30秒

  return Math.min(baseDuration + continuousBonus, 24 * 60 * 60 * 1000) // 最多24小时
}

if (typeof window !== 'undefined') {
  ;(window as any).STABILITY_CONFIG = STABILITY_CONFIG
}
