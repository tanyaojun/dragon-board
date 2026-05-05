import { themeMapping } from '@/services/ThemeDataService'

export const themeRepository = {
  load: () => themeMapping.load?.(),
  isLoaded: () => themeMapping.isLoaded?.() || false,
  getAllThemes: () => themeMapping.getAllThemes(),
  getTheme: (themeId: string) => themeMapping.getTheme(themeId),
  getThemeStocks: (themeId: string) => themeMapping.getThemeStocks(themeId),
  getStockThemes: (code: string) => themeMapping.getStockThemes(code),
  getStockTags: (code: string) => themeMapping.getStockTagsWithReason?.(code) || [],
  getStockReason: (code: string) => themeMapping.getStockReason?.(code) || '',
  forceRefresh: () => themeMapping.forceRefresh?.(),
  clearCache: () => themeMapping.clearCache?.(),
}
