import { afterEach, describe, expect, it, vi } from 'vitest'

import { HotStockEventMonitorService } from '../HotStockEventMonitorService'
import { refreshScheduler, refreshTaskRegistry } from '../../refresh/RefreshTaskRuntime'
import type { HotStockAbnormalEvent } from '../hotStockEventTypes'

function makeEvent(overrides: Partial<HotStockAbnormalEvent>): HotStockAbnormalEvent {
  return {
    category: overrides.category || 'stock',
    id: String(overrides.id || `${overrides.type || 10001}-${overrides.code || '000001'}`),
    eventType: overrides.eventType || overrides.type || 10001,
    type: overrides.type || 10001,
    typeName: overrides.typeName || '火箭发射',
    direction: overrides.direction || 'up',
    severity: overrides.severity || 'normal',
    timestamp: overrides.timestamp || Date.parse('2026-05-15T10:00:00+08:00'),
    code: overrides.code || '000001',
    name: overrides.name || '测试股',
    changePct: overrides.changePct || 0,
    price: overrides.price || 10,
    relatedPlates: overrides.relatedPlates || [],
    sectorName: overrides.sectorName || '',
    matchedHotStock: false,
    matchedCandidate: false,
    raw: overrides.raw || {},
  }
}

function makeTdxBlockPool(codes: string[] = []) {
  return {
    getCodes: vi.fn().mockReturnValue(codes),
    refresh: vi.fn().mockResolvedValue({ codes }),
    refreshFiles: vi.fn().mockResolvedValue({ codes, files: [], selectedFiles: [] }),
    setSelectedFiles: vi.fn().mockResolvedValue({ codes, files: [], selectedFiles: [] }),
    clear: vi.fn(),
    applyCodes: vi.fn(),
  }
}

describe('HotStockEventMonitorService', () => {
  afterEach(() => {
    refreshScheduler.stopTask('hotStockEvent.monitor')
    refreshTaskRegistry.resetRuntimeState()
    vi.useRealTimers()
  })

  it('splits today events into hot stocks, other stocks and sectors', async () => {
    const feed = {
      fetchEvents: vi.fn().mockResolvedValue([
        makeEvent({ id: 'old', code: '600001', timestamp: Date.parse('2026-05-14T14:00:00+08:00') }),
        makeEvent({ id: 'a', code: '600001', timestamp: Date.parse('2026-05-15T09:40:00+08:00') }),
        makeEvent({ id: 'a', code: '600001', timestamp: Date.parse('2026-05-15T09:41:00+08:00') }),
        makeEvent({ id: 'b', code: '000002.SZ', timestamp: Date.parse('2026-05-15T10:01:00+08:00') }),
        makeEvent({ id: 'c', code: '300001', timestamp: Date.parse('2026-05-15T10:02:00+08:00') }),
        makeEvent({
          id: 'sector-a',
          category: 'sector',
          code: '',
          name: '',
          sectorName: '机器人',
          type: 11000,
          eventType: 11000,
          typeName: '板块拉升',
          timestamp: Date.parse('2026-05-15T10:03:00+08:00'),
        }),
      ]),
    }
    const dataLayer = {
      getStocks: vi.fn().mockReturnValue([
        { code: '600001', name: '一号' },
        { code: '000002', name: '二号' },
      ]),
      getDragonReview: vi.fn().mockReturnValue({
        candidates: [{ code: '600001' }],
        trueLeaders: [{ code: '000003' }],
        attentionBoard: [],
      }),
    }
    const tdxBlockPool = makeTdxBlockPool(['300001'])
    const service = new HotStockEventMonitorService({
      feed,
      dataLayer,
      tdxBlockPool,
      now: () => Date.parse('2026-05-15T10:05:00+08:00'),
    })

    const result = await service.refresh()

    expect(result.ok).toBe(true)
    expect(result.added).toBe(4)
    expect(result.watchedCodes).toEqual(['600001', '000002'])
    expect(result.hotStockEvents.map(event => event.id)).toEqual(['b', 'a'])
    expect(result.otherStockEvents.map(event => event.id)).toEqual(['c'])
    expect(result.sectorEvents.map(event => event.id)).toEqual(['sector-a'])
    expect(result.events.map(event => event.id)).toEqual(['sector-a', 'c', 'b', 'a'])
    expect(result.hotStockEvents[0]).toMatchObject({
      code: '000002',
      matchedHotStock: true,
      matchedCandidate: false,
    })
    expect(result.hotStockEvents[1]).toMatchObject({
      code: '600001',
      matchedHotStock: true,
      matchedCandidate: true,
    })
    expect(result.otherStockEvents[0]).toMatchObject({
      code: '300001',
      matchedHotStock: false,
      matchedCandidate: false,
    })
    expect(result.sectorEvents[0]).toMatchObject({
      category: 'sector',
      sectorName: '机器人',
      matchedHotStock: false,
      matchedCandidate: false,
    })
    expect(service.getState().latestHotStockAdded.map(event => event.id)).toEqual(['b', 'a'])
  })

  it('uses TDX block codes for the second stock page instead of showing all non-hot stocks', async () => {
    const feed = {
      fetchEvents: vi.fn().mockResolvedValue([
        makeEvent({ id: 'hot', code: '600001', timestamp: Date.parse('2026-05-15T09:40:00+08:00') }),
        makeEvent({ id: 'tdx', code: '300001', timestamp: Date.parse('2026-05-15T10:02:00+08:00') }),
        makeEvent({ id: 'outside', code: '688001', timestamp: Date.parse('2026-05-15T10:03:00+08:00') }),
      ]),
    }
    const dataLayer = {
      getStocks: vi.fn().mockReturnValue([{ code: '600001', name: '一号' }]),
      getDragonReview: vi.fn().mockReturnValue(null),
    }
    const tdxBlockPool = makeTdxBlockPool(['300001'])
    const service = new HotStockEventMonitorService({
      feed,
      dataLayer,
      tdxBlockPool,
      now: () => Date.parse('2026-05-15T10:05:00+08:00'),
    })

    const result = await service.refresh()

    expect(result.hotStockEvents.map(event => event.id)).toEqual(['hot'])
    expect(result.otherStockEvents.map(event => event.id)).toEqual(['tdx'])
    expect(result.events.map(event => event.id)).toEqual(['outside', 'tdx', 'hot'])
    expect(result.tdxBlockCodes).toEqual(['300001'])
    expect(service.getState().tdxBlockCodes).toEqual(['300001'])
  })

  it('preserves previous events when feed fails', async () => {
    const firstFeed = {
      fetchEvents: vi.fn().mockResolvedValue([
        makeEvent({ id: 'a', code: '600001', timestamp: Date.parse('2026-05-15T09:40:00+08:00') }),
      ]),
    }
    const dataLayer = {
      getStocks: vi.fn().mockReturnValue([{ code: '600001', name: '一号' }]),
      getDragonReview: vi.fn().mockReturnValue(null),
    }
    const service = new HotStockEventMonitorService({
      feed: firstFeed,
      dataLayer,
      tdxBlockPool: makeTdxBlockPool(),
      now: () => Date.parse('2026-05-15T10:05:00+08:00'),
    })

    await service.refresh()
    service.setFeed({
      fetchEvents: vi.fn().mockRejectedValue(new Error('network')),
    })
    const result = await service.refresh()

    expect(result.ok).toBe(false)
    expect(result.added).toBe(0)
    expect(result.error).toBe('network')
    expect(result.events.map(event => event.id)).toEqual(['a'])
    expect(result.hotStockEvents.map(event => event.id)).toEqual(['a'])
  })

  it('pushes only newly added hot stock events after the first refresh when feishu owner is active', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('document', { visibilityState: 'visible' })
    const notifier = {
      sendEvents: vi.fn().mockResolvedValue({ ok: true, sent: 1 }),
    }
    const feed = {
      fetchEvents: vi
        .fn()
        .mockResolvedValueOnce([
          makeEvent({ id: 'a', code: '600001', timestamp: Date.parse('2026-05-15T09:40:00+08:00') }),
        ])
        .mockResolvedValueOnce([
          makeEvent({ id: 'a', code: '600001', timestamp: Date.parse('2026-05-15T09:40:00+08:00') }),
          makeEvent({ id: 'b', code: '000002', timestamp: Date.parse('2026-05-15T10:01:00+08:00') }),
          makeEvent({ id: 'c', code: '300001', timestamp: Date.parse('2026-05-15T10:02:00+08:00') }),
        ]),
    }
    const dataLayer = {
      getStocks: vi.fn().mockReturnValue([
        { code: '600001', name: '一号' },
        { code: '000002', name: '二号' },
      ]),
      getDragonReview: vi.fn().mockReturnValue(null),
    }
    const service = new HotStockEventMonitorService({
      feed,
      dataLayer,
      tdxBlockPool: makeTdxBlockPool(),
      notifier,
      now: () => Date.parse('2026-05-15T10:05:00+08:00'),
    })

    service.start('feishu')
    await service.refresh()
    await service.refresh()

    expect(notifier.sendEvents).toHaveBeenCalledTimes(1)
    expect(notifier.sendEvents).toHaveBeenCalledWith([
      expect.objectContaining({ id: 'b', code: '000002', matchedHotStock: true }),
    ])
    service.stop('feishu')
  })

  it('does not push feishu events from panel-only polling', async () => {
    const notifier = {
      sendEvents: vi.fn().mockResolvedValue({ ok: true, sent: 1 }),
    }
    const feed = {
      fetchEvents: vi
        .fn()
        .mockResolvedValueOnce([])
        .mockResolvedValueOnce([
          makeEvent({ id: 'a', code: '600001', timestamp: Date.parse('2026-05-15T09:40:00+08:00') }),
        ]),
    }
    const dataLayer = {
      getStocks: vi.fn().mockReturnValue([{ code: '600001', name: '一号' }]),
      getDragonReview: vi.fn().mockReturnValue(null),
    }
    const service = new HotStockEventMonitorService({
      feed,
      dataLayer,
      tdxBlockPool: makeTdxBlockPool(),
      notifier,
      now: () => Date.parse('2026-05-15T10:05:00+08:00'),
    })

    await service.refresh()
    await service.refresh()

    expect(notifier.sendEvents).not.toHaveBeenCalled()
  })

  it('accepts realtime derived opening weak-to-strong events without HTTP feed involvement', async () => {
    const feed = {
      fetchEvents: vi.fn().mockResolvedValue([
        makeEvent({
          id: 'http-limitup',
          code: '600001',
          type: 10005,
          eventType: 10005,
          typeName: '逼近涨停',
          timestamp: Date.parse('2026-05-22T09:30:30+08:00'),
        }),
      ]),
    }
    const dataLayer = {
      getStocks: vi.fn().mockReturnValue([{ code: '002552', name: '宝鼎科技' }]),
      getDragonReview: vi.fn().mockReturnValue(null),
    }
    const tdxBlockPool = makeTdxBlockPool(['600001'])
    const service = new HotStockEventMonitorService({
      feed,
      dataLayer,
      tdxBlockPool,
      now: () => Date.parse('2026-05-22T09:31:00+08:00'),
    })

    service.acceptDerivedEvents([
      makeEvent({
        id: 'opening_weak_to_strong:2026-05-22:002552',
        code: '002552',
        name: '宝鼎科技',
        type: 12001,
        eventType: 12001,
        typeName: '竞价弱转强',
        timestamp: Date.parse('2026-05-22T09:30:06+08:00'),
        raw: { source: 'opening_weak_to_strong_v3' },
      }),
    ])
    const result = await service.refresh()

    expect(result.ok).toBe(true)
    expect(feed.fetchEvents).toHaveBeenCalledTimes(1)
    expect(result.hotStockEvents.map(event => event.typeName)).toEqual(['竞价弱转强'])
    expect(result.otherStockEvents.map(event => event.typeName)).toEqual(['逼近涨停'])
    expect(result.events.some(event => event.typeName === '竞价弱转强')).toBe(true)
    expect(result.events.some(event => event.typeName === 'opening_weak_to_strong')).toBe(false)
  })

  it('still shows realtime derived opening events when HTTP feed is unavailable', async () => {
    const feed = {
      fetchEvents: vi.fn().mockRejectedValue(new Error('http feed offline')),
    }
    const dataLayer = {
      getStocks: vi.fn().mockReturnValue([{ code: '002552', name: '宝鼎科技' }]),
      getDragonReview: vi.fn().mockReturnValue(null),
    }
    const service = new HotStockEventMonitorService({
      feed,
      dataLayer,
      tdxBlockPool: makeTdxBlockPool(),
      now: () => Date.parse('2026-05-22T09:31:00+08:00'),
    })

    service.acceptDerivedEvents([
      makeEvent({
        id: 'opening_weak_to_strong:2026-05-22:002552',
        code: '002552',
        name: '宝鼎科技',
        type: 12001,
        eventType: 12001,
        typeName: '竞价弱转强',
        timestamp: Date.parse('2026-05-22T09:30:06+08:00'),
        raw: { source: 'opening_weak_to_strong_v3' },
      }),
    ])
    const result = await service.refresh()

    expect(result.ok).toBe(false)
    expect(result.error).toBe('http feed offline')
    expect(result.events.map(event => event.typeName)).toEqual(['竞价弱转强'])
    expect(result.hotStockEvents.map(event => event.code)).toEqual(['002552'])
  })

  it('keeps refresh successful when event radar notification fails', async () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const notifier = {
      sendEvents: vi.fn().mockRejectedValue(new Error('feishu offline')),
    }
    const feed = {
      fetchEvents: vi
        .fn()
        .mockResolvedValueOnce([])
        .mockResolvedValueOnce([
          makeEvent({ id: 'a', code: '600001', timestamp: Date.parse('2026-05-15T09:40:00+08:00') }),
        ]),
    }
    const dataLayer = {
      getStocks: vi.fn().mockReturnValue([{ code: '600001', name: '一号' }]),
      getDragonReview: vi.fn().mockReturnValue(null),
    }
    const service = new HotStockEventMonitorService({
      feed,
      dataLayer,
      tdxBlockPool: makeTdxBlockPool(),
      notifier,
      now: () => Date.parse('2026-05-15T10:05:00+08:00'),
    })

    await service.refresh()
    const result = await service.refresh()

    expect(result.ok).toBe(true)
    expect(result.hotStockEvents.map(event => event.id)).toEqual(['a'])
    expect(notifier.sendEvents).not.toHaveBeenCalled()
    warnSpy.mockRestore()
  })

  it('runs panel polling through the shared scheduler and pauses when hidden', async () => {
    vi.useFakeTimers()
    const visibility = { visibilityState: 'hidden' }
    vi.stubGlobal('document', visibility)
    const feed = {
      fetchEvents: vi.fn().mockResolvedValue([
        makeEvent({ id: 'a', code: '600001', timestamp: Date.parse('2026-05-15T09:40:00+08:00') }),
      ]),
    }
    const dataLayer = {
      getStocks: vi.fn().mockReturnValue([{ code: '600001', name: '一号' }]),
      getDragonReview: vi.fn().mockReturnValue(null),
    }
    const service = new HotStockEventMonitorService({
      feed,
      dataLayer,
      tdxBlockPool: makeTdxBlockPool(),
      intervalMs: 1_000,
      now: () => Date.parse('2026-05-15T10:05:00+08:00'),
    })

    service.start()
    await vi.advanceTimersByTimeAsync(1_000)

    expect(feed.fetchEvents).not.toHaveBeenCalled()
    expect(refreshTaskRegistry.getTask('hotStockEvent.monitor')).toMatchObject({
      visibilityPolicy: 'pause',
      running: false,
      successCount: 0,
    })

    visibility.visibilityState = 'visible'
    await vi.advanceTimersByTimeAsync(1_000)

    expect(feed.fetchEvents).toHaveBeenCalledTimes(1)
    expect(refreshTaskRegistry.getTask('hotStockEvent.monitor')).toMatchObject({
      running: false,
      lastSuccessAt: expect.any(Number),
      successCount: 1,
      source: 'scheduler',
    })

    service.stop()
  })

  it('keeps polling while any owner still needs event radar updates', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('document', { visibilityState: 'visible' })
    const feed = {
      fetchEvents: vi.fn().mockResolvedValue([]),
    }
    const dataLayer = {
      getStocks: vi.fn().mockReturnValue([]),
      getDragonReview: vi.fn().mockReturnValue(null),
    }
    const service = new HotStockEventMonitorService({
      feed,
      dataLayer,
      tdxBlockPool: makeTdxBlockPool(),
      intervalMs: 1_000,
      now: () => Date.parse('2026-05-15T10:05:00+08:00'),
    })

    service.start('panel')
    service.start('feishu')
    service.stop('panel')

    await vi.advanceTimersByTimeAsync(1_000)

    expect(feed.fetchEvents).toHaveBeenCalledTimes(1)
    service.stop('feishu')
    await vi.advanceTimersByTimeAsync(1_000)
    expect(feed.fetchEvents).toHaveBeenCalledTimes(1)
  })

  it('clears the TDX block subscription only after the last event radar owner stops', () => {
    const feed = {
      fetchEvents: vi.fn().mockResolvedValue([]),
    }
    const dataLayer = {
      getStocks: vi.fn().mockReturnValue([]),
      getDragonReview: vi.fn().mockReturnValue(null),
    }
    const tdxBlockPool = makeTdxBlockPool()
    const service = new HotStockEventMonitorService({
      feed,
      dataLayer,
      tdxBlockPool,
      intervalMs: 1_000,
      now: () => Date.parse('2026-05-15T10:05:00+08:00'),
    })

    service.start('panel')
    service.start('feishu')
    service.stop('panel')
    expect(tdxBlockPool.clear).not.toHaveBeenCalled()

    service.stop('feishu')
    expect(tdxBlockPool.clear).toHaveBeenCalledTimes(1)
  })

  it('does not keep TDX block codes when the panel stops before a refresh completes', async () => {
    let resolveRefresh: (value: { codes: string[] }) => void = () => {}
    const refreshPromise = new Promise<{ codes: string[] }>((resolve) => {
      resolveRefresh = resolve
    })
    const feed = {
      fetchEvents: vi.fn().mockResolvedValue([
        makeEvent({ id: 'tdx', code: '300001', timestamp: Date.parse('2026-05-15T10:02:00+08:00') }),
      ]),
    }
    const dataLayer = {
      getStocks: vi.fn().mockReturnValue([]),
      getDragonReview: vi.fn().mockReturnValue(null),
    }
    const tdxBlockPool = {
      ...makeTdxBlockPool(['300001']),
      refresh: vi.fn().mockReturnValue(refreshPromise),
    }
    const service = new HotStockEventMonitorService({
      feed,
      dataLayer,
      tdxBlockPool,
      intervalMs: 1_000,
      now: () => Date.parse('2026-05-15T10:05:00+08:00'),
    })

    service.start('panel')
    const runningRefresh = service.refresh()
    service.stop('panel')
    resolveRefresh({ codes: ['300001'] })
    await runningRefresh

    expect(tdxBlockPool.clear).toHaveBeenCalledTimes(1)
    expect(service.getState().tdxBlockCodes).toEqual([])
    expect(service.getState().otherStockEvents).toEqual([])
  })

  it('updates monitor block file selection through the TDX block pool', async () => {
    const feed = {
      fetchEvents: vi.fn().mockResolvedValue([]),
    }
    const dataLayer = {
      getStocks: vi.fn().mockReturnValue([]),
      getDragonReview: vi.fn().mockReturnValue(null),
    }
    const tdxBlockPool = {
      ...makeTdxBlockPool(),
      setSelectedFiles: vi.fn().mockResolvedValue({
        codes: ['603072'],
        files: [{ name: '观察.blk', path: 'D:\\TDX\\观察.blk', stockCount: 1, issueCount: 0, selected: true }],
        selectedFiles: ['D:\\TDX\\观察.blk'],
      }),
      refreshFiles: vi.fn().mockResolvedValue({
        codes: ['603072'],
        files: [
          { name: 'ZB.blk', path: 'D:\\TDX\\ZB.blk', stockCount: 2, issueCount: 0, selected: false },
          { name: '观察.blk', path: 'D:\\TDX\\观察.blk', stockCount: 1, issueCount: 0, selected: true },
        ],
        selectedFiles: ['D:\\TDX\\观察.blk'],
      }),
    }
    const service = new HotStockEventMonitorService({
      feed,
      dataLayer,
      tdxBlockPool,
      now: () => Date.parse('2026-05-15T10:05:00+08:00'),
    })

    const state = await service.setSelectedTdxBlockFiles(['D:\\TDX\\观察.blk'])

    expect(tdxBlockPool.setSelectedFiles).toHaveBeenCalledWith(['D:\\TDX\\观察.blk'])
    expect(tdxBlockPool.refreshFiles).toHaveBeenCalled()
    expect(state.tdxBlockCodes).toEqual(['603072'])
    expect(state.selectedTdxBlockFiles).toEqual(['D:\\TDX\\观察.blk'])
    expect(state.tdxBlockFiles.map(file => ({ name: file.name, selected: file.selected }))).toEqual([
      { name: 'ZB.blk', selected: false },
      { name: '观察.blk', selected: true },
    ])
  })

  it('keeps the TDX block file loading error after a successful event refresh', async () => {
    const feed = {
      fetchEvents: vi.fn().mockResolvedValue([]),
    }
    const dataLayer = {
      getStocks: vi.fn().mockReturnValue([]),
      getDragonReview: vi.fn().mockReturnValue(null),
    }
    const tdxBlockPool = {
      ...makeTdxBlockPool(),
      refreshFiles: vi.fn().mockRejectedValue(new Error('tdx block dir missing')),
    }
    const service = new HotStockEventMonitorService({
      feed,
      dataLayer,
      tdxBlockPool,
      now: () => Date.parse('2026-05-15T10:05:00+08:00'),
    })

    const result = await service.refresh()

    expect(result.ok).toBe(true)
    expect(service.getState().error).toBe('tdx block dir missing')
  })

  it('keeps feishu event radar polling active when the page is hidden', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('document', { visibilityState: 'hidden' })
    const feed = {
      fetchEvents: vi.fn().mockResolvedValue([]),
    }
    const dataLayer = {
      getStocks: vi.fn().mockReturnValue([]),
      getDragonReview: vi.fn().mockReturnValue(null),
    }
    const service = new HotStockEventMonitorService({
      feed,
      dataLayer,
      tdxBlockPool: makeTdxBlockPool(),
      intervalMs: 1_000,
      now: () => Date.parse('2026-05-15T10:05:00+08:00'),
    })

    service.start('feishu')
    await vi.advanceTimersByTimeAsync(1_000)

    expect(feed.fetchEvents).toHaveBeenCalledTimes(1)
    expect(refreshTaskRegistry.getTask('hotStockEvent.monitor')).toMatchObject({
      visibilityPolicy: 'run',
      runWhenHidden: true,
    })

    service.stop('feishu')
  })
})
