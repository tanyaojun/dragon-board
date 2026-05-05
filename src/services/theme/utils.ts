export function toFiniteNumber(value: unknown, fallback = 0): number {
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric : fallback
}

export function hasFiniteNumber(value: unknown): boolean {
  return Number.isFinite(Number(value))
}

export function clamp(value: number, min = 0, max = 100): number {
  return Math.max(min, Math.min(max, value))
}

export function round(value: number, digits = 0): number {
  const factor = 10 ** digits
  return Math.round(value * factor) / factor
}

export function dedupeByKey<T>(items: T[], keyFn: (item: T) => string): T[] {
  const seen = new Set<string>()
  return items.filter((item) => {
    const key = keyFn(item)
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}
