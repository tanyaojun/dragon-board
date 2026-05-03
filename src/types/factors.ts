// src/types/factors.ts

import type {
  BREATH_FACTOR_IDS,
  LEADER_CHANGE_TYPES,
  LEADER_LEVELS,
  THEME_FACTOR_IDS,
} from './config'

/**
 * 因子基础接口
 */
export interface Factor {
  id?: string
  name: string
  type: string
  category: string
  description: string
  example?: string
  range?: [number, number]
  min?: number
  max?: number
  unit?: string
  invert?: boolean
  calculate: (stock: any) => number
}

/**
 * 因子配置
 */
export interface FactorConfig {
  weight: number | 'dynamic'
  enabled: boolean
  min?: number
  max?: number
  baseWeight?: number // 用于 dynamic 类型的基准权重
}

/**
 * 龙头阈值配置（新增）
 */
export interface LeaderThresholds {
  continuous?: {
    minChange: number // 最小涨幅
    minDays: number // 最小连板天数
    maxRank: number // 最大排名
    minScore: number // 最低得分
    useRank?: boolean // 是否使用排名
    useFactorScore?: boolean // 是否使用因子得分
    factorThreshold?: number // 因子得分阈值
  }
  middle?: {
    minMV: number // 最小市值
    maxChange: number // 最大涨幅
    minTurnoverRate: number // 最小换手率
    maxTurnoverRate: number // 最大换手率
    maxRank: number // 最大排名
    useRank?: boolean
    useFactorScore?: boolean
    factorThreshold?: number
  }
  sector?: {
    maxRank: number // 最大排名
    minChange: number // 最小涨幅
    minScore: number // 最低得分
    minThemeHeat: number // 最小题材热度
    minTurnover: number // 最小成交额（全市场用）
    highTurnover: number // 较高成交额（全市场用）
    useRank?: boolean
    useTheme?: boolean
    useFactorScore?: boolean
    factorThreshold?: number
  }
  total?: {
    maxRank: number // 最大排名
    minDays: number // 最小连板天数
    eliteRank: number // 精英排名
    minScore: number // 最低得分
    minTurnover: number // 最小成交额（全市场用）
    extremeChange: number // 极端涨幅（全市场用）
    useRank?: boolean
    useFactorScore?: boolean
    factorThreshold?: number
  }
  emotion?: {
    minTurnoverRate: number // 最小换手率
    minAbsChange: number // 最小绝对涨幅
    minScore: number // 最低得分
    useFactorScore?: boolean
    factorThreshold?: number
  }
}

/**
 * 算法定义
 */
export interface Algorithm {
  id?: string
  name: string
  icon: string
  description: string
  category: string
  color: string
  factors: Record<string, FactorConfig>
  leaderThresholds?: LeaderThresholds
  adaptive?: boolean
  learningRate?: number
}

// ===== 题材因子定义（新增）=====

/**
 * 题材因子接口
 */
export interface ThemeFactors {
  themeHeat: number // 题材热度
  themeLeaderCount: number // 题材龙头数
  themeMomentum: number // 题材动量
  themePosition: number // 题材排名
  themeCorrelation?: number // 题材联动性（可选）
}

export type ThemeFactorId = (typeof THEME_FACTOR_IDS)[keyof typeof THEME_FACTOR_IDS]

export type BreathFactorId = (typeof BREATH_FACTOR_IDS)[keyof typeof BREATH_FACTOR_IDS]

export type LeaderLevelType = keyof typeof LEADER_LEVELS

export type LeaderChangeType = (typeof LEADER_CHANGE_TYPES)[keyof typeof LEADER_CHANGE_TYPES]
