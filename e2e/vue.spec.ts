import { expect, test, type Page, type Route } from '@playwright/test'

const NOW = '2026-05-17T10:00:00+08:00'

type JournalEntry = {
  id: string
  stock_code: string
  stock_name: string
  status: string
  direction: string
  trade_type: string
  price: number
  volume: number
  entry_reason: string
  trade_hypothesis: string
  entry_prerequisites: string
  invalidation_rules: string
  human_decision: string
  skip_reason: string
  review_outcome: string
  model_result: string
  execution_result: string
  review_notes: string
  review_tags: string[]
  signals_snapshot: Record<string, unknown> | null
  created_at: string
  updated_at: string
  linked_entry_id?: string | null
  pnl?: number | null
  notes?: string
}

const stockRows = [
  {
    code: '600584',
    name: '长电科技',
    price: 58.05,
    change: 4.6,
    zlje: 1_080_000_000,
    zljzb: 10.2,
    cddje: 320_000_000,
    cddjzb: 4.4,
    volumeRatio: 1.45,
    turnoverRate: 6.2,
    turnover: 2_100_000_000,
  },
  {
    code: '600759',
    name: 'ST洲际',
    price: 3.21,
    change: -2.4,
    zlje: -80_000_000,
    zljzb: -4.2,
    cddje: -20_000_000,
    cddjzb: -1.6,
    volumeRatio: 0.8,
    turnoverRate: 2.1,
    turnover: 300_000_000,
  },
  {
    code: '603601',
    name: '再升科技',
    price: 6.52,
    change: 2.8,
    zlje: 130_000_000,
    zljzb: 5.1,
    cddje: 30_000_000,
    cddjzb: 1.8,
    volumeRatio: 1.2,
    turnoverRate: 3.7,
    turnover: 450_000_000,
  },
  {
    code: '000001',
    name: '平安银行',
    price: 12.35,
    change: 0.8,
    zlje: 60_000_000,
    zljzb: 1.2,
    cddje: 10_000_000,
    cddjzb: 0.8,
    volumeRatio: 0.9,
    turnoverRate: 1.5,
    turnover: 900_000_000,
  },
  {
    code: '002407',
    name: '多氟多',
    price: 36.47,
    change: 5.2,
    zlje: 210_000_000,
    zljzb: 6.2,
    cddje: 80_000_000,
    cddjzb: 2.2,
    volumeRatio: 1.3,
    turnoverRate: 5.1,
    turnover: 620_000_000,
  },
  {
    code: '000970',
    name: '中科三环',
    price: 14.2,
    change: 6.5,
    zlje: 180_000_000,
    zljzb: 5.8,
    cddje: 48_000_000,
    cddjzb: 1.9,
    volumeRatio: 1.6,
    turnoverRate: 4.8,
    turnover: 580_000_000,
  },
]

function createRankTrend(code: string, rank: number, tier = 'A_MAIN') {
  return {
    meta: {
      code,
      currentRank: rank,
      currentPercentile: 82,
      change: 12,
      rawChange: 12,
      updateTime: Date.now(),
      sampleQuality: {
        snapshotType: 'half_hour',
        sampleCount: 6,
        requiredSampleCount: 5,
        status: 'ok',
        delayedCount: 0,
        restoredCount: 0,
      },
    },
    technical: {
      movingAverage: { ma5: 5, ma10: 8, trend: 'up' },
      macd: { dif: 1.2, dea: 0.8, histogram: 0.4, cross: 'golden', rawScore: 78, confirmed: true },
      signals: {
        direction: { signal: 'buy', confidence: 88, score: 88 },
        acceleration: { signal: 'buy', confidence: 84, score: 84 },
        zeroCross: { signal: 'buy', confidence: 80, score: 80 },
      },
      momentumScore: 82,
      momentumProfile: { short: 8, mid: 6, long: 4, acceleration: 2, shock: 0, composite: 78 },
    },
    cycle: {
      rawStage: 'expansion',
      stage: 'expansion',
      previousStage: 'ignition',
      transition: 'ignition->expansion',
      confidence: 82,
      metrics: {
        rankVelocity: 5,
        rankAcceleration: 2,
        rankShock: 0,
        hotZoneStreak: 3,
        bestRecentRank: rank,
        drawdownFromPeak: 0,
      },
      entryAdvice: {
        bias: 'preferred',
        allowed: true,
        reason: '样本确认主升',
      },
    },
    risk: {
      overheat: { score: 18, signal: 'hold', severity: 0.18 },
      divergence: { score: 8, signal: 'hold', severity: 0.08 },
      pressure: 0.12,
      synergy: 0.35,
    },
    decision: {
      base: { signal: 'buy', confidence: 86, combinedScore: 86, scoreMargin: 22 },
      final: { signal: 'buy', confidence: 84 },
    },
    strategy: {
      regime: { state: 'strong', score: 80, reasons: ['测试市场强势'] },
      momentum: { short: 8, mid: 6, long: 4, acceleration: 2, shock: 0, composite: 78 },
      candidateTier: tier,
      action: 'focus',
      reasons: ['Phase 14 E2E 主升候选'],
    },
  }
}

function createThesisEntry(id: string, code: string, name: string, status = 'observe'): JournalEntry {
  const analysis = {
    version: 'candidate-rules-v1',
    score: code === '600584' ? 82 : 58,
    grade: code === '600584' ? 'A' : 'C',
    suggestedStatus: status,
    scoreBreakdown: {
      rankTrend: code === '600584' ? 30 : 10,
      theme: code === '600584' ? 18 : 8,
      dragon: code === '600584' ? 20 : 0,
      sentiment: 8,
      moneyFlow: code === '600584' ? 15 : 5,
    },
    structuredThesis: {
      triggerConditions: [],
      entryPrerequisites: [],
      invalidationConditions: [],
    },
    structuredRisks: [],
    riskWarnings: [],
    strengths: ['规则样本'],
    weaknesses: [],
    evidence: [],
    penalties: [],
    generatedAt: Date.now(),
  }
  return {
    id,
    stock_code: code,
    stock_name: name,
    status,
    direction: 'buy',
    trade_type: 'thesis',
    price: code === '600584' ? 58.05 : 3.21,
    volume: 0,
    entry_reason: `${name} 入池理由`,
    trade_hypothesis: `${name} 交易假设`,
    entry_prerequisites: `${name} 买入前提`,
    invalidation_rules: `${name} 失效条件`,
    human_decision: 'watch',
    skip_reason: '',
    review_outcome: 'pending',
    model_result: 'unknown',
    execution_result: 'unknown',
    review_notes: '',
    review_tags: code === '600584' ? ['A', 'A_MAIN', '国产芯片'] : ['C'],
    signals_snapshot: {
      quote: stockRows.find((stock) => stock.code === code) || { code, name },
      rankTrend: createRankTrend(code, code === '600584' ? 1 : 4, code === '600584' ? 'A_MAIN' : 'N_NEUTRAL'),
      theme: {
        primaryTheme: '国产芯片',
        exposures: [
          {
            code,
            themeId: 'chip',
            themeName: '国产芯片',
            role: code === '600584' ? 'leader' : 'follower',
            exposureWeight: 1,
            themeContribution: code === '600584' ? 18 : 8,
            riskPenalty: 0,
          },
        ],
      },
      dragon: code === '600584' ? { primaryRole: 'MARKET_CORE', authority: 'TRUE_LEADER' } : null,
      sentiment: { overall: 62, phase: 'start', phaseName: '启动' },
      candidateAnalysis: analysis,
    },
    created_at: NOW,
    updated_at: NOW,
  }
}

function createTradeEntry(): JournalEntry {
  return {
    id: 'trade_000001',
    stock_code: '000001',
    stock_name: '平安银行',
    status: 'closed',
    direction: 'buy',
    trade_type: 'entry',
    price: 12.1,
    volume: 1000,
    entry_reason: '',
    trade_hypothesis: '',
    entry_prerequisites: '',
    invalidation_rules: '',
    human_decision: 'execute',
    skip_reason: '',
    review_outcome: 'success',
    model_result: 'correct',
    execution_result: 'good',
    review_notes: '历史交易样本',
    review_tags: ['历史交易'],
    signals_snapshot: null,
    created_at: NOW,
    updated_at: NOW,
    pnl: 250,
    notes: '历史交易日志样本',
  }
}

function cloneEntry(entry: JournalEntry): JournalEntry {
  return JSON.parse(JSON.stringify(entry)) as JournalEntry
}

function normalizeCode(value: string | null): string {
  const digits = String(value || '').replace(/\D/g, '')
  return digits ? digits.padStart(6, '0').slice(-6) : ''
}

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  })
}

async function setupCandidateRoutes(page: Page) {
  const state = {
    failJournalList: false,
    journalEntries: [
      createThesisEntry('thesis_600759', '600759', 'ST洲际', 'observe'),
      createTradeEntry(),
    ],
    createdCount: 0,
    postCount: 0,
    putPayloads: [] as Array<{ id: string; payload: Record<string, unknown> }>,
    deleteIds: [] as string[],
  }

  await page.route('**/api/journal/stats**', (route) =>
    fulfillJson(route, {
      totalPnl: 250,
      winRate: 1,
      totalExits: 1,
    }),
  )

  await page.route((url) => url.pathname === '/api/journal/entries', async (route) => {
    const request = route.request()
    const method = request.method()
    const url = new URL(request.url())
    if (method === 'GET') {
      if (state.failJournalList) {
        await fulfillJson(route, { message: 'journal unavailable' }, 503)
        return
      }
      const tradeType = url.searchParams.get('trade_type')
      const stockCode = normalizeCode(url.searchParams.get('stock_code'))
      const status = url.searchParams.get('status')
      const entries = state.journalEntries.filter((entry) => {
        if (tradeType && entry.trade_type !== tradeType) return false
        if (stockCode && entry.stock_code !== stockCode) return false
        if (status && entry.status !== status) return false
        return true
      })
      await fulfillJson(route, { entries: entries.map(cloneEntry), total: entries.length })
      return
    }

    if (method === 'POST') {
      const payload = request.postDataJSON() as Record<string, unknown>
      state.postCount += 1
      const code = normalizeCode(String(payload.stock_code || ''))
      const row = stockRows.find((stock) => stock.code === code)
      const entry: JournalEntry = {
        id: `thesis_created_${++state.createdCount}`,
        stock_code: code,
        stock_name: String(payload.stock_name || row?.name || code),
        status: String(payload.status || 'observe'),
        direction: String(payload.direction || 'buy'),
        trade_type: String(payload.trade_type || 'thesis'),
        price: Number(payload.price || row?.price || 0),
        volume: Number(payload.volume || 0),
        entry_reason: String(payload.entry_reason || ''),
        trade_hypothesis: String(payload.trade_hypothesis || ''),
        entry_prerequisites: String(payload.entry_prerequisites || ''),
        invalidation_rules: String(payload.invalidation_rules || ''),
        human_decision: String(payload.human_decision || 'watch'),
        skip_reason: String(payload.skip_reason || ''),
        review_outcome: String(payload.review_outcome || 'pending'),
        model_result: String(payload.model_result || 'unknown'),
        execution_result: String(payload.execution_result || 'unknown'),
        review_notes: String(payload.review_notes || ''),
        review_tags: Array.isArray(payload.review_tags) ? payload.review_tags.map(String) : [],
        signals_snapshot: (payload.signals_snapshot as Record<string, unknown>) || null,
        created_at: NOW,
        updated_at: NOW,
      }
      state.journalEntries.unshift(entry)
      await fulfillJson(route, cloneEntry(entry), 201)
      return
    }

    await fulfillJson(route, { message: 'unsupported method' }, 405)
  })

  await page.route((url) => /^\/api\/journal\/entries\/[^/]+$/.test(url.pathname), async (route) => {
    const request = route.request()
    const method = request.method()
    const id = decodeURIComponent(new URL(request.url()).pathname.split('/').pop() || '')
    const index = state.journalEntries.findIndex((entry) => entry.id === id)

    if (method === 'PUT') {
      if (index < 0) {
        await fulfillJson(route, { message: 'not found' }, 404)
        return
      }
      const payload = request.postDataJSON() as Record<string, unknown>
      state.putPayloads.push({ id, payload })
      state.journalEntries[index] = {
        ...state.journalEntries[index],
        ...Object.fromEntries(
          Object.entries(payload).filter(([, value]) => value !== undefined),
        ),
        updated_at: NOW,
      } as JournalEntry
      await fulfillJson(route, cloneEntry(state.journalEntries[index]))
      return
    }

    if (method === 'DELETE') {
      state.deleteIds.push(id)
      if (index >= 0) state.journalEntries.splice(index, 1)
      await fulfillJson(route, { id, status: 'deleted' })
      return
    }

    await fulfillJson(route, { message: 'unsupported method' }, 405)
  })

  await page.route('**/api/stocks/names**', (route) =>
    fulfillJson(route, {
      ok: true,
      version: 'phase14-e2e',
      stocks: stockRows.map((stock) => ({
        code: stock.code,
        name: stock.name,
        market: stock.code.startsWith('6') ? 'SH' : 'SZ',
        type: 'stock',
        active: true,
      })),
    }),
  )

  await page.route('**/api/themes/mapping**', (route) =>
    fulfillJson(route, {
      ok: true,
      mapping: {
        version: 'phase14-e2e',
        lastUpdate: NOW,
        totalThemes: 1,
        themes: [
          {
            id: 'chip',
            name: '国产芯片',
            zsCode: 'BKCHIP',
            stocks: ['600584', '600759', '603601'],
            stockTags: {
              '600584': [{ Name: '先进封装', Reason: '封测龙头' }],
              '603601': [{ Name: '材料', Reason: '半导体材料' }],
            },
            stockReasons: {
              '600584': '先进封装核心样本',
              '603601': '材料补涨样本',
            },
          },
        ],
      },
    }),
  )

  await page.route('**/api/ranktrend/rank-series**', (route) => {
    const frames = Array.from({ length: 6 }, (_, index) => {
      const ranks: Record<string, number> = {}
      stockRows.forEach((stock, stockIndex) => {
        ranks[stock.code] = Math.max(1, stockIndex + 1 + (5 - index))
      })
      ranks['600584'] = Math.max(1, 6 - index)
      return {
        snapshotId: `phase14-${index}`,
        displayKey: `2026-05-17 ${String(9 + index).padStart(2, '0')}:30`,
        timestamp: Date.now() - (6 - index) * 30 * 60 * 1000,
        type: 'half_hour',
        tradingDate: '2026-05-17',
        slotTime: `${String(9 + index).padStart(2, '0')}:30`,
        captureMode: 'real_time',
        totalCount: stockRows.length,
        ranks,
      }
    })
    return fulfillJson(route, { frames })
  })

  await page.route('**/api/snapshots/stock-rows**', (route) => fulfillJson(route, { rows: [] }))
  await page.route('**/api/snapshots/sector-rows**', (route) => fulfillJson(route, { rows: [] }))
  await page.route('**/api/snapshots/records**', (route) => fulfillJson(route, { records: [] }))
  await page.route('**/api/snapshots/frames**', (route) => fulfillJson(route, { frames: [] }))
  await page.route('**/api/snapshots/counts**', (route) => fulfillJson(route, { counts: [] }))

  await page.route('**/api/eastmoney/hot', (route) =>
    fulfillJson(route, { data: stockRows.map((stock) => ({ sc: stock.code, sn: stock.name })) }),
  )
  await page.route('**/api/ths/hot', (route) =>
    fulfillJson(route, {
      data: {
        stock_list: stockRows.map((stock, index) => ({
          order: index + 1,
          code: stock.code,
          name: stock.name,
          rate: String(stock.change),
        })),
      },
    }),
  )
  await page.route('**/api/kpl/hot', (route) =>
    fulfillJson(route, {
      data: stockRows.map((stock, index) => [stock.code, stock.name, stock.change, 0, index + 1]),
    }),
  )
  await page.route('**/api/tdx/hot', (route) =>
    fulfillJson(route, [
      ['meta'],
      ['meta'],
      ['meta'],
      ...stockRows.map((stock, index) => [null, stock.code, stock.name, stock.change, 0, 0, 0, 0, 0, 0, index + 1]),
    ]),
  )
  await page.route('**/api/xueqiu/hot', (route) =>
    fulfillJson(route, {
      data: {
        items: stockRows.map((stock) => ({ code: stock.code, name: stock.name, percent: stock.change })),
      },
    }),
  )
  await page.route('**/api/cls/hot', (route) =>
    fulfillJson(route, {
      errno: 0,
      data: stockRows.map((stock) => ({
        stock: { StockID: stock.code, name: stock.name, RiseRange: stock.change },
      })),
    }),
  )
  await page.route('**/api/tgb/hot', (route) =>
    fulfillJson(route, {
      dto: stockRows.map((stock, index) => ({
        ranking: index + 1,
        fullCode: stock.code,
        stockName: stock.name,
        popularValue: 100 - index,
        reason: stock.code === '600584' ? '国产芯片' : '',
      })),
    }),
  )
  await page.route('**/api/dzh/hot', (route) =>
    fulfillJson(route, {
      result: stockRows.map((stock, index) => ({ [stock.code.startsWith('6') ? `SH${stock.code}` : `SZ${stock.code}`]: index + 1 })),
    }),
  )

  await page.route('**/api/quotes/**', (route) => {
    const url = new URL(route.request().url())
    const codes = (url.searchParams.get('codes') || '').split(',').map(normalizeCode).filter(Boolean)
    const diff = codes.map((code) => {
      const stock = stockRows.find((item) => item.code === code) || stockRows[0]
      return {
        f12: code,
        f14: stock.name,
        f2: String(stock.price),
        f3: String(stock.change),
        f5: String(stock.turnover),
        f6: String(stock.turnover),
        f8: String(stock.turnoverRate),
        f9: '18',
        f20: '1200',
        f21: '900',
        f23: '2.8',
        f62: String(stock.zlje),
        f66: String(stock.cddje),
        f69: String(stock.cddjzb),
        f184: String(stock.zljzb),
      }
    })
    return fulfillJson(route, { data: { diff } })
  })

  await page.route('**/api/tdx/**', (route) => fulfillJson(route, { ok: true, data: [] }))
  await page.route('**/api/market/**', (route) => fulfillJson(route, { ok: true, data: {} }))
  await page.route('**/api/limitup/**', (route) => fulfillJson(route, { ok: true, data: [] }))

  return state
}

async function seedRuntime(page: Page) {
  const rowsWithRankTrend = stockRows.map((stock, index) => ({
    ...stock,
    rankTrend: createRankTrend(stock.code, index + 1),
  }))
  await page.evaluate((serializedRows) => {
    const rows = serializedRows as Array<typeof stockRows[number] & { rankTrend: ReturnType<typeof createRankTrend> }>
    const mapping = {
      version: 'phase14-e2e',
      lastUpdate: new Date().toISOString(),
      totalThemes: 1,
      themes: [
        {
          id: 'chip',
          name: '国产芯片',
          zsCode: 'BKCHIP',
          stocks: ['600584', '600759', '603601'],
          stockTags: {
            '600584': [{ Name: '先进封装', Reason: '封测龙头' }],
            '603601': [{ Name: '材料', Reason: '半导体材料' }],
          },
          stockReasons: {
            '600584': '先进封装核心样本',
            '603601': '材料补涨样本',
          },
        },
      ],
    }

    const stocks = rows.map((stock, index) => ({
      ...stock,
      rank: index + 1,
      compRank: index + 1,
      avgRank: index + 1,
      emRank: index + 1,
      thsRank: index + 1,
      kplRank: index + 1,
      tdxRank: index + 1,
      xqRank: index + 1,
      clsRank: index + 1,
      tgbRank: index + 1,
      dzhRank: index + 1,
      hotness: 100 - index * 8,
      leadStatus: stock.code === '600584' ? '龙一' : '',
      leadTimes: stock.code === '600584' ? 2 : 0,
      rankTrend: stock.rankTrend,
      themes: stock.code === '600584' ? [{ id: 'chip', name: '国产芯片' }] : [],
      candidatePoolLabel: stock.code === '000970' ? '观察候选' : undefined,
      candidatePoolProjection:
        stock.code === '000970'
          ? {
              stockCode: '000970',
              stockName: '中科三环',
              strategyName: 'ranktrend_early_big_move_v3_lifecycle_fusion',
              snapshotType: 'half_hour',
              tradingDate: '2026-05-17',
              snapshotId: 'half_hour:2026-05-17:10:00',
              frameTime: '2026-05-17T10:00:00+08:00',
              projectionSource: 'live',
              strategyState: 'idle',
              candidateTier: 'A_MAIN',
              lifecycleAction: 'allow',
              executionOverlay: null,
              entryDecision: {
                accepted: false,
                decisionState: 'watch_candidate',
                label: '观察候选',
                summary: '涨幅偏高，进入观察候选',
                checks: [
                  {
                    key: 'ranktrend_present',
                    label: 'RankTrend',
                    status: 'pass',
                    hardBlock: false,
                    actual: true,
                    expected: '存在 RankTrend 诊断',
                    message: '存在 RankTrend 诊断',
                  },
                  {
                    key: 'change_position',
                    label: '涨幅位置',
                    status: 'warn',
                    hardBlock: false,
                    actual: 6.5,
                    expected: '< 6 或观察',
                    message: '涨幅偏高，进入观察候选',
                  },
                  {
                    key: 'limit_up',
                    label: '涨停状态',
                    status: 'pass',
                    hardBlock: false,
                    actual: 'board_fallback',
                    expected: '未涨停',
                    message: '未处于涨停阻断状态',
                  },
                ],
                configSnapshot: {
                  version: 'live-v5.1.0',
                  mode: 'balanced',
                  minJumpConfidence: 85,
                  allowDegradedSample: true,
                  requireCandidateTier: false,
                  allowedCandidateTiers: ['A_MAIN', 'B_IGNITION'],
                  requireTierBMidAndZeroCross: false,
                  tierBMidMin: 20,
                  accelerationMin: 10,
                  accDeltaMin: 8,
                  changeGate: { mode: 'warn', maxEntryChangePct: 6 },
                  limitUpPolicy: 'quote_first',
                },
              },
            }
          : undefined,
    }))

    const runtime = window as any
    runtime.themeMapping?.setData(mapping)
    runtime.dataLayer?.updateJxbkBlocks?.([
      {
        code: 'BKCHIP',
        name: '国产芯片',
        strength: 4200,
        change: 3.6,
        mainNetInflow: 980_000_000,
        bigMoney300: 260_000_000,
        institutionBuy: 120_000_000,
        volumeRatio: 1.8,
        ztCount: 4,
      },
    ])
    runtime.dataLayer?.updateJxbkStocks?.([
      {
        code: '600584',
        name: '长电科技',
        blocks: ['BKCHIP'],
        score: 95,
      },
    ])
    runtime.dataLayer?.updateReviewData?.({
      reviewDate: '2026-05-17',
      regime: 'MAINLINE_ADVANCE',
      marketCore: {
        code: '600584',
        name: '长电科技',
        primaryRole: 'MARKET_CORE',
        roles: ['MARKET_CORE', 'THEME_CORE'],
        authority: 'TRUE_LEADER',
        tradeability: 'ACTIONABLE',
        chaseRisk: 'MEDIUM',
        status: 'CONFIRMED_LEADER',
        battlefieldId: 'chip',
        themeId: 'chip',
        themeName: '国产芯片',
        evidence: [],
        contradictions: [],
        fatalNegatives: [],
        invalidationReasons: [],
        successors: [],
        timeline: {},
        playbook: [],
        duelResults: [],
        confidence: 'HIGH',
        price: 58.05,
        change: 4.6,
        turnover: 2_100_000_000,
        turnoverRate: 6.2,
        zlje: 1_080_000_000,
        continuousDays: 1,
        highDays: 1,
        hotness: 100,
        popularity: 100,
        popularityChange: 10,
        leadStatus: '龙一',
        lianbanStr: '',
        boardHeight: 1,
        themes: [{ id: 'chip', name: '国产芯片' }],
      },
      battlefields: [],
      trueLeaders: [],
      heightBoard: [],
      attentionBoard: [],
      pseudoLeaderGraveyard: [],
      transitions: [],
      summaryLines: ['Phase 14 E2E'],
      missingData: [],
      reviewCompleteness: 'complete',
    })
    runtime.dataLayer?.setMergedStocks?.(stocks)
    runtime.themeFacade?.refreshThemeFactors?.()
  }, rowsWithRankTrend)
}

async function openCandidatePoolFromMenu(page: Page) {
  await page.getByRole('button').filter({ hasText: '⋯' }).click()
  await page.locator('.dropdown-menu .dropdown-item').filter({ hasText: '候选池' }).click()
  await expect(page.getByRole('heading', { name: '候选池' })).toBeVisible()
}

async function openTradeJournalFromMenu(page: Page) {
  await page.getByRole('button').filter({ hasText: '⋯' }).click()
  await page.locator('.dropdown-menu .dropdown-item').filter({ hasText: '历史交易日志' }).click()
  await expect(page.getByRole('heading', { name: '历史交易日志' })).toBeVisible()
}

async function addChangdianFromContextMenu(page: Page) {
  const row = page.locator('.data-row[data-code="600584"]')
  await expect(row).toBeVisible()
  await row.click({ button: 'right' })
  await page.locator('.context-menu .menu-item').filter({ hasText: '加入候选池' }).click()
  await expect(page.getByRole('heading', { name: '候选池' })).toBeVisible()
  await expect(page.locator('.candidate-detail')).toContainText('长电科技')
}

test.describe('候选池 Phase 14 回归', () => {
  test.setTimeout(60_000)

  test('右键入池、编辑假设、写回分析、保存复盘，并与历史交易日志隔离', async ({ page }, testInfo) => {
    const state = await setupCandidateRoutes(page)
    await page.goto('/')
    await expect(page.locator('.data-row[data-code="600584"]')).toBeVisible({ timeout: 20_000 })
    await seedRuntime(page)

    await addChangdianFromContextMenu(page)

    const entryReason = page.locator('.editor-card textarea').nth(0)
    await entryReason.fill('Phase 14 手工修正入池理由')
    await page.locator('.editor-card').getByRole('button', { name: '保存假设' }).click()
    await expect.poll(() => state.putPayloads.some((item) => item.payload.entry_reason === 'Phase 14 手工修正入池理由')).toBe(true)

    const writeBackButton = page.getByRole('button', { name: '写回当前分析' })
    const writeBackCount = state.putPayloads.length
    await writeBackButton.click()
    await expect.poll(() => state.putPayloads.some((item) => Boolean(item.payload.signals_snapshot))).toBe(true)
    await expect.poll(() => state.putPayloads.length).toBeGreaterThan(writeBackCount)
    await expect(writeBackButton).toBeEnabled()

    const reviewCard = page.locator('.review-card')
    await reviewCard.locator('select').nth(0).selectOption('success')
    await reviewCard.locator('select').nth(1).selectOption('correct')
    await reviewCard.locator('select').nth(2).selectOption('missed')
    await expect(reviewCard.locator('select').nth(0)).toHaveValue('success')
    await reviewCard.locator('textarea').fill('Phase 14 复盘闭环样本')
    await reviewCard.getByRole('button', { name: '保存复盘' }).click()
    await expect.poll(() => state.putPayloads.some((item) => item.payload.review_outcome === 'success' && item.payload.status === 'reviewed')).toBe(true)
    await expect(page.locator('.candidate-detail')).toContainText('已复盘')

    await page.screenshot({ path: testInfo.outputPath('candidate-pool-wide.png'), fullPage: true })
    await page.setViewportSize({ width: 900, height: 700 })
    await page.screenshot({ path: testInfo.outputPath('candidate-pool-narrow.png'), fullPage: true })

    await page.getByLabel('关闭候选池').click()
    await openTradeJournalFromMenu(page)
    const tradeJournal = page.getByRole('heading', { name: '历史交易日志' }).locator('..').locator('..')
    await expect(tradeJournal.getByText('平安银行')).toBeVisible()
    await expect(tradeJournal.getByText('长电科技')).toHaveCount(0)
  })

  test('重复候选右键进入详情，不重复创建；服务失败有明确提示；删除候选可回归', async ({ page }, testInfo) => {
    const state = await setupCandidateRoutes(page)
    await page.goto('/')
    await expect(page.locator('.data-row[data-code="600584"]')).toBeVisible({ timeout: 20_000 })
    await seedRuntime(page)

    await addChangdianFromContextMenu(page)
    await page.getByLabel('关闭候选池').click()

    const row = page.locator('.data-row[data-code="600584"]')
    await row.click({ button: 'right' })
    const candidateMenuItem = page.locator('.context-menu .menu-item').filter({ hasText: '查看候选详情' })
    await expect(candidateMenuItem).toBeVisible()
    await candidateMenuItem.click()
    await expect(page.locator('.candidate-detail')).toContainText('长电科技')
    expect(state.postCount).toBe(1)

    await page.screenshot({ path: testInfo.outputPath('candidate-pool-duplicate.png'), fullPage: true })

    await page.getByLabel('关闭候选池').click()
    state.failJournalList = true
    await openCandidatePoolFromMenu(page)
    await page.locator('.candidate-toolbar').getByRole('button', { name: '刷新' }).click()
    await expect(page.getByText(/候选池加载失败/)).toBeVisible()
    await page.screenshot({ path: testInfo.outputPath('candidate-pool-service-error.png'), fullPage: true })

    state.failJournalList = false
    await page.locator('.candidate-toolbar').getByRole('button', { name: '刷新' }).click()
    await expect(page.locator('.candidate-detail')).toContainText('长电科技')
    page.once('dialog', (dialog) => dialog.accept())
    await page.getByText('删除候选', { exact: true }).click()
    await expect.poll(() => state.deleteIds).toContain('thesis_created_1')
    await expect(page.locator('.candidate-detail')).not.toContainText('长电科技')
  })

  test('从既有候选池列打开未持久化 live projection 规则矩阵', async ({ page }, testInfo) => {
    await setupCandidateRoutes(page)
    await page.goto('/')
    await expect(page.locator('.data-row[data-code="600584"]')).toBeVisible({ timeout: 20_000 })
    await seedRuntime(page)

    const row = page.locator('.data-row[data-code="000970"]')
    await expect(row).toBeVisible()
    await expect(row.locator('.candidate-pool-badge')).toContainText('观察候选')
    await row.locator('.candidate-pool-badge').click()

    await expect(page.getByRole('heading', { name: '候选池' })).toBeVisible()
    const detail = page.locator('.candidate-detail')
    await expect(detail).toContainText('中科三环')
    await expect(detail).toContainText('规则矩阵')
    await expect(detail).toContainText('涨幅位置')
    await expect(detail).toContainText('观察')
    await expect(detail).toContainText('参数快照')
    await expect(detail).not.toContainText('删除候选')
    await expect(detail).not.toContainText('保存执行记录')

    await page.screenshot({
      path: testInfo.outputPath('candidate-pool-transient-live-projection.png'),
      fullPage: true,
    })
  })
})
