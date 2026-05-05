import { themeMapping } from '@/services/ThemeDataService'

export const themeRepository = {
  loadThemeBase: () => themeMapping.load?.(),
  isThemeBaseLoaded: () => themeMapping.isLoaded?.() || false,
  getThemes: () => themeMapping.getAllThemes(),
  refreshThemeBase: () => themeMapping.forceRefresh?.(),
  getThemeBaseStatus: () => themeMapping.getLoadStatus?.(),
  getTheme: (themeId: string) => themeMapping.getTheme(themeId),
  getThemeStocks: (themeId: string) => themeMapping.getThemeStocks(themeId),
  getStockThemes: (code: string) => themeMapping.getStockThemes(code),
  getStockTags: (code: string) => themeMapping.getStockTagsWithReason?.(code) || [],
  getStockReason: (code: string) => themeMapping.getStockReason?.(code) || '',
  clearCache: () => themeMapping.clearCache?.(),
}
