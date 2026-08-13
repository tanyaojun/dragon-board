// rankTrend 分析结果前端 LRU TTL 缓存。
// 与后端 analyze Redis 缓存（60s TTL）配合：后端 Redis 保证数据新鲜度（60s 内一致），
// 前端 LRU 300s 覆盖「分析耗时较长（60s+）」场景——避免数据刷新循环在分析刚完成就因缓存过期
// 重复打后端，并让【共振/趋势/量价/周期】四字段在分析未完成/未预热时能命中缓存稳定显示。
// 观察指标（共振/趋势/量价/周期）基于快照帧低频变化，300s 内缓存旧值风险可接受。
import { cacheManager } from '../LRUCache'

/** 前端 LRU TTL：300s（覆盖慢分析场景，避免刷新循环在分析刚完成就重复打后端）。
 *  数据新鲜度由后端 analyze 缓存 TTL 保证（盘中 300s / 盘后 1800s 动态化）；
 *  前端 LRU 只在浏览器内存中，重启即清空，冷启动恢复不依赖它，故保持 300s。 */
export const RANK_TREND_RESULT_CACHE_TTL_MS = 300_000

export const rankTrendResultCache = cacheManager.createCache('rankTrendResult', {
  capacity: 1200,
  defaultTTL: RANK_TREND_RESULT_CACHE_TTL_MS,
  maxMemory: 8 * 1024 * 1024,
  ttlConfig: { rankTrendResult: RANK_TREND_RESULT_CACHE_TTL_MS },
})

export const rankTrendResultCacheKey = (code: string, snapshotType: string): string =>
  `${snapshotType}:${code}`

/** 测试与诊断用：清空 rankTrend 结果缓存。 */
export function clearRankTrendResultCache(): void {
  rankTrendResultCache.clear()
}
