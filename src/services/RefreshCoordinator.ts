// src/services/RefreshCoordinator.ts
// 统一全量刷新协调器：数据 -> 题材 -> 龙息 -> 真龙复盘 -> 算法

import { EventManager } from '../utils/eventManager'
import { AppEvents } from '../types'

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
  type: 'full'
  startTime: number
  requestData: any
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
      syncMethod: 'mergeData',
    },
    {
      name: 'sectorAnalyzer',
      priority: 20,
      fullMethod: 'runUpdate',
      syncMethod: 'syncData',
      dependsOn: ['dataLoader'],
    },
    {
      name: 'dragonBreathAnalyzer',
      priority: 30,
      fullMethod: 'runFullUpdate',
      syncMethod: 'syncData',
      dependsOn: ['dataLoader', 'sectorAnalyzer'],
    },
    {
      name: 'dragonReviewService',
      priority: 40,
      fullMethod: 'runFullUpdate',
      syncMethod: 'syncData',
      dependsOn: ['dataLoader', 'sectorAnalyzer', 'dragonBreathAnalyzer'],
    },
    {
      name: 'algorithmManager',
      priority: 50,
      fullMethod: 'runFullUpdate',
      syncMethod: 'syncData',
      dependsOn: ['dragonReviewService', 'sectorAnalyzer'],
    },
  ]

  constructor() {
    this.setupListeners()
    this.scheduleRegistration()
  }

  private setupListeners(): void {
    EventManager.on(AppEvents.REFRESH.FULL_REQUESTED, async (data: any) => {
      await this.executeRefresh('full', { source: 'event', ...(data || {}) })
    })

    EventManager.on(AppEvents.REFRESH.MANUAL_REQUESTED, async (data: any) => {
      await this.executeRefresh('full', { source: 'manual', ...(data || {}) })
    })
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

  private shouldThrottle(type: 'full', requestData: any): boolean {
    const requestKey = `${type}:${requestData?.source || 'unknown'}`
    const now = Date.now()
    const last = this.pendingRequests.get(requestKey) || 0

    if (now - last < this.REQUEST_COOLDOWN) {
      return true
    }

    this.pendingRequests.set(requestKey, now)
    return false
  }

  private async executeRefresh(type: 'full', requestData: any = {}): Promise<boolean> {
    if (this.isRefreshing) {
      return false
    }

    if (this.shouldThrottle(type, requestData)) {
      return false
    }

    this.isRefreshing = true
    this.currentContext = {
      type,
      startTime: Date.now(),
      requestData,
      results: new Map(),
      errors: new Map(),
    }

    EventManager.emit(AppEvents.REFRESH.STARTED, {
      type,
      requestData,
      timestamp: this.currentContext.startTime,
    })

    try {
      const services = this.getSortedServices()
      for (const service of services) {
        await this.executeServiceRefresh(service)
      }

      this.forceRender()

      const payload = {
        success: this.currentContext.errors.size === 0,
        type,
        duration: Date.now() - this.currentContext.startTime,
        results: Object.fromEntries(this.currentContext.results),
        errors: Object.fromEntries(
          Array.from(this.currentContext.errors.entries()).map(([key, error]) => [key, error.message]),
        ),
      }

      EventManager.emit(AppEvents.REFRESH.FULL_COMPLETE, payload)
      EventManager.emit(AppEvents.REFRESH.COMPLETE, payload)
      return payload.success
    } catch (error) {
      const payload = {
        success: false,
        type,
        error: error instanceof Error ? error.message : String(error),
        timestamp: Date.now(),
      }
      EventManager.emit(AppEvents.REFRESH.FAILED, payload)
      return false
    } finally {
      this.isRefreshing = false
      this.currentContext = null
    }
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
