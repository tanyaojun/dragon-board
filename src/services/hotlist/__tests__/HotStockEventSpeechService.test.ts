import { describe, expect, it, vi } from 'vitest'

import {
  HotStockEventSpeechService,
  buildRemoteSpeechText,
  isSpeechEligibleHotStockEvent,
  resolveSpeechVoiceSelection,
} from '../HotStockEventSpeechService'
import { EventDeduper, buildSpeechItems, buildSpeechTextForEvent } from '../EventDeduper'
import { filterForVoice, isStrongSignal, voiceModeDisplayName } from '../EventVoicePolicy'
import { buildL1EventRecord, type L1EventRecord } from '../l1EventCatalog'
import type { HotStockAbnormalEvent } from '../hotStockEventTypes'

function makeL1Event(overrides: Partial<L1EventRecord> = {}): L1EventRecord {
  return buildL1EventRecord({
    type: 'LimitUpSealed',
    typeName: '封涨停板',
    code: '600001',
    name: '测试股',
    price: 10,
    changePct: 9.95,
    volume: 100,
    amount: 1_000_000,
    timestamp: Date.parse('2026-10-13T10:00:00+08:00'),
    severity: 'critical',
    reason: '买一封单 1200万',
    ...overrides,
  })
}

function makeEvent(overrides: Partial<HotStockAbnormalEvent>): HotStockAbnormalEvent {
  return {
    category: overrides.category || 'stock',
    id: String(overrides.id || 'event-1'),
    eventType: overrides.eventType || overrides.type || 10001,
    type: overrides.type || 10001,
    typeName: overrides.typeName || '封涨停板',
    direction: overrides.direction || 'up',
    severity: overrides.severity || 'normal',
    timestamp: overrides.timestamp || Date.parse('2026-05-15T10:00:00+08:00'),
    code: overrides.code || '600001',
    name: overrides.name || '测试股',
    changePct: overrides.changePct ?? 0.0954,
    price: overrides.price ?? 10,
    relatedPlates: overrides.relatedPlates || [],
    sectorName: overrides.sectorName || '',
    matchedHotStock: true,
    matchedCandidate: overrides.matchedCandidate || false,
    raw: overrides.raw || {},
  }
}

function createLocalVoiceMock(response: Partial<Response> = { ok: true }) {
  return vi.fn(async () => response as Response)
}

function spokenTexts(fetcher: ReturnType<typeof createLocalVoiceMock>): string[] {
  return fetcher.mock.calls
    .filter(([url]) => url === '/api/local-voice/speak')
    .map(([, init]) => (JSON.parse(String((init as RequestInit).body)) as { text: string }).text)
}

describe('HotStockEventSpeechService（零丢失语义，对齐 SpeechAnnouncer.cs）', () => {
  it('首批只记录不播报，其后每条事件独立成句（不合并、不同股压缩）', async () => {
    const fetcher = createLocalVoiceMock()
    const service = new HotStockEventSpeechService({ fetcher })

    await service.handleLatestAdded([makeEvent({ id: 'a', name: '首批股' })])
    await service.handleLatestAdded([
      makeEvent({ id: 'b', name: '中南文化', code: '002445', typeName: '即将打开涨停', changePct: 0.0954 }),
      makeEvent({ id: 'c', name: '中南文化', code: '002445', typeName: '封涨停板', changePct: 0.1001 }),
    ])
    await service.whenIdle()

    const texts = spokenTexts(fetcher)
    expect(texts).toHaveLength(2)
    expect(texts[0]).toBe('中南文化，即将打开涨停，涨幅9.54%')
    expect(texts[1]).toBe('中南文化，封涨停板，涨幅10.01%')
  })

  it('L1 事件：Critical 抢占先清队列再播报，其余按时间序零丢失', async () => {
    const fetcher = createLocalVoiceMock()
    const service = new HotStockEventSpeechService({ fetcher })
    // 越过首批静默
    service.announceL1Events([makeL1Event({ timestamp: 1 })])
    fetcher.mock.calls.length = 0

    const base = Date.parse('2026-10-13T10:00:00+08:00')
    service.announceL1Events([
      makeL1Event({ type: 'FastRise', typeName: '快速拉升', severity: 'important', changePct: 5.2, timestamp: base, code: '000002', name: 'A股' }),
      makeL1Event({ type: 'SectorLimitUpWave', typeName: '板块涨停潮', severity: 'critical', timestamp: base + 1000, code: '', name: '算力', sector: '算力' }),
      makeL1Event({ type: 'LimitUpSealed', typeName: '2连板', severity: 'critical', timestamp: base + 2000, code: '600001', name: '测试股' }),
    ])
    await service.whenIdle()

    const urls = fetcher.mock.calls.map(([url]) => url)
    expect(urls[0]).toBe('/api/local-voice/stop')
    const texts = spokenTexts(fetcher)
    expect(texts).toEqual([
      '算力，板块涨停潮',
      '测试股，2连板，买一封单 1200万',
      'A股，快速拉升，涨幅5.2%',
    ])
  })

  it('同一事件（类型+主体+时间戳）不重复播报', async () => {
    const fetcher = createLocalVoiceMock()
    const service = new HotStockEventSpeechService({ fetcher })
    service.announceL1Events([makeL1Event({ timestamp: 1 })])
    fetcher.mock.calls.length = 0

    // 同类型+同主体+同时间戳 → 同一事件，不重复播报
    service.announceL1Events([makeL1Event({ timestamp: 1 })])
    await service.whenIdle()
    expect(spokenTexts(fetcher)).toHaveLength(0)
  })

  it('setDisabled 后不播报', async () => {
    const fetcher = createLocalVoiceMock()
    const service = new HotStockEventSpeechService({ fetcher })
    service.announceL1Events([makeL1Event({ timestamp: 1 })])
    service.setEnabled(false)
    fetcher.mock.calls.length = 0
    service.announceL1Events([makeL1Event({ timestamp: 2 })])
    await service.handleLatestAdded([makeEvent({ id: 'a' })])
    await service.whenIdle()
    expect(fetcher.mock.calls.filter(([url]) => url === '/api/local-voice/speak')).toHaveLength(0)
  })

  it('远端事件文本：比率口径换算百分数', () => {
    expect(buildRemoteSpeechText(makeEvent({ changePct: 0.0954 }))).toBe('测试股，封涨停板，涨幅9.54%')
    expect(buildRemoteSpeechText(makeEvent({ changePct: -0.031 }))).toBe('测试股，封涨停板，涨幅-3.1%')
    const noPct = makeEvent({})
    noPct.changePct = null
    expect(buildRemoteSpeechText(noPct)).toBe('测试股，封涨停板')
  })
})

describe('EventDeduper（对齐 EventDeduper.cs）', () => {
  it('语音文本：封板类带原因、快拉快跳带涨幅、其余仅名称+类型', () => {
    expect(buildSpeechTextForEvent(makeL1Event({ type: 'LimitUpSealed', typeName: '2连板' })))
      .toBe('测试股，2连板，买一封单 1200万')
    expect(buildSpeechTextForEvent(makeL1Event({ type: 'LimitUpResealed', typeName: '涨停回封' })))
      .toBe('测试股，涨停回封，买一封单 1200万')
    expect(buildSpeechTextForEvent(makeL1Event({ type: 'FastRise', typeName: '快速拉升', severity: 'important', changePct: 5.2 })))
      .toBe('测试股，快速拉升，涨幅5.2%')
    expect(buildSpeechTextForEvent(makeL1Event({ type: 'BigRiseTier', typeName: '大幅拉升', severity: 'important' })))
      .toBe('测试股，大幅拉升')
  })

  it('buildSpeechItems 按时间升序逐条成句', () => {
    const items = buildSpeechItems([
      makeL1Event({ timestamp: 2, type: 'FastDrop', typeName: '快速跳水', severity: 'important', changePct: -3 }),
      makeL1Event({ timestamp: 1 }),
    ])
    expect(items).toEqual([
      '测试股，封涨停板，买一封单 1200万',
      '测试股，快速跳水，涨幅-3%',
    ])
  })

  it('状态变化类 30s 冷却、噪声类 180s 冷却', () => {
    const deduper = new EventDeduper()
    const t0 = Date.parse('2026-10-13T10:00:00+08:00')
    expect(deduper.filter([makeL1Event({ timestamp: t0 })])).toHaveLength(1)
    expect(deduper.filter([makeL1Event({ timestamp: t0 + 29_000 })])).toHaveLength(0)
    expect(deduper.filter([makeL1Event({ timestamp: t0 + 30_000 })])).toHaveLength(1)

    expect(deduper.filter([makeL1Event({ type: 'BigRiseTier', severity: 'important', timestamp: t0 })])).toHaveLength(1)
    expect(deduper.filter([makeL1Event({ type: 'BigRiseTier', severity: 'important', timestamp: t0 + 179_000 })])).toHaveLength(0)
    expect(deduper.filter([makeL1Event({ type: 'BigRiseTier', severity: 'important', timestamp: t0 + 180_000 })])).toHaveLength(1)
  })

  it('板块事件 DedupeKey 与个股互不影响，输出按评分降序', () => {
    const deduper = new EventDeduper()
    const t0 = Date.parse('2026-10-13T10:00:00+08:00')
    const sectorWave = makeL1Event({ type: 'SectorLimitUpWave', typeName: '板块涨停潮', code: '', name: '算力', sector: '算力', timestamp: t0 })
    const stockSeal = makeL1Event({ timestamp: t0 })
    const sorted = deduper.filter([stockSeal, sectorWave])
    // 评分：封板 300+50=350 > 板块涨停潮 300+46=346
    expect(sorted[0].type).toBe('LimitUpSealed')
    expect(sorted[1].type).toBe('SectorLimitUpWave')

    // LowOpenLongYang 233 / HighOpenLongYin 232（C# EventDeduper.Score 齐全）
    const lowYang = makeL1Event({ type: 'LowOpenLongYang', severity: 'important', timestamp: t0 + 1 })
    const highYin = makeL1Event({ type: 'HighOpenLongYin', severity: 'important', timestamp: t0 + 2 })
    const nearUp = makeL1Event({ type: 'NearLimitUp', severity: 'important', timestamp: t0 + 3 })
    const ranked = deduper.filter([lowYang, highYin, nearUp])
    expect(ranked.map(item => item.type)).toEqual(['LowOpenLongYang', 'HighOpenLongYin', 'NearLimitUp'])
  })
})

describe('EventVoicePolicy（两层模型，对齐 EventVoicePolicy.cs）', () => {
  const events = [
    makeL1Event({ type: 'LimitUpSealed', severity: 'critical' }),
    makeL1Event({ type: 'BigRiseTier', severity: 'important', timestamp: 2 }),
    makeL1Event({ type: 'BidPressure', severity: 'normal', timestamp: 3 }),
  ]

  it('muted 全静音；all 全播；strongOnly 滤掉 normal 与盘口噪声', () => {
    expect(filterForVoice(events, 'muted')).toHaveLength(0)
    expect(filterForVoice(events, 'all')).toHaveLength(3)
    const strong = filterForVoice(events, 'strongOnly')
    expect(strong.map(item => item.type)).toEqual(['LimitUpSealed', 'BigRiseTier'])
  })

  it('VoiceEvents 数值码键与类型名键双向兼容（面板持久化键空间）', () => {
    const byCode = new Map<string, boolean>([
      ['13013', true], // FastRise
      ['13011', false], // BigRiseTier
    ])
    const fastRise = makeL1Event({ type: 'FastRise', typeName: '快速拉升', severity: 'important' })
    const riseTier = makeL1Event({ type: 'BigRiseTier', typeName: '大幅拉升', severity: 'important', timestamp: 2 })
    const filtered = filterForVoice([fastRise, riseTier], 'all', { voiceEvents: byCode })
    expect(filtered.map(item => item.type)).toEqual(['FastRise'])
  })

  it('VoiceEvents 白名单优先（只影响语音层）；空名单跟随模式', () => {
    const whitelist = new Map<string, boolean>([
      ['LimitUpSealed', true],
      ['BigRiseTier', false],
      ['BidPressure', false],
    ])
    expect(filterForVoice(events, 'all', { voiceEvents: whitelist }).map(item => item.type))
      .toEqual(['LimitUpSealed'])
    expect(filterForVoice(events, 'strongOnly', { voiceEvents: new Map() })).toHaveLength(2)
  })

  it('IsStrongSignal 排除盘口噪声五类', () => {
    expect(isStrongSignal(makeL1Event({ type: 'LargeAskOrder', severity: 'normal' }))).toBe(false)
    expect(isStrongSignal(makeL1Event({ type: 'SealOrderIncreased', severity: 'important' }))).toBe(true)
    expect(voiceModeDisplayName('all')).toBe('播报全部')
    expect(voiceModeDisplayName('muted')).toBe('静音')
    expect(voiceModeDisplayName('strongOnly')).toBe('只播强信号')
  })
})

describe('竞价弱转强语音门禁（保留既有语义）', () => {
  it('voiceEligible + gapAlert/trendConfirm 才可播', () => {
    expect(isSpeechEligibleHotStockEvent(makeEvent({
      type: 12001,
      raw: { signal: { voiceEligible: true, stage: 'gapAlert' } },
    }))).toBe(true)
    expect(isSpeechEligibleHotStockEvent(makeEvent({
      type: 12001,
      raw: { signal: { voiceEligible: true, stage: 'auctionConditionPassed' } },
    }))).toBe(false)
    expect(isSpeechEligibleHotStockEvent(makeEvent({ type: 10001 }))).toBe(true)
  })
})

describe('语音选项解析', () => {
  it('resolveSpeechVoiceSelection 保持既有行为', () => {
    const voices = [{ name: 'Huihui' }, { name: 'Kangkang' }]
    expect(resolveSpeechVoiceSelection('Huihui', undefined, voices)).toBe('Huihui')
    expect(resolveSpeechVoiceSelection(undefined, 'Kangkang', voices)).toBe('Kangkang')
    expect(resolveSpeechVoiceSelection('Ghost', 'Kangkang', voices)).toBe('Kangkang')
    expect(resolveSpeechVoiceSelection(undefined, undefined, voices)).toBeUndefined()
  })
})
