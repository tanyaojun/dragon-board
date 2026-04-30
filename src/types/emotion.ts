// src/types/emotion.ts
// ========== 统一情绪中心配置 ==========

/**
 * 统一情绪阶段。
 *
 * 当前系统只保留五阶段标准：
 * 冰点 / 启动 / 发酵 / 高潮 / 退潮
 *
 * DragonBreathAnalyzer 与 HotListSentimentAnalyzer 都应输出这套阶段。
 * 阶段必须由规则证据判定；旧 overall 字段只作为历史数据兼容，不参与阶段判断和展示。
 */
export type UnifiedEmotionStage = '冰点' | '启动' | '发酵' | '高潮' | '退潮'
export type UnifiedEmotionStageValue = 'ice' | 'start' | 'ferment' | 'climax' | 'retreat'
export type EmotionCycleStage = UnifiedEmotionStage

export interface EmotionRuleDescriptor {
  priority: number
  intent: string
  evidence: readonly string[]
}

export const EMOTION_STAGE_RULES: Record<UnifiedEmotionStage, EmotionRuleDescriptor> = {
  退潮: {
    priority: 1,
    intent: '风险优先，先判断是否需要降仓或暂停进攻。',
    evidence: ['资金背离/转弱增加', '炸板率抬升', '晋级率走弱', '昨日强票承接失败'],
  },
  高潮: {
    priority: 2,
    intent: '强势识别但不鼓励追高，重点管理高位兑现风险。',
    evidence: ['涨停或高涨幅集中', '高位拥挤增加', '成交额和换手显著放大', '风险尚未失控'],
  },
  发酵: {
    priority: 3,
    intent: '主线扩散和资金承接形成合力，适合围绕主线做精选跟踪。',
    evidence: ['强资金扩散', '点火和主升状态增加', '昨日强票留榜较好', '上涨承接优于下跌承接'],
  },
  启动: {
    priority: 4,
    intent: '情绪开始修复，轻仓试错，等待持续性确认。',
    evidence: ['上涨比例改善', '跌停/风险减少', '新入和点火线索增加', '热榜池开始扩张'],
  },
  冰点: {
    priority: 5,
    intent: '机会稀少，等待修复信号，不主动提高交易频率。',
    evidence: ['上涨比例低', '机会状态少', '热榜池收缩', '亏钱效应或风险状态占优'],
  },
}

export const EMOTION_CYCLE_STAGE_CONFIG: Record<
  EmotionCycleStage,
  { summary: string; confidenceBase: number }
> = {
  冰点: {
    summary: '机会稀少，风险或弱承接占优，优先控制仓位和交易频率。',
    confidenceBase: 56,
  },
  启动: {
    summary: '情绪开始修复，新增线索和点火机会增多，但持续性仍待确认。',
    confidenceBase: 58,
  },
  发酵: {
    summary: '强资金、点火和主线扩散形成合力，交易情绪处于扩散阶段。',
    confidenceBase: 62,
  },
  高潮: {
    summary: '前排强度和资金承接较强，但拥挤明显，适合强势识别，不宜盲目追高。',
    confidenceBase: 64,
  },
  退潮: {
    summary: '风险状态升温或强票承接走弱，交易情绪进入防守优先阶段。',
    confidenceBase: 64,
  },
}

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

export const EMOTION_PHASES = {
  ICE: {
    id: 'ice',
    name: '冰点',
    value: 'ice',
    color: '#7f8c8d',
    gradient: 'linear-gradient(135deg, #1e2b3a, #2c3e50)',
    icon: '❄️',
    desc: '市场承接弱，机会稀少，短线交易以等待修复为主。',
    suggestion: '控制仓位，等待风险释放后的启动信号',
    features: ['机会状态少', '上涨比例低', '跌停或风险状态占优', '主线不清晰'],
    thresholdMultiplier: {
      totalLeader: 0.85,
      continuousLeader: 0.8,
      sectorLeader: 0.75,
      middleLeader: 0.7,
      emotionLeader: 0.7,
      themeHeat: 0.55,
      themeMomentum: 0.6,
      rotationSpeed: 0.7,
    },
  },
  START: {
    id: 'start',
    name: '启动',
    value: 'start',
    color: '#3498db',
    gradient: 'linear-gradient(135deg, #1e3c5a, #2980b9)',
    icon: '🌱',
    desc: '情绪开始修复，新增线索和点火标的增加，但持续性仍需确认。',
    suggestion: '轻仓试错，关注率先修复并能留强的方向',
    features: ['跌停减少', '新入和点火增多', '上涨比例改善', '主线开始试探'],
    thresholdMultiplier: {
      totalLeader: 1.0,
      continuousLeader: 1.0,
      sectorLeader: 1.0,
      middleLeader: 1.0,
      emotionLeader: 1.0,
      themeHeat: 0.95,
      themeMomentum: 1.0,
      rotationSpeed: 1.0,
    },
  },
  FERMENT: {
    id: 'ferment',
    name: '发酵',
    value: 'ferment',
    color: '#f39c12',
    gradient: 'linear-gradient(135deg, #b45f06, #f39c12)',
    icon: '🔥',
    desc: '主线扩散，资金承接改善，赚钱效应开始向更多标的传导。',
    suggestion: '围绕主线精选参与，重点看资金承接和持续性',
    features: ['强资金扩散', '点火和主升增加', '连板梯队成型', '昨日强票留榜较好'],
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
  CLIMAX: {
    id: 'climax',
    name: '高潮',
    value: 'climax',
    color: '#e74c3c',
    gradient: 'linear-gradient(135deg, #a52613, #e74c3c)',
    icon: '🌋',
    desc: '前排强度很高，但拥挤和分化风险同步上升。',
    suggestion: '持有强势核心为主，谨慎追高，重点防分歧兑现',
    features: ['批量高涨幅', '高位拥挤增加', '成交和换手放大', '风险尚未失控'],
    thresholdMultiplier: {
      totalLeader: 1.15,
      continuousLeader: 1.15,
      sectorLeader: 1.1,
      middleLeader: 1.05,
      emotionLeader: 1.05,
      themeHeat: 1.28,
      themeMomentum: 1.25,
      rotationSpeed: 1.25,
    },
  },
  RETREAT: {
    id: 'retreat',
    name: '退潮',
    value: 'retreat',
    color: '#9b59b6',
    gradient: 'linear-gradient(135deg, #4a235a, #8e44ad)',
    icon: '⚖️',
    desc: '风险状态升温或前排承接失败，交易优先级转向防守。',
    suggestion: '降低进攻仓位，规避高位弱承接和资金背离标的',
    features: ['资金背离增加', '转弱预警增加', '炸板率抬升', '昨日强票承接失败'],
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

export type EmotionPhaseId = keyof typeof EMOTION_PHASES
export type EmotionPhase = (typeof EMOTION_PHASES)[EmotionPhaseId]

export const EMOTION_PHASE_LIST = Object.values(EMOTION_PHASES)

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

export function getEmotionPhaseByStage(stage: UnifiedEmotionStage | UnifiedEmotionStageValue): EmotionPhase {
  return EMOTION_PHASE_BY_NAME[stage] || EMOTION_PHASE_BY_VALUE[stage] || EMOTION_PHASES.START
}

export function getThresholdMultiplier(phaseName: string): ThresholdMultiplier {
  const phase = EMOTION_PHASE_BY_NAME[phaseName] || EMOTION_PHASE_BY_VALUE[phaseName]
  return phase?.thresholdMultiplier || EMOTION_PHASES.START.thresholdMultiplier
}

export function getPhaseSuggestion(phaseName: string): string {
  const phase = EMOTION_PHASE_BY_NAME[phaseName] || EMOTION_PHASE_BY_VALUE[phaseName]
  return phase?.suggestion || EMOTION_PHASES.START.suggestion
}

export function getPhaseIcon(phaseName: string): string {
  const phase = EMOTION_PHASE_BY_NAME[phaseName] || EMOTION_PHASE_BY_VALUE[phaseName]
  return phase?.icon || EMOTION_PHASES.START.icon
}

export function getPhaseColor(phaseName: string): string {
  const phase = EMOTION_PHASE_BY_NAME[phaseName] || EMOTION_PHASE_BY_VALUE[phaseName]
  return phase?.color || EMOTION_PHASES.START.color
}

export function getPhaseGradient(phaseName: string): string {
  const phase = EMOTION_PHASE_BY_NAME[phaseName] || EMOTION_PHASE_BY_VALUE[phaseName]
  return phase?.gradient || EMOTION_PHASES.START.gradient
}

export function getPhaseFeatures(phaseName: string): readonly string[] {
  const phase = EMOTION_PHASE_BY_NAME[phaseName] || EMOTION_PHASE_BY_VALUE[phaseName]
  return phase?.features || EMOTION_PHASES.START.features
}

export function getEmotionStageRule(stage: UnifiedEmotionStage): EmotionRuleDescriptor {
  return EMOTION_STAGE_RULES[stage]
}

export function getEmotionCycleStageSummary(stage: EmotionCycleStage): string {
  return EMOTION_CYCLE_STAGE_CONFIG[stage]?.summary || EMOTION_CYCLE_STAGE_CONFIG.启动.summary
}

// ========== 情绪因子类型定义 ==========

export interface EmotionFactor {
  id: string
  name: string
  description: string
  unit?: string
  getValue: (marketData: any) => number | null
}

export interface EmotionFactorConfig {
  factors: Record<string, EmotionFactor>
  reference?: Record<string, any>
}

export interface EmotionFactorConfigType {
  factors: Record<string, EmotionFactor>
}

export const EMOTION_IMPACT = {
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

  ALGORITHM: {
    FACTOR_ADJUSTMENTS: {
      冰点: {
        contrarian: 0.05,
        compRank: 0.02,
        breathDtCount: 0.03,
        themeHeat: -0.03,
        breathZtCount: -0.02,
        breathPassRate: -0.02,
        zlje: -0.02,
      },
      启动: {
        themeHeat: 0.02,
        compRank: 0.02,
        breathPassRate: 0.03,
        breathZtCount: 0.01,
        continuousDays: 0.01,
        zlje: 0.01,
        contrarian: -0.02,
      },
      发酵: {
        themeHeat: 0.03,
        themeMomentum: 0.03,
        continuousDays: 0.02,
        breathPassRate: 0.02,
        zlje: 0.02,
        breathZtCount: 0.01,
        compRank: -0.01,
      },
      高潮: {
        continuousDays: 0.04,
        breathZtCount: 0.02,
        breathPhase: 0.02,
        themeHeat: -0.02,
        themeMomentum: -0.02,
        zlje: -0.02,
        contrarian: -0.03,
      },
      退潮: {
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

export const UNIFIED_EMOTION = {
  PHASES: EMOTION_PHASES,
  PHASE_LIST: EMOTION_PHASE_LIST,
  PHASE_BY_NAME: EMOTION_PHASE_BY_NAME,
  PHASE_BY_VALUE: EMOTION_PHASE_BY_VALUE,
  STAGE_RULES: EMOTION_STAGE_RULES,
  IMPACT: EMOTION_IMPACT,
  getPhaseByStage: getEmotionPhaseByStage,
  getThresholdMultiplier,
  getPhaseSuggestion,
  getPhaseIcon,
  getPhaseColor,
  getPhaseGradient,
  getPhaseFeatures,
}

// ========== 情绪观察因子配置 ==========
// 这些因子只用于展示原始市场结构证据，不参与阶段打分。

export const EMOTION_FACTOR_CONFIG: EmotionFactorConfigType = {
  factors: {
    promotionRate: {
      id: 'promotionRate',
      name: '晋级率',
      description: '昨日涨停今日继续涨停的比例（加权平均）',
      unit: '%',
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
    },

    yesterdayZtAvgChange: {
      id: 'yesterdayZtAvgChange',
      name: '昨日涨停表现',
      description: '昨日涨停股今日平均涨幅',
      unit: '%',
      getValue: (marketData: any) => {
        const stats = marketData?.yesterdayLimitUpStats
        return stats?.avgChange ?? null
      },
    },

    ztCount: {
      id: 'ztCount',
      name: '涨停数',
      description: '当日涨停家数，反映市场进攻意愿',
      unit: '家',
      getValue: (marketData: any) => marketData?.ztCount ?? null,
    },

    dtCount: {
      id: 'dtCount',
      name: '跌停数',
      description: '当日跌停家数，反映市场风险',
      unit: '家',
      getValue: (marketData: any) => marketData?.dtCount ?? null,
    },

    zhabanRate: {
      id: 'zhabanRate',
      name: '炸板率',
      description: '炸板率越低，涨停质量越高',
      unit: '%',
      getValue: (marketData: any) => marketData?.zhaban?.rate ?? null,
    },

    maxContinuousDays: {
      id: 'maxContinuousDays',
      name: '连板高度',
      description: '市场最高连板天数',
      unit: '天',
      getValue: (marketData: any) => marketData?.maxContinuousDays ?? null,
    },

    upDownRatio: {
      id: 'upDownRatio',
      name: '涨跌比',
      description: '上涨家数与下跌家数的比值',
      unit: '倍',
      getValue: (marketData: any) => {
        const up = marketData?.upCount ?? 0
        const down = marketData?.downCount ?? 1
        return up / down
      },
    },

    volumeRatio: {
      id: 'volumeRatio',
      name: '量比',
      description: '今日成交量/昨日成交量',
      getValue: (marketData: any) => marketData?.volumeRatio ?? null,
    },

    tdxEmotion: {
      id: 'tdxEmotion',
      name: '通达信情绪',
      description: '通达信专业情绪指标',
      getValue: (marketData: any) => {
        const value = marketData?.emotionValue
        if (value === undefined || value === null) return null
        return value
      },
    },
  },
}
