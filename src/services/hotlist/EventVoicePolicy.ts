/**
 * 语音层过滤策略：与 tools/YiDongJingLing/Events/EventVoicePolicy.cs 完全一致。
 * 两层模型：
 * - 产生层（EnabledEvents）：事件根本不产生/不展示，由设置层在引擎输出后过滤；
 * - 语音层（VoiceEvents 白名单）：只静音语音，表格/推送不受影响；空集合 = 未固化，沿用历史行为。
 */
import { L1_EVENT_TYPE_CODES, l1TypeNameByNumericCode, type L1EventRecord, type L1EventTypeName } from './l1EventCatalog'

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

const NUMERIC_KEY_PATTERN = /^\d+$/

/**
 * 键归一化：类型名直查；13xxx 数值码键反查类型名后等价查询。
 * C# 两侧均名称键（EventVoicePolicy.cs / AppSettings.IsVoiceEventEnabled），
 * TS 面板持久化用数值码键——此处双向兼容，避免键空间断裂。
 */
function lookup(map: Map<string, boolean>, typeName: L1EventTypeName): boolean | undefined {
  const direct = map.get(typeName)
  if (direct !== undefined) return direct
  const numeric = String(L1_EVENT_TYPE_CODES[typeName])
  const byCode = map.get(numeric)
  if (byCode !== undefined) return byCode
  return undefined
}

export function isVoiceEventEnabled(eventName: string, settings: VoiceLayerSettings): boolean {
  const typeName = NUMERIC_KEY_PATTERN.test(eventName)
    ? l1TypeNameByNumericCode(eventName) ?? eventName
    : eventName
  const enabled = lookup(settings.voiceEvents, typeName as L1EventTypeName)
  return enabled === undefined ? true : enabled
}

export function isEventEnabled(eventName: string, enabledEvents: Map<string, boolean>): boolean {
  const typeName = NUMERIC_KEY_PATTERN.test(eventName)
    ? l1TypeNameByNumericCode(eventName) ?? eventName
    : eventName
  const enabled = lookup(enabledEvents, typeName as L1EventTypeName)
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
