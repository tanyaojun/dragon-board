// src/composables/useCache.ts
import { sectorCache } from '@/services/LRUCache'
import { dataLayer } from '@/services/DataLayer'

export function useCache(panelName: string) {
  
  function getCacheKey(key: string): string {
    const version = dataLayer.getVersion?.()
    return `${panelName}:${key}:t${version?.themes || 0}:s${version?.stocks || 0}`
  }

  async function getOrCompute<T>(
    key: string,
    compute: () => Promise<T>,
    ttl: number = 30000,
    tags: string[] = []
  ): Promise<T> {
    const cacheKey = getCacheKey(key)
    return sectorCache.getOrComputeAsync(cacheKey, compute, ttl, tags)
  }

  function invalidate(tags: string | string[]) {
    const tagList = Array.isArray(tags) ? tags : [tags]
    tagList.forEach(tag => sectorCache.invalidateByTag?.(tag))
  }

  function clear() {
    sectorCache.clear?.()
  }

  return {
    getOrCompute,
    invalidate,
    clear,
    getCacheKey,
  }
}