<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";

import { api, formatApiError } from "./api";
import {
  buildReplaySteps,
  buildBacktestVerdict,
  buildControlConclusion,
  buildDrawdownCurve,
  buildQualityNarratives,
  buildSignalSummary,
  buildTradeSummary,
  formatDisplayTime,
  formatNumber,
  formatPercent,
  formatPrice,
  getArrayField,
  getEquityCurve,
  getMetric,
  getNestedNumber,
  getNestedString,
  getObjectField,
  getOptimizationTrials,
  getRunId,
  getTrades
} from "./report";
import type {
  BacktestEquityPoint,
  BacktestQualityReport,
  BacktestRequest,
  BacktestReportTabKey,
  BacktestSignal,
  BacktestTrade,
  DatasetSummary,
  GoldenImportPayload,
  GoldenValidateRequest,
  HealthResponse,
  OptimizationRequest,
  RequestResult,
  StrategyName
} from "./types";

type TabKey = "golden" | "backtest" | "optimization" | "report" | "replay";
type ImportMode = "sqlite_snapshots" | "json_file";

const strategyOptions: Array<{ value: StrategyName; label: string; description: string }> = [
  {
    value: "rank_trend_candidate",
    label: "RankTrend 候选池",
    description: "A_MAIN + 连续确认 B_IGNITION，当前正式策略"
  },
  {
    value: "hot_top10",
    label: "热榜 Top10",
    description: "只按热榜前 10 入场"
  },
  {
    value: "a_main_only",
    label: "A_MAIN only",
    description: "只买 A_MAIN"
  },
  {
    value: "b_ignition_only",
    label: "B_IGNITION only",
    description: "只买连续确认后的 B_IGNITION"
  },
  {
    value: "a_b_combined",
    label: "A+B",
    description: "A_MAIN + 连续确认 B_IGNITION 对照口径"
  }
];

const tabs: Array<{ key: TabKey; label: string }> = [
  { key: "golden", label: "Golden 对齐" },
  { key: "backtest", label: "回测运行" },
  { key: "optimization", label: "参数优化" },
  { key: "report", label: "回测报告" },
  { key: "replay", label: "单票回放" }
];

const activeTab = ref<TabKey>("backtest");
const health = reactive<RequestResult<HealthResponse>>({ status: "idle" });
const datasetsState = reactive<RequestResult<DatasetSummary[]>>({ status: "idle", data: [] });
const importState = reactive<RequestResult>({ status: "idle" });
const goldenState = reactive<RequestResult>({ status: "idle" });
const backtestState = reactive<RequestResult>({ status: "idle" });
const backtestDetailState = reactive<RequestResult>({ status: "idle" });
const backtestNormalizedState = reactive<RequestResult<{
  trades: BacktestTrade[];
  equityCurve: BacktestEquityPoint[];
  signals: BacktestSignal[];
  qualityReport: BacktestQualityReport | null;
  tradeTotal: number;
  signalTotal: number;
}>>({ status: "idle" });
const optimizationState = reactive<RequestResult>({ status: "idle" });
const optimizationDetailState = reactive<RequestResult>({ status: "idle" });
const snapshotCountsState = reactive<RequestResult<Record<string, unknown>>>({ status: "idle" });

const selectedDatasetId = ref("");
const datasetRefreshAt = ref("");
const importMode = ref<ImportMode>("sqlite_snapshots");
const sourceDatasetId = ref("dragonboard_live");
const selectedJsonFile = ref<File | null>(null);
const selectedGoldenFile = ref<File | null>(null);
const importSnapshotType = ref<"half_hour" | "quarter_hour">("half_hour");
const datasetName = ref(`dragonboard-${new Date().toISOString().slice(0, 10)}`);
const dryRunImport = ref(false);
const importMaxSnapshots = ref(0);
const importStartDate = ref("");
const importEndDate = ref("");
const lastBacktestId = ref("");
const lastOptimizationId = ref("");
const manualBacktestId = ref("");
const manualOptimizationId = ref("");
const optimizationPollMessage = ref("");
const replayCode = ref("");
const goldenAction = ref<"baseline" | "validate" | "">("");
const copiedBox = ref("");
const activeReportTab = ref<BacktestReportTabKey>("trades");
const signalTierFilter = ref("");
const signalTypeFilter = ref("");
const signalRegimeFilter = ref("");
const signalRiskFilter = ref<"all" | "risk" | "clean">("all");
const showReportJson = ref(false);
let optimizationPollToken = 0;

const backtestForm = reactive<BacktestRequest>({
  datasetId: "",
  strategyName: "rank_trend_candidate",
  snapshotType: "half_hour",
  randomSeed: 20260430,
  initialCash: 1000000,
  maxPositions: 5,
  positionSize: 0.2,
  executionMode: "current_bar",
  maxHoldingBars: 40,
  targetHoldingDays: 5,
  takeProfitPct: 0.12,
  stopLossPct: 0.06,
  feeRate: 0.0003,
  stampTaxRate: 0.0005,
  slippageRate: 0.001,
  enforceT1: true,
  useOrderBookPrice: true,
  enforceLimitStatus: true,
  enforceVolumeLimit: true,
  enforceOrderBookQueue: true,
  allowPartialFills: true,
  volumeParticipationRate: 0.05,
  orderBookParticipationRate: 0.3,
  useIntrabarStops: true,
  intrabarAmbiguity: "stop_first",
  momentumPeriods: [3, 5, 8, 13, 21],
  macdFast: 21,
  macdSlow: 34,
  macdSignal: 13
});

const optimizationForm = reactive<OptimizationRequest>({
  datasetId: "",
  strategyName: "rank_trend_candidate",
  method: "grid",
  randomSeed: 20260430,
  objective: "stability",
  trials: 36,
  validationMode: "auto",
  validationRatio: 0.3,
  validationWarmupBars: 40,
  walkForward: {
    enabled: false,
    trainWindowDays: 5,
    validationWindowDays: 1,
    stepDays: 1,
    topTrials: 5
  },
  parameterGrid: {
    momentumPeriods: [
      [3, 5, 8, 13, 21],
      [2, 4, 6, 10, 16],
      [5, 8, 13, 21, 34]
    ],
    takeProfitPct: [0.08, 0.12, 0.16],
    stopLossPct: [0.04, 0.06, 0.08],
    maxPositions: [3, 5, 8]
  }
});

const goldenForm = reactive<GoldenValidateRequest>({
  datasetId: "",
  caseId: "rank_trend_default",
  strict: true,
  tolerance: 0.000001,
  sampleLimit: 100
});

const gridInputs = reactive({
  momentumPeriods: "3-5-8-13-21;2-4-6-10-16;5-8-13-21-34",
  takeProfitPct: "0.08,0.12,0.16",
  stopLossPct: "0.04,0.06,0.08",
  maxPositions: "3,5,8"
});

const selectedDataset = computed(() => {
  return datasetsState.data?.find((dataset) => dataset.id === selectedDatasetId.value);
});

const sqliteSourceOptions = computed(() => {
  const seen = new Set<string>();
  const options: Array<{ id: string; label: string }> = [];
  const add = (id: string, label?: string) => {
    if (!id || seen.has(id)) {
      return;
    }
    seen.add(id);
    options.push({ id, label: label || id });
  };
  add("dragonboard_live", "dragonboard_live / 正式快照库");
  for (const dataset of datasetsState.data || []) {
    add(dataset.id, datasetDisplayName(dataset));
  }
  return options;
});
const reportSource = computed(() => {
  const base = asRecord(backtestDetailState.data || backtestState.data);
  if (!backtestNormalizedState.data) {
    return base;
  }
  const quality = backtestNormalizedState.data.qualityReport;
  return {
    ...base,
    trades: backtestNormalizedState.data.trades,
    equityCurve: backtestNormalizedState.data.equityCurve,
    signals: backtestNormalizedState.data.signals,
    normalizedReport: {
      tradeTotal: backtestNormalizedState.data.tradeTotal,
      signalTotal: backtestNormalizedState.data.signalTotal
    },
    qualityReport: quality,
    dataQuality: quality
      ? {
          ...quality,
          snapshotCount: quality.frameCount,
          sourceSnapshotCount: quality.frameCount,
          recommendation: quality.researchGrade === "research_ready" ? "样本质量满足研究报告读取要求" : "样本质量存在降级，请结合 warnings 和覆盖率解释结果"
        }
      : base.dataQuality
  };
});
const optimizationSource = computed(() => optimizationDetailState.data || optimizationState.data);
const equityCurve = computed(() => getEquityCurve(reportSource.value));
const trades = computed(() => getTrades(reportSource.value));
const replaySteps = computed(() => buildReplaySteps(reportSource.value, replayCode.value));

const reportMetrics = computed(() => ({
  totalReturn: getMetric(reportSource.value, ["totalReturn", "total_return", "return"]),
  realizedReturn: getMetric(reportSource.value, ["realizedReturn", "realized_return"]),
  unrealizedMarkProfit: getMetric(reportSource.value, ["unrealizedMarkProfit", "unrealized_mark_profit"]),
  unrealizedExitCost: getMetric(reportSource.value, ["unrealizedExitCost", "unrealized_exit_cost"]),
  unrealizedProfit: getMetric(reportSource.value, ["unrealizedProfit", "unrealized_profit"]),
  sharpe: getMetric(reportSource.value, ["sharpe", "sharpeRatio", "sharpe_ratio"]),
  maxDrawdown: getMetric(reportSource.value, ["maxDrawdown", "max_drawdown", "drawdown"]),
  winRate: getMetric(reportSource.value, ["winRate", "win_rate"]),
  tradeCount: getMetric(reportSource.value, ["tradeCount", "trade_count", "trades"]),
  openPositionCount: getMetric(reportSource.value, ["openPositionCount", "open_position_count"])
}));

const equityPolyline = computed(() => {
  const points = equityCurve.value;
  if (points.length < 2) {
    return "";
  }
  const values = points.map((point) => point.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  return points
    .map((point, index) => {
      const x = (index / Math.max(points.length - 1, 1)) * 100;
      const y = 100 - ((point.value - min) / range) * 100;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
});
const drawdownCurve = computed(() => buildDrawdownCurve(equityCurve.value));
const drawdownPolyline = computed(() => {
  const points = drawdownCurve.value;
  if (points.length < 2) {
    return "";
  }
  const values = points.map((point) => point.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  return points
    .map((point, index) => {
      const x = (index / Math.max(points.length - 1, 1)) * 100;
      const y = 100 - ((point.value - min) / range) * 100;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
});

const datasetStatusLabel = computed(() => {
  if (datasetsState.status === "loading") {
    return "刷新中";
  }
  if (datasetsState.status === "error") {
    return "error";
  }
  return `${datasetsState.data?.length || 0} 个`;
});

const importStatusLabel = computed(() => {
  if (importState.status === "loading" || snapshotCountsState.status === "loading") {
    return "loading";
  }
  if (importState.status === "error" || snapshotCountsState.status === "error") {
    return "error";
  }
  if (importState.status === "ok") {
    return "ok";
  }
  if (snapshotCountsState.status === "ok") {
    return "checked";
  }
  return "idle";
});

const importStatusClass = computed(() => {
  if (importState.status === "loading" || snapshotCountsState.status === "loading") {
    return "status-loading";
  }
  if (importState.status === "error" || snapshotCountsState.status === "error") {
    return "status-error";
  }
  if (importState.status === "ok" || snapshotCountsState.status === "ok") {
    return "status-ok";
  }
  return "status-idle";
});

const importHelpText = computed(() => {
  if (importMode.value === "json_file") {
    return "迁移辅助：只在需要导入历史 JSON/备份文件时使用。日常研究应优先使用 SQLite 快照库。";
  }
  return "推荐：从 QuantBoard SQLite 主库里的正式快照表生成研究数据集。DragonBoard 已经把正式快照写入 SQLite，不再需要浏览器 IndexedDB/LevelDB/运行页桥接。";
});

const snapshotCounts = computed(() => {
  const raw = snapshotCountsState.data?.counts;
  return raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
});

const importSuccessText = computed(() => {
  const raw = importState.data as unknown;
  const data =
    raw && typeof raw === "object"
      ? ((raw as { dataset?: DatasetSummary } & Partial<DatasetSummary>).dataset ||
          (raw as Partial<DatasetSummary>))
      : undefined;
  const name = data?.name || datasetName.value;
  return dryRunImport.value ? `试运行完成，未写入数据集：${name}` : `数据集已生成：${name}`;
});

const goldenResult = computed(() => {
  const data = (goldenState.data || goldenState.raw) as Record<string, unknown> | undefined;
  return data && typeof data === "object" ? data : {};
});

const goldenSummary = computed(() => {
  if (goldenState.status === "loading") {
    return goldenAction.value === "baseline" ? "正在生成并保存 Golden 基线..." : "正在重放 RankTrend 并执行 Golden 校验...";
  }
  if (goldenState.status === "error") {
    return goldenState.error || "Golden 操作失败";
  }
  if (goldenState.status !== "ok") {
    return "尚未执行 Golden 操作";
  }
  if (goldenResult.value.message) {
    const source = goldenResult.value.source === "ts_golden_import" ? "TS Golden" : "Python 自基线";
    return `${source} 已保存：${goldenResult.value.caseId || goldenForm.caseId}，样本 ${goldenResult.value.checked || 0} 条`;
  }
  const passed = Boolean(goldenResult.value.passed);
  const issueCount = Number(goldenResult.value.issueCount || 0);
  const source = goldenResult.value.source === "ts_golden_import" ? "TS Golden" : "Python 自基线";
  const mode = goldenResult.value.strict === false ? "宽松" : "严格";
  const checked = Number(goldenResult.value.checked || 0);
  const expectedCount = Number(goldenResult.value.expectedCount || checked);
  const sampleText = expectedCount && expectedCount !== checked ? `检查 ${checked}/${expectedCount} 条` : `检查 ${checked} 条`;
  return passed
    ? `${source} ${mode}校验通过：${goldenResult.value.caseId || goldenForm.caseId}，${sampleText}，差异 0`
    : `${source} ${mode}校验未通过：差异 ${issueCount} 条，请查看 issues`;
});

const goldenSummaryClass = computed(() => {
  if (goldenState.status === "loading") {
    return "golden-banner loading";
  }
  if (goldenState.status === "error" || (goldenState.status === "ok" && goldenResult.value.passed === false)) {
    return "golden-banner error";
  }
  if (goldenState.status === "ok" && goldenResult.value.source === "python_current_output") {
    return "golden-banner warning";
  }
  if (goldenState.status === "ok") {
    return "golden-banner ok";
  }
  return "golden-banner";
});

const goldenPreviewRows = computed(() => {
  const preview = goldenResult.value.actualPreview;
  return Array.isArray(preview) ? preview.slice(0, 5) as Array<Record<string, unknown>> : [];
});

const controlBacktests = computed(() => {
  return getArrayField(reportSource.value, ["controlBacktests"]) as Array<Record<string, unknown>>;
});

const dataQuality = computed(() => getObjectField(reportSource.value, ["dataQuality"]));
const dataQualityExamples = computed(() => {
  const rows = dataQuality.value.lowHotlistExamples;
  return Array.isArray(rows) ? rows.slice(0, 6) as Array<Record<string, unknown>> : [];
});
const tradeDiagnostics = computed(() => getObjectField(reportSource.value, ["tradeDiagnostics"]));
const matchingDiagnostics = computed(() => {
  const fromTradeDiagnostics = getObjectField(tradeDiagnostics.value, ["matchingDiagnostics"]);
  if (Object.keys(fromTradeDiagnostics).length) {
    return fromTradeDiagnostics;
  }
  const simulation = getObjectField(reportSource.value, ["tradeSimulation"]);
  return getObjectField(simulation, ["matchingDiagnostics"]);
});
const matchingSkippedReasons = computed(() => {
  const rows = matchingDiagnostics.value.skippedByReason;
  return Array.isArray(rows) ? rows.slice(0, 8) as Array<Record<string, unknown>> : [];
});
const matchingWarnings = computed(() => {
  const warnings = matchingDiagnostics.value.warnings;
  return Array.isArray(warnings) ? warnings.map(String) : [];
});
const tradeDiagnosticsReasons = computed(() => {
  const rows = tradeDiagnostics.value.byExitReason;
  return Array.isArray(rows) ? rows.slice(0, 8) as Array<Record<string, unknown>> : [];
});
const tradeDiagnosticsTiers = computed(() => {
  const rows = tradeDiagnostics.value.byCandidateTier;
  return Array.isArray(rows) ? rows.slice(0, 8) as Array<Record<string, unknown>> : [];
});
const normalizedReportMeta = computed(() => getObjectField(reportSource.value, ["normalizedReport"]));
const normalizedSignals = computed(() => getArrayField(reportSource.value, ["signals"]) as BacktestSignal[]);
const qualityReport = computed(() => {
  const fromNormalized = backtestNormalizedState.data?.qualityReport;
  if (fromNormalized) {
    return fromNormalized;
  }
  const report = getObjectField(reportSource.value, ["qualityReport"]);
  return Object.keys(report).length ? (report as BacktestQualityReport) : null;
});
const reportVerdict = computed(() => buildBacktestVerdict(reportSource.value, qualityReport.value, trades.value as BacktestTrade[], normalizedSignals.value));
const tradeSummary = computed(() => buildTradeSummary(trades.value as BacktestTrade[]));
const signalSummary = computed(() => buildSignalSummary(normalizedSignals.value));
const qualityNarratives = computed(() => buildQualityNarratives(dataQuality.value, qualityReport.value));
const controlConclusions = computed(() => buildControlConclusion(reportSource.value, controlBacktests.value));
const reportTabs: Array<{ key: BacktestReportTabKey; label: string }> = [
  { key: "trades", label: "交易明细" },
  { key: "signals", label: "信号解释" },
  { key: "quality", label: "质量诊断" },
  { key: "controls", label: "对照组" },
  { key: "matching", label: "撮合诊断" },
  { key: "config", label: "参数快照" }
];
const signalRegimeOptions = computed(() => {
  const values = new Set<string>();
  for (const signal of normalizedSignals.value) {
    if (signal.regime) {
      values.add(signal.regime);
    }
  }
  return Array.from(values).sort();
});
const filteredSignals = computed(() => {
  return normalizedSignals.value.filter((signal) => {
    if (signalTierFilter.value && signal.candidateTier !== signalTierFilter.value) {
      return false;
    }
    if (signalTypeFilter.value && signal.signal !== signalTypeFilter.value) {
      return false;
    }
    if (signalRegimeFilter.value && signal.regime !== signalRegimeFilter.value) {
      return false;
    }
    const hasRisk = Boolean(signal.riskFlags?.length);
    if (signalRiskFilter.value === "risk" && !hasRisk) {
      return false;
    }
    if (signalRiskFilter.value === "clean" && hasRisk) {
      return false;
    }
    return true;
  });
});
const optimizationTrials = computed(() => getOptimizationTrials(optimizationSource.value));
const optimizationRunStatus = computed(() => getRunStatus(optimizationSource.value));
const optimizationRunId = computed(() => getRunId(optimizationSource.value) || lastOptimizationId.value);
const optimizationExperiment = computed(() => getObjectField(optimizationSource.value, ["experiment"]));
const optimizationRisk = computed(() => getObjectField(optimizationSource.value, ["overfitRisk"]));
const optimizationRiskLevel = computed(() => {
  return getNestedString(optimizationExperiment.value, ["overfitRisk", "level"]) || String(optimizationRisk.value.level || "");
});
const optimizationRiskReason = computed(() => {
  return getNestedString(optimizationExperiment.value, ["overfitRisk", "reason"]) || String(optimizationRisk.value.reason || "");
});
const parameterStability = computed(() => getObjectField(optimizationSource.value, ["parameterStability"]));
const parameterStabilityRows = computed(() => {
  const rows = parameterStability.value.parameters;
  return Array.isArray(rows) ? rows.slice(0, 6) as Array<Record<string, unknown>> : [];
});
const optimizationWarnings = computed(() => {
  const warnings = getArrayField(optimizationSource.value, ["warnings"]);
  return warnings.map(String);
});
const optimizationDataQuality = computed(() => getObjectField(optimizationSource.value, ["dataQuality"]));
const walkForward = computed(() => getObjectField(optimizationSource.value, ["walkForward"]));
const walkForwardAggregate = computed(() => getObjectField(walkForward.value, ["aggregate"]));

const healthLabel = computed(() => {
  if (health.status === "ok") {
    return `API ${health.data?.status || "ok"} ${health.data?.version || ""}`.trim();
  }
  if (health.status === "error") {
    return `API 异常: ${health.error}`;
  }
  return health.status === "loading" ? "API 检查中" : "API 未检查";
});

function jsonPreview(value: unknown): string {
  if (value === undefined) {
    return "";
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

async function copyJsonBox(id: string, value: unknown): Promise<void> {
  const text = jsonPreview(value);
  if (!text) {
    copiedBox.value = `${id}:empty`;
    window.setTimeout(() => {
      if (copiedBox.value === `${id}:empty`) {
        copiedBox.value = "";
      }
    }, 1800);
    return;
  }
  try {
    await navigator.clipboard.writeText(text);
    copiedBox.value = id;
  } catch {
    copiedBox.value = `${id}:error`;
  }
  window.setTimeout(() => {
    if (copiedBox.value === id || copiedBox.value === `${id}:error`) {
      copiedBox.value = "";
    }
  }, 1800);
}

function copyLabel(id: string): string {
  if (copiedBox.value === id) {
    return "已复制";
  }
  if (copiedBox.value === `${id}:error`) {
    return "复制失败";
  }
  if (copiedBox.value === `${id}:empty`) {
    return "无内容";
  }
  return "一键复制";
}

function statusClass(status: string): string {
  return `status-${status}`;
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function getRunStatus(value: unknown): string {
  const root = asRecord(value);
  const result = asRecord(root.result);
  const run = asRecord(root.run);
  return String(root.status || result.status || run.status || "");
}

function getStructuredError(value: unknown): unknown {
  const root = asRecord(value);
  const result = asRecord(root.result);
  const run = asRecord(root.run);
  return root.error || result.error || run.error || root.detail || result.detail || "";
}

function formatStructuredError(value: unknown): string {
  if (!value) {
    return "";
  }
  if (typeof value === "string") {
    return value;
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function parseNumberList(value: string): number[] {
  return value
    .split(",")
    .map((item) => Number(item.trim()))
    .filter((item) => Number.isFinite(item));
}

function parsePeriodGrid(value: string): number[][] {
  return value
    .split(";")
    .map((group) =>
      group
        .split(/[-,]/)
        .map((item) => Number(item.trim()))
        .filter((item) => Number.isFinite(item) && item > 0)
    )
    .filter((group) => group.length > 0);
}

function datasetDisplayName(dataset: DatasetSummary): string {
  const name = dataset.name || dataset.id;
  const shortId = dataset.id ? dataset.id.slice(-6) : "";
  const frames = dataset.frame_count ?? dataset.snapshot_count ?? 0;
  const range = dataset.start_date && dataset.end_date ? `${dataset.start_date}~${dataset.end_date}` : "无区间";
  return `${name} · ${range} · ${frames}帧 · ${shortId}`;
}

function datasetRange(dataset: DatasetSummary): string {
  const start = dataset.start_date || "-";
  const end = dataset.end_date || "-";
  return `${start} / ${end}`;
}

function shortId(value: unknown): string {
  const text = String(value || "");
  return text ? text.slice(0, 12) : "-";
}

function formatTrialParameters(value: unknown): string {
  if (!value || typeof value !== "object") {
    return "-";
  }
  return Object.entries(value as Record<string, unknown>)
    .map(([key, item]) => `${key}=${Array.isArray(item) ? item.join("-") : String(item)}`)
    .join(" · ");
}

function formatTopValues(value: unknown): string {
  if (!Array.isArray(value)) {
    return "-";
  }
  return value
    .slice(0, 4)
    .map((item) => {
      const row = item && typeof item === "object" ? (item as Record<string, unknown>) : {};
      return `${row.value ?? "-"}(${row.count ?? 0})`;
    })
    .join(" · ");
}

function syncSelectedDataset(datasetId: string): void {
  backtestForm.datasetId = datasetId;
  optimizationForm.datasetId = datasetId;
  goldenForm.datasetId = datasetId;
}

watch(
  () => backtestForm.strategyName,
  (strategyName) => {
    optimizationForm.strategyName = strategyName;
  }
);

async function runRequest<T>(
  state: RequestResult<T>,
  action: () => Promise<T>,
  onSuccess?: (data: T) => void
): Promise<void> {
  state.status = "loading";
  state.error = undefined;
  try {
    const data = await action();
    state.status = "ok";
    state.data = data;
    state.raw = data;
    onSuccess?.(data);
  } catch (error) {
    state.status = "error";
    state.error = formatApiError(error);
    state.raw = {
      error: state.error,
      name: error instanceof Error ? error.name : "Error",
      message: error instanceof Error ? error.message : String(error)
    };
  }
}

async function checkHealth(): Promise<void> {
  await runRequest(health, api.health);
}

async function loadDatasets(): Promise<void> {
  await runRequest(datasetsState, api.datasets, (datasets) => {
    datasetRefreshAt.value = new Date().toLocaleTimeString();
    if (!selectedDatasetId.value && datasets.length) {
      selectedDatasetId.value = datasets[0].id;
    } else if (selectedDatasetId.value && !datasets.some((dataset) => dataset.id === selectedDatasetId.value)) {
      selectedDatasetId.value = datasets[0]?.id || "";
    }
  });
}

async function inspectSnapshotSource(): Promise<void> {
  await runRequest(snapshotCountsState, () =>
    api.snapshotCounts(sourceDatasetId.value.trim() || "dragonboard_live") as Promise<Record<string, unknown>>
  );
}

function selectJsonFile(event: Event): void {
  const input = event.target as HTMLInputElement;
  selectedJsonFile.value = input.files?.[0] || null;
  if (selectedJsonFile.value && !datasetName.value.trim()) {
    datasetName.value = selectedJsonFile.value.name.replace(/\.[^.]+$/, "");
  }
}

function selectGoldenFile(event: Event): void {
  const input = event.target as HTMLInputElement;
  selectedGoldenFile.value = input.files?.[0] || null;
}

async function readJsonFile(file: File): Promise<unknown> {
  const text = await file.text();
  return JSON.parse(text);
}

async function importDataset(): Promise<void> {
  if (importMode.value === "json_file") {
    if (!selectedJsonFile.value) {
      importState.status = "error";
      importState.error = "请先选择 JSON 快照文件";
      return;
    }
    await runRequest(importState, async () => {
      const content = await readJsonFile(selectedJsonFile.value as File);
      return api.uploadDataset({
        filename: selectedJsonFile.value?.name || "upload.json",
        name: datasetName.value,
        content,
        snapshotTypes: [importSnapshotType.value],
        dryRun: dryRunImport.value
      });
    });
    if (importState.status === "ok" && !dryRunImport.value) {
      await loadDatasets();
    }
    return;
  }

  const payload = {
    sourceType: "sqlite_snapshots" as const,
    sourceDatasetId: sourceDatasetId.value.trim() || "dragonboard_live",
    name: datasetName.value,
    snapshotTypes: [importSnapshotType.value],
    startDate: importStartDate.value.trim() || undefined,
    endDate: importEndDate.value.trim() || undefined,
    maxSnapshots: importMaxSnapshots.value > 0 ? importMaxSnapshots.value : undefined,
    dryRun: dryRunImport.value
  };

  await runRequest(importState, () => api.importDataset(payload));
  if (importState.status === "ok" && !dryRunImport.value) {
    await loadDatasets();
  }
}

async function validateGolden(): Promise<void> {
  goldenAction.value = "validate";
  await runRequest(goldenState, () => api.validateGolden({ ...goldenForm }));
}

async function importGoldenCase(): Promise<void> {
  if (!selectedGoldenFile.value) {
    goldenState.status = "error";
    goldenState.error = "请先选择 TS golden JSON 文件";
    return;
  }
  goldenAction.value = "validate";
  await runRequest(goldenState, async () => {
    const payload = await readJsonFile(selectedGoldenFile.value as File);
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
      throw new Error("TS golden JSON 须是对象结构");
    }
    const request: GoldenImportPayload = {
      caseId: goldenForm.caseId,
      datasetId: selectedDatasetId.value || goldenForm.datasetId,
      snapshotType: backtestForm.snapshotType,
      source: "ts_golden_import",
      payload: payload as Record<string, unknown>
    };
    return api.importGolden(request);
  });
}

async function createGoldenBaseline(): Promise<void> {
  goldenAction.value = "baseline";
  await runRequest(goldenState, () =>
    api.createGoldenBaseline({
      ...goldenForm,
      datasetId: selectedDatasetId.value || goldenForm.datasetId
    })
  );
}

async function runBacktest(): Promise<void> {
  await runRequest(
    backtestState,
    () =>
      api.runBacktest({
        ...backtestForm,
        datasetId: selectedDatasetId.value || backtestForm.datasetId
      }),
    (data) => {
      const id = getRunId(data);
      if (id) {
        lastBacktestId.value = id;
        manualBacktestId.value = id;
        backtestNormalizedState.status = "idle";
        backtestNormalizedState.data = undefined;
        backtestNormalizedState.error = undefined;
      }
    }
  );
}

async function fetchBacktest(): Promise<void> {
  const id = manualBacktestId.value.trim() || lastBacktestId.value.trim();
  if (!id) {
    backtestDetailState.status = "error";
    backtestDetailState.error = "缺少回测 ID";
    return;
  }
  backtestNormalizedState.status = "loading";
  backtestNormalizedState.error = undefined;
  backtestNormalizedState.data = undefined;
  await runRequest(backtestDetailState, () => api.getBacktest(id));
  if (backtestDetailState.status !== "ok") {
    backtestNormalizedState.status = "error";
    backtestNormalizedState.error = "兼容报告读取失败，未继续读取归一化明细";
    return;
  }
  try {
    const [tradePage, equity, signalPage, quality] = await Promise.all([
      api.getBacktestTrades(id, 200, 0),
      api.getBacktestEquity(id),
      api.getBacktestSignals(id, 300, 0),
      api.getBacktestQuality(id)
    ]);
    backtestNormalizedState.status = "ok";
    backtestNormalizedState.data = {
      trades: tradePage.items,
      equityCurve: equity.items,
      signals: signalPage.items,
      qualityReport: quality.qualityReport,
      tradeTotal: tradePage.total,
      signalTotal: signalPage.total
    };
    backtestNormalizedState.raw = {
      trades: tradePage,
      equity,
      signals: signalPage,
      quality
    };
    activeReportTab.value = tradePage.items.length ? "trades" : "signals";
  } catch (error) {
    backtestNormalizedState.status = "error";
    backtestNormalizedState.error = formatApiError(error);
    backtestNormalizedState.raw = {
      error: backtestNormalizedState.error,
      message: error instanceof Error ? error.message : String(error)
    };
  }
}

async function runOptimization(): Promise<void> {
  optimizationForm.parameterGrid = {
    momentumPeriods: parsePeriodGrid(gridInputs.momentumPeriods),
    takeProfitPct: parseNumberList(gridInputs.takeProfitPct),
    stopLossPct: parseNumberList(gridInputs.stopLossPct),
    maxPositions: parseNumberList(gridInputs.maxPositions)
  };

  const pollToken = ++optimizationPollToken;
  optimizationState.status = "loading";
  optimizationState.error = undefined;
  optimizationState.data = undefined;
  optimizationState.raw = undefined;
  optimizationDetailState.status = "idle";
  optimizationDetailState.error = undefined;
  optimizationDetailState.data = undefined;
  optimizationDetailState.raw = undefined;
  optimizationPollMessage.value = "";

  try {
    const started = await api.runOptimization({
      ...optimizationForm,
      datasetId: selectedDatasetId.value || optimizationForm.datasetId
    });
    const id = getRunId(started);
    if (!id) {
      throw new Error("后端未返回 runId，无法轮询优化状态");
    }
    lastOptimizationId.value = id;
    manualOptimizationId.value = id;
    optimizationState.status = "running";
    optimizationState.data = started;
    optimizationState.raw = started;
    optimizationPollMessage.value = `优化任务已启动：${id}`;
    await pollOptimization(id, pollToken);
  } catch (error) {
    if (pollToken !== optimizationPollToken) {
      return;
    }
    optimizationState.status = "error";
    optimizationState.error = formatApiError(error);
    optimizationState.raw = {
      error: optimizationState.error,
      name: error instanceof Error ? error.name : "Error",
      message: error instanceof Error ? error.message : String(error)
    };
  }
}

async function pollOptimization(id: string, pollToken: number): Promise<void> {
  while (pollToken === optimizationPollToken) {
    await delay(1500);
    const data = await api.getOptimization(id);
    if (pollToken !== optimizationPollToken) {
      return;
    }

    const status = getRunStatus(data) || "running";
    optimizationState.data = data;
    optimizationState.raw = data;
    optimizationPollMessage.value = `优化任务 ${id} 当前状态：${status}`;

    if (status === "completed") {
      optimizationState.status = "ok";
      optimizationPollMessage.value = `优化任务已完成：${id}`;
      return;
    }

    if (status === "failed") {
      const structuredError = getStructuredError(data);
      optimizationState.status = "error";
      optimizationState.error = formatStructuredError(structuredError) || "优化任务失败";
      optimizationState.raw = data;
      optimizationPollMessage.value = `优化任务失败：${id}`;
      return;
    }

    optimizationState.status = "running";
  }
}

async function fetchOptimization(): Promise<void> {
  const id = manualOptimizationId.value.trim() || lastOptimizationId.value.trim();
  if (!id) {
    optimizationDetailState.status = "error";
    optimizationDetailState.error = "缺少优化 ID";
    return;
  }
  await runRequest(optimizationDetailState, () => api.getOptimization(id), (data) => {
    const status = getRunStatus(data);
    if (status === "failed") {
      optimizationDetailState.status = "error";
      optimizationDetailState.error = formatStructuredError(getStructuredError(data)) || "优化任务失败";
    }
  });
}

watch(selectedDatasetId, syncSelectedDataset);

onMounted(async () => {
  await checkHealth();
  await loadDatasets();
});
</script>

<template>
  <main class="app-shell">
    <header class="topbar">
      <div>
        <h1>QuantBoard 轻实验台</h1>
        <p>数据导入、Golden 对齐、回测、优化、报告与单票解释联调面板</p>
      </div>
      <div class="topbar-actions">
        <span class="status-pill" :class="statusClass(health.status)">{{ healthLabel }}</span>
        <button type="button" class="icon-button" title="刷新 API 状态" @click="checkHealth">↻</button>
      </div>
    </header>

    <section class="workspace">
      <aside class="sidebar">
        <section class="panel">
          <div class="panel-header">
            <h2>数据集</h2>
            <div class="panel-actions">
              <span class="status-pill" :class="statusClass(datasetsState.status)">
                {{ datasetStatusLabel }}
              </span>
              <button type="button" :disabled="datasetsState.status === 'loading'" @click="loadDatasets">
                {{ datasetsState.status === "loading" ? "刷新中" : "刷新" }}
              </button>
            </div>
          </div>
          <div v-if="datasetsState.status === 'error'" class="inline-error">
            {{ datasetsState.error }}
          </div>
          <div v-else-if="datasetRefreshAt" class="inline-note">
            最近刷新 {{ datasetRefreshAt }}
          </div>
          <select v-model="selectedDatasetId" class="full-select">
            <option value="">未选择数据集</option>
            <option v-for="dataset in datasetsState.data" :key="dataset.id" :value="dataset.id">
              {{ datasetDisplayName(dataset) }}
            </option>
          </select>
          <div v-if="selectedDataset" class="dataset-card">
            <div class="dataset-title">{{ datasetDisplayName(selectedDataset) }}</div>
            <dl>
              <div>
                <dt>ID</dt>
                <dd>{{ selectedDataset.id }}</dd>
              </div>
              <div>
                <dt>区间</dt>
                <dd>{{ datasetRange(selectedDataset) }}</dd>
              </div>
              <div>
                <dt>快照</dt>
                <dd>{{ selectedDataset.snapshot_count ?? 0 }}</dd>
              </div>
              <div>
                <dt>股票行</dt>
                <dd>{{ selectedDataset.stock_row_count ?? 0 }}</dd>
              </div>
            </dl>
          </div>
          <div v-else class="empty-state">后端返回数据集后会在这里展示元信息。</div>
        </section>

        <section class="panel">
          <div class="panel-header">
            <h2>数据导入</h2>
            <span class="status-pill" :class="importStatusClass">
              {{ importStatusLabel }}
            </span>
          </div>
          <label>
            导入方式
            <select v-model="importMode">
              <option value="sqlite_snapshots">SQLite 快照库</option>
              <option value="json_file">JSON 文件上传</option>
            </select>
          </label>
          <label v-if="importMode === 'json_file'">
            JSON 快照文件
            <input type="file" accept=".json,application/json" @change="selectJsonFile" />
          </label>
          <label v-if="importMode === 'sqlite_snapshots'">
            源快照数据集
            <select v-model="sourceDatasetId">
              <option v-for="option in sqliteSourceOptions" :key="option.id" :value="option.id">
                {{ option.label }}
              </option>
            </select>
          </label>
          <label>
            数据集名
            <input v-model="datasetName" type="text" />
          </label>
          <label>
            snapshotType / 快照类型
            <select v-model="importSnapshotType">
              <option value="half_hour">half_hour / 半小时</option>
              <option value="quarter_hour">quarter_hour / 15分钟</option>
            </select>
          </label>
          <div class="inline-note">
            {{ importHelpText }}
          </div>
          <template v-if="importMode === 'sqlite_snapshots'">
            <label>
              开始日期
              <input v-model="importStartDate" type="date" />
            </label>
            <label>
              结束日期
              <input v-model="importEndDate" type="date" />
            </label>
          </template>
          <div class="form-row">
            <label>
              最大快照数
              <input
                v-model.number="importMaxSnapshots"
                type="number"
                min="0"
                max="50000"
                :disabled="importMode !== 'sqlite_snapshots'"
              />
            </label>
            <label class="check-row">
              <input v-model="dryRunImport" type="checkbox" />
              dry run / 试运行
            </label>
          </div>
          <div class="button-row">
            <button
              type="button"
              :disabled="importMode !== 'sqlite_snapshots' || snapshotCountsState.status === 'loading'"
              @click="inspectSnapshotSource"
            >
              检查 SQLite 源
            </button>
            <button type="button" class="primary" :disabled="importState.status === 'loading'" @click="importDataset">
              生成数据集
            </button>
          </div>
          <div v-if="importState.status === 'error'" class="inline-error">
            {{ importState.error }}
          </div>
          <div v-if="snapshotCountsState.status === 'error'" class="inline-error">
            {{ snapshotCountsState.error }}
          </div>
          <div v-if="importState.status === 'ok'" class="inline-success">
            {{ importSuccessText }}
          </div>
          <div v-if="snapshotCountsState.data" class="preview-grid">
            <div>
              <b>{{ snapshotCounts.snapshot_frames ?? 0 }}</b>
              <span>frames</span>
            </div>
            <div>
              <b>{{ snapshotCounts.snapshot_stock_rows ?? 0 }}</b>
              <span>stock rows</span>
            </div>
            <div>
              <b>{{ snapshotCounts.snapshot_sector_rows ?? 0 }}</b>
              <span>sector rows</span>
            </div>
          </div>
        </section>
      </aside>

      <section class="main-panel">
        <nav class="tabs" aria-label="实验台功能">
          <button
            v-for="tab in tabs"
            :key="tab.key"
            type="button"
            :class="{ active: activeTab === tab.key }"
            @click="activeTab = tab.key"
          >
            {{ tab.label }}
          </button>
        </nav>

        <section v-if="activeTab === 'golden'" class="tab-panel">
          <div class="section-heading">
            <h2>Golden 对齐</h2>
            <span class="status-pill" :class="statusClass(goldenState.status)">
              {{ goldenState.status }}
            </span>
          </div>
          <div class="form-grid compact">
            <label>
              datasetId / 数据集ID
              <input v-model="goldenForm.datasetId" type="text" />
            </label>
            <label>
              caseId / 用例ID
              <input v-model="goldenForm.caseId" type="text" />
            </label>
            <label>
              tolerance / 误差容忍
              <input v-model.number="goldenForm.tolerance" type="number" step="0.000001" />
            </label>
            <label>
              sampleLimit / 校验样本数
              <input v-model.number="goldenForm.sampleLimit" type="number" min="1" max="5000" />
            </label>
            <label class="check-row">
              <input v-model="goldenForm.strict" type="checkbox" />
              strict / 严格模式
            </label>
          </div>
          <div class="button-row">
            <button
              type="button"
              :disabled="goldenState.status === 'loading'"
              @click="createGoldenBaseline"
            >
              {{ goldenState.status === "loading" && goldenAction === "baseline" ? "保存中..." : "保存当前输出为基线" }}
            </button>
            <button
              type="button"
              class="primary"
              :disabled="goldenState.status === 'loading'"
              @click="validateGolden"
            >
              {{ goldenState.status === "loading" && goldenAction === "validate" ? "校验中..." : "执行校验" }}
            </button>
          </div>
          <div class="file-row">
            <label>
              TS golden JSON / TypeScript 基线文件
              <input type="file" accept="application/json,.json" @change="selectGoldenFile" />
            </label>
            <button
              type="button"
              :disabled="goldenState.status === 'loading' || !selectedGoldenFile"
              @click="importGoldenCase"
            >
              导入 TS Golden
            </button>
          </div>
          <div class="inline-note">
            页面有两种基线：`保存当前输出为基线` 只保存 Python 当前结果，适合临时回归；`导入 TS Golden` 才是正式跨语言对齐入口。
            请在 DragonBoard 页面控制台执行 `window.quantBoardExportRankTrendGolden({ sampleLimit: {{ goldenForm.sampleLimit }} })` 导出 TS JSON 后在这里导入。导入后继续点击 `执行校验`。
          </div>
          <div :class="goldenSummaryClass">
            <strong>{{ goldenSummary }}</strong>
            <span v-if="goldenState.status === 'loading'">真实数据集通常需要数秒，请等待结果返回。</span>
            <span v-else-if="goldenState.status === 'ok' && goldenResult.source === 'ts_golden_import' && goldenResult.passed === true">这是正式 TS Golden 对齐通过，可作为跨语言验收依据。</span>
            <span v-else-if="goldenState.status === 'ok' && goldenResult.source === 'ts_golden_import' && goldenResult.message">TS Golden 已导入。下一步点击“执行校验”比较 Python 当前输出。</span>
            <span v-else-if="goldenState.status === 'ok' && goldenResult.source === 'python_current_output'">当前不是 TS Golden。它只说明 Python 当前输出没有相对自基线漂移，不能作为 TypeScript 跨语言验收。</span>
            <span v-else>正式验收请先导入 TypeScript 端导出的 TS Golden，再执行校验。</span>
          </div>
          <div v-if="goldenPreviewRows.length" class="golden-preview-grid">
            <div v-for="row in goldenPreviewRows" :key="`${row.snapshotId}-${row.code}`" class="golden-preview-item">
              <b>{{ row.code }}</b>
              <span>{{ row.candidateTier }} / {{ row.stage }} / {{ row.regime }}</span>
              <small>{{ row.snapshotId }}</small>
            </div>
          </div>
          <div class="json-box-wrap">
            <button
              type="button"
              class="copy-button"
              @click="copyJsonBox('golden', goldenState.raw || goldenState.data)"
            >
              {{ copyLabel("golden") }}
            </button>
            <pre class="json-box">{{ jsonPreview(goldenState.raw || goldenState.data) }}</pre>
          </div>
        </section>

        <section v-if="activeTab === 'backtest'" class="tab-panel">
          <div class="section-heading">
            <h2>RankTrend 回测</h2>
            <span class="status-pill" :class="statusClass(backtestState.status)">
              {{ backtestState.status }}
            </span>
          </div>
          <div class="form-grid">
            <label>
              datasetId / 数据集ID
              <input v-model="backtestForm.datasetId" type="text" />
            </label>
            <label>
              strategy / 策略
              <select v-model="backtestForm.strategyName">
                <option v-for="option in strategyOptions" :key="option.value" :value="option.value">
                  {{ option.label }} / {{ option.value }}
                </option>
              </select>
            </label>
            <label>
              snapshotType / 快照类型
              <select v-model="backtestForm.snapshotType">
                <option value="quarter_hour">quarter_hour / 15分钟</option>
                <option value="half_hour">half_hour / 半小时</option>
              </select>
            </label>
            <label>
              randomSeed / 随机种子
              <input v-model.number="backtestForm.randomSeed" type="number" />
            </label>
            <label>
              initialCash / 初始资金
              <input v-model.number="backtestForm.initialCash" type="number" />
            </label>
            <label>
              maxPositions / 最大持仓数
              <input v-model.number="backtestForm.maxPositions" type="number" min="1" />
            </label>
            <label>
              positionSize / 单票仓位
              <input v-model.number="backtestForm.positionSize" type="number" min="0.01" max="1" step="0.01" />
            </label>
            <label>
              executionMode / 成交时点
              <select v-model="backtestForm.executionMode">
                <option value="current_bar">current_bar / 信号同快照成交</option>
                <option value="next_bar">next_bar / 下一快照成交</option>
              </select>
            </label>
            <label>
              targetHoldingDays / 目标持仓天数
              <input v-model.number="backtestForm.targetHoldingDays" type="number" min="1" step="0.5" />
            </label>
            <label>
              maxHoldingBars / 最大持有快照
              <input v-model.number="backtestForm.maxHoldingBars" type="number" min="1" />
            </label>
            <label>
              takeProfitPct / 止盈比例
              <input v-model.number="backtestForm.takeProfitPct" type="number" step="0.01" />
            </label>
            <label>
              stopLossPct / 止损比例
              <input v-model.number="backtestForm.stopLossPct" type="number" step="0.01" />
            </label>
            <label>
              feeRate / 手续费率
              <input v-model.number="backtestForm.feeRate" type="number" min="0" step="0.0001" />
            </label>
            <label>
              stampTaxRate / 印花税率
              <input v-model.number="backtestForm.stampTaxRate" type="number" min="0" step="0.0001" />
            </label>
            <label>
              slippageRate / 滑点率
              <input v-model.number="backtestForm.slippageRate" type="number" min="0" step="0.0001" />
            </label>
            <label>
              volumeParticipationRate / 成交量参与率
              <input v-model.number="backtestForm.volumeParticipationRate" type="number" min="0" max="1" step="0.01" />
            </label>
            <label>
              orderBookParticipationRate / 盘口参与率
              <input v-model.number="backtestForm.orderBookParticipationRate" type="number" min="0" max="1" step="0.01" />
            </label>
            <label>
              intrabarAmbiguity / 盘中止盈止损优先
              <select v-model="backtestForm.intrabarAmbiguity">
                <option value="stop_first">stop_first / 同时触发先止损</option>
                <option value="take_first">take_first / 同时触发先止盈</option>
              </select>
            </label>
            <label class="check-row">
              <input v-model="backtestForm.enforceT1" type="checkbox" />
              enforceT1 / T+1
            </label>
            <label class="check-row">
              <input v-model="backtestForm.useOrderBookPrice" type="checkbox" />
              useOrderBookPrice / 盘口价优先
            </label>
            <label class="check-row">
              <input v-model="backtestForm.enforceLimitStatus" type="checkbox" />
              enforceLimitStatus / 涨跌停约束
            </label>
            <label class="check-row">
              <input v-model="backtestForm.enforceVolumeLimit" type="checkbox" />
              enforceVolumeLimit / 成交量容量约束
            </label>
            <label class="check-row">
              <input v-model="backtestForm.enforceOrderBookQueue" type="checkbox" />
              enforceOrderBookQueue / 盘口队列约束
            </label>
            <label class="check-row">
              <input v-model="backtestForm.allowPartialFills" type="checkbox" />
              allowPartialFills / 允许部分成交
            </label>
            <label class="check-row">
              <input v-model="backtestForm.useIntrabarStops" type="checkbox" />
              useIntrabarStops / 盘中止盈止损
            </label>
            <label>
              momentumPeriods / 动量周期
              <input
                :value="backtestForm.momentumPeriods.join(',')"
                type="text"
                @input="backtestForm.momentumPeriods = parseNumberList(($event.target as HTMLInputElement).value)"
              />
            </label>
            <label>
              macdFast / MACD 快线
              <input v-model.number="backtestForm.macdFast" type="number" min="1" />
            </label>
            <label>
              macdSlow / MACD 慢线
              <input v-model.number="backtestForm.macdSlow" type="number" min="1" />
            </label>
            <label>
              macdSignal / MACD 信号线
              <input v-model.number="backtestForm.macdSignal" type="number" min="1" />
            </label>
          </div>
          <div class="button-row">
            <button
              type="button"
              class="primary"
              :disabled="backtestState.status === 'loading'"
              @click="runBacktest"
            >
              {{ backtestState.status === "loading" ? "回测中..." : "启动回测" }}
            </button>
            <button type="button" @click="activeTab = 'report'">查看报告</button>
          </div>
          <div class="inline-note">
            {{ strategyOptions.find((option) => option.value === backtestForm.strategyName)?.description }}
          </div>
          <div v-if="backtestState.status === 'loading'" class="inline-note">
            回测计算中，SQLite 派生数据集会先生成 RankTrend 信号，再做交易模拟和后验统计。
          </div>
          <div v-if="backtestState.status === 'error'" class="inline-error">
            {{ backtestState.error }}
          </div>
          <div class="json-box-wrap">
            <button
              type="button"
              class="copy-button"
              @click="copyJsonBox('backtest', backtestState.raw || backtestState.data)"
            >
              {{ copyLabel("backtest") }}
            </button>
            <pre class="json-box">{{ jsonPreview(backtestState.raw || backtestState.data) }}</pre>
          </div>
        </section>

        <section v-if="activeTab === 'optimization'" class="tab-panel">
          <div class="section-heading">
            <h2>参数优化</h2>
            <span class="status-pill" :class="statusClass(optimizationState.status)">
              {{ optimizationState.status }}
            </span>
          </div>
          <div class="form-grid">
            <label>
              datasetId / 数据集ID
              <input v-model="optimizationForm.datasetId" type="text" />
            </label>
            <label>
              method / 搜索方法
              <select v-model="optimizationForm.method">
                <option value="grid">grid / 网格搜索</option>
                <option value="random">random / 随机搜索</option>
                <option value="bayesian">bayesian / 高斯过程贝叶斯搜索</option>
                <option value="tpe">tpe / TPE 搜索</option>
              </select>
            </label>
            <label>
              strategy / 策略
              <select v-model="optimizationForm.strategyName">
                <option v-for="option in strategyOptions" :key="option.value" :value="option.value">
                  {{ option.label }} / {{ option.value }}
                </option>
              </select>
            </label>
            <label>
              objective / 优化目标
              <select v-model="optimizationForm.objective">
                <option value="stability">stability / 样本外稳定</option>
                <option value="risk_adjusted">risk_adjusted / 风险调整</option>
                <option value="sharpe">sharpe / 夏普比率</option>
                <option value="return">return / 收益率</option>
                <option value="max_drawdown">max_drawdown / 最大回撤</option>
                <option value="win_rate">win_rate / 胜率</option>
              </select>
            </label>
            <label>
              trials / 试验次数
              <input v-model.number="optimizationForm.trials" type="number" min="1" />
            </label>
            <label>
              randomSeed / 随机种子
              <input v-model.number="optimizationForm.randomSeed" type="number" />
            </label>
            <label>
              validation / 样本外验证
              <select v-model="optimizationForm.validationMode">
                <option value="auto">auto / 按时间后段验证</option>
                <option value="none">none / 全样本试跑</option>
              </select>
            </label>
            <label>
              validationRatio / 验证比例
              <input v-model.number="optimizationForm.validationRatio" type="number" min="0.05" max="0.8" step="0.05" />
            </label>
            <label>
              warmupBars / 验证预热 bars
              <input v-model.number="optimizationForm.validationWarmupBars" type="number" min="0" />
            </label>
            <label class="check-row">
              <input v-model="optimizationForm.walkForward.enabled" type="checkbox" />
              walk-forward / 滚动验证
            </label>
            <label>
              WF train days
              <input v-model.number="optimizationForm.walkForward.trainWindowDays" type="number" min="1" />
            </label>
            <label>
              WF validation days
              <input v-model.number="optimizationForm.walkForward.validationWindowDays" type="number" min="1" />
            </label>
            <label>
              WF top trials
              <input v-model.number="optimizationForm.walkForward.topTrials" type="number" min="1" />
            </label>
            <label>
              momentumPeriods / 动量周期组
              <input v-model="gridInputs.momentumPeriods" type="text" />
            </label>
            <label>
              takeProfitPct / 止盈比例
              <input v-model="gridInputs.takeProfitPct" type="text" />
            </label>
            <label>
              stopLossPct / 止损比例
              <input v-model="gridInputs.stopLossPct" type="text" />
            </label>
            <label>
              maxPositions / 最大持仓数
              <input v-model="gridInputs.maxPositions" type="text" />
            </label>
          </div>
          <div class="button-row">
            <button
              type="button"
              class="primary"
              :disabled="optimizationState.status === 'loading' || optimizationState.status === 'running'"
              @click="runOptimization"
            >
              {{ optimizationState.status === "loading" || optimizationState.status === "running" ? "优化中..." : "启动优化" }}
            </button>
            <button type="button" :disabled="optimizationDetailState.status === 'loading'" @click="fetchOptimization">
              {{ optimizationDetailState.status === "loading" ? "拉取中..." : "拉取优化详情" }}
            </button>
          </div>
          <div v-if="optimizationState.status === 'loading' || optimizationState.status === 'running'" class="inline-note">
            参数优化会按组合重复执行 train/validation 回测；真实数据集建议先把 trials / 试验次数降到 3-6 做试跑。
            <span v-if="optimizationPollMessage"> {{ optimizationPollMessage }}</span>
          </div>
          <div v-else-if="optimizationPollMessage" class="inline-note">
            {{ optimizationPollMessage }}
          </div>
          <div v-if="optimizationRunId" class="inline-note">
            <b>优化 run：</b>{{ optimizationRunId }}
            <span v-if="optimizationRunStatus">，后端状态 {{ optimizationRunStatus }}</span>
          </div>
          <div v-if="optimizationState.status === 'error'" class="inline-error">
            {{ optimizationState.error }}
          </div>
          <div v-if="optimizationDetailState.status === 'error'" class="inline-error">
            {{ optimizationDetailState.error }}
          </div>
          <div v-if="Object.keys(optimizationExperiment).length" class="optimization-summary">
            <div>
              <span>执行 trial</span>
              <b>{{ optimizationExperiment.executedCandidateCount ?? optimizationTrials.length }}</b>
            </div>
            <div>
              <span>总候选</span>
              <b>{{ optimizationExperiment.totalCandidateCount ?? "-" }}</b>
            </div>
            <div>
              <span>验证模式</span>
              <b>{{ getNestedString(optimizationExperiment, ["split", "mode"]) || "-" }}</b>
            </div>
            <div>
              <span>过拟合风险</span>
              <b>{{ optimizationRiskLevel || "-" }}</b>
            </div>
            <div>
              <span>最佳 trial</span>
              <b>{{ getNestedString(optimizationSource, ["best", "trialId"]) || "-" }}</b>
            </div>
            <div>
              <span>WF 分段</span>
              <b>{{ walkForward.segmentCount ?? 0 }}</b>
            </div>
            <div>
              <span>WF 正收益率</span>
              <b>{{ formatPercent(getNestedNumber(walkForwardAggregate, ["positiveReturnSegmentRate"])) }}</b>
            </div>
          </div>
          <div v-if="optimizationRiskReason || optimizationWarnings.length" class="inline-note">
            <b>实验提示：</b>
            {{ optimizationRiskReason }}
            <span v-if="optimizationWarnings.length"> {{ optimizationWarnings.join("；") }}</span>
          </div>
          <div v-if="Object.keys(optimizationDataQuality).length" class="inline-note">
            <b>数据质量：</b>
            {{ optimizationDataQuality.researchGrade || "-" }}，
            低热榜 {{ optimizationDataQuality.lowHotlistCount ?? 0 }} 个，
            样本 OK {{ formatPercent(Number(optimizationDataQuality.sampleOkShare)) }}。
            {{ optimizationDataQuality.recommendation || "" }}
          </div>
          <div v-if="optimizationTrials.length" class="section-block">
            <h3>trial 追溯</h3>
            <div class="table-wrap optimization-table">
              <table>
                <thead>
                  <tr>
                    <th>排名</th>
                    <th>trial</th>
                    <th>score</th>
                    <th>train 收益</th>
                    <th>validation 收益</th>
                    <th>validation Sharpe</th>
                    <th>验证交易</th>
                    <th>风险</th>
                    <th>回测 run</th>
                    <th>参数</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="trial in optimizationTrials.slice(0, 20)" :key="String(trial.trialId || trial.trial_id)">
                    <td>{{ trial.rank ?? "-" }}</td>
                    <td>{{ trial.trialId || trial.trial_id }}</td>
                    <td>{{ formatNumber(Number(trial.score), 4) }}</td>
                    <td>{{ formatPercent(getNestedNumber(trial, ["train", "metrics", "totalReturn"])) }}</td>
                    <td>{{ formatPercent(getNestedNumber(trial, ["validation", "metrics", "totalReturn"])) }}</td>
                    <td>{{ formatNumber(getNestedNumber(trial, ["validation", "metrics", "sharpe"])) }}</td>
                    <td>{{ getNestedNumber(trial, ["validation", "metrics", "tradeCount"]) ?? "-" }}</td>
                    <td>{{ getNestedString(trial, ["scoreDetails", "overfitRisk"]) || getNestedString(trial, ["stability", "overfitRisk"]) || "-" }}</td>
                    <td class="mono-cell">
                      <div>train {{ shortId(getNestedString(trial, ["train", "runId"])) }}</div>
                      <div>valid {{ shortId(getNestedString(trial, ["validation", "runId"])) }}</div>
                    </td>
                    <td>{{ formatTrialParameters(trial.parameters) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
          <div v-if="parameterStabilityRows.length" class="section-block">
            <h3>参数稳定性</h3>
            <div class="table-wrap compact-table">
              <table>
                <thead>
                  <tr>
                    <th>参数</th>
                    <th>最佳值</th>
                    <th>Top 取值数</th>
                    <th>Top 分布</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="row in parameterStabilityRows" :key="String(row.key)">
                    <td>{{ row.key }}</td>
                    <td>{{ row.bestValue }}</td>
                    <td>{{ row.uniqueCount }}</td>
                    <td>{{ formatTopValues(row.topValues) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
          <div class="json-box-wrap">
            <button
              type="button"
              class="copy-button"
              @click="copyJsonBox('optimization', optimizationDetailState.raw || optimizationState.raw)"
            >
              {{ copyLabel("optimization") }}
            </button>
            <pre class="json-box">{{ jsonPreview(optimizationDetailState.raw || optimizationState.raw) }}</pre>
          </div>
        </section>

        <section v-if="activeTab === 'report'" class="tab-panel">
          <div class="section-heading">
            <h2>回测报告</h2>
            <span class="status-pill" :class="statusClass(backtestDetailState.status)">
              {{ backtestDetailState.status }}
            </span>
          </div>
          <div class="lookup-row">
            <input v-model="manualBacktestId" type="text" placeholder="backtest id" />
            <button type="button" :disabled="backtestDetailState.status === 'loading'" @click="fetchBacktest">
              {{ backtestDetailState.status === "loading" ? "拉取中..." : "拉取报告" }}
            </button>
          </div>
          <div v-if="backtestDetailState.status === 'loading'" class="inline-note">
            正在读取兼容报告和归一化明细。
          </div>
          <div v-if="backtestDetailState.status === 'error'" class="inline-error">
            {{ backtestDetailState.error }}
          </div>
          <div v-if="backtestNormalizedState.status === 'loading'" class="inline-note">
            正在读取 trades / equity / signals / quality 明细。
          </div>
          <div v-else-if="backtestNormalizedState.status === 'error'" class="inline-error">
            明细读取失败：{{ backtestNormalizedState.error }}。当前仅展示兼容摘要。
          </div>
          <div v-else-if="backtestNormalizedState.status === 'ok'" class="inline-note">
            已读取归一化明细：交易 {{ normalizedReportMeta.tradeTotal ?? trades.length }} 条，信号
            {{ normalizedReportMeta.signalTotal ?? normalizedSignals.length }} 条。
          </div>
          <div class="report-verdict" :class="reportVerdict.tone">
            <div>
              <span>报告结论</span>
              <b>{{ reportVerdict.label }}</b>
              <p>{{ reportVerdict.summary }}</p>
            </div>
            <div class="verdict-tags">
              <span>{{ reportVerdict.performanceLabel }}</span>
              <span>{{ reportVerdict.tradeLabel }}</span>
              <span>质量 {{ reportVerdict.qualityLabel }}</span>
              <span v-if="getNestedString(reportSource, ['snapshotType']) === 'quarter_hour'">quarter_hour</span>
            </div>
            <ul v-if="reportVerdict.reasons.length" class="narrative-list">
              <li v-for="reason in reportVerdict.reasons" :key="reason">{{ reason }}</li>
            </ul>
          </div>

          <div class="report-kpi-groups">
            <div class="section-block">
              <h3>收益表现</h3>
              <div class="diagnostic-grid compact-diagnostic">
                <div><span>总收益</span><b>{{ formatPercent(reportMetrics.totalReturn) }}</b></div>
                <div><span>已实现收益</span><b>{{ formatPercent(reportMetrics.realizedReturn) }}</b></div>
                <div><span>持仓盯市盈亏</span><b>{{ formatNumber(reportMetrics.unrealizedMarkProfit) }}</b></div>
                <div><span>预估平仓成本</span><b>{{ formatNumber(reportMetrics.unrealizedExitCost) }}</b></div>
                <div><span>预估平仓后盈亏</span><b>{{ formatNumber(reportMetrics.unrealizedProfit) }}</b></div>
              </div>
            </div>
            <div class="section-block">
              <h3>风险表现</h3>
              <div class="diagnostic-grid compact-diagnostic">
                <div><span>最大回撤</span><b>{{ formatPercent(reportMetrics.maxDrawdown) }}</b></div>
                <div><span>Sharpe</span><b>{{ formatNumber(reportMetrics.sharpe) }}</b></div>
                <div><span>胜率</span><b>{{ formatPercent(reportMetrics.winRate) }}</b></div>
                <div><span>回撤深度</span><b>{{ Number(reportMetrics.maxDrawdown) < -0.1 ? "严重" : Number(reportMetrics.maxDrawdown) < -0.03 ? "中等" : "轻微" }}</b></div>
              </div>
            </div>
            <div class="section-block">
              <h3>交易活跃度</h3>
              <div class="diagnostic-grid compact-diagnostic">
                <div><span>交易数</span><b>{{ reportMetrics.tradeCount ?? trades.length }}</b></div>
                <div><span>买入尝试</span><b>{{ matchingDiagnostics.buyAttempts ?? 0 }}</b></div>
                <div><span>买入成交</span><b>{{ matchingDiagnostics.buyFilled ?? 0 }}</b></div>
                <div><span>未成交订单</span><b>{{ matchingDiagnostics.skippedOrderCount ?? 0 }}</b></div>
                <div><span>未平仓</span><b>{{ reportMetrics.openPositionCount ?? "-" }}</b></div>
              </div>
            </div>
            <div class="section-block">
              <h3>可复现信息</h3>
              <div class="diagnostic-grid compact-diagnostic">
                <div><span>dataset</span><b>{{ getNestedString(reportSource, ["datasetId"]) || "-" }}</b></div>
                <div><span>snapshot</span><b>{{ getNestedString(reportSource, ["snapshotType"]) || "-" }}</b></div>
                <div><span>strategy</span><b>{{ getNestedString(reportSource, ["strategyName"]) || "-" }}</b></div>
                <div><span>version</span><b>{{ getNestedString(reportSource, ["strategyVersion"]) || "-" }}</b></div>
                <div><span>config</span><b>{{ shortId(getNestedString(reportSource, ["configHash"])) }}</b></div>
                <div><span>seed</span><b>{{ getNestedString(reportSource, ["randomSeed"]) || "-" }}</b></div>
              </div>
            </div>
          </div>

          <div class="report-chart-grid">
            <div class="section-block">
              <h3>净值曲线</h3>
              <div class="chart-panel small-chart">
                <svg viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label="权益曲线">
                  <polyline v-if="equityPolyline" :points="equityPolyline" />
                </svg>
                <div v-if="!equityPolyline" class="empty-state">权益曲线为空，无法绘制。请确认该 run 是否已写入 backtest_equity_curve。</div>
                <div v-else-if="equityCurve.length < 2" class="empty-state">样本点不足，曲线仅供参考。</div>
              </div>
            </div>
            <div class="section-block">
              <h3>回撤曲线</h3>
              <div class="chart-panel small-chart drawdown-chart">
                <svg viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label="回撤曲线">
                  <polyline v-if="drawdownPolyline" :points="drawdownPolyline" />
                </svg>
                <div v-if="!drawdownPolyline" class="empty-state">权益点不足，无法计算回撤。</div>
              </div>
            </div>
            <div class="section-block">
              <h3>收益构成</h3>
              <div class="profit-stack">
                <div><span>已实现</span><b>{{ formatPercent(reportMetrics.realizedReturn) }}</b></div>
                <div><span>未实现</span><b>{{ formatNumber(reportMetrics.unrealizedMarkProfit) }}</b></div>
                <div><span>预估成本</span><b>{{ formatNumber(reportMetrics.unrealizedExitCost) }}</b></div>
              </div>
            </div>
          </div>

          <div class="report-tabs" role="tablist" aria-label="回测报告明细">
            <button
              v-for="tab in reportTabs"
              :key="tab.key"
              type="button"
              :class="{ active: activeReportTab === tab.key }"
              @click="activeReportTab = tab.key"
            >
              {{ tab.label }}
            </button>
          </div>

          <div v-if="activeReportTab === 'trades'" class="report-tab-panel">
            <div class="diagnostic-grid compact-diagnostic">
              <div><span>总交易数</span><b>{{ tradeSummary.total }}</b></div>
              <div><span>盈利交易</span><b>{{ tradeSummary.winning }}</b></div>
              <div><span>亏损交易</span><b>{{ tradeSummary.losing }}</b></div>
              <div><span>平均净收益</span><b>{{ formatPercent(tradeSummary.averageNetReturn) }}</b></div>
              <div><span>最大盈利</span><b>{{ formatNumber(tradeSummary.maxProfit) }}</b></div>
              <div><span>最大亏损</span><b>{{ formatNumber(tradeSummary.maxLoss) }}</b></div>
            </div>
            <div v-if="!trades.length" class="empty-explanation">
              <b>没有真实成交</b>
              <p>可能原因：候选不足、涨停不可买、流动性不足、T+1 限制或样本质量降级。</p>
              <button type="button" @click="activeReportTab = 'signals'">查看信号解释</button>
              <button type="button" @click="activeReportTab = 'matching'">查看撮合诊断</button>
            </div>
            <div v-else class="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>股票</th>
                    <th>入场</th>
                    <th>出场</th>
                    <th>数量</th>
                    <th>净收益</th>
                    <th>利润</th>
                    <th>持有 bars</th>
                    <th>分层</th>
                    <th>阶段/环境</th>
                    <th>退出原因</th>
                    <th>成交细节</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="trade in (trades as BacktestTrade[]).slice(0, 80)" :key="`${trade.id}-${trade.code}`">
                    <td><b>{{ trade.code || "-" }}</b><br /><small>{{ trade.name || "-" }}</small></td>
                    <td>{{ trade.entryTradingDate || formatDisplayTime(String(trade.entryTime || "")) }}<br />{{ formatPrice(Number(trade.entryPrice)) }}</td>
                    <td>{{ trade.exitTradingDate || formatDisplayTime(String(trade.exitTime || "")) }}<br />{{ formatPrice(Number(trade.exitPrice)) }}</td>
                    <td>{{ trade.quantity ?? "-" }}</td>
                    <td>{{ formatPercent(Number(trade.netReturn)) }}</td>
                    <td>{{ formatNumber(Number(trade.profit)) }}</td>
                    <td>{{ trade.holdingBars ?? "-" }}</td>
                    <td>{{ trade.candidateTier || "-" }}</td>
                    <td>{{ trade.stage || "-" }} / {{ trade.regime || "-" }}</td>
                    <td>{{ trade.reason || "-" }}</td>
                    <td>{{ trade.fillDetail ? Object.keys(trade.fillDetail).slice(0, 3).join(" / ") : "-" }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div v-if="Number(normalizedReportMeta.tradeTotal || 0) > trades.length" class="inline-note">
              当前仅显示前 {{ trades.length }} 条，共 {{ normalizedReportMeta.tradeTotal }} 条。
            </div>
          </div>

          <div v-if="activeReportTab === 'signals'" class="report-tab-panel">
            <div class="inline-note">信号解释展示策略判断，不代表真实成交。真实成交请查看交易明细。</div>
            <div class="diagnostic-grid compact-diagnostic">
              <div><span>信号总数</span><b>{{ signalSummary.total }}</b></div>
              <div><span>强候选 A_MAIN</span><b>{{ signalSummary.strongCandidates }}</b></div>
              <div><span>观察 B_IGNITION</span><b>{{ signalSummary.watchCandidates }}</b></div>
              <div><span>剔除/风险候选</span><b>{{ signalSummary.excludedCandidates }}</b></div>
              <div><span>buy</span><b>{{ signalSummary.signalCounts.buy || 0 }}</b></div>
              <div><span>watch</span><b>{{ signalSummary.signalCounts.watch || 0 }}</b></div>
            </div>
            <div class="filter-row">
              <select v-model="signalTierFilter">
                <option value="">全部分层</option>
                <option value="A_MAIN">A_MAIN</option>
                <option value="B_IGNITION">B_IGNITION</option>
                <option value="C_CROWDED">C_CROWDED</option>
                <option value="D_EXIT_RISK">D_EXIT_RISK</option>
                <option value="N_NEUTRAL">N_NEUTRAL</option>
              </select>
              <select v-model="signalTypeFilter">
                <option value="">全部信号</option>
                <option value="buy">buy</option>
                <option value="watch">watch</option>
                <option value="hold">hold</option>
                <option value="sell">sell</option>
              </select>
              <select v-model="signalRegimeFilter">
                <option value="">全部环境</option>
                <option v-for="regime in signalRegimeOptions" :key="regime" :value="regime">{{ regime }}</option>
              </select>
              <select v-model="signalRiskFilter">
                <option value="all">全部风险</option>
                <option value="risk">有风险</option>
                <option value="clean">无风险</option>
              </select>
            </div>
            <div v-if="signalSummary.riskTop.length" class="inline-note">
              <b>风险标记 Top：</b>{{ signalSummary.riskTop.map((item) => `${item.key} ${item.count}`).join("；") }}
            </div>
            <div class="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>快照</th>
                    <th>股票</th>
                    <th>分层</th>
                    <th>信号</th>
                    <th>置信度</th>
                    <th>排名</th>
                    <th>阶段/环境</th>
                    <th>风险标记</th>
                    <th>原因</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="signal in filteredSignals.slice(0, 120)" :key="`${signal.id}-${signal.snapshotId}-${signal.code}`">
                    <td>{{ shortId(signal.snapshotId) }}</td>
                    <td><b>{{ signal.code || "-" }}</b><br /><small>{{ signal.name || "-" }}</small></td>
                    <td>{{ signal.candidateTier || "-" }}</td>
                    <td>{{ signal.signal || "-" }}</td>
                    <td>{{ formatNumber(Number(signal.confidence)) }}</td>
                    <td>{{ signal.rank ?? "-" }}</td>
                    <td>{{ signal.stage || "-" }} / {{ signal.regime || "-" }}</td>
                    <td>{{ signal.riskFlags?.length ? signal.riskFlags.slice(0, 3).join("；") : "-" }}</td>
                    <td>{{ signal.reasons?.length ? signal.reasons.slice(0, 3).join("；") : "-" }}</td>
                  </tr>
                  <tr v-if="!filteredSignals.length"><td colspan="9" class="empty-cell">没有符合筛选条件的信号。</td></tr>
                </tbody>
              </table>
            </div>
            <div v-if="Number(normalizedReportMeta.signalTotal || 0) > normalizedSignals.length" class="inline-note">
              当前仅显示前 {{ normalizedSignals.length }} 条，共 {{ normalizedReportMeta.signalTotal }} 条。
            </div>
          </div>
          <div v-if="activeReportTab === 'quality'" class="report-tab-panel">
            <div v-if="Object.keys(dataQuality).length" class="section-block quality-block">
              <h3>样本覆盖</h3>
              <div class="diagnostic-grid compact-diagnostic">
                <div><span>研究等级</span><b>{{ dataQuality.researchGrade || qualityReport?.researchGrade || "-" }}</b></div>
                <div><span>质量状态</span><b>{{ dataQuality.severity || qualityReport?.severity || "-" }}</b></div>
                <div><span>运行快照</span><b>{{ dataQuality.snapshotCount ?? qualityReport?.frameCount ?? "-" }} / {{ dataQuality.sourceSnapshotCount ?? qualityReport?.frameCount ?? "-" }}</b></div>
                <div><span>低热榜快照</span><b>{{ dataQuality.lowHotlistCount ?? 0 }}</b></div>
                <div><span>剔除空热榜</span><b>{{ dataQuality.droppedEmptyHotlistSnapshots ?? 0 }}</b></div>
                <div><span>覆盖率</span><b>{{ formatPercent(Number(qualityReport?.coverageRatio)) }}</b></div>
                <div><span>低热榜占比</span><b>{{ formatPercent(Number(dataQuality.lowHotlistShare)) }}</b></div>
                <div><span>样本 OK 占比</span><b>{{ formatPercent(Number(dataQuality.sampleOkShare)) }}</b></div>
              </div>
              <h3>异常数据</h3>
              <div class="diagnostic-grid compact-diagnostic">
                <div><span>NaN 字段</span><b>{{ Object.keys(qualityReport?.nanCounts || {}).length }}</b></div>
                <div><span>Infinity 字段</span><b>{{ Object.keys(qualityReport?.infCounts || {}).length }}</b></div>
                <div><span>负价格</span><b>{{ qualityReport?.negativePriceCount ?? 0 }}</b></div>
                <div><span>非正价格</span><b>{{ qualityReport?.nonPositivePriceCount ?? 0 }}</b></div>
                <div><span>负成交量</span><b>{{ qualityReport?.negativeVolumeCount ?? 0 }}</b></div>
                <div><span>时间修复</span><b>{{ qualityReport?.timeOrderFixed ? `是 / ${qualityReport.timeOrderFixCount || 0}` : "否" }}</b></div>
              </div>
              <div class="inline-note"><b>建议：</b>{{ dataQuality.recommendation || "暂无质量建议" }}</div>
              <ul v-if="qualityNarratives.length" class="narrative-list">
                <li v-for="item in qualityNarratives" :key="item">{{ item }}</li>
              </ul>
              <div v-if="dataQualityExamples.length" class="table-wrap compact-table">
                <table>
                  <thead><tr><th>日期</th><th>时间</th><th>热榜行数</th><th>snapshotId</th></tr></thead>
                  <tbody>
                    <tr v-for="row in dataQualityExamples" :key="String(row.snapshotId)">
                      <td>{{ row.tradingDate || "-" }}</td>
                      <td>{{ row.slotTime || "-" }}</td>
                      <td>{{ row.stockRowCount ?? "-" }}</td>
                      <td>{{ row.snapshotId }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
            <div v-else class="empty-explanation"><b>没有质量报告</b><p>兼容报告和归一化 quality 端点都没有返回质量信息。</p></div>
          </div>

          <div v-if="activeReportTab === 'controls'" class="report-tab-panel">
            <ul class="narrative-list">
              <li v-for="item in controlConclusions" :key="item">{{ item }}</li>
            </ul>
            <div v-if="controlBacktests.length" class="table-wrap compact-table">
              <table>
                <thead>
                  <tr>
                    <th>对照组</th>
                    <th>说明</th>
                    <th>总收益</th>
                    <th>Sharpe</th>
                    <th>最大回撤</th>
                    <th>胜率</th>
                    <th>交易数</th>
                    <th>未平仓</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="row in controlBacktests" :key="String(row.key)">
                    <td>{{ row.label || row.key }}</td>
                    <td>{{ row.description }}</td>
                    <td>{{ formatPercent(Number(row.totalReturn)) }}</td>
                    <td>{{ formatNumber(Number(row.sharpe)) }}</td>
                    <td>{{ formatPercent(Number(row.maxDrawdown)) }}</td>
                    <td>{{ formatPercent(Number(row.winRate)) }}</td>
                    <td>{{ row.tradeCount ?? "-" }}</td>
                    <td>{{ row.openPositionCount ?? "-" }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div v-else class="empty-explanation"><b>没有对照组</b><p>当前报告没有返回 controlBacktests。</p></div>
          </div>

          <div v-if="activeReportTab === 'matching'" class="report-tab-panel">
            <div v-if="Object.keys(matchingDiagnostics).length" class="section-block">
              <h3>撮合诊断</h3>
              <div class="diagnostic-grid compact-diagnostic">
                <div><span>买入尝试</span><b>{{ matchingDiagnostics.buyAttempts ?? 0 }}</b></div>
                <div><span>买入成交</span><b>{{ matchingDiagnostics.buyFilled ?? 0 }}</b></div>
                <div><span>卖出尝试</span><b>{{ matchingDiagnostics.sellAttempts ?? 0 }}</b></div>
                <div><span>未成交订单</span><b>{{ matchingDiagnostics.skippedOrderCount ?? 0 }}</b></div>
                <div><span>盘口覆盖</span><b>{{ formatPercent(Number(matchingDiagnostics.orderBookCoverage)) }}</b></div>
                <div><span>快照价回退</span><b>{{ formatPercent(Number(matchingDiagnostics.snapshotFallbackRate)) }}</b></div>
              </div>
              <div v-if="Number(matchingDiagnostics.buyAttempts || 0) > 0 && Number(matchingDiagnostics.buyFilled || 0) === 0" class="inline-note">
                策略产生过买入意图，但全部被撮合约束过滤。
              </div>
              <div v-if="Number(matchingDiagnostics.snapshotFallbackRate || 0) > 0.5" class="inline-note">
                大量成交依赖快照价回退，盘口数据不足。
              </div>
              <div v-if="Number(matchingDiagnostics.orderBookCoverage || 0) < 0.5" class="inline-note">
                盘口覆盖不足，成交质量需要降权。
              </div>
              <div v-if="matchingWarnings.length" class="inline-note"><b>撮合提示：</b>{{ matchingWarnings.join("；") }}</div>
              <div v-if="matchingSkippedReasons.length" class="table-wrap compact-table">
                <table>
                  <thead><tr><th>未成交原因</th><th>次数</th></tr></thead>
                  <tbody>
                    <tr v-for="row in matchingSkippedReasons" :key="String(row.reason)">
                      <td>{{ row.reason }}</td>
                      <td>{{ row.count }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
            <div v-else class="empty-explanation"><b>没有撮合诊断</b><p>当前报告没有返回 matchingDiagnostics。</p></div>
            <div v-if="tradeDiagnosticsReasons.length || tradeDiagnosticsTiers.length" class="section-block">
              <h3>交易贡献分析</h3>
              <div class="two-column">
                <div class="table-wrap compact-table">
                  <table>
                    <thead><tr><th>出场原因</th><th>次数</th><th>利润</th><th>均值</th><th>胜率</th></tr></thead>
                    <tbody>
                      <tr v-for="row in tradeDiagnosticsReasons" :key="String(row.key)">
                        <td>{{ row.key }}</td><td>{{ row.count }}</td><td>{{ formatNumber(Number(row.profit)) }}</td><td>{{ formatNumber(Number(row.avgProfit)) }}</td><td>{{ formatPercent(Number(row.winRate)) }}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
                <div class="table-wrap compact-table">
                  <table>
                    <thead><tr><th>RankTrend 分层</th><th>次数</th><th>利润</th><th>均值</th><th>胜率</th></tr></thead>
                    <tbody>
                      <tr v-for="row in tradeDiagnosticsTiers" :key="String(row.key)">
                        <td>{{ row.key }}</td><td>{{ row.count }}</td><td>{{ formatNumber(Number(row.profit)) }}</td><td>{{ formatNumber(Number(row.avgProfit)) }}</td><td>{{ formatPercent(Number(row.winRate)) }}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          </div>

          <div v-if="activeReportTab === 'config'" class="report-tab-panel">
            <div class="diagnostic-grid compact-diagnostic">
              <div><span>dataset</span><b>{{ getNestedString(reportSource, ["datasetId"]) || "-" }}</b></div>
              <div><span>snapshot</span><b>{{ getNestedString(reportSource, ["snapshotType"]) || "-" }}</b></div>
              <div><span>strategy</span><b>{{ getNestedString(reportSource, ["strategyName"]) || "-" }}</b></div>
              <div><span>version</span><b>{{ getNestedString(reportSource, ["strategyVersion"]) || "-" }}</b></div>
              <div><span>config</span><b>{{ shortId(getNestedString(reportSource, ["configHash"])) }}</b></div>
              <div><span>seed</span><b>{{ getNestedString(reportSource, ["randomSeed"]) || "-" }}</b></div>
              <div><span>start</span><b>{{ getNestedString(reportSource, ["dateStart"]) || "-" }}</b></div>
              <div><span>end</span><b>{{ getNestedString(reportSource, ["dateEnd"]) || "-" }}</b></div>
            </div>
            <button type="button" class="secondary-button" @click="showReportJson = !showReportJson">
              {{ showReportJson ? "收起 JSON 原文" : "展开 JSON 原文" }}
            </button>
            <div v-if="showReportJson" class="json-box-wrap">
              <button type="button" class="copy-button" @click="copyJsonBox('report', backtestDetailState.raw || reportSource)">
                {{ copyLabel("report") }}
              </button>
              <pre class="json-box">{{ jsonPreview(backtestDetailState.raw || reportSource) }}</pre>
            </div>
          </div>

        </section>

        <section v-if="activeTab === 'replay'" class="tab-panel">
          <div class="section-heading">
            <h2>单票回放解释</h2>
            <span>{{ replaySteps.length }} steps</span>
          </div>
          <div class="lookup-row">
            <input v-model="replayCode" type="text" placeholder="股票代码，可为空" />
            <button type="button" @click="fetchBacktest">刷新报告源</button>
          </div>
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>时间</th>
                  <th>代码</th>
                  <th>名称</th>
                  <th>动作</th>
                  <th>价格</th>
                  <th>排名</th>
                  <th>信心</th>
                  <th>持有</th>
                  <th>RankTrend</th>
                  <th>解释</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(step, index) in replaySteps" :key="`${step.time}-${step.code}-${index}`">
                  <td>{{ formatDisplayTime(step.time) }}</td>
                  <td>{{ step.code || "-" }}</td>
                  <td>{{ step.name || "-" }}</td>
                  <td>{{ step.action }}</td>
                  <td>{{ formatPrice(step.price) }}</td>
                  <td>{{ step.rank ?? "-" }}</td>
                  <td>{{ formatNumber(step.score) }}</td>
                  <td>{{ step.holdingBars ?? "-" }}</td>
                  <td>
                    <span class="tag-stack">
                      <span>{{ step.candidateTier || "-" }}</span>
                      <small>{{ step.stage || "-" }} / {{ step.regime || "-" }}</small>
                    </span>
                  </td>
                  <td>{{ step.reason }}</td>
                </tr>
                <tr v-if="!replaySteps.length">
                  <td colspan="10" class="empty-cell">
                    回测报告返回 trades/signals/decisions 后会在这里按股票代码过滤。
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      </section>
    </section>
  </main>
</template>
