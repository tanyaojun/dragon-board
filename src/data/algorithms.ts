// src/data/algorithms.ts

import type { Algorithm } from '@/types'
import { BREATH_FACTOR_IDS } from '@/types'

/**
 * 所有算法定义
 */
export const ALGORITHMS: Record<string, Algorithm> = {
  // ========== 平衡型 ==========
  balanced: {
    id: 'balanced',
    name: '平衡型',
    icon: '⚖️',
    description: '综合排名优先，兼顾技术指标和市场情绪',
    category: 'comprehensive',
    color: '#3498db',
    factors: {
      // 基础因子
      compRank: { weight: 0.15, enabled: true, min: 0.1, max: 0.4 },
      change: { weight: 0.08, enabled: true, min: 0.05, max: 0.2 },
      turnover: { weight: 0.08, enabled: true, min: 0.05, max: 0.2 },
      turnoverRate: { weight: 0.06, enabled: true, min: 0.03, max: 0.15 },
      zlje: { weight: 0.1, enabled: true, min: 0.05, max: 0.25 },

      // 题材因子
      sectorEffect: { weight: 0.08, enabled: true, min: 0.05, max: 0.2 },
      themeHeat: { weight: 0.08, enabled: true, min: 0.05, max: 0.2 },

      // 龙息因子
      [BREATH_FACTOR_IDS.PHASE]: { weight: 0.08, enabled: true, min: 0.03, max: 0.15 },
      [BREATH_FACTOR_IDS.ZT_COUNT]: { weight: 0.06, enabled: true, min: 0.03, max: 0.12 },
      [BREATH_FACTOR_IDS.DT_COUNT]: { weight: 0.04, enabled: true, min: 0.02, max: 0.08 },
      [BREATH_FACTOR_IDS.ZHABAN_RATE]: { weight: 0.04, enabled: true, min: 0.02, max: 0.1 },
      [BREATH_FACTOR_IDS.FENGBAN_RATE]: { weight: 0.04, enabled: true, min: 0.02, max: 0.1 },
      [BREATH_FACTOR_IDS.PASS_RATE]: { weight: 0.06, enabled: true, min: 0.03, max: 0.12 },
      [BREATH_FACTOR_IDS.MAX_DAYS]: { weight: 0.06, enabled: true, min: 0.03, max: 0.12 },
      [BREATH_FACTOR_IDS.UP_DOWN_RATIO]: { weight: 0.03, enabled: true, min: 0.01, max: 0.06 },
      [BREATH_FACTOR_IDS.EMOTION_VALUE]: { weight: 0.02, enabled: true, min: 0.01, max: 0.05 },
      [BREATH_FACTOR_IDS.MARKET_SCORE]: { weight: 0.02, enabled: true, min: 0.01, max: 0.05 },

      // 逆势因子
      contrarian: { weight: 0.05, enabled: true, min: 0.03, max: 0.12 },
    },
    // ===== 新增：龙头阈值配置 =====
    leaderThresholds: {
      continuous: {
        minChange: 9.5,
        minDays: 2,
        maxRank: 30,
        minScore: 70,
        useRank: true,
        useFactorScore: true,
        factorThreshold: 80,
      },
      middle: {
        minMV: 20e8,
        maxChange: 8,
        minTurnoverRate: 0.5,
        maxTurnoverRate: 15,
        maxRank: 50,
        useRank: true,
        useFactorScore: true,
        factorThreshold: 80,
      },
      sector: {
        maxRank: 50,
        minChange: 3,
        minScore: 70,
        minThemeHeat: 75,
        minTurnover: 1e8,
        highTurnover: 5e8,
        useRank: true,
        useTheme: true,
        useFactorScore: true,
        factorThreshold: 70,
      },
      total: {
        maxRank: 15,
        minDays: 3,
        eliteRank: 5,
        minScore: 95,
        minTurnover: 2e9,
        extremeChange: 15,
        useRank: true,
        useFactorScore: true,
        factorThreshold: 85,
      },
      emotion: {
        minTurnoverRate: 8,
        minAbsChange: 2,
        minScore: 60,
        useFactorScore: true,
        factorThreshold: 70,
      },
    },
  },

  // ========== 龙头优先 ==========
  dragonFirst: {
    id: 'dragonFirst',
    name: '龙头优先',
    icon: '👑',
    description: '强调市场地位和资金关注，结合市场情绪',
    category: 'leader',
    color: '#FFD700',
    factors: {
      // 基础因子
      marketCap: { weight: 0.1, enabled: true, min: 0.05, max: 0.25 },
      compRank: { weight: 0.12, enabled: true, min: 0.05, max: 0.25 },
      zlje: { weight: 0.12, enabled: true, min: 0.05, max: 0.25 },
      turnover: { weight: 0.08, enabled: true, min: 0.05, max: 0.2 },
      continuousDays: { weight: 0.1, enabled: true, min: 0.05, max: 0.2 },

      // 题材因子
      sectorEffect: { weight: 0.1, enabled: true, min: 0.05, max: 0.2 },
      themeHeat: { weight: 0.08, enabled: true, min: 0.05, max: 0.2 },

      // 龙息因子
      [BREATH_FACTOR_IDS.PHASE]: { weight: 0.08, enabled: true, min: 0.03, max: 0.15 },
      [BREATH_FACTOR_IDS.ZT_COUNT]: { weight: 0.06, enabled: true, min: 0.03, max: 0.12 },
      [BREATH_FACTOR_IDS.PASS_RATE]: { weight: 0.08, enabled: true, min: 0.03, max: 0.15 },
      [BREATH_FACTOR_IDS.MAX_DAYS]: { weight: 0.1, enabled: true, min: 0.05, max: 0.2 },
      [BREATH_FACTOR_IDS.UP_DOWN_RATIO]: { weight: 0.04, enabled: true, min: 0.02, max: 0.08 },

      // 逆势因子
      contrarian: { weight: 0.06, enabled: true, min: 0.03, max: 0.12 },
    },
    leaderThresholds: {
      continuous: {
        minChange: 9.0, // 龙头优先，涨幅要求稍低
        minDays: 2,
        maxRank: 40, // 排名要求放宽
        minScore: 65,
        useRank: true,
        useFactorScore: true,
        factorThreshold: 75,
      },
      middle: {
        minMV: 15e8, // 市值要求降低
        maxChange: 10,
        minTurnoverRate: 0.3,
        maxTurnoverRate: 20,
        maxRank: 60,
        useRank: true,
        useFactorScore: true,
        factorThreshold: 75,
      },
      sector: {
        maxRank: 60,
        minChange: 2,
        minScore: 65,
        minThemeHeat: 70,
        minTurnover: 0.8e8,
        highTurnover: 4e8,
        useRank: true,
        useTheme: true,
        useFactorScore: true,
        factorThreshold: 65,
      },
      total: {
        maxRank: 20,
        minDays: 2, // 连板要求降低
        eliteRank: 8,
        minScore: 90,
        minTurnover: 1.5e9,
        extremeChange: 12,
        useRank: true,
        useFactorScore: true,
        factorThreshold: 80,
      },
      emotion: {
        minTurnoverRate: 6,
        minAbsChange: 1.5,
        minScore: 55,
        useFactorScore: true,
        factorThreshold: 65,
      },
    },
  },

  // ========== 资金驱动 ==========
  moneyDriven: {
    id: 'moneyDriven',
    name: '资金驱动',
    icon: '💰',
    description: '主力资金流向优先，结合市场情绪',
    category: 'money',
    color: '#2ed573',
    factors: {
      // 基础因子
      zlje: { weight: 0.2, enabled: true, min: 0.1, max: 0.4 },
      zljzb: { weight: 0.12, enabled: true, min: 0.05, max: 0.25 },
      turnover: { weight: 0.12, enabled: true, min: 0.05, max: 0.25 },
      change: { weight: 0.08, enabled: true, min: 0.05, max: 0.2 },
      compRank: { weight: 0.08, enabled: true, min: 0.05, max: 0.2 },

      // 龙息因子
      [BREATH_FACTOR_IDS.PHASE]: { weight: 0.08, enabled: true, min: 0.03, max: 0.15 },
      [BREATH_FACTOR_IDS.ZT_COUNT]: { weight: 0.06, enabled: true, min: 0.03, max: 0.12 },
      [BREATH_FACTOR_IDS.DT_COUNT]: { weight: 0.05, enabled: true, min: 0.02, max: 0.1 },
      [BREATH_FACTOR_IDS.PASS_RATE]: { weight: 0.06, enabled: true, min: 0.03, max: 0.12 },
      [BREATH_FACTOR_IDS.MAX_DAYS]: { weight: 0.08, enabled: true, min: 0.03, max: 0.15 },
      [BREATH_FACTOR_IDS.UP_DOWN_RATIO]: { weight: 0.05, enabled: true, min: 0.02, max: 0.1 },

      // 逆势因子
      contrarian: { weight: 0.05, enabled: true, min: 0.02, max: 0.1 },
    },
    leaderThresholds: {
      continuous: {
        minChange: 9.5,
        minDays: 2,
        maxRank: 35,
        minScore: 68,
        useRank: true,
        useFactorScore: true,
        factorThreshold: 75,
      },
      middle: {
        minMV: 25e8, // 资金驱动更喜欢大市值
        maxChange: 7,
        minTurnoverRate: 0.8,
        maxTurnoverRate: 12,
        maxRank: 45,
        useRank: true,
        useFactorScore: true,
        factorThreshold: 75,
      },
      sector: {
        maxRank: 45,
        minChange: 3,
        minScore: 68,
        minThemeHeat: 70,
        minTurnover: 1.2e8, // 成交额要求更高
        highTurnover: 6e8,
        useRank: true,
        useTheme: true,
        useFactorScore: true,
        factorThreshold: 65,
      },
      total: {
        maxRank: 12,
        minDays: 3,
        eliteRank: 4,
        minScore: 92,
        minTurnover: 2.5e9, // 成交额要求更高
        extremeChange: 14,
        useRank: true,
        useFactorScore: true,
        factorThreshold: 80,
      },
      emotion: {
        minTurnoverRate: 7,
        minAbsChange: 2,
        minScore: 58,
        useFactorScore: true,
        factorThreshold: 68,
      },
    },
  },

  // ========== 技术驱动 ==========
  techDriven: {
    id: 'techDriven',
    name: '技术驱动',
    icon: '📈',
    description: '技术指标优先，结合市场情绪',
    category: 'technical',
    color: '#ffa502',
    factors: {
      // 基础因子
      change: { weight: 0.15, enabled: true, min: 0.1, max: 0.3 },
      turnover: { weight: 0.12, enabled: true, min: 0.05, max: 0.25 },
      turnoverRate: { weight: 0.12, enabled: true, min: 0.05, max: 0.25 },
      compRank: { weight: 0.1, enabled: true, min: 0.05, max: 0.2 },

      // 龙息因子
      [BREATH_FACTOR_IDS.PHASE]: { weight: 0.08, enabled: true, min: 0.03, max: 0.15 },
      [BREATH_FACTOR_IDS.ZT_COUNT]: { weight: 0.06, enabled: true, min: 0.03, max: 0.12 },
      [BREATH_FACTOR_IDS.UP_DOWN_RATIO]: { weight: 0.08, enabled: true, min: 0.04, max: 0.16 },
      [BREATH_FACTOR_IDS.EMOTION_VALUE]: { weight: 0.08, enabled: true, min: 0.04, max: 0.16 },
      [BREATH_FACTOR_IDS.PASS_RATE]: { weight: 0.06, enabled: true, min: 0.03, max: 0.12 },
      [BREATH_FACTOR_IDS.MAX_DAYS]: { weight: 0.06, enabled: true, min: 0.03, max: 0.12 },

      // 逆势因子
      contrarian: { weight: 0.04, enabled: true, min: 0.02, max: 0.1 },
    },
    leaderThresholds: {
      continuous: {
        minChange: 9.5,
        minDays: 2,
        maxRank: 35,
        minScore: 68,
        useRank: true,
        useFactorScore: true,
        factorThreshold: 75,
      },
      middle: {
        minMV: 25e8, // 资金驱动更喜欢大市值
        maxChange: 7,
        minTurnoverRate: 0.8,
        maxTurnoverRate: 12,
        maxRank: 45,
        useRank: true,
        useFactorScore: true,
        factorThreshold: 75,
      },
      sector: {
        maxRank: 45,
        minChange: 3,
        minScore: 68,
        minThemeHeat: 70,
        minTurnover: 1.2e8, // 成交额要求更高
        highTurnover: 6e8,
        useRank: true,
        useTheme: true,
        useFactorScore: true,
        factorThreshold: 65,
      },
      total: {
        maxRank: 12,
        minDays: 3,
        eliteRank: 4,
        minScore: 92,
        minTurnover: 2.5e9, // 成交额要求更高
        extremeChange: 14,
        useRank: true,
        useFactorScore: true,
        factorThreshold: 80,
      },
      emotion: {
        minTurnoverRate: 7,
        minAbsChange: 2,
        minScore: 58,
        useFactorScore: true,
        factorThreshold: 68,
      },
    },
  },

  // ========== 情绪驱动 ==========
  sentimentDriven: {
    id: 'sentimentDriven',
    name: '情绪驱动',
    icon: '🔥',
    description: '市场情绪优先，捕捉情绪龙头',
    category: 'sentiment',
    color: '#ff7f50',
    factors: {
      // 基础因子 - 降低权重
      change: { weight: 0.05, enabled: true, min: 0.03, max: 0.1 },
      turnoverRate: { weight: 0.05, enabled: true, min: 0.03, max: 0.1 },

      // 龙息因子 - 高权重
      [BREATH_FACTOR_IDS.PHASE]: { weight: 0.15, enabled: true, min: 0.08, max: 0.25 },
      [BREATH_FACTOR_IDS.ZT_COUNT]: { weight: 0.12, enabled: true, min: 0.05, max: 0.2 },
      [BREATH_FACTOR_IDS.DT_COUNT]: { weight: 0.08, enabled: true, min: 0.03, max: 0.15 },
      [BREATH_FACTOR_IDS.ZHABAN_RATE]: { weight: 0.1, enabled: true, min: 0.05, max: 0.2 },
      [BREATH_FACTOR_IDS.FENGBAN_RATE]: { weight: 0.08, enabled: true, min: 0.03, max: 0.15 },
      [BREATH_FACTOR_IDS.PASS_RATE]: { weight: 0.12, enabled: true, min: 0.05, max: 0.2 },
      [BREATH_FACTOR_IDS.MAX_DAYS]: { weight: 0.1, enabled: true, min: 0.05, max: 0.2 },
      [BREATH_FACTOR_IDS.UP_DOWN_RATIO]: { weight: 0.08, enabled: true, min: 0.03, max: 0.15 },
      [BREATH_FACTOR_IDS.EMOTION_VALUE]: { weight: 0.08, enabled: true, min: 0.03, max: 0.15 },
      [BREATH_FACTOR_IDS.MARKET_SCORE]: { weight: 0.08, enabled: true, min: 0.03, max: 0.15 },

      // 逆势因子
      contrarian: { weight: 0.08, enabled: true, min: 0.03, max: 0.15 },
    },
    leaderThresholds: {
      continuous: {
        minChange: 9.5,
        minDays: 2,
        maxRank: 35,
        minScore: 68,
        useRank: true,
        useFactorScore: true,
        factorThreshold: 75,
      },
      middle: {
        minMV: 25e8, // 资金驱动更喜欢大市值
        maxChange: 7,
        minTurnoverRate: 0.8,
        maxTurnoverRate: 12,
        maxRank: 45,
        useRank: true,
        useFactorScore: true,
        factorThreshold: 75,
      },
      sector: {
        maxRank: 45,
        minChange: 3,
        minScore: 68,
        minThemeHeat: 70,
        minTurnover: 1.2e8, // 成交额要求更高
        highTurnover: 6e8,
        useRank: true,
        useTheme: true,
        useFactorScore: true,
        factorThreshold: 65,
      },
      total: {
        maxRank: 12,
        minDays: 3,
        eliteRank: 4,
        minScore: 92,
        minTurnover: 2.5e9, // 成交额要求更高
        extremeChange: 14,
        useRank: true,
        useFactorScore: true,
        factorThreshold: 80,
      },
      emotion: {
        minTurnoverRate: 7,
        minAbsChange: 2,
        minScore: 58,
        useFactorScore: true,
        factorThreshold: 68,
      },
    },
  },

  // ========== 龙息驱动（新增）==========
  breathDriven: {
    id: 'breathDriven',
    name: '龙息驱动',
    icon: '🌬️',
    description: '以市场情绪为核心，捕捉情绪驱动的龙头',
    category: 'sentiment',
    color: '#ff9f7f',
    factors: {
      // 龙息因子 - 极高权重
      [BREATH_FACTOR_IDS.PHASE]: { weight: 0.2, enabled: true, min: 0.1, max: 0.3 },
      [BREATH_FACTOR_IDS.ZT_COUNT]: { weight: 0.15, enabled: true, min: 0.08, max: 0.25 },
      [BREATH_FACTOR_IDS.DT_COUNT]: { weight: 0.1, enabled: true, min: 0.05, max: 0.2 },
      [BREATH_FACTOR_IDS.ZHABAN_RATE]: { weight: 0.1, enabled: true, min: 0.05, max: 0.2 },
      [BREATH_FACTOR_IDS.FENGBAN_RATE]: { weight: 0.1, enabled: true, min: 0.05, max: 0.2 },
      [BREATH_FACTOR_IDS.PASS_RATE]: { weight: 0.15, enabled: true, min: 0.08, max: 0.25 },
      [BREATH_FACTOR_IDS.MAX_DAYS]: { weight: 0.15, enabled: true, min: 0.08, max: 0.25 },
      [BREATH_FACTOR_IDS.UP_DOWN_RATIO]: { weight: 0.08, enabled: true, min: 0.03, max: 0.15 },
      [BREATH_FACTOR_IDS.EMOTION_VALUE]: { weight: 0.08, enabled: true, min: 0.03, max: 0.15 },
      [BREATH_FACTOR_IDS.MARKET_SCORE]: { weight: 0.08, enabled: true, min: 0.03, max: 0.15 },

      // 逆势因子
      contrarian: { weight: 0.15, enabled: true, min: 0.08, max: 0.25 },

      // 其他因子 - 降低权重
      compRank: { weight: 0.05, enabled: true, min: 0.02, max: 0.1 },
      zlje: { weight: 0.05, enabled: true, min: 0.02, max: 0.1 },
      change: { weight: 0.04, enabled: true, min: 0.02, max: 0.08 },
      turnover: { weight: 0.03, enabled: true, min: 0.01, max: 0.06 },
      marketCap: { weight: 0.02, enabled: true, min: 0.01, max: 0.05 },
    },
    leaderThresholds: {
      continuous: {
        minChange: 9.5,
        minDays: 2,
        maxRank: 35,
        minScore: 68,
        useRank: true,
        useFactorScore: true,
        factorThreshold: 75,
      },
      middle: {
        minMV: 25e8, // 资金驱动更喜欢大市值
        maxChange: 7,
        minTurnoverRate: 0.8,
        maxTurnoverRate: 12,
        maxRank: 45,
        useRank: true,
        useFactorScore: true,
        factorThreshold: 75,
      },
      sector: {
        maxRank: 45,
        minChange: 3,
        minScore: 68,
        minThemeHeat: 70,
        minTurnover: 1.2e8, // 成交额要求更高
        highTurnover: 6e8,
        useRank: true,
        useTheme: true,
        useFactorScore: true,
        factorThreshold: 65,
      },
      total: {
        maxRank: 12,
        minDays: 3,
        eliteRank: 4,
        minScore: 92,
        minTurnover: 2.5e9, // 成交额要求更高
        extremeChange: 14,
        useRank: true,
        useFactorScore: true,
        factorThreshold: 80,
      },
      emotion: {
        minTurnoverRate: 7,
        minAbsChange: 2,
        minScore: 58,
        useFactorScore: true,
        factorThreshold: 68,
      },
    },
  },

  // ========== 机器学习（动态权重）==========
  ml: {
    id: 'ml',
    name: '机器学习',
    icon: '🤖',
    description: '动态权重，自适应优化，包含所有因子',
    category: 'ml',
    color: '#9b59b6',
    factors: {
      // 基础因子
      compRank: { weight: 'dynamic', enabled: true, baseWeight: 0.06, min: 0.03, max: 0.12 },
      marketCap: { weight: 'dynamic', enabled: true, baseWeight: 0.04, min: 0.02, max: 0.08 },
      change: { weight: 'dynamic', enabled: true, baseWeight: 0.05, min: 0.03, max: 0.1 },
      turnover: { weight: 'dynamic', enabled: true, baseWeight: 0.04, min: 0.02, max: 0.08 },
      turnoverRate: { weight: 'dynamic', enabled: true, baseWeight: 0.04, min: 0.02, max: 0.08 },
      zlje: { weight: 'dynamic', enabled: true, baseWeight: 0.06, min: 0.03, max: 0.12 },

      // 题材因子
      sectorEffect: { weight: 'dynamic', enabled: true, baseWeight: 0.06, min: 0.03, max: 0.12 },
      themeHeat: { weight: 'dynamic', enabled: true, baseWeight: 0.06, min: 0.03, max: 0.12 },
      themeMomentum: { weight: 'dynamic', enabled: true, baseWeight: 0.05, min: 0.03, max: 0.1 },

      // 龙息因子 - 全部启用
      [BREATH_FACTOR_IDS.PHASE]: {
        weight: 'dynamic',
        enabled: true,
        baseWeight: 0.08,
        min: 0.04,
        max: 0.15,
      },
      [BREATH_FACTOR_IDS.ZT_COUNT]: {
        weight: 'dynamic',
        enabled: true,
        baseWeight: 0.06,
        min: 0.03,
        max: 0.12,
      },
      [BREATH_FACTOR_IDS.DT_COUNT]: {
        weight: 'dynamic',
        enabled: true,
        baseWeight: 0.05,
        min: 0.02,
        max: 0.1,
      },
      [BREATH_FACTOR_IDS.ZHABAN_RATE]: {
        weight: 'dynamic',
        enabled: true,
        baseWeight: 0.05,
        min: 0.02,
        max: 0.1,
      },
      [BREATH_FACTOR_IDS.FENGBAN_RATE]: {
        weight: 'dynamic',
        enabled: true,
        baseWeight: 0.04,
        min: 0.02,
        max: 0.08,
      },
      [BREATH_FACTOR_IDS.PASS_RATE]: {
        weight: 'dynamic',
        enabled: true,
        baseWeight: 0.06,
        min: 0.03,
        max: 0.12,
      },
      [BREATH_FACTOR_IDS.MAX_DAYS]: {
        weight: 'dynamic',
        enabled: true,
        baseWeight: 0.07,
        min: 0.03,
        max: 0.14,
      },
      [BREATH_FACTOR_IDS.UP_DOWN_RATIO]: {
        weight: 'dynamic',
        enabled: true,
        baseWeight: 0.04,
        min: 0.02,
        max: 0.08,
      },
      [BREATH_FACTOR_IDS.EMOTION_VALUE]: {
        weight: 'dynamic',
        enabled: true,
        baseWeight: 0.04,
        min: 0.02,
        max: 0.08,
      },
      [BREATH_FACTOR_IDS.MARKET_SCORE]: {
        weight: 'dynamic',
        enabled: true,
        baseWeight: 0.04,
        min: 0.02,
        max: 0.08,
      },

      // 逆势因子
      contrarian: { weight: 'dynamic', enabled: true, baseWeight: 0.06, min: 0.03, max: 0.12 },
    },

    adaptive: true,
    learningRate: 0.05,

    leaderThresholds: {
      continuous: {
        minChange: 9.5,
        minDays: 2,
        maxRank: 35,
        minScore: 68,
        useRank: true,
        useFactorScore: true,
        factorThreshold: 75,
      },
      middle: {
        minMV: 25e8,
        maxChange: 7,
        minTurnoverRate: 0.8,
        maxTurnoverRate: 12,
        maxRank: 45,
        useRank: true,
        useFactorScore: true,
        factorThreshold: 75,
      },
      sector: {
        maxRank: 45,
        minChange: 3,
        minScore: 68,
        minThemeHeat: 70,
        minTurnover: 1.2e8,
        highTurnover: 6e8,
        useRank: true,
        useTheme: true,
        useFactorScore: true,
        factorThreshold: 65,
      },
      total: {
        maxRank: 12,
        minDays: 3,
        eliteRank: 4,
        minScore: 92,
        minTurnover: 2.5e9,
        extremeChange: 14,
        useRank: true,
        useFactorScore: true,
        factorThreshold: 80,
      },
      emotion: {
        minTurnoverRate: 7,
        minAbsChange: 2,
        minScore: 58,
        useFactorScore: true,
        factorThreshold: 68,
      },
    },
  },
}
