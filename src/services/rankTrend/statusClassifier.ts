import type { RankTrendAnalysisResult, RankTrendDisplayStatus } from './types'

export type { RankTrendDisplayStatus }

export interface RankTrendDisplayBreakdown {
  qualityLabel: string
  qualityBadgeLabel: string
  showQualityBadge: boolean
  cycleLabel: string
  tierLabel: string
  displayStatusLabel: string
  candidateTierKey: string
  candidateTierLabel: string
  tooltip: string
  classKeys: {
    quality: string
    cycle: string
    tier: string
    displayStatus: string
  }
}

// 2026-09-10 口径统一（spec: docs/superpowers/specs/2026-09-10-displaystatus-stage-projection-design.md）：
// displayStatus 是后端 `cycle.stage` 的纯投影 {stage, label, tooltip}，前端**不自维护任何词表**
// （历史教训：本文件 CYCLE_LABELS 曾用"降温"，而 DataTable 用"冷却"，同一状态两套词）。
// 分类层（8 类 RISK_LABELS / RISK_CLASS_KEYS / classKey / riskLabel）已删除。
//
// 与"无阶段"的区分：`label === '无阶段'` = 有投影记录但 stage 缺失；
// 这里是"完全没有 displayStatus 记录"（旧缓存/离线），故标签为"未知"。
const UNKNOWN_STATUS: RankTrendDisplayStatus = {
  stage: null,
  label: '未知',
  tooltip: '后端 displayStatus 缺失（旧缓存/离线）。',
}

export const UNKNOWN_STAGE_CLASS_KEY = 'stage-none'

const CANDIDATE_TIER_LABELS: Record<string, string> = {
  A_MAIN: 'A_MAIN / 主升候选',
  B_IGNITION: 'B_IGNITION / 点火候选',
  C_CROWDED: 'C_CROWDED / 拥挤候选',
  D_EXIT_RISK: 'D_EXIT_RISK / 退出风险',
  N_NEUTRAL: 'N_NEUTRAL / 中性观察',
}

export const CANDIDATE_TIER_SHORT_LABELS: Record<string, string> = {
  A_MAIN: '主升候选',
  B_IGNITION: '点火候选',
  C_CROWDED: '拥挤候选',
  D_EXIT_RISK: '退出风险',
  N_NEUTRAL: '中性观察',
}

const CANDIDATE_TIER_CLASS_KEYS: Record<string, string> = {
  A_MAIN: 'candidate-main',
  B_IGNITION: 'candidate-ignition',
  C_CROWDED: 'candidate-crowded',
  D_EXIT_RISK: 'candidate-exit',
  N_NEUTRAL: 'candidate-neutral',
}

const SAMPLE_QUALITY_LABELS: Record<string, string> = {
  ok: '样本OK',
  degraded: '样本降级',
  insufficient: '样本不足',
  unknown: '样本未知',
}

/** stage 的 CSS classKey（无 stage → `stage-none`）；不再使用 8 类 classKey。 */
export const stageClassKey = (stage: string | null): string =>
  stage ? `stage-${stage}` : UNKNOWN_STAGE_CLASS_KEY

export function getRankTrendDisplayStatus(
  rankTrend?: RankTrendAnalysisResult | null,
): RankTrendDisplayStatus {
  // 后端直通：analysis.displayStatus 由 Python compute_display_status 生产（stage 纯投影）。
  const backendStatus = rankTrend?.displayStatus
  if (backendStatus && typeof backendStatus.label === 'string') {
    return {
      stage: typeof backendStatus.stage === 'string' && backendStatus.stage ? backendStatus.stage : null,
      label: backendStatus.label,
      tooltip: backendStatus.tooltip ?? '',
    }
  }
  return UNKNOWN_STATUS
}

export function getRankTrendDisplayBreakdown(
  rankTrend?: RankTrendAnalysisResult | null,
): RankTrendDisplayBreakdown {
  const status = getRankTrendDisplayStatus(rankTrend)
  const sampleStatus = rankTrend ? rankTrend.meta?.sampleQuality?.status ?? 'unknown' : 'insufficient'
  const candidateTierKey = rankTrend?.strategy?.candidateTier ? String(rankTrend.strategy.candidateTier) : ''
  const candidateTierLabel = candidateTierKey
    ? CANDIDATE_TIER_LABELS[candidateTierKey] ?? candidateTierKey
    : '-'
  const tierLabel = candidateTierKey
    ? CANDIDATE_TIER_SHORT_LABELS[candidateTierKey] ?? candidateTierKey
    : status.label
  const qualityLabel = SAMPLE_QUALITY_LABELS[sampleStatus] ?? '样本未知'
  // 周期栏直接消费后端 label（词表单源；本文件不再维护 CYCLE_LABELS）
  const cycleLabel = status.label
  const tooltip = [
    `样本：${qualityLabel}`,
    `周期：${cycleLabel}`,
    `生命周期：${tierLabel}`,
    candidateTierKey ? `原始分层：${candidateTierLabel}` : '',
    `展示状态：${status.label}`,
    status.tooltip,
  ]
    .filter(Boolean)
    .join('\n')

  return {
    qualityLabel,
    qualityBadgeLabel: '',
    showQualityBadge: false,
    cycleLabel,
    tierLabel,
    displayStatusLabel: status.label,
    candidateTierKey,
    candidateTierLabel,
    tooltip,
    classKeys: {
      quality: `quality-${sampleStatus}`,
      cycle: status.stage ? `cycle-${status.stage}` : 'cycle-empty',
      tier: candidateTierKey
        ? CANDIDATE_TIER_CLASS_KEYS[candidateTierKey] ?? 'candidate-unknown'
        : stageClassKey(status.stage),
      displayStatus: stageClassKey(status.stage),
    },
  }
}
