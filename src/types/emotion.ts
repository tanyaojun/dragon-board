// src/types/emotion.ts
// ========== 统一情绪中心配置 ==========

/**
 * 情绪阶段定义 - 基于震荡市特征优化
 * 保持原有阶段数量不变，调整分数区间和thresholdMultiplier
 */
export const EMOTION_PHASES = {
  ICE: {
    id: 'ice',
    name: '冰点期',
    value: 'ice',
    scoreRange: { min: 0, max: 25 },
    score: 20,
    color: '#7f8c8d',
    gradient: 'linear-gradient(135deg, #1e2b3a, #2c3e50)',
    icon: '❄️',
    desc: '市场极度悲观，涨停稀少，跌停泛滥',
    suggestion: '空仓观望，等待情绪反转',
    features: ['涨停<25家', '跌停>15家', '连板高度≤2板', '炸板率>40%'],
    thresholdMultiplier: {
      totalLeader: 0.85,
      continuousLeader: 0.8,
      sectorLeader: 0.75,
      middleLeader: 0.7,
      emotionLeader: 0.7,
      themeHeat: 0.5,
      themeMomentum: 0.6,
      rotationSpeed: 0.7,
    },
  },
  DEPRESSED: {
    id: 'depressed',
    name: '低迷期',
    value: 'depressed',
    scoreRange: { min: 25, max: 40 },
    score: 32,
    color: '#7f8c8d',
    gradient: 'linear-gradient(135deg, #7f8c8d, #95a5a6)',
    icon: '🌧️',
    desc: '人气低迷，量能萎缩，涨停25-40家',
    suggestion: '多看少动，等待机会',
    features: ['涨停25-40家', '跌停8-15家', '连板高度2-3板', '炸板率35-45%'],
    thresholdMultiplier: {
      totalLeader: 0.9,
      continuousLeader: 0.85,
      sectorLeader: 0.8,
      middleLeader: 0.75,
      emotionLeader: 0.75,
      themeHeat: 0.6,
      themeMomentum: 0.7,
      rotationSpeed: 0.8,
    },
  },
  START: {
    id: 'start',
    name: '启动期',
    value: 'start',
    scoreRange: { min: 40, max: 52 },
    score: 46,
    color: '#3498db',
    gradient: 'linear-gradient(135deg, #1e3c5a, #2980b9)',
    icon: '🌱',
    desc: '情绪开始回暖，涨停35-50家，跌停减少',
    suggestion: '轻仓试错，关注率先反弹的板块',
    features: ['首板增多', '板块龙头萌芽', '跌停<8家', '题材开始发酵'],
    thresholdMultiplier: {
      totalLeader: 1.0,
      continuousLeader: 1.0,
      sectorLeader: 1.0,
      middleLeader: 1.0,
      emotionLeader: 1.0,
      themeHeat: 0.9,
      themeMomentum: 1.0,
      rotationSpeed: 1.0,
    },
  },
  OSCILLATION: {
    id: 'oscillation',
    name: '震荡期',
    value: 'oscillation',
    scoreRange: { min: 52, max: 64 },
    score: 58,
    color: '#95a5a6',
    gradient: 'linear-gradient(135deg, #2c3e50, #34495e)',
    icon: '⚖️',
    desc: '多空平衡，板块轮动，涨停40-60家',
    suggestion: '控制仓位，低吸为主，不追高',
    features: ['板块轮动', '情绪震荡', '涨停40-60家', '炸板率28-38%'],
    thresholdMultiplier: {
      totalLeader: 1.0,
      continuousLeader: 1.0,
      sectorLeader: 1.0,
      middleLeader: 1.0,
      emotionLeader: 1.0,
      themeHeat: 1.0,
      themeMomentum: 1.0,
      rotationSpeed: 1.0,
    },
  },
  STABLE: {
    id: 'stable',
    name: '平稳期',
    value: 'stable',
    scoreRange: { min: 64, max: 74 },
    score: 69,
    color: '#3498db',
    gradient: 'linear-gradient(135deg, #3498db, #5dade2)',
    icon: '🌊',
    desc: '情绪稳定，涨停50-70家，赚钱效应温和',
    suggestion: '低吸为主，波段操作',
    features: ['情绪稳定', '涨停50-70家', '跌停<5家', '主线清晰'],
    thresholdMultiplier: {
      totalLeader: 1.03,
      continuousLeader: 1.03,
      sectorLeader: 1.02,
      middleLeader: 1.0,
      emotionLeader: 1.0,
      themeHeat: 1.05,
      themeMomentum: 1.05,
      rotationSpeed: 1.05,
    },
  },
  FERMENT: {
    id: 'ferment',
    name: '发酵期',
    value: 'ferment',
    scoreRange: { min: 74, max: 82 },
    score: 78,
    color: '#f39c12',
    gradient: 'linear-gradient(135deg, #b45f06, #f39c12)',
    icon: '🔥',
    desc: '题材扩散，连板增加，涨停60-85家，赚钱效应显现',
    suggestion: '适度加仓，紧跟主线题材',
    features: ['连板梯队成型', '资金涌入', '涨停60-85家', '晋级率>20%'],
    thresholdMultiplier: {
      totalLeader: 1.08,
      continuousLeader: 1.08,
      sectorLeader: 1.05,
      middleLeader: 1.03,
      emotionLeader: 1.02,
      themeHeat: 1.15,
      themeMomentum: 1.15,
      rotationSpeed: 1.15,
    },
  },
  ACTIVE: {
    id: 'active',
    name: '活跃期',
    value: 'active',
    scoreRange: { min: 82, max: 89 },
    score: 85.5,
    color: '#ff7f50',
    gradient: 'linear-gradient(135deg, #ff7f50, #ffa07a)',
    icon: '⚡',
    desc: '题材活跃，涨停70-100家，情绪升温，连板高度4-6板',
    suggestion: '积极参与，紧跟热点',
    features: ['涨停70-100家', '连板高度4-6板', '晋级率25-35%', '炸板率<28%'],
    thresholdMultiplier: {
      totalLeader: 1.12,
      continuousLeader: 1.12,
      sectorLeader: 1.08,
      middleLeader: 1.05,
      emotionLeader: 1.05,
      themeHeat: 1.25,
      themeMomentum: 1.25,
      rotationSpeed: 1.25,
    },
  },
  CLIMAX: {
    id: 'climax',
    name: '高潮期',
    value: 'climax',
    scoreRange: { min: 89, max: 100 },
    score: 94,
    color: '#e74c3c',
    gradient: 'linear-gradient(135deg, #a52613, #e74c3c)',
    icon: '🌋',
    desc: '情绪亢奋，涨停>90家，连板高度≥6板，批量涨停',
    suggestion: '持股为主，注意分化风险，不轻易开新仓',
    features: ['涨停>90家', '连板高度≥6板', '晋级率>35%', '炸板率<25%', '注意风险'],
    thresholdMultiplier: {
      totalLeader: 1.18,
      continuousLeader: 1.18,
      sectorLeader: 1.12,
      middleLeader: 1.08,
      emotionLeader: 1.08,
      themeHeat: 1.35,
      themeMomentum: 1.35,
      rotationSpeed: 1.35,
    },
  },
  RECESSION: {
    id: 'recession',
    name: '退潮期',
    value: 'recession',
    scoreRange: { min: 0, max: 0 }, // 不通过分数判断
    score: 70,
    color: '#9b59b6',
    gradient: 'linear-gradient(135deg, #4a235a, #8e44ad)',
    icon: '🌊',
    desc: '高位分歧，亏钱效应，炸板率升高，高位股补跌',
    suggestion: '减仓防守，规避高位股，等待企稳',
    features: ['高位分歧', '炸板率>30%', '晋级率下降', '亏钱效应', '减仓防守'],
    thresholdMultiplier: {
      totalLeader: 0.92,
      continuousLeader: 0.88,
      sectorLeader: 0.85,
      middleLeader: 0.82,
      emotionLeader: 0.78,
      themeHeat: 0.7,
      themeMomentum: 0.65,
      rotationSpeed: 0.75,
    },
  },
} as const

// ========== 导出类型 ==========
export type EmotionPhaseId = keyof typeof EMOTION_PHASES
export type EmotionPhase = (typeof EMOTION_PHASES)[EmotionPhaseId]

// 修复：将 ThresholdMultiplier 定义为通用类型而非具体字面量类型
export type ThresholdMultiplier = {
  readonly totalLeader: number
  readonly continuousLeader: number
  readonly sectorLeader: number
  readonly middleLeader: number
  readonly emotionLeader: number
  readonly themeHeat: number
  readonly themeMomentum: number
  readonly rotationSpeed: number
}

// ========== 导出数组 ==========
export const EMOTION_PHASE_LIST = Object.values(EMOTION_PHASES)

// ========== 导出映射 ==========
export const EMOTION_PHASE_BY_NAME = EMOTION_PHASE_LIST.reduce(
  (acc, phase) => {
    acc[phase.name] = phase
    return acc
  },
  {} as Record<string, EmotionPhase>,
)

export const EMOTION_PHASE_BY_VALUE = EMOTION_PHASE_LIST.reduce(
  (acc, phase) => {
    acc[phase.value] = phase
    return acc
  },
  {} as Record<string, EmotionPhase>,
)

// ========== 情绪因子类型定义 ==========

/**
 * 情绪因子接口
 */
export interface EmotionFactor {
  id: string
  name: string
  weight: number
  maxScore: number
  description: string
  unit?: string
  getValue: (marketData: any) => number | null
  getScore: (value: number) => number
}

/**
 * 情绪分数配置接口
 */
export interface EmotionScoreConfig {
  factors: Record<string, EmotionFactor>
  reference?: Record<string, any>
}

// ========== 工具函数 ==========
/**
 * 根据分数获取情绪阶段
 * 退潮期需要单独判断，不通过分数
 */
export function getEmotionPhaseByScore(score: number): EmotionPhase {
  if (score < 0) return EMOTION_PHASES.ICE
  if (score >= 100) return EMOTION_PHASES.CLIMAX

  for (const phase of EMOTION_PHASE_LIST) {
    if (phase.id === 'recession') continue
    if (score >= phase.scoreRange.min && score < phase.scoreRange.max) {
      return phase
    }
  }

  return EMOTION_PHASES.OSCILLATION
}

/**
 * 获取指定阶段的阈值乘数
 */
export function getThresholdMultiplier(phaseName: string): ThresholdMultiplier {
  const phase = EMOTION_PHASE_BY_NAME[phaseName]
  return phase?.thresholdMultiplier || EMOTION_PHASES.OSCILLATION.thresholdMultiplier
}

/**
 * 根据当前分数获取阈值乘数
 */
export function getThresholdMultiplierByScore(score: number): ThresholdMultiplier {
  const phase = getEmotionPhaseByScore(score)
  return phase.thresholdMultiplier
}

/**
 * 获取阶段建议
 */
export function getPhaseSuggestion(phaseName: string): string {
  const phase = EMOTION_PHASE_BY_NAME[phaseName]
  return phase?.suggestion || '观望为主'
}

/**
 * 获取阶段图标
 */
export function getPhaseIcon(phaseName: string): string {
  const phase = EMOTION_PHASE_BY_NAME[phaseName]
  return phase?.icon || '🌬️'
}

/**
 * 获取阶段颜色
 */
export function getPhaseColor(phaseName: string): string {
  const phase = EMOTION_PHASE_BY_NAME[phaseName]
  return phase?.color || '#95a5a6'
}

/**
 * 获取阶段渐变
 */
export function getPhaseGradient(phaseName: string): string {
  const phase = EMOTION_PHASE_BY_NAME[phaseName]
  return phase?.gradient || 'linear-gradient(135deg, #2c3e50, #34495e)'
}

/**
 * 获取阶段特征
 */
export function getPhaseFeatures(phaseName: string): readonly string[] {
  const phase = EMOTION_PHASE_BY_NAME[phaseName]
  return phase?.features || []
}

// ========== 统一情绪影响配置（兼容旧代码） ==========
export const EMOTION_IMPACT = {
  // ===== 龙头分析相关 =====
  DRAGON: {
    THRESHOLD_MULTIPLIERS: EMOTION_PHASE_LIST.reduce(
      (acc, phase) => {
        acc[phase.name] = {
          totalLeader: phase.thresholdMultiplier.totalLeader,
          continuousLeader: phase.thresholdMultiplier.continuousLeader,
          sectorLeader: phase.thresholdMultiplier.sectorLeader,
          middleLeader: phase.thresholdMultiplier.middleLeader,
          emotionLeader: phase.thresholdMultiplier.emotionLeader,
        }
        return acc
      },
      {} as Record<string, any>,
    ),
  },

  // ===== 题材分析相关 =====
  THEME: {
    HEAT_MULTIPLIERS: EMOTION_PHASE_LIST.reduce(
      (acc, phase) => {
        acc[phase.name] = phase.thresholdMultiplier.themeHeat
        return acc
      },
      {} as Record<string, number>,
    ),
    MOMENTUM_IMPACT: EMOTION_PHASE_LIST.reduce(
      (acc, phase) => {
        acc[phase.name] = phase.thresholdMultiplier.themeMomentum
        return acc
      },
      {} as Record<string, number>,
    ),
    ROTATION_SPEED: EMOTION_PHASE_LIST.reduce(
      (acc, phase) => {
        acc[phase.name] = phase.thresholdMultiplier.rotationSpeed
        return acc
      },
      {} as Record<string, number>,
    ),
    ZT_BONUS: 5,
    ZHABAN_PENALTY: 0.005,
    FACTOR_WEIGHTS: {
      ztCount: 0.4,
      leaderCount: 0.3,
      momentum: 0.2,
      correlation: 0.1,
    },
  },

  // ===== 算法中心相关 =====
  ALGORITHM: {
    FACTOR_ADJUSTMENTS: {
      冰点期: {
        contrarian: 0.05,
        compRank: 0.02,
        breathDtCount: 0.03,
        themeHeat: -0.03,
        breathZtCount: -0.02,
        breathPassRate: -0.02,
        zlje: -0.02,
      },
      低迷期: {
        contrarian: 0.03,
        breathDtCount: 0.02,
        compRank: 0.01,
        themeHeat: -0.02,
        breathZtCount: -0.01,
        breathPassRate: -0.01,
      },
      启动期: {
        themeHeat: 0.02,
        compRank: 0.02,
        breathPassRate: 0.03,
        breathZtCount: 0.01,
        continuousDays: 0.01,
        zlje: 0.01,
        contrarian: -0.02,
      },
      震荡期: {
        compRank: 0.01,
        themeHeat: 0.01,
        breathPassRate: 0.01,
        breathZtCount: 0.01,
      },
      平稳期: {
        compRank: 0.02,
        themeHeat: 0.01,
        turnover: 0.02,
        zlje: 0.01,
        continuousDays: 0.01,
      },
      发酵期: {
        themeHeat: 0.03,
        themeMomentum: 0.03,
        continuousDays: 0.02,
        breathPassRate: 0.02,
        zlje: 0.02,
        breathZtCount: 0.01,
        compRank: -0.01,
      },
      活跃期: {
        themeHeat: 0.02,
        themeMomentum: 0.02,
        continuousDays: 0.03,
        breathZtCount: 0.02,
        breathPassRate: 0.02,
        zlje: 0.01,
        turnover: 0.01,
        compRank: -0.02,
      },
      高潮期: {
        continuousDays: 0.04,
        breathZtCount: 0.02,
        breathPhase: 0.02,
        themeHeat: -0.02,
        themeMomentum: -0.02,
        zlje: -0.02,
        contrarian: -0.03,
      },
      退潮期: {
        breathDtCount: 0.04,
        breathZhabanRate: 0.03,
        contrarian: 0.02,
        continuousDays: -0.03,
        themeHeat: -0.02,
        themeMomentum: -0.02,
        zlje: -0.03,
        breathPassRate: -0.02,
      },
    },
  },
} as const

// 导出一个统一的情绪配置对象（完全兼容旧代码）
export const UNIFIED_EMOTION = {
  PHASES: EMOTION_PHASES,
  PHASE_LIST: EMOTION_PHASE_LIST,
  PHASE_BY_NAME: EMOTION_PHASE_BY_NAME,
  PHASE_BY_VALUE: EMOTION_PHASE_BY_VALUE,
  IMPACT: EMOTION_IMPACT,
  getPhaseByScore: getEmotionPhaseByScore,
  getThresholdMultiplier,
  getThresholdMultiplierByScore,
  getPhaseSuggestion,
  getPhaseIcon,
  getPhaseColor,
  getPhaseGradient,
  getPhaseFeatures,
}

// ========== 情绪分数配置 ==========

/**
 * 情绪分数配置接口
 */
export interface EmotionScoreConfigType {
  factors: Record<string, EmotionFactor>
}

export const EMOTION_SCORE_CONFIG: EmotionScoreConfigType = {
  factors: {
    promotionRate: {
      id: 'promotionRate',
      name: '晋级率',
      weight: 11, // 原12 → 11
      maxScore: 10,
      description: '昨日涨停今日继续涨停的比例（加权平均）',
      getValue: (marketData: any) => {
        const passRate = marketData?.passRate
        if (!passRate) return null

        let totalWeight = 0
        let totalRate = 0

        if (passRate.to2 !== undefined) {
          totalRate += passRate.to2 * 1
          totalWeight += 1
        }
        if (passRate.to3 !== undefined) {
          totalRate += passRate.to3 * 2
          totalWeight += 2
        }
        if (passRate.to4 !== undefined) {
          totalRate += passRate.to4 * 3
          totalWeight += 3
        }

        return totalWeight > 0 ? totalRate / totalWeight : null
      },
      getScore: (value: number) => {
        if (value >= 28) return 10
        if (value >= 20) return 8
        if (value >= 12) return 6
        if (value >= 6) return 4
        return 2
      },
    },

    yesterdayZtAvgChange: {
      id: 'yesterdayZtAvgChange',
      name: '昨日涨停表现',
      weight: 12,
      maxScore: 10,
      description: '昨日涨停股今日平均涨幅',
      getValue: (marketData: any) => {
        const stats = marketData?.yesterdayLimitUpStats
        return stats?.avgChange ?? null
      },
      getScore: (value: number) => {
        if (value >= 5) return 10
        if (value >= 3) return 8
        if (value >= 1.5) return 6
        if (value >= 0) return 4
        return 2
      },
    },

    ztCount: {
      id: 'ztCount',
      name: '涨停数',
      weight: 9,
      maxScore: 10,
      description: '当日涨停家数，反映市场进攻意愿',
      getValue: (marketData: any) => marketData?.ztCount ?? null,
      getScore: (value: number) => {
        if (value >= 80) return 10
        if (value >= 55) return 8
        if (value >= 40) return 6
        if (value >= 25) return 4
        return 2
      },
    },

    dtCount: {
      id: 'dtCount',
      name: '跌停数',
      weight: 13,
      maxScore: 10,
      description: '当日跌停家数，反映市场风险',
      getValue: (marketData: any) => marketData?.dtCount ?? null,
      getScore: (value: number) => {
        if (value === 0) return 10
        if (value <= 3) return 8
        if (value <= 8) return 6
        if (value <= 15) return 4
        return 0
      },
    },

    zhabanRate: {
      id: 'zhabanRate',
      name: '炸板率',
      weight: 12, // 原12 → 12（保持不变）
      maxScore: 10,
      description: '炸板率越低，涨停质量越高',
      getValue: (marketData: any) => marketData?.zhaban?.rate ?? null,
      getScore: (value: number) => {
        if (value <= 18) return 10
        if (value <= 25) return 8
        if (value <= 32) return 6
        if (value <= 40) return 4
        return 2
      },
    },

    maxContinuousDays: {
      id: 'maxContinuousDays',
      name: '连板高度',
      weight: 9, // 原10 → 9
      maxScore: 10,
      description: '市场最高连板天数',
      getValue: (marketData: any) => marketData?.maxContinuousDays ?? null,
      getScore: (value: number) => {
        if (value >= 7) return 10
        if (value >= 5) return 8
        if (value >= 3) return 6
        if (value >= 2) return 4
        return 2
      },
    },

    upDownRatio: {
      id: 'upDownRatio',
      name: '涨跌比',
      weight: 12,
      maxScore: 10,
      description: '上涨家数与下跌家数的比值',
      getValue: (marketData: any) => {
        const up = marketData?.upCount ?? 0
        const down = marketData?.downCount ?? 1
        return up / down
      },
      getScore: (value: number) => {
        if (value >= 2.5) return 10
        if (value >= 1.8) return 8
        if (value >= 1.2) return 6
        if (value >= 0.8) return 4
        return 2
      },
    },

    volumeRatio: {
      id: 'volumeRatio',
      name: '量比',
      weight: 8,
      maxScore: 10,
      description: '今日成交量/昨日成交量',
      getValue: (marketData: any) => marketData?.volumeRatio ?? null,
      getScore: (value: number) => {
        if (value >= 1.3) return 10
        if (value >= 1.1) return 8
        if (value >= 0.95) return 6
        if (value >= 0.8) return 4
        return 2
      },
    },

    tdxEmotion: {
      id: 'tdxEmotion',
      name: '通达信情绪',
      weight: 14,
      maxScore: 10,
      description: '通达信专业情绪指标',
      getValue: (marketData: any) => {
        const value = marketData?.emotionValue
        if (value === undefined || value === null) return null
        return value
      },
      getScore: (value: number) => {
        // 改为10分满分
        return Math.round(value * 10)
      },
    },
  },
}

// 验证权重总和
const totalWeight = Object.values(EMOTION_SCORE_CONFIG.factors).reduce(
  (sum, f) => sum + f.weight,
  0,
)
if (Math.abs(totalWeight - 100) > 0.01) {
  console.warn('[emotion] 情绪因子权重总和不为100:', totalWeight)
}

// 验证分数区间连续性
const phases = EMOTION_PHASE_LIST.filter((p) => p.id !== 'recession')
for (let i = 0; i < phases.length - 1; i++) {
  if (phases[i].scoreRange.max !== phases[i + 1].scoreRange.min) {
    console.warn(
      `[emotion] 分数区间不连续: ${phases[i].name}.max=${phases[i].scoreRange.max}, ${phases[i + 1].name}.min=${phases[i + 1].scoreRange.min}`,
    )
  }
}
