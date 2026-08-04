import { apiService } from '../apiService'

type AnalyzePayload = Parameters<typeof apiService.analyzeRankTrend>[0]
export type AnalyzeRankTrendResponse = Awaited<ReturnType<typeof apiService.analyzeRankTrend>>

type Waiter = {
  resolve: (value: AnalyzeRankTrendResponse) => void
  reject: (reason?: unknown) => void
}

let inFlight: Promise<AnalyzeRankTrendResponse> | null = null
let pending: { payload: AnalyzePayload; waiters: Waiter[] } | null = null

function start(payload: AnalyzePayload): Promise<AnalyzeRankTrendResponse> {
  const task = apiService.analyzeRankTrend(payload, { bypassQueue: true })
  inFlight = task
  task.then(
    (result) => {
      inFlight = null
      flushPending(result)
    },
    (error) => {
      inFlight = null
      flushPending(error)
    },
  )
  return task
}

function flushPending(value: AnalyzeRankTrendResponse | unknown): void {
  const next = pending
  pending = null
  if (!next) return
  const nextTask = start(next.payload)
  nextTask.then(
    (result) => next.waiters.forEach((waiter) => waiter.resolve(result)),
    (error) => next.waiters.forEach((waiter) => waiter.reject(error)),
  )
}

/**
 * 全量 analyze 单飞（latest-wins）：同一时刻最多一个 analyze 在飞；
 * 重叠请求合并为最新 payload，前一个完成后只再跑最新一次。
 * 防止刷新循环并发全量 analyze 把后端打满（bypassQueue 只保证不被交互队列饿死，不限制并发）。
 */
export function analyzeRankTrendCoalesced(payload: AnalyzePayload): Promise<AnalyzeRankTrendResponse> {
  if (!inFlight) {
    return start(payload)
  }
  if (!pending) {
    pending = { payload, waiters: [] }
  } else {
    pending.payload = payload // latest-wins：新 payload 取代旧的待运行请求
  }
  return new Promise<AnalyzeRankTrendResponse>((resolve, reject) => {
    pending!.waiters.push({ resolve, reject })
  })
}

/** 清空单飞状态（测试与诊断用；调用方不应在运行中重置）。 */
export function resetAnalyzeCoalescer(): void {
  inFlight = null
  pending = null
}
