import type { ThemeRuntimeSnapshot } from './types'

type ThemeRuntimeListener = (snapshot: ThemeRuntimeSnapshot) => void

function clonePlain<T>(value: T): T {
  if (value === null || value === undefined) return value
  if (typeof structuredClone === 'function') return structuredClone(value)
  return JSON.parse(JSON.stringify(value)) as T
}

function cloneSnapshot(snapshot: ThemeRuntimeSnapshot): ThemeRuntimeSnapshot {
  return {
    factors: [...snapshot.factors],
    exposures: {
      byCode: new Map(
        Array.from(snapshot.exposures.byCode.entries()).map(([code, exposures]) => [
          code,
          [...exposures],
        ]),
      ),
      byTheme: new Map(
        Array.from(snapshot.exposures.byTheme.entries()).map(([themeId, exposures]) => [
          themeId,
          [...exposures],
        ]),
      ),
    },
    rotationSummary: clonePlain(snapshot.rotationSummary),
    events: [...snapshot.events],
      correlations: new Map(snapshot.correlations),
      lastUpdate: snapshot.lastUpdate,
      inputSignature: snapshot.inputSignature,
      factorVersion: snapshot.factorVersion,
      eventVersion: snapshot.eventVersion,
      qualitySummary: clonePlain(snapshot.qualitySummary),
      refreshSource: snapshot.refreshSource,
      changedFields: snapshot.changedFields ? [...snapshot.changedFields] : undefined,
    }
}

export function createThemeRuntimeStore(initial?: Partial<ThemeRuntimeSnapshot>) {
  let snapshot: ThemeRuntimeSnapshot = {
    factors: [],
    exposures: {
      byCode: new Map(),
      byTheme: new Map(),
    },
    rotationSummary: null,
    events: [],
    correlations: new Map(),
    lastUpdate: null,
    inputSignature: undefined,
    factorVersion: undefined,
    eventVersion: undefined,
    qualitySummary: undefined,
    refreshSource: undefined,
    changedFields: undefined,
    ...initial,
  }
  const listeners = new Set<ThemeRuntimeListener>()

  function notify() {
    const cloned = cloneSnapshot(snapshot)
    listeners.forEach((listener) => listener(cloned))
  }

  return {
    getSnapshot(): ThemeRuntimeSnapshot {
      return cloneSnapshot(snapshot)
    },

    update(patch: Partial<ThemeRuntimeSnapshot>): ThemeRuntimeSnapshot {
      snapshot = {
        ...snapshot,
        ...patch,
        lastUpdate: patch.lastUpdate ?? Date.now(),
      }
      notify()
      return snapshot
    },

    subscribe(listener: ThemeRuntimeListener): () => void {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },

    clear() {
      snapshot = {
        factors: [],
        exposures: {
          byCode: new Map(),
          byTheme: new Map(),
        },
        rotationSummary: null,
        events: [],
        correlations: new Map(),
        lastUpdate: null,
        inputSignature: undefined,
        factorVersion: undefined,
        eventVersion: undefined,
        qualitySummary: undefined,
        refreshSource: undefined,
        changedFields: undefined,
      }
      notify()
    },
  }
}

export const themeRuntimeStore = createThemeRuntimeStore()
