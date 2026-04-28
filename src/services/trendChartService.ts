// src/services/trendChartService.ts

import { ref } from 'vue'
import { useStockStore } from '@/stores/stock'
import { dragonAnalyzer } from './DragonAnalyzer'
import { sectorAnalyzer } from './sectorAnalyzer'
import { dragonBreathAnalyzer } from './DragonBreathAnalyzer'
import type { Stock } from '@/types'

interface ChartData {
  labels: string[]
  datasets: {
    name: string
    data: number[]
    color: string
    type?: 'line' | 'bar'
  }[]
}

interface ChartStats {
  totalLeaders: number
  totalLeadersCount: number
  sectorLeaders: number
  continuousLeaders: number
  avgHeatScore: number
  hotSectors: number
  ztCount: number
  emotionValue: number
}

class TrendChartService {
  private historyData = ref<Map<string, any[]>>(new Map())
  private readonly MAX_HISTORY = 90 // 90天

  constructor() {
    this.init()
  }

  private init() {
    // 生成模拟历史数据
    this.generateMockHistory()
  }

  // ========== 龙头趋势数据 ==========

  getLeaderTrendData(days: number = 30): ChartData {
    const labels: string[] = []
    const totalLeaders: number[] = []
    const totalLeadersCount: number[] = []
    const sectorLeaders: number[] = []
    const continuousLeaders: number[] = []

    // 生成日期标签
    for (let i = days; i >= 0; i--) {
      const date = new Date()
      date.setDate(date.getDate() - i)
      labels.push(`${date.getMonth() + 1}/${date.getDate()}`)
    }

    // 生成模拟数据
    for (let i = 0; i <= days; i++) {
      totalLeaders.push(Math.floor(30 + Math.random() * 20))
      totalLeadersCount.push(Math.floor(3 + Math.random() * 5))
      sectorLeaders.push(Math.floor(15 + Math.random() * 10))
      continuousLeaders.push(Math.floor(2 + Math.random() * 5))
    }

    return {
      labels,
      datasets: [
        {
          name: '总龙头',
          data: totalLeadersCount,
          color: '#FFD700',
          type: 'line',
        },
        {
          name: '板块龙头',
          data: sectorLeaders,
          color: '#3498db',
          type: 'line',
        },
        {
          name: '连板龙头',
          data: continuousLeaders,
          color: '#e74c3c',
          type: 'line',
        },
      ],
    }
  }

  // ========== 板块热度数据 ==========

  getSectorHeatData(): ChartData {
    const sectors = sectorAnalyzer.getHotThemes(10)

    return {
      labels: sectors.map((s) => s.name),
      datasets: [
        {
          name: '热度评分',
          data: sectors.map((s) => s.heatScore),
          color: '#ffa502',
          type: 'bar',
        },
        {
          name: '涨停数量',
          data: sectors.map((s) => s.ztCount),
          color: '#e74c3c',
          type: 'bar',
        },
      ],
    }
  }

  // ========== 资金流向数据 ==========

  getMoneyFlowData(): ChartData {
    const stockStore = useStockStore()
    const stocks = stockStore.stocks

    let inflow = 0,
      outflow = 0
    let inflowCount = 0,
      outflowCount = 0

    stocks.forEach((stock: Stock) => {
      const zlje = stock.zlje || 0
      if (zlje > 0) {
        inflow += zlje
        inflowCount++
      } else if (zlje < 0) {
        outflow += Math.abs(zlje)
        outflowCount++
      }
    })

    return {
      labels: ['主力流入', '主力流出', '净额'],
      datasets: [
        {
          name: '金额(亿)',
          data: [
            Math.round((inflow / 1e8) * 100) / 100,
            Math.round((outflow / 1e8) * 100) / 100,
            Math.round(((inflow - outflow) / 1e8) * 100) / 100,
          ],
          color: '#2ed573',
          type: 'bar',
        },
      ],
    }
  }

  // ========== 晋级率数据 ==========

  getUpgradeRateData(): ChartData {
    const marketData = dragonBreathAnalyzer.getMarketData()
    const { yiban, erban, sanban, sibanPlus } = marketData.limitData

    // 计算晋级率
    const erbanRate = yiban > 0 ? (erban / yiban) * 100 : 0
    const sanbanRate = erban > 0 ? (sanban / erban) * 100 : 0
    const sibanRate = sanban > 0 ? (sibanPlus / sanban) * 100 : 0
    const wubanRate = sibanPlus > 0 ? sibanPlus / 2 : 0

    return {
      labels: ['首板→二板', '二板→三板', '三板→四板', '四板以上'],
      datasets: [
        {
          name: '晋级率(%)',
          data: [
            Math.round(erbanRate),
            Math.round(sanbanRate),
            Math.round(sibanRate),
            Math.round(wubanRate),
          ],
          color: '#9b59b6',
          type: 'bar',
        },
      ],
    }
  }

  // ========== 统计信息 ==========

  getStats(): ChartStats {
    const stockStore = useStockStore()
    const dragonStats = dragonAnalyzer.getStats()
    const sectorStats = sectorAnalyzer.getStats()
    const hotThemes = sectorAnalyzer.getHotThemes(50)
    const avgHeatScore =
      hotThemes.length > 0
        ? hotThemes.reduce((sum, theme) => sum + (theme.heatScore || 0), 0) / hotThemes.length
        : 0
    const marketData = dragonBreathAnalyzer.getMarketData()

    return {
      totalLeaders: dragonStats.totalLeaders,
      totalLeadersCount: dragonStats.totalLeadersCount,
      sectorLeaders: dragonStats.sectorLeaders,
      continuousLeaders: dragonStats.continuousLeaders,
      avgHeatScore: Math.round(avgHeatScore),
      hotSectors: sectorStats.hotThemes,
      ztCount: marketData.ztCount,
      emotionValue: Math.round(marketData.emotionValue),
    }
  }

  // ========== 模拟历史数据 ==========

  private generateMockHistory() {
    const leaders: any[] = []
    const sectors: any[] = []
    const money: any[] = []

    for (let i = 0; i < this.MAX_HISTORY; i++) {
      const date = new Date()
      date.setDate(date.getDate() - (this.MAX_HISTORY - i))

      leaders.push({
        date: date.toISOString().split('T')[0],
        totalLeaders: Math.floor(30 + Math.random() * 20),
        totalLeadersCount: Math.floor(3 + Math.random() * 5),
        sectorLeaders: Math.floor(15 + Math.random() * 10),
        continuousLeaders: Math.floor(2 + Math.random() * 5),
      })

      sectors.push({
        date: date.toISOString().split('T')[0],
        heatScore: Math.floor(60 + Math.random() * 40),
        ztCount: Math.floor(5 + Math.random() * 15),
      })

      money.push({
        date: date.toISOString().split('T')[0],
        inflow: Math.floor(30 + Math.random() * 20),
        outflow: Math.floor(25 + Math.random() * 20),
      })
    }

    this.historyData.value.set('leaders', leaders)
    this.historyData.value.set('sectors', sectors)
    this.historyData.value.set('money', money)
  }

  getHistoryData(type: 'leaders' | 'sectors' | 'money', days: number = 30) {
    const data = this.historyData.value.get(type) || []
    return data.slice(-days)
  }
}

export const trendChartService = new TrendChartService()
