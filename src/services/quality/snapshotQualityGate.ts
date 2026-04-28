export {
  evaluateSnapshotQualityGate,
  normalizeSnapshotQualityGateOptions,
  resolveSnapshotFeatureCoverage,
  resolveSnapshotFormalValidationCoverage,
  resolveSnapshotSeriesFeatureCoverage,
  resolveSnapshotTimestamp,
  resolveSnapshotVersion,
} from '../snapshot/snapshotQualityGate'

export type {
  SnapshotQualityGateOptions,
  SnapshotQualityGateResult,
  SnapshotSeriesItem,
} from '../snapshot/snapshotQualityGate'

export type SnapshotFeatureCoverage = 'full' | 'partial'
