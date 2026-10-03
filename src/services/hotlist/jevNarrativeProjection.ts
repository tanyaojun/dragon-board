// src/services/hotlist/jevNarrativeProjection.ts
// jev 叙事投影纯函数（JEV 叙事面板深加工层，2026-10-08 立项）。
// 只做无副作用投影：叙事分段 / 锚分位解析 / 置信指标 / 拥挤时间线 / 方格矩阵 / 层统计。
// fail-visible：任何缺失返回 null/空结构，不伪造档位、0 分或概率分布；
// score 型（温度）答案实测携带 10 档锚点概率分布 + confidence（2026-10-02 生产库 100% 覆盖，锚期望/9×100=还原分）；
// 仅当确实缺失时标 noDistribution（fail-visible），不把 TS 类型缺字段当协议事实（2026-10-02 纠错）。
// 结论唯一来源 = QuantBoard 后端 jev 轨道（hotlist_jev_sentiment）落库文档，本模块零计算补齐。

import type { HotlistJevAnswer, HotlistJevDayEntry, HotlistJevDoc, HotlistJevMissingDay } from '@/types/hotlistJev'
import { JEV_CROWDING_NAMES, JEV_CROWDING_WARN_LAYERS } from './hotlistJevApi'

/** 犹豫阈值（与热榜情绪面板 jevHesitant 同一口径）：top 概率 < 60% 视为低置信 */
export const JEV_HESITANT_THRESHOLD = 0.6

// ---------- 叙事分段（narrativeRaw 的【…】段结构化） ----------

export interface JevNarrativeSection {
  /** 段标题（如 近20日参照 / 当前帧 / 当日已走帧证据 / 数据质量）；header 行归属 null */
  title: string
  /** 段体行（不含【…】头行；段头后同行尾文为首个元素） */
  lines: string[]
}

export interface JevNarrativeProjection {
  /** 首个【…】段之前的引导行（如「2026-10-08 14:30 时点快照…」） */
  header: string
  sections: JevNarrativeSection[]
}

/** 空投影（输入缺失/非字符串时返回，不抛错） */
export const EMPTY_NARRATIVE: JevNarrativeProjection = { header: '', sections: [] }

/** 按【…】段头切分叙事文本；无段头时整体归 header */
export function parseNarrativeSections(narrativeRaw: string | null | undefined): JevNarrativeProjection {
  if (!narrativeRaw || typeof narrativeRaw !== 'string') return EMPTY_NARRATIVE
  const header: string[] = []
  const sections: JevNarrativeSection[] = []
  let current: JevNarrativeSection | null = null
  for (const line of narrativeRaw.split('\n')) {
    const match = /^【(.+?)】(.*)$/.exec(line)
    if (match) {
      current = { title: match[1] ?? '', lines: match[2]?.trim() ? [match[2].trim()] : [] }
      sections.push(current)
    } else if (current) {
      current.lines.push(line)
    } else {
      header.push(line)
    }
  }
  return { header: header.join('\n').trim(), sections }
}

/** 按段标题取段（缺失 null） */
export function findNarrativeSection(
  projection: JevNarrativeProjection | null | undefined,
  title: string,
): JevNarrativeSection | null {
  return projection?.sections.find((section) => section.title === title) ?? null
}

// ---------- 锚分位解析（【近20日参照】段 → 结构化四指标） ----------

export interface JevAnchorMetric {
  /** 指标名（涨停数/最高连板/两市成交额/炸板率） */
  metric: string
  p20: number | null
  p50: number | null
  p80: number | null
  lastDate: string | null
  lastValue: number | null
  /** 单位（家/板/亿/%；缺失 null） */
  unit: string | null
  /** fail-visible 注记（如「历史样本不足（3 日）」）；正常解析为 null */
  note: string | null
}

// 形如：涨停数：p20=45 家 / p50=67 家 / p80=91 家（2026-09-30 88 家）
// 炸板率：p20=12% / p50=15% / p80=25%（2026-09-30 18%）
const ANCHOR_Q_RE =
  /^(.+?)：p20=(-?[\d.]+)\s*(%|家|板|亿)?\s*\/\s*p50=(-?[\d.]+)\s*(%|家|板|亿)?\s*\/\s*p80=(-?[\d.]+)\s*(%|家|板|亿)?\s*（([\d-]{8,10})\s+(-?[\d.]+)\s*(%|家|板|亿)?）$/
// 形如：涨停数 历史样本不足（3 日）
const ANCHOR_INSUFFICIENT_RE = /^(.+?)\s*历史样本不足（(\d+)\s*日）$/

function safeNumber(raw: string | undefined): number | null {
  if (raw === undefined) return null
  const value = Number(raw)
  return Number.isFinite(value) ? value : null
}

/** 解析锚分位段（接受段对象、原始文本或行数组）；行不匹配任何已知形态则跳过（不猜测） */
export function parseAnchorQuantiles(
  input: { lines: string[] } | string[] | string | null | undefined,
): JevAnchorMetric[] {
  const lines =
    typeof input === 'string'
      ? input.split('\n')
      : Array.isArray(input)
        ? input
        : (input?.lines ?? [])
  const out: JevAnchorMetric[] = []
  for (const rawLine of lines) {
    const line = rawLine.trim()
    if (!line) continue
    const quantile = ANCHOR_Q_RE.exec(line)
    if (quantile) {
      out.push({
        metric: quantile[1]?.trim() ?? '',
        p20: safeNumber(quantile[2]),
        p50: safeNumber(quantile[4]),
        p80: safeNumber(quantile[6]),
        lastDate: quantile[8] ?? null,
        lastValue: safeNumber(quantile[9]),
        unit: quantile[3] || quantile[7] || quantile[10] || null,
        note: null,
      })
      continue
    }
    const insufficient = ANCHOR_INSUFFICIENT_RE.exec(line)
    if (insufficient) {
      out.push({
        metric: insufficient[1]?.trim() ?? '',
        p20: null,
        p50: null,
        p80: null,
        lastDate: null,
        lastValue: null,
        unit: null,
        note: `历史样本不足（${insufficient[2]} 日）`,
      })
    }
  }
  return out
}

/** 便捷封装：从文档 narrativeRaw 直接解析锚分位 */
export function anchorMetricsOfDoc(doc: HotlistJevDoc | null | undefined): JevAnchorMetric[] {
  const projection = parseNarrativeSections(doc?.narrativeRaw)
  return parseAnchorQuantiles(findNarrativeSection(projection, '近20日参照'))
}

// ---------- 置信指标（choice 深加工：margin / 归一化熵 / 犹豫标记） ----------

export interface JevConfidenceMetrics {
  kind: 'choice' | 'score' | 'missing'
  /** 归层/档位英文键（choice 答案的原始 choice） */
  choice: string | null
  /** 所选选项的 top 概率（0-1；缺失 null；score 型无 choice 恒 null，锚点离散度看 margin/熵） */
  probability: number | null
  /** 模型自带 confidence 字段（缺失 null；score 型实测同样携带） */
  confidence: number | null
  /** top1 − top2 概率差（选项 <2 个为 null） */
  margin: number | null
  /** 归一化香农熵（0=笃定，1=均匀；有效选项 <2 或全零为 null） */
  entropy: number | null
  /** top 概率低于犹豫阈值 */
  hesitant: boolean
  /** true=答案确实未携带概率分布（score 型缺锚点分布）；携带时 false——类型缺字段≠协议事实（2026-10-02 纠错） */
  noDistribution: boolean
  noDistributionReason: string | null
}

export const EMPTY_CONFIDENCE: JevConfidenceMetrics = {
  kind: 'missing',
  choice: null,
  probability: null,
  confidence: null,
  margin: null,
  entropy: null,
  hesitant: false,
  noDistribution: false,
  noDistributionReason: null,
}

/** choice/score 答案的置信投影；score 型消费锚点分布+confidence，仅确缺失时标 noDistribution（fail-visible） */
export function confidenceMetrics(answer: HotlistJevAnswer | null | undefined): JevConfidenceMetrics {
  if (!answer) return EMPTY_CONFIDENCE
  if (answer.type === 'score') {
    // 2026-10-02 纠错：score 答案实测携带 10 档锚点分布（键 "0"-"9"，锚期望/9×100=还原分）+confidence；
    // 旧逻辑直接标「无分布」是把 TS 类型缺字段当协议事实（把有说成没有）
    const probabilities = answer.probabilities ?? null
    const values = probabilities
      ? Object.values(probabilities).filter(
          (value): value is number => typeof value === 'number' && Number.isFinite(value) && value >= 0,
        )
      : []
    const sorted = [...values].sort((a, b) => b - a)
    const sum = values.reduce((total, value) => total + value, 0)
    let entropy: number | null = null
    if (values.length > 1 && sum > 0) {
      let h = 0
      for (const value of values) {
        if (value > 0) h -= (value / sum) * Math.log(value / sum)
      }
      entropy = h / Math.log(values.length)
    }
    const noDistribution = values.length === 0
    return {
      ...EMPTY_CONFIDENCE,
      kind: 'score',
      confidence: typeof answer.confidence === 'number' ? answer.confidence : null,
      margin: sorted.length >= 2 && sorted[0] != null && sorted[1] != null ? sorted[0] - sorted[1] : null,
      entropy,
      noDistribution,
      noDistributionReason: noDistribution ? 'score 型答案未携带锚点分布' : null,
    }
  }
  const probabilities = answer.probabilities ?? {}
  const values = Object.values(probabilities).filter(
    (value): value is number => typeof value === 'number' && Number.isFinite(value) && value >= 0,
  )
  const sorted = [...values].sort((a, b) => b - a)
  const sum = values.reduce((total, value) => total + value, 0)
  let entropy: number | null = null
  if (values.length > 1 && sum > 0) {
    let h = 0
    for (const value of values) {
      if (value > 0) h -= (value / sum) * Math.log(value / sum)
    }
    entropy = h / Math.log(values.length)
  }
  const probability =
    answer.choice != null && typeof probabilities[answer.choice] === 'number'
      ? (probabilities[answer.choice] as number)
      : null
  return {
    kind: 'choice',
    choice: answer.choice ?? null,
    probability,
    confidence: typeof answer.confidence === 'number' ? answer.confidence : null,
    margin: sorted.length >= 2 && sorted[0] != null && sorted[1] != null ? sorted[0] - sorted[1] : null,
    entropy,
    hesitant: probability != null && probability < JEV_HESITANT_THRESHOLD,
    noDistribution: false,
    noDistributionReason: null,
  }
}

// ---------- 拥挤时间线（当日逐槽归层 + 层迁移） ----------

export interface JevCrowdingPoint {
  slotTime: string
  status: string
  /** 归层英文键（缺失/非 choice 为 null） */
  layer: string | null
  /** 归层中文名 */
  layerName: string | null
  /** 毒层（top_acceleration / late_seal_weakness，fwdWorst 实证读数差） */
  warn: boolean
  /** 所选层概率（0-1；缺失 null） */
  probability: number | null
  /** 模型 confidence（缺失 null） */
  confidence: number | null
  /** 全层概率分布（waffle 方格用；缺失 null） */
  probabilities: Record<string, number> | null
}

export function crowdingTimeline(slots: HotlistJevDoc[]): JevCrowdingPoint[] {
  return slots.map((slot) => {
    const answer = slot.answers?.crowding
    const choice = answer && answer.type === 'choice' ? answer.choice ?? null : null
    const probabilities = answer && answer.type === 'choice' ? answer.probabilities ?? null : null
    const probability =
      choice != null && probabilities && typeof probabilities[choice] === 'number'
        ? (probabilities[choice] as number)
        : null
    return {
      slotTime: slot.slotTime || '--',
      status: slot.status || 'ok',
      layer: choice,
      layerName: choice ? (JEV_CROWDING_NAMES[choice] ?? choice) : null,
      warn: choice != null && JEV_CROWDING_WARN_LAYERS.has(choice),
      probability,
      confidence:
        answer && answer.type === 'choice' && typeof answer.confidence === 'number'
          ? answer.confidence
          : null,
      probabilities,
    }
  })
}

export interface JevCrowdingTransition {
  atSlot: string
  from: string | null
  fromName: string | null
  to: string
  toName: string
}

/** 当日层迁移序列（相邻槽归层变化点；首槽无 from 不产生迁移） */
export function crowdingTransitions(points: JevCrowdingPoint[]): JevCrowdingTransition[] {
  const out: JevCrowdingTransition[] = []
  for (let i = 1; i < points.length; i += 1) {
    const prev = points[i - 1]
    const curr = points[i]
    if (!prev || !curr || !curr.layer || prev.layer === curr.layer) continue
    out.push({
      atSlot: curr.slotTime,
      from: prev.layer,
      fromName: prev.layerName,
      to: curr.layer,
      toName: curr.layerName ?? curr.layer,
    })
  }
  return out
}

// ---------- 层统计（窗口内归层分布 + insufficient_evidence 逃生率） ----------

export interface JevLayerStats {
  /** 有归层答案的文档数（分母） */
  total: number
  counts: Record<string, number>
  escapeCount: number
  /** 逃生率（0-1；分母 0 为 null） */
  escapeRate: number | null
}
/** 拥挤层统计：slot 文档读 crowding、EOD 文档读 day_crowding（按传入集合各自取键） */
export function layerStats(docs: HotlistJevDoc[], kind: 'slot' | 'eod'): JevLayerStats {
  const key = kind === 'eod' ? 'day_crowding' : 'crowding'
  const counts: Record<string, number> = {}
  let total = 0
  for (const doc of docs) {
    const answer = doc.answers?.[key]
    if (!answer || answer.type !== 'choice' || !answer.choice) continue
    total += 1
    counts[answer.choice] = (counts[answer.choice] ?? 0) + 1
  }
  const escapeCount = counts.insufficient_evidence ?? 0
  return { total, counts, escapeCount, escapeRate: total > 0 ? escapeCount / total : null }
}

// ---------- 窗口收缩裁剪（缓存更宽时就地收缩，不重拉） ----------

export interface JevRangeWindow {
  days: HotlistJevDayEntry[]
  missingDays: HotlistJevMissingDay[]
}

/**
 * 按快照交易日历就地收缩到最近 days 个历日：日历 = 有文档日 ∪ 缺失日并集排序后取尾部，
 * 再拆回文档日/缺失日（2026-10-08 评审修复：宽→窄窗口切换时内容必须随窗口变化）。
 */
export function trimRangeWindow(days: number, range: JevRangeWindow): JevRangeWindow {
  const calendar = [
    ...range.days.map((day) => day.tradingDate),
    ...range.missingDays.map((day) => day.tradingDate),
  ]
    .filter((date) => !!date)
    .sort()
  const windowSet = new Set(calendar.slice(-Math.max(1, days)))
  const byDate = (a: { tradingDate: string }, b: { tradingDate: string }) =>
    a.tradingDate.localeCompare(b.tradingDate)
  return {
    days: range.days.filter((day) => windowSet.has(day.tradingDate)).sort(byDate),
    missingDays: range.missingDays.filter((day) => windowSet.has(day.tradingDate)).sort(byDate),
  }
}

/** 窗口内降级/无数据文档数（slot + eod，与后端 degradedCount 同口径） */
export function countDegradedDocs(days: HotlistJevDayEntry[]): number {
  let count = 0
  for (const day of days) {
    for (const slot of day.slots) {
      if (slot.status === 'degraded' || slot.status === 'no_data') count += 1
    }
    if (day.eod && (day.eod.status === 'degraded' || day.eod.status === 'no_data')) count += 1
  }
  return count
}
