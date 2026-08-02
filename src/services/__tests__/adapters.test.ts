import { describe, expect, it, vi } from 'vitest'

import { apiService } from '../apiService'
import { Adapters } from '../adapters'

vi.mock('../apiService', () => ({
  apiService: {
    get: vi.fn(),
    post: vi.fn(),
  },
}))

describe('platform adapters fail visible', () => {
  it('eastmoney throws a structured error on a degraded envelope', async () => {
    vi.mocked(apiService.post).mockResolvedValue({
      ok: false,
      degraded: true,
      errorCode: 'upstream_unavailable',
      message: '上游不可用',
      data: [],
    })

    await expect(Adapters.eastmoney.getHotList()).rejects.toMatchObject({
      name: 'PlatformLoadError',
      platform: 'eastmoney',
      errorCode: 'upstream_unavailable',
      message: '上游不可用',
    })
  })

  it('ths returns the stock list from a normal envelope', async () => {
    vi.mocked(apiService.get).mockResolvedValue({
      data: { stock_list: [{ code: '000001', name: '平安银行' }] },
    })

    const rows = await Adapters.ths.getHotList()

    expect(rows).toEqual([{ code: '000001', name: '平安银行' }])
  })

  it('dzh treats a genuinely empty result as empty data, not as failure', async () => {
    vi.mocked(apiService.get).mockResolvedValue({ result: [] })

    const rows = await Adapters.dzh.getHotList()

    expect(rows).toEqual([])
  })

  it('tdx passes through a top-level array payload without misreading it as an envelope', async () => {
    vi.mocked(apiService.post).mockResolvedValue([['0', '', '100']])

    const rows = await Adapters.tdx.getHotList()

    expect(rows).toEqual([['0', '', '100']])
  })
})
