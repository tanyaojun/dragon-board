// calculateThemeHeat 函数
热度计算公式：
heatScore = (
  基础分(每个成分股) +
  涨停加分(每个涨停股) +
  连板加分(连板天数 * 系数) +
  龙头加分(每个龙头股) +
  热点加分(股票热度)
) * (1 + 相关性系数 * 0.2)

// 权重配置
CONFIG.HEAT_WEIGHTS = {
  STOCK_BASE: 10,        // 每个成分股基础分
  ZT_COUNT: 50,          // 每个涨停股加分
  CONTINUOUS_DAY: 20,    // 每连板一天加分
  LEADER_COUNT: 30,      // 每个龙头股加分
  HOT_SCORE: 0.5,        // 股票热点系数
  CORRELATION_BONUS: 0.2 // 相关性奖励系数
}