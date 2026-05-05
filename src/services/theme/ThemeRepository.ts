import { themeMapping } from '@/services/ThemeDataService'

export const themeRepository = {
  loadThemeBase: () => themeMapping.load?.(),
  isThemeBaseLoaded: () => themeMapping.isLoaded?.() || false,
  getThemes: () => themeMapping.getAllThemes(),
  refreshThemeBase: () => themeMapping.forceRefresh?.(),
  getThemeBaseStatus: () => themeMapping.getLoadStatus?.(),

  /** @deprecated Use loadThemeBase(). */
  load: () => themeMapping.load?.(),
  /** @deprecated Use isThemeBaseLoaded(). */
  isLoaded: () => themeMapping.isLoaded?.() || false,
  /** @deprecated Use getThemes(). */
  getAllThemes: () => themeMapping.getAllThemes(),
  getTheme: (themeId: string) => themeMapping.getTheme(themeId),
  getThemeStocks: (themeId: string) => themeMapping.getThemeStocks(themeId),
  getStockThemes: (code: string) => themeMapping.getStockThemes(code),
  getStockTags: (code: string) => themeMapping.getStockTagsWithReason?.(code) || [],
  getStockReason: (code: string) => themeMapping.getStockReason?.(code) || '',
  /** @deprecated Use refreshThemeBase(). */
  forceRefresh: () => themeMapping.forceRefresh?.(),
  clearCache: () => themeMapping.clearCache?.(),
}
