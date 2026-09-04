// src/services/theme/themeSortConfig.ts
// 题材列表排序配置：字段白名单、用户 spec 归一化、确定性比较器与 localStorage 持久化。
// 排序规则由用户在界面配置（ThemeSortControl），ThemeFacade.getHotThemes 全消费方统一应用；
// 缺失/非有限值恒排尾部（不伪装 0），补位默认键保证同值顺序稳定。

import { STORAGE_KEYS } from '@/config/storage'

export const THEME_SORT_FIELDS = [
  'heatScore',
  'ztCount',
  'momentumScore',
  'mainNetInflow',
  'volumeRatio',
  'fundScore',
] as const

export type ThemeSortField = (typeof THEME_SORT_FIELDS)[number]
export type ThemeSortDirection = 'asc' | 'desc'

export interface ThemeSortStep {
  field: ThemeSortField
  direction: ThemeSortDirection
}

export type ThemeSortSpec = ThemeSortStep[]

export const THEME_SORT_MAX_STEPS = 3

export const THEME_SORT_FIELD_LABELS: Record<ThemeSortField, string> = {
  heatScore: '热度',
  ztCount: '涨停',
  momentumScore: '动量',
  mainNetInflow: '主力净额',
  volumeRatio: '量比',
  fundScore: '资金分',
}

// 未配置时的统一口径：热度 → 涨停 → 动量，全部降序
export const DEFAULT_THEME_SORT_SPEC: ThemeSortSpec = [
  { field: 'heatScore', direction: 'desc' },
  { field: 'ztCount', direction: 'desc' },
  { field: 'momentumScore', direction: 'desc' },
]

const FIELD_SET = new Set<string>(THEME_SORT_FIELDS)

function isThemeSortField(value: unknown): value is ThemeSortField {
  return typeof value === 'string' && FIELD_SET.has(value)
}

function isThemeSortDirection(value: unknown): value is ThemeSortDirection {
  return value === 'asc' || value === 'desc'
}

/** 归一化任意输入为合法 spec：剔除非法步骤、同字段取首个、截断到上限；空/非法回退默认。 */
export function normalizeThemeSortSpec(input: unknown): ThemeSortSpec {
  if (!Array.isArray(input)) return [...DEFAULT_THEME_SORT_SPEC]

  const steps: ThemeSortSpec = []
  const seen = new Set<ThemeSortField>()
  for (const raw of input) {
    if (steps.length >= THEME_SORT_MAX_STEPS) break
    const field = (raw as ThemeSortStep | null)?.field
    const direction = (raw as ThemeSortStep | null)?.direction
    if (!isThemeSortField(field) || !isThemeSortDirection(direction) || seen.has(field)) continue
    seen.add(field)
    steps.push({ field, direction })
  }
  return steps.length > 0 ? steps : [...DEFAULT_THEME_SORT_SPEC]
}

function sortValue(record: Partial<Record<ThemeSortField, number | null>>, field: ThemeSortField): number | null {
  const value = record[field]
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

/** 用户 spec 之后按默认键序补位（跳过已用字段），保证同值顺序完全确定。 */
function effectiveSteps(spec: ThemeSortSpec): ThemeSortStep[] {
  const used = new Set(spec.map((step) => step.field))
  const fillers = DEFAULT_THEME_SORT_SPEC.filter((step) => !used.has(step.field))
  return [...spec, ...fillers]
}

/**
 * 确定性比较器：按 spec 键序比较；null/非有限值恒排尾部（与方向无关，缺失不伪装 0）；
 * spec 键全相同或缺失时按补位默认键决出先后。
 */
export function compareThemesBySpec(
  a: Partial<Record<ThemeSortField, number | null>>,
  b: Partial<Record<ThemeSortField, number | null>>,
  spec: ThemeSortSpec,
): number {
  for (const { field, direction } of effectiveSteps(spec)) {
    const va = sortValue(a, field)
    const vb = sortValue(b, field)
    // 缺失恒排尾：一方缺失即分出先后，双方缺失则继续看下一键
    if (va === null && vb === null) continue
    if (va === null) return 1
    if (vb === null) return -1
    if (va !== vb) return direction === 'desc' ? vb - va : va - vb
  }
  return 0
}

const THEME_SORT_STORAGE_KEY = STORAGE_KEYS.THEME_SORT

function canUseStorage(): boolean {
  return typeof localStorage !== 'undefined'
}

/**
 * 排序配置存取：运行时缓存 + localStorage 持久化（可选），服务层不依赖 Pinia；
 * 模式与 StockHotnessConfigService 一致。持久化失败静默降级为内存配置。
 */
export class ThemeSortConfigStore {
  private runtimeSpec: ThemeSortSpec = [...DEFAULT_THEME_SORT_SPEC]

  constructor() {
    this.runtimeSpec = this.load()
  }

  getSpec(): ThemeSortSpec {
    return this.runtimeSpec.map((step) => ({ ...step }))
  }

  save(spec: unknown): ThemeSortSpec {
    this.runtimeSpec = normalizeThemeSortSpec(spec)
    if (canUseStorage()) {
      try {
        localStorage.setItem(THEME_SORT_STORAGE_KEY, JSON.stringify(this.runtimeSpec))
      } catch (error) {
        console.error('[ThemeSortConfig] 保存排序配置失败:', error)
      }
    }
    return this.getSpec()
  }

  reset(): ThemeSortSpec {
    // 恢复默认时清除持久化 key（不固化当时的默认值），未来默认口径演进可自然生效
    this.runtimeSpec = [...DEFAULT_THEME_SORT_SPEC]
    if (canUseStorage()) {
      try {
        localStorage.removeItem(THEME_SORT_STORAGE_KEY)
      } catch (error) {
        console.error('[ThemeSortConfig] 清除排序配置失败:', error)
      }
    }
    return this.getSpec()
  }

  private load(): ThemeSortSpec {
    if (!canUseStorage()) return [...DEFAULT_THEME_SORT_SPEC]
    try {
      const raw = localStorage.getItem(THEME_SORT_STORAGE_KEY)
      if (!raw) return [...DEFAULT_THEME_SORT_SPEC]
      return normalizeThemeSortSpec(JSON.parse(raw))
    } catch (error) {
      console.error('[ThemeSortConfig] 加载排序配置失败，回退默认配置:', error)
      return [...DEFAULT_THEME_SORT_SPEC]
    }
  }
}

export const themeSortConfigStore = new ThemeSortConfigStore()
