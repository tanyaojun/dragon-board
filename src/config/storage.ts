// src/config/storage.ts
// 唯一需要硬编码的地方

export const STORAGE_KEYS = {
  ALGORITHM: 'algorithm',
  WEIGHTS: 'algorithm_weights',
  THRESHOLDS: 'algorithm_thresholds',
  HISTORY: 'algorithm_history',
  HOTNESS_CONFIG: 'stock_hotness_config',
} as const

export type StorageKey = keyof typeof STORAGE_KEYS
