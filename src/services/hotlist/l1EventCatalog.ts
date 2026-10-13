/**
 * L1 异动事件目录：与 tools/YiDongJingLing/Settings/EventCatalog.cs 完全对齐的单一事实源。
 * 枚举名、中文名、说明、默认语音开关、严重度与评分全部镜像 C# 侧，禁止两处分叉。
 */

export type L1EventTypeName =
  | 'LimitUpSealed'
  | 'LimitUpOpened'
  | 'UpcomingLimitUpOpen'
  | 'NearLimitUp'
  | 'LimitDownSealed'
  | 'LimitDownOpened'
  | 'UpcomingLimitDownOpen'
  | 'NearLimitDown'
  | 'SealOrderIncreased'
  | 'SealOrderWeakened'
  | 'BigRiseTier'
  | 'BigDropTier'
  | 'FastRise'
  | 'FastDrop'
  | 'TurnRed'
  | 'TurnGreen'
  | 'IntradayHigh'
  | 'IntradayLow'
  | 'AmountTier'
  | 'VolumeAcceleration'
  | 'LargeBidOrder'
  | 'LargeAskOrder'
  | 'LowOpenLongYang'
  | 'HighOpenLongYin'
  | 'NewStockOpened'
  | 'NewStockReseal'
  | 'LimitUpResealed'
  | 'SectorRush'
  | 'SectorDive'
  | 'SectorLimitUpWave'
  | 'SectorLimitUpOpenWave'
  | 'BidPressure'
  | 'AskPressure'
  | 'SpreadWidened'

export type L1EventSeverity = 'normal' | 'important' | 'critical'

export interface L1EventRecord {
  type: L1EventTypeName
  typeName: string
  code: string
  name: string
  price: number
  changePct: number
  volume: number
  amount: number
  timestamp: number
  severity: L1EventSeverity
  reason: string
  sector: string
  memberCodes: string[]
}

export interface L1EventCatalogEntry {
  type: L1EventTypeName
  label: string
  note: string
  defaultVoice: boolean
}

export const L1_EVENT_CATALOG: readonly L1EventCatalogEntry[] = [
  { type: 'LimitUpSealed', label: '封涨停板', note: '涨停价+买一封单', defaultVoice: true },
  { type: 'LimitUpOpened', label: '打开涨停板', note: '跌离涨停封单', defaultVoice: true },
  { type: 'UpcomingLimitUpOpen', label: '即将打开涨停', note: '买一封单骤降', defaultVoice: true },
  { type: 'NearLimitUp', label: '逼近涨停', note: '距涨停1%内', defaultVoice: true },
  { type: 'LimitDownSealed', label: '封跌停板', note: '跌停价+卖一封单', defaultVoice: true },
  { type: 'LimitDownOpened', label: '打开跌停板', note: '脱离跌停封单', defaultVoice: true },
  { type: 'UpcomingLimitDownOpen', label: '即将打开跌停', note: '卖一封单骤降', defaultVoice: true },
  { type: 'NearLimitDown', label: '逼近跌停', note: '距跌停1%内', defaultVoice: true },
  { type: 'LimitUpResealed', label: '涨停回封', note: '打开后重新封回', defaultVoice: true },
  { type: 'SealOrderIncreased', label: '封单增强', note: '封单较前帧增50%', defaultVoice: true },
  { type: 'SealOrderWeakened', label: '封单变弱', note: '封单较前帧减半', defaultVoice: true },
  { type: 'BigRiseTier', label: '大幅拉升', note: '当日涨幅破阈值', defaultVoice: true },
  { type: 'BigDropTier', label: '大幅跳水', note: '当日跌幅破阈值', defaultVoice: true },
  { type: 'FastRise', label: '快速拉升', note: '30/60秒或5分钟急涨', defaultVoice: true },
  { type: 'FastDrop', label: '快速跳水', note: '30/60秒或5分钟急跌', defaultVoice: true },
  { type: 'LowOpenLongYang', label: '低开长阳', note: '低开后大幅拉起', defaultVoice: true },
  { type: 'HighOpenLongYin', label: '高开长阴', note: '高开后大幅回落', defaultVoice: true },
  { type: 'NewStockOpened', label: '新股开板', note: '冲高回落破阈值', defaultVoice: true },
  { type: 'NewStockReseal', label: '新股开板回封', note: '回撤收窄至高点附近', defaultVoice: true },
  { type: 'SectorRush', label: '板块拉升', note: '成员普涨且均涨破阈值', defaultVoice: true },
  { type: 'SectorDive', label: '板块跳水', note: '成员普跌且均跌破阈值', defaultVoice: true },
  { type: 'SectorLimitUpWave', label: '板块涨停潮', note: '窗口内多只成员封板', defaultVoice: true },
  { type: 'SectorLimitUpOpenWave', label: '板块开板潮', note: '窗口内多只成员开板', defaultVoice: true },
  { type: 'TurnRed', label: '翻红', note: '涨跌幅由负转正', defaultVoice: false },
  { type: 'TurnGreen', label: '翻绿', note: '涨跌幅由正转负', defaultVoice: false },
  { type: 'IntradayHigh', label: '创日内新高', note: '刷新启动后高点', defaultVoice: false },
  { type: 'IntradayLow', label: '创日内新低', note: '刷新启动后低点', defaultVoice: false },
  { type: 'AmountTier', label: '成交额跨档', note: '累计成交额破门槛', defaultVoice: false },
  { type: 'VolumeAcceleration', label: '成交增量加速', note: '近30秒成交量放大', defaultVoice: false },
  { type: 'LargeBidOrder', label: '出现大买挂盘', note: '买一挂单额过大', defaultVoice: false },
  { type: 'LargeAskOrder', label: '出现大卖挂盘', note: '卖一挂单额过大', defaultVoice: false },
  { type: 'BidPressure', label: '盘口买压增强', note: '五档买量压卖量', defaultVoice: false },
  { type: 'AskPressure', label: '盘口卖压增强', note: '五档卖量压买量', defaultVoice: false },
  { type: 'SpreadWidened', label: '买卖价差异常', note: '买卖一价差过大', defaultVoice: false },
] as const

const CATALOG_BY_TYPE = new Map<string, L1EventCatalogEntry>(
  L1_EVENT_CATALOG.map(entry => [entry.type as string, entry]),
)

export function getL1EventCatalogEntry(type: L1EventTypeName): L1EventCatalogEntry | undefined {
  return CATALOG_BY_TYPE.get(type)
}

export function defaultVoiceEventSet(): Set<string> {
  return new Set(
    L1_EVENT_CATALOG.filter(entry => entry.defaultVoice).map(entry => entry.type as string),
  )
}

export function buildL1EventRecord(
  record: Omit<L1EventRecord, 'sector' | 'memberCodes'> &
    Partial<Pick<L1EventRecord, 'sector' | 'memberCodes'>>,
): L1EventRecord {
  return {
    sector: '',
    memberCodes: [],
    ...record,
  }
}

export function isSectorEvent(record: L1EventRecord): boolean {
  return record.sector.length > 0
}

export function buildDedupeKey(record: L1EventRecord): string {
  return record.sector.length > 0
    ? `S:${record.sector}:${record.type}`
    : `${record.code}:${record.type}`
}

/** 严重度×事件类型评分，镜像 EventDeduper.Score（Critical=300/Important=200/其余100 + 类型分）。 */
export function eventScore(record: L1EventRecord): number {
  const severityScore = record.severity === 'critical'
    ? 300
    : record.severity === 'important'
      ? 200
      : 100

  const typeScore: Partial<Record<L1EventTypeName, number>> = {
    LimitUpSealed: 50,
    LimitUpOpened: 45,
    NewStockOpened: 44,
    NewStockReseal: 43,
    LimitUpResealed: 47,
    UpcomingLimitUpOpen: 43,
    LimitDownSealed: 44,
    LimitDownOpened: 42,
    UpcomingLimitDownOpen: 41,
    FastRise: 35,
    FastDrop: 34,
    NearLimitUp: 30,
    NearLimitDown: 28,
    BigRiseTier: 25,
    BigDropTier: 24,
    SectorLimitUpWave: 46,
    SectorLimitUpOpenWave: 42,
    SectorRush: 26,
    SectorDive: 25,
  }

  return severityScore + (typeScore[record.type] ?? 0)
}
