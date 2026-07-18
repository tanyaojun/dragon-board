import { afterEach, describe, expect, it, vi } from 'vitest'

import { sendHotlistSelection } from '../ThsBigOrderFollowBridge'

describe('ThsBigOrderFollowBridge', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('posts normalized selected stock data to the local listener', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true })
    vi.stubGlobal('fetch', fetchMock)

    sendHotlistSelection('SZ000001', '平安银行')
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledOnce())

    expect(fetchMock).toHaveBeenCalledWith(
      'http://127.0.0.1:38891/hotlist/selection',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ code: '000001', name: '平安银行' }),
      }),
    )
  })

  it('ignores invalid stock codes', () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)

    sendHotlistSelection('123', '无效')

    expect(fetchMock).not.toHaveBeenCalled()
  })
})
