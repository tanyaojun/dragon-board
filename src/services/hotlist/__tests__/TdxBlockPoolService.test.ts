import { describe, expect, it, vi } from 'vitest'

import { TdxBlockPoolService } from '../TdxBlockPoolService'

describe('TdxBlockPoolService', () => {
  it('loads TDX block codes from the proxy and registers them in the shared realtime subscription registry', async () => {
    const api = {
      get: vi.fn(async (url: string) => {
        if (url === '/api/tdx-blocks') {
          return {
            ok: true,
            data: {
              selectedFiles: ['D:\\APP_SOFT\\TDX\\T0002\\blocknew\\自选股.blk'],
              files: [
                {
                  name: '自选股.blk',
                  path: 'D:\\APP_SOFT\\TDX\\T0002\\blocknew\\自选股.blk',
                  stockCount: 2,
                  issueCount: 1,
                },
              ],
              directory: 'D:\\APP_SOFT\\TDX\\T0002\\blocknew',
            },
          }
        }
        if (url.startsWith('/api/tdx-blocks/codes?files=')) {
          return {
            ok: true,
            data: {
              codes: ['300834', '603072', '300834'],
              selectedFiles: ['D:\\APP_SOFT\\TDX\\T0002\\blocknew\\自选股.blk'],
              files: [{ name: '自选股.blk', stockCount: 2, issueCount: 1 }],
              directory: 'D:\\APP_SOFT\\TDX\\T0002\\blocknew',
              issueCount: 1,
            },
          }
        }
        throw new Error(`unexpected url: ${url}`)
      }),
    }
    const registry = {
      setOwnerCodes: vi.fn(),
      clearOwner: vi.fn(),
    }
    const service = new TdxBlockPoolService({ api, registry })

    const result = await service.refresh()

    expect(api.get).toHaveBeenNthCalledWith(1, '/api/tdx-blocks', {
      context: 'tdx',
      timeout: 5000,
      retries: 1,
      silent: true,
    })
    expect(api.get).toHaveBeenNthCalledWith(2, expect.stringMatching(/^\/api\/tdx-blocks\/codes\?files=/), {
      context: 'tdx',
      timeout: 5000,
      retries: 1,
      silent: true,
    })
    expect(result.codes).toEqual(['300834', '603072'])
    expect(result.issueCount).toBe(1)
    expect(service.getCodes()).toEqual(['300834', '603072'])
    expect(registry.setOwnerCodes).toHaveBeenCalledWith('eventRadar.tdxBlock', ['300834', '603072'])
  })

  it('clears the TDX block owner when the proxy cannot load block files', async () => {
    const api = {
      get: vi.fn().mockRejectedValue(new Error('tdx block dir missing')),
    }
    const registry = {
      setOwnerCodes: vi.fn(),
      clearOwner: vi.fn(),
    }
    const service = new TdxBlockPoolService({ api, registry })

    await expect(service.refresh()).rejects.toThrow('tdx block dir missing')

    expect(registry.clearOwner).toHaveBeenCalledWith('eventRadar.tdxBlock')
    expect(service.getCodes()).toEqual([])
  })

  it('clears cached codes and its realtime subscription owner on demand', async () => {
    const api = {
      get: vi.fn().mockResolvedValue({
        ok: true,
        data: { codes: ['300834'], files: [], directory: '', issueCount: 0 },
      }),
    }
    const registry = {
      setOwnerCodes: vi.fn(),
      clearOwner: vi.fn(),
    }
    const service = new TdxBlockPoolService({ api, registry })

    await service.refresh()
    service.clear()

    expect(service.getCodes()).toEqual([])
    expect(registry.clearOwner).toHaveBeenCalledWith('eventRadar.tdxBlock')
  })

  it('can refresh the cached snapshot without applying realtime subscriptions', async () => {
    const api = {
      get: vi.fn().mockResolvedValue({
        ok: true,
        data: { codes: ['300834'], files: [], directory: '', issueCount: 0 },
      }),
    }
    const registry = {
      setOwnerCodes: vi.fn(),
      clearOwner: vi.fn(),
    }
    const service = new TdxBlockPoolService({ api, registry })

    const result = await service.refresh({ apply: false })

    expect(result.codes).toEqual(['300834'])
    expect(service.getCodes()).toEqual(['300834'])
    expect(registry.setOwnerCodes).not.toHaveBeenCalled()
  })

  it('loads desktop selected block files and marks them in the snapshot', async () => {
    const api = {
      get: vi.fn().mockResolvedValue({
        ok: true,
        data: {
          directory: 'D:\\APP_SOFT\\TDX\\T0002\\blocknew',
          selectedFiles: ['D:\\APP_SOFT\\TDX\\T0002\\blocknew\\ZB.blk'],
          files: [
            { name: 'ZB.blk', path: 'D:\\APP_SOFT\\TDX\\T0002\\blocknew\\ZB.blk', stockCount: 3, issueCount: 0, selected: true },
            { name: '观察.blk', path: 'D:\\APP_SOFT\\TDX\\T0002\\blocknew\\观察.blk', stockCount: 2, issueCount: 0, selected: false },
          ],
        },
      }),
    }
    const registry = {
      setOwnerCodes: vi.fn(),
      clearOwner: vi.fn(),
    }
    const service = new TdxBlockPoolService({ api, registry })

    const result = await service.refreshFiles()

    expect(api.get).toHaveBeenCalledWith('/api/tdx-blocks', {
      context: 'tdx',
      timeout: 5000,
      retries: 1,
      silent: true,
    })
    expect(result.selectedFiles).toEqual(['D:\\APP_SOFT\\TDX\\T0002\\blocknew\\ZB.blk'])
    expect(result.files.map(file => ({ name: file.name, selected: file.selected }))).toEqual([
      { name: 'ZB.blk', selected: true },
      { name: '观察.blk', selected: false },
    ])
  })

  it('refreshes TDX block codes from checked block files only', async () => {
    const api = {
      post: vi.fn().mockResolvedValue({
        ok: true,
        data: { selectedFiles: ['D:\\TDX\\观察.blk'] },
      }),
      get: vi.fn(async (url: string) => {
        if (url === '/api/tdx-blocks') {
          return {
            ok: true,
            data: {
              files: [{ name: 'ZB.blk', path: 'D:\\TDX\\ZB.blk', stockCount: 1, issueCount: 0, selected: true }],
              selectedFiles: ['D:\\TDX\\ZB.blk'],
              directory: 'D:\\TDX',
            },
          }
        }
        if (url.includes('ZB.blk')) {
          return {
            ok: true,
            data: {
              codes: ['300834'],
              files: [{ name: 'ZB.blk', path: 'D:\\TDX\\ZB.blk', stockCount: 1, issueCount: 0, selected: true }],
              selectedFiles: ['D:\\TDX\\ZB.blk'],
              directory: 'D:\\TDX',
              issueCount: 0,
            },
          }
        }
        if (url.includes('%E8%A7%82%E5%AF%9F.blk')) {
          return {
            ok: true,
            data: {
              codes: ['603072'],
              files: [{ name: '观察.blk', path: 'D:\\TDX\\观察.blk', stockCount: 1, issueCount: 0, selected: true }],
              selectedFiles: ['D:\\TDX\\观察.blk'],
              directory: 'D:\\TDX',
              issueCount: 0,
            },
          }
        }
        throw new Error(`unexpected url: ${url}`)
      }),
    }
    const registry = {
      setOwnerCodes: vi.fn(),
      clearOwner: vi.fn(),
    }
    const service = new TdxBlockPoolService({ api, registry })

    await service.refresh()
    const result = await service.setSelectedFiles(['D:\\TDX\\观察.blk'])

    expect(api.post).toHaveBeenCalledWith('/api/tdx-blocks/selection', {
      files: ['D:\\TDX\\观察.blk'],
    }, {
      context: 'tdx',
      timeout: 5000,
      retries: 1,
      silent: true,
    })
    expect(api.get).toHaveBeenLastCalledWith('/api/tdx-blocks/codes?files=D%3A%5CTDX%5C%E8%A7%82%E5%AF%9F.blk', {
      context: 'tdx',
      timeout: 5000,
      retries: 1,
      silent: true,
    })
    expect(result.codes).toEqual(['603072'])
    expect(result.selectedFiles).toEqual(['D:\\TDX\\观察.blk'])
    expect(registry.setOwnerCodes).toHaveBeenLastCalledWith('eventRadar.tdxBlock', ['603072'])
  })

  it('keeps the full block file list after refreshing codes from checked files', async () => {
    const api = {
      post: vi.fn().mockResolvedValue({
        ok: true,
        data: { selectedFiles: ['D:\\TDX\\观察.blk'] },
      }),
      get: vi
        .fn()
        .mockResolvedValueOnce({
          ok: true,
          data: {
            directory: 'D:\\TDX',
            selectedFiles: ['D:\\TDX\\ZB.blk'],
            files: [
              { name: 'ZB.blk', path: 'D:\\TDX\\ZB.blk', stockCount: 1, issueCount: 0, selected: true },
              { name: '观察.blk', path: 'D:\\TDX\\观察.blk', stockCount: 1, issueCount: 0, selected: false },
            ],
          },
        })
        .mockResolvedValueOnce({
          ok: true,
          data: {
            codes: ['603072'],
            files: [{ name: '观察.blk', path: 'D:\\TDX\\观察.blk', stockCount: 1, issueCount: 0, selected: true }],
            selectedFiles: ['D:\\TDX\\观察.blk'],
            directory: 'D:\\TDX',
            issueCount: 0,
          },
        }),
    }
    const registry = {
      setOwnerCodes: vi.fn(),
      clearOwner: vi.fn(),
    }
    const service = new TdxBlockPoolService({ api, registry })

    await service.refreshFiles()
    const result = await service.setSelectedFiles(['D:\\TDX\\观察.blk'])

    expect(result.files.map(file => ({ name: file.name, selected: file.selected }))).toEqual([
      { name: 'ZB.blk', selected: false },
      { name: '观察.blk', selected: true },
    ])
  })

  it('restores the full block file list from the file endpoint after selection code refresh', async () => {
    const api = {
      post: vi.fn().mockResolvedValue({
        ok: true,
        data: { selectedFiles: ['D:\\TDX\\ZB.blk'] },
      }),
      get: vi
        .fn()
        .mockResolvedValueOnce({
          ok: true,
          data: {
            codes: ['603072'],
            files: [{ name: 'ZB.blk', path: 'D:\\TDX\\ZB.blk', stockCount: 1, issueCount: 0, selected: true }],
            selectedFiles: ['D:\\TDX\\ZB.blk'],
            directory: 'D:\\TDX',
            issueCount: 0,
          },
        })
        .mockResolvedValueOnce({
          ok: true,
          data: {
            directory: 'D:\\TDX',
            selectedFiles: ['D:\\TDX\\ZB.blk'],
            files: [
              { name: 'ZB.blk', path: 'D:\\TDX\\ZB.blk', stockCount: 1, issueCount: 0, selected: true },
              { name: '观察.blk', path: 'D:\\TDX\\观察.blk', stockCount: 1, issueCount: 0, selected: false },
            ],
          },
        }),
    }
    const registry = {
      setOwnerCodes: vi.fn(),
      clearOwner: vi.fn(),
    }
    const service = new TdxBlockPoolService({ api, registry })

    await service.setSelectedFiles(['D:\\TDX\\ZB.blk'])
    const result = await service.refreshFiles()

    expect(result.files.map(file => file.name)).toEqual(['ZB.blk', '观察.blk'])
  })

  it('keeps an empty checked block file list as an empty realtime pool', async () => {
    const api = {
      post: vi.fn().mockResolvedValue({
        ok: true,
        data: { selectedFiles: [] },
      }),
      get: vi.fn().mockResolvedValue({
        ok: true,
        data: {
          codes: [],
          files: [],
          selectedFiles: [],
          directory: 'D:\\TDX',
          issueCount: 0,
        },
      }),
    }
    const registry = {
      setOwnerCodes: vi.fn(),
      clearOwner: vi.fn(),
    }
    const service = new TdxBlockPoolService({ api, registry })

    await service.setSelectedFiles([])

    expect(api.get).toHaveBeenCalledWith('/api/tdx-blocks/codes?files=', {
      context: 'tdx',
      timeout: 5000,
      retries: 1,
      silent: true,
    })
    expect(registry.setOwnerCodes).toHaveBeenCalledWith('eventRadar.tdxBlock', [])
  })

  it('loads the file selection before the first code refresh so an empty selection stays empty', async () => {
    const api = {
      get: vi.fn(async (url: string) => {
        if (url === '/api/tdx-blocks') {
          return {
            ok: true,
            data: {
              directory: 'D:\\TDX',
              selectedFiles: [],
              files: [
                { name: 'ZB.blk', path: 'D:\\TDX\\ZB.blk', stockCount: 1, issueCount: 0, selected: false },
              ],
            },
          }
        }
        if (url === '/api/tdx-blocks/codes?files=') {
          return {
            ok: true,
            data: {
              codes: [],
              files: [],
              selectedFiles: [],
              directory: 'D:\\TDX',
              issueCount: 0,
            },
          }
        }
        throw new Error(`unexpected url: ${url}`)
      }),
    }
    const registry = {
      setOwnerCodes: vi.fn(),
      clearOwner: vi.fn(),
    }
    const service = new TdxBlockPoolService({ api, registry })

    const result = await service.refresh()

    expect(result.codes).toEqual([])
    expect(api.get).toHaveBeenNthCalledWith(1, '/api/tdx-blocks', {
      context: 'tdx',
      timeout: 5000,
      retries: 1,
      silent: true,
    })
    expect(api.get).toHaveBeenNthCalledWith(2, '/api/tdx-blocks/codes?files=', {
      context: 'tdx',
      timeout: 5000,
      retries: 1,
      silent: true,
    })
    expect(registry.setOwnerCodes).toHaveBeenCalledWith('eventRadar.tdxBlock', [])
  })
})
