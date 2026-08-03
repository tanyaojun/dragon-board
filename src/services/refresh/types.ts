export type RefreshTaskId =
  | 'dataLoader.full'
  | 'dataLoader.quote'
  | 'dataLoader.ranktrendSignal'
  | 'theme.runtime'
  | 'dragon.breath'
  | 'dragon.review'
  | 'alert.check'
  | 'snapshot.sweep'
  | 'snapshot.backupSync'
  | 'websocket.staleCheck'
  | (string & {})

export type RefreshTaskCategory = 'business' | 'market' | 'derived' | 'storage' | 'realtime'

export type RefreshTaskSource =
  | 'registered'
  | 'scheduler'
  | 'manual'
  | 'event'
  | 'timer'
  | 'external'

export type RefreshVisibilityPolicy = 'run' | 'pause' | 'slow'

export type RefreshResourceKey =
  | 'hotlist-platform'
  | 'quote-http'
  | 'theme-runtime'
  | 'dragon-breath'
  | 'dragon-review'
  | 'ranktrend-signal'
  | 'snapshot-write'
  | (string & {})

export interface RefreshTaskDefinition {
  id: RefreshTaskId
  label: string
  category: RefreshTaskCategory
  owner: string
  /**
   * 单次 runner 执行超时（毫秒）。超时后任务标记失败并复位 running，
   * 下一个调度周期会自然重试；不设置则无超时（保持原语义）。
   * 注意：超时不会中断仍在后台执行的 runner，调用方应保证 runner 幂等。
   */
  timeoutMs?: number | null
  intervalMs?: number | null
  hiddenIntervalMs?: number | null
  enabled?: boolean
  tradingTimeOnly?: boolean
  runWhenHidden?: boolean
  visibilityPolicy?: RefreshVisibilityPolicy
  description?: string
}

export interface RefreshTaskState extends Required<Omit<RefreshTaskDefinition, 'intervalMs'>> {
  intervalMs: number | null
  timeoutMs: number | null
  running: boolean
  lastRunAt: number | null
  lastSuccessAt: number | null
  lastError: string | null
  successCount: number
  failureCount: number
  source: RefreshTaskSource
}

export type RefreshTaskRunner = () => void | Promise<void>

export type RefreshRequestKind = 'full'

export type RefreshRequestTrigger = 'manual' | 'timer' | 'event' | 'external'

export interface RefreshRequest {
  kind: RefreshRequestKind
  source: string
  trigger?: RefreshRequestTrigger
  force?: boolean
  retryCount?: number
  timestamp?: number
}

export interface RefreshRequestResult {
  kind: RefreshRequestKind
  source: string
  success: boolean
  skipped: boolean
  busy: boolean
  duration: number
  executedTasks: string[]
  errors: Record<string, string>
  reason?: string
  timestamp?: number
}

export interface RefreshSchedulerPolicy {
  tradingTimeOnly: boolean
  defaultVisibilityPolicy: RefreshVisibilityPolicy
}
