export type ApiStatus = "idle" | "loading" | "running" | "ok" | "error";

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
  sourceType: "sqlite_snapshots" | "indexeddb" | "json" | "leveldb" | "browser_bridge" | "json_bundle";
  sourcePath?: string;
  sourceDatasetId?: string;
  dbName?: string;
  name: string;
  snapshotTypes?: Array<"quarter_hour" | "half_hour">;
  startDate?: string;
  endDate?: string;
  maxSnapshots?: number;
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
  | "a_b_combined"
  | "theme_rotation"
  | "leader_theme_confirmation"
  | "hotlist_theme_confluence";

export interface ThemeResearchSummary {
  available: boolean;
  reason?: string;
  datasetId?: string;
  snapshotType?: string;
  frameCount?: number;
  lastTradingDate?: string;
  lifecycleDistribution?: Record<string, number>;
  mainlineThemes?: Array<{ themeId: string; themeName: string; heatScore: number }>;
  crowdingAlerts?: Array<{ themeId: string; themeName: string; crowdingRisk: number }>;
  qualityPassed?: boolean;
  researchGrade?: string;
  themeCount?: number;
  signalCount?: number;
}

export interface ThemeReturnStats {
  tradeCount: number;
  winRate: number;
  avgNetReturn: number;
  totalNetReturn: number;
  totalProfit: number;
}

export interface ThemeTrendReport {
  runId: string;
  strategyName: string;
  datasetId: string;
  lifecycleDistribution?: Record<string, number>;
  signalDistribution?: Record<string, number>;
  crowdingEventCount?: number;
  lifecycleTransitionCount?: number;
  lifecycleReturnDistribution?: Record<string, ThemeReturnStats>;
  themeTradeDiagnostics?: Array<{ themeName: string } & ThemeReturnStats>;
  candidateTierDiagnostics?: Array<{ candidateTier: string } & ThemeReturnStats>;
  roleDiagnostics?: Array<{ role: string } & ThemeReturnStats>;
  crowdingRiskDecay?: { triggeredTradeCount: number } & ThemeReturnStats;
}

export interface ThemeBacktestRequest {
  datasetId: string;
  strategyName: string;
  snapshotType: "quarter_hour" | "half_hour";
  randomSeed: number;
  crowdingBlockThreshold?: number;
  maxPositions?: number;
  positionSize?: number;
}

export interface ThemeOptimizationRequest {
  datasetId: string;
  strategyName: string;
  snapshotType: string;
  method: string;
  randomSeed: number;
  trials: number;
  objective: string;
  parameterGrid?: Record<string, unknown>;
}

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
  useThemeFactorForExecution: boolean;
  intrabarAmbiguity: "stop_first" | "take_first";
  momentumPeriods: number[];
  macdFast: number;
  macdSlow: number;
  macdSignal: number;
}

export interface BacktestTrade {
  id?: number;
  backtestRunId?: string;
  code: string;
  name?: string;
  side?: string;
  entrySnapshotId?: string | null;
  exitSnapshotId?: string | null;
  entryTime?: number | null;
  exitTime?: number | null;
  entryTradingDate?: string | null;
  exitTradingDate?: string | null;
  entryPrice?: number | null;
  exitPrice?: number | null;
  quantity?: number;
  grossReturn?: number | null;
  netReturn?: number | null;
  profit?: number | null;
  holdingBars?: number | null;
  reason?: string | null;
  candidateTier?: string | null;
  stage?: string | null;
  regime?: string | null;
  explanation?: string | null;
  fillDetail?: Record<string, unknown>;
}

export interface BacktestEquityPoint {
  id?: number;
  backtestRunId?: string;
  snapshotId?: string | null;
  timestamp?: number | null;
  tradingDate?: string | null;
  equity?: number | null;
  cash?: number | null;
  marketValue?: number | null;
  positionCount?: number | null;
}

export interface BacktestSignal {
  id?: number;
  backtestRunId?: string;
  snapshotId?: string | null;
  tradingDate?: string | null;
  code: string;
  name?: string;
  candidateTier?: string | null;
  signal?: string | null;
  confidence?: number | null;
  rank?: number | null;
  stage?: string | null;
  regime?: string | null;
  reasons?: string[];
  riskFlags?: string[];
}

export interface BacktestQualityReport {
  id?: number;
  backtestRunId?: string;
  passed?: boolean;
  severity?: string;
  researchGrade?: string;
  frameCount?: number;
  stockCount?: number;
  sectorCount?: number;
  missingFields?: Record<string, number>;
  nanCounts?: Record<string, number>;
  infCounts?: Record<string, number>;
  negativePriceCount?: number;
  nonPositivePriceCount?: number;
  negativeVolumeCount?: number;
  coverageRatio?: number | null;
  timeOrderFixed?: boolean;
  timeOrderFixCount?: number;
  warnings?: string[];
}

export interface PaginatedBacktestResponse<T> {
  runId: string;
  items: T[];
  limit: number;
  offset: number;
  total: number;
}

export interface BacktestEquityResponse {
  runId: string;
  items: BacktestEquityPoint[];
}

export interface BacktestQualityResponse {
  runId: string;
  qualityReport: BacktestQualityReport | null;
}

export interface BacktestDeleteResponse {
  ok: boolean;
  runId: string;
  deleted: Record<string, number>;
}

export type BacktestReportTabKey =
  | "trades"
  | "signals"
  | "quality"
  | "controls"
  | "matching"
  | "config";

export interface BacktestReportVerdict {
  level: "usable" | "degraded" | "blocked";
  label: string;
  tone: "good" | "warn" | "bad";
  performanceLabel: string;
  tradeLabel: string;
  qualityLabel: string;
  summary: string;
  reasons: string[];
}

export interface BacktestCompareSummary {
  runId: string;
  datasetId?: string;
  snapshotType?: string;
  strategyName?: string;
  strategyVersion?: string;
  configHash?: string;
  randomSeed?: number;
  metrics: Record<string, number | null>;
  missingMetrics?: string[];
}

export interface OptimizationRequest {
  datasetId: string;
  strategyName: StrategyName;
  method: "grid" | "random" | "bayesian" | "tpe";
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
