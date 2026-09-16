import { describe, expect, it } from 'vitest'
import {
  buildObservationFactorRows,
  buildMarketPercentileRows,
} from '../observationFactors'

describe('buildObservationFactorRows', () => {
  it('组装 价格动量/ATR/量比/价rank背离 四行，档位+核心读数+原因', () => {
    const rows = buildObservationFactorRows({
      priceMomentum: {
        maTrend: 'down',
        momentumScore: 7.5065,
        momentumSignal: 'buy',
        signalTier: 'B',
        tierReasons: ['价格动量 buy（均线未确认）'],
      },
      atrMeanReversion: {
        status: 'insufficient',
        direction: 'hold',
        score: 0,
        missingBars: 29,
        reasons: ['ATR 样本不足（1/20 帧）'],
        signalTier: 'unknown',
      },
      amountRatio: null,
      priceRankDivergence: {
        state: 'unknown',
        priceDir: 'up',
        rankDir: 'flat',
        tierReasons: ['价格/排名方向不明确（flat 态）'],
        signalTier: 'unknown',
      },
    })
    expect(rows.map((row) => row.label)).toEqual(['价格动量', 'ATR均值回归', '量比异动', '价/排名背离'])
    expect(rows[0]).toMatchObject({ tier: 'B', primary: '动量 +7.51 · 均线下行（buy）' })
    expect(rows[1]).toMatchObject({ tier: 'unknown', primary: '样本不足（缺 29 帧）' })
    expect(rows[2]).toMatchObject({ tier: null, primary: '缺数据' })
    expect(rows[3]).toMatchObject({ primary: '价格 上行 / 排名 走平' })
    expect(rows[0].reason).toBe('价格动量 buy（均线未确认）')
  })

  it('ATR 正常态显示偏差与 ATR 值', () => {
    const rows = buildObservationFactorRows({
      atrMeanReversion: {
        status: 'ok',
        deviation: -8.2,
        atr: 0.42,
        signalTier: 'A',
      },
    })
    expect(rows[0]).toMatchObject({ primary: '缺数据' })
    expect(rows[1]).toMatchObject({ tier: 'A', primary: '偏差 -8.2% · ATR 0.42' })
  })

  it('observation 整体缺失仍返回四行占位（fail-visible，不隐藏轴存在）', () => {
    const rows = buildObservationFactorRows(undefined)
    expect(rows).toHaveLength(4)
    expect(rows.every((row) => row.primary === '缺数据')).toBe(true)
  })
})

describe('buildMarketPercentileRows', () => {
  it('成交额转亿、量比/换手率保留两位小数', () => {
    const rows = buildMarketPercentileRows({
      turnoverP50: 446930256.0,
      turnoverP70: 663465971.2,
      turnoverP85: 1259586515.2,
      volumeRatioP50: 1.145,
      volumeRatioP70: 4.771,
      volumeRatioP85: 13.761,
      turnoverRateP50: 2.66,
      turnoverRateP70: 4.42,
      turnoverRateP85: 7.186,
    })
    expect(rows).toEqual([
      { label: '成交额', unit: '亿', p50: '4.47', p70: '6.63', p85: '12.60' },
      { label: '量比', unit: '', p50: '1.15', p70: '4.77', p85: '13.76' },
      { label: '换手率', unit: '%', p50: '2.66', p70: '4.42', p85: '7.19' },
    ])
  })

  it('缺字段返回 null（调用方整块隐藏，不伪造）', () => {
    expect(buildMarketPercentileRows(undefined)).toBeNull()
    expect(buildMarketPercentileRows({})).toBeNull()
  })
})
