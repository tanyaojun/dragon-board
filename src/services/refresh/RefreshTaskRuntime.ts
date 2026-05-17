import { isTradingTime } from '@/utils/time'
import { RefreshScheduler } from './RefreshScheduler'
import { createRefreshTaskRegistry } from './RefreshTaskRegistry'

export const refreshTaskRegistry = createRefreshTaskRegistry()

export const refreshScheduler = new RefreshScheduler(refreshTaskRegistry, {
  isTradingTime: () => isTradingTime(),
})

export function resetRefreshTaskRuntime(): void {
  refreshScheduler.stopAll()
  refreshScheduler.setPolicy({
    tradingTimeOnly: true,
    defaultVisibilityPolicy: 'pause',
  })
  refreshTaskRegistry.resetRuntimeState()
}
