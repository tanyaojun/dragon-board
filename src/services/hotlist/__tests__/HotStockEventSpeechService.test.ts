import { describe, expect, it, vi } from 'vitest'

import {
  HotStockEventSpeechService,
  isSpeechEligibleHotStockEvent,
  resolveSpeechVoiceSelection,
  selectSpeechEvents,
} from '../HotStockEventSpeechService'
import type { HotStockAbnormalEvent } from '../hotStockEventTypes'

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

describe('HotStockEventSpeechService', () => {
  it('skips initial events and sends new event to local voice first', async () => {
    const fetcher = createLocalVoiceMock()
    const service = new HotStockEventSpeechService({ fetcher, flushDelayMs: 0 })

    await service.handleLatestAdded([makeEvent({ id: 'a', name: '首批股' })])
    await service.handleLatestAdded([
      makeEvent({ id: 'b', name: '中南文化', code: '002445', typeName: '即将打开涨停' }),
    ])

    expect(fetcher).toHaveBeenCalledTimes(1)
    expect(fetcher).toHaveBeenCalledWith('/api/local-voice/speak', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        text: '热榜异动，中南文化即将打开涨停，涨幅9.54%',
        rate: 1,
        volume: 100,
        voice: undefined,
      }),
    })
  })

  it('does not fall back to browser speech when local voice request fails', async () => {
    const speak = vi.fn()
    const fetcher = vi.fn(async () => {
      throw new Error('local voice offline')
    })
    const service = new HotStockEventSpeechService({
      fetcher,
      flushDelayMs: 0,
    })

    await service.speakTest()

    expect(fetcher).toHaveBeenCalledWith('/api/local-voice/test', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ rate: 1, volume: 100, voice: undefined }),
    })
    expect(speak).not.toHaveBeenCalled()
    expect(service.getStatus()).toEqual({ mode: 'offline', supported: false, queueLength: 0 })
  })

  it('keeps only the highest priority event for the same stock inside one batch', async () => {
    const fetcher = createLocalVoiceMock()
    const service = new HotStockEventSpeechService({ fetcher, flushDelayMs: 0 })

    await service.handleLatestAdded([makeEvent({ id: 'seed' })])
    await service.handleLatestAdded([
      makeEvent({ id: 'weak', code: '002445', name: '中南文化', type: 10009, eventType: 10009, typeName: '大幅拉升' }),
      makeEvent({
        id: 'strong',
        code: '002445',
        name: '中南文化',
        type: 10007,
        eventType: 10007,
        typeName: '即将打开涨停',
      }),
      makeEvent({ id: 'other', code: '300001', name: '特锐德', type: 10005, eventType: 10005, typeName: '逼近涨停' }),
    ])

    const body = JSON.parse(String(fetcher.mock.calls[0][1]?.body))
    expect(body.text).toBe('新增2条热榜异动，中南文化即将打开涨停，特锐德逼近涨停')
  })

  it('reports local voice support status', async () => {
    const fetcher = vi.fn(async () => ({
      ok: true,
      json: async () => ({ ok: true, supported: true, engine: 'volcengine', queueLength: 0 }),
    }) as Response)
    const service = new HotStockEventSpeechService({ fetcher })

    const status = await service.refreshStatus()

    expect(status).toEqual({
      mode: 'local',
      supported: true,
      engine: 'volcengine',
      queueLength: 0,
      voice: undefined,
      voices: [],
    })
  })

  it('merges at most three new events into one announcement', async () => {
    const fetcher = createLocalVoiceMock()
    const service = new HotStockEventSpeechService({
      fetcher,
      flushDelayMs: 0,
    })

    await service.handleLatestAdded([makeEvent({ id: 'seed' })])
    await service.handleLatestAdded([
      makeEvent({ id: 'a', code: '600001', name: '一号', typeName: '大幅拉升' }),
      makeEvent({ id: 'b', code: '600002', name: '二号', typeName: '逼近涨停' }),
      makeEvent({ id: 'c', code: '600003', name: '三号', typeName: '打开涨停板' }),
      makeEvent({ id: 'd', code: '600004', name: '四号', typeName: '封涨停板' }),
    ])

    expect(fetcher).toHaveBeenCalledTimes(1)
    expect(JSON.parse(String(fetcher.mock.calls[0][1]?.body)).text).toBe(
      '新增4条热榜异动，一号大幅拉升，二号逼近涨停，三号打开涨停板',
    )
  })

  it('test speak uses local voice endpoint only', async () => {
    const fetcher = createLocalVoiceMock()
    const service = new HotStockEventSpeechService({ fetcher })

    service.setVoiceOptions({ rate: 0.8, volume: 55 })
    await service.speakTest()

    expect(fetcher).toHaveBeenCalledWith('/api/local-voice/test', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ rate: 0.8, volume: 55, voice: undefined }),
    })
  })

  it('passes configured rate and volume to local voice', async () => {
    const fetcher = createLocalVoiceMock()
    const service = new HotStockEventSpeechService({ fetcher, flushDelayMs: 0 })

    service.setVoiceOptions({ rate: 0.8, volume: 55 })
    await service.handleLatestAdded([makeEvent({ id: 'seed' })])
    await service.handleLatestAdded([makeEvent({ id: 'next', name: '中南文化' })])

    expect(JSON.parse(String(fetcher.mock.calls[0][1]?.body))).toEqual({
      text: '热榜异动，中南文化封涨停板，涨幅9.54%',
      rate: 0.8,
      volume: 55,
      voice: undefined,
    })
  })

  it('passes selected SAPI voice to local voice', async () => {
    const fetcher = createLocalVoiceMock()
    const service = new HotStockEventSpeechService({ fetcher, flushDelayMs: 0 })

    service.setVoiceOptions({ voice: 'Microsoft Kangkang' })
    await service.handleLatestAdded([makeEvent({ id: 'seed' })])
    await service.handleLatestAdded([makeEvent({ id: 'next', name: '中南文化' })])

    expect(JSON.parse(String(fetcher.mock.calls[0][1]?.body))).toEqual({
      text: '热榜异动，中南文化封涨停板，涨幅9.54%',
      rate: 1,
      volume: 100,
      voice: 'Microsoft Kangkang',
    })
  })

  it('resets selected voice when status no longer reports that voice', () => {
    expect(
      resolveSpeechVoiceSelection('Microsoft Kangkang', 'Microsoft Huihui Desktop', [
        { name: 'Microsoft Huihui Desktop', culture: 'zh-CN', gender: 'Female' },
        { name: 'Microsoft Zira Desktop', culture: 'en-US', gender: 'Female' },
      ]),
    ).toBe('Microsoft Huihui Desktop')
  })

  it('does not use proxy voice owner as opening signal speech gate', () => {
    expect(
      isSpeechEligibleHotStockEvent(makeEvent({
        type: 12001,
        eventType: 12001,
        typeName: '竞价弱转强',
        raw: {
          voiceOwner: 'desktop',
          signal: {
            stage: 'gapAlert',
            voiceEligible: true,
          },
        },
      })),
    ).toBe(true)

    expect(
      isSpeechEligibleHotStockEvent(makeEvent({
        type: 12001,
        eventType: 12001,
        typeName: '竞价弱转强候选',
        raw: {
          voiceOwner: 'web',
          signal: {
            stage: 'auctionConditionPassed',
            voiceEligible: false,
          },
        },
      })),
    ).toBe(false)

    expect(
      isSpeechEligibleHotStockEvent(makeEvent({
        type: 12001,
        eventType: 12001,
        typeName: '竞价弱转强',
        raw: {
          openingSignalPost: { voiceOwner: 'web' },
          signal: {
            stage: 'trendWeak',
            voiceEligible: false,
          },
        },
      })),
    ).toBe(false)
  })

  it('only voices 09:30 gap alerts and 09:35 trend confirmations for opening signals', () => {
    const stageEvent = (stage: string, voiceEligible: boolean) => makeEvent({
      type: 12001,
      eventType: 12001,
      typeName: '竞价弱转强',
      raw: { signal: { stage, voiceEligible } },
    })

    expect(isSpeechEligibleHotStockEvent(stageEvent('gapAlert', true))).toBe(true)
    expect(isSpeechEligibleHotStockEvent(stageEvent('trendConfirm', true))).toBe(true)
    expect(isSpeechEligibleHotStockEvent(stageEvent('auctionConditionPassed', false))).toBe(false)
    expect(isSpeechEligibleHotStockEvent(stageEvent('noGap', false))).toBe(false)
    expect(isSpeechEligibleHotStockEvent(stageEvent('trendWeak', false))).toBe(false)
    expect(isSpeechEligibleHotStockEvent(stageEvent('optionalFinalStatus', false))).toBe(false)
  })

  it('includes opening weak-to-strong hits outside the hot-stock page for speech', () => {
    const hot = makeEvent({ id: 'hot', code: '600001', typeName: '逼近涨停' })
    const tdxOpening = makeEvent({
      id: 'opening_weak_to_strong:2026-05-22:002552:pending',
      code: '002552',
      type: 12001,
      eventType: 12001,
      typeName: '竞价弱转强',
      matchedHotStock: false,
      raw: {
        signal: {
          stage: 'gapAlert',
          voiceEligible: true,
        },
      },
    })
    const tdxOrdinary = makeEvent({
      id: 'tdx-ordinary',
      code: '300001',
      typeName: '大幅拉升',
      matchedHotStock: false,
    })

    expect(selectSpeechEvents([tdxOrdinary, tdxOpening, hot], [hot]).map(event => event.id)).toEqual([
      'hot',
      'opening_weak_to_strong:2026-05-22:002552:pending',
    ])
  })
})
