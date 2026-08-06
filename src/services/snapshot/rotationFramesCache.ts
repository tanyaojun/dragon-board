// 轮动摘要帧查询共享投影缓存（SectorPanel / SectorRotation 共用）
// 30 分钟失效：轮动摘要数据来自最新快照帧，槽位数据变化低频；
// ranktrend 行投影瘦身后，帧级 rotationSummary 字段不受影响。
import { cacheManager } from '../LRUCache'

export const ROTATION_FRAMES_CACHE_TTL_MS = 30 * 60 * 1000

export const rotationFramesCache = cacheManager.createCache('sectorRotationFrames', {
  capacity: 4,
  defaultTTL: ROTATION_FRAMES_CACHE_TTL_MS,
  maxMemory: 8 * 1024 * 1024,
  ttlConfig: { sectorRotationFrames: ROTATION_FRAMES_CACHE_TTL_MS },
})
