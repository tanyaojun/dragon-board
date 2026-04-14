// src/services/RefreshCoordinator.ts
// 职责：协调所有分析器的刷新顺序，确保数据一致性
// 注意：已移除所有增量刷新相关代码

import { EventManager } from '@/utils/eventManager'
import { AppEvents } from '@/types'
import { dataLayer } from './DataLayer'

interface Service {
  name: string
  instance: any
  priority: number // 执行优先级（数字越小越先执行）
  fullMethod?: string // 全量刷新方法名
  syncMethod?: string // 数据同步方法名
  dependsOn?: string[] // 依赖的其他服务
}

interface RefreshContext {
  type: 'full' // 只保留全量刷新
  startTime: number
  results: Map<string, any>
  errors: Map<string, Error>
}

class RefreshCoordinator {
  private services: Map<string, Service> = new Map()
  private isRefreshing = false
  private currentContext: RefreshContext | null = null

  private pendingRequests: Map<string, number> = new Map()
  private readonly REQUEST_COOLDOWN = 5000 // 5秒内相同类型请求只处理一次

  // 服务注册表（按优先级排序）
  private readonly SERVICE_REGISTRY: Omit<Service, 'instance'>[] = [
    // 第1层：数据层（必须先有数据）
    {
      name: 'dataLoader',
      priority: 10,
      fullMethod: 'runUpdate',
      syncMethod: 'mergeData',
    },
    // 第3层：基础分析器（依赖数据）
    {
      name: 'dragonAnalyzer',
      priority: 30,
      fullMethod: 'runFullUpdate',
      syncMethod: 'syncData',
      dependsOn: ['dataLoader'],
    },
    {
      name: 'sectorAnalyzer',
      priority: 31,
      fullMethod: 'runUpdate',
      syncMethod: 'syncData',
      dependsOn: ['dataLoader'],
    },
    // 第4层：复合分析器（依赖基础分析器）
    {
      name: 'dragonBreathAnalyzer',
      priority: 40,
      fullMethod: 'runFullUpdate',
      syncMethod: 'syncData',
      dependsOn: ['dragonAnalyzer', 'sectorAnalyzer'],
    },
    {
      name: 'algorithmManager',
      priority: 41,
      fullMethod: 'runFullUpdate',
      syncMethod: 'syncData',
      dependsOn: ['dragonAnalyzer', 'sectorAnalyzer'],
    },
  ]

  constructor() {
    this.setupListeners()
    this.scheduleRegistration()
  }

  /**
   * 调度服务注册
   */
  private scheduleRegistration() {
    if (this.registrationTimer) {
      clearTimeout(this.registrationTimer)
    }

    this.registrationTimer = setTimeout(() => {
      this.registerServices()
      this.registrationTimer = null
    }, 1000) // 延迟1秒，让所有服务先初始化
  }

  /**
   * 手动注册服务（供外部调用）
   */
  registerService(name: string, instance: any) {
    const reg = this.SERVICE_REGISTRY.find((r) => r.name === name)
    if (reg) {
      this.services.set(name, {
        ...reg,
        instance,
      })
      console.log(`[RefreshCoordinator] ✅ 手动注册服务: ${name}`)
    } else {
      console.warn(`[RefreshCoordinator] ⚠️ 未知服务名称: ${name}，跳过注册`)
    }
  }

  /**
   * 注册所有服务
   */
  private registerServices() {
    if (this.registered) return

    const missingServices: string[] = []

    this.SERVICE_REGISTRY.forEach((reg) => {
      // 尝试多种方式获取服务实例
      let instance = (window as any)[reg.name]

      if (!instance) {
        const possibleNames = [reg.name, reg.name.replace('Analyzer', ''), reg.name.toLowerCase()]

        for (const name of possibleNames) {
          if ((window as any)[name]) {
            instance = (window as any)[name]
            break
          }
        }
      }

      if (instance) {
        this.services.set(reg.name, {
          ...reg,
          instance,
        })
        console.log(`[RefreshCoordinator] ✅ 已注册服务: ${reg.name}`)
      } else {
        missingServices.push(reg.name)
        console.warn(`[RefreshCoordinator] ⚠️ 服务未找到: ${reg.name}`)
      }
    })

    this.registered = true

    // 如果有缺失的服务，稍后重试
    if (missingServices.length > 0) {
      console.log(`[RefreshCoordinator] 缺失服务: ${missingServices.join(', ')}，5秒后重试`)
      setTimeout(() => {
        this.retryMissingServices(missingServices)
      }, 5000)
    }
  }

  /**
   * 重试缺失的服务
   */
  private retryMissingServices(missingServices: string[]) {
    missingServices.forEach((name) => {
      const instance = (window as any)[name]
      if (instance) {
        const reg = this.SERVICE_REGISTRY.find((r) => r.name === name)
        if (reg) {
          this.services.set(name, {
            ...reg,
            instance,
          })
          console.log(`[RefreshCoordinator] ✅ 重试成功: ${name}`)
        }
      }
    })
  }

  /**
   * 设置事件监听
   */
  private setupListeners() {
    // 监听全量刷新请求
    EventManager.on(AppEvents.REFRESH.FULL_REQUESTED, async (data: any) => {
      if (this.isRefreshing) {
        console.log('[RefreshCoordinator] 刷新进行中，忽略请求')
        return
      }
      await this.executeRefresh('full', data)
    })

    // 监听手动刷新（通过 manualRefresh）
    EventManager.on('refresh:manual-requested', async (data: any) => {
      if (this.isRefreshing) return
      await this.executeRefresh('full', { ...data, source: 'manual' })
    })

    console.log('[RefreshCoordinator] 监听器已设置')
  }

  /**
   * 执行刷新（核心协调逻辑）
   */
  private async executeRefresh(type: 'full', requestData: any) {
    // 生成请求key
    const requestKey = `${type}_${requestData.source || 'unknown'}`
    const now = Date.now()

    // 检查是否最近处理过相同请求
    const lastTime = this.pendingRequests.get(requestKey)
    if (lastTime && now - lastTime < this.REQUEST_COOLDOWN) {
      console.log(
        `[RefreshCoordinator] ⏱️ 忽略重复请求: ${requestKey}, 距离上次: ${now - lastTime}ms`,
      )
      return
    }

    this.pendingRequests.set(requestKey, now)

    const startTime = Date.now()
    this.isRefreshing = true

    const context: RefreshContext = {
      type,
      startTime,
      results: new Map(),
      errors: new Map(),
    }

    this.currentContext = context

    console.log(`[RefreshCoordinator] ========== 开始协调全量刷新 ==========`)
    console.log(`[RefreshCoordinator] 请求数据:`, requestData)

    try {
      // 1. 按优先级排序服务
      const sortedServices = Array.from(this.services.values()).sort(
        (a, b) => a.priority - b.priority,
      )

      // 添加整体超时控制（5分钟）
      const overallTimeout = setTimeout(() => {
        console.error('[RefreshCoordinator] ⚠️ 整体刷新超时，强制结束')
        this.isRefreshing = false
        this.currentContext = null
      }, 300000) // 5分钟

      // 2. 分层执行
      for (const service of sortedServices) {
        // 检查依赖是否都成功了
        if (!this.checkDependencies(service, context)) {
          console.warn(`[RefreshCoordinator] ${service.name} 的依赖未满足，跳过`)
          context.errors.set(service.name, new Error('依赖服务失败'))
          continue
        }

        // 执行服务刷新
        await this.executeService(service, context)
      }

      // 3. 所有服务执行完成后，触发一次最终合并
      const dataLoader = this.services.get('dataLoader')?.instance
      if (dataLoader && dataLoader.mergeData) {
        console.log('[RefreshCoordinator] 执行最终数据合并（保险）')
        const latestQuotes = dataLayer.getAllQuotes()
        const quoteMap = new Map(latestQuotes.map((q) => [q.code, q]))
      }

      // 4. 强制刷新视图
      this.forceRender()

      const duration = Date.now() - startTime
      console.log(`[RefreshCoordinator] ✅ 所有服务执行完成，总耗时 ${duration}ms`)

      // 5. 发送完成事件
      const success = context.errors.size === 0

      EventManager.emit(AppEvents.REFRESH.FULL_COMPLETE, {
        type: 'full',
        success,
        duration,
        timestamp: Date.now(),
        errors: Array.from(context.errors.entries()),
      })

      EventManager.emit(AppEvents.REFRESH.COMPLETE, {
        type: 'full',
        success,
        duration,
        timestamp: Date.now(),
      })

      // 6. 额外发送各模块的更新事件
      EventManager.emit('data:all-refreshed', {
        timestamp: Date.now(),
        type: 'full',
      })
    } catch (error) {
      console.error('[RefreshCoordinator] 刷新异常:', error)
    } finally {
      this.isRefreshing = false
      this.currentContext = null
      if (this.overallTimeout) {
        clearTimeout(this.overallTimeout)
      }
      console.log(`[RefreshCoordinator] ========== 刷新结束 ==========`)
    }
    // 在 finally 中清理过期的记录
    setTimeout(() => {
      this.pendingRequests.delete(requestKey)
    }, this.REQUEST_COOLDOWN + 1000)
  }

  /**
   * 执行单个服务
   */
  private async executeService(service: Service, context: RefreshContext) {
    const methodName = service.fullMethod
    if (!methodName) {
      console.log(`[RefreshCoordinator] ${service.name} 没有刷新方法，跳过`)
      return
    }

    const method = service.instance[methodName]
    if (typeof method !== 'function') {
      console.warn(`[RefreshCoordinator] ${service.name}.${methodName} 不是函数，尝试查找替代方法`)

      // 尝试查找可能的替代方法名
      const possibleMethods = [methodName, 'runUpdate', 'fullUpdate', 'update', 'sync']

      let found = false
      for (const altMethod of possibleMethods) {
        if (typeof service.instance[altMethod] === 'function') {
          console.log(`[RefreshCoordinator] 找到替代方法: ${service.name}.${altMethod}`)
          await this.executeMethod(service.instance, altMethod, service, context)
          found = true
          break
        }
      }

      if (!found) {
        console.warn(`[RefreshCoordinator] ${service.name} 没有可用的刷新方法，跳过`)
      }
      return
    }

    await this.executeMethod(service.instance, methodName, service, context)
  }

  private async executeMethod(
    instance: any,
    methodName: string,
    service: Service,
    context: RefreshContext,
  ) {
    console.log(`[RefreshCoordinator] 执行 ${service.name}.${methodName}...`)
    const serviceStart = Date.now()

    try {
      // 添加超时控制
      const timeoutPromise = new Promise((_, reject) => {
        setTimeout(() => reject(new Error(`${service.name}.${methodName} 执行超时`)), 30000)
      })

      const result = await Promise.race([instance[methodName].call(instance), timeoutPromise])

      const duration = Date.now() - serviceStart
      context.results.set(service.name, result)

      console.log(`[RefreshCoordinator] ✅ ${service.name} 完成，耗时 ${duration}ms`)

      if (service.syncMethod && instance[service.syncMethod]) {
        await instance[service.syncMethod].call(instance)
      }
    } catch (error) {
      const duration = Date.now() - serviceStart
      console.error(`[RefreshCoordinator] ❌ ${service.name} 失败，耗时 ${duration}ms:`, error)
      context.errors.set(service.name, error as Error)
    }
  }

  /**
   * 检查服务的依赖是否都成功了
   */
  private checkDependencies(service: Service, context: RefreshContext): boolean {
    if (!service.dependsOn || service.dependsOn.length === 0) {
      return true
    }

    for (const depName of service.dependsOn) {
      // 如果依赖服务有错误，返回 false
      if (context.errors.has(depName)) {
        return false
      }
      // 如果依赖服务没有执行（比如没有注册），也返回 false
      if (!context.results.has(depName) && !this.services.has(depName)) {
        return false
      }
    }

    return true
  }

  /**
   * 强制刷新视图
   */
  private forceRender() {
    // 触发 Vue 响应式更新
    if ((window as any).Renderer) {
      requestAnimationFrame(() => {
        ;(window as any).Renderer.renderTable?.()
      })
    }

    // 触发数据更新事件
    EventManager.emit('data:force-refresh', {
      timestamp: Date.now(),
    })
  }

  /**
   * 获取刷新状态
   */
  getStatus() {
    return {
      isRefreshing: this.isRefreshing,
      currentContext: this.currentContext
        ? {
            type: this.currentContext.type,
            startTime: this.currentContext.startTime,
            elapsed: Date.now() - this.currentContext.startTime,
            successCount: this.currentContext.results.size,
            errorCount: this.currentContext.errors.size,
          }
        : null,
      registeredServices: Array.from(this.services.keys()),
    }
  }

  /**
   * 手动触发刷新（供外部调用）
   */
  async manualRefresh(): Promise<boolean> {
    // 如果已经在刷新中，返回 false
    if (this.isRefreshing) {
      console.log('[RefreshCoordinator] 刷新进行中，忽略手动刷新请求')
      return false
    }

    // 直接执行刷新，不通过事件
    return new Promise((resolve) => {
      const onComplete = (data: any) => {
        EventManager.off(AppEvents.REFRESH.COMPLETE, onComplete)
        resolve(data.success)
      }

      EventManager.on(AppEvents.REFRESH.COMPLETE, onComplete)

      // 直接调用 executeRefresh
      this.executeRefresh('full', { source: 'manual', timestamp: Date.now() }).catch((error) => {
        console.error('[RefreshCoordinator] 手动刷新失败:', error)
        EventManager.off(AppEvents.REFRESH.COMPLETE, onComplete)
        resolve(false)
      })

      // 超时保护
      setTimeout(() => {
        EventManager.off(AppEvents.REFRESH.COMPLETE, onComplete)
        resolve(false)
      }, 30000)
    })
  }

  /**
   * 重置
   */
  reset() {
    this.isRefreshing = false
    this.currentContext = null
    console.log('[RefreshCoordinator] 已重置')
  }
}

// 导出单例
export const refreshCoordinator = new RefreshCoordinator()

if (typeof window !== 'undefined') {
  ;(window as any).refreshCoordinator = refreshCoordinator
}
