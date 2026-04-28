import type {
  AuthorityClass,
  BattlefieldDominance,
  BattlefieldType,
  ChaseRisk,
  FragilityLevel,
  LeaderRole,
  LeaderStatus,
  ReviewRegime,
  SignalStrength,
  Tradeability,
  LeaderTransition,
} from './types'

const ROLE_LABELS: Record<LeaderRole, string> = {
  MARKET_CORE: '市场总龙头',
  THEME_CORE: '题材真龙',
  SPACE_CORE: '高标核心',
  TREND_CORE: '趋势中军',
  EMOTION_CORE: '情绪核心',
}

const AUTHORITY_LABELS: Record<AuthorityClass, string> = {
  TRUE_LEADER: '真龙',
  THEME_COMMANDER: '题材主将',
  CARRY_PROXY: '承载代理',
  HEIGHT_ONLY: '高标样本',
  HEAT_ONLY: '热度样本',
  PSEUDO_LEADER: '伪龙',
}

const TRADEABILITY_LABELS: Record<Tradeability, string> = {
  ACTIONABLE: '可处理',
  WATCH_ONLY: '只观察',
  DO_NOT_CHASE: '禁止追涨',
}

const RISK_LABELS: Record<ChaseRisk, string> = {
  LOW: '低风险',
  MEDIUM: '中风险',
  HIGH: '高风险',
  EXTREME: '极高风险',
}

const STATUS_LABELS: Record<LeaderStatus, string> = {
  CANDIDATE: '候选',
  PROBING_LEADER: '试探',
  CONFIRMED_LEADER: '确认',
  COMMANDING: '主导',
  WEAKENING: '转弱',
  DEPOSED: '失位',
}

const REGIME_LABELS: Record<ReviewRegime, string> = {
  MAINLINE_ADVANCE: '主线推进',
  MULTI_FRONT_CONTEST: '多线争夺',
  HIGH_LEVEL_HUG: '高位抱团',
  REPAIR_ATTEMPT: '修复尝试',
  ROTATION_NO_CORE: '轮动无核',
  DISTRIBUTION_DECAY: '分歧退潮',
}

const DOMINANCE_LABELS: Record<BattlefieldDominance, string> = {
  DOMINANT: '主导战场',
  CONTESTED: '争夺战场',
  WEAK: '弱战场',
}

const BATTLEFIELD_TYPE_LABELS: Record<BattlefieldType, string> = {
  THEME: '题材战场',
  STYLE: '风格战场',
  INDEPENDENT: '独立战场',
}

const SIGNAL_LABELS: Record<SignalStrength, string> = {
  strong: '强',
  medium: '中',
  weak: '弱',
}

const FRAGILITY_LABELS: Record<FragilityLevel, string> = {
  low: '低',
  mid: '中',
  high: '高',
}

const TRANSITION_LABELS: Record<LeaderTransition['type'], string> = {
  candidate: '入池',
  confirm: '确认',
  command: '主导',
  weaken: '转弱',
  replace: '换龙',
  depose: '失位',
}

const MISSING_DATA_LABELS: Record<string, string> = {
  daily_snapshot: '日级快照缺失',
  intraday_frames: '盘中复盘帧缺失',
  close_frame: '收盘态缺失',
  review_frames: '复盘帧缺失',
  hourly_snapshot: '整点快照缺失',
  half_hour_snapshot: '半小时快照缺失',
  quarter_hour_snapshot: '刻钟快照缺失',
}

export function roleLabel(value?: LeaderRole | null): string {
  return value ? ROLE_LABELS[value] || value : '--'
}

export function authorityLabel(value?: AuthorityClass | null): string {
  return value ? AUTHORITY_LABELS[value] || value : '--'
}

export function tradeabilityLabel(value?: Tradeability | null): string {
  return value ? TRADEABILITY_LABELS[value] || value : '--'
}

export function chaseRiskLabel(value?: ChaseRisk | null): string {
  return value ? RISK_LABELS[value] || value : '--'
}

export function statusLabel(value?: LeaderStatus | null): string {
  return value ? STATUS_LABELS[value] || value : '--'
}

export function regimeLabel(value?: ReviewRegime | null): string {
  return value ? REGIME_LABELS[value] || value : '--'
}

export function dominanceLabel(value?: BattlefieldDominance | null): string {
  return value ? DOMINANCE_LABELS[value] || value : '--'
}

export function battlefieldTypeLabel(value?: BattlefieldType | null): string {
  return value ? BATTLEFIELD_TYPE_LABELS[value] || value : '--'
}

export function strengthLabel(value?: SignalStrength | null): string {
  return value ? SIGNAL_LABELS[value] || value : '--'
}

export function fragilityLabel(value?: FragilityLevel | null): string {
  return value ? FRAGILITY_LABELS[value] || value : '--'
}

export function transitionLabel(value?: LeaderTransition['type'] | null): string {
  return value ? TRANSITION_LABELS[value] || value : '--'
}

export function missingDataLabel(value?: string | null): string {
  if (!value) return '--'
  return MISSING_DATA_LABELS[value] || value
}
