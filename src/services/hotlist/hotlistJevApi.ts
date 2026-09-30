// src/services/hotlist/hotlistJevApi.ts
// 薄 API client：jev 热榜情绪观察轨道读口（GET /api/hotlist-jev/series）。
// 只做 fetch + 类型化，无兜底计算（结论唯一来源 = QuantBoard 后端 jev 轨道落库）。
import type {
  HotlistJevDoc,
  HotlistJevDayEntry,
  HotlistJevMissingDay,
  HotlistJevRangeResponse,
  HotlistJevRangeResult,
  HotlistJevSeriesResult,
} from '@/types/hotlistJev'

/** jev 五档英文值 → 展示中文（与规则轨道五档同词汇，判定彼此独立） */
export const JEV_STAGE_NAMES: Record<string, string> = {
  ice: '冰点',
  start: '启动',
  ferment: '发酵',
  climax: '高潮',
  retreat: '退潮',
}

/** 日级路径形态七类 → 展示中文 */
export const JEV_PATTERN_NAMES: Record<string, string> = {
  steady_strong: '全天强势主导',
  steady_weak: '全天弱势主导',
  rally_fade: '冲高回落',
  low_recover: '低开修复',
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
      return { days: [], missingDays: [], degraded: true, reason: `HTTP ${response.status}` }
    }
    const body = (await response.json()) as HotlistJevRangeResponse
    if (!body.ok || body.degraded) {
      return {
        days: [],
        missingDays: [],
        degraded: true,
        reason: body.reason || 'degraded',
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
    return { days: dayEntries, missingDays, degraded: false, reason: null }
  } catch (err) {
    return {
      days: [],
      missingDays: [],
      degraded: true,
      reason: err instanceof Error ? err.message : 'fetch failed',
    }
  }
}
