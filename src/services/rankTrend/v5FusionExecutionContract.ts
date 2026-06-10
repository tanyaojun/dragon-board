import type { CandidateTier, RankTrendAnalysisResult } from './types'
import type {
  RankTrendLiveDecisionState,
  RankTrendLiveEntryDecision,
  RankTrendLiveGateCheck,
  RankTrendLiveStrategyConfig,
} from '@/types/rankTrendLiveStrategy'
import { normalizeRankTrendLiveStrategyConfig } from '@/config/rankTrendLiveStrategyConfig'
import { getExecutionCandidateTier } from './executionTierSelector'
import { buildLiveGateCheck, selectFirstBlockingCheck } from './liveGateCheckBuilder'
import { resolveLiveLimitState } from './liveLimitState'
import { getRankTrendLiveStrategyConfig } from './liveStrategyConfigStore'

export const V5_FUSION_DEFAULTS = {
  strategyName: 'ranktrend_early_big_move_v3_lifecycle_fusion',
  snapshotType: 'half_hour',
  executionMode: 'current_bar',
  maxHoldingBars: 30,
  volumeParticipationRate: 0.1,
  stopLossPct: 0.05,
  takeProfitPct: 9.99,
  minJumpConfidence: 90,
} as const

type RankTrendLike = RankTrendAnalysisResult & {
  jump?: {
    direction?: string
    confidence?: number
  }
}

export interface V5FusionEntryResult {
  accepted: boolean
  candidateTier: CandidateTier
  jumpConfidence: number
  lifecycleAction: string
  blockedReasons: string[]
  decisionState: RankTrendLiveDecisionState
  label: string
  summary: string
  firstBlockingCheck?: RankTrendLiveGateCheck
  checks: RankTrendLiveGateCheck[]
  configSnapshot: RankTrendLiveStrategyConfig
  entryDecision: RankTrendLiveEntryDecision
}

export interface V5FusionExitInput {
  hasOpenPosition?: boolean
  grossReturn?: number
}

export interface V5FusionExitResult {
  exitWatch: boolean
  reason?: string
}

function asNumber(value: unknown, fallback = 0): number {
  const num = Number(value)
  return Number.isFinite(num) ? num : fallback
}

function getRankTrend(stock: any): RankTrendLike | null {
  return (stock?.rankTrend as RankTrendLike | undefined) ?? null
}

function getMomentum(rankTrend: RankTrendLike) {
  return rankTrend.technical?.momentumProfile ?? rankTrend.executionStrategy?.momentum
}

function buildDecision(
  checks: RankTrendLiveGateCheck[],
  config: RankTrendLiveStrategyConfig,
): Pick<
  V5FusionEntryResult,
  | 'accepted'
  | 'decisionState'
  | 'label'
  | 'summary'
  | 'firstBlockingCheck'
  | 'entryDecision'
> {
  const firstBlockingCheck = selectFirstBlockingCheck(checks)
  const hasWarn = checks.some((check) => check.status === 'warn')
  const hasRecallSignal = checks.some(
    (check) =>
      (check.key === 'jump_direction' ||
        check.key === 'jump_confidence' ||
        check.key === 'momentum_positive' ||
        check.key === 'acceleration') &&
      (check.status === 'pass' || check.status === 'warn'),
  )
  const blockingMessage = firstBlockingCheck?.message
  const warningMessage = checks.find((check) => check.status === 'warn')?.message

  let decisionState: RankTrendLiveDecisionState = 'not_candidate'
  if (firstBlockingCheck) {
    decisionState = 'blocked_candidate'
  } else if (hasWarn) {
    decisionState = 'watch_candidate'
  } else if (hasRecallSignal) {
    decisionState = 'auto_add'
  }

  const label =
    decisionState === 'auto_add'
      ? '自动入池'
      : decisionState === 'watch_candidate'
        ? '观察候选'
        : decisionState === 'blocked_candidate'
          ? '被阻断'
          : '未触发'
  const summary =
    blockingMessage ||
    warningMessage ||
    (decisionState === 'auto_add' ? '满足当前 live 自动入池规则' : '尚未形成 live 候选召回')
  const accepted = decisionState === 'auto_add'
  const entryDecision: RankTrendLiveEntryDecision = {
    accepted,
    decisionState,
    label,
    summary,
    firstBlockingCheck,
    checks,
    configSnapshot: config,
  }

  return {
    accepted,
    decisionState,
    label,
    summary,
    firstBlockingCheck,
    entryDecision,
  }
}

function buildResult(input: {
  candidateTier: CandidateTier
  jumpConfidence: number
  lifecycleAction: string
  checks: RankTrendLiveGateCheck[]
  config: RankTrendLiveStrategyConfig
}): V5FusionEntryResult {
  const decision = buildDecision(input.checks, input.config)
  const blockedReasons = input.checks
    .filter((check) => check.status === 'fail' && check.hardBlock)
    .map((check) => check.message)

  return {
    accepted: decision.accepted,
    candidateTier: input.candidateTier,
    jumpConfidence: input.jumpConfidence,
    lifecycleAction: input.lifecycleAction,
    blockedReasons,
    decisionState: decision.decisionState,
    label: decision.label,
    summary: decision.summary,
    firstBlockingCheck: decision.firstBlockingCheck,
    checks: input.checks,
    configSnapshot: input.config,
    entryDecision: decision.entryDecision,
  }
}

export function evaluateV5FusionEntry(
  stock: any,
  configPatch: Partial<RankTrendLiveStrategyConfig> = {},
): V5FusionEntryResult {
  const storedConfig = getRankTrendLiveStrategyConfig()
  const modeChanged = !!configPatch.mode && configPatch.mode !== storedConfig.mode
  const presetForMode = modeChanged
    ? normalizeRankTrendLiveStrategyConfig({ mode: configPatch.mode })
    : storedConfig
  const config = normalizeRankTrendLiveStrategyConfig({
    ...presetForMode,
    ...configPatch,
    changeGate: configPatch.changeGate ?? presetForMode.changeGate,
  })
  const checks: RankTrendLiveGateCheck[] = []
  const rankTrend = getRankTrend(stock)
  if (!rankTrend) {
    checks.push(
      buildLiveGateCheck({
        key: 'ranktrend_present',
        label: 'RankTrend',
        status: 'fail',
        hardBlock: true,
        actual: false,
        expected: '存在 RankTrend 诊断',
        message: '缺失 rankTrend，阻断 V5 入场',
      }),
    )
    return buildResult({
      candidateTier: 'N_NEUTRAL',
      jumpConfidence: 0,
      lifecycleAction: '',
      checks,
      config,
    })
  }

  const executionTier = getExecutionCandidateTier(rankTrend)
  const candidateTier = executionTier || 'N_NEUTRAL'
  const lifecycleAction = String(rankTrend.cycle?.decision?.action ?? '')
  const jumpConfidence = asNumber(rankTrend.jump?.confidence)
  checks.push(
    buildLiveGateCheck({
      key: 'execution_strategy',
      label: '执行分层',
      status: executionTier ? 'pass' : 'fail',
      hardBlock: !executionTier,
      actual: candidateTier,
      expected: '存在 executionStrategy',
      message: executionTier ? '存在执行层候选分层' : '缺失 executionStrategy，阻断 V5 入场',
    }),
  )

  const sampleStatus = rankTrend.meta?.sampleQuality?.status || 'ok'
  const samplePass = sampleStatus === 'ok' || (config.allowDegradedSample && sampleStatus === 'degraded')
  checks.push(
    buildLiveGateCheck({
      key: 'sample_quality',
      label: '样本质量',
      status: samplePass ? 'pass' : 'fail',
      hardBlock: !samplePass,
      actual: sampleStatus,
      expected: config.allowDegradedSample ? 'ok/degraded' : 'ok',
      message: samplePass ? '样本质量满足 live 入池要求' : '样本不足，阻断 V5 入场',
    }),
  )

  checks.push(
    buildLiveGateCheck({
      key: 'lifecycle',
      label: '生命周期',
      status: lifecycleAction === 'veto' ? 'fail' : 'pass',
      hardBlock: lifecycleAction === 'veto',
      actual: lifecycleAction || null,
      expected: '非 veto',
      message: lifecycleAction === 'veto' ? '生命周期辅助决策一票否决' : '生命周期允许观察',
    }),
  )

  const jumpDirection = String(rankTrend.jump?.direction ?? '')
  checks.push(
    buildLiveGateCheck({
      key: 'jump_direction',
      label: 'Jump方向',
      status: jumpDirection === 'buy' ? 'pass' : 'fail',
      hardBlock: jumpDirection !== 'buy',
      actual: jumpDirection || null,
      expected: 'buy',
      message: jumpDirection === 'buy' ? 'Jump 方向为 buy' : 'Jump 方向不是 buy',
    }),
  )
  checks.push(
    buildLiveGateCheck({
      key: 'jump_confidence',
      label: 'Jump置信度',
      status: jumpConfidence >= config.minJumpConfidence ? 'pass' : 'fail',
      hardBlock: jumpConfidence < config.minJumpConfidence,
      actual: jumpConfidence,
      expected: `>= ${config.minJumpConfidence}`,
      message:
        jumpConfidence >= config.minJumpConfidence
          ? 'Jump 置信度满足要求'
          : `Jump 置信度低于 ${config.minJumpConfidence}`,
    }),
  )

  const momentum = getMomentum(rankTrend)
  const short = asNumber(momentum?.short)
  const mid = asNumber(momentum?.mid)
  const long = asNumber(momentum?.long)
  const acceleration = asNumber(momentum?.acceleration)
  const accDelta = asNumber(stock?.accDelta)
  const change = asNumber(stock?.change)
  const momentumPass = short > 0 && mid > 0 && long > 0

  checks.push(
    buildLiveGateCheck({
      key: 'momentum_positive',
      label: '多周期动量',
      status: momentumPass ? 'pass' : 'fail',
      hardBlock: !momentumPass,
      actual: `${short}/${mid}/${long}`,
      expected: 'short/mid/long > 0',
      message: momentumPass ? '多周期动量同步为正' : '多周期动量未同步为正',
    }),
  )
  const accelerationPass = acceleration >= config.accelerationMin || accDelta >= config.accDeltaMin
  checks.push(
    buildLiveGateCheck({
      key: 'acceleration',
      label: '加速度',
      status: accelerationPass ? 'pass' : 'fail',
      hardBlock: !accelerationPass,
      actual: `${acceleration}/${accDelta}`,
      expected: `acceleration >= ${config.accelerationMin} 或 accDelta >= ${config.accDeltaMin}`,
      message: accelerationPass ? '加速度满足 V5 入场要求' : '加速度未达到 V5 入场要求',
    }),
  )

  if (config.changeGate.mode === 'off' || config.changeGate.maxEntryChangePct === null) {
    checks.push(
      buildLiveGateCheck({
        key: 'change_position',
        label: '涨幅位置',
        status: 'disabled',
        hardBlock: false,
        actual: change,
        expected: '关闭',
        message: '涨幅位置规则已关闭',
      }),
    )
  } else {
    const changeTooHigh = change >= config.changeGate.maxEntryChangePct
    checks.push(
      buildLiveGateCheck({
        key: 'change_position',
        label: '涨幅位置',
        status: changeTooHigh ? (config.changeGate.mode === 'block' ? 'fail' : 'warn') : 'pass',
        hardBlock: changeTooHigh && config.changeGate.mode === 'block',
        actual: change,
        expected:
          config.changeGate.mode === 'block'
            ? `< ${config.changeGate.maxEntryChangePct}`
            : `< ${config.changeGate.maxEntryChangePct} 或观察`,
        message: changeTooHigh
          ? config.changeGate.mode === 'block'
            ? '涨幅过高，阻断早期入场'
            : '涨幅偏高，进入观察候选'
          : '涨幅位置满足 live 入池要求',
      }),
    )
  }

  const limitState = resolveLiveLimitState(stock)
  checks.push(
    buildLiveGateCheck({
      key: 'limit_up',
      label: '涨停状态',
      status: limitState.atLimitUp ? 'fail' : 'pass',
      hardBlock: limitState.atLimitUp,
      actual: limitState.source,
      expected: '未涨停',
      message: limitState.atLimitUp ? '涨停状态，阻断入场' : '未处于涨停阻断状态',
    }),
  )

  const tierAllowed = config.allowedCandidateTiers.includes(candidateTier)
  checks.push(
    buildLiveGateCheck({
      key: 'candidate_tier',
      label: '候选分层',
      status: tierAllowed ? 'pass' : config.requireCandidateTier ? 'fail' : 'warn',
      hardBlock: !tierAllowed && config.requireCandidateTier,
      actual: candidateTier,
      expected: config.allowedCandidateTiers.join('/'),
      message: tierAllowed ? '候选分层满足配置要求' : 'executionStrategy 非允许候选分层',
    }),
  )

  if (candidateTier === 'B_IGNITION') {
    const zeroCross = String(rankTrend.technical?.signals?.zeroCross?.signal ?? 'none')
    const tierBPass = mid >= config.tierBMidMin && zeroCross === 'buy'
    const hardBlock = !tierBPass && config.requireTierBMidAndZeroCross
    checks.push(
      buildLiveGateCheck({
        key: 'tier_b_confirmation',
        label: 'B档确认',
        status: tierBPass ? 'pass' : hardBlock ? 'fail' : 'warn',
        hardBlock,
        actual: `mid=${mid}, zeroCross=${zeroCross}`,
        expected: `mid >= ${config.tierBMidMin} 且 zeroCross=buy`,
        message: tierBPass
          ? 'B_IGNITION 通过中周期动量和零轴确认'
          : 'B_IGNITION 未通过中周期动量和零轴同步确认',
      }),
    )
  }

  return buildResult({
    candidateTier,
    jumpConfidence,
    lifecycleAction,
    checks,
    config,
  })
}

export function evaluateV5FusionExit(stock: any, input: V5FusionExitInput): V5FusionExitResult {
  const rankTrend = getRankTrend(stock)
  const lifecycleAction = String(rankTrend?.cycle?.decision?.action ?? '')
  const grossReturn = asNumber(input.grossReturn)

  if (
    input.hasOpenPosition &&
    grossReturn <= 0 &&
    (lifecycleAction === 'veto' || lifecycleAction === 'exit_watch')
  ) {
    return { exitWatch: true, reason: '生命周期B反对且未盈利' }
  }

  return { exitWatch: false }
}
