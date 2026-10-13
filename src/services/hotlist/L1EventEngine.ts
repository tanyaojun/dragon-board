/**
 * L1 个股事件引擎：与 tools/YiDongJingLing/Events/L1EventEngine.cs 语义完全一致。
 * 覆盖事件：封涨停/涨停回封（含连板命名）/打开涨停/逼近涨停/封跌停/打开跌停/逼近跌停/
 * 即将打开涨跌停/封单增强变弱/涨跌档/成交额档/低开长阳/高开长阴/新股开板回封/
 * 翻红翻绿/日内新高新低/快速拉跳/量增加速/大买大卖挂盘/买卖压/价差异常。
 *
 * 竞价弱转强（OpeningWeakToStrong）不在本引擎重复实现：TS 线已有
 * OpeningRealtimeEventBridge + OpeningWeakToStrongDetector 独立产出 12001 事件，
 * 本引擎保持沉默以避免双份事件（与 C# 单引擎内嵌实现的行为等价）。
 */
import {
  buildL1EventRecord,
  type L1EventRecord,
  type L1EventTypeName,
} from './l1EventCatalog'
import { DEFAULT_L1_EVENT_RULES, type L1EventRules } from './l1EventRules'
import {
  ask1Price,
  ask1Volume,
  askVolume5,
  bid1Price,
  bid1Volume,
  bidVolume5,
  type L1QuoteSnapshot,
} from './L1QuoteSnapshot'

const SHARES_PER_LOT = 100

interface StockState {
  wasLimitUpSealed: boolean
  wasLimitDownSealed: boolean
  lastLimitUpSealAmount: number
  lastLimitDownSealAmount: number
  maxRiseTierTriggered: number
  maxDropTierTriggered: number
  maxAmountTierTriggered: number
  intradayHigh: number
  intradayLow: number
  openShapeTriggered: boolean
  newStockEventDate: string
  newStockOpened: boolean
  newStockResealAnnounced: boolean
  sealStateDate: string
  sealedToday: boolean
}

export class L1EventEngine {
  private readonly rules: L1EventRules
  private readonly states = new Map<string, StockState>()
  private limitUpStreaks: Map<string, number> = new Map()

  constructor(rules?: Partial<L1EventRules>) {
    this.rules = { ...DEFAULT_L1_EVENT_RULES, ...rules }
  }

  /** 注入截至上一交易日的连续涨停天数（0 = 昨日未涨停），盘前由涨停池加载器更新。 */
  setLimitUpStreaks(streaks: Map<string, number> | Record<string, number>) {
    this.limitUpStreaks = streaks instanceof Map
      ? streaks
      : new Map(Object.entries(streaks).map(([code, count]) => [code, Number(count) || 0]))
  }

  clear() {
    this.states.clear()
  }

  /** 逐股评估：history 为该股本日内早于当前帧的快照（时间升序），由桥接层维护。 */
  evaluate(
    quote: L1QuoteSnapshot,
    previous: L1QuoteSnapshot | null,
    history: readonly L1QuoteSnapshot[],
  ): L1EventRecord[] {
    const state = this.getState(quote.code)
    // 跨日复位：昨日收盘帧的封板状态不应让今日首帧误报"打开涨停板"
    const evalDate = localDate(quote.sourceTime)
    if (state.sealStateDate !== evalDate) {
      state.sealStateDate = evalDate
      state.sealedToday = false
      state.wasLimitUpSealed = false
      state.wasLimitDownSealed = false
    }

    const events: L1EventRecord[] = []
    const isNewStock = isNewStockWithoutLimit(quote.name)
    const limitPct = isNewStock ? 0 : resolveLimitPct(quote)
    const limitUpPrice = isNewStock ? 0 : roundPrice(quote.preClose * (1 + limitPct / 100))
    const limitDownPrice = isNewStock ? 0 : roundPrice(quote.preClose * (1 - limitPct / 100))
    const sealedUp = !isNewStock && isLimitUpSealed(quote, limitUpPrice)
    const sealedDown = !isNewStock && isLimitDownSealed(quote, limitDownPrice)

    if (isNewStock) {
      this.evaluateNewStock(events, quote, state)
    } else if (sealedUp && !state.wasLimitUpSealed) {
      const tradingDate = localDate(quote.sourceTime)
      if (state.sealStateDate !== tradingDate) {
        state.sealStateDate = tradingDate
        state.sealedToday = false
      }
      const streak = this.limitUpStreaks.get(quote.code) ?? 0
      const board = streak + 1
      const boardLabel = board >= 2 ? `${board}连板` : '首板'
      const sealText = formatMoney(sealAmount(quote, true))
      if (state.sealedToday) {
        add(events, quote, 'LimitUpResealed', '涨停回封', 'critical', `${boardLabel}，回封封单 ${sealText}`)
      } else {
        const typeName = board >= 2 ? `${board}连板` : '封涨停板'
        add(events, quote, 'LimitUpSealed', typeName, 'critical', `买一封单 ${sealText}`)
      }
      state.sealStateDate = tradingDate
      state.sealedToday = true
    }
    if (!isNewStock && !sealedUp && state.wasLimitUpSealed) {
      add(events, quote, 'LimitUpOpened', '打开涨停板', 'critical', '最新价低于涨停价或买一不再为涨停价')
    }
    if (!isNewStock && !sealedUp && quote.changePct >= limitPct - this.rules.nearLimitDistancePct && quote.changePct < limitPct) {
      add(events, quote, 'NearLimitUp', '逼近涨停', 'important', `距涨停约 ${fixed2(Math.max(0, limitPct - quote.changePct))}%`)
    }
    if (!isNewStock && sealedDown && !state.wasLimitDownSealed) {
      add(events, quote, 'LimitDownSealed', '封跌停板', 'critical', `卖一封单 ${formatMoney(sealAmount(quote, false))}`)
    }
    if (!isNewStock && !sealedDown && state.wasLimitDownSealed) {
      add(events, quote, 'LimitDownOpened', '打开跌停板', 'critical', '最新价高于跌停价或卖一不再为跌停价')
    }
    if (!isNewStock && !sealedDown && quote.changePct <= -limitPct + this.rules.nearLimitDistancePct && quote.changePct > -limitPct) {
      add(events, quote, 'NearLimitDown', '逼近跌停', 'important', `距跌停约 ${fixed2(Math.max(0, limitPct + quote.changePct))}%`)
    }

    this.evaluateUpcomingOpen(events, quote, history, state, sealedUp, sealedDown)
    this.evaluateSealOrder(events, quote, state, sealedUp, sealedDown)
    this.evaluateRiseTiers(events, quote, state)
    this.evaluateDropTiers(events, quote, state)
    this.evaluateAmountTiers(events, quote, state)
    this.evaluateOpenShape(events, quote, state)
    this.evaluateDirectionChanges(events, quote, previous)
    this.evaluateIntradayHighLow(events, quote, state)
    this.evaluateSpeed(events, quote, history)
    this.evaluateVolumeAcceleration(events, quote, history)
    this.evaluateLargeOrders(events, quote)
    this.evaluatePressure(events, quote)
    this.evaluateSpread(events, quote)

    this.updateStateFromQuote(state, quote, sealedUp, sealedDown)
    return events
  }

  private getState(code: string): StockState {
    let state = this.states.get(code)
    if (!state) {
      state = {
        wasLimitUpSealed: false,
        wasLimitDownSealed: false,
        lastLimitUpSealAmount: 0,
        lastLimitDownSealAmount: 0,
        maxRiseTierTriggered: 0,
        maxDropTierTriggered: 0,
        maxAmountTierTriggered: 0,
        intradayHigh: 0,
        intradayLow: 0,
        openShapeTriggered: false,
        newStockEventDate: '',
        newStockOpened: false,
        newStockResealAnnounced: false,
        sealStateDate: '',
        sealedToday: false,
      }
      this.states.set(code, state)
    }
    return state
  }

  private evaluateUpcomingOpen(
    events: L1EventRecord[],
    quote: L1QuoteSnapshot,
    history: readonly L1QuoteSnapshot[],
    state: StockState,
    sealedUp: boolean,
    sealedDown: boolean,
  ) {
    if (sealedUp && state.wasLimitUpSealed) {
      const current = sealAmount(quote, true)
      const recentHigh = recentMaxSealAmount(quote, history, true, this.rules.upcomingOpenWindowMs)
      if (isSealWeakening(current, bid1Volume(quote), state.lastLimitUpSealAmount, recentHigh, this.rules)) {
        add(events, quote, 'UpcomingLimitUpOpen', '即将打开涨停', 'important', `买一封单降至 ${formatMoney(current)}`)
      }
    }
    if (sealedDown && state.wasLimitDownSealed) {
      const current = sealAmount(quote, false)
      const recentHigh = recentMaxSealAmount(quote, history, false, this.rules.upcomingOpenWindowMs)
      if (isSealWeakening(current, ask1Volume(quote), state.lastLimitDownSealAmount, recentHigh, this.rules)) {
        add(events, quote, 'UpcomingLimitDownOpen', '即将打开跌停', 'important', `卖一封单降至 ${formatMoney(current)}`)
      }
    }
  }

  private evaluateSealOrder(
    events: L1EventRecord[],
    quote: L1QuoteSnapshot,
    state: StockState,
    sealedUp: boolean,
    sealedDown: boolean,
  ) {
    if (sealedUp && state.lastLimitUpSealAmount > 0) {
      const current = sealAmount(quote, true)
      if (current >= state.lastLimitUpSealAmount * this.rules.sealIncreaseRatio) {
        add(events, quote, 'SealOrderIncreased', '封单增强', 'important', `涨停封单增至 ${formatMoney(current)}`)
      } else if (current <= state.lastLimitUpSealAmount * this.rules.sealWeakRatio) {
        add(events, quote, 'SealOrderWeakened', '封单变弱', 'important', `涨停封单降至 ${formatMoney(current)}`)
      }
    }
    if (sealedDown && state.lastLimitDownSealAmount > 0) {
      const current = sealAmount(quote, false)
      if (current >= state.lastLimitDownSealAmount * this.rules.sealIncreaseRatio) {
        add(events, quote, 'SealOrderIncreased', '封单增强', 'important', `跌停封单增至 ${formatMoney(current)}`)
      } else if (current <= state.lastLimitDownSealAmount * this.rules.sealWeakRatio) {
        add(events, quote, 'SealOrderWeakened', '封单变弱', 'important', `跌停封单降至 ${formatMoney(current)}`)
      }
    }
  }

  private evaluateNewStock(events: L1EventRecord[], quote: L1QuoteSnapshot, state: StockState) {
    if (quote.preClose <= 0 || quote.high <= 0 || quote.lastPrice <= 0) return

    const tradingDate = localDate(quote.sourceTime)
    if (state.newStockEventDate !== tradingDate) {
      state.newStockEventDate = tradingDate
      state.newStockOpened = false
      state.newStockResealAnnounced = false
    }

    const surgePct = (quote.high - quote.preClose) / quote.preClose * 100
    if (surgePct < this.rules.newStockMinSurgePct) return

    const drawdownPct = (quote.high - quote.lastPrice) / quote.high * 100
    if (!state.newStockOpened) {
      if (drawdownPct >= this.rules.newStockOpenDropPct) {
        state.newStockOpened = true
        add(events, quote, 'NewStockOpened', '新股开板', 'critical',
          `冲高 ${formatNumber(surgePct)}% 后自高点回落 ${formatNumber(drawdownPct)}%`)
      }
      return
    }

    if (!state.newStockResealAnnounced && drawdownPct <= this.rules.newStockResealDrawdownPct) {
      state.newStockResealAnnounced = true
      add(events, quote, 'NewStockReseal', '新股开板回封', 'critical',
        `回升至高点 ${formatNumber(quote.high)} 附近，回撤收窄至 ${formatNumber(drawdownPct)}%`)
    }
  }

  private evaluateRiseTiers(events: L1EventRecord[], quote: L1QuoteSnapshot, state: StockState) {
    const tier = highestTriggeredTier(this.rules.riseTiers, quote.changePct, state.maxRiseTierTriggered)
    if (tier > 0) {
      state.maxRiseTierTriggered = tier
      add(events, quote, 'BigRiseTier', '大幅拉升', 'important', `涨幅突破 ${formatNumber(tier)}%`)
    }
  }

  private evaluateDropTiers(events: L1EventRecord[], quote: L1QuoteSnapshot, state: StockState) {
    const tier = highestTriggeredTier(this.rules.dropTiers, -quote.changePct, state.maxDropTierTriggered)
    if (tier > 0) {
      state.maxDropTierTriggered = tier
      add(events, quote, 'BigDropTier', '大幅跳水', 'important', `跌幅突破 ${formatNumber(tier)}%`)
    }
  }

  private evaluateAmountTiers(events: L1EventRecord[], quote: L1QuoteSnapshot, state: StockState) {
    const tier = highestTriggeredTier(this.rules.amountTiers, quote.amount, state.maxAmountTierTriggered)
    if (tier > 0) {
      state.maxAmountTierTriggered = tier
      add(events, quote, 'AmountTier', '成交额跨档', 'normal', `成交额突破 ${formatMoney(tier)}`)
    }
  }

  private evaluateOpenShape(events: L1EventRecord[], quote: L1QuoteSnapshot, state: StockState) {
    if (quote.open <= 0 || quote.preClose <= 0 || quote.lastPrice <= 0 || state.openShapeTriggered) return

    const openGapPct = (quote.open - quote.preClose) / quote.preClose * 100
    const bodyPct = (quote.lastPrice - quote.open) / quote.open * 100
    if (openGapPct <= -this.rules.openGapPct && bodyPct >= this.rules.longBodyPct) {
      state.openShapeTriggered = true
      add(events, quote, 'LowOpenLongYang', '低开长阳', 'important',
        `低开 ${fixed2(Math.abs(openGapPct))}%，开盘后拉升 ${fixed2(bodyPct)}%`)
    } else if (openGapPct >= this.rules.openGapPct && bodyPct <= -this.rules.longBodyPct) {
      state.openShapeTriggered = true
      add(events, quote, 'HighOpenLongYin', '高开长阴', 'important',
        `高开 ${fixed2(openGapPct)}%，开盘后回落 ${fixed2(Math.abs(bodyPct))}%`)
    }
  }

  private evaluateDirectionChanges(events: L1EventRecord[], quote: L1QuoteSnapshot, previous: L1QuoteSnapshot | null) {
    if (!previous) return
    if (previous.changePct <= 0 && quote.changePct > 0) {
      add(events, quote, 'TurnRed', '翻红', 'normal', '涨跌幅由绿转红')
    }
    if (previous.changePct >= 0 && quote.changePct < 0) {
      add(events, quote, 'TurnGreen', '翻绿', 'normal', '涨跌幅由红转绿')
    }
  }

  private evaluateIntradayHighLow(events: L1EventRecord[], quote: L1QuoteSnapshot, state: StockState) {
    if (state.intradayHigh > 0 && quote.lastPrice > state.intradayHigh) {
      add(events, quote, 'IntradayHigh', '创日内新高', 'normal', `刷新工具启动后高点 ${fixed2(quote.lastPrice)}`)
    }
    if (state.intradayLow > 0 && quote.lastPrice < state.intradayLow) {
      add(events, quote, 'IntradayLow', '创日内新低', 'normal', `刷新工具启动后低点 ${fixed2(quote.lastPrice)}`)
    }
  }

  private evaluateSpeed(events: L1EventRecord[], quote: L1QuoteSnapshot, history: readonly L1QuoteSnapshot[]) {
    const change30 = changeFromWindow(quote, history, 30_000, this.rules.speedBaselineToleranceMs)
    const change60 = changeFromWindow(quote, history, 60_000, this.rules.speedBaselineToleranceMs)
    const change300 = changeFromWindow(quote, history, 300_000, this.rules.speedBaselineToleranceMs)

    if (change30 >= this.rules.fastRise30SecPct || change60 >= this.rules.fastRise60SecPct || change300 >= this.rules.fastRise300SecPct) {
      add(events, quote, 'FastRise', '快速拉升', 'important',
        `30秒 ${fixed2(change30)}%，60秒 ${fixed2(change60)}%，5分钟 ${fixed2(change300)}%`)
    }
    if (change30 <= this.rules.fastDrop30SecPct || change60 <= this.rules.fastDrop60SecPct || change300 <= this.rules.fastDrop300SecPct) {
      add(events, quote, 'FastDrop', '快速跳水', 'important',
        `30秒 ${fixed2(change30)}%，60秒 ${fixed2(change60)}%，5分钟 ${fixed2(change300)}%`)
    }
  }

  private evaluateVolumeAcceleration(events: L1EventRecord[], quote: L1QuoteSnapshot, history: readonly L1QuoteSnapshot[]) {
    const recent = history.filter(item => quote.sourceTime - item.sourceTime <= 30_000)
    const prior = history.filter(item =>
      quote.sourceTime - item.sourceTime > 30_000 &&
      quote.sourceTime - item.sourceTime <= 60_000)
    if (recent.length < 2 || prior.length < 2) return

    const recentDelta = Math.max(0, recent[recent.length - 1].volume - recent[0].volume)
    const priorDelta = Math.max(0, prior[prior.length - 1].volume - prior[0].volume)
    if (priorDelta > 0 && recentDelta >= priorDelta * this.rules.volumeAccelerationRatio) {
      add(events, quote, 'VolumeAcceleration', '成交增量加速', 'normal',
        `近30秒成交增量约为前段 ${fixed1(recentDelta / priorDelta)} 倍`)
    }
  }

  private evaluateLargeOrders(events: L1EventRecord[], quote: L1QuoteSnapshot) {
    if (bid1Price(quote) > 0 && bid1Volume(quote) > 0) {
      const amount = bid1Price(quote) * bid1Volume(quote) * SHARES_PER_LOT
      if (amount >= this.rules.largeOrderAmount) {
        add(events, quote, 'LargeBidOrder', '出现大买挂盘', 'normal', `买一挂单 ${formatMoney(amount)}`)
      }
    }
    if (ask1Price(quote) > 0 && ask1Volume(quote) > 0) {
      const amount = ask1Price(quote) * ask1Volume(quote) * SHARES_PER_LOT
      if (amount >= this.rules.largeOrderAmount) {
        add(events, quote, 'LargeAskOrder', '出现大卖挂盘', 'normal', `卖一挂单 ${formatMoney(amount)}`)
      }
    }
  }

  private evaluatePressure(events: L1EventRecord[], quote: L1QuoteSnapshot) {
    const bidTotal = bidVolume5(quote)
    const askTotal = askVolume5(quote)
    if (bidTotal > 0 && askTotal > 0) {
      if (bidTotal >= askTotal * this.rules.pressureRatio) {
        add(events, quote, 'BidPressure', '盘口买压增强', 'normal', `五档买量/卖量 ${fixed1(bidTotal / askTotal)}`)
      }
      if (askTotal >= bidTotal * this.rules.pressureRatio) {
        add(events, quote, 'AskPressure', '盘口卖压增强', 'normal', `五档卖量/买量 ${fixed1(askTotal / bidTotal)}`)
      }
    }
  }

  private evaluateSpread(events: L1EventRecord[], quote: L1QuoteSnapshot) {
    if (bid1Price(quote) <= 0 || ask1Price(quote) <= 0 || quote.lastPrice <= 0) return
    const spreadPct = (ask1Price(quote) - bid1Price(quote)) / quote.lastPrice * 100
    if (spreadPct >= this.rules.spreadPct) {
      add(events, quote, 'SpreadWidened', '买卖价差异常', 'normal', `买卖一价差 ${fixed2(spreadPct)}%`)
    }
  }

  private updateStateFromQuote(state: StockState, quote: L1QuoteSnapshot, sealedUp: boolean, sealedDown: boolean) {
    state.wasLimitUpSealed = sealedUp
    state.wasLimitDownSealed = sealedDown
    const sealDate = localDate(quote.sourceTime)
    if (state.sealStateDate !== sealDate) {
      state.sealStateDate = sealDate
      state.sealedToday = false
    }
    if (sealedUp) {
      state.sealedToday = true
    }
    state.lastLimitUpSealAmount = sealedUp ? sealAmount(quote, true) : 0
    state.lastLimitDownSealAmount = sealedDown ? sealAmount(quote, false) : 0
    state.maxRiseTierTriggered = Math.max(state.maxRiseTierTriggered, highestTriggeredTier(this.rules.riseTiers, quote.changePct, 0))
    state.maxDropTierTriggered = Math.max(state.maxDropTierTriggered, highestTriggeredTier(this.rules.dropTiers, -quote.changePct, 0))
    state.maxAmountTierTriggered = Math.max(state.maxAmountTierTriggered, highestTriggeredTier(this.rules.amountTiers, quote.amount, 0))
    state.intradayHigh = Math.max(state.intradayHigh, quote.lastPrice)
    state.intradayLow = state.intradayLow === 0 ? quote.lastPrice : Math.min(state.intradayLow, quote.lastPrice)
    state.openShapeTriggered = state.openShapeTriggered || isOpenShapeTriggered(quote, this.rules)
  }
}

/** 新股（N=首日，C=第2-5日注册制）无涨跌幅限制：跳过全部涨跌停类事件，改报开板/回封。 */
function isNewStockWithoutLimit(name: string): boolean {
  if (!name) return false
  return name.startsWith('N') || name.startsWith('C')
}

function resolveLimitPct(quote: L1QuoteSnapshot): number {
  const code = quote.code
  if (quote.name.includes('ST')) return 5
  if (code.startsWith('30') || code.startsWith('68')) return 20
  if (code.startsWith('8') || code.startsWith('4')) return 30
  return 10
}

function isLimitUpSealed(quote: L1QuoteSnapshot, limitUpPrice: number): boolean {
  if (quote.preClose <= 0 || quote.lastPrice <= 0) return false
  return quote.lastPrice >= limitUpPrice - 0.01 &&
    bid1Price(quote) >= limitUpPrice - 0.01 &&
    bid1Volume(quote) > 0
}

function isLimitDownSealed(quote: L1QuoteSnapshot, limitDownPrice: number): boolean {
  if (quote.preClose <= 0 || quote.lastPrice <= 0) return false
  return quote.lastPrice <= limitDownPrice + 0.01 &&
    ask1Price(quote) <= limitDownPrice + 0.01 &&
    ask1Volume(quote) > 0
}

function sealAmount(quote: L1QuoteSnapshot, up: boolean): number {
  return up
    ? bid1Price(quote) * bid1Volume(quote) * SHARES_PER_LOT
    : ask1Price(quote) * ask1Volume(quote) * SHARES_PER_LOT
}

function recentMaxSealAmount(quote: L1QuoteSnapshot, history: readonly L1QuoteSnapshot[], up: boolean, windowMs: number): number {
  let max = 0
  for (const item of history) {
    if (item.sourceTime < quote.sourceTime && quote.sourceTime - item.sourceTime <= windowMs) {
      max = Math.max(max, sealAmount(item, up))
    }
  }
  return max
}

function isSealWeakening(
  currentAmount: number,
  currentVolume: number,
  lastAmount: number,
  recentHighAmount: number,
  rules: L1EventRules,
): boolean {
  if (currentAmount <= 0 || currentVolume <= 0) return false
  const baseline = Math.max(lastAmount, recentHighAmount)
  return (baseline > 0 && currentAmount <= baseline * rules.upcomingOpenSealWeakRatio) ||
    currentAmount <= rules.upcomingOpenMinSealAmount ||
    currentVolume <= rules.upcomingOpenMinSealVolume
}

function isOpenShapeTriggered(quote: L1QuoteSnapshot, rules: L1EventRules): boolean {
  if (quote.open <= 0 || quote.preClose <= 0 || quote.lastPrice <= 0) return false
  const openGapPct = (quote.open - quote.preClose) / quote.preClose * 100
  const bodyPct = (quote.lastPrice - quote.open) / quote.open * 100
  return (openGapPct <= -rules.openGapPct && bodyPct >= rules.longBodyPct) ||
    (openGapPct >= rules.openGapPct && bodyPct <= -rules.longBodyPct)
}

function changeFromWindow(quote: L1QuoteSnapshot, history: readonly L1QuoteSnapshot[], windowMs: number, toleranceMs: number): number {
  let baseline: L1QuoteSnapshot | null = null
  for (const item of history) {
    if (item.sourceTime <= quote.sourceTime - windowMs && item.lastPrice > 0) {
      baseline = item
    }
  }
  if (!baseline || baseline.lastPrice <= 0) return 0
  // 快照断档时基线已过期（超窗口+容忍度），按旧基线算涨速会把断档涨幅误报成瞬时暴涨/暴跌
  if (quote.sourceTime - baseline.sourceTime > windowMs + toleranceMs) return 0
  return (quote.lastPrice - baseline.lastPrice) / baseline.lastPrice * 100
}

function highestTriggeredTier(tiers: number[], value: number, current: number): number {
  let highest = 0
  for (const tier of tiers) {
    if (value >= tier && current < tier) highest = Math.max(highest, tier)
  }
  return highest
}

function add(
  events: L1EventRecord[],
  quote: L1QuoteSnapshot,
  type: L1EventTypeName,
  typeName: string,
  severity: 'critical' | 'important' | 'normal',
  reason: string,
) {
  events.push(buildL1EventRecord({
    type,
    typeName,
    code: quote.code,
    name: quote.name,
    price: quote.lastPrice,
    changePct: quote.changePct,
    volume: quote.volume,
    amount: quote.amount,
    timestamp: quote.sourceTime,
    severity,
    reason,
  }))
}

function roundPrice(value: number): number {
  return Math.round(value * 100) / 100
}

function localDate(timestamp: number): string {
  const date = new Date(timestamp)
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${date.getFullYear()}-${month}-${day}`
}

export function formatMoney(value: number): string {
  if (value >= 100_000_000) return `${formatNumber(value / 100_000_000)}亿`
  if (value >= 10_000) return `${formatNumber(value / 10_000)}万`
  return `${Math.round(value)}`
}

/** 对齐 C# ":0.00" 固定两位格式。 */
export function fixed2(value: number): string {
  return Number.isFinite(value) ? value.toFixed(2) : '0.00'
}

/** 对齐 C# ":0.0" 固定一位格式。 */
export function fixed1(value: number): string {
  return Number.isFinite(value) ? value.toFixed(1) : '0.0'
}

export function formatNumber(value: number): string {
  if (!Number.isFinite(value)) return '0'
  const text = value.toFixed(2).replace(/(\.\d*?)0+$/, '$1').replace(/\.$/, '')
  return text === '-0' ? '0' : text
}
