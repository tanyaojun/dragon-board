// jev 叙事投影纯函数测试（fail-visible 合同：缺失不伪造、score 型显式无分布）
import { describe, expect, test } from 'vitest'

import type { HotlistJevDoc } from '@/types/hotlistJev'
import {
  anchorMetricsOfDoc,
  buildDayGrid,
  buildSlotGrid,
  confidenceMetrics,
  crowdingTimeline,
  crowdingTransitions,
  findNarrativeSection,
  layerStats,
  parseAnchorQuantiles,
  parseNarrativeSections,
} from '@/services/hotlist/jevNarrativeProjection'

const SLOT_NARRATIVE = [
  '2026-10-08 14:30 时点快照（A股短线热榜情绪观察，原始市场证据）。',
  '【近20日参照】（2026-09-08 → 2026-10-07，20 个交易日收盘统计，判读坐标系）',
  '涨停数：p20=45 家 / p50=67 家 / p80=91 家（2026-10-07 88 家）',
  '最高连板：p20=3 板 / p50=5 板 / p80=7 板（2026-10-07 6 板）',
  '两市成交额：p20=15000 亿 / p50=17000 亿 / p80=19000 亿（2026-10-07 18000 亿）',
  '炸板率：p20=12% / p50=15% / p80=25%（2026-10-07 18%）',
  '【当前帧】',
  '指数：sh +0.5%',
  '涨停与炸板：涨停 88 家',
  '【当日已走帧证据】',
  '14:00 帧：涨停 80 家',
  '【数据质量】无缺失。',
].join('\n')

const ANCHOR_INSUFFICIENT_NARRATIVE = [
  '2026-09-30 11:00 时点快照。',
  '【近20日参照】（2026-09-20 → 2026-09-29，7 个交易日收盘统计，判读坐标系）',
  '涨停数 历史样本不足（7 日）',
  '炸板率：p20=12% / p50=15% / p80=25%（2026-09-29 18%）',
  '【数据质量】锚窗口浅。',
].join('\n')

function choiceAnswer(choice: string, probabilities: Record<string, number>, confidence?: number) {
  return { type: 'choice' as const, choice, probabilities, ...(confidence !== undefined ? { confidence } : {}) }
}

describe('parseNarrativeSections 叙事分段', () => {
  test('标准槽位叙事：header + 四段，段体不含【】头', () => {
    const projection = parseNarrativeSections(SLOT_NARRATIVE)
    expect(projection.header).toContain('14:30 时点快照')
    expect(projection.sections.map((s) => s.title)).toEqual([
      '近20日参照',
      '当前帧',
      '当日已走帧证据',
      '数据质量',
    ])
    const anchor = findNarrativeSection(projection, '近20日参照')
    expect(anchor?.lines[0]).toContain('2026-09-08 → 2026-10-07')
    expect(anchor?.lines.join('\n')).not.toContain('【近20日参照】')
  })

  test('缺失/空输入返回空投影，不抛错', () => {
    expect(parseNarrativeSections(null)).toEqual({ header: '', sections: [] })
    expect(parseNarrativeSections('')).toEqual({ header: '', sections: [] })
    expect(parseNarrativeSections(undefined).sections).toEqual([])
  })

  test('无段头文本整体归 header', () => {
    const projection = parseNarrativeSections('只有一行')
    expect(projection.header).toBe('只有一行')
    expect(projection.sections).toEqual([])
  })
})

describe('parseAnchorQuantiles 锚分位解析', () => {
  test('四指标标准行：p20/p50/p80/最新值/单位全解析', () => {
    const metrics = parseAnchorQuantiles(SLOT_NARRATIVE.split('\n').filter((l) => l.includes('：p20=')))
    expect(metrics).toHaveLength(4)
    expect(metrics[0]).toEqual({
      metric: '涨停数', p20: 45, p50: 67, p80: 91,
      lastDate: '2026-10-07', lastValue: 88, unit: '家', note: null,
    })
    expect(metrics[3]).toEqual({
      metric: '炸板率', p20: 12, p50: 15, p80: 25,
      lastDate: '2026-10-07', lastValue: 18, unit: '%', note: null,
    })
  })

  test('历史样本不足行：分位全 null + note，不伪造刻度', () => {
    const metrics = parseAnchorQuantiles(
      ANCHOR_INSUFFICIENT_NARRATIVE.split('\n').filter((l) => l !== '' && !l.startsWith('【')),
    )
    expect(metrics).toHaveLength(2)
    expect(metrics[0]).toEqual({
      metric: '涨停数', p20: null, p50: null, p80: null,
      lastDate: null, lastValue: null, unit: null, note: '历史样本不足（7 日）',
    })
    expect(metrics[1]?.p50).toBe(15)
  })

  test('畸形行跳过不猜测', () => {
    expect(parseAnchorQuantiles(['完全不是锚行', ''])).toEqual([])
    expect(parseAnchorQuantiles(null)).toEqual([])
  })

  test('anchorMetricsOfDoc 从文档 narrativeRaw 直达锚分位', () => {
    const doc = { narrativeRaw: SLOT_NARRATIVE } as HotlistJevDoc
    expect(anchorMetricsOfDoc(doc)).toHaveLength(4)
    expect(anchorMetricsOfDoc({} as HotlistJevDoc)).toEqual([])
  })
})

describe('confidenceMetrics 置信指标', () => {
  test('choice：top 概率/margin/熵/犹豫标记', () => {
    const metrics = confidenceMetrics(choiceAnswer('ferment', { ice: 0.05, start: 0.15, ferment: 0.6, climax: 0.2 }, 0.72))
    expect(metrics.kind).toBe('choice')
    expect(metrics.choice).toBe('ferment')
    expect(metrics.probability).toBe(0.6)
    expect(metrics.confidence).toBe(0.72)
    expect(metrics.margin).toBeCloseTo(0.4)
    expect(metrics.entropy).not.toBeNull()
    expect(metrics.entropy!).toBeGreaterThan(0)
    expect(metrics.entropy!).toBeLessThan(1)
    expect(metrics.hesitant).toBe(false)
    expect(metrics.noDistribution).toBe(false)
  })

  test('top 概率 < 0.6 → hesitant；margin=top1-top2', () => {
    const metrics = confidenceMetrics(choiceAnswer('start', { start: 0.35, ferment: 0.33, ice: 0.32 }))
    expect(metrics.hesitant).toBe(true)
    expect(metrics.margin).toBeCloseTo(0.02)
  })

  test('score 型：显式无分布，不是 missing 也不是异常', () => {
    const metrics = confidenceMetrics({ type: 'score', score: 3, legend: {} })
    expect(metrics.kind).toBe('score')
    expect(metrics.noDistribution).toBe(true)
    expect(metrics.noDistributionReason).toContain('无概率分布')
    expect(metrics.probability).toBeNull()
    expect(metrics.margin).toBeNull()
  })

  test('缺失答案返回 missing', () => {
    expect(confidenceMetrics(null).kind).toBe('missing')
    expect(confidenceMetrics(undefined)?.kind).toBe('missing')
  })
})

describe('crowdingTimeline / crowdingTransitions 拥挤时间线', () => {
  const slots = [
    { slotTime: '10:00', status: 'ok', answers: { crowding: choiceAnswer('no_crowding', { no_crowding: 0.7 }) } },
    { slotTime: '10:30', status: 'ok', answers: { crowding: choiceAnswer('breadth_climax', { breadth_climax: 0.55 }, 0.55) } },
    { slotTime: '11:00', status: 'degraded', answers: null },
    { slotTime: '11:30', status: 'ok', answers: { crowding: choiceAnswer('late_seal_weakness', { late_seal_weakness: 0.8 }, 0.8) } },
  ] as unknown as HotlistJevDoc[]

  test('逐槽归层/毒层标记/缺失如实', () => {
    const timeline = crowdingTimeline(slots)
    expect(timeline).toHaveLength(4)
    expect(timeline[0]).toMatchObject({ slotTime: '10:00', layer: 'no_crowding', layerName: '无拥挤', warn: false })
    expect(timeline[1]).toMatchObject({ layer: 'breadth_climax', probability: 0.55, confidence: 0.55 })
    expect(timeline[2]).toMatchObject({ status: 'degraded', layer: null, layerName: null })
    expect(timeline[3]).toMatchObject({ layer: 'late_seal_weakness', layerName: '封板弱化', warn: true })
  })

  test('层迁移只记录相邻变化点，降级槽无层不产生迁移', () => {
    const transitions = crowdingTransitions(crowdingTimeline(slots))
    expect(transitions).toHaveLength(2)
    expect(transitions[0]).toMatchObject({ atSlot: '10:30', from: 'no_crowding', to: 'breadth_climax' })
    expect(transitions[1]).toMatchObject({ atSlot: '11:30', from: null, toName: '封板弱化' })
  })
})

describe('layerStats 层统计与逃生率', () => {
  test('计数 + insufficient_evidence 逃生率', () => {
    const docs = [
      { answers: { crowding: choiceAnswer('no_crowding', {}) } },
      { answers: { crowding: choiceAnswer('insufficient_evidence', {}) } },
      { answers: { crowding: choiceAnswer('insufficient_evidence', {}) } },
      { answers: null },
    ] as unknown as HotlistJevDoc[]
    const stats = layerStats(docs, 'slot')
    expect(stats.total).toBe(3)
    expect(stats.counts.no_crowding).toBe(1)
    expect(stats.escapeCount).toBe(2)
    expect(stats.escapeRate).toBeCloseTo(2 / 3)
  })

  test('eod 集合读 day_crowding 键；空集合逃生率 null', () => {
    const docs = [{ answers: { day_crowding: choiceAnswer('breadth_climax', {}) } }] as unknown as HotlistJevDoc[]
    expect(layerStats(docs, 'eod').total).toBe(1)
    expect(layerStats([], 'slot')).toMatchObject({ total: 0, escapeRate: null })
  })
})

describe('buildSlotGrid / buildDayGrid 方格矩阵', () => {
  const slots = [
    {
      slotTime: '10:00', status: 'ok',
      answers: {
        frame_stage: choiceAnswer('ferment', {}),
        sequence_stage: choiceAnswer('ferment', { ferment: 0.62 }),
        crowding: choiceAnswer('no_crowding', {}),
      },
      scores: { temperature: 55.4 },
    },
    { slotTime: '10:30', status: 'degraded', answers: null, scores: null },
  ] as unknown as HotlistJevDoc[]

  test('五行齐全；缺失槽 degradation 如实、文本 null', () => {
    const grid = buildSlotGrid(slots)
    expect(grid.map((row) => row.key)).toEqual([
      'frame_stage', 'sequence_stage', 'temperature', 'crowding', 'confidence',
    ])
    expect(grid[0]?.cells[0]).toMatchObject({ column: '10:00', key: 'ferment', text: '发酵' })
    expect(grid[0]?.cells[1]).toMatchObject({ column: '10:30', degraded: true, text: null })
    expect(grid[2]?.cells[0]).toMatchObject({ numeric: 55, text: '55' })
    expect(grid[3]?.cells[0]).toMatchObject({ key: 'no_crowding', text: '无拥挤' })
    expect(grid[4]?.cells[0]).toMatchObject({ numeric: 0.62, text: 'P62%' })
    expect(grid[4]?.cells[1]?.text).toBeNull()
  })

  test('空集合返回空矩阵', () => {
    expect(buildSlotGrid([])).toEqual([])
    expect(buildDayGrid([])).toEqual([])
  })

  test('日级网格：EOD 缺失日 no_data 列，字段各归位', () => {
    const days = [
      {
        tradingDate: '2026-10-07',
        slots: [],
        eod: {
          status: 'ok',
          answers: {
            day_stage: choiceAnswer('retreat', { retreat: 0.58 }),
            day_pattern: choiceAnswer('rally_fade', {}),
            day_crowding: choiceAnswer('late_seal_weakness', {}),
          },
          scores: { day_temperature: 41 },
        } as unknown as HotlistJevDoc,
      },
      { tradingDate: '2026-10-08', slots: [], eod: null },
    ]
    const grid = buildDayGrid(days)
    expect(grid.map((row) => row.key)).toEqual([
      'day_stage', 'day_pattern', 'day_temperature', 'day_crowding', 'day_confidence',
    ])
    expect(grid[0]?.cells[0]).toMatchObject({ column: '2026-10-07', text: '退潮' })
    expect(grid[1]?.cells[0]).toMatchObject({ text: '冲高回落' })
    expect(grid[2]?.cells[0]).toMatchObject({ numeric: 41 })
    expect(grid[4]?.cells[0]).toMatchObject({ numeric: 0.58, text: 'P58%' })
    expect(grid[0]?.cells[1]).toMatchObject({ column: '2026-10-08', noData: true, text: null })
  })
})
