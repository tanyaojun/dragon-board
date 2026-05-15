import { describe, expect, it, vi } from 'vitest'

import { HotStockEventSpeechService } from '../HotStockEventSpeechService'
import type { HotStockAbnormalEvent } from '../hotStockEventTypes'

function makeEvent(overrides: Partial<HotStockAbnormalEvent>): HotStockAbnormalEvent {
  return {
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
    matchedHotStock: true,
    matchedCandidate: overrides.matchedCandidate || false,
    raw: overrides.raw || {},
  }
}

function createSpeechMock() {
  const speak = vi.fn((utterance: SpeechSynthesisUtterance) => {
    utterance.onend?.({} as SpeechSynthesisEvent)
  })
  const utteranceFactory = vi.fn((text: string) => ({ text } as SpeechSynthesisUtterance))
  return {
    speech: {
      speak,
      cancel: vi.fn(),
      getVoices: vi.fn().mockReturnValue([{ lang: 'zh-CN' }]),
    } as unknown as SpeechSynthesis,
    utteranceFactory,
    speak,
  }
}

describe('HotStockEventSpeechService', () => {
  it('skips initial events and speaks only new unseen events', () => {
    const { speech, speak, utteranceFactory } = createSpeechMock()
    const service = new HotStockEventSpeechService({ speechSynthesis: speech, utteranceFactory })

    service.handleLatestAdded([makeEvent({ id: 'a', name: '首批股' })])
    service.handleLatestAdded([makeEvent({ id: 'a', name: '首批股' })])
    service.handleLatestAdded([makeEvent({ id: 'b', name: '中南文化', typeName: '即将打开涨停' })])

    expect(speak).toHaveBeenCalledTimes(1)
    expect(speak.mock.calls[0][0].text).toContain('中南文化即将打开涨停')
  })

  it('merges at most three new events into one announcement', () => {
    const { speech, speak, utteranceFactory } = createSpeechMock()
    const service = new HotStockEventSpeechService({ speechSynthesis: speech, utteranceFactory })

    service.handleLatestAdded([makeEvent({ id: 'seed' })])
    service.handleLatestAdded([
      makeEvent({ id: 'a', name: '一号', typeName: '大幅拉升' }),
      makeEvent({ id: 'b', name: '二号', typeName: '逼近涨停' }),
      makeEvent({ id: 'c', name: '三号', typeName: '打开涨停板' }),
      makeEvent({ id: 'd', name: '四号', typeName: '封涨停板' }),
    ])

    expect(speak).toHaveBeenCalledTimes(1)
    expect(speak.mock.calls[0][0].text).toBe('新增4条热榜异动，一号大幅拉升，二号逼近涨停，三号打开涨停板')
  })

  it('test speak reads a fixed test phrase', () => {
    const { speech, speak, utteranceFactory } = createSpeechMock()
    const service = new HotStockEventSpeechService({ speechSynthesis: speech, utteranceFactory })

    service.speakTest()

    expect(speak).toHaveBeenCalledTimes(1)
    expect(speak.mock.calls[0][0].text).toContain('热榜异动语音测试')
  })
})
