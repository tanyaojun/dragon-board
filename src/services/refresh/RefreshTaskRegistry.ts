import type {
  RefreshTaskDefinition,
  RefreshTaskId,
  RefreshTaskSource,
  RefreshTaskState,
  RefreshVisibilityPolicy,
} from './types'

export const REFRESH_TASK_DEFINITIONS: RefreshTaskDefinition[] = [
  {
    id: 'dataLoader.full',
    label: '全量热榜刷新',
    category: 'business',
    owner: 'DataLoaderFacade',
    intervalMs: null,
    tradingTimeOnly: true,
    description: '全量刷新链任务，由 RefreshManager 触发、RefreshCoordinator 执行',
  },
  {
    id: 'dataLoader.quote',
    label: 'HTTP 行情兜底',
    category: 'market',
    owner: 'DataLoaderFacade',
    intervalMs: 30_000,
    hiddenIntervalMs: 120_000,
    tradingTimeOnly: true,
    visibilityPolicy: 'slow',
    description: 'WebSocket 不健康时的 HTTP 行情补偿',
  },
  {
    id: 'dataLoader.ranktrendSignal',
    label: 'RankTrend 信号刷新',
    category: 'derived',
    owner: 'DataLoaderFacade',
    intervalMs: 1_000,
    tradingTimeOnly: false,
    visibilityPolicy: 'run',
    description: '14:45 每日一次 RankTrend 信号检查',
  },
  {
    id: 'theme.runtime',
    label: '题材运行态刷新',
    category: 'derived',
    owner: 'ThemeRuntimeCoordinator',
    intervalMs: 5_000,
    tradingTimeOnly: false,
    visibilityPolicy: 'pause',
    description: '题材轮动运行态刷新',
  },
  {
    id: 'dragon.breath',
    label: '龙息刷新',
    category: 'derived',
    owner: 'DragonBreathAnalyzer',
    intervalMs: 300_000,
    tradingTimeOnly: true,
    visibilityPolicy: 'pause',
  },
  {
    id: 'dragon.review',
    label: '真龙复盘刷新',
    category: 'derived',
    owner: 'DragonReviewService',
    intervalMs: null,
    tradingTimeOnly: true,
  },
  {
    id: 'alert.check',
    label: '预警检查',
    category: 'business',
    owner: 'AlertService',
    intervalMs: 10_000,
    tradingTimeOnly: false,
    visibilityPolicy: 'pause',
  },
  {
    id: 'snapshot.sweep',
    label: '快照槽位扫描',
    category: 'storage',
    owner: 'SnapshotRuntime',
    intervalMs: 1_000,
    tradingTimeOnly: false,
    visibilityPolicy: 'run',
  },
  {
    id: 'snapshot.backupSync',
    label: '快照备份同步',
    category: 'storage',
    owner: 'SnapshotRuntime',
    intervalMs: 300_000,
    tradingTimeOnly: true,
    visibilityPolicy: 'run',
  },
  {
    id: 'websocket.staleCheck',
    label: 'WebSocket 陈旧检查',
    category: 'realtime',
    owner: 'WebSocketService',
    intervalMs: 500,
    hiddenIntervalMs: 5_000,
    tradingTimeOnly: false,
    visibilityPolicy: 'slow',
  },
  {
    id: 'hotStockEvent.monitor',
    label: '异动雷达刷新',
    category: 'business',
    owner: 'HotStockEventMonitorService',
    intervalMs: 30_000,
    tradingTimeOnly: false,
    visibilityPolicy: 'pause',
    description: '异动雷达面板或飞书推送启用时轮询选股通异动数据',
  },
]

export class RefreshTaskRegistry {
  private tasks = new Map<RefreshTaskId, RefreshTaskState>()

  constructor(private readonly now: () => number = () => Date.now()) {}

  register(definition: RefreshTaskDefinition): RefreshTaskState {
    const existing = this.tasks.get(definition.id)
    const explicitRunWhenHidden = definition.runWhenHidden ?? existing?.runWhenHidden
    const visibilityPolicy =
      definition.visibilityPolicy ??
      (definition.runWhenHidden !== undefined ? undefined : existing?.visibilityPolicy) ??
      (explicitRunWhenHidden ? 'run' : 'pause')
    const runWhenHidden = explicitRunWhenHidden ?? visibilityPolicy !== 'pause'
    const task: RefreshTaskState = {
      id: definition.id,
      label: definition.label,
      category: definition.category,
      owner: definition.owner,
      description: definition.description ?? '',
      intervalMs: definition.intervalMs ?? null,
      hiddenIntervalMs: definition.hiddenIntervalMs ?? existing?.hiddenIntervalMs ?? null,
      enabled: definition.enabled ?? existing?.enabled ?? true,
      tradingTimeOnly: definition.tradingTimeOnly ?? existing?.tradingTimeOnly ?? true,
      runWhenHidden,
      visibilityPolicy,
      running: existing?.running ?? false,
      lastRunAt: existing?.lastRunAt ?? null,
      lastSuccessAt: existing?.lastSuccessAt ?? null,
      lastError: existing?.lastError ?? null,
      successCount: existing?.successCount ?? 0,
      failureCount: existing?.failureCount ?? 0,
      source: existing?.source ?? 'registered',
    }

    this.tasks.set(definition.id, task)
    return { ...task }
  }

  registerMany(definitions: RefreshTaskDefinition[]): void {
    definitions.forEach((definition) => this.register(definition))
  }

  listTasks(): RefreshTaskState[] {
    return Array.from(this.tasks.values()).map((task) => ({ ...task }))
  }

  getTask(id: RefreshTaskId): RefreshTaskState | null {
    const task = this.tasks.get(id)
    return task ? { ...task } : null
  }

  setEnabled(id: RefreshTaskId, enabled: boolean): boolean {
    const task = this.tasks.get(id)
    if (!task) return false
    task.enabled = enabled
    if (!enabled) {
      task.running = false
    }
    return true
  }

  setVisibilityPolicy(id: RefreshTaskId, visibilityPolicy: RefreshVisibilityPolicy): boolean {
    const task = this.tasks.get(id)
    if (!task) return false
    task.visibilityPolicy = visibilityPolicy
    task.runWhenHidden = visibilityPolicy !== 'pause'
    return true
  }

  markStarted(id: RefreshTaskId, source: RefreshTaskSource = 'scheduler'): boolean {
    const task = this.tasks.get(id)
    if (!task) return false
    task.running = true
    task.lastRunAt = this.now()
    task.lastError = null
    task.source = source
    return true
  }

  markSuccess(id: RefreshTaskId, source: RefreshTaskSource = 'scheduler'): boolean {
    const task = this.tasks.get(id)
    if (!task) return false
    task.running = false
    task.lastSuccessAt = this.now()
    task.lastError = null
    task.successCount += 1
    task.source = source
    return true
  }

  markFailure(
    id: RefreshTaskId,
    error: unknown,
    source: RefreshTaskSource = 'scheduler',
  ): boolean {
    const task = this.tasks.get(id)
    if (!task) return false
    task.running = false
    task.lastError = error instanceof Error ? error.message : String(error)
    task.failureCount += 1
    task.source = source
    return true
  }

  resetRuntimeState(): void {
    this.tasks.forEach((task) => {
      task.running = false
      task.lastRunAt = null
      task.lastSuccessAt = null
      task.lastError = null
      task.successCount = 0
      task.failureCount = 0
      task.source = 'registered'
    })
  }
}

export function createRefreshTaskRegistry(): RefreshTaskRegistry {
  const registry = new RefreshTaskRegistry()
  registry.registerMany(REFRESH_TASK_DEFINITIONS)
  return registry
}
