import type {
  CandidateTier,
  MarketRegimeAnalysis,
  RankTrendAnalysisResult,
  RankTrendMomentumProfile,
  RankTrendStrategyResult,
  StrategyAction,
} from './types'

export type HotlistSentimentLike = {
  stage?: string | null
  phase?: string | null
  phaseName?: string | null
  riskLevel?: string | null
  confidence?: unknown
} | null

function formatMomentum(value: number): string {
  return value > 0 ? `+${value.toFixed(1)}` : value.toFixed(1)
}

function resolveAction(tier: CandidateTier): StrategyAction {
  switch (tier) {
    case 'A_MAIN':
      return 'focus'
    case 'B_IGNITION':
      return 'watch'
    case 'C_CROWDED':
      return 'avoid'
    case 'D_EXIT_RISK':
      return 'exit_watch'
    default:
      return 'hold'
  }
}

function normalizeHotlistStage(hotlist: HotlistSentimentLike): string {
  const raw = String(hotlist?.stage || hotlist?.phaseName || hotlist?.phase || '')
  if (raw.includes('冰点')) return '冰点'
  if (raw.includes('启动')) return '启动'
  if (raw.includes('发酵')) return '发酵'
  if (raw.includes('高潮')) return '高潮'
  if (raw.includes('退潮')) return '退潮'
  return raw
}

export function composeExecutionCandidateTier(input: {
  technical: RankTrendAnalysisResult['technical']
  cycle: RankTrendAnalysisResult['cycle']
  risk: RankTrendAnalysisResult['risk']
  regime: MarketRegimeAnalysis
  hotlistSentiment?: HotlistSentimentLike
}): RankTrendStrategyResult {
  const { technical, cycle, risk, regime, hotlistSentiment } = input
  const momentum: RankTrendMomentumProfile = technical.momentumProfile
  const stage = cycle.stage
  const hotlistMissing = !hotlistSentiment || typeof hotlistSentiment !== 'object'
  const hotlistStage = hotlistMissing ? '' : normalizeHotlistStage(hotlistSentiment)
  const hotlistRisk = hotlistMissing ? '' : String(hotlistSentiment?.riskLevel || '')
  const hotlist = {
    state: hotlistMissing ? 'missing' as const : 'present' as const,
    stage: hotlistStage || null,
    riskLevel: hotlistRisk || null,
    confidence: hotlistMissing ? null : hotlistSentiment?.confidence,
  }
  const trendBuy =
    technical.signals.direction.signal === 'buy' ||
    technical.signals.acceleration.signal === 'buy' ||
    technical.macd.cross === 'golden'
  const lifecycleDecision = cycle.decision
  const lifecycleReasons = Array.isArray(lifecycleDecision.reasons) ? lifecycleDecision.reasons : []
  const lifecycleLowVisibilityIgnition =
    lifecycleDecision.action === 'caution' &&
    lifecycleReasons.some((reason) => String(reason).includes('低可见度'))
  const reasons: string[] = []
  let candidateTier: CandidateTier = 'N_NEUTRAL'

  if (hotlistStage === '退潮' || hotlistStage === '冰点') {
    if (momentum.short <= -2 || momentum.acceleration <= -2 || risk.pressure >= 0.55) {
      candidateTier = 'D_EXIT_RISK'
      reasons.push(`热榜${hotlistStage}期，动量衰减触发退出风险`)
    } else {
      reasons.push(`热榜${hotlistStage}期，暂停入场`)
    }
    reasons.push(`热榜情绪: ${hotlistStage}(风险${hotlistRisk || '未知'})`)
    return {
      regime,
      hotlist,
      momentum,
      candidateTier,
      action: resolveAction(candidateTier),
      reasons,
    }
  }

  const allowAMain = hotlistMissing || ((hotlistStage === '高潮' || hotlistStage === '发酵') && hotlistRisk !== '高')
  const allowBIgnition = hotlistMissing || hotlistStage === '高潮' || hotlistStage === '发酵' || hotlistStage === '启动'

  if (lifecycleDecision.action === 'veto') {
    reasons.push('生命周期辅助决策一票否决，阻止进入 A/B 候选池')
  } else if (
    (stage === 'reversal' || stage === 'cooling') &&
    (momentum.short <= -2 || momentum.acceleration <= -2 || risk.pressure >= 0.55)
  ) {
    candidateTier = 'D_EXIT_RISK'
    reasons.push('生命周期进入反转/冷却，短周期动量或风险压力转弱')
  } else if (
    stage === 'crowded' ||
    (momentum.long >= 4 && (momentum.acceleration <= 0 || risk.pressure >= 0.45))
  ) {
    candidateTier = 'C_CROWDED'
    reasons.push('长周期热度高位停留，追高性价比下降')
  } else if (
    stage === 'expansion' &&
    momentum.mid >= 4 &&
    momentum.short >= -1 &&
    trendBuy &&
    allowAMain &&
    risk.divergence.severity < 0.7
  ) {
    candidateTier = 'A_MAIN'
    reasons.push('扩散阶段中周期动量确认，热榜情绪支持A_MAIN入场')
  } else if (
    stage === 'ignition' &&
    momentum.short >= 3 &&
    momentum.acceleration >= 0.5 &&
    allowBIgnition &&
    risk.pressure < 0.65
  ) {
    candidateTier = 'B_IGNITION'
    reasons.push('点火阶段短周期冲击增强，热榜情绪支持B_IGNITION')
    if (lifecycleLowVisibilityIgnition) {
      reasons.push('生命周期B低可见度点火诊断生效，B_IGNITION保留候选但排序降权')
    }
  } else if (hotlistStage === '启动' && stage === 'expansion' && trendBuy) {
    reasons.push('热榜启动期，A_MAIN暂缓，等待扩散确认')
  } else if (hotlistRisk === '高' && trendBuy) {
    reasons.push('热榜情绪高风险，买入信号降级为观察')
  } else {
    reasons.push('动量、阶段与风险未形成明确候选池信号')
  }

  if (hotlistMissing) {
    reasons.push('热榜情绪缺失，按中性处理')
  } else if (hotlistStage) {
    reasons.push(`热榜情绪: ${hotlistStage}(风险${hotlistRisk || '未知'})`)
  }
  if (risk.divergence.severity >= 0.6) reasons.push('注意力与资金存在背离')
  if (risk.overheat.severity >= 0.65) reasons.push('过热压力较高')
  reasons.push(
    `动量结构 短${formatMomentum(momentum.short)} 中${formatMomentum(momentum.mid)} 长${formatMomentum(momentum.long)} 加速度${formatMomentum(momentum.acceleration)}`,
  )

  return {
    regime,
    hotlist,
    momentum,
    candidateTier,
    action: resolveAction(candidateTier),
    reasons,
  }
}
