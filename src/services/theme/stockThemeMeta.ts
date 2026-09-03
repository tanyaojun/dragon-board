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
  /** 主题材 heatLevel 相对分（0-100）；null = 热度缺失或无题材，不伪装 0 */
  themeHeat: number | null
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

export function deriveThemeHeatLevel(score: number | null | undefined): string {
  // JS 陷阱（评审 H-2d）：hasFiniteNumber(null) === true（Number(null) === 0），
  // 旧写法会把缺失热度判成 0 度"冰"；必须显式 null/undefined 判断，缺失返回 ''。
  if (score == null || typeof score !== 'number' || !Number.isFinite(score)) return ''
  if (score >= 80) return '热门'
  if (score >= 60) return '活跃'
  if (score >= 40) return '温'
  if (score >= 20) return '冷'
  return '冰'
}

export function deriveThemeHeatMeta(score: number): { level: string; icon: string; color: string } {
  if (score >= 80) return { level: '热门', icon: '🔥', color: '#ff4757' }
  if (score >= 60) return { level: '活跃', icon: '⚡', color: '#f39c12' }
  if (score >= 40) return { level: '温', icon: '🌟', color: '#3498db' }
  if (score >= 20) return { level: '冷', icon: '❄️', color: '#7f8c8d' }
  return { level: '冰', icon: '🧊', color: '#2c3e50' }
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
    return { mainTheme: undefined, themeHeat: null, themeLevel: '' }
  }

  // 同一陷阱：hasFiniteNumber(null) === true 会让 null 经 normalizeThemeHeatScore
  // 伪装成 0，必须显式守卫，缺失热度返回 null 而非 0。
  const themeHeat =
    primaryTheme.heatScore != null &&
    typeof primaryTheme.heatScore === 'number' &&
    Number.isFinite(primaryTheme.heatScore)
      ? normalizeThemeHeatScore(primaryTheme.heatScore)
      : null
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
