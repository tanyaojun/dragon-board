// src/data/factors.ts

import type { Factor, Stock } from '@/types'

/**
 * 所有因子定义
 */
export const FACTORS: Record<string, Factor> = {
  compRank: {
    id: 'compRank',
    name: '综合排名',
    type: 'rank',
    category: 'market',
    description: '热榜综合排名，越靠前分数越高',
    calculate: (stock: Stock) => {
      const rank = stock.compRank || 999
      return Math.max(0, 100 - rank)
    },
    range: [0, 100],
    unit: '名',
    invert: true,
    example: '排名第1得99分，排名第100得0分',
  },
  avgRank: {
    id: 'avgRank',
    name: '均榜排名',
    type: 'rank',
    category: 'market',
    description: '多平台加权平均榜位',
    calculate: (stock: Stock) => {
      const rank = Number(stock.avgRank) || 100
      return Math.max(0, 100 - rank)
    },
    range: [0, 100],
    unit: '名',
    invert: true,
    example: '均榜排名第1得99分，排名第100得0分',
  },
  marketCap: {
    id: 'marketCap',
    name: '总市值',
    type: 'scale',
    category: 'fundamental',
    description: '总市值越大，龙头地位越强',
    calculate: (stock: Stock) => {
      const mc = stock.totalMV || 0
      return Math.min(100, Math.log10(mc / 1e8) * 10)
    },
    range: [0, 100],
    unit: '亿',
    example: '市值1000亿得30分，1万亿得40分',
  },
  cirMV: {
    id: 'cirMV',
    name: '流通市值',
    type: 'scale',
    category: 'fundamental',
    description: '流通市值反映市场认可度',
    calculate: (stock: Stock) => {
      const cm = stock.cirMV || 0
      return Math.min(100, Math.log10(cm / 1e8) * 10)
    },
    range: [0, 100],
    unit: '亿',
    example: '流通市值500亿得27分，5000亿得37分',
  },
  zlje: {
    id: 'zlje',
    name: '主力净额',
    type: 'money',
    category: 'money',
    description: '主力资金净流入/流出',
    calculate: (stock: Stock) => {
      const zl = Math.abs(stock.zlje || 0)
      return Math.min(100, Math.log10(zl / 1e6) * 10)
    },
    range: [0, 100],
    unit: '万',
    example: '主力净额1亿得20分，10亿得30分',
  },
  zljzb: {
    id: 'zljzb',
    name: '主力占比',
    type: 'percent',
    category: 'money',
    description: '主力资金占总成交比例',
    calculate: (stock: Stock) => {
      const zb = Math.abs(stock.zljzb || 0)
      return Math.min(100, zb * 5)
    },
    range: [0, 100],
    unit: '%',
    example: '主力占比10%得50分，20%得100分',
  },
  cddje: {
    id: 'cddje',
    name: '超大单净额',
    type: 'money',
    category: 'money',
    description: '超大单资金流向',
    calculate: (stock: Stock) => {
      const cd = Math.abs(stock.cddje || 0)
      return Math.min(100, Math.log10(cd / 1e6) * 10)
    },
    range: [0, 100],
    unit: '万',
    example: '超大单净额5000万得17分，5亿得27分',
  },
  cddjzb: {
    id: 'cddjzb',
    name: '超大单占比',
    type: 'percent',
    category: 'money',
    description: '超大单资金占比',
    calculate: (stock: Stock) => {
      const cb = Math.abs(stock.cddjzb || 0)
      return Math.min(100, cb * 5)
    },
    range: [0, 100],
    unit: '%',
    example: '超大单占比8%得40分，15%得75分',
  },
  change: {
    id: 'change',
    name: '涨幅',
    type: 'percent',
    category: 'technical',
    description: '当日涨跌幅',
    calculate: (stock: Stock) => {
      const ch = Math.abs(stock.change || 0)
      return Math.min(100, ch * 5)
    },
    range: [0, 100],
    unit: '%',
    example: '涨幅5%得25分，涨停10%得50分',
  },
  turnover: {
    id: 'turnover',
    name: '成交额',
    type: 'money',
    category: 'technical',
    description: '当日成交金额',
    calculate: (stock: Stock) => {
      const to = stock.turnover || 0
      return Math.min(100, Math.log10(to / 1e6) * 10)
    },
    range: [0, 100],
    unit: '万',
    example: '成交额1亿得20分，10亿得30分',
  },
  turnoverRate: {
    id: 'turnoverRate',
    name: '换手率',
    type: 'percent',
    category: 'technical',
    description: '换手率反映活跃度',
    calculate: (stock: Stock) => {
      const tr = stock.turnoverRate || 0
      return Math.min(100, tr * 3)
    },
    range: [0, 100],
    unit: '%',
    example: '换手率10%得30分，20%得60分',
  },
  sectorEffect: {
    id: 'sectorEffect',
    name: '板块效应',
    type: 'count',
    category: 'sector',
    description: '所属板块整体强度',
    calculate: (stock: Stock) => {
      if (stock.themes && stock.themes.length > 0) {
        const count = stock.themes.length
        if (count >= 5) return 98
        if (count === 4) return 92
        if (count === 3) return 85
        if (count === 2) return 75
        return 60
      }
      return 50
    },
    range: [0, 100],
    unit: '分',
    example: '5个以上题材得98分，3个题材得85分',
  },
  sectorLeaderCount: {
    id: 'sectorLeaderCount',
    name: '板块龙头数',
    type: 'count',
    category: 'sector',
    description: '板块内龙头股数量',
    calculate: (stock: Stock) => {
      if (stock.isSectorLeader) return 80
      if (stock.themes && stock.themes.length > 0) {
        return Math.min(60, 30 + stock.themes.length * 10)
      }
      return 30
    },
    range: [0, 100],
    unit: '个',
    example: '本身是龙头得80分，有2个题材得50分',
  },
  marketSentiment: {
    id: 'marketSentiment',
    name: '市场情绪',
    type: 'sentiment',
    category: 'macro',
    description: '当前市场情绪阶段的结构档位',
    calculate: (stock: Stock) => {
      if (typeof window !== 'undefined' && (window as any).DragonBreathAnalyzer) {
        const sentiment = (window as any).DragonBreathAnalyzer.getMarketSentiment?.()
        const phase = sentiment?.phaseName || sentiment?.phase
        if (phase === '高潮') return 88
        if (phase === '发酵') return 66
        if (phase === '启动') return 45
        if (phase === '退潮') return 35
        if (phase === '冰点') return 20
      }
      return 50
    },
    range: [0, 100],
    unit: '档',
    example: '高潮=88档，冰点=20档',
  },
  upDownRatio: {
    id: 'upDownRatio',
    name: '涨跌比',
    type: 'sentiment',
    category: 'macro',
    description: '上涨家数/下跌家数比例',
    calculate: (stock: Stock) => {
      if (typeof window !== 'undefined' && (window as any).DragonBreathAnalyzer) {
        const marketData = (window as any).DragonBreathAnalyzer.getMarketData?.()
        if (marketData && marketData.upCount !== undefined && marketData.downCount !== undefined) {
          const total = marketData.upCount + marketData.downCount
          if (total > 0) {
            const ratio = marketData.upCount / total
            return ratio * 100
          }
        }
      }
      return 50
    },
    range: [0, 100],
    unit: '分',
    example: '上涨家数70%得70分，30%得30分',
  },
  ztCount: {
    id: 'ztCount',
    name: '涨停数量',
    type: 'count',
    category: 'macro',
    description: '市场涨停家数',
    calculate: (stock: Stock) => {
      if (typeof window !== 'undefined' && (window as any).DragonBreathAnalyzer) {
        const marketData = (window as any).DragonBreathAnalyzer.getMarketData?.()
        if (marketData && marketData.ztCount !== undefined) {
          return Math.min(100, marketData.ztCount * 2)
        }
      }
      return 50
    },
    range: [0, 100],
    unit: '个',
    example: '30家涨停得60分，50家涨停得100分',
  },
  dtCount: {
    id: 'dtCount',
    name: '跌停数量',
    type: 'count',
    category: 'macro',
    description: '市场跌停家数（反向指标）',
    calculate: (stock: Stock) => {
      if (typeof window !== 'undefined' && (window as any).DragonBreathAnalyzer) {
        const marketData = (window as any).DragonBreathAnalyzer.getMarketData?.()
        if (marketData && marketData.dtCount !== undefined) {
          return Math.max(0, 100 - marketData.dtCount * 5)
        }
      }
      return 50
    },
    range: [0, 100],
    unit: '个',
    example: '5家跌停得75分，20家跌停得0分',
  },
  limitSpace: {
    id: 'limitSpace',
    name: '连板高度',
    type: 'count',
    category: 'macro',
    description: '市场最高连板数',
    calculate: (stock: Stock) => {
      if (typeof window !== 'undefined' && (window as any).DragonBreathAnalyzer) {
        const marketData = (window as any).DragonBreathAnalyzer.getMarketData?.()
        if (marketData && marketData.limitData) {
          const maxBan =
            (marketData.limitData.sibanPlus || 0) * 4 +
            (marketData.limitData.sanban || 0) * 3 +
            (marketData.limitData.erban || 0) * 2 +
            (marketData.limitData.yiban || 0)
          return Math.min(100, maxBan * 10)
        }
      }
      return 50
    },
    range: [0, 100],
    unit: '板',
    example: '7板空间得70分，10板空间得100分',
  },
  zhabanRate: {
    id: 'zhabanRate',
    name: '炸板率',
    type: 'percent',
    category: 'macro',
    description: '炸板率（反向指标）',
    calculate: (stock: Stock) => {
      if (typeof window !== 'undefined' && (window as any).DragonBreathAnalyzer) {
        const marketData = (window as any).DragonBreathAnalyzer.getMarketData?.()
        if (marketData && marketData.zhaban && marketData.zhaban.rate !== undefined) {
          return Math.max(0, 100 - marketData.zhaban.rate)
        }
      }
      return 50
    },
    range: [0, 100],
    unit: '%',
    example: '炸板率20%得80分，50%得50分',
  },
  moneyFlowSentiment: {
    id: 'moneyFlowSentiment',
    name: '资金情绪',
    type: 'sentiment',
    category: 'macro',
    description: '主力资金流向情绪',
    calculate: (stock: Stock) => {
      if (typeof window !== 'undefined' && (window as any).DragonBreathAnalyzer) {
        const marketData = (window as any).DragonBreathAnalyzer.getMarketData?.()
        if (marketData && marketData.moneyFlow && marketData.moneyFlow.main !== undefined) {
          const mainFlow = marketData.moneyFlow.main / 100000000
          if (mainFlow > 10) return 90
          if (mainFlow > 5) return 80
          if (mainFlow > 1) return 70
          if (mainFlow > 0) return 60
          if (mainFlow > -5) return 40
          return 20
        }
      }
      return 50
    },
    range: [0, 100],
    unit: '分',
    example: '主力净流入10亿得90分，流出10亿得20分',
  },
  emotionValue: {
    id: 'emotionValue',
    name: '情绪值',
    type: 'sentiment',
    category: 'macro',
    description: '通达信短线情绪值',
    calculate: (stock: Stock) => {
      if (typeof window !== 'undefined' && (window as any).DragonBreathAnalyzer) {
        const marketData = (window as any).DragonBreathAnalyzer.getMarketData?.()
        if (marketData && marketData.emotionValue !== undefined) {
          const base = marketData.emotionValue
          if (base >= 2) return 90
          if (base >= 1) return 80
          if (base >= 0) return 70
          if (base >= -1) return 50
          if (base >= -2) return 30
          if (base >= -3) return 20
          return 10
        }
      }
      return 50
    },
    range: [0, 100],
    unit: '分',
    example: '情绪值2以上得90分，-2得30分',
  },
  tradingAdvice: {
    id: 'tradingAdvice',
    name: '交易建议',
    type: 'sentiment',
    category: 'macro',
    description: '是否适合交易',
    calculate: (stock: Stock) => {
      if (typeof window !== 'undefined' && (window as any).DragonBreathAnalyzer) {
        const tradable = (window as any).DragonBreathAnalyzer.isTradable?.()
        return tradable ? 80 : 30
      }
      return 50
    },
    range: [0, 100],
    unit: '分',
    example: '适合交易得80分，不适合得30分',
  },
  marketPhase: {
    id: 'marketPhase',
    name: '市场阶段',
    type: 'sentiment',
    category: 'macro',
    description: '市场所处阶段',
    calculate: (stock: Stock) => {
      if (typeof window !== 'undefined' && (window as any).DragonBreathAnalyzer) {
        const sentiment = (window as any).DragonBreathAnalyzer.getMarketSentiment?.()
        if (sentiment && sentiment.phase) {
          const phase = sentiment.phase
          if (phase === '高潮') return 90
          if (phase === '发酵') return 75
          if (phase === '启动') return 60
          if (phase === '退潮') return 25
          if (phase === '冰点') return 10
        }
      }
      return 50
    },
    range: [0, 100],
    unit: '分',
    example: '高潮期90分，冰点期10分',
  },
  themeHeat: {
    id: 'themeHeat',
    name: '题材热度',
    type: 'sentiment',
    category: 'sector',
    description: '所属题材的热度分数',
    calculate: (stock: Stock) => {
      if (typeof window !== 'undefined' && (window as any).SectorAnalyzer) {
        const factors = (window as any).SectorAnalyzer.getThemeFactors?.(stock.code) || {}
        return Math.min(100, (factors.themeHeat || 0) / 100)
      }
      return 50
    },
    range: [0, 100],
    unit: '分',
    example: '题材热度5000得50分，10000得100分',
  },
  themeLeaderCount: {
    id: 'themeLeaderCount',
    name: '题材龙头数',
    type: 'count',
    category: 'sector',
    description: '所属题材内的龙头数量',
    calculate: (stock: Stock) => {
      if (typeof window !== 'undefined' && (window as any).SectorAnalyzer) {
        const factors = (window as any).SectorAnalyzer.getThemeFactors?.(stock.code) || {}
        return Math.min(100, (factors.themeLeaderCount || 0) * 20)
      }
      return 30
    },
    range: [0, 100],
    unit: '个',
    example: '题材内有3个龙头得60分，5个龙头得100分',
  },
  themeMomentum: {
    id: 'themeMomentum',
    name: '题材动量',
    type: 'momentum',
    category: 'sector',
    description: '题材热度变化趋势',
    calculate: (stock: Stock) => {
      if (typeof window !== 'undefined' && (window as any).SectorAnalyzer) {
        const factors = (window as any).SectorAnalyzer.getThemeFactors?.(stock.code) || {}
        return ((factors.themeMomentum || 0) + 100) / 2
      }
      return 50
    },
    range: [0, 100],
    unit: '分',
    example: '动量+80得90分，动量-50得25分',
  },
  themePosition: {
    id: 'themePosition',
    name: '题材轮动',
    type: 'position',
    category: 'sector',
    description: '题材在轮动中的位置',
    calculate: (stock: Stock) => {
      if (typeof window !== 'undefined' && (window as any).SectorAnalyzer) {
        const factors = (window as any).SectorAnalyzer.getThemeFactors?.(stock.code) || {}
        return factors.themePosition || 50
      }
      return 50
    },
    range: [0, 100],
    unit: '分',
    example: '轮动前排得80分，后排得20分',
  },

  // ===== 新增：逆势因子 =====
  contrarian: {
    id: 'contrarian',
    name: '逆势因子',
    type: 'sentiment',
    category: 'technical',
    description: '冰点期逆势上涨的股票，反映个股独立性',
    calculate: (stock: Stock) => {
      try {
        const sentiment = (window as any).dragonBreathAnalyzer?.getMarketSentiment()
        if (!sentiment) return 50

        // 只有在冰点期才有效
        if (sentiment.phase === '冰点期') {
          // 涨幅为正的股票加分
          if (stock.change > 0) {
            return Math.min(100, 50 + stock.change * 5)
          }
          // 跌幅小的股票也适当加分
          if (stock.change > -3) {
            return Math.max(0, 30 + stock.change * 5)
          }
          return 20
        }

        // 其他阶段，逆势因子权重降低
        if (sentiment.phase === '退潮期' && stock.change > 0) {
          return 40
        }

        return 30
      } catch (e) {
        return 50
      }
    },
    range: [0, 100],
    unit: '分',
    example: '冰点期涨停得100分，下跌5%得5分',
  },
}

/**
 * 题材因子ID映射（与 types/factors.ts 保持一致）
 */
export const THEME_FACTOR_IDS = {
  HEAT: 'themeHeat',
  LEADER_COUNT: 'themeLeaderCount',
  MOMENTUM: 'themeMomentum',
  POSITION: 'themePosition',
} as const
