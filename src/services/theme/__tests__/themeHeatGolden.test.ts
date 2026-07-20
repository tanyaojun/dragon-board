import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { buildSnapshotSectorRows } from '../../snapshot/builders'
import type { SnapshotRecord } from '../../snapshot/types'
import { ThemeHeatFeed } from '../ThemeHeatFeed'
import { toHotThemeSummary } from '../ThemeFacade'

const fixture = JSON.parse(
  readFileSync(
    join(process.cwd(), 'quant-board', 'tests', 'fixtures', 'theme_heat_market_golden_v1.json'),
    'utf8',
  ),
)

function record(): SnapshotRecord {
  return {
    id: 'half_hour:2026-06-21:10:00',
    type: 'half_hour',
    tradingDate: '2026-06-21',
    slotTime: '10:00',
    timestamp: fixture.expected.computedAt,
    displayKey: '2026-06-21 10:00',
    captureMode: 'auto',
    source: 'runtime',
    payload: {},
    qualityFlags: [],
    delayMs: 0,
    createdAt: fixture.expected.computedAt,
    updatedAt: fixture.expected.computedAt,
  }
}

describe('theme heat market golden consumer contract', () => {
  it('preserves backend scores and nullable fund fields across runtime, UI and snapshot rows', async () => {
    const api = {
      getThemeHeat: async () => ({ data: fixture.expected }),
      getThemeHeatStocks: async () => ({ data: { stocks: [] } }),
    } as any
    const feed = new ThemeHeatFeed(api)

    await feed.refresh()
    const runtime = feed.getRuntimeFactors()
    const ai = runtime.find((factor) => factor.themeId === 'AI')!
    const power = runtime.find((factor) => factor.themeId === 'POWER')!
    const apiPower = fixture.expected.factors.find((factor: any) => factor.themeId === 'POWER')
    const summary = toHotThemeSummary(power, apiPower)
    const factors = fixture.expected.factors.map((factor: any) => ({
      ...factor,
      metadata: { ...factor.metadata, quoteSource: 'tencent', fundSource: 'ths_l2' },
    }))
    const rows = buildSnapshotSectorRows(record(), { themeHeatFactors: factors } as any)
    const powerRow = rows.find((row) => row.entityKey === 'POWER')

    expect(ai).toMatchObject({ heatScore: 76, fundScore: 58.75, netInflow: 5_000_000 })
    expect(summary).toMatchObject({ fundScore: null, mainNetInflow: null, degraded: true })
    expect(rows).toHaveLength(fixture.expected.factors.length)
    expect(powerRow).toMatchObject({
      heatScore: 19,
      fundScore: null,
      mainNetInflow: null,
      metadata: expect.objectContaining({ quoteSource: 'tencent', fundSource: 'ths_l2' }),
    })
  })
})
