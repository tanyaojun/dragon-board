// src/config/factors.ts
// 所有因子定义和计算逻辑

import type { Factor, Stock } from '@/types'
import { dragonBreathAnalyzer } from '@/services/DragonBreathAnalyzer'
import { sectorAnalyzer } from '@/services/sectorAnalyzer'

export const FACTORS: Record<string, Factor> = {
  // ========== 基础因子 ==========
  compRank: {
    name: '综合排名',
    type: 'rank',
    category: 'market',
    description: '热榜综合排名，越靠前分数越高',
    calculate: (stock: Stock) => {
      const rank = stock.compRank || 999
      return Math.max(0, 100 - rank)
    },
  },

  change: {
    name: '涨幅',
    type: 'percent',
    category: 'technical',
    description: '当日涨跌幅',
    calculate: (stock: Stock) => {
      const ch = Math.abs(stock.change || 0)
      return Math.min(100, ch * 5)
    },
  },

  turnover: {
    name: '成交额',
    type: 'money',
    category: 'technical',
    description: '当日成交金额',
    calculate: (stock: Stock) => {
      const to = stock.turnover || 0
      return Math.min(100, Math.log10(to / 1e6) * 10)
    },
  },

  turnoverRate: {
    name: '换手率',
    type: 'percent',
    category: 'technical',
    description: '换手率反映活跃度',
    calculate: (stock: Stock) => {
      const tr = stock.turnoverRate || 0
      return Math.min(100, tr * 3)
    },
  },

  zlje: {
    name: '主力净额',
    type: 'money',
    category: 'money',
    description: '主力资金净流入/流出',
    calculate: (stock: Stock) => {
      const zl = Math.abs(stock.zlje || 0)
      return Math.min(100, Math.log10(zl / 1e6) * 10)
    },
  },

  zljzb: {
    name: '主力占比',
    type: 'percent',
    category: 'money',
    description: '主力资金占总成交比例',
    calculate: (stock: Stock) => {
      const zb = Math.abs(stock.zljzb || 0)
      return Math.min(100, zb * 5)
    },
  },

  marketCap: {
    name: '总市值',
    type: 'scale',
    category: 'fundamental',
    description: '总市值越大，龙头地位越强',
    calculate: (stock: Stock) => {
      const mc = stock.totalMV || 0
      return Math.min(100, Math.log10(mc / 1e8) * 10)
    },
  },

  continuousDays: {
    name: '连板天数',
    type: 'count',
    category: 'technical',
    description: '连续涨停天数',
    calculate: (stock: Stock) => {
      const days = stock.continuousDays || 1
      return Math.min(100, days * 10)
    },
  },

  // ========== 题材因子 ==========
  themeHeat: {
    name: '题材热度',
    type: 'theme',
    category: 'sector',
    description: '所属题材的热度分数',
    calculate: (stock: Stock) => {
      try {
        const factors = (sectorAnalyzer as any)?.getThemeFactors?.(stock.code) || {}
        return Math.min(100, (factors.themeHeat || 0) / 100)
      } catch {
        return 50
      }
    },
  },

  themeLeaderCount: {
    name: '题材龙头数',
    type: 'theme',
    category: 'sector',
    description: '所属题材内的龙头数量',
    calculate: (stock: Stock) => {
      try {
        const factors = (sectorAnalyzer as any)?.getThemeFactors?.(stock.code) || {}
        return Math.min(100, (factors.themeLeaderCount || 0) * 20)
      } catch {
        return 30
      }
    },
  },

  themeMomentum: {
    name: '题材动量',
    type: 'momentum',
    category: 'sector',
    description: '题材热度变化趋势',
    calculate: (stock: Stock) => {
      try {
        const factors = (sectorAnalyzer as any)?.getThemeFactors?.(stock.code) || {}
        return ((factors.themeMomentum || 0) + 100) / 2
      } catch {
        return 50
      }
    },
  },

  // ========== 龙息因子 ==========
  breathPhase: {
    name: '情绪阶段',
    type: 'breath',
    category: 'market',
    description: '当前市场情绪阶段',
    calculate: () => {
      try {
        const sentiment = dragonBreathAnalyzer?.getMarketSentiment?.()
        const phase = sentiment?.phase
        if (phase === '高潮') return 88
        if (phase === '发酵') return 66
        if (phase === '启动') return 45
        if (phase === '退潮') return 35
        if (phase === '冰点') return 20
        return 50
      } catch {
        return 50
      }
    },
  },

  breathZtCount: {
    name: '涨停数',
    type: 'breath',
    category: 'market',
    description: '当日涨停股票数量',
    calculate: () => {
      try {
        const marketData = dragonBreathAnalyzer?.getMarketData?.()
        return Math.min(100, (marketData?.ztCount || 30) * 2)
      } catch {
        return 50
      }
    },
  },

  breathDtCount: {
    name: '跌停数',
    type: 'breath',
    category: 'market',
    description: '当日跌停股票数量（反向指标）',
    calculate: () => {
      try {
        const marketData = dragonBreathAnalyzer?.getMarketData?.()
        return Math.max(0, 100 - (marketData?.dtCount || 10) * 5)
      } catch {
        return 50
      }
    },
  },

  breathZhabanRate: {
    name: '炸板率',
    type: 'breath',
    category: 'market',
    description: '炸板率越低越好',
    calculate: () => {
      try {
        const marketData = dragonBreathAnalyzer?.getMarketData?.()
        return 100 - (marketData?.zhaban?.rate || 30)
      } catch {
        return 70
      }
    },
  },

  breathFengbanRate: {
    name: '封板率',
    type: 'breath',
    category: 'market',
    description: '封板率越高越强',
    calculate: () => {
      try {
        const marketData = dragonBreathAnalyzer?.getMarketData?.()
        return marketData?.zhaban?.fengbanRate || 70
      } catch {
        return 70
      }
    },
  },

  breathPassRate: {
    name: '晋级率',
    type: 'breath',
    category: 'market',
    description: '昨日涨停今日继续涨停的比例',
    calculate: () => {
      try {
        const marketData = dragonBreathAnalyzer?.getMarketData?.()
        const { yesterdayLimit, limitData } = marketData || {}
        if (!yesterdayLimit || !limitData) return 50

        let totalPass = 0
        let totalBase = 0

        if (yesterdayLimit.yiban > 0) {
          totalPass += limitData.erban || 0
          totalBase += yesterdayLimit.yiban
        }
        if (yesterdayLimit.erban > 0) {
          totalPass += limitData.sanban || 0
          totalBase += yesterdayLimit.erban
        }
        if (yesterdayLimit.sanban > 0) {
          totalPass += limitData.sibanPlus || 0
          totalBase += yesterdayLimit.sanban
        }

        return totalBase > 0 ? (totalPass / totalBase) * 100 : 50
      } catch {
        return 50
      }
    },
  },

  breathMaxDays: {
    name: '最高连板',
    type: 'breath',
    category: 'market',
    description: '市场最高连板天数',
    calculate: () => {
      try {
        const leaders = (window as any).dragonAnalyzer?.getAllLeaders({ level: 'CONTINUOUS' }) || []
        const maxDays = Math.max(...leaders.map((l: any) => l.continuousDays), 0)
        return Math.min(100, maxDays * 10)
      } catch {
        return 50
      }
    },
  },

  breathUpDownRatio: {
    name: '涨跌比',
    type: 'breath',
    category: 'market',
    description: '上涨家数/下跌家数',
    calculate: () => {
      try {
        const marketData = dragonBreathAnalyzer?.getMarketData?.()
        const { upCount, downCount } = marketData || {}
        if (upCount > 0 || downCount > 0) {
          const total = (upCount || 0) + (downCount || 1)
          return ((upCount || 0) / total) * 100
        }
        return 50
      } catch {
        return 50
      }
    },
  },

  breathEmotionValue: {
    name: '情绪值',
    type: 'breath',
    category: 'market',
    description: '通达信情绪指标',
    calculate: () => {
      try {
        const marketData = dragonBreathAnalyzer?.getMarketData?.()
        const value = marketData?.emotionValue ?? 0
        return (value + 10) * 5
      } catch {
        return 50
      }
    },
  },

  breathMarketScore: {
    name: '市场阶段档位',
    type: 'breath',
    category: 'market',
    description: '当前市场情绪阶段对应的结构档位',
    calculate: () => {
      try {
        const sentiment = dragonBreathAnalyzer?.getMarketSentiment?.()
        const phase = sentiment?.phaseName || sentiment?.phase
        if (phase === '高潮') return 88
        if (phase === '发酵') return 66
        if (phase === '启动') return 45
        if (phase === '退潮') return 35
        if (phase === '冰点') return 20
        return 50
      } catch {
        return 50
      }
    },
  },

  // ========== 逆势因子 ==========
  contrarian: {
    name: '逆势因子',
    type: 'sentiment',
    category: 'technical',
    description: '冰点期逆势上涨的股票，反映个股独立性',
    calculate: (stock: Stock) => {
      try {
        const sentiment = dragonBreathAnalyzer?.getMarketSentiment?.()
        if (!sentiment) return 50

        if (sentiment.phase === '冰点期') {
          if (stock.change > 0) {
            return Math.min(100, 50 + stock.change * 5)
          }
          if (stock.change > -3) {
            return Math.max(0, 30 + stock.change * 5)
          }
          return 20
        }

        if (sentiment.phase === '退潮期' && stock.change > 0) {
          return 40
        }

        return 30
      } catch {
        return 50
      }
    },
  },
}
