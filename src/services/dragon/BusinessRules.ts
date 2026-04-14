// src/services/dragon/BusinessRules.ts

/**
 * 龙头业务规则 - 市场共识的龙头判断标准
 */
export class DragonBusinessRules {
  
  /**
   * 总龙头规则 - 市场核心
   */
  static isTotalLeader(stock: StockContext, market: MarketContext, sector: SectorContext): boolean {
    // 业务规则1：必须是市场最热题材的核心
    if (sector.sectorHeat < 5000) return false
    
    // 业务规则2：必须有板块效应（至少3只跟风）
    if (sector.sectorZtCount < 3) return false
    
    // 业务规则3：必须是该板块的领涨股（最先涨停或封单最大）
    const isLeader = stock.code === sector.firstLimitCode || 
                     stock.code === sector.maxFengdanCode
    if (!isLeader) return false
    
    // 业务规则4：成交额必须在前10（大资金认可）
    if (stock.turnoverRank > 10) return false
    
    // 业务规则5：市场情绪配合（不在退潮期）
    if (market.marketPhase === '退潮期') return false
    
    // 加分项：连板高度
    const heightBonus = stock.limitDays >= 5 ? 1.2 : 1
    
    // 计算综合得分
    const score = this.calculateTotalLeaderScore(stock, market, sector) * heightBonus
    
    return score >= 80
  }
  
  /**
   * 连板龙头规则 - 空间板
   */
  static isContinuousLeader(stock: StockContext, market: MarketContext, sector: SectorContext): boolean {
    // 业务规则1：必须有实体连板（不是一字板）
    if (stock.limitType === '一字' && stock.limitDays > 1) return false
    
    // 业务规则2：必须有板块跟风（至少2只）
    if (sector.sectorZtCount < 2) return false
    
    // 业务规则3：换手健康（5%-30%）
    if (stock.turnoverRate < 5 || stock.turnoverRate > 30) return false
    
    // 业务规则4：不能是纯情绪博弈（要有题材支撑）
    if (sector.sectorHeat < 2000) return false
    
    // 连板高度决定级别
    if (stock.limitDays >= 4) return true  // 四板以上自动晋级
    if (stock.limitDays >= 2 && sector.sectorHeat > 3000) return true
    
    return false
  }
  
  /**
   * 板块龙头规则 - 题材核心
   */
  static isSectorLeader(stock: StockContext, sector: SectorContext): boolean {
    // 业务规则1：必须是题材热度前3
    if (sector.sectorHeat < 3000) return false
    
    // 业务规则2：必须是该题材的领涨股
    const isFirstLimit = stock.code === sector.firstLimitCode
    const isMaxFengdan = stock.code === sector.maxFengdanCode
    
    if (!isFirstLimit && !isMaxFengdan) return false
    
    // 业务规则3：必须带动题材热度上升
    if (sector.ztIncrease <= 0 && stock.limitDays < 2) return false
    
    // 业务规则4：必须有跟风（至少1只）
    if (sector.followerCodes.length < 1 && stock.limitDays < 3) return false
    
    return true
  }
  
  /**
   * 中军龙头规则 - 趋势核心
   */
  static isMiddleLeader(stock: StockContext, sector: SectorContext): boolean {
    // 业务规则1：市值大于100亿
    if (stock.totalMV < 100e8) return false
    
    // 业务规则2：趋势向上（均线多头）
    const isTrendUp = stock.ma5 > stock.ma10 && 
                      stock.ma10 > stock.ma20 &&
                      stock.ma20 > stock.ma20 * 0.9  // 不能偏离太多
    if (!isTrendUp) return false
    
    // 业务规则3：成交量温和（不是爆量）
    if (stock.volumeRatio > 3) return false  // 量比超过3是爆量
    
    // 业务规则4：有机构参与
    const hasInstitution = stock.longhu?.includes('机构') || 
                           stock.longhu?.includes('北向')
    if (!hasInstitution && stock.limitDays < 2) return false
    
    // 业务规则5：题材不能太冷
    if (sector.sectorHeat < 2000) return false
    
    return true
  }
  
  /**
   * 情绪龙头规则 - 情绪指标
   */
  static isEmotionLeader(stock: StockContext, market: MarketContext): boolean {
    // 业务规则1：换手率大于20%（游资票）
    if (stock.turnoverRate < 20) return false
    
    // 业务规则2：与市场情绪共振或背离
    if (market.marketPhase === '冰点期') {
      // 冰点期的逆势票
      if (stock.change < 5) return false
    } else if (market.marketPhase === '高潮期') {
      // 高潮期的高换手接力
      if (stock.turnoverRate < 25) return false
    }
    
    // 业务规则3：有属性标签（次新、低价、超跌等）
    const hasHotAttribute = stock.attributes.some(attr => 
      ['次新', '低价', '超跌', '摘帽', '重组'].includes(attr)
    )
    if (!hasHotAttribute && stock.limitDays < 2) return false
    
    // 业务规则4：不能有机构砸盘
    if (stock.longhu?.includes('机构卖出')) return false
    
    return true
  }
  
  /**
   * 计算总龙头综合得分
   */
  private static calculateTotalLeaderScore(
    stock: StockContext, 
    market: MarketContext,
    sector: SectorContext
  ): number {
    let score = 0
    
    // 排名因子 (30%)
    const rankScore = Math.max(0, 100 - stock.compRank * 5)
    score += rankScore * 0.3
    
    // 题材热度因子 (25%)
    const heatScore = Math.min(100, sector.sectorHeat / 50)
    score += heatScore * 0.25
    
    // 资金因子 (25%)
    const moneyScore = Math.min(100, (stock.zlje / 1e8) * 2)  // 1亿=2分
    score += moneyScore * 0.25
    
    // 情绪因子 (20%)
    let emotionScore = 50
    if (market.marketPhase === '高潮期') emotionScore = 80
    if (market.marketPhase === '发酵期') emotionScore = 70
    if (market.marketPhase === '冰点期') emotionScore = 60
    if (market.marketPhase === '退潮期') emotionScore = 40
    score += emotionScore * 0.2
    
    return score
  }
}