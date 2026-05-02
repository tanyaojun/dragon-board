export type ApiStatus = "idle" | "loading" | "ok" | "error";

export interface HealthResponse {
  status?: string;
  version?: string;
  [key: string]: unknown;
}

export interface DatasetSummary {
  id: string;
  name?: string;
  source_type?: string;
  sourcePath?: string;
  source_path?: string;
  db_name?: string;
  schema_fingerprint?: string;
  snapshot_count?: number;
  frame_count?: number;
  stock_row_count?: number;
  sector_row_count?: number;
  start_date?: string | null;
  end_date?: string | null;
  snapshot_types?: string[];
  snapshot_types_json?: string;
  created_at?: string;
  [key: string]: unknown;
}

export interface ApiErrorDetail {
  status: number;
  statusText: string;
  message: string;
  body?: unknown;
}

export interface RequestResult<T = unknown> {
  status: ApiStatus;
  data?: T;
  error?: string;
  raw?: unknown;
}

export interface IndexedDbStorePreview {
  name: string;
  keyPath: string | string[] | null;
  autoIncrement: boolean;
  indexes: string[];
  count: number;
  samples: unknown[];
}

export interface IndexedDbPreview {
  dbName: string;
  version: number;
  stores: IndexedDbStorePreview[];
  snapshotLikeRows: number;
  capturedAt: string;
}

export interface ImportPayload {
  sourceType: "indexeddb" | "json" | "leveldb" | "browser_bridge" | "json_bundle";
  sourcePath?: string;
  dbName?: string;
  name: string;
  snapshotTypes?: Array<"quarter_hour" | "half_hour">;
  dryRun?: boolean;
  preview?: IndexedDbPreview | null;
  records?: unknown[];
  options?: {
    dryRun: boolean;
    maxRowsPerStore: number;
  };
}

export interface UploadPayload {
  filename: string;
  name: string;
  content: unknown;
  snapshotTypes?: Array<"quarter_hour" | "half_hour">;
  dryRun?: boolean;
}

export interface RuntimeBridgeRequest {
  dragonBoardUrl: string;
  dbName: string;
  snapshotType: "quarter_hour" | "half_hour";
  limit: number;
  startDate?: string;
  endDate?: string;
  timeoutMs?: number;
}

export type StrategyName =
  | "rank_trend_candidate"
  | "hot_top10"
  | "a_main_only"
  | "b_ignition_only"
  | "a_b_combined";

export interface BacktestRequest {
  datasetId: string;
  strategyName: StrategyName;
  snapshotType: "quarter_hour" | "half_hour";
  randomSeed: number;
  initialCash: number;
  maxPositions: number;
  positionSize: number;
  executionMode: "current_bar" | "next_bar";
  maxHoldingBars: number;
  targetHoldingDays: number;
  takeProfitPct: number;
  stopLossPct: number;
  feeRate: number;
  stampTaxRate: number;
  slippageRate: number;
  enforceT1: boolean;
  useOrderBookPrice: boolean;
  enforceLimitStatus: boolean;
  enforceVolumeLimit: boolean;
  enforceOrderBookQueue: boolean;
  allowPartialFills: boolean;
  volumeParticipationRate: number;
  orderBookParticipationRate: number;
  useIntrabarStops: boolean;
  intrabarAmbiguity: "stop_first" | "take_first";
  momentumPeriods: number[];
  macdFast: number;
  macdSlow: number;
  macdSignal: number;
}

export interface OptimizationRequest {
  datasetId: string;
  strategyName: StrategyName;
  method: "grid" | "random" | "bayesian";
  randomSeed: number;
  objective: "sharpe" | "return" | "max_drawdown" | "win_rate" | "risk_adjusted" | "stability";
  trials: number;
  validationMode: "none" | "auto";
  validationRatio: number;
  validationWarmupBars: number;
  walkForward: {
    enabled: boolean;
    trainWindowDays: number;
    validationWindowDays: number;
    stepDays: number;
    topTrials: number;
  };
  parameterGrid: {
    momentumPeriods: number[][];
    takeProfitPct: number[];
    stopLossPct: number[];
    maxPositions: number[];
  };
}

export interface GoldenValidateRequest {
  datasetId: string;
  caseId: string;
  strict: boolean;
  tolerance: number;
  sampleLimit: number;
}

export interface GoldenImportPayload {
  name?: string;
  caseId?: string;
  datasetId?: string;
  snapshotType?: "quarter_hour" | "half_hour";
  source?: string;
  payload: Record<string, unknown>;
}

export interface ReplayStep {
  time: string;
  code: string;
  name: string;
  action: string;
  reason: string;
  score?: number;
  rank?: number;
  price?: number;
  holdingBars?: number;
  candidateTier?: string;
  stage?: string;
  regime?: string;
}
