import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  fetchHotlistJevRange,
  fetchHotlistJevSeries,
  jevChoiceConfidence,
  jevCrowdingName,
  jevCrowdingProbability,
  JEV_CROWDING_NAMES,
  JEV_PATTERN_NAMES,
  JEV_PATTERN_ORDER,
  JEV_STAGE_ORDER,
} from '../hotlistJevApi'
import type { HotlistJevDoc } from '@/types/hotlistJev'

const slotDoc = (overrides: Partial<HotlistJevDoc>): HotlistJevDoc => ({
  kind: 'slot',
  datasetId: 'dragonboard_live',
  snapshotType: 'half_hour',
  tradingDate: '2026-09-29',
  slotTime: '09:30',
  status: 'ok',
  answers: {
    sequence_stage: { type: 'choice', choice: 'start', probabilities: { start: 0.6 } },
  },
  scores: { temperature: 24, crowding: 15 },
  ...overrides,
})

afterEach(() => vi.unstubAllGlobals())

describe('jev 规范展示顺序', () => {
  it('五档冷→热、八类路径顺序锁定（概率条顺序唯一来源）', () => {
    expect(JEV_STAGE_ORDER).toEqual(['ice', 'start', 'ferment', 'climax', 'retreat'])
    expect(JEV_PATTERN_ORDER).toEqual([
      'steady_strong',
      'steady_weak',
      'rally_fade',
      'low_recover',
      'late_rescue',
      'wide_swing',
      'narrow_range',
      'unclear',
    ])
  })

  it('v2.5 新档中文映射：拥挤解除（六层）+ 尾盘偷袭（八类）', () => {
    expect(JEV_CROWDING_NAMES.crowd_clearing).toBe('拥挤解除')
    expect(JEV_PATTERN_NAMES.late_rescue).toBe('尾盘偷袭')
    // 新档答案照常读中文（缺失映射才回退英文键）
    const doc = slotDoc({
      answers: {
        crowding: { type: 'choice', choice: 'crowd_clearing', probabilities: { crowd_clearing: 0.7 } },
      },
    })
    expect(jevCrowdingName(doc, 'crowding')).toBe('拥挤解除')
  })

  it('拥挤解除是出清态：不计入拥挤三层概率合计', () => {
    const doc = slotDoc({
      answers: {
        crowding: {
          type: 'choice',
          choice: 'crowd_clearing',
          probabilities: { top_acceleration: 0.1, crowd_clearing: 0.7, no_crowding: 0.2 },
        },
      },
    })
    expect(jevCrowdingProbability(doc, 'crowding')).toBeCloseTo(0.1, 5)
  })
})

describe('fetchHotlistJevSeries', () => {
  it('正常响应返回类型化 slots + eod', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({ ok: true, date: '2026-09-29', slots: [slotDoc({})], eod: null }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      ),
    )
    const result = await fetchHotlistJevSeries()
    expect(result.degraded).toBe(false)
    expect(result.date).toBe('2026-09-29')
    expect(result.slots).toHaveLength(1)
  })

  it('degraded 响应透传错误态，不伪造数据', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ ok: false, degraded: true, reason: 'mongodb_unavailable: x' }), {
          status: 200,
        }),
      ),
    )
    const result = await fetchHotlistJevSeries()
    expect(result.degraded).toBe(true)
    expect(result.slots).toHaveLength(0)
    expect(result.reason).toBe('mongodb_unavailable: x')
  })
})

describe('拥挤度/置信投影（jev 观察轨道图表数据源，2026-10-02）', () => {
  it('jevCrowdingProbability=拥挤三层概率合计；缺分布/非 choice/缺答案为 null 不伪造 0', () => {
    // 2026-09-30 15:00 实测分布：判定=无拥挤，但拥挤层合计 0.61——柱高与归层判定口径不同是有意设计
    const doc = slotDoc({
      answers: {
        crowding: {
          type: 'choice',
          choice: 'no_crowding',
          probabilities: {
            top_acceleration: 0.21,
            late_seal_weakness: 0.06,
            breadth_climax: 0.34,
            no_crowding: 0.37,
            insufficient_evidence: 0.02,
          },
          confidence: 0.21,
        },
      },
    })
    expect(jevCrowdingProbability(doc, 'crowding')).toBeCloseTo(0.61, 5)
    expect(
      jevCrowdingProbability(
        slotDoc({ answers: { crowding: { type: 'choice', choice: 'no_crowding' } } }),
        'crowding',
      ),
    ).toBeNull()
    expect(jevCrowdingProbability(slotDoc({ answers: {} }), 'crowding')).toBeNull()
    expect(jevCrowdingProbability(null, 'crowding')).toBeNull()
  })

  it('jevChoiceConfidence 读模型 confidence；缺失/非 choice 为 null（score 型不在此假设）', () => {
    expect(
      jevChoiceConfidence(
        slotDoc({
          answers: {
            sequence_stage: { type: 'choice', choice: 'start', probabilities: { start: 0.6 }, confidence: 0.51 },
          },
        }),
        'sequence_stage',
      ),
    ).toBe(0.51)
    expect(
      jevChoiceConfidence(
        slotDoc({ answers: { sequence_stage: { type: 'choice', choice: 'start' } } }),
        'sequence_stage',
      ),
    ).toBeNull()
  })
})

describe('fetchHotlistJevRange', () => {
  it('正常响应拆分文档日与缺失日（missing 收集进 missingDays，不吞掉）', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            ok: true,
            datasetId: 'dragonboard_live',
            days: [
              { tradingDate: '2026-09-26', missing: true, reason: 'no_jev_docs' },
              {
                tradingDate: '2026-09-29',
                slots: [slotDoc({ tradingDate: '2026-09-29' })],
                eod: {
                  kind: 'eod',
                  tradingDate: '2026-09-29',
                  status: 'ok',
                  answers: { day_stage: { type: 'choice', choice: 'climax' } },
                  scores: { day_temperature: 73, day_crowding: 32 },
                },
              },
            ],
            degradedCount: 0,
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      ),
    )
    const result = await fetchHotlistJevRange(5)
    expect(result.degraded).toBe(false)
    expect(result.days).toHaveLength(1)
    expect(result.days[0].tradingDate).toBe('2026-09-29')
    expect(result.days[0].slots[0].scores?.temperature).toBe(24)
    expect(result.missingDays).toEqual([{ tradingDate: '2026-09-26', reason: 'no_jev_docs' }])
  })

  it('degraded 响应透传错误态', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({ ok: false, degraded: true, reason: 'no_snapshot_trading_date' }),
          { status: 200 },
        ),
      ),
    )
    const result = await fetchHotlistJevRange()
    expect(result.degraded).toBe(true)
    expect(result.days).toHaveLength(0)
    expect(result.reason).toBe('no_snapshot_trading_date')
  })

  it('HTTP 错误返回错误态', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('err', { status: 502 })))
    const result = await fetchHotlistJevRange()
    expect(result.degraded).toBe(true)
    expect(result.reason).toBe('HTTP 502')
  })

  it('网络异常返回错误态，不抛出', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network down')))
    const result = await fetchHotlistJevRange()
    expect(result.degraded).toBe(true)
    expect(result.reason).toBe('network down')
  })
})
