/**
 * L1 桥接层的最小接口与类型（避免与 HotStockEventMonitorService 形成模块环）。
 */
import type { HotStockAbnormalEvent } from './hotStockEventTypes'

export interface HotStockEventMonitorServiceLike {
  acceptDerivedEvents(events: HotStockAbnormalEvent[]): void
}
