// src/types/sector.ts

// ========== 题材基础数据类型 ==========
export interface ThemeBase {
  id: string
  name: string
  zsCode?: string
}

export interface ThemeMapping {
  id: string
  name: string
  stocks: string[]
  zsCode?: string
  stockTags?: Record<string, Array<{ Name: string; Reason?: string }>>
  stockReasons?: Record<string, string>
}

export interface ThemeMappingData {
  version: string
  lastUpdate: string
  totalThemes: number
  themes: ThemeMapping[]
}

// ========== 题材热度数据类型 ==========
export interface ThemeHeatResult {
  themeId: string
  themeName: string
  heatScore: number
  heatLevel: string
  heatIcon: string
  heatColor: string
  correlation: number
  stats: {
    stockCount: number
    ztCount: number
    leaderCount: number
  }
  components: {
    baseScore: number
    ztScore: number
    moneyScore: number
    correlationBonus: number
  }
}

// ========== 题材指标类型 ==========
export interface ThemeMetrics {
  themeId: string
  themeName: string
  heatScore: number
  heatLevel: string
  heatIcon: string
  heatColor: string
  momentum: number
  trend: number
  acceleration: number
  correlation: number
  relatedThemes: Array<{ id: string; name: string; correlation: number }>
  stats: {
    stockCount: number
    ztCount: number
    leaderCount: number
  }
  lastUpdate: number
}

// ========== 热门题材类型 ==========
export interface HotTheme {
  id: string
  name: string
  rank: number
  heatScore: number
  heatIcon: string
  heatColor: string
  heatLevel: string
  stockCount: number
  ztCount: number
  leaderCount: number
  momentum: number
  trend: number
  acceleration: number
  correlation: number
  strength: number
  lastUpdate: number
}

// ========== 题材股票类型 ==========
export interface ThemeStock {
  code: string
  name: string
  price: number
  change: number
  turnover: number
  turnoverRate: number
  continuousDays: number
  isZT: boolean
  lianbanStr: string
  firstZtTime?: string
  lastZtTime?: string
  fengdan: number
  maxFengdan: number
  isSectorLeader: boolean
  leaderLevel?: string
  tags?: any[]
  reason?: string
  speed: number
  volumeRatio: number
  mainNetInflow: number
  leadTimes: number
  leadStatus: string
  bigMoney300: number
  popularity: number
  popularityChange: number
  institutionBuy: number
  mainBuy: number
  mainSell: number
  cirMV: number
}

// ========== 题材详情返回类型 ==========
export interface ThemeDetail {
  id: string
  name: string
  zsCode: string
  aliases: string[]
  heatScore: number
  heatLevel: string
  heatIcon: string
  heatColor: string
  momentum: number
  trend: number
  acceleration: number
  correlation: number
  relatedThemes: Array<{ id: string; name: string; correlation: number }>
  stats: {
    stockCount: number
    ztCount: number
    leaderCount: number
  }
  stocks: ThemeStock[]
  history: any[]
  lastUpdate: number | null
  leaders: Array<{
    code: string
    name: string
    level: string
    change: number
    continuousDays: number
    score: number
  }>
}
