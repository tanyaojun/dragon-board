import { describe, expect, it, vi } from 'vitest'

import { OpeningSignalClient } from '../OpeningSignalClient'

describe('OpeningSignalClient', () => {
  it('loads today opening weak-to-strong signals by code', async () => {
    const fetcher = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        ok: true,
        signals: [
          {
            canonicalSignal: {
                code: '002552',
                name: '宝鼎科技',
                stage: 'gapAlert',
                status: 'gapAlert',
              time: '2026-05-22T09:30:06+08:00',
              price: 10.35,
              pct: 3.5,
              amount: 8_000_000,
                voiceEligible: true,
              reason: '09:30较09:25出现跳空高开缺口',
            },
          },
        ],
      }),
    })
    const client = new OpeningSignalClient({ fetcher })

    const signals = await client.fetchTodaySignals('2026-05-22')

    expect(fetcher).toHaveBeenCalledWith('/api/opening-signals/today?tradingDate=2026-05-22')
    expect(signals.get('002552')).toMatchObject({
      code: '002552',
      stage: 'gapAlert',
      voiceEligible: true,
    })
  })

  it('posts opening weak-to-strong signal and returns voice owner', async () => {
    const fetcher = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        ok: true,
        accepted: true,
        isNew: true,
        voiceOwner: 'web',
        dedupeAction: 'created',
      }),
    })
    const client = new OpeningSignalClient({ fetcher })

    const response = await client.postSignal('web', {
      code: '002552',
      name: '宝鼎科技',
      stage: 'gapAlert',
      status: 'gapAlert',
      voiceEligible: true,
      time: '2026-05-22T09:30:06+08:00',
      price: 10.35,
      pct: 3.5,
      amount: 8_000_000,
      reason: '09:30较09:25出现跳空高开缺口',
    })

    expect(fetcher).toHaveBeenCalledWith('/api/opening-signals', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: expect.stringContaining('"source":"web"'),
    })
    expect(response).toMatchObject({
      ok: true,
      accepted: true,
      voiceOwner: 'web',
    })
  })
})
