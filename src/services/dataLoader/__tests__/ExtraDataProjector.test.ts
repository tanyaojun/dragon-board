import { beforeEach, describe, expect, it } from 'vitest'

import { dataLayer } from '../../DataLayer'
import { extraDataProjector } from '../ExtraDataProjector'

function baseStock(overrides: Record<string, unknown> = {}) {
  return {
    code: '000001',
    name: '样本股',
    price: 10,
    change: 10.01,
    volume: 100000,
    turnover: 1000000,
    turnoverRate: 2.5,
    pe: 20,
    pb: 3,
    totalMV: 1e9,
    cirMV: 8e8,
    zlje: 1e6,
    zljzb: 5,
    cddje: 5e5,
    cddjzb: 3,
    ...overrides,
  }
}

describe('ExtraDataProjector 涨停原因/关联原因投影口径', () => {
  beforeEach(() => {
    dataLayer.reset()
  })

  it('keeps related reason on stock.reason and exposes limit-up reason as limitUpReason', () => {
    // 2026-09-02 口径：stock.reason 恒为关联原因（主营业务静态文本）；
    // 涨停原因（同花顺涨停池 reason_type）投影到独立键 limitUpReason，不得互相覆盖
    dataLayer.setMergedStocks([
      baseStock(),
      baseStock({ code: '600002', name: '未涨停股', change: 3.2 }),
    ])
    dataLayer.updateStockReasons([
      { code: '000001', reason: '算力龙头' },
      { code: '600002', reason: '零售主业' },
    ])
    dataLayer.updateLimitUpData([
      {
        code: '000001',
        reason: '兵装重组+军工装备',
        lianbanStr: '3天2板',
        firstZtTime: '09:31:00',
        lastZtTime: '14:55:00',
        fengdan: 42000000,
        openNum: 1,
      },
    ])

    const merged = extraDataProjector.project([baseStock(), baseStock({ code: '600002', name: '未涨停股' })])
    const zt = merged[0] as Record<string, unknown>
    const nonZt = merged[1] as Record<string, unknown>

    expect(zt.reason).toBe('算力龙头') // 关联原因不被涨停原因覆盖
    expect(zt.limitUpReason).toBe('兵装重组+军工装备') // 涨停原因独立键
    expect(zt.lianbanStr).toBe('3天2板')
    expect(zt.firstZtTime).toBe('09:31:00')
    expect(zt.lastZtTime).toBe('14:55:00')
    expect(zt.fengdan).toBe(42000000)
    expect(zt.openNum).toBe(1)

    // 未涨停股：只有关联原因，无涨停原因键（不伪造）
    expect(nonZt.reason).toBe('零售主业')
    expect('limitUpReason' in nonZt).toBe(false)
  })

  it('projectRuntimeFields projects the same limit-up fields without touching related reason', () => {
    // 两条投影链（project / projectRuntimeFields）口径必须一致：涨停字段全量投影到独立键，
    // stock.reason 只来自 getStockReason（关联原因），涨停原因不覆盖
    dataLayer.setMergedStocks([baseStock()])
    dataLayer.updateStockReasons([{ code: '000001', reason: '算力龙头' }])
    dataLayer.updateLimitUpData([
      {
        code: '000001',
        reason: '兵装重组+军工装备',
        lianbanStr: '3天2板',
        firstZtTime: '09:31:00',
        lastZtTime: '14:55:00',
        fengdan: 42000000,
        openNum: 1,
      },
    ])

    const stock: Record<string, unknown> = { ...baseStock() }
    extraDataProjector.projectRuntimeFields(stock)

    expect(stock.reason).toBe('算力龙头') // 关联原因（来自 stockReasons，非涨停原因）
    expect(stock.limitUpReason).toBe('兵装重组+军工装备') // 涨停原因独立键
    expect(stock.lianbanStr).toBe('3天2板')
    expect(stock.firstZtTime).toBe('09:31:00')
    expect(stock.lastZtTime).toBe('14:55:00')
    expect(stock.fengdan).toBe(42000000)
    expect(stock.openNum).toBe(1)
  })
})
