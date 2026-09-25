// src/services/dragon/BusinessValidator.ts

import { StockUtils } from '../../utils/common'

/**
 * 业务验证器 - 次日验证龙头质量
 */
export class BusinessValidator {
  
  /**
   * 验证昨日龙头的表现
   */
  validateYesterdayLeaders(): ValidationReport {
    const yesterday = this.getYesterdayLeaders()
    const today = this.getTodayStocks()
    
    const results = yesterday.map(y => {
      const todayStock = today.find(s => s.code === y.code)
      if (!todayStock) {
        return {
          code: y.code,
          name: y.name,
          level: y.level,
          status: '消失',
          score: 0
        }
      }
      
      // 计算表现分
      let performanceScore = 0
      
      // 溢价率
      if (todayStock.change > 0) {
        performanceScore += todayStock.change * 2
      }
      
      // 晋级情况
      if (todayStock.continuousDays > y.continuousDays) {
        performanceScore += 30
      }
      
      // 板块效应
      const sectorStocks = today.filter(s => 
        s.themes?.some(t => y.themes?.includes(t))
      )
      const sectorZtCount = sectorStocks.filter(s => StockUtils.isLimitUp(s.change, s.code, s.name)).length
      if (sectorZtCount > 0) {
        performanceScore += sectorZtCount * 5
      }
      
      return {
        code: y.code,
        name: y.name,
        level: y.level,
        status: StockUtils.isLimitUp(todayStock.change, todayStock.code, todayStock.name) ? '晋级' :
                todayStock.change > 5 ? '高溢价' :
                todayStock.change > 0 ? '小涨' :
                todayStock.change > -5 ? '调整' : '大跌',
        score: performanceScore
      }
    })
    
    // 计算各类型龙头的平均分
    const byLevel: Record<string, number> = {}
    results.forEach(r => {
      if (!byLevel[r.level]) {
        byLevel[r.level] = { total: 0, count: 0 }
      }
      byLevel[r.level].total += r.score
      byLevel[r.level].count++
    })
    
    Object.keys(byLevel).forEach(level => {
      byLevel[level] = byLevel[level].total / byLevel[level].count
    })
    
    return {
      date: new Date().toLocaleDateString(),
      totalLeaders: results.length,
      avgScore: results.reduce((sum, r) => sum + r.score, 0) / results.length,
      byLevel,
      details: results
    }
  }
}

interface ValidationReport {
  date: string
  totalLeaders: number
  avgScore: number
  byLevel: Record<string, number>
  details: Array<{
    code: string
    name: string
    level: string
    status: string
    score: number
  }>
}