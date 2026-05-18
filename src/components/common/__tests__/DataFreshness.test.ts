import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, test } from 'vitest'

const dataFreshnessSource = () =>
  readFileSync(join(process.cwd(), 'src', 'components', 'common', 'DataFreshness.vue'), 'utf8')

describe('DataFreshness realtime stock list filter', () => {
  test('uses MACD golden cross as the stock list entry condition', () => {
    const source = dataFreshnessSource()

    expect(source).toMatch(/const\s+isMacdGoldenCross\s*=\s*\(stock:\s*any\)\s*=>/)
    expect(source).toMatch(/getMacdCross\(stock\)\s*===\s*'golden'/)
    expect(source).toMatch(/stock\?\.rankTrend\?\.technical\?\.macd\?\.cross\s*\?\?\s*stock\?\.macdCross\s*\?\?\s*'none'/)
    expect(source).toMatch(/Boolean\(stock\)\s*&&\s*isMacdGoldenCross\(stock\)/)
    expect(source).not.toMatch(/isMainFocusStock/)
    expect(source).not.toMatch(/candidateTier\s*\?\?\s*null/)
    expect(source).not.toMatch(/strategy\?\.action\s*\?\?\s*null/)
  })
})
