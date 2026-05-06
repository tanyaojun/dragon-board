import { beforeEach, describe, expect, it } from 'vitest'

import { dataLayer } from '../../DataLayer'
import { ExtraDataProjector } from '../ExtraDataProjector'

describe('ExtraDataProjector', () => {
  beforeEach(() => {
    dataLayer.reset()
  })

  it('projects stock tags and reason from DataLayer during merge', () => {
    dataLayer.updateStockTags([{ code: '000001', tags: [{ Name: '算力' }] }])
    dataLayer.updateLimitUpData([{ code: '000001', reason: '算力龙头' }])

    const [stock] = new ExtraDataProjector().project([{ code: '000001', name: '样本股' }])

    expect(stock.tags).toEqual([{ Name: '算力' }])
    expect(stock.reason).toBe('算力龙头')
  })
})
