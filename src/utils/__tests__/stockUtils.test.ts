import { describe, expect, it } from 'vitest'

import { StockUtils } from '../common'

describe('StockUtils.getLimitThreshold 分板块涨跌停阈值', () => {
  it('主板（沪 60x / 深 000-003）使用 ±10% 阈值', () => {
    for (const code of ['600001', '601001', '603001', '605001', '000001', '001001', '002001', '003001']) {
      expect(StockUtils.getLimitThreshold(code)).toEqual({ up: 9.8, down: -9.8 })
    }
  })

  it('创业板（300/301/302）使用 ±20% 阈值', () => {
    for (const code of ['300001', '301001', '302001']) {
      expect(StockUtils.getLimitThreshold(code)).toEqual({ up: 19.8, down: -19.8 })
    }
  })

  it('科创板（688/689）使用 ±20% 阈值', () => {
    for (const code of ['688001', '689009']) {
      expect(StockUtils.getLimitThreshold(code)).toEqual({ up: 19.8, down: -19.8 })
    }
  })

  it('北交所（43/82-88/920）使用 ±30% 阈值', () => {
    for (const code of ['430001', '830001', '870001', '920001']) {
      expect(StockUtils.getLimitThreshold(code)).toEqual({ up: 29.8, down: -29.8 })
    }
  })

  it('主板 ST 股 2026-09 起与主板一致（±10%），不再降为 5%', () => {
    expect(StockUtils.getLimitThreshold('600001', 'ST测试')).toEqual({ up: 9.8, down: -9.8 })
    expect(StockUtils.getLimitThreshold('000001', '*ST测试')).toEqual({ up: 9.8, down: -9.8 })
  })

  it('创业板/科创板/北交所 ST 股保持板块阈值，ST 名称不影响判定', () => {
    expect(StockUtils.getLimitThreshold('300001', 'ST测试')).toEqual({ up: 19.8, down: -19.8 })
    expect(StockUtils.getLimitThreshold('688001', '*ST测试')).toEqual({ up: 19.8, down: -19.8 })
    expect(StockUtils.getLimitThreshold('920001', 'ST测试')).toEqual({ up: 29.8, down: -29.8 })
  })
})

describe('StockUtils.isLimitUp / isLimitDown 按板块判定', () => {
  it('主板 9.4% 记为涨停（容差内），9.2% 不算', () => {
    expect(StockUtils.isLimitUp(9.4, '600001', '主板股')).toBe(true)
    expect(StockUtils.isLimitUp(9.2, '600001', '主板股')).toBe(false)
  })

  it('创业板 9.9% 不算涨停，19.5% 才算', () => {
    expect(StockUtils.isLimitUp(9.9, '300001', '创业板股')).toBe(false)
    expect(StockUtils.isLimitUp(19.5, '300001', '创业板股')).toBe(true)
  })

  it('科创板 19.5% 算涨停（689 同样适用）', () => {
    expect(StockUtils.isLimitUp(19.5, '688001', '科创板股')).toBe(true)
    expect(StockUtils.isLimitUp(19.5, '689009', '科创板CDR')).toBe(true)
  })

  it('北交所 29% 不算涨停，29.5% 才算（含 43/920 前缀）', () => {
    expect(StockUtils.isLimitUp(29, '430001', '北交所股')).toBe(false)
    expect(StockUtils.isLimitUp(29.5, '830001', '北交所股')).toBe(true)
    expect(StockUtils.isLimitUp(29.5, '920001', '北交所股')).toBe(true)
  })

  it('主板 ST 股按 ±10% 判定：9.4% 算涨停，4.6% 不算', () => {
    expect(StockUtils.isLimitUp(9.4, '600001', 'ST测试')).toBe(true)
    expect(StockUtils.isLimitUp(4.6, '600001', 'ST测试')).toBe(false)
  })

  it('跌停按板块对称判定', () => {
    expect(StockUtils.isLimitDown(-9.4, '600001', '主板股')).toBe(true)
    expect(StockUtils.isLimitDown(-9.9, '300001', '创业板股')).toBe(false)
    expect(StockUtils.isLimitDown(-19.5, '300001', '创业板股')).toBe(true)
    expect(StockUtils.isLimitDown(-29.5, '920001', '北交所股')).toBe(true)
  })
})
