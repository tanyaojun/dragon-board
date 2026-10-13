/**
 * 语音层过滤策略：与 tools/YiDongJingLing/Events/EventVoicePolicy.cs 完全一致。
 * 两层模型：
 * - 产生层（EnabledEvents）：事件根本不产生/不展示，由设置层在引擎输出后过滤；
 * - 语音层（VoiceEvents 白名单）：只静音语音，表格/推送不受影响；空集合 = 未固化，沿用历史行为。
 */
import type { L1EventRecord } from './l1EventCatalog'

export type VoiceMode = 'strongOnly' | 'all' | 'muted'

/** 默认强信号排除集：IsStrongSignal 中被点名排除的盘口噪声事件。 */
const STRONG_SIGNAL_EXCLUDED_TYPES = new Set<string>([
  'BidPressure',
  'AskPressure',
  'SpreadWidened',
  'LargeBidOrder',
  'LargeAskOrder',
])

export interface VoiceLayerSettings {
  /** 语音层白名单：键存在以键为准；空 Map = 未固化勾选。 */
  voiceEvents: Map<string, boolean>
}

export function isStrongSignal(item: L1EventRecord): boolean {
  return (
    (item.severity === 'critical' || item.severity === 'important') &&
    !STRONG_SIGNAL_EXCLUDED_TYPES.has(item.type)
  )
}

export function filterForVoice(
  events: readonly L1EventRecord[],
  mode: VoiceMode,
  settings?: VoiceLayerSettings,
): L1EventRecord[] {
  if (mode === 'muted') return []
  if (settings && settings.voiceEvents.size > 0) {
    return events.filter(item => isVoiceEventEnabled(item.type, settings))
  }
  if (mode === 'all') return [...events]
  return events.filter(item => isStrongSignal(item))
}

export function isVoiceEventEnabled(eventName: string, settings: VoiceLayerSettings): boolean {
  const enabled = settings.voiceEvents.get(eventName)
  return enabled === undefined ? true : enabled
}

export function isEventEnabled(eventName: string, enabledEvents: Map<string, boolean>): boolean {
  const enabled = enabledEvents.get(eventName)
  return enabled === undefined ? true : enabled
}

export function voiceModeDisplayName(mode: VoiceMode): string {
  switch (mode) {
    case 'all':
      return '播报全部'
    case 'muted':
      return '静音'
    default:
      return '只播强信号'
  }
}
