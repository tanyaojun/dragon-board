import { describe, expect, it, vi } from 'vitest'

import { ConceptMapLoader, parseConceptMapPayload, sectorsOf } from '../ConceptMapLoader'

function jsonResponse(body: unknown, ok = true): Response {
  return { ok, json: async () => body } as Response
}

function fullPayload(refreshing = false) {
  return {
    ok: true,
    refreshing,
    fetchedAt: '2026-10-13T05:23:20.907113+00:00',
    conceptCount: 2,
    stockCount: 3,
    data: [
      { code: 'BK0425', name: '工程建设', changePct: 0.86, stocks: [{ code: '920964' }, { code: '920149' }] },
      { code: 'BK0000', name: '空板块', changePct: 0, stocks: [] },
    ],
  }
}

describe('ConceptMapLoader（对齐 ConceptMapLoader.cs 后台刷新协议）', () => {
  it('refreshing=true 时轮询等待直到拿到全量映射', async () => {
    const storage = memoryStorage()
    const fetcher = vi.fn()
      .mockResolvedValueOnce(jsonResponse(fullPayload(true)))
      .mockResolvedValueOnce(jsonResponse(fullPayload(true)))
      .mockResolvedValueOnce(jsonResponse(fullPayload(false)))
    const loader = new ConceptMapLoader({ fetcher, storage, maxAttempts: 5, retryDelayMs: 0 })

    const outcome = await loader.load()
    expect(fetcher).toHaveBeenCalledTimes(3)
    expect(outcome.refreshed).toBe(true)
    expect(outcome.sectorToStocks.get('工程建设')).toEqual(['920964', '920149'])
    expect(outcome.conceptCount).toBe(2)
    // 空板块成员缺失进 errors（失败可见）
    expect(outcome.errors.some(item => item.includes('no_valid_members'))).toBe(true)
  })

  it('服务端失败回退本地缓存并标记 stale + serving_local_cache', async () => {
    const storage = memoryStorage()
    storage.setItem('yidongjingling.concept-map-cache.v1', JSON.stringify({ savedAt: 1, payload: fullPayload(false) }))
    const fetcher = vi.fn().mockRejectedValue(new Error('server down'))
    const loader = new ConceptMapLoader({ fetcher, storage, maxAttempts: 2, retryDelayMs: 0 })

    const outcome = await loader.load()
    expect(outcome.stale).toBe(true)
    expect(outcome.sectorToStocks.size).toBe(1)
    expect(outcome.errors).toContain('serving_local_cache')
    expect(outcome.errors.some(item => item.startsWith('server_unavailable'))).toBe(true)
  })

  it('损坏缓存自愈（删除后回退空映射，不抛错）', async () => {
    const storage = memoryStorage()
    storage.setItem('yidongjingling.concept-map-cache.v1', '{broken json')
    const fetcher = vi.fn().mockRejectedValue(new Error('server down'))
    const loader = new ConceptMapLoader({ fetcher, storage, maxAttempts: 1, retryDelayMs: 0 })

    const outcome = await loader.load()
    expect(outcome.sectorToStocks.size).toBe(0)
    expect(outcome.stale).toBe(false)
    expect(storage.getItem('yidongjingling.concept-map-cache.v1')).toBeNull()
  })

  it('成功后写入缓存；反向索引 stockToSectors 正确', async () => {
    const storage = memoryStorage()
    const fetcher = vi.fn().mockResolvedValue(jsonResponse(fullPayload(false)))
    const loader = new ConceptMapLoader({ fetcher, storage, maxAttempts: 1, retryDelayMs: 0 })

    const outcome = await loader.load()
    expect(storage.getItem('yidongjingling.concept-map-cache.v1')).toBeTruthy()
    expect(sectorsOf(outcome, '920964')).toEqual(['工程建设'])
  })

  it('parseConceptMapPayload：空/坏载荷返回 null', () => {
    expect(parseConceptMapPayload(null)).toBeNull()
    expect(parseConceptMapPayload({ ok: false })).toBeNull()
    expect(parseConceptMapPayload({ data: [] })).toBeNull()
  })
})

function memoryStorage(): Storage {
  const map = new Map<string, string>()
  return {
    getItem: (key: string) => map.get(key) ?? null,
    setItem: (key: string, value: string) => void map.set(key, value),
    removeItem: (key: string) => void map.delete(key),
    clear: () => void map.clear(),
    key: () => null,
    length: 0,
  }
}
