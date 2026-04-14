// src/services/dragon/BusinessValidator.ts

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
      const sectorZtCount = sectorStocks.filter(s => s.change > 9.5).length
      if (sectorZtCount > 0) {
        performanceScore += sectorZtCount * 5
      }
      
      return {
        code: y.code,
        name: y.name,
        level: y.level,
        status: todayStock.change > 9.5 ? '晋级' : 
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
  
  /**
   * 调整权重 - 基于验证结果
   */
  adjustWeights(report: ValidationReport): void {
    // 如果某类型龙头平均分低于60，降低权重
    Object.entries(report.byLevel).forEach(([level, score]) => {
      if (score < 60) {
        // 降低该类型权重
        algorithmManager.adjustFactorWeight(level, -0.05)
        console.log(`[DragonValidator] ⚖️ 降低${level}权重，表现分${score}`)
      } else if (score > 80) {
        // 提高该类型权重
        algorithmManager.adjustFactorWeight(level, +0.03)
        console.log(`[DragonValidator] ⚖️ 提高${level}权重，表现分${score}`)
      }
    })
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