// 量比结果前端 LRU TTL 缓存（60s）。
// 与后端量比结果 Redis 缓存（VOLUME_RATIO_RESULT_CACHE_TTL_SECONDS=60s）及前端刷新门限
// （VOLUME_RATIO_MIN_INTERVAL_MS=60s）一致：60s 内量比固定，缓存命中不再重复调后端量比接口。
// 量价计算依赖量比（量比先于量价），此缓存保证信号刷新前置量比刷新时 60s 内直接复用。
import { cacheManager } from '@/services/LRUCache'

/** 前端量比结果缓存 TTL：60s（与后端结果缓存/刷新门限一致） */
export const VOLUME_RATIO_CACHE_TTL_MS = 60_000

export const volumeRatioCache = cacheManager.createCache('volumeRatio', {
  capacity: 1200,
  defaultTTL: VOLUME_RATIO_CACHE_TTL_MS,
  maxMemory: 4 * 1024 * 1024,
  ttlConfig: { volumeRatio: VOLUME_RATIO_CACHE_TTL_MS },
})

/** 测试与诊断用：清空量比结果缓存。 */
export function clearVolumeRatioCache(): void {
  volumeRatioCache.clear()
}
