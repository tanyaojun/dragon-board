// src/config/storage.ts
// 唯一需要硬编码的地方

export const STORAGE_KEYS = {
  HOTNESS_CONFIG: 'stock_hotness_config',
  THEME_SORT: 'theme_sort_config',
} as const

export type StorageKey = keyof typeof STORAGE_KEYS
