import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, test } from 'vitest'

const panelSource = () =>
  readFileSync(join(process.cwd(), 'src', 'components', 'panels', 'TradeJournalPanel.vue'), 'utf8')
const appSource = () => readFileSync(join(process.cwd(), 'src', 'App.vue'), 'utf8')

describe('TradeJournalPanel source contract', () => {
  test('is positioned as a historical trade log instead of a candidate thesis panel', () => {
    const source = panelSource()

    expect(source).toContain('历史交易日志')
    expect(source).not.toContain('候选与交易假设')
    expect(source).not.toContain('新增候选/假设')
    expect(source).not.toContain('编辑候选/假设')
    expect(source).not.toContain('暂无候选/假设记录')
    expect(source).not.toContain('市场环境')
    expect(source).not.toContain('题材地位')
    expect(source).not.toContain('个股角色')
    expect(source).not.toContain('人工决策')
    expect(source).not.toContain('未执行原因')
    expect(source).not.toContain('预期持仓天数')
  })

  test('defaults manual records to real trade entries and keeps thesis records out of the list query', () => {
    const source = panelSource()

    expect(source).toMatch(/tradeType:\s*'entry'/)
    expect(source).toMatch(/entry\.tradeType !== 'thesis'/)
    expect(source).not.toMatch(/tradeType:\s*'thesis'/)
    expect(source).not.toMatch(/trade_type:\s*'thesis'/)
  })

  test('renames the app menu entry to historical trade log', () => {
    const source = appSource()

    expect(source).toContain('历史交易日志')
    expect(source).not.toContain('<span class="item-icon">📓</span>交易日记')
  })
})
