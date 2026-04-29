export interface MoneyFlowDiagnosticTick {
  amount?: number
  volume?: number
  side?: 'buy' | 'sell' | 'neutral' | string
}

export interface MoneyFlowDiagnosticStock {
  [key: string]: unknown
  code?: string | number
  name?: string
  price?: number
  latestPrice?: number
  lastPrice?: number
  close?: number
  change?: number
  compRank?: number
  rank?: number
  volumeRatio?: number
  turnover?: number
  turnoverRate?: number
  amount?: number
  zlje?: number
  zljzb?: number
  cddje?: number
  cddjzb?: number
  moneyFlowSource?: string
  moneyFlowEstimated?: boolean
  tdxBuyVolume?: number
  tdxSellVolume?: number
  tdxCurrentVolume?: number
  ticks?: MoneyFlowDiagnosticTick[]
  recentTicks?: MoneyFlowDiagnosticTick[]
}

export interface MoneyFlowDiagnosticRow {
  code: string
  name: string
  rank: number
  price: number
  change: number
  volumeRatio: number
  turnover: number
  turnoverRate: number
  zlje: number
  zljzb: number
  cddje: number
  cddjzb: number
  estimated: boolean
  moneyFlowSource: string
  tdxBuyVolume: number
  tdxSellVolume: number
  tdxActiveAmount: number
  tdxActiveNet: number
  tdxActiveAmountToTurnover: number
  tickSampleAmount: number
  tickMainNet: number
  tickSuperNet: number
  tickSampleToTurnover: number
  hasUsableTickSample: boolean
}

export interface MoneyFlowGroupSummary {
  label: string
  total: number
  estimatedCount: number
  estimatedShare: number
  zljePositiveCount: number
  zljeNegativeCount: number
  zljeNegativeShare: number
  zljzbNeg20Count: number
  zljzbNeg50Count: number
  severeNegativeCount: number
  severeNegativeShare: number
  cddjePositiveCount: number
  cddjeNegativeCount: number
  usableTickSampleCount: number
  usableTickSampleShare: number
  avgZljzb: number
  avgTdxActiveAmountToTurnover: number
  avgTickSampleToTurnover: number
}

export interface MoneyFlowDiagnosis {
  estimatedShare: number
  top100NegativeZljeShare: number
  top100SevereNegativeShare: number
  strongStockNegativeShare: number
  limitUpNegativeZljeShare: number | null
  usableTickSampleShare: number
  avgTdxActiveAmountToTurnover: number
  avgTickSampleToTurnover: number
  suspectBias: boolean
  suspectSevereBias: boolean
  suspectStrongStockContradiction: boolean
  suspectUnit: boolean
  suspectThinTickSample: boolean
  notes: string[]
}

export interface MoneyFlowDiagnostics {
  rows: MoneyFlowDiagnosticRow[]
  groups: {
    all: MoneyFlowGroupSummary
    sample: MoneyFlowGroupSummary
    top100: MoneyFlowGroupSummary
    strong: MoneyFlowGroupSummary
    limitUp: MoneyFlowGroupSummary
    weak: MoneyFlowGroupSummary
    highTurnoverRate: MoneyFlowGroupSummary
    highAmount: MoneyFlowGroupSummary
    highVolumeRatio: MoneyFlowGroupSummary
  }
  diagnosis: MoneyFlowDiagnosis
  sampleRows: MoneyFlowDiagnosticRow[]
  extremeNegativeRows: MoneyFlowDiagnosticRow[]
}

export interface BuildMoneyFlowDiagnosticsOptions {
  sampleCodes?: Array<string | number>
  topSize?: number
}

const SUPER_ORDER_AMOUNT_THRESHOLD = 1_000_000
const SUPER_ORDER_VOLUME_THRESHOLD = 500_000
const LARGE_ORDER_AMOUNT_THRESHOLD = 200_000
const LARGE_ORDER_VOLUME_THRESHOLD = 100_000
const MIN_MONEY_FLOW_SAMPLE_AMOUNT = 2_000_000

function toNumber(value: unknown): number {
  const number = Number(value)
  return Number.isFinite(number) ? number : 0
}

function pickNumber(...values: unknown[]): number {
  for (const value of values) {
    const number = toNumber(value)
    if (number !== 0) return number
  }
  return 0
}

function average(values: number[]): number {
  const validValues = values.filter(value => Number.isFinite(value))
  if (!validValues.length) return 0
  return validValues.reduce((sum, value) => sum + value, 0) / validValues.length
}

function share(count: number, total: number): number {
  return total > 0 ? count / total : 0
}

function isEstimatedMoneyFlow(stock: MoneyFlowDiagnosticStock): boolean {
  return stock.moneyFlowEstimated === true || stock.moneyFlowSource === 'tdx_estimate'
}

function classifyMoneyFlowOrder(amount: number, volume: number): 'super' | 'large' | 'other' {
  if (amount >= SUPER_ORDER_AMOUNT_THRESHOLD || volume >= SUPER_ORDER_VOLUME_THRESHOLD) return 'super'
  if (amount >= LARGE_ORDER_AMOUNT_THRESHOLD || volume >= LARGE_ORDER_VOLUME_THRESHOLD) return 'large'
  return 'other'
}

export function summarizeMoneyFlowTicks(ticks: MoneyFlowDiagnosticTick[] = []) {
  const summary = {
    activeAmount: 0,
    mainNet: 0,
    superNet: 0,
  }

  ticks.forEach((tick) => {
    if (tick.side !== 'buy' && tick.side !== 'sell') return

    const amount = toNumber(tick.amount)
    const volume = toNumber(tick.volume)
    if (amount <= 0 || volume <= 0) return

    summary.activeAmount += amount
    const direction = tick.side === 'buy' ? 1 : -1
    const bucket = classifyMoneyFlowOrder(amount, volume * 100)
    if (bucket === 'super') {
      summary.superNet += amount * direction
      summary.mainNet += amount * direction
    } else if (bucket === 'large') {
      summary.mainNet += amount * direction
    }
  })

  return summary
}

export function buildMoneyFlowDiagnosticRows(stocks: MoneyFlowDiagnosticStock[]): MoneyFlowDiagnosticRow[] {
  return stocks.map((stock) => {
    const price = pickNumber(stock.price, stock.latestPrice, stock.lastPrice, stock.close)
    const turnover = pickNumber(stock.turnover, stock.amount)
    const tdxBuyVolume = toNumber(stock.tdxBuyVolume)
    const tdxSellVolume = toNumber(stock.tdxSellVolume)
    const tdxActiveAmount = price > 0 ? (tdxBuyVolume + tdxSellVolume) * price * 100 : 0
    const tdxActiveNet = price > 0 ? (tdxBuyVolume - tdxSellVolume) * price * 100 : 0
    const tickSummary = summarizeMoneyFlowTicks(stock.recentTicks ?? stock.ticks ?? [])

    return {
      code: String(stock.code ?? ''),
      name: String(stock.name ?? ''),
      rank: pickNumber(stock.compRank, stock.rank),
      price,
      change: toNumber(stock.change),
      volumeRatio: toNumber(stock.volumeRatio),
      turnover,
      turnoverRate: toNumber(stock.turnoverRate),
      zlje: toNumber(stock.zlje),
      zljzb: toNumber(stock.zljzb),
      cddje: toNumber(stock.cddje),
      cddjzb: toNumber(stock.cddjzb),
      estimated: isEstimatedMoneyFlow(stock),
      moneyFlowSource: String(stock.moneyFlowSource ?? ''),
      tdxBuyVolume,
      tdxSellVolume,
      tdxActiveAmount,
      tdxActiveNet,
      tdxActiveAmountToTurnover: turnover > 0 ? tdxActiveAmount / turnover : 0,
      tickSampleAmount: tickSummary.activeAmount,
      tickMainNet: tickSummary.mainNet,
      tickSuperNet: tickSummary.superNet,
      tickSampleToTurnover: turnover > 0 ? tickSummary.activeAmount / turnover : 0,
      hasUsableTickSample: tickSummary.activeAmount >= MIN_MONEY_FLOW_SAMPLE_AMOUNT,
    }
  })
}

function isValidQuote(row: MoneyFlowDiagnosticRow): boolean {
  return row.price > 0 && row.turnover > 0
}

function isSevereNegative(row: MoneyFlowDiagnosticRow): boolean {
  return row.zlje < 0 && row.zljzb <= -30 && row.cddje < 0 && row.cddjzb <= -5
}

function summarizeGroup(label: string, rows: MoneyFlowDiagnosticRow[]): MoneyFlowGroupSummary {
  const total = rows.length
  const estimatedCount = rows.filter(row => row.estimated).length
  const zljePositiveCount = rows.filter(row => row.zlje > 0).length
  const zljeNegativeCount = rows.filter(row => row.zlje < 0).length
  const zljzbNeg20Count = rows.filter(row => row.zljzb <= -20).length
  const zljzbNeg50Count = rows.filter(row => row.zljzb <= -50).length
  const severeNegativeCount = rows.filter(isSevereNegative).length
  const cddjePositiveCount = rows.filter(row => row.cddje > 0).length
  const cddjeNegativeCount = rows.filter(row => row.cddje < 0).length
  const usableTickSampleCount = rows.filter(row => row.hasUsableTickSample).length

  return {
    label,
    total,
    estimatedCount,
    estimatedShare: share(estimatedCount, total),
    zljePositiveCount,
    zljeNegativeCount,
    zljeNegativeShare: share(zljeNegativeCount, total),
    zljzbNeg20Count,
    zljzbNeg50Count,
    severeNegativeCount,
    severeNegativeShare: share(severeNegativeCount, total),
    cddjePositiveCount,
    cddjeNegativeCount,
    usableTickSampleCount,
    usableTickSampleShare: share(usableTickSampleCount, total),
    avgZljzb: average(rows.map(row => row.zljzb)),
    avgTdxActiveAmountToTurnover: average(rows.map(row => row.tdxActiveAmountToTurnover)),
    avgTickSampleToTurnover: average(rows.map(row => row.tickSampleToTurnover)),
  }
}

function takeTopRows(rows: MoneyFlowDiagnosticRow[], topSize: number): MoneyFlowDiagnosticRow[] {
  const validRows = rows.filter(isValidQuote)
  const rankedRows = validRows.filter(row => row.rank > 0)
  const sourceRows = rankedRows.length ? rankedRows : validRows

  return [...sourceRows].sort((left, right) => {
    const leftRank = left.rank > 0 ? left.rank : Number.MAX_SAFE_INTEGER
    const rightRank = right.rank > 0 ? right.rank : Number.MAX_SAFE_INTEGER
    if (leftRank !== rightRank) return leftRank - rightRank
    return left.code.localeCompare(right.code)
  }).slice(0, topSize)
}

function buildDiagnosis(
  top100: MoneyFlowGroupSummary,
  strong: MoneyFlowGroupSummary,
  limitUp: MoneyFlowGroupSummary,
): MoneyFlowDiagnosis {
  const limitUpNegativeZljeShare = limitUp.total > 0 ? limitUp.zljeNegativeShare : null
  const suspectBias = top100.estimatedShare >= 0.7 && top100.zljeNegativeShare >= 0.75
  const suspectSevereBias = top100.estimatedShare >= 0.7 && top100.severeNegativeShare >= 0.35
  const suspectStrongStockContradiction = strong.total >= 5 && strong.zljeNegativeShare >= 0.7
  const suspectUnit = top100.avgTdxActiveAmountToTurnover >= 1.5
  const suspectThinTickSample = top100.estimatedShare >= 0.7 && top100.usableTickSampleShare < 0.3
  const notes: string[] = []

  if (suspectBias) notes.push('热榜前100估算资金整体偏负，优先检查 TDX 主买/主卖方向或样本覆盖。')
  if (suspectSevereBias) notes.push('热榜前100出现大面积严重负占比，优先排查估算模型系统性偏差。')
  if (suspectStrongStockContradiction) notes.push('强势股也大面积净流出，需要确认这是盘面真实分歧还是估算口径偏空。')
  if (suspectUnit) notes.push('TDX主动成交额明显超过成交额，优先检查 volume 是否重复乘100或成交额单位不一致。')
  if (suspectThinTickSample) notes.push('逐笔样本覆盖不足，当前资金估算更依赖 TDX 主买/主卖 fallback。')

  return {
    estimatedShare: top100.estimatedShare,
    top100NegativeZljeShare: top100.zljeNegativeShare,
    top100SevereNegativeShare: top100.severeNegativeShare,
    strongStockNegativeShare: strong.zljeNegativeShare,
    limitUpNegativeZljeShare,
    usableTickSampleShare: top100.usableTickSampleShare,
    avgTdxActiveAmountToTurnover: top100.avgTdxActiveAmountToTurnover,
    avgTickSampleToTurnover: top100.avgTickSampleToTurnover,
    suspectBias,
    suspectSevereBias,
    suspectStrongStockContradiction,
    suspectUnit,
    suspectThinTickSample,
    notes,
  }
}

export function buildMoneyFlowDiagnostics(
  stocks: MoneyFlowDiagnosticStock[],
  options: BuildMoneyFlowDiagnosticsOptions = {},
): MoneyFlowDiagnostics {
  const topSize = options.topSize ?? 100
  const sampleCodeSet = new Set((options.sampleCodes ?? []).map(code => String(code)))
  const rows = buildMoneyFlowDiagnosticRows(stocks)
  const validRows = rows.filter(isValidQuote)
  const top100Rows = takeTopRows(rows, topSize)
  const sampleRows = sampleCodeSet.size ? rows.filter(row => sampleCodeSet.has(row.code)) : []
  const strongRows = top100Rows.filter(row => row.change >= 7)
  const limitUpRows = top100Rows.filter(row => row.change >= 9.5)
  const weakRows = top100Rows.filter(row => row.change <= -5)
  const highTurnoverRateRows = top100Rows.filter(row => row.turnoverRate >= 10)
  const highAmountRows = top100Rows.filter(row => row.turnover >= 1_000_000_000)
  const highVolumeRatioRows = top100Rows.filter(row => row.volumeRatio >= 1.2)

  const groups = {
    all: summarizeGroup('全部有效标的', validRows),
    sample: summarizeGroup('样本标的', sampleRows),
    top100: summarizeGroup(`热榜前${topSize}`, top100Rows),
    strong: summarizeGroup(`前${topSize}且涨幅>=7%`, strongRows),
    limitUp: summarizeGroup(`前${topSize}且接近涨停>=9.5%`, limitUpRows),
    weak: summarizeGroup(`前${topSize}且跌幅<=-5%`, weakRows),
    highTurnoverRate: summarizeGroup(`前${topSize}且换手>=10%`, highTurnoverRateRows),
    highAmount: summarizeGroup(`前${topSize}且成交额>=10亿`, highAmountRows),
    highVolumeRatio: summarizeGroup(`前${topSize}且量比>=1.2`, highVolumeRatioRows),
  }

  return {
    rows,
    groups,
    diagnosis: buildDiagnosis(groups.top100, groups.strong, groups.limitUp),
    sampleRows,
    extremeNegativeRows: top100Rows
      .filter(isSevereNegative)
      .sort((left, right) => left.zljzb - right.zljzb)
      .slice(0, 20),
  }
}
