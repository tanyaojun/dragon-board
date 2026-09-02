import { describe, expect, it } from 'vitest'

import type { LimitUpExtData } from '@/types'

import {
  compareThemeStockRows,
  enrichStocksWithLimitUp,
  formatFengdanYi,
  formatLeaderRank,
  formatLianbanText,
  formatOpenNum,
  timeToSeconds,
} from '../stockLimitUpRows'

type Row = {
  code: string
  name: string
  change: number
  volumeRatio: number | null
  mainNetInflow: number | null
  role: string
}

function baseRow(overrides: Partial<Row> = {}): Row {
  return {
    code: '002059',
    name: '云南旅游',
    change: 10.03,
    volumeRatio: 3.08,
    mainNetInflow: -124000000,
    role: 'follower',
    ...overrides,
  }
}

describe('enrichStocksWithLimitUp', () => {
  it('merges limit-up ext fields into matching stock rows', () => {
    const rows = [
      baseRow(),
      baseRow({ code: '603978', name: '深圳新星', change: 10.02 }),
    ]
    const extData: Record<string, LimitUpExtData> = {
      '002059': {
        lianbanStr: '首板',
        boardHeight: 1,
        firstZtTime: '09:31:00',
        lastZtTime: '14:55:00',
        fengdan: 42107625,
        openNum: 1,
        reason: '景区运营+文旅科技',
      },
    }

    const merged = enrichStocksWithLimitUp(rows, (code) => extData[code])

    expect(merged[0]).toMatchObject({
      code: '002059',
      lianbanStr: '首板',
      boardHeight: 1,
      firstZtTime: '09:31:00',
      lastZtTime: '14:55:00',
      fengdan: 42107625,
      openNum: 1,
      reason: '景区运营+文旅科技',
    })
  })

  it('keeps non limit-up rows free of fabricated limit-up values', () => {
    const rows = [baseRow({ code: '603978', name: '深圳新星' })]

    const merged = enrichStocksWithLimitUp(rows, () => undefined)

    expect(merged[0].code).toBe('603978')
    expect('lianbanStr' in merged[0]).toBe(false)
    expect('firstZtTime' in merged[0]).toBe(false)
    expect('fengdan' in merged[0]).toBe(false)
    expect('openNum' in merged[0]).toBe(false)
    expect('reason' in merged[0]).toBe(false)
  })

  it('moves static related reason to relatedReason and keeps reason for limit-up reason only', () => {
    // 2026-09-02 口径：行对象 reason 键只承载涨停原因（同花顺涨停池 reason_type，仅涨停股有值）；
    // 题材映射静态文本（主营业务/关联原因）转移到 relatedReason，未涨停股涨停原因列不得显示关联原因
    const rows = [
      { ...baseRow(), reason: '公司主营军工电子设备' } as Row & { reason?: string },
      { ...baseRow({ code: '603978', name: '深圳新星' }), reason: '公司为国内高科技军用特种装备的供应商' } as Row & {
        reason?: string
      },
    ]
    const extData: Record<string, LimitUpExtData> = {
      '002059': { firstZtTime: '09:31:00', reason: '兵装重组+军工装备' },
    }

    const merged = enrichStocksWithLimitUp(rows, (code) => extData[code])

    // 涨停股：reason=涨停原因，relatedReason 保留静态文本
    expect((merged[0] as { reason?: string }).reason).toBe('兵装重组+军工装备')
    expect((merged[0] as { relatedReason?: string }).relatedReason).toBe('公司主营军工电子设备')
    // 未涨停股：reason 清空（不显示关联原因），relatedReason 保留
    expect((merged[1] as { reason?: string }).reason).toBeFalsy()
    expect((merged[1] as { relatedReason?: string }).relatedReason).toBe(
      '公司为国内高科技军用特种装备的供应商',
    )
  })

  it('keeps input rows unmutated when relocating related reason', () => {
    const rows = [{ ...baseRow(), reason: '主营文本' } as Row & { reason?: string }]

    enrichStocksWithLimitUp(rows, () => undefined)

    expect(rows[0].reason).toBe('主营文本')
    expect('relatedReason' in rows[0]).toBe(false)
  })

  it('skips partial ext data without fabricating missing fields as zero', () => {
    const rows = [baseRow()]

    const merged = enrichStocksWithLimitUp(rows, () => ({
      firstZtTime: '09:31:00',
      fengdan: 0,
    }))

    expect(merged[0].firstZtTime).toBe('09:31:00')
    expect(merged[0].fengdan).toBe(0)
    expect('lianbanStr' in merged[0]).toBe(false)
    expect('reason' in merged[0]).toBe(false)
  })

  it('does not mutate input rows', () => {
    const rows = [baseRow()]

    enrichStocksWithLimitUp(rows, () => ({ firstZtTime: '09:31:00' }))

    expect('firstZtTime' in rows[0]).toBe(false)
  })

  it('assigns leaderRank by board height desc, then first limit-up time asc', () => {
    // 2026-09-02 口径：龙一/龙二……按 连板数降序 + 首次涨停时间升序 编位
    const twoBoardLate = baseRow({ code: '002059', name: '2板晚' }) // 2板 09:40 → 龙三
    const threeBoard = baseRow({ code: '002639', name: '3板' }) // 3板 09:50 → 龙一（板高优先）
    const twoBoardEarly = baseRow({ code: '603978', name: '2板早' }) // 2板 09:30 → 龙二
    const notLimitUp = baseRow({ code: '300877', name: '未涨停' })

    const merged = enrichStocksWithLimitUp(
      [twoBoardLate, notLimitUp, threeBoard, twoBoardEarly],
      (code) =>
        code === '002059'
          ? { boardHeight: 2, firstZtTime: '09:40:00' }
          : code === '002639'
            ? { boardHeight: 3, firstZtTime: '09:50:00' }
            : code === '603978'
              ? { boardHeight: 2, firstZtTime: '09:30:00' }
              : undefined,
    )

    const rankByCode = new Map(merged.map((row) => [row.code, (row as { leaderRank?: number }).leaderRank]))
    expect(rankByCode.get('002639')).toBe(1) // 3板最高 → 龙一
    expect(rankByCode.get('603978')).toBe(2) // 同 2板，09:30 早 → 龙二
    expect(rankByCode.get('002059')).toBe(3) // 同 2板，09:40 晚 → 龙三
    expect(rankByCode.get('300877')).toBeUndefined() // 未涨停不编号
  })

  it('ranks limit-up rows with missing boardHeight after real board heights', () => {
    const withHeight = baseRow({ code: '000001' })
    const noHeight = baseRow({ code: '000002' })

    const merged = enrichStocksWithLimitUp(
      [noHeight, withHeight],
      (code) =>
        code === '000001'
          ? { boardHeight: 1, firstZtTime: '10:00:00' }
          : { firstZtTime: '09:25:00' }, // 涨停但无板高字段：按 0 处理，排有板高之后
    )

    const rankByCode = new Map(merged.map((row) => [row.code, (row as { leaderRank?: number }).leaderRank]))
    expect(rankByCode.get('000001')).toBe(1)
    expect(rankByCode.get('000002')).toBe(2)
  })

  it('breaks board-height and first-time ties by code for a stable leader order', () => {
    const a = baseRow({ code: '000001' })
    const b = baseRow({ code: '000002' })

    const merged = enrichStocksWithLimitUp(
      [b, a],
      () => ({ boardHeight: 2, firstZtTime: '09:31:00' }),
    )

    const rankByCode = new Map(merged.map((row) => [row.code, (row as { leaderRank?: number }).leaderRank]))
    expect(rankByCode.get('000001')).toBe(1)
    expect(rankByCode.get('000002')).toBe(2)
  })
})

describe('compareThemeStockRows', () => {
  it('sorts numeric fields descending by default regression-safe', () => {
    const high = baseRow({ code: 'A', change: 10.03 })
    const low = baseRow({ code: 'B', change: 5.2 })

    expect(compareThemeStockRows(high, low, 'change', true)).toBeLessThan(0)
    expect(compareThemeStockRows(low, high, 'change', true)).toBeGreaterThan(0)
    expect(compareThemeStockRows(high, low, 'change', false)).toBeGreaterThan(0)
  })

  it('treats null mainNetInflow and volumeRatio as zero like the legacy sort', () => {
    const nullInflow = baseRow({ code: 'A', mainNetInflow: null })
    const zeroInflow = baseRow({ code: 'B', mainNetInflow: 0 })

    expect(compareThemeStockRows(nullInflow, zeroInflow, 'mainNetInflow', true)).toBe(0)
    expect(compareThemeStockRows(nullInflow, zeroInflow, 'mainNetInflow', false)).toBe(0)
  })

  it('sorts leaderRank first (龙一 first) when descending and keeps unranked last', () => {
    // 2026-09-02 口径变更：leader 排序不再看 role 打分，改为按题材内首次涨停时间编位 leaderRank
    const first = baseRow({ code: 'A' }) as any
    first.leaderRank = 1
    const second = baseRow({ code: 'B' }) as any
    second.leaderRank = 2
    const unranked = baseRow({ code: 'C' }) as any

    expect(compareThemeStockRows(first, second, 'leader', true)).toBeLessThan(0)
    expect(compareThemeStockRows(first, unranked, 'leader', true)).toBeLessThan(0)
    expect(compareThemeStockRows(first, unranked, 'leader', false)).toBeLessThan(0) // 缺失永远最后
    // 升序时反转：龙二在龙一前
    expect(compareThemeStockRows(second, first, 'leader', false)).toBeLessThan(0)
  })

  it('sorts board height descending and keeps missing lianban last', () => {
    const high = baseRow({ code: 'A' }) as any
    high.boardHeight = 5
    const low = baseRow({ code: 'B' }) as any
    low.boardHeight = 2
    const missing = baseRow({ code: 'C' }) as any

    expect(compareThemeStockRows(high, low, 'lianban', true)).toBeLessThan(0)
    expect(compareThemeStockRows(high, missing, 'lianban', true)).toBeLessThan(0)
    expect(compareThemeStockRows(high, missing, 'lianban', false)).toBeLessThan(0)
  })

  it('sorts first limit-up time as time value and keeps missing last', () => {
    const early = baseRow({ code: 'A' }) as any
    early.firstZtTime = '09:31:00'
    const late = baseRow({ code: 'B' }) as any
    late.firstZtTime = '14:55:00'
    const missing = baseRow({ code: 'C' }) as any

    // 降序=时间晚在前；缺失永远最后
    expect(compareThemeStockRows(late, early, 'firstZtTime', true)).toBeLessThan(0)
    expect(compareThemeStockRows(early, missing, 'firstZtTime', true)).toBeLessThan(0)
    expect(compareThemeStockRows(early, missing, 'firstZtTime', false)).toBeLessThan(0)
  })

  it('sorts fengdan descending and keeps missing last', () => {
    const big = baseRow({ code: 'A' }) as any
    big.fengdan = 800000000
    const small = baseRow({ code: 'B' }) as any
    small.fengdan = 42000000
    const missing = baseRow({ code: 'C' }) as any

    expect(compareThemeStockRows(big, small, 'fengdan', true)).toBeLessThan(0)
    expect(compareThemeStockRows(big, missing, 'fengdan', true)).toBeLessThan(0)
    expect(compareThemeStockRows(big, missing, 'fengdan', false)).toBeLessThan(0)
  })

  it('compares code and name as strings', () => {
    const a = baseRow({ code: '002639', name: '雪人集团' })
    const b = baseRow({ code: '603978', name: '深圳新星' })

    // 锁定现有组件行为：desc = strB.localeCompare(strA)
    expect(compareThemeStockRows(a, b, 'code', true)).toBeGreaterThan(0)
    expect(compareThemeStockRows(a, b, 'code', false)).toBeLessThan(0)
    expect(compareThemeStockRows(a, b, 'name', true)).not.toBe(0)
  })
})

describe('timeToSeconds', () => {
  it('parses HH:mm:ss, HH:mm and null-safe inputs', () => {
    expect(timeToSeconds('09:31:00')).toBe(34260)
    expect(timeToSeconds('09:31')).toBe(34260)
    expect(timeToSeconds('')).toBeNull()
    expect(timeToSeconds(undefined)).toBeNull()
  })
})

describe('formatLianbanText', () => {
  it('prefers lianban text and falls back to board height', () => {
    expect(formatLianbanText({ lianbanStr: '5天3板', boardHeight: 3 })).toBe('5天3板')
    expect(formatLianbanText({ boardHeight: 3 })).toBe('3板')
    expect(formatLianbanText({ boardHeight: 1 })).toBe('首板')
    expect(formatLianbanText({})).toBe('--')
    expect(formatLianbanText(undefined)).toBe('--')
  })
})

describe('formatFengdanYi', () => {
  it('formats fengdan amount in 亿 and keeps missing distinct from zero', () => {
    expect(formatFengdanYi(42107625)).toBe('0.42亿')
    expect(formatFengdanYi(800000000)).toBe('8.00亿')
    expect(formatFengdanYi(0)).toBe('0.00亿')
    expect(formatFengdanYi(null)).toBe('--')
    expect(formatFengdanYi(undefined)).toBe('--')
  })
})

describe('formatOpenNum', () => {
  it('formats open count and keeps missing distinct from zero', () => {
    expect(formatOpenNum(0)).toBe('0')
    expect(formatOpenNum(2)).toBe('2')
    expect(formatOpenNum(null)).toBe('--')
    expect(formatOpenNum(undefined)).toBe('--')
  })
})

describe('formatLeaderRank', () => {
  it('formats 龙一..龙十 in Chinese and numeric beyond ten', () => {
    expect(formatLeaderRank(1)).toBe('龙一')
    expect(formatLeaderRank(2)).toBe('龙二')
    expect(formatLeaderRank(3)).toBe('龙三')
    expect(formatLeaderRank(4)).toBe('龙四')
    expect(formatLeaderRank(10)).toBe('龙十')
    expect(formatLeaderRank(11)).toBe('龙11')
    expect(formatLeaderRank(null)).toBe('--')
    expect(formatLeaderRank(undefined)).toBe('--')
  })
})
