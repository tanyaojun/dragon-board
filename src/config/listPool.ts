// src/config/listPool.ts
/**
 * 行情列表池来源配置（2026-09-21 池源替换，spec:
 * docs/superpowers/specs/2026-09-21-frontend-pool-frame-alignment-design.md）
 */
export const LIST_POOL_SOURCE_MODE: 'frame-pool' | 'hotlist-merged' = 'frame-pool'

/** 新帧槽探测最小间隔：帧槽 30min 闭合，1min 探测延迟足够，且避免 10s 行情刷新链打后端 */
export const FRAME_POOL_PROBE_INTERVAL_MS = 60_000

/** 单帧股票行读取上限：实测自治帧池 240-250 行，500 为安全余量 */
export const FRAME_POOL_ROW_LIMIT = 500
