// src/services/LRUCache.ts
// 优化版：添加分级TTL、批量操作、增强统计、修复所有方法
interface CacheItem<T> {
  value: T
  timestamp: number
  lastAccessed: number
  accessCount: number
  size: number
  tags?: Set<string>
  type?: string // 缓存类型，用于分级TTL
}

interface CacheStats {
  hits: number
  misses: number
  evictions: number
  size: number
  memoryUsage: number
  hitRate: number
  accessCount: number
  avgAccessPerItem: number
  hotKeys: CacheKeyInfo[]
  typeDistribution?: Record<string, number> // 类型分布
  ttlUsage?: Record<string, { count: number; avgAge: string }> // TTL使用情况
}

interface CacheKeyInfo {
  key: string
  accessCount: number
  lastAccessed: number
  size: number
  type?: string
}

// TTL配置接口
interface TTLConfig {
  [key: string]: number // 类型名称 -> TTL（毫秒）
}

class LRUCache<T = any> {
  private cache = new Map<string, CacheItem<T>>()
  private tagMap = new Map<string, Set<string>>()
  private readonly capacity: number
  private readonly defaultTTL: number
  private readonly maxMemory: number
  private currentMemory = 0

  // 统计
  private hits = 0
  private misses = 0
  private evictions = 0
  private totalAccessCount = 0

  // 预热队列
  private preloadQueue: string[] = []
  private isPreloading = false

  // 分级TTL配置
  private ttlConfig: TTLConfig = {}

  // ===== 内部事件订阅 =====
  private bumpCallbacks = new Set<(type: string, key?: string) => void>()

  constructor(
    capacity: number,
    defaultTTL: number = 5 * 60 * 1000,
    maxMemory: number = 5 * 1024 * 1024,
  ) {
    this.capacity = capacity
    this.defaultTTL = defaultTTL
    this.maxMemory = maxMemory

    // 初始化默认分级TTL
    this.initDefaultTTLConfig()
  }

  // ========== 分级TTL配置 ==========

  /**
   * 初始化默认分级TTL配置
   */
  private initDefaultTTLConfig() {
    this.ttlConfig = {
      default: this.defaultTTL,
      hot: 5 * 1000, // 热门数据5秒
      list: 30 * 1000, // 列表30秒
      detail: 5 * 60 * 1000, // 详情5分钟
      ranking: 15 * 1000, // 排行15秒
      stats: 10 * 1000, // 统计10秒
      score: 5 * 1000, // 得分5秒
      themeFactors: 10 * 1000, // 题材因子10秒
      'algorithm:stats': 30 * 1000, // 算法统计30秒
      realtime: 5 * 1000, // 实时数据5秒
      quote: 30 * 1000, // 行情数据30秒
      'dragon:list': 20 * 1000,
      'dragon:detail': 3 * 60 * 1000,
      'dragon:ranking': 15 * 1000,
      'sector:hot': 5 * 1000,
      'sector:list': 30 * 1000,
      'sector:detail': 5 * 60 * 1000,
    }
  }

  /**
   * 设置分级TTL
   */
  setTTLForType(type: string, ttl: number) {
    this.ttlConfig[type] = ttl
    console.log(`[LRUCache] 设置类型TTL: ${type}=${ttl}ms`)
  }

  /**
   * 批量设置分级TTL
   */
  setTTLConfig(config: TTLConfig) {
    this.ttlConfig = { ...this.ttlConfig, ...config }
    console.log(`[LRUCache] 已更新TTL配置，共${Object.keys(this.ttlConfig).length}种类型`)
  }

  /**
   * 获取类型TTL
   */
  getTTLForType(type: string = 'default'): number {
    return this.ttlConfig[type] || this.defaultTTL
  }

  /**
   * 获取所有TTL配置
   */
  getTTLConfig(): TTLConfig {
    return { ...this.ttlConfig }
  }

  // ========== 核心方法 ==========

  /**
   * 获取或计算缓存值（支持类型）
   */
  getOrCompute(key: string, compute: () => T, type?: string, tags?: string[]): T {
    let value = this.get(key)
    if (value === null) {
      value = compute()
      this.setWithType(key, value, type, tags)
    }
    return value
  }

  /**
   * 异步获取或计算缓存值
   */
  async getOrComputeAsync(
    key: string,
    compute: () => Promise<T>,
    type?: string,
    tags?: string[],
  ): Promise<T> {
    let value = this.get(key)
    if (value === null) {
      value = await compute()
      this.setWithType(key, value, type, tags)
    }
    return value
  }

  /**
   * 批量获取或计算缓存值
   */
  getOrComputeMany(
    keys: string[],
    compute: (missingKeys: string[]) => Map<string, T>,
    type?: string,
    tags?: string[],
  ): Map<string, T> {
    const result = new Map<string, T>()
    const missingKeys: string[] = []

    // 先从缓存获取
    keys.forEach((key) => {
      const value = this.get(key)
      if (value !== null) {
        result.set(key, value)
      } else {
        missingKeys.push(key)
      }
    })

    // 计算缺失的值
    if (missingKeys.length > 0) {
      const computed = compute(missingKeys)
      computed.forEach((value, key) => {
        this.setWithType(key, value, type, tags)
        result.set(key, value)
      })
    }

    return result
  }

  async getOrComputeManyAsync(
    keys: string[],
    compute: (missingKeys: string[]) => Promise<Map<string, T>>,
    type?: string,
    tags?: string[],
  ): Promise<Map<string, T>> {
    const result = new Map<string, T>()
    const missingKeys: string[] = []

    keys.forEach((key) => {
      const value = this.get(key)
      if (value !== null) {
        result.set(key, value)
      } else {
        missingKeys.push(key)
      }
    })

    if (missingKeys.length > 0) {
      const computed = await compute(missingKeys)
      computed.forEach((value, key) => {
        this.setWithType(key, value, type, tags)
        result.set(key, value)
      })
    }

    return result
  }

  /**
   * 按类型设置缓存
   */
  setWithType(key: string, value: T, type?: string, tags?: string[]) {
    const ttl = type ? this.getTTLForType(type) : this.defaultTTL
    this.set(key, value, ttl, tags, type)
  }

  /**
   * 批量按类型设置缓存
   */
  setManyWithType(entries: Array<{ key: string; value: T; type?: string; tags?: string[] }>) {
    entries.forEach(({ key, value, type, tags }) => {
      this.setWithType(key, value, type, tags)
    })
  }

  /**
   * 设置缓存项
   */
  set(key: string, value: T, customTTL?: number, tags?: string[], type?: string): void {
    const size = this.estimateSize(value)
    const ttl = customTTL || this.getTTLForType(type)

    // 检查内存限制
    if (this.currentMemory + size > this.maxMemory) {
      this.evictByMemory(size)
    }

    // 如果 key 已存在，先减去旧值的内存
    if (this.cache.has(key)) {
      const oldItem = this.cache.get(key)!
      this.currentMemory -= oldItem.size

      // 从旧标签中移除
      if (oldItem.tags) {
        oldItem.tags.forEach((tag) => {
          const tagSet = this.tagMap.get(tag)
          if (tagSet) {
            tagSet.delete(key)
            if (tagSet.size === 0) {
              this.tagMap.delete(tag)
            }
          }
        })
      }
    }

    const item: CacheItem<T> = {
      value,
      timestamp: Date.now(),
      lastAccessed: Date.now(),
      accessCount: 0,
      size,
      tags: tags ? new Set(tags) : undefined,
      type,
    }

    this.cache.set(key, item)
    this.currentMemory += size

    // 记录标签
    if (tags) {
      tags.forEach((tag) => {
        if (!this.tagMap.has(tag)) {
          this.tagMap.set(tag, new Set())
        }
        this.tagMap.get(tag)!.add(key)
      })
    }

    // 检查容量
    if (this.cache.size > this.capacity) {
      this.evictLRU()
    }

    // ✅ 触发内部 bump 事件（新增）
    this.triggerBump('set', key)
  }

  /**
   * 获取缓存项
   */
  get(key: string): T | null {
    const startTime = performance.now()
    const item = this.cache.get(key)
    const accessTime = performance.now() - startTime
    this.totalAccessCount++

    if (!item) {
      this.misses++
      return null
    }


    // 检查是否过期
    const ttl = item.type ? this.getTTLForType(item.type) : this.defaultTTL
    if (Date.now() - item.timestamp > ttl) {
      this.cache.delete(key)
      this.currentMemory -= item.size
      this.misses++

      // ✅ 触发内部 bump 事件（新增）
      this.triggerBump('expired', key)

      return null
    }

    // 更新访问信息
    item.lastAccessed = Date.now()
    item.accessCount++
    this.hits++

    // ✅ 触发内部 bump 事件
    this.triggerBump('hit', key)

    return item.value
  }

  /**
   * 批量获取缓存
   */
  getMany(keys: string[]): Map<string, T | null> {
    const result = new Map<string, T | null>()
    keys.forEach((key) => {
      result.set(key, this.get(key))
    })
    return result
  }

  /**
   * 检查键是否存在
   */
  has(key: string): boolean {
    const item = this.cache.get(key)
    if (!item) return false

    if (Date.now() - item.timestamp > this.defaultTTL) {
      this.cache.delete(key)
      this.currentMemory -= item.size
      return false
    }

    return true
  }

  /**
   * 删除缓存项
   */
  delete(key: string): boolean {
    const item = this.cache.get(key)
    if (item) {
      // 从标签中移除
      if (item.tags) {
        item.tags.forEach((tag) => {
          const tagSet = this.tagMap.get(tag)
          if (tagSet) {
            tagSet.delete(key)
            if (tagSet.size === 0) {
              this.tagMap.delete(tag)
            }
          }
        })
      }

      this.currentMemory -= item.size
      const result = this.cache.delete(key)

      // ✅ 触发内部 bump 事件（新增）
      if (result) {
        this.triggerBump('delete', key)
      }

      return result
    }
    return false
  }

  /**
   * 按前缀删除
   */
  deleteByPrefix(prefix: string): number {
    let count = 0
    for (const key of this.cache.keys()) {
      if (key.startsWith(prefix)) {
        if (this.delete(key)) count++
      }
    }
    return count
  }

  /**
   * 清空所有缓存
   */
  clear(): void {
    this.cache.clear()
    this.tagMap.clear()
    this.preloadQueue = []
    this.currentMemory = 0
    this.hits = 0
    this.misses = 0
    this.evictions = 0
    this.totalAccessCount = 0
    this.isPreloading = false
  }

  /**
   * 订阅缓存变更事件
   * @param callback 回调函数，参数为 (type: string, key?: string)
   * @returns 取消订阅的函数
   */
  onBump(callback: (type: string, key?: string) => void): () => void {
    this.bumpCallbacks.add(callback)
    return () => this.bumpCallbacks.delete(callback)
  }

  /**
   * 触发 bump 事件（内部使用）
   */
  private triggerBump(type: string, key?: string) {
    this.bumpCallbacks.forEach((cb) => {
      try {
        cb(type, key)
      } catch (e) {
        console.error(`[LRUCache] bump回调错误:`, e)
      }
    })
  }

  /**
   * 获取缓存大小
   */
  size(): number {
    return this.cache.size
  }

  // ========== 淘汰策略 ==========

  /**
   * 淘汰最久未使用的项（LRU）
   */
  private evictLRU(): void {
    let oldest: { key: string; time: number } | null = null

    for (const [key, item] of this.cache.entries()) {
      if (!oldest || item.lastAccessed < oldest.time) {
        oldest = { key, time: item.lastAccessed }
      }
    }

    if (oldest) {
      this.delete(oldest.key)
      this.evictions++

      // ✅ 触发内部 bump 事件（新增）
      this.triggerBump('evict', oldest.key)
    }
  }

  /**
   * 淘汰最少使用的项（LFU）
   */
  private evictLFU(): void {
    let leastUsed: { key: string; count: number } | null = null

    for (const [key, item] of this.cache.entries()) {
      if (!leastUsed || item.accessCount < leastUsed.count) {
        leastUsed = { key, count: item.accessCount }
      }
    }

    if (leastUsed) {
      this.delete(leastUsed.key)
      this.evictions++
    }
  }

  /**
   * 混合淘汰策略
   */
  private evictHybrid(): void {
    let worstScore: { key: string; score: number } | null = null

    for (const [key, item] of this.cache.entries()) {
      const age = Date.now() - item.lastAccessed
      const score = item.accessCount / (1 + age / 60000)

      if (!worstScore || score < worstScore.score) {
        worstScore = { key, score }
      }
    }

    if (worstScore) {
      this.delete(worstScore.key)
      this.evictions++
    }
  }

  /**
   * 按内存淘汰
   */
  private evictByMemory(neededSize: number): void {
    const items = Array.from(this.cache.entries()).sort(
      (a, b) => a[1].lastAccessed - b[1].lastAccessed,
    )

    for (const [key, item] of items) {
      if (this.currentMemory + neededSize <= this.maxMemory) break
      this.delete(key)
      this.evictions++
    }
  }

  // ========== 内存估算 ==========

  /**
   * 估算值的内存大小
   */
  private estimateSize(value: T): number {
    if (value === null || value === undefined) {
      return 8
    }

    // 基础类型
    if (typeof value === 'boolean') {
      return 4
    }
    if (typeof value === 'number') {
      return 8
    }
    if (typeof value === 'string') {
      return value.length * 2
    }

    // 数组
    if (Array.isArray(value)) {
      return value.reduce((sum, item) => sum + this.estimateSize(item), 0)
    }

    // 对象
    if (typeof value === 'object') {
      try {
        const json = JSON.stringify(value)
        return json ? json.length * 2 : 64
      } catch (e) {
        // 如果序列化失败（比如循环引用），返回一个估算值
        return 1024
      }
    }

    // 默认大小
    return 64
  }

  // ========== 标签系统 ==========

  /**
   * 按标签使缓存失效
   */
  invalidateByTag(tag: string): number {
    const keys = this.tagMap.get(tag)
    if (!keys) return 0

    let count = 0
    keys.forEach((key) => {
      if (this.delete(key)) count++
    })
    this.tagMap.delete(tag)
    return count
  }

  /**
   * 按多个标签使缓存失效
   */
  invalidateByTags(tags: string[]): number {
    let total = 0
    tags.forEach((tag) => {
      total += this.invalidateByTag(tag)
    })
    return total
  }

  /**
   * 获取标签下的所有键
   */
  getKeysByTag(tag: string): string[] {
    return Array.from(this.tagMap.get(tag) || [])
  }

  // ========== 缓存预热 ==========

  /**
   * 添加预热任务
   */
  addToPreload(key: string): void {
    if (!this.cache.has(key) && !this.preloadQueue.includes(key)) {
      this.preloadQueue.push(key)
    }
  }

  /**
   * 批量添加预热任务
   */
  addManyToPreload(keys: string[]): void {
    keys.forEach((key) => {
      this.addToPreload(key)
    })
  }

  /**
   * 开始预热
   */
  async startPreload(
    loader: (key: string) => Promise<T>,
    concurrency: number = 3,
    onProgress?: (loaded: number, total: number) => void,
  ): Promise<void> {
    if (this.isPreloading || this.preloadQueue.length === 0) return

    this.isPreloading = true
    const total = this.preloadQueue.length
    let loaded = 0

    console.log(`[LRUCache] 🚀 开始预热 ${total} 个条目`)

    // 分批加载
    const batches = []
    for (let i = 0; i < this.preloadQueue.length; i += concurrency) {
      batches.push(this.preloadQueue.slice(i, i + concurrency))
    }

    for (const batch of batches) {
      await Promise.all(
        batch.map(async (key) => {
          try {
            const value = await loader(key)
            this.set(key, value, undefined, ['preload'])
            loaded++
            if (onProgress) {
              onProgress(loaded, total)
            }
          } catch (error) {
            console.error(`[LRUCache] 预热失败: ${key}`, error)
          }
        }),
      )
    }

    this.preloadQueue = []
    this.isPreloading = false
    console.log(`[LRUCache] ✅ 预热完成: ${loaded}/${total}`)
  }

  /**
   * 获取预热进度
   */
  getPreloadProgress(): { loaded: number; total: number; isPreloading: boolean } {
    return {
      loaded: this.isPreloading ? this.preloadQueue.length - this.preloadQueue.length : 0,
      total: this.preloadQueue.length,
      isPreloading: this.isPreloading,
    }
  }

  // ========== 统计信息 ==========

  /**
   * 获取类型分布
   */
  getTypeDistribution(): Record<string, number> {
    const distribution: Record<string, number> = {}

    for (const [key, item] of this.cache.entries()) {
      const type = item.type || 'unknown'
      distribution[type] = (distribution[type] || 0) + 1
    }

    return distribution
  }

  /**
   * 获取TTL使用情况
   */
  getTTLUsage(): Record<string, { count: number; avgAge: string }> {
    const usage: Record<string, { count: number; totalAge: number }> = {}
    const now = Date.now()

    for (const [key, item] of this.cache.entries()) {
      const type = item.type || 'unknown'
      if (!usage[type]) {
        usage[type] = { count: 0, totalAge: 0 }
      }

      usage[type].count++
      usage[type].totalAge += now - item.timestamp
    }

    const result: Record<string, { count: number; avgAge: string }> = {}
    for (const [type, data] of Object.entries(usage)) {
      result[type] = {
        count: data.count,
        avgAge: (data.totalAge / data.count / 1000).toFixed(0) + 's',
      }
    }

    return result
  }

  /**
   * 获取增强统计
   */
  getStats(): CacheStats {
    const hitRate = this.hits + this.misses > 0 ? (this.hits / (this.hits + this.misses)) * 100 : 0
    const avgAccessPerItem = this.cache.size > 0 ? this.totalAccessCount / this.cache.size : 0

    return {
      hits: this.hits,
      misses: this.misses,
      evictions: this.evictions,
      size: this.cache.size, // ✅ 这里是实际缓存条目数
      memoryUsage: this.currentMemory,
      hitRate,
      accessCount: this.totalAccessCount,
      avgAccessPerItem,
      hotKeys: this.getHotKeys(5),
      typeDistribution: this.getTypeDistribution(),
      ttlUsage: this.getTTLUsage(),
    }
  }

  /**
   * 获取命中率
   */
  getHitRate(): number {
    const total = this.hits + this.misses
    return total > 0 ? (this.hits / total) * 100 : 0
  }

  /**
   * 获取热门键
   */
  getHotKeys(limit: number = 10): CacheKeyInfo[] {
    const keys = Array.from(this.cache.entries())
      .map(([key, item]) => ({
        key,
        accessCount: item.accessCount,
        lastAccessed: item.lastAccessed,
        size: item.size,
        type: item.type,
      }))
      .sort((a, b) => b.accessCount - a.accessCount)
      .slice(0, limit)

    return keys
  }

  /**
   * 获取冷门键
   */
  getColdKeys(limit: number = 10): CacheKeyInfo[] {
    const keys = Array.from(this.cache.entries())
      .map(([key, item]) => {
        const age = Date.now() - item.lastAccessed
        const coldScore = (1 / (item.accessCount + 1)) * age
        return {
          key,
          accessCount: item.accessCount,
          lastAccessed: item.lastAccessed,
          size: item.size,
          type: item.type,
          coldScore,
        }
      })
      .sort((a, b) => b.coldScore - a.coldScore)
      .slice(0, limit)
      .map(({ coldScore, ...rest }) => rest)

    return keys
  }

  /**
   * 清理过期缓存
   */
  cleanup(): number {
    let cleaned = 0
    const now = Date.now()

    for (const [key, item] of this.cache.entries()) {
      const ttl = item.type ? this.getTTLForType(item.type) : this.defaultTTL
      if (now - item.timestamp > ttl) {
        this.delete(key)
        cleaned++
      }
    }

    return cleaned
  }

  /**
   * 遍历所有缓存
   */
  forEach(callback: (value: T, key: string) => void): void {
    for (const [key, item] of this.cache.entries()) {
      callback(item.value, key)
    }
  }

  /**
   * 获取所有键
   */
  keys(): string[] {
    return Array.from(this.cache.keys())
  }

  /**
   * 获取所有值
   */
  values(): T[] {
    return Array.from(this.cache.values()).map((item) => item.value)
  }

  /**
   * 获取所有条目
   */
  entries(): Array<{ key: string; value: T; stats: Omit<CacheItem<T>, 'value'> }> {
    return Array.from(this.cache.entries()).map(([key, item]) => ({
      key,
      value: item.value,
      stats: {
        timestamp: item.timestamp,
        lastAccessed: item.lastAccessed,
        accessCount: item.accessCount,
        size: item.size,
        type: item.type,
      },
    }))
  }
}

// ========== 缓存管理器 ==========

class CacheManager {
  private caches: Map<string, LRUCache> = new Map()
  private preloadTasks: Map<string, () => Promise<any>> = new Map()

  /**
   * 创建缓存实例
   */
  createCache(
    name: string,
    config: {
      capacity: number
      defaultTTL: number
      maxMemory: number
      ttlConfig?: TTLConfig
    },
  ): LRUCache {
    const cache = new LRUCache(config.capacity, config.defaultTTL, config.maxMemory)

    if (config.ttlConfig) {
      cache.setTTLConfig(config.ttlConfig)
    }

    this.caches.set(name, cache)
    return cache
  }

  createStockCache() {
    return this.createCache('stock', {
      capacity: 800,
      defaultTTL: 30 * 60 * 1000,
      maxMemory: 8 * 1024 * 1024,
      ttlConfig: {
        score: 5 * 1000,
        themeFactors: 10 * 1000,
        'algorithm:stats': 30 * 1000,
      },
    })
  }

  createLeaderCache() {
    return this.createCache('leader', {
      capacity: 300,
      defaultTTL: 30 * 60 * 1000,
      maxMemory: 6 * 1024 * 1024,
      ttlConfig: {
        'dragon:list': 20 * 1000,
        'dragon:detail': 3 * 60 * 1000,
        'dragon:ranking': 15 * 1000,
        'dragon:stats': 8 * 1000,
      },
    })
  }

  createSectorCache() {
    return this.createCache('sector', {
      capacity: 600,
      defaultTTL: 2 * 60 * 60 * 1000,
      maxMemory: 10 * 1024 * 1024,
      ttlConfig: {
        'sector:hot': 5 * 1000,
        'sector:list': 30 * 1000,
        'sector:detail': 5 * 60 * 1000,
        'sector:rotation': 15 * 1000,
        'sector:correlation': 10 * 60 * 1000,
        'sector:history': 30 * 60 * 1000,
      },
    })
  }

  createQuoteCache() {
    return this.createCache('quote', {
      capacity: 1500,
      defaultTTL: 30 * 1000,
      maxMemory: 3 * 1024 * 1024,
      ttlConfig: {
        realtime: 5 * 1000,
        quote: 30 * 1000,
      },
    })
  }

  getCache(name: string): LRUCache | undefined {
    return this.caches.get(name)
  }

  /**
   * 注册预热任务
   */
  registerPreloadTask(name: string, task: () => Promise<any>): void {
    this.preloadTasks.set(name, task)
  }

  /**
   * 执行所有预热任务
   */
  async preloadAll(concurrency: number = 2): Promise<void> {
    console.log('[CacheManager] 🚀 开始缓存预热...')

    const tasks = Array.from(this.preloadTasks.entries())
    const batches = []

    for (let i = 0; i < tasks.length; i += concurrency) {
      batches.push(tasks.slice(i, i + concurrency))
    }

    for (const batch of batches) {
      await Promise.all(
        batch.map(async ([name, task]) => {
          try {
            console.log(`[CacheManager] 预热: ${name}`)
            await task()
          } catch (error) {
            console.error(`[CacheManager] 预热失败: ${name}`, error)
          }
        }),
      )
    }

    console.log('[CacheManager] ✅ 缓存预热完成')
  }

  /**
   * 按标签使缓存失效（跨所有缓存）
   */
  invalidateByTag(tag: string): Record<string, number> {
    const result: Record<string, number> = {}
    this.caches.forEach((cache, name) => {
      const count = cache.invalidateByTag(tag)
      if (count > 0) {
        result[name] = count
      }
    })
    return result
  }

  /**
   * 清空所有缓存
   */
  clearAll(): void {
    this.caches.forEach((cache) => cache.clear())
    console.log('[CacheManager] 🧹 所有缓存已清空')
  }

  /**
   * 按前缀清除缓存
   */
  clearByPrefix(prefix: string): Record<string, number> {
    const result: Record<string, number> = {}
    this.caches.forEach((cache, name) => {
      const count = cache.deleteByPrefix(prefix)
      if (count > 0) {
        result[name] = count
      }
    })
    return result
  }

  /**
   * 清理过期缓存
   */
  cleanup(): Record<string, number> {
    const result: Record<string, number> = {}
    this.caches.forEach((cache, name) => {
      const count = cache.cleanup()
      if (count > 0) {
        result[name] = count
      }
    })
    return result
  }

  /**
   * 获取所有缓存统计
   */
  getAllStats(): Record<string, CacheStats> {
    const stats: Record<string, CacheStats> = {}
    this.caches.forEach((cache, name) => {
      stats[name] = cache.getStats()
    })
    return stats
  }

  /**
   * 获取摘要
   */
  getSummary() {
    let totalSize = 0
    let totalMemory = 0
    let totalHits = 0
    let totalMisses = 0

    this.caches.forEach((cache) => {
      const stats = cache.getStats()
      totalSize += stats.size
      totalMemory += stats.memoryUsage
      totalHits += stats.hits
      totalMisses += stats.misses
    })

    const avgHitRate =
      totalHits + totalMisses > 0 ? (totalHits / (totalHits + totalMisses)) * 100 : 0

    return {
      totalSize,
      totalMemory,
      totalHits,
      totalMisses,
      avgHitRate,
    }
  }

  // 添加异步方法
  async getOrComputeAsync<T>(
    key: string,
    computeFn: () => Promise<T>,
    type?: string,
    tags?: string[],
  ): Promise<T> {
    const cache = this.getCache('default') // 获取默认缓存实例
    if (!cache) {
      throw new Error('默认缓存实例不存在')
    }
    return cache.getOrComputeAsync(key, computeFn, type, tags)
  }

  async getOrComputeManyAsync<T>(
    keys: string[],
    computeFn: (missingKeys: string[]) => Promise<Map<string, T>>,
    type?: string,
    tags?: string[],
  ): Promise<Map<string, T>> {
    const cache = this.getCache('default')
    if (!cache) {
      throw new Error('默认缓存实例不存在')
    }
    // 由于 LRUCache 类中没有 getOrComputeManyAsync 方法，这里需要实现一个
    const result = new Map<string, T>()
    const missingKeys: string[] = []

    // 检查缓存
    keys.forEach((key) => {
      const cached = cache.get(key)
      if (cached !== null) {
        result.set(key, cached as T)
      } else {
        missingKeys.push(key)
      }
    })

    // 计算缺失的
    if (missingKeys.length > 0) {
      const computed = await computeFn(missingKeys)
      computed.forEach((value, key) => {
        cache.setWithType(key, value, type, tags)
        result.set(key, value)
      })
    }
    return result
  }

}

// 导出单例
export const cacheManager = new CacheManager()

// 初始化各类型缓存
export const stockCache = cacheManager.createStockCache()
export const leaderCache = cacheManager.createLeaderCache()
export const sectorCache = cacheManager.createSectorCache()
export const quoteCache = cacheManager.createQuoteCache()

// 挂载到 window
if (typeof window !== 'undefined') {
  ;(window as any).LRUCache = {
    stock: stockCache,
    leader: leaderCache,
    sector: sectorCache,
    quote: quoteCache,
    manager: cacheManager,
  }
  console.log('[LRUCache] ✅ 缓存管理器已初始化')
}
