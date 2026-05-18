import { describe, expect, it } from 'vitest'

describe('PinyinUtils', () => {
  it('uses the packaged pinyin library without a global window mount', async () => {
    const { PinyinUtils } = await import('../pinyin')

    expect(PinyinUtils.isAvailable()).toBe(true)
    expect(PinyinUtils.getPinyinInitials('平安银行')).toBe('PAYH')
  })
})
