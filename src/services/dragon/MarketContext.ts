// src/services/dragon/MarketContext.ts

/**
 * 市场上下文 - 为龙头判断提供全局视角
 */
export interface MarketContext {
  // 市场整体
  marketPhase: '冰点期' | '发酵期' | '高潮期' | '退潮期'
  marketSentiment: number      // 0-100
  upCount: number              // 上涨家数
  downCount: number            // 下跌家数
  
  // 涨停数据
  totalZtCount: number         // 总涨停数
  limitDistribution: {         // 连板分布
    yiban: number              // 首板
    erban: number              // 二板
    sanban: number             // 三板
    sibanPlus: number          // 四板以上
  }
  
  // 赚钱效应
  passRate: number             // 晋级率
  zhabanRate: number           // 炸板率
  fengbanRate: number          // 封板率
  
  // 资金面
  mainInflow: number           // 主力净流入
  turnoverTop10: number        // 前10成交额总和
}

/**
 * 题材上下文 - 为板块龙头判断提供
 */
export interface SectorContext {
  sectorName: string
  sectorHeat: number           // 题材热度
  sectorMomentum: number       // 题材动量
  sectorZtCount: number        // 板块涨停数
  sectorLeaderCount: number    // 板块龙头数
  
  // 涨停时间线
  firstLimitTime: string       // 最先涨停时间
  firstLimitCode: string       // 最先涨停股票
  
  // 封单情况
  maxFengdan: number           // 最大封单
  maxFengdanCode: string       // 最大封单股票
  
  // 跟风情况
  followerCodes: string[]      // 跟风股票
  ztIncrease: number           // 涨停增加数（比昨日）
}

/**
 * 个股上下文 - 为个股分析提供
 */
export interface StockContext {
  // 个股属性
  code: string
  name: string
  
  // 技术面
  ma5: number                  // 5日均线
  ma10: number                 // 10日均线
  ma20: number                 // 20日均线
  volumeRatio: number          // 量比
  turnoverRate: number         // 换手率
  
  // 资金面
  fengdan: number              // 封单金额
  zlje: number                 // 主力净额
  longhu: string[]             // 龙虎榜席位
  
  // 题材
  themes: Array<{
    name: string
    heat: number
    rank: number
  }>
  
  // 属性标签
  attributes: string[]         // ['次新', '低价', '超跌', '国企']
  
  // 涨停信息
  limitTime?: string           // 涨停时间
  limitType?: '一字' | 'T字' | '换手' | '烂板'
  limitDays: number            // 连板天数
}