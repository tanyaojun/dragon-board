// src/services/RefreshCoordinator.ts
// 统一全量刷新协调器：数据 -> 题材 -> 龙息 -> 真龙复盘 -> 算法

import { EventManager } from '../utils/eventManager'
import { AppEvents } from '../types'
import type { RefreshRequest, RefreshRequestResult } from './refresh/types'

interface ServiceDefinition {
  name: string
  priority: number
  fullMethod?: string
  syncMethod?: string
  dependsOn?: string[]
}

interface ServiceEntry extends ServiceDefinition {
  instance: any
}

interface RefreshContext {
  request: RefreshRequest
  startTime: number
  results: Map<string, any>
  errors: Map<string, Error>
}

class RefreshCoordinator {
  private services = new Map<string, ServiceEntry>()
  private isRefreshing = false
  private currentContext: RefreshContext | null = null
  private pendingRequests = new Map<string, number>()
  private registrationTimer: ReturnType<typeof setTimeout> | null = null
  private registered = false
  private readonly REQUEST_COOLDOWN = 5000

  private readonly SERVICE_REGISTRY: ServiceDefinition[] = [
    {
      name: 'dataLoader',
      priority: 10,
      fullMethod: 'runUpdate',
    },
    {
      name: 'themeRuntime',
      priority: 20,
      fullMethod: 'runUpdate',
      syncMethod: 'syncData',
      dependsOn: ['dataLoader'],
    },
    {
      name: 'sectorAnalyzer',
      priority: 21,
      fullMethod: 'runUpdate',
      syncMethod: 'syncData',
      dependsOn: ['themeRuntime'],
    },
    {
      name: 'dragonBreathAnalyzer',
      priority: 30,
      fullMethod: 'runFullUpdate',
      syncMethod: 'syncData',
      dependsOn: ['dataLoader', 'themeRuntime'],
    },
    {
      name: 'dragonReviewService',
      priority: 40,
      fullMethod: 'runFullUpdate',
      syncMethod: 'syncData',
      dependsOn: ['dataLoader', 'themeRuntime', 'dragonBreathAnalyzer'],
    },
    {
      name: 'algorithmManager',
      priority: 50,
      fullMethod: 'runFullUpdate',
      syncMethod: 'syncData',
      dependsOn: ['dragonReviewService', 'themeRuntime'],
    },
  ]

  constructor() {
    this.setupListeners()
    this.scheduleRegistration()
  }

  private setupListeners(): void {
    EventManager.on(AppEvents.REFRESH.FULL_REQUESTED, async (data: any) => {
      await this.forwardLegacyRequest({ source: 'event', trigger: 'event', force: false, ...(data || {}) })
    })

    EventManager.on(AppEvents.REFRESH.MANUAL_REQUESTED, async (data: any) => {
      await this.forwardLegacyRequest({ source: 'manual', trigger: 'manual', force: true, ...(data || {}) })
    })
  }

  private async forwardLegacyRequest(data: any): Promise<void> {
    const manager = typeof window !== 'undefined' ? (window as any).RefreshManager : null
    if (manager?.requestRefresh) {
      if (!manager.getStatus?.().initialized) {
        await manager.requestRefresh({
          kind: 'full',
          source: data?.source || 'event',
          trigger: data?.trigger || 'event',
          force: Boolean(data?.force),
          timestamp: data?.timestamp || Date.now(),
        })
      }
      return
    }

    console.warn('[RefreshCoordinator] 忽略旧刷新事件：RefreshManager 未就绪')
  }

  private scheduleRegistration(): void {
    if (this.registrationTimer) {
      clearTimeout(this.registrationTimer)
    }

    this.registrationTimer = setTimeout(() => {
      this.registerServices()
      this.registrationTimer = null
    }, 1000)
  }

  private resolveServiceFromWindow(name: string): any {
    if (typeof window === 'undefined') return null
    const names = [name]

    names.push(name.replace('Service', ''))
    names.push(name.replace('Analyzer', ''))
    names.push(name.toLowerCase())

    for (const candidate of names) {
      const instance = (window as any)[candidate]
      if (instance) return instance
    }

    return null
  }

  private registerServices(): void {
    const missing: string[] = []

    this.SERVICE_REGISTRY.forEach((definition) => {
      const existing = this.services.get(definition.name)
      if (existing?.instance) return

      const instance = this.resolveServiceFromWindow(definition.name)
      if (instance) {
        this.services.set(definition.name, {
          ...definition,
          instance,
        })
      } else {
        missing.push(definition.name)
      }
    })

    this.registered = true

    if (missing.length) {
      setTimeout(() => this.retryMissingServices(missing), 5000)
    }
  }

  private retryMissingServices(names: string[]): void {
    names.forEach((name) => {
      if (this.services.has(name)) return
      const definition = this.SERVICE_REGISTRY.find((item) => item.name === name)
      const instance = this.resolveServiceFromWindow(name)
      if (definition && instance) {
        this.services.set(name, {
          ...definition,
          instance,
        })
      }
    })
  }

  registerService(name: string, instance: any): void {
    const definition = this.SERVICE_REGISTRY.find((item) => item.name === name)
    if (!definition) {
      return
    }

    this.services.set(name, {
      ...definition,
      instance,
    })
  }

  private getSortedServices(): ServiceEntry[] {
    return Array.from(this.services.values()).sort((left, right) => left.priority - right.priority)
  }

  private dependenciesReady(service: ServiceEntry): boolean {
    if (!service.dependsOn?.length) return true
    if (!this.currentContext) return false

    return service.dependsOn.every((depName) => !this.currentContext!.errors.has(depName))
  }

  private async executeServiceRefresh(service: ServiceEntry): Promise<void> {
    if (!this.currentContext) return
    if (!this.dependenciesReady(service)) {
      this.currentContext.errors.set(
        service.name,
        new Error(`依赖未就绪: ${(service.dependsOn || []).join(', ')}`),
      )
      return
    }

    const { instance, fullMethod, syncMethod } = service
    try {
      let result: any = null
      if (fullMethod && typeof instance?.[fullMethod] === 'function') {
        result = await instance[fullMethod]()
      }

      if (syncMethod && typeof instance?.[syncMethod] === 'function') {
        await instance[syncMethod]()
      }

      this.currentContext.results.set(service.name, result)
    } catch (error) {
      this.currentContext.errors.set(service.name, error as Error)
    }
  }

  private forceRender(): void {
    if (typeof window !== 'undefined' && (window as any).Renderer?.renderTable) {
      requestAnimationFrame(() => {
        ;(window as any).Renderer.renderTable()
      })
    }

    EventManager.emit('data:force-refresh', {
      timestamp: Date.now(),
    })
  }

  private shouldThrottle(request: RefreshRequest): boolean {
    const requestKey = `${request.kind}:${request.source || 'unknown'}`
    const now = Date.now()
    const last = this.pendingRequests.get(requestKey) || 0

    if (now - last < this.REQUEST_COOLDOWN) {
      return true
    }

    this.pendingRequests.set(requestKey, now)
    return false
  }

  async executeRequest(request: RefreshRequest): Promise<RefreshRequestResult> {
    const normalizedRequest: RefreshRequest = {
      kind: 'full',
      source: request.source || 'unknown',
      trigger: request.trigger || 'external',
      force: Boolean(request.force),
      retryCount: request.retryCount,
      timestamp: request.timestamp || Date.now(),
    }
    const startTime = Date.now()

    if (this.isRefreshing) {
      return {
        kind: normalizedRequest.kind,
        source: normalizedRequest.source,
        success: false,
        skipped: false,
        busy: true,
        duration: 0,
        executedTasks: [],
        errors: {},
        reason: 'refresh-busy',
        timestamp: startTime,
      }
    }

    if (this.shouldThrottle(normalizedRequest)) {
      return {
        kind: normalizedRequest.kind,
        source: normalizedRequest.source,
        success: false,
        skipped: true,
        busy: false,
        duration: 0,
        executedTasks: [],
        errors: {},
        reason: 'request-throttled',
        timestamp: startTime,
      }
    }

    this.isRefreshing = true
    this.currentContext = {
      request: normalizedRequest,
      startTime,
      results: new Map(),
      errors: new Map(),
    }

    EventManager.emit(AppEvents.REFRESH.STARTED, {
      type: normalizedRequest.kind,
      requestData: normalizedRequest,
      timestamp: this.currentContext.startTime,
    })

    try {
      const services = this.getSortedServices()
      for (const service of services) {
        await this.executeServiceRefresh(service)
      }

      this.forceRender()

      const payload = {
        kind: normalizedRequest.kind,
        source: normalizedRequest.source,
        success: this.currentContext.errors.size === 0,
        skipped: false,
        busy: false,
        type: normalizedRequest.kind,
        duration: Date.now() - this.currentContext.startTime,
        executedTasks: Array.from(this.currentContext.results.keys()),
        results: Object.fromEntries(this.currentContext.results),
        errors: Object.fromEntries(
          Array.from(this.currentContext.errors.entries()).map(([key, error]) => [key, error.message]),
        ),
        timestamp: Date.now(),
      }

      EventManager.emit(AppEvents.REFRESH.FULL_COMPLETE, payload)
      EventManager.emit(AppEvents.REFRESH.COMPLETE, payload)
      return payload
    } catch (error) {
      const payload = {
        kind: normalizedRequest.kind,
        source: normalizedRequest.source,
        success: false,
        skipped: false,
        busy: false,
        type: normalizedRequest.kind,
        duration: Date.now() - startTime,
        executedTasks: this.currentContext ? Array.from(this.currentContext.results.keys()) : [],
        errors: {
          refresh: error instanceof Error ? error.message : String(error),
        },
        error: error instanceof Error ? error.message : String(error),
        timestamp: Date.now(),
      }
      EventManager.emit(AppEvents.REFRESH.FAILED, payload)
      return payload
    } finally {
      this.isRefreshing = false
      this.currentContext = null
    }
  }

  private async executeRefresh(type: 'full', requestData: any = {}): Promise<boolean> {
    const result = await this.executeRequest({
      kind: type,
      source: requestData?.source || 'unknown',
      trigger: requestData?.trigger || 'event',
      force: Boolean(requestData?.force),
      retryCount: requestData?.retryCount,
      timestamp: requestData?.timestamp,
    })
    return result.success
  }

  async manualRefresh(): Promise<boolean> {
    return this.executeRefresh('full', {
      source: 'manual',
      timestamp: Date.now(),
    })
  }

  getStatus() {
    return {
      isRefreshing: this.isRefreshing,
      currentContext: this.currentContext
        ? {
            type: this.currentContext.request.kind,
            startTime: this.currentContext.startTime,
            elapsed: Date.now() - this.currentContext.startTime,
            successCount: this.currentContext.results.size,
            errorCount: this.currentContext.errors.size,
          }
        : null,
      registeredServices: Array.from(this.services.keys()),
    }
  }

  reset(): void {
    this.isRefreshing = false
    this.currentContext = null
    EventManager.emit(AppEvents.REFRESH.STOPPED, {
      timestamp: Date.now(),
    })
  }
}

export const refreshCoordinator = new RefreshCoordinator()

if (typeof window !== 'undefined') {
  ;(window as any).refreshCoordinator = refreshCoordinator
}
