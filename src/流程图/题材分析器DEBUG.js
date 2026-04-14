// 查看当前进度
sectorAnalyzer.debug.getLoadProgress()

// 全量加载所有题材
sectorAnalyzer.debug.loadAllThemes(10, 500)

// 强制重新计算热度
sectorAnalyzer.debug.recalcAllHeat()

// 查看缓存状态
sectorAnalyzer.debug.cache.stats()

// 缓存预热
sectorAnalyzer.debug.cache.warmup(20)