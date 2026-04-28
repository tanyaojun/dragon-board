import type { LeaderRecord, Tradeability, ChaseRisk } from './types'

function deriveChaseRisk(record: LeaderRecord): ChaseRisk {
  const oneWord = record.fatalNegatives.includes('ONE_WORD_ISOLATION')
  const lateLoss = record.fatalNegatives.includes('CLOSE_LOST_LEADERSHIP')
  const heatAhead =
    record.authority === 'HEAT_ONLY' ||
    record.fatalNegatives.includes('LATE_HEAT_CHASE') ||
    (record.hotness >= 85 && record.authority !== 'TRUE_LEADER' && record.authority !== 'THEME_COMMANDER')
  const crowdedHeight = record.continuousDays >= 4 && record.turnoverRate < 6

  if (
    oneWord ||
    lateLoss ||
    heatAhead ||
    record.authority === 'PSEUDO_LEADER'
  ) {
    return 'EXTREME'
  }

  if (
    record.authority === 'HEIGHT_ONLY' ||
    record.authority === 'CARRY_PROXY' ||
    crowdedHeight ||
    record.fatalNegatives.includes('NO_FOLLOWERS')
  ) {
    return 'HIGH'
  }

  if (record.authority === 'TRUE_LEADER' || record.authority === 'THEME_COMMANDER') {
    return record.boardHeight >= 4 ? 'MEDIUM' : 'LOW'
  }

  return 'HIGH'
}

function deriveTradeability(record: LeaderRecord, chaseRisk: ChaseRisk): Tradeability {
  const actionableAuthority =
    record.authority === 'TRUE_LEADER' || record.authority === 'THEME_COMMANDER'
  const oneWord = record.fatalNegatives.includes('ONE_WORD_ISOLATION')
  const closeWeak = record.fatalNegatives.includes('CLOSE_LOST_LEADERSHIP')

  if (
    actionableAuthority &&
    (chaseRisk === 'LOW' || chaseRisk === 'MEDIUM') &&
    !oneWord &&
    !closeWeak &&
    record.turnoverRate >= 4 &&
    record.turnoverRate <= 28
  ) {
    return 'ACTIONABLE'
  }

  if (
    actionableAuthority ||
    record.authority === 'CARRY_PROXY'
  ) {
    return 'WATCH_ONLY'
  }

  return 'DO_NOT_CHASE'
}

function buildPlaybook(record: LeaderRecord, tradeability: Tradeability): string[] {
  if (tradeability === 'ACTIONABLE') {
    return [
      '优先观察分歧后的承接确认，而不是一致性顶点直接追价',
      '若收盘失去战场前二或出现 D 门失守，次日自动降级观察',
      '把它当作战场主将样本，不把真龙结论等同无条件买入',
    ]
  }

  if (tradeability === 'WATCH_ONLY') {
    return [
      '继续观察战场争夺是否收敛到唯一主导者',
      '等待下一段或下一日确认，不在高热时段硬追',
      '重点看跟风扩散和收盘完整性是否继续改善',
    ]
  }

  const reason =
    record.authority === 'HEAT_ONLY'
      ? '很热，但不是龙'
      : record.authority === 'HEIGHT_ONLY'
        ? '有身位，但没有领导权'
        : '领导权闭环失败'

  return [
    `${reason}，默认只做复盘样本`,
    '若仅靠热度或一致性维持，追涨回撤风险通常更大',
    '优先等下一只真正通过四道门的主导者出现',
  ]
}

export class TradeabilityEngine {
  apply(leaders: LeaderRecord[]): LeaderRecord[] {
    return leaders.map((record) => {
      const chaseRisk = deriveChaseRisk(record)
      const tradeability = deriveTradeability(record, chaseRisk)

      return {
        ...record,
        chaseRisk,
        tradeability,
        playbook: buildPlaybook(record, tradeability),
      }
    })
  }
}

export const tradeabilityEngine = new TradeabilityEngine()
