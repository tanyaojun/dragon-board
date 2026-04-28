const DEBUG_LOG_KEY = 'dragon-board:debug-logs'

function isBrowserDebugEnabled(): boolean {
  if (typeof window === 'undefined') return false

  try {
    const params = new URLSearchParams(window.location.search)
    const queryEnabled = params.get('debugLogs') === '1' || params.get('debug') === '1'
    const storageValue = window.localStorage.getItem(DEBUG_LOG_KEY)

    return queryEnabled || storageValue === '1' || storageValue === 'true'
  } catch {
    return false
  }
}

export function isDebugLogEnabled(): boolean {
  return isBrowserDebugEnabled()
}

export function debugLog(...args: unknown[]): void {
  if (isDebugLogEnabled()) {
    console.log(...args)
  }
}

