import type { SnapshotQueryOptions, SnapshotCaptureMode, SnapshotFormalReadPolicy } from './types'

export const FORMAL_SNAPSHOT_CAPTURE_MODES: SnapshotCaptureMode[] = ['real_time', 'delayed']

// 正式分析与恢复/排障读取必须走同一策略入口，
// 避免消费方各自散写 captureMode 过滤后再逐步跑偏。
export const FORMAL_SNAPSHOT_READ_POLICY: SnapshotFormalReadPolicy = {
  mode: 'formal_analysis',
  allowedCaptureModes: [...FORMAL_SNAPSHOT_CAPTURE_MODES],
  excludeRestored: true,
  description: '正式样本默认只读取 real_time / delayed，并显式排除 restored/manual；restored/manual 仅用于恢复、容灾或人工核查。',
}

export function applyFormalSnapshotReadPolicy(options: SnapshotQueryOptions = {}): SnapshotQueryOptions {
  const requestedModes = Array.isArray(options.allowedCaptureModes) ? options.allowedCaptureModes : []
  const filteredModes = requestedModes.filter((mode) => FORMAL_SNAPSHOT_CAPTURE_MODES.includes(mode))

  return {
    ...options,
    allowedCaptureModes: filteredModes.length > 0 ? filteredModes : [...FORMAL_SNAPSHOT_CAPTURE_MODES],
    excludeRestored: true,
  }
}

// 恢复/容灾路径显式放开 restored，避免“只是想排障”却仍然读不到恢复样本。
export function createRecoverySnapshotReadOptions(options: SnapshotQueryOptions = {}): SnapshotQueryOptions {
  return {
    ...options,
    allowedCaptureModes: ['real_time', 'delayed', 'restored'],
    excludeRestored: false,
  }
}
