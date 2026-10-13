/**
 * 事件去重器：与 tools/YiDongJingLing/Events/EventDeduper.cs 语义一致。
 * 状态变化类事件 30s 冷却、噪声类 180s；同键在冷却窗内只发一次；
 * 输出按 严重度+类型 评分降序、时间降序排列。
 * 语音文本构建也在此（BuildSpeechItems：零丢失、逐条成句），与 C# BuildSpeechTextForEvent 逐字对齐。
 */
import {
  buildDedupeKey,
  eventScore,
  type L1EventRecord,
  type L1EventTypeName,
} from './l1EventCatalog'
import { NOISE_COOLDOWN_MS, STATE_CHANGE_COOLDOWN_MS } from './l1EventRules'

const STATE_CHANGE_TYPES = new Set<L1EventTypeName>([
  'LimitUpSealed',
  'LimitUpOpened',
  'UpcomingLimitUpOpen',
  'LimitDownSealed',
  'LimitDownOpened',
  'UpcomingLimitDownOpen',
  'NearLimitUp',
  'NearLimitDown',
  'FastRise',
  'FastDrop',
  'TurnRed',
  'TurnGreen',
  'IntradayHigh',
  'IntradayLow',
  'LowOpenLongYang',
  'HighOpenLongYin',
  'NewStockOpened',
  'NewStockReseal',
  'LimitUpResealed',
])

export class EventDeduper {
  private readonly lastEmittedAt = new Map<string, number>()
  private readonly stateChangeCooldownMs: number
  private readonly noiseCooldownMs: number

  constructor(options: { stateChangeCooldownMs?: number; noiseCooldownMs?: number } = {}) {
    this.stateChangeCooldownMs = options.stateChangeCooldownMs ?? STATE_CHANGE_COOLDOWN_MS
    this.noiseCooldownMs = options.noiseCooldownMs ?? NOISE_COOLDOWN_MS
  }

  clear() {
    this.lastEmittedAt.clear()
  }

  filter(events: readonly L1EventRecord[]): L1EventRecord[] {
    const result: L1EventRecord[] = []
    for (const item of events) {
      if (!this.canEmit(item)) continue
      this.lastEmittedAt.set(buildDedupeKey(item), item.timestamp)
      result.push(item)
    }

    return result
      .sort((a, b) => {
        const scoreDelta = eventScore(b) - eventScore(a)
        return scoreDelta !== 0 ? scoreDelta : b.timestamp - a.timestamp
      })
  }

  private canEmit(item: L1EventRecord): boolean {
    const key = buildDedupeKey(item)
    const last = this.lastEmittedAt.get(key)
    if (last === undefined) return true
    return item.timestamp - last >= this.cooldownFor(item.type)
  }

  private cooldownFor(type: L1EventTypeName): number {
    return STATE_CHANGE_TYPES.has(type) ? this.stateChangeCooldownMs : this.noiseCooldownMs
  }
}

const SEALED_SPEECH_TYPES = new Set<L1EventTypeName>(['LimitUpSealed', 'LimitDownSealed', 'LimitUpResealed'])
const SPEAK_CHANGE_PCT_TYPES = new Set<L1EventTypeName>(['FastRise', 'FastDrop'])

/** 单条事件语音文本：与 EventDeduper.BuildSpeechTextForEvent 逐字一致。 */
export function buildSpeechTextForEvent(item: L1EventRecord): string {
  const displayName = item.name || item.code
  if (SEALED_SPEECH_TYPES.has(item.type)) {
    return `${displayName}，${item.typeName}，${item.reason}`
  }
  if (SPEAK_CHANGE_PCT_TYPES.has(item.type)) {
    return `${displayName}，${item.typeName}，涨幅${formatPct(item.changePct)}`
  }
  return `${displayName}，${item.typeName}`
}

/** 批量语音条目：按时间升序逐条成句（零丢失，不合并）。 */
export function buildSpeechItems(events: readonly L1EventRecord[]): string[] {
  return [...events]
    .sort((a, b) => a.timestamp - b.timestamp)
    .map(item => buildSpeechTextForEvent(item))
}

function formatPct(value: number): string {
  if (!Number.isFinite(value)) return '未知'
  return `${value.toFixed(2).replace(/\.?0+$/, '')}%`
}
