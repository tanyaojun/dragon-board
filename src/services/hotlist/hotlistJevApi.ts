// src/services/hotlist/hotlistJevApi.ts
// 薄 API client：jev 热榜情绪观察轨道读口（GET /api/hotlist-jev/series）。
// 只做 fetch + 类型化，无兜底计算（结论唯一来源 = QuantBoard 后端 jev 轨道落库）。
import type {
  HotlistJevLimitUpDay,
  HotlistJevThemeLeaderDay,
  HotlistJevDoc,
  HotlistJevDayEntry,
  HotlistJevMissingDay,
  HotlistJevRangeResponse,
  HotlistJevRangeResult,
  HotlistJevSeriesResult,
  HotlistSentimentOverviewResult,
} from '@/types/hotlistJev'

/** 拥挤归层英文值 → 展示中文（离散归层 v2.5 起六层含「拥挤解除」；fail-visible 逃生口如实标注） */
export const JEV_CROWDING_NAMES: Record<string, string> = {
  top_acceleration: '高位加速',
  late_seal_weakness: '封板弱化',
  breadth_climax: '广度高潮',
  crowd_clearing: '拥挤解除',
  no_crowding: '无拥挤',
  insufficient_evidence: '信息不足',
}

/** 拥挤归层的风险警示层（chip 着色用） */
export const JEV_CROWDING_WARN_LAYERS: ReadonlySet<string> = new Set([
  'top_acceleration',
  'late_seal_weakness',
])

/** jev 五档英文值 → 展示中文（与规则轨道五档同词汇，判定彼此独立） */
export const JEV_STAGE_NAMES: Record<string, string> = {
  ice: '冰点',
  start: '启动',
  ferment: '发酵',
  climax: '高潮',
  retreat: '退潮',
}

/** 日级路径形态八类 → 展示中文（v2.5 起尾盘偷袭自低开修复分流单列） */
export const JEV_PATTERN_NAMES: Record<string, string> = {
  steady_strong: '全天强势主导',
  steady_weak: '全天弱势主导',
  rally_fade: '冲高回落',
  low_recover: '低开修复',
  late_rescue: '尾盘偷袭',
  wide_swing: '剧烈反复',
  narrow_range: '窄幅平淡',
  unclear: '无法归纳',
}

/** 档位/形态的规范展示顺序（五档冷→热；七类路径），概率条顺序唯一来源 */
export const JEV_STAGE_ORDER = Object.keys(JEV_STAGE_NAMES)
export const JEV_PATTERN_ORDER = Object.keys(JEV_PATTERN_NAMES)

/** 读 choice 答案的档位中文（缺失返回 null，不伪造默认档） */
export function jevChoiceName(doc: HotlistJevDoc | null | undefined, key: string): string | null {
  const answer = doc?.answers?.[key]
  if (!answer || answer.type !== 'choice' || !answer.choice) return null
  const name =
    key === 'day_pattern' ? JEV_PATTERN_NAMES[answer.choice] : JEV_STAGE_NAMES[answer.choice]
  return name ?? answer.choice
}

/** choice 答案的 top 概率（0-1；缺失 null） */
export function jevChoiceProbability(
  doc: HotlistJevDoc | null | undefined,
  key: string,
): number | null {
  const answer = doc?.answers?.[key]
  if (!answer || answer.type !== 'choice') return null
  const probability = answer.probabilities?.[answer.choice ?? '']
  return typeof probability === 'number' ? probability : null
}

/** 还原后 0-100 分数（缺失 null，不伪造 0 分） */
export function jevScore(doc: HotlistJevDoc | null | undefined, key: string): number | null {
  const value = doc?.scores?.[key]
  return typeof value === 'number' && Number.isFinite(value) ? Math.round(value) : null
}

/** 拥挤归层答案展示（拥挤=离散归层 choice；缺失/score 型返回 null 不伪造） */
export function jevCrowdingName(
  doc: HotlistJevDoc | null | undefined,
  key: string,
): string | null {
  const answer = doc?.answers?.[key]
  if (!answer || answer.type !== 'choice' || !answer.choice) return null
  return JEV_CROWDING_NAMES[answer.choice] ?? answer.choice
}

/** 拥挤三层（即 1−无拥挤−信息不足−拥挤解除），拥挤度柱体的唯一数值口径（拥挤解除=出清态，不计入拥挤合计） */
export const JEV_CROWDING_LAYERS = ['top_acceleration', 'late_seal_weakness', 'breadth_climax'] as const

/**
 * 拥挤度（0-1）= 拥挤三层概率合计（top_acceleration/late_seal_weakness/breadth_climax），
 * 即模型认为市场处于任一拥挤层的总概率。v2 拥挤是离散归层 choice，无连续分可读；
 * 只聚合落库分布里的已有数值，缺分布/非 choice 返回 null 不伪造（展示层零计算补齐的边界：仅做加总透明聚合）。
 *
 * 2026-10-24 A2 单一事实源提后端：读口（/series、/range）已为每文档附 crowdingProbability
 * （后端同口径三层合计），有后端值直接消费；缺字段（直构文档/旧形态）回退本地同式计算。
 */
export function jevCrowdingProbability(
  doc: HotlistJevDoc | null | undefined,
  key: string,
): number | null {
  if (doc && typeof doc.crowdingProbability === 'number') return doc.crowdingProbability
  const answer = doc?.answers?.[key]
  if (!answer || answer.type !== 'choice' || !answer.probabilities) return null
  const probabilities = answer.probabilities
  let total = 0
  let seen = false
  for (const layer of JEV_CROWDING_LAYERS) {
    const value = probabilities[layer]
    if (typeof value === 'number' && Number.isFinite(value)) {
      total += value
      seen = true
    }
  }
  return seen ? total : null
}

/** choice 答案的模型 confidence（0-1；缺失/非 choice 返回 null 不伪造） */
export function jevChoiceConfidence(
  doc: HotlistJevDoc | null | undefined,
  key: string,
): number | null {
  const answer = doc?.answers?.[key]
  if (!answer || answer.type !== 'choice') return null
  return typeof answer.confidence === 'number' ? answer.confidence : null
}

export async function fetchHotlistJevSeries(
  date?: string,
  datasetId = 'dragonboard_live',
): Promise<HotlistJevSeriesResult> {
  const params = new URLSearchParams({ dataset_id: datasetId })
  if (date) params.set('date', date)
  try {
    const response = await fetch(`/api/hotlist-jev/series?${params.toString()}`)
    if (!response.ok) {
      return { date: '', slots: [], eod: null, degraded: true, reason: `HTTP ${response.status}` }
    }
    const body = (await response.json()) as {
      ok: boolean
      degraded?: boolean
      reason?: string
      date: string | null
      slots?: HotlistJevDoc[]
      eod?: HotlistJevDoc | null
    }
    if (!body.ok || body.degraded) {
      return { date: '', slots: [], eod: null, degraded: true, reason: body.reason || 'degraded' }
    }
    return {
      date: body.date || '',
      slots: body.slots || [],
      eod: body.eod ?? null,
      degraded: false,
      reason: null,
    }
  } catch (err) {
    return {
      date: '',
      slots: [],
      eod: null,
      degraded: true,
      reason: err instanceof Error ? err.message : 'fetch failed',
    }
  }
}

type HotlistJevRangeDay = NonNullable<HotlistJevRangeResponse['days']>[number]
type HotlistJevRangeMissingDay = Extract<HotlistJevRangeDay, { missing: true }>

function isMissingRangeDay(day: HotlistJevRangeDay): day is HotlistJevRangeMissingDay {
  return (day as { missing?: unknown }).missing === true
}

/**
 * 多日 jev 观察轨道读口（GET /api/hotlist-jev/range）：快照交易日历窗口逐日返回。
 * 缺失日（窗口内无任何 jev 文档）不吞掉，收集进 missingDays 供界面标注；
 * 无兜底计算（结论唯一来源 = QuantBoard 后端 jev 轨道落库）。
 */
export async function fetchHotlistJevRange(
  days = 3,
  datasetId = 'dragonboard_live',
): Promise<HotlistJevRangeResult> {
  const params = new URLSearchParams({ dataset_id: datasetId, days: String(days) })
  try {
    const response = await fetch(`/api/hotlist-jev/range?${params.toString()}`)
    if (!response.ok) {
      return { days: [], missingDays: [], degraded: true, reason: `HTTP ${response.status}`, degradedCount: 0 }
    }
    const body = (await response.json()) as HotlistJevRangeResponse
    if (!body.ok || body.degraded) {
      return {
        days: [],
        missingDays: [],
        degraded: true,
        reason: body.reason || 'degraded',
        degradedCount: 0,
      }
    }
    const dayEntries: HotlistJevDayEntry[] = []
    const missingDays: HotlistJevMissingDay[] = []
    for (const day of body.days || []) {
      if (isMissingRangeDay(day)) {
        missingDays.push({ tradingDate: day.tradingDate || '', reason: day.reason ?? null })
      } else {
        dayEntries.push({
          tradingDate: day.tradingDate || '',
          slots: day.slots || [],
          eod: day.eod ?? null,
        })
      }
    }
    return { days: dayEntries, missingDays, degraded: false, reason: null, degradedCount: body.degradedCount ?? 0 }
  } catch (err) {
    return {
      days: [],
      missingDays: [],
      degraded: true,
      reason: err instanceof Error ? err.message : 'fetch failed',
      degradedCount: 0,
    }
  }
}

// ---------- 复核工作台（W1 辅助线，2026-10-01） ----------
import type {
  JevReviewDay,
  JevReviewItem,
  JevReviewListResult,
  JevReviewRulingStatus,
} from '@/types/hotlistJev'

/**
 * 复核工作台清单（GET /api/hotlist-jev/review-list）：三类复核项按日聚合。
 * 首次调用后端会懒生成（读 frames 较慢），degraded 时如实返回不伪造。
 */
export async function fetchJevReviewList(): Promise<JevReviewListResult> {
  try {
    const response = await fetch('/api/hotlist-jev/review-list')
    if (!response.ok) {
      return { days: [], total: 0, ruled: 0, degraded: true, reason: `HTTP ${response.status}` }
    }
    const body = (await response.json()) as {
      ok: boolean
      degraded?: boolean
      reason?: string
      days?: JevReviewDay[]
      progress?: { total: number; ruled: number }
    }
    if (!body.ok || body.degraded) {
      return { days: [], total: 0, ruled: 0, degraded: true, reason: body.reason || 'degraded' }
    }
    return {
      days: body.days || [],
      total: body.progress?.total ?? 0,
      ruled: body.progress?.ruled ?? 0,
      degraded: false,
      reason: null,
    }
  } catch (err) {
    return {
      days: [],
      total: 0,
      ruled: 0,
      degraded: true,
      reason: err instanceof Error ? err.message : 'fetch failed',
    }
  }
}

/** 复核裁决回填（POST /api/hotlist-jev/review-ruling）；失败返回 null 由调用方提示 */
export async function postJevReviewRuling(
  item: Pick<JevReviewItem, 'id'>,
  status: JevReviewRulingStatus,
  note = '',
): Promise<boolean> {
  try {
    const response = await fetch('/api/hotlist-jev/review-ruling', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: item.id, status, note }),
    })
    const body = (await response.json()) as { ok?: boolean; error?: string }
    return response.ok && body.ok === true
  } catch {
    return false
  }
}

// ---------- 韭研公社异动（W-jiuyan，2026-10-02） ----------
import type { JiuyanActionResult } from '@/types/hotlistJev'

/** 韭研异动读口（纯读）：无 date 返回最新 final + 全部日期索引；degraded 如实返回 */
export async function fetchJiuyanAction(date?: string): Promise<JiuyanActionResult> {
  const params = new URLSearchParams()
  if (date) params.set('date', date)
  try {
    const response = await fetch(`/api/hotlist-jev/jiuyan-action?${params.toString()}`)
    if (!response.ok) {
      return { dates: [], doc: null, degraded: true, reason: `HTTP ${response.status}` }
    }
    const body = (await response.json()) as {
      ok: boolean
      degraded?: boolean
      reason?: string
      dates?: Array<{ date: string; kinds: string[] }>
      doc?: import('@/types/hotlistJev').JiuyanActionDoc | null
    }
    if (!body.ok || body.degraded) {
      return { dates: body.dates || [], doc: null, degraded: true, reason: body.reason || 'degraded' }
    }
    return { dates: body.dates || [], doc: body.doc ?? null, degraded: false, reason: null }
  } catch (err) {
    return { dates: [], doc: null, degraded: true, reason: err instanceof Error ? err.message : 'fetch failed' }
  }
}

/**
 * 情绪概览读口（GET /api/hotlist-jev/sentiment-overview）：市场热度计 + 规则分同包返回。
 * 带 date 取指定交易日（与 hero 规则分对齐用），缺省取最新。
 * 后端降级/异常路径只回 {ok, degraded, reason}（缺 date/jev/rule 键），此处归一化补齐再交付；
 * 无兜底计算（结论唯一来源 = QuantBoard 后端情绪轨道落库）。
 */
export async function fetchHotlistSentimentOverview(date?: string): Promise<HotlistSentimentOverviewResult> {
  const params = new URLSearchParams()
  if (date) params.set('date', date)
  try {
    const response = await fetch(`/api/hotlist-jev/sentiment-overview?${params.toString()}`)
    if (!response.ok) {
      return { ok: false, date: date ?? null, jev: null, rule: null, degraded: true, reason: `HTTP ${response.status}` }
    }
    const body = (await response.json()) as Partial<HotlistSentimentOverviewResult> | null
    return {
      ok: body?.ok === true,
      date: body?.date ?? null,
      jev: body?.jev ?? null,
      rule: body?.rule ?? null,
      degraded: body?.degraded === true,
      reason: body?.reason ?? null,
    }
  } catch (err) {
    return {
      ok: false,
      date: date ?? null,
      jev: null,
      rule: null,
      degraded: true,
      reason: err instanceof Error ? err.message : 'fetch failed',
    }
  }
}

/** 涨停打标轨道中文映射（研究↔展示同步 2026-10-03，题目判据见 docs/hotlist-jev/jev-driver-label-v3-questionset.md） */
export const JEV_DRIVER_NAMES: Record<string, string> = {
  policy: '政策驱动',
  order_earnings: '订单业绩',
  product_event: '产品事件',
  ma_restructure: '重组并购',
  industry_cycle: '行业周期',
  capital_flow: '资金接力',
  concept_stretch: '蹭概念',
  insufficient_evidence: '信息不足',
}

export const JEV_DEPTH_NAMES: Record<string, string> = {
  core_main_business: '核心主业',
  new_business_scaling: '放量承接',
  new_business_early: '早期承接',
  equity_or_affiliate: '股权关联',
  concept_assembly: '概念组装',
  insufficient_evidence: '信息不足',
}

export const JEV_FRESHNESS_NAMES: Record<string, string> = {
  fresh_catalyst: '新催化',
  continuing: '老催化续命',
  none: '无明确催化',
  unclear: '信息不足',
}

export const JEV_BUYSIDE_NAMES: Record<string, string> = {
  independent_catalyst: '独立催化',
  sector_follow: '板块跟随',
  high_board_relay: '高位卡位',
  pure_sentiment: '纯情绪修复',
  insufficient: '信息不足',
}

export const JEV_PHASE_BAND_NAMES: Record<string, string> = {
  cold_lt40: '冷带(<40)',
  weak_40_60: '弱势带(40-60)',
  strong_ge60: '强势带(60+)',
  insufficient: '信息不足',
}

/** 个股相位分线（stock_phase_position 五档，2026-10-04 试点冻结稿；个股自身生命周期位，与市场三带不同层不混词） */
export const JEV_STOCK_PHASE_NAMES: Record<string, string> = {
  start: '低位启动',
  ferment: '中位发酵',
  climax: '高位高潮',
  divergence: '分歧',
  insufficient: '信息不足',
}

/** 涨停打标单日读口（GET /api/hotlist-jev/limitup-labels，纯读 fail-visible） */
export async function fetchHotlistJevLimitUpLabels(
  date: string,
): Promise<{ ok: boolean; degraded: boolean; day: HotlistJevLimitUpDay | null; reason: string | null }> {
  if (!date) return { ok: false, degraded: true, day: null, reason: '缺日期' }
  try {
    const response = await fetch(`/api/hotlist-jev/limitup-labels?date=${encodeURIComponent(date)}`)
    if (!response.ok) {
      return { ok: false, degraded: true, day: null, reason: `HTTP ${response.status}` }
    }
    const body = (await response.json()) as HotlistJevLimitUpDay
    if (!body.ok) {
      return { ok: false, degraded: true, day: null, reason: body.reason || 'degraded' }
    }
    return { ok: true, degraded: false, day: body, reason: null }
  } catch (error) {
    return { ok: false, degraded: true, day: null, reason: String(error) }
  }
}

/**
 * 题材层龙头投喂单日读口（GET /api/hotlist-jev/theme-leaders，纯读 fail-visible）。
 * `withNarrative=true` 时附带叙事全文与题目集原文（前端「投喂语料」抽屉用）。
 */
export async function fetchHotlistJevThemeLeaders(
  date: string,
  withNarrative = false,
): Promise<{ ok: boolean; degraded: boolean; day: HotlistJevThemeLeaderDay | null; reason: string | null }> {
  if (!date) return { ok: false, degraded: true, day: null, reason: '缺日期' }
  try {
    const params = new URLSearchParams({ date })
    if (withNarrative) params.set('with_narrative', '1')
    const response = await fetch(`/api/hotlist-jev/theme-leaders?${params.toString()}`)
    if (!response.ok) {
      return { ok: false, degraded: true, day: null, reason: `HTTP ${response.status}` }
    }
    const body = (await response.json()) as HotlistJevThemeLeaderDay
    if (!body.ok) {
      return { ok: false, degraded: true, day: null, reason: (body as { reason?: string }).reason || 'degraded' }
    }
    return { ok: true, degraded: false, day: body, reason: null }
  } catch (error) {
    return { ok: false, degraded: true, day: null, reason: String(error) }
  }
}
