import type {
  CandidateTier,
  MarketRegimeAnalysis,
  RankTrendAnalysisResult,
  RankTrendMomentumProfile,
  RankTrendStrategyResult,
  StrategyAction,
} from './types'

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

export function composeCandidateTier(input: {
  technical: RankTrendAnalysisResult['technical']
  cycle: RankTrendAnalysisResult['cycle']
  risk: RankTrendAnalysisResult['risk']
  regime: MarketRegimeAnalysis
}): RankTrendStrategyResult {
  const { technical, cycle, risk, regime } = input
  const momentum: RankTrendMomentumProfile = technical.momentumProfile
  const stage = cycle.stage
  const reasons: string[] = []
  const moneyRisk = risk.divergence.severity
  const pressure = risk.pressure
  const weakMarket = regime.state === 'weak' || regime.state === 'retreat'
  const trendBuy =
    technical.signals.direction.signal === 'buy' ||
    technical.signals.acceleration.signal === 'buy' ||
    technical.macd.cross === 'golden'
  const lifecycleDecision = cycle.decision

  let candidateTier: CandidateTier = 'N_NEUTRAL'

  if (lifecycleDecision.action === 'veto') {
    reasons.push('生命周期辅助决策一票否决，阻止进入 A/B 候选池')
  } else if (
    (stage === 'reversal' || stage === 'cooling') &&
    (momentum.short <= -2 || momentum.acceleration <= -2 || pressure >= 0.55)
  ) {
    candidateTier = 'D_EXIT_RISK'
    reasons.push('生命周期进入反转/冷却，短周期动量或风险压力转弱')
  } else if (
    stage === 'crowded' ||
    (momentum.long >= 4 && (momentum.acceleration <= 0 || pressure >= 0.45))
  ) {
    candidateTier = 'C_CROWDED'
    reasons.push('长周期热度高位停留，追高性价比下降')
  } else if (
    stage === 'expansion' &&
    momentum.mid >= 4 &&
    momentum.short >= -1 &&
    trendBuy &&
    !weakMarket &&
    moneyRisk < 0.7
  ) {
    candidateTier = 'A_MAIN'
    reasons.push('扩散阶段中周期动量确认，技术信号保持正向')
  } else if (
    stage === 'ignition' &&
    momentum.short >= 3 &&
    momentum.acceleration >= 0.5 &&
    regime.state !== 'retreat' &&
    pressure < 0.65
  ) {
    candidateTier = 'B_IGNITION'
    reasons.push('点火阶段短周期冲击增强，仍需继续确认')
  } else if (weakMarket && trendBuy) {
    candidateTier = 'N_NEUTRAL'
    reasons.push('弱势/退潮环境下买入信号降级为观察')
  } else {
    reasons.push('动量、阶段与风险未形成明确候选池信号')
  }

  if (regime.state === 'strong') reasons.push('市场环境强，允许跟踪点火/扩散机会')
  if (regime.state === 'retreat') reasons.push('市场退潮，优先控制回撤风险')
  if (risk.divergence.severity >= 0.6) reasons.push('注意力与资金存在背离')
  if (risk.overheat.severity >= 0.65) reasons.push('过热压力较高')
  reasons.push(
    `动量结构 短${formatMomentum(momentum.short)} 中${formatMomentum(momentum.mid)} 长${formatMomentum(momentum.long)} 加速度${formatMomentum(momentum.acceleration)}`,
  )

  return {
    regime,
    momentum,
    candidateTier,
    action: resolveAction(candidateTier),
    reasons,
  }
}
