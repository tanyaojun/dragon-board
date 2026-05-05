import { hasFiniteNumber, toFiniteNumber } from './utils'

export interface StockThemeLike {
  id?: string
  name?: string
  heatScore?: number
  heatLevel?: string
  correlation?: number
  source?: string
}

export interface StockThemeSnapshot {
  mainTheme?: string
  themeHeat: number
  themeLevel: string
}

function normalizeThemeHeatScore(value: unknown): number {
  if (!hasFiniteNumber(value)) return 0
  return Math.max(0, Math.round(toFiniteNumber(value) * 10) / 10)
}

function normalizeThemeCorrelation(value: unknown): number {
  if (!hasFiniteNumber(value)) return 0
  return Math.max(0, Math.round(toFiniteNumber(value) * 1000) / 1000)
}

function themeSourceWeight(source?: string): number {
  if (source === 'static') return 2
  if (source === 'realtime') return 1
  return 0
}

export function deriveThemeHeatLevel(score: number): string {
  if (score >= 80) return '热门'
  if (score >= 60) return '活跃'
  if (score >= 40) return '温'
  if (score >= 20) return '冷'
  return '冰'
}

/**
 * 个股题材列表需要先按“谁更像主战题材”排序，再决定主题材字段。
 */
export function sortStockThemes<T extends StockThemeLike>(themes: T[]): T[] {
  return [...themes].sort((a, b) => {
    const heatDiff = normalizeThemeHeatScore(b.heatScore) - normalizeThemeHeatScore(a.heatScore)
    if (heatDiff !== 0) return heatDiff

    const correlationDiff =
      normalizeThemeCorrelation(b.correlation) - normalizeThemeCorrelation(a.correlation)
    if (correlationDiff !== 0) return correlationDiff

    const sourceDiff = themeSourceWeight(b.source) - themeSourceWeight(a.source)
    if (sourceDiff !== 0) return sourceDiff

    return String(a.name || '').localeCompare(String(b.name || ''), 'zh-CN')
  })
}

export function resolvePrimaryStockTheme(themes: StockThemeLike[]): StockThemeSnapshot {
  const [primaryTheme] = sortStockThemes(themes).filter((theme) => String(theme?.name || '').trim())
  if (!primaryTheme) {
    return {
      mainTheme: undefined,
      themeHeat: 0,
      themeLevel: '冷',
    }
  }

  const themeHeat = normalizeThemeHeatScore(primaryTheme.heatScore)
  return {
    mainTheme: String(primaryTheme.name || '').trim() || undefined,
    themeHeat,
    themeLevel: primaryTheme.heatLevel || deriveThemeHeatLevel(themeHeat),
  }
}

/**
 * 题材热度变化要能触发同步，不能只比较题材 id。
 */
export function buildStockThemeSignature(themes: StockThemeLike[]): string {
  return sortStockThemes(themes)
    .map((theme) => {
      const id = String(theme.id || theme.name || '').trim()
      const name = String(theme.name || '').trim()
      const heatScore = normalizeThemeHeatScore(theme.heatScore).toFixed(1)
      const heatLevel = String(theme.heatLevel || '')
      const correlation = normalizeThemeCorrelation(theme.correlation).toFixed(3)
      const source = String(theme.source || '')
      return [id, name, heatScore, heatLevel, correlation, source].join('|')
    })
    .join('||')
}
