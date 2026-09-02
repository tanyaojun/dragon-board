import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

describe('DataTable resonance tooltip decoupled from theme momentum', () => {
  const source = readFileSync(
    join(process.cwd(), 'src', 'components', 'common', 'DataTable.vue'),
    'utf8',
  )

  it('removes inline theme momentum section from resonance tooltip', () => {
    expect(source).not.toContain('【题材动量】')
    expect(source).not.toContain('resonance.theme.themeMomentumScore')
  })

  it('renders limit-up reason from the dedicated limitUpReason field next to related reason', () => {
    // 2026-09-02 口径：题材 tooltip 中「关联原因」（stock.reason，主营业务静态文本）与
    // 「涨停原因」（stock.limitUpReason，同花顺涨停池 reason_type）是两个独立字段
    expect(source).toContain('📋 关联原因:')
    expect(source).toContain('🚀 涨停原因: ${stock.limitUpReason}')
    expect(source).not.toContain('merged.reason = limitUpData.reason')
  })
})
