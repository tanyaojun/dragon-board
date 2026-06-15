import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, test } from 'vitest'

const panelSource = () =>
  readFileSync(join(process.cwd(), 'src', 'components', 'panels', 'TradeJournalPanel.vue'), 'utf8')
const appSource = () => readFileSync(join(process.cwd(), 'src', 'App.vue'), 'utf8')

describe('TradeJournalPanel source contract', () => {
  test('is positioned as the trading pool instead of the old historical trade log', () => {
    const source = panelSource()

    expect(source).toContain('交易池')
    expect(source).toContain('Trading Pool')
    expect(source).toContain('新建交易池记录')
    expect(source).toContain('保存交易池记录')
    expect(source).toContain('删除交易池记录')
    expect(source).not.toContain('历史交易日志')
    expect(source).not.toContain('记录真实交易')
    expect(source).not.toContain('暂无历史交易记录')
    expect(source).not.toContain('记录出场')
    expect(source).not.toContain('候选与交易假设')
    expect(source).not.toContain('新增候选/假设')
    expect(source).not.toContain('编辑候选/假设')
    expect(source).not.toContain('暂无候选/假设记录')
  })

  test('loads and writes durable trading-pool journal records only', () => {
    const source = panelSource()

    expect(source).toContain("const TRADING_POOL_TYPE = 'trading_pool' as const")
    expect(source).toMatch(/tradeType:\s*TRADING_POOL_TYPE/)
    expect(source).toMatch(/trade_type:\s*TRADING_POOL_TYPE/)
    expect(source).toMatch(/entry\.tradeType === TRADING_POOL_TYPE/)
    expect(source).toContain('signals_snapshot: buildTradingPoolFormSnapshot()')
    expect(source).toContain('signalsSnapshot.tradingPool')
    expect(source).not.toContain("const TRADE_LOG_TYPES = ['entry', 'exit'] as const")
    expect(source).not.toMatch(/trade_type:\s*'entry'/)
    expect(source).not.toMatch(/trade_type:\s*'exit'/)
    expect(source).not.toMatch(/tradeType:\s*'thesis'/)
    expect(source).not.toMatch(/trade_type:\s*'thesis'/)
  })

  test('uses trading-pool status and decision wording', () => {
    const source = panelSource()

    expect(source).toContain("status: 'active'")
    expect(source).toContain('全部跟踪状态')
    expect(source).toContain('跟踪中')
    expect(source).toContain('观察买点')
    expect(source).toContain('降级观察')
    expect(source).toContain('信号过期')
    expect(source).toContain('复筛备注')
    expect(source).not.toContain('全部交易状态')
    expect(source).not.toContain('已平仓')
    expect(source).not.toContain('先记录一笔真实入场或调整筛选条件。')
  })

  test('renames the app menu entry to trading pool', () => {
    const source = appSource()

    expect(source).toContain('<span class="item-icon">🎯</span>交易池')
    expect(source).not.toContain('历史交易日志')
    expect(source).not.toContain('<span class="item-icon">📓</span>交易日记')
  })

  test('uses the same dashboard-grade visual language as the candidate pool', () => {
    const source = panelSource()

    expect(source).toContain('<style scoped>')
    expect(source).toContain('class="trade-journal-overlay"')
    expect(source).toContain('class="journal-shell"')
    expect(source).toContain('class="journal-list-panel"')
    expect(source).toContain('class="journal-detail-panel"')
    expect(source).toContain('class="metric-card"')
    expect(source).toContain('--candidate-bg: #111318')
    expect(source).toContain('--candidate-surface: #1b2028')
    expect(source).toContain('--candidate-text: #f4f7fb')
    expect(source).toContain('--candidate-accent: #ffb13b')
    expect(source).toContain('font-family: var(--candidate-font-ui)')
    expect(source).toContain('font-family: var(--candidate-font-data)')
    expect(source).toMatch(/\.journal-entry-card\.active::before/)
    expect(source).toMatch(/@media\s*\(max-width:\s*860px\)/)
    expect(source).not.toMatch(/<div[^>]+style="/)
    expect(source).not.toMatch(/<button[^>]+style="/)
    expect(source).not.toMatch(/<input[^>]+style="/)
    expect(source).not.toMatch(/<select[^>]+style="/)
    expect(source).not.toMatch(/<textarea[^>]+style="/)
  })
})
