// jev 叙事投影纯函数测试（fail-visible 合同：缺失不伪造、score 型显式无分布）
import { describe, expect, test } from 'vitest'

import type { HotlistJevDoc } from '@/types/hotlistJev'
import {
  anchorMetricsOfDoc,
  confidenceMetrics,
  countDegradedDocs,
  crowdingTimeline,
  crowdingTransitions,
  findNarrativeSection,
  formatJevCoverageHint,
  layerStats,
  parseAnchorQuantiles,
  parseNarrativeSections,
  trimRangeWindow,
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

  test('score 型未携带分布：显式 noDistribution，不是 missing 也不是异常', () => {
    const metrics = confidenceMetrics({ type: 'score', score: 3, legend: {} })
    expect(metrics.kind).toBe('score')
    expect(metrics.noDistribution).toBe(true)
    expect(metrics.noDistributionReason).toContain('未携带锚点分布')
    expect(metrics.probability).toBeNull()
    expect(metrics.margin).toBeNull()
  })

  test('score 型携带锚点分布：消费 confidence/margin/熵（2026-10-02 实测生产 100% 携带，旧「无分布」判定是类型缺字段误判）', () => {
    // 2026-09-30 15:00 生产文档实测：锚点分布期望 6.28 → 还原温度 69.8 ≈ scores.temperature 69.7
    const metrics = confidenceMetrics({
      type: 'score',
      score: 6.27,
      probabilities: { '0': 0, '1': 0.01, '2': 0.02, '3': 0.03, '4': 0.05, '5': 0.13, '6': 0.24, '7': 0.33, '8': 0.17, '9': 0.02 },
      confidence: 0.53,
    })
    expect(metrics.kind).toBe('score')
    expect(metrics.noDistribution).toBe(false)
    expect(metrics.probability).toBeNull() // score 无 choice，无 top 概率语义
    expect(metrics.confidence).toBe(0.53)
    expect(metrics.margin).toBeCloseTo(0.09) // top1 0.33 − top2 0.24
    expect(metrics.entropy).not.toBeNull()
    expect(metrics.entropy!).toBeGreaterThan(0)
    expect(metrics.entropy!).toBeLessThan(1)
    expect(metrics.hesitant).toBe(false) // 犹豫阈值只作用于 choice top 概率
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

describe('trimRangeWindow 窗口收缩 / countDegradedDocs 降级计数', () => {
  const mkDay = (date: string) => ({ tradingDate: date, slots: [], eod: null })
  const wide = {
    days: [mkDay('2026-10-08'), mkDay('2026-10-07'), mkDay('2026-10-06'), mkDay('2026-10-02')],
    missingDays: [{ tradingDate: '2026-10-03', reason: 'no_jev_docs' }],
  }

  test('宽→窄按交易日历尾部收缩，文档日与缺失日同步拆分', () => {
    const trimmed = trimRangeWindow(3, wide)
    expect(trimmed.days.map((d) => d.tradingDate)).toEqual(['2026-10-06', '2026-10-07', '2026-10-08'])
    expect(trimmed.missingDays).toEqual([])
    const trimmed5 = trimRangeWindow(5, wide)
    expect(trimmed5.days).toHaveLength(4)
    expect(trimmed5.missingDays.map((d) => d.tradingDate)).toEqual(['2026-10-03'])
  })

  test('days=1 只留最新历日；空输入安全', () => {
    expect(trimRangeWindow(1, wide).days.map((d) => d.tradingDate)).toEqual(['2026-10-08'])
    expect(trimRangeWindow(3, { days: [], missingDays: [] })).toEqual({ days: [], missingDays: [] })
  })

  test('countDegradedDocs 与后端 degradedCount 同口径（slot+eod）', () => {
    const days = [
      {
        tradingDate: '2026-10-08',
        slots: [
          { status: 'ok' },
          { status: 'degraded' },
          { status: 'no_data' },
        ],
        eod: { status: 'ok' },
      },
      { tradingDate: '2026-10-07', slots: [], eod: { status: 'degraded' } },
      { tradingDate: '2026-10-06', slots: [], eod: null },
    ] as unknown as Parameters<typeof countDegradedDocs>[0]
    expect(countDegradedDocs(days)).toBe(3)
    expect(countDegradedDocs([])).toBe(0)
  })

  test('formatJevCoverageHint：缺槽位与空证据分开计数，不折叠成「缺 N 帧」', () => {
    const hint = formatJevCoverageHint({
      frameCoverage: {
        frameCount: 10, expectedCount: 10, hasCloseFrame: true,
        missingSlots: ['09:30', '10:00'],
        emptyEvidenceSlots: [
          { slot: '10:30', reason: 'rows_empty' },
          { slot: '11:00', reason: 'snapshot_missing' },
          { slot: '11:30', reason: 'unknown' },
        ],
      },
    })
    expect(hint).toContain('缺槽位 09:30、10:00')
    expect(hint).toContain('空证据 3 帧')
    expect(hint).not.toContain('缺 5 帧')
  })

  test('formatJevCoverageHint：缺收盘帧/无帧/存量未落档/全覆盖', () => {
    expect(formatJevCoverageHint({
      frameCoverage: { frameCount: 9, expectedCount: 10, hasCloseFrame: false, lastSlot: '14:30' },
    })).toBe('覆盖 9/10：缺收盘帧（末帧 14:30）')
    expect(formatJevCoverageHint({
      frameCoverage: { frameCount: 0, expectedCount: 10, hasCloseFrame: false,
                       missingSlots: ['09:30', '10:00'] },
    })).toBe('EOD 无帧（0/10）')
    expect(formatJevCoverageHint({ evidenceRawUnavailable: true })).toBe('历史证据未落档')
    expect(formatJevCoverageHint({
      frameCoverage: { frameCount: 10, expectedCount: 10, hasCloseFrame: true },
    })).toBeNull()
    expect(formatJevCoverageHint({})).toBeNull()
  })
})
