import { describe, expect, it } from 'vitest'

import { getRankField } from '../ComprehensiveRankEngine'

describe('ComprehensiveRankEngine', () => {
  it('maps platform rank fields', () => {
    expect(getRankField('eastmoney')).toBe('emRank')
    expect(getRankField('xueqiu')).toBe('xqRank')
    expect(getRankField('unknown')).toBeNull()
  })
})
