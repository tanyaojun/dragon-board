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
  intervalMs?: number | null
  enabled?: boolean
  tradingTimeOnly?: boolean
  runWhenHidden?: boolean
  description?: string
}

export interface RefreshTaskState extends Required<Omit<RefreshTaskDefinition, 'intervalMs'>> {
  intervalMs: number | null
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
