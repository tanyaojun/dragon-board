const PLATFORMS = ['eastmoney', 'ths', 'kpl', 'tdx', 'xueqiu', 'cls', 'tgb', 'dzh'] as const

type Platform = (typeof PLATFORMS)[number]

const rankFieldMap: Record<Platform, string> = {
  eastmoney: 'emRank',
  ths: 'thsRank',
  kpl: 'kplRank',
  tdx: 'tdxRank',
  xueqiu: 'xqRank',
  cls: 'clsRank',
  tgb: 'tgbRank',
  dzh: 'dzhRank',
}

/**
 * 只保留平台 rank 字段映射查询（StockMergeCoordinator 用于合并各平台排名输入）。
 * 五维综合排名 agRank 等计算结论值已全部后端化（backend/analysis/ranktrend/comprehensive_rank.py），
 * 前端不再重算，杜绝前后端口径漂移。
 */
export function getRankField(platform: string): string | null {
  return rankFieldMap[platform as Platform] || null
}
