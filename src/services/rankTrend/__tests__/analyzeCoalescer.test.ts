import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { apiService } from '../../apiService'
import { analyzeRankTrendCoalesced, resetAnalyzeCoalescer } from '../analyzeCoalescer'

const okResponse = { ok: true, frames: [], source: 'py_golden', issues: [] }

describe('analyzeRankTrendCoalesced', () => {
  let captured: Array<Record<string, unknown>>
  let resolvers: Array<(value: unknown) => void>
  let rejecters: Array<(reason: unknown) => void>

  beforeEach(() => {
    resetAnalyzeCoalescer()
    captured = []
    resolvers = []
    rejecters = []
    vi.spyOn(apiService, 'analyzeRankTrend').mockImplementation(
      (payload: Record<string, unknown>) =>
        new Promise((resolve, reject) => {
          captured.push(payload)
          resolvers.push(resolve)
          rejecters.push(reject)
        }),
    )
  })

  afterEach(() => {
    vi.restoreAllMocks()
    resetAnalyzeCoalescer()
  })

  it('并发调用合并为最新一次运行，且所有调用都拿到结果', async () => {
    const p1 = analyzeRankTrendCoalesced({ codes: ['a'] })
    const p2 = analyzeRankTrendCoalesced({ codes: ['b'] })
    const p3 = analyzeRankTrendCoalesced({ codes: ['c'] })

    expect(captured.length).toBe(1)
    expect(captured[0].codes).toEqual(['a'])

    resolvers[0](okResponse)
    await Promise.resolve()
    await Promise.resolve()

    expect(captured.length).toBe(2)
    expect(captured[1].codes).toEqual(['c'])

    resolvers[1]({ ...okResponse, frames: [{ code: 'c' }] })

    const [r1, r2, r3] = await Promise.all([p1, p2, p3])
    expect(r1).toEqual(okResponse)
    expect(r2).toEqual(r3)
    expect(r3.frames?.[0]?.code).toBe('c')
  })

  it('串行调用每次都独立运行', async () => {
    const p1 = analyzeRankTrendCoalesced({ codes: ['a'] })
    resolvers[0](okResponse)
    await p1

    const p2 = analyzeRankTrendCoalesced({ codes: ['b'] })
    resolvers[1](okResponse)
    await p2

    expect(captured.length).toBe(2)
  })

  it('前一次失败后，待处理的最新请求仍会运行并拿到结果', async () => {
    const p1 = analyzeRankTrendCoalesced({ codes: ['a'] })
    const p2 = analyzeRankTrendCoalesced({ codes: ['b'] })

    rejecters[0](new Error('backend offline'))
    await expect(p1).rejects.toThrow('backend offline')
    await Promise.resolve()
    await Promise.resolve()

    expect(captured.length).toBe(2)
    resolvers[1]({ ...okResponse, frames: [{ code: 'b' }] })

    await expect(p2).resolves.toMatchObject({ frames: [{ code: 'b' }] })
  })
})
