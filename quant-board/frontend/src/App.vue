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
  formatTradeFill,
  formatTradeTime,
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

type TabKey = "golden" | "backtest" | "theme" | "optimization" | "report" | "replay" | "trends";
type ImportMode = "snapshot_store" | "json_file";

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
  },
  {
    value: "theme_rotation",
    label: "题材轮动",
    description: "基于题材生命周期买卖高暴露股票"
  },
  {
    value: "leader_theme_confirmation",
    label: "龙头题材确认",
    description: "龙头股须获得强题材确认才买入"
  },
  {
    value: "hotlist_theme_confluence",
    label: "热榜题材共振",
    description: "RankTrend + ThemeTrend 共振策略"
  }
];

const tabs: Array<{ key: TabKey; label: string }> = [
  { key: "golden", label: "Golden 对齐" },
  { key: "backtest", label: "回测运行" },
  { key: "theme", label: "ThemeTrend" },
  { key: "optimization", label: "参数优化" },
  { key: "report", label: "回测报告" },
  { key: "replay", label: "单票回放" },
  { key: "trends", label: "长测趋势" }
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
const deleteDatasetState = reactive<RequestResult>({ status: "idle" });

const selectedDatasetId = ref("");
const datasetRefreshAt = ref("");
const importMode = ref<ImportMode>("snapshot_store");
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
const checkpointList = ref<Array<Record<string, unknown>>>([]);
const checkpointLoading = ref(false);
const checkpointError = ref("");

async function fetchCheckpoints() {
  checkpointLoading.value = true;
  checkpointError.value = "";
  try {
    checkpointList.value = (await api.getCheckpoints(20)) as unknown as Array<Record<string, unknown>>;
  } catch (e: unknown) {
    checkpointError.value = e instanceof Error ? e.message : String(e);
  } finally {
    checkpointLoading.value = false;
  }
}

const recentCheckpoints = computed(() => [...checkpointList.value].reverse());
const latestCheckpoint = computed(() => recentCheckpoints.value[0] ?? null);

function checkpointNumber(value: unknown): number | null {
  if (value == null || value === '') {
    return null
  }
  const num = Number(value);
  return Number.isFinite(num) ? num : null;
}

function formatCheckpointPercent(value: unknown): string {
  const num = checkpointNumber(value);
  return num == null ? "-" : formatPercent(num);
}

function formatCheckpointFixed(value: unknown, digits = 2): string {
  const num = checkpointNumber(value);
  return num == null ? "-" : num.toFixed(digits);
}

function checkpointLabel(value: unknown, fallback: string): string {
  const label = String(value || "").trim();
  return label || fallback;
}

const h1CheckpointLabel = computed(() => checkpointLabel(latestCheckpoint.value?.h1Label, "H1"));
const h2CheckpointLabel = computed(() => checkpointLabel(latestCheckpoint.value?.h2Label, "H2"));
const e1CheckpointLabel = computed(() => checkpointLabel(latestCheckpoint.value?.e1Label, "E1"));
const q1CheckpointLabel = computed(() => checkpointLabel(latestCheckpoint.value?.q1Label, "Q1"));
const showQ1CheckpointColumns = computed(() => {
  const cp = latestCheckpoint.value;
  if (!cp) {
    return false;
  }
  const label = String(cp.q1Label || "").trim();
  return Boolean(label) || checkpointNumber(cp.q1TotalReturn) != null || checkpointNumber(cp.q1Sharpe) != null;
});

const activeReportTab = ref<BacktestReportTabKey>("trades");
const signalTierFilter = ref("");
const signalTypeFilter = ref("");
const signalRegimeFilter = ref("");
const signalRiskFilter = ref<"all" | "risk" | "clean">("all");
const showReportJson = ref(false);
const deleteBacktestMessage = ref("");
const deleteDatasetMessage = ref("");
let optimizationPollToken = 0;

// ── ThemeTrend 状态 ──
const themeState = reactive<RequestResult>({ status: "idle" });
const themeReportState = reactive<RequestResult<import("./types").ThemeTrendReport>>({ status: "idle" });
const themeResearchState = reactive<RequestResult<import("./types").ThemeResearchSummary>>({ status: "idle" });
const themeBacktestForm = reactive<import("./types").ThemeBacktestRequest>({
  datasetId: "",
  strategyName: "theme_rotation",
  snapshotType: "half_hour",
  randomSeed: 20260430,
  crowdingBlockThreshold: 75,
  maxPositions: 5,
  positionSize: 0.2,
});
const themeOptimizationForm = reactive<import("./types").ThemeOptimizationRequest>({
  datasetId: "",
  strategyName: "theme_rotation",
  snapshotType: "half_hour",
  method: "random",
  randomSeed: 20260430,
  trials: 12,
  objective: "stability",
});
const lastThemeBacktestId = ref("");
const manualThemeBacktestId = ref("");
const themeVerdict = computed(() => {
  if (themeState.status === "idle") {
    return { label: "待运行" };
  }
  if (themeState.status === "loading") {
    return { label: "运行中" };
  }
  if (themeState.status === "error") {
    return { label: "运行失败" };
  }
  const data = asRecord(themeState.data || themeState.raw);
  const result = asRecord(data?.result);
  const tt = asRecord(data?.themeTrend || result?.themeTrend);
  const quality = asRecord(data?.dataQuality || result?.dataQuality);
  const grade = String(quality?.researchGrade || "unknown");
  const signalCount = Number(tt?.signalCount || 0);
  return {
    label: grade === "research_ready" ? `研究就绪 · ${signalCount} 信号` : `质量降级(${grade}) · ${signalCount} 信号`
  };
});
const themeReport = computed(() => asRecord(themeReportState.data));
const themeLifecycleReturns = computed(() => {
  const dist = asRecord(themeReport.value.lifecycleReturnDistribution);
  return Object.entries(dist).map(([lifecycle, stats]) => ({ lifecycle, ...(asRecord(stats)) })) as Array<Record<string, unknown>>;
});
const themeTradeDiagnostics = computed(() => (themeReport.value.themeTradeDiagnostics as Array<Record<string, unknown>> | undefined) || []);
const themeTierDiagnostics = computed(() => (themeReport.value.candidateTierDiagnostics as Array<Record<string, unknown>> | undefined) || []);
const themeRoleDiagnostics = computed(() => (themeReport.value.roleDiagnostics as Array<Record<string, unknown>> | undefined) || []);
const themeCrowdingRiskDecay = computed(() => asRecord(themeReport.value.crowdingRiskDecay));

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
  useThemeFactorForExecution: false,
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
  maxPositions: "3,5,8",
  macdFast: "21",
  macdSlow: "34",
  macdSignal: "13"
});

const selectedDataset = computed(() => {
  return datasetsState.data?.find((dataset) => dataset.id === selectedDatasetId.value);
});

const canDeleteSelectedDataset = computed(() => {
  const dataset = selectedDataset.value;
  return Boolean(
    dataset &&
      dataset.id !== "dragonboard_live" &&
      dataset.source_type !== "dragon_board_runtime" &&
      deleteDatasetState.status !== "loading"
  );
});

const databaseStatus = computed(() => {
  const database = asRecord(health.data?.database);
  const primary = asRecord(database?.primary);
  return {
    mode: String(database?.mode || ""),
    primaryMode: String(primary?.mode || ""),
    connected: primary?.connected === true,
    lastError: typeof primary?.last_error === "string" ? primary.last_error : ""
  };
});

const isMongoMode = computed(() => {
  return databaseStatus.value.mode === "mongodb_primary" || databaseStatus.value.primaryMode === "mongodb";
});

const canUseSnapshotStore = computed(() => {
  return !isMongoMode.value || databaseStatus.value.connected;
});

const snapshotSourceOptions = computed(() => {
  const seen = new Set<string>();
  const options: Array<{ id: string; label: string }> = [];
  const add = (id: string, label?: string) => {
    if (!id || seen.has(id)) {
      return;
    }
    seen.add(id);
    options.push({ id, label: label || id });
  };
  add("dragonboard_live", "dragonboard_live / 正式快照主库");
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
  const baseDataQuality = getObjectField(base, ["dataQuality"]);
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
          ...baseDataQuality,
          ...quality,
          snapshotCount: baseDataQuality.snapshotCount ?? quality.frameCount,
          sourceSnapshotCount: baseDataQuality.sourceSnapshotCount ?? quality.frameCount,
          recommendation:
            baseDataQuality.recommendation ||
            (quality.researchGrade === "research_ready" ? "样本质量满足研究报告读取要求" : "样本质量存在降级，请结合 warnings 和覆盖率解释结果")
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
    return "刷新失败";
  }
  return `${datasetsState.data?.length || 0} 个`;
});

const importStatusLabel = computed(() => {
  if (importState.status === "loading" || snapshotCountsState.status === "loading") {
    return "处理中";
  }
  if (importState.status === "error" || snapshotCountsState.status === "error") {
    return "失败";
  }
  if (importState.status === "ok") {
    return "已生成";
  }
  if (snapshotCountsState.status === "ok") {
    return "已检查";
  }
  return "待执行";
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
  if (isMongoMode.value && !databaseStatus.value.connected) {
    return `MongoDB 主库未连接，无法读取数据集或生成研究数据集：${databaseStatus.value.lastError || "unknown error"}`;
  }
  if (importMode.value === "json_file") {
    return isMongoMode.value
      ? "MongoDB 迁移后 JSON 上传入口默认关闭；历史 JSON 请先走后端迁移/导入脚本，再进入 MongoDB 主库。"
      : "迁移辅助：只在需要导入历史 JSON/备份文件时使用。日常研究应优先使用快照主库。";
  }
  return isMongoMode.value
    ? "推荐：直接使用 MongoDB 主库中的正式快照数据集运行回测和优化；通常不需要再生成派生数据集。"
    : "推荐：从 QuantBoard 快照主库里的正式快照表生成研究数据集。DragonBoard 已经把正式快照写入后端主库，不再需要浏览器 IndexedDB/LevelDB/运行页桥接。";
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
const layer1SignalEfficacy = computed(() => {
  const raw = dataQuality.value.layer1SignalEfficacy;
  return raw && typeof raw === "object" ? (raw as Record<string, unknown>) : null;
});
const layer2ExecutionQuality = computed(() => {
  const raw = dataQuality.value.layer2ExecutionQuality;
  return raw && typeof raw === "object" && (raw as Record<string, unknown>).layer2Status
    ? (raw as Record<string, unknown>)
    : null;
});
const priceQualityDiagnostics = computed(() => {
  const rd = dataQuality.value.reportOnlyDiagnostics;
  return rd && typeof rd === "object" ? ((rd as Record<string, unknown>).priceQuality as Record<string, any> | null) : null;
});

const alignmentResult = ref<Record<string, unknown> | null>(null);
const alignmentLoading = ref(false);
const alignmentError = ref("");

async function fetchAlignment(runId: string) {
  if (!runId) return;
  alignmentLoading.value = true;
  alignmentError.value = "";
  try {
    alignmentResult.value = await api.getAlignment(runId);
  } catch (e: unknown) {
    alignmentError.value = e instanceof Error ? e.message : String(e);
    alignmentResult.value = null;
  } finally {
    alignmentLoading.value = false;
  }
}

watch(activeReportTab, (tab) => {
  if (tab === "alignment" && !alignmentResult.value) {
    const runId = getRunId(reportSource.value);
    if (runId) fetchAlignment(runId);
  }
});

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
  { key: "alignment", label: "实盘对齐" },
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
const optimizationBestTrial = computed(() => getObjectField(optimizationSource.value, ["best", "bestTrial", "best_trial"]));

const healthLabel = computed(() => {
  if (health.status === "ok") {
    const storage = isMongoMode.value ? "MongoDB" : "SQLite";
    const connection = canUseSnapshotStore.value ? "已连接" : "未连接";
    const version = health.data?.version ? ` · v${health.data.version}` : "";
    return `后端已连接 · ${storage}${connection}${version}`;
  }
  if (health.status === "error") {
    return `API 异常: ${health.error}`;
  }
  return health.status === "loading" ? "连接检查中" : "尚未检查";
});

const healthStatusClass = computed(() => {
  if (health.status === "ok" && !canUseSnapshotStore.value) {
    return "status-error";
  }
  return statusClass(health.status);
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

function statusLabel(
  status: string,
  overrides: Partial<Record<string, string>> = {}
): string {
  const normalized = String(status || "idle");
  const defaults: Record<string, string> = {
    idle: "待执行",
    loading: "进行中",
    running: "运行中",
    ok: "已完成",
    error: "失败",
    checked: "已检查"
  };
  return overrides[normalized] || defaults[normalized] || normalized;
}

function statusClass(status: string): string {
  return `status-${status}`;
}

function signalLightLabel(value: unknown): string {
  switch (String(value || "").toLowerCase()) {
    case "green":
      return "绿灯";
    case "yellow":
      return "黄灯";
    case "red":
      return "红灯";
    default:
      return "-";
  }
}

function formatSnapshotTypeLabel(value: unknown): string {
  switch (String(value || "")) {
    case "half_hour":
      return "半小时";
    case "quarter_hour":
      return "15分钟";
    default:
      return String(value || "-");
  }
}

function formatSignalActionLabel(value: unknown): string {
  switch (String(value || "")) {
    case "buy":
      return "买入";
    case "watch":
      return "观察";
    case "hold":
      return "持有";
    case "sell":
      return "卖出";
    default:
      return String(value || "-");
  }
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

function apiErrorRaw(error: unknown, fallback: string): Record<string, unknown> {
  if (error && typeof error === "object") {
    const detail =
      "body" in error
        ? asRecord((error as { body?: unknown }).body).detail
        : undefined;
    return {
      error: fallback,
      name: "name" in error ? String((error as { name?: unknown }).name || "Error") : "Error",
      message: "message" in error ? String((error as { message?: unknown }).message || fallback) : fallback,
      detail,
      body: "body" in error ? (error as { body?: unknown }).body : undefined
    };
  }
  return {
    error: fallback,
    name: error instanceof Error ? error.name : "Error",
    message: error instanceof Error ? error.message : String(error)
  };
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

function datasetFilters(dataset: DatasetSummary): Record<string, unknown> {
  const metadata = asRecord(dataset.metadata);
  return asRecord(metadata.filters);
}

function requestedDatasetRange(dataset: DatasetSummary): string {
  const filters = datasetFilters(dataset);
  const start = typeof filters.startDate === "string" && filters.startDate ? filters.startDate : dataset.start_date;
  const end = typeof filters.endDate === "string" && filters.endDate ? filters.endDate : dataset.end_date;
  return start && end ? `${start}~${end}` : "";
}

function actualDatasetRange(dataset: DatasetSummary): string {
  return dataset.start_date && dataset.end_date ? `${dataset.start_date}~${dataset.end_date}` : "";
}

function datasetDisplayName(dataset: DatasetSummary): string {
  const name = dataset.name || dataset.id;
  const shortId = dataset.id ? dataset.id.slice(-6) : "";
  const frames = dataset.frame_count ?? dataset.snapshot_count ?? 0;
  const requested = requestedDatasetRange(dataset);
  const actual = actualDatasetRange(dataset);
  const range = requested || actual || "无区间";
  const actualText = requested && actual && requested !== actual ? ` · 实际${actual}` : "";
  return `${name} · ${range}${actualText} · ${frames}帧 · ${shortId}`;
}

function datasetRange(dataset: DatasetSummary): string {
  const requested = requestedDatasetRange(dataset);
  const actual = actualDatasetRange(dataset);
  if (requested && actual && requested !== actual) {
    return `请求 ${requested} / 实际 ${actual}`;
  }
  return requested || actual || "-";
}

function shortId(value: unknown): string {
  const text = String(value || "");
  return text ? text.slice(0, 12) : "-";
}

function formatTrialParameters(value: unknown): string {
  const record = asRecord(value);
  const nested = asRecord(record.parameters || record.params || record.optunaParams);
  const parameters = Object.keys(nested).length ? nested : record;
  if (!Object.keys(parameters).length) {
    return "-";
  }
  return Object.entries(parameters)
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
    state.raw = apiErrorRaw(error, state.error);
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
  if (!canUseSnapshotStore.value) {
    snapshotCountsState.status = "error";
    snapshotCountsState.error = "MongoDB 主库未连接，无法检查快照源";
    return;
  }
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

  if (!canUseSnapshotStore.value) {
    importState.status = "error";
    importState.error = "MongoDB 主库未连接，无法生成研究数据集";
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
    const raw = importState.data as unknown;
    const data =
      raw && typeof raw === "object"
        ? ((raw as { dataset?: DatasetSummary } & Partial<DatasetSummary>).dataset ||
            (raw as Partial<DatasetSummary>))
        : undefined;
    if (data?.id) {
      selectedDatasetId.value = data.id;
    }
    await loadDatasets();
  }
}

async function deleteSelectedDataset(): Promise<void> {
  const datasetId = selectedDatasetId.value.trim();
  if (!datasetId) {
    deleteDatasetState.status = "error";
    deleteDatasetState.error = "请先选择要删除的数据集";
    deleteDatasetMessage.value = "";
    return;
  }
  if (!canDeleteSelectedDataset.value) {
    deleteDatasetState.status = "error";
    deleteDatasetState.error = "快照主库数据不能删除，只能删除派生/测试数据集";
    deleteDatasetMessage.value = "";
    return;
  }
  const confirmed = window.confirm(
    `确认删除派生/测试数据集 ${datasetId}？\n\n此操作会删除该数据集及其快照事实行，不会删除正式快照主库或已生成的回测、优化、题材研究结果。`
  );
  if (!confirmed) {
    return;
  }
  deleteDatasetState.status = "loading";
  deleteDatasetState.error = undefined;
  deleteDatasetState.data = undefined;
  deleteDatasetState.raw = undefined;
  deleteDatasetMessage.value = "";
  try {
    const result = await api.deleteDataset(datasetId);
    const deletedDatasets = result.deleted.datasets ?? 0;
    deleteDatasetState.status = "ok";
    deleteDatasetState.data = result;
    deleteDatasetState.raw = result;
    deleteDatasetMessage.value = `已删除 ${datasetId}，数据集记录 ${deletedDatasets} 条。`;
    if (sourceDatasetId.value === datasetId) {
      sourceDatasetId.value = "dragonboard_live";
    }
    await loadDatasets();
  } catch (error) {
    deleteDatasetState.status = "error";
    deleteDatasetState.error = formatApiError(error);
    deleteDatasetState.raw = apiErrorRaw(error, deleteDatasetState.error);
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

async function deleteCurrentBacktest(): Promise<void> {
  const id = manualBacktestId.value.trim() || lastBacktestId.value.trim();
  if (!id) {
    deleteBacktestMessage.value = "缺少回测 ID";
    return;
  }
  const confirmed = window.confirm(
    `确认删除回测 ${id}？\n\n此操作只删除 quant_board_research.db 中的本地研究结果，不会删除正式快照事实库。`
  );
  if (!confirmed) {
    return;
  }
  backtestDetailState.status = "loading";
  backtestDetailState.error = undefined;
  deleteBacktestMessage.value = "";
  try {
    const result = await api.deleteBacktest(id);
    const deletedRuns = result.deleted.backtest_runs ?? 0;
    deleteBacktestMessage.value = `已删除 ${id}，回测记录 ${deletedRuns} 条。`;
    backtestDetailState.status = "idle";
    backtestDetailState.data = undefined;
    backtestDetailState.raw = undefined;
    backtestNormalizedState.status = "idle";
    backtestNormalizedState.data = undefined;
    backtestNormalizedState.raw = undefined;
    manualBacktestId.value = "";
    if (lastBacktestId.value === id) {
      lastBacktestId.value = "";
    }
  } catch (error) {
    backtestDetailState.status = "error";
    backtestDetailState.error = formatApiError(error);
    deleteBacktestMessage.value = "";
  }
}

async function runOptimization(): Promise<void> {
  optimizationForm.parameterGrid = {
    momentumPeriods: parsePeriodGrid(gridInputs.momentumPeriods),
    takeProfitPct: parseNumberList(gridInputs.takeProfitPct),
    stopLossPct: parseNumberList(gridInputs.stopLossPct),
    maxPositions: parseNumberList(gridInputs.maxPositions)
  };
  // Phase 2 strategy params (only include if user provided values)
  const macdFast = parseNumberList(gridInputs.macdFast);
  const macdSlow = parseNumberList(gridInputs.macdSlow);
  const macdSignal = parseNumberList(gridInputs.macdSignal);
  if (macdFast.length) optimizationForm.parameterGrid.macdFast = macdFast;
  if (macdSlow.length) optimizationForm.parameterGrid.macdSlow = macdSlow;
  if (macdSignal.length) optimizationForm.parameterGrid.macdSignal = macdSignal;

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

watch(selectedDatasetId, (id) => {
  syncSelectedDataset(id);
  themeBacktestForm.datasetId = id;
  themeOptimizationForm.datasetId = id;
});

watch(isMongoMode, (enabled) => {
  if (enabled && importMode.value === "json_file") {
    importMode.value = "snapshot_store";
  }
});

// ── ThemeTrend handlers ──
async function runThemeBacktest(): Promise<void> {
  await runRequest(themeState, () => api.runThemeTrend({ ...themeBacktestForm, datasetId: selectedDatasetId.value || themeBacktestForm.datasetId }), (data) => {
    const id = getRunId(data);
    if (id) { lastThemeBacktestId.value = id; manualThemeBacktestId.value = id; }
  });
}
async function runThemeConfluence(): Promise<void> {
  await runRequest(themeState, () => api.runThemeConfluence({ ...themeBacktestForm, datasetId: selectedDatasetId.value || themeBacktestForm.datasetId }), (data) => {
    const id = getRunId(data);
    if (id) { lastThemeBacktestId.value = id; manualThemeBacktestId.value = id; }
  });
}
async function fetchThemeReport(): Promise<void> {
  const id = manualThemeBacktestId.value.trim() || lastThemeBacktestId.value.trim();
  if (!id) { themeReportState.status = "error"; themeReportState.error = "缺少回测 ID"; return; }
  await runRequest(themeReportState, () => api.getThemeReport(id));
}
async function loadThemeResearch(): Promise<void> {
  await runRequest(themeResearchState, () =>
    api.getThemeResearchSummary({ dataset_id: selectedDatasetId.value || "dragonboard_live", snapshot_type: "half_hour" }),
  );
}
async function runThemeOptimization(): Promise<void> {
  await runRequest(themeState, () => api.runThemeOptimization({ ...themeOptimizationForm, datasetId: selectedDatasetId.value || themeOptimizationForm.datasetId }), (data) => {
    const id = getRunId(data);
    if (id) { lastThemeBacktestId.value = id; manualThemeBacktestId.value = id; }
  });
}

onMounted(async () => {
  await checkHealth();
  await loadDatasets();
  fetchCheckpoints();
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
        <span class="status-pill" :class="healthStatusClass">{{ healthLabel }}</span>
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
              <option value="snapshot_store">快照主库</option>
              <option value="json_file" :disabled="isMongoMode">JSON 文件上传</option>
            </select>
          </label>
          <label v-if="importMode === 'json_file'">
            JSON 快照文件
            <input type="file" accept=".json,application/json" @change="selectJsonFile" />
          </label>
          <label v-if="importMode === 'snapshot_store'">
            源快照数据集
            <select v-model="sourceDatasetId">
              <option v-for="option in snapshotSourceOptions" :key="option.id" :value="option.id">
                {{ option.label }}
              </option>
            </select>
          </label>
          <label>
            数据集名
            <input v-model="datasetName" type="text" />
          </label>
          <label>
            快照类型
            <select v-model="importSnapshotType">
              <option value="half_hour">半小时</option>
              <option value="quarter_hour">15分钟</option>
            </select>
          </label>
          <div class="inline-note">
            {{ importHelpText }}
          </div>
          <template v-if="importMode === 'snapshot_store'">
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
                :disabled="importMode !== 'snapshot_store'"
              />
            </label>
            <label class="check-row">
              <input v-model="dryRunImport" type="checkbox" />
              试运行
            </label>
          </div>
          <div class="button-row">
            <button
              type="button"
              :disabled="importMode !== 'snapshot_store' || snapshotCountsState.status === 'loading' || !canUseSnapshotStore"
              @click="inspectSnapshotSource"
            >
              检查快照源
            </button>
            <button
              type="button"
              class="primary"
              :disabled="importState.status === 'loading' || (importMode === 'snapshot_store' && !canUseSnapshotStore)"
              @click="importDataset"
            >
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
              <span>快照帧</span>
            </div>
            <div>
              <b>{{ snapshotCounts.snapshot_stock_rows ?? 0 }}</b>
              <span>股票行</span>
            </div>
            <div>
              <b>{{ snapshotCounts.snapshot_sector_rows ?? 0 }}</b>
              <span>板块行</span>
            </div>
          </div>
          <div class="button-row dataset-delete-row">
            <button
              type="button"
              class="danger-button"
              :disabled="!canDeleteSelectedDataset"
              @click="deleteSelectedDataset"
            >
              {{ deleteDatasetState.status === "loading" ? "删除中" : "删除数据集" }}
            </button>
          </div>
          <div v-if="selectedDataset && !canDeleteSelectedDataset" class="inline-note">
            快照主库数据受保护，只能删除派生/测试数据集。
          </div>
          <div v-if="deleteDatasetState.status === 'error'" class="inline-error">
            {{ deleteDatasetState.error }}
          </div>
          <div v-if="deleteDatasetMessage" class="inline-note">
            {{ deleteDatasetMessage }}
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
              {{ statusLabel(goldenState.status) }}
            </span>
          </div>
          <div class="form-grid compact">
            <label>
              数据集 ID
              <input v-model="goldenForm.datasetId" type="text" />
            </label>
            <label>
              用例 ID
              <input v-model="goldenForm.caseId" type="text" />
            </label>
            <label>
              误差容忍
              <input v-model.number="goldenForm.tolerance" type="number" step="0.000001" />
            </label>
            <label>
              校验样本数
              <input v-model.number="goldenForm.sampleLimit" type="number" min="1" max="5000" />
            </label>
            <label class="check-row">
              <input v-model="goldenForm.strict" type="checkbox" />
              严格模式
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
              TS Golden JSON / TypeScript 基线文件
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
            请导入已生成的 TS Golden JSON 文件。导入后继续点击 `执行校验`。
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
              {{ statusLabel(backtestState.status) }}
            </span>
          </div>
          <div class="form-grid">
            <label>
              数据集 ID
              <input v-model="backtestForm.datasetId" type="text" />
            </label>
            <label>
              策略
              <select v-model="backtestForm.strategyName">
                <option v-for="option in strategyOptions" :key="option.value" :value="option.value">
                  {{ option.label }}
                </option>
              </select>
            </label>
            <label>
              快照类型
              <select v-model="backtestForm.snapshotType">
                <option value="quarter_hour">15分钟</option>
                <option value="half_hour">半小时</option>
              </select>
            </label>
            <label>
              随机种子
              <input v-model.number="backtestForm.randomSeed" type="number" />
            </label>
            <label>
              初始资金
              <input v-model.number="backtestForm.initialCash" type="number" />
            </label>
            <label>
              最大持仓数
              <input v-model.number="backtestForm.maxPositions" type="number" min="1" />
            </label>
            <label>
              单票仓位
              <input v-model.number="backtestForm.positionSize" type="number" min="0.01" max="1" step="0.01" />
            </label>
            <label>
              成交时点
              <select v-model="backtestForm.executionMode">
                <option value="current_bar">信号当根快照成交</option>
                <option value="next_bar">下一根快照成交</option>
              </select>
            </label>
            <label>
              目标持仓天数
              <input v-model.number="backtestForm.targetHoldingDays" type="number" min="1" step="0.5" />
            </label>
            <label>
              最大持有快照数
              <input v-model.number="backtestForm.maxHoldingBars" type="number" min="1" />
            </label>
            <label>
              止盈比例
              <input v-model.number="backtestForm.takeProfitPct" type="number" step="0.01" />
            </label>
            <label>
              止损比例
              <input v-model.number="backtestForm.stopLossPct" type="number" step="0.01" />
            </label>
            <label>
              手续费率
              <input v-model.number="backtestForm.feeRate" type="number" min="0" step="0.0001" />
            </label>
            <label>
              印花税率
              <input v-model.number="backtestForm.stampTaxRate" type="number" min="0" step="0.0001" />
            </label>
            <label>
              滑点率
              <input v-model.number="backtestForm.slippageRate" type="number" min="0" step="0.0001" />
            </label>
            <label>
              成交量参与率
              <input v-model.number="backtestForm.volumeParticipationRate" type="number" min="0" max="1" step="0.01" />
            </label>
            <label>
              盘口参与率
              <input v-model.number="backtestForm.orderBookParticipationRate" type="number" min="0" max="1" step="0.01" />
            </label>
            <label>
              盘中止盈止损优先
              <select v-model="backtestForm.intrabarAmbiguity">
                <option value="stop_first">同时触发先止损</option>
                <option value="take_first">同时触发先止盈</option>
              </select>
            </label>
            <label class="check-row">
              <input v-model="backtestForm.enforceT1" type="checkbox" />
              T+1 约束
            </label>
            <label class="check-row">
              <input v-model="backtestForm.useOrderBookPrice" type="checkbox" />
              盘口价优先
            </label>
            <label class="check-row">
              <input v-model="backtestForm.enforceLimitStatus" type="checkbox" />
              涨跌停约束
            </label>
            <label class="check-row">
              <input v-model="backtestForm.enforceVolumeLimit" type="checkbox" />
              成交量容量约束
            </label>
            <label class="check-row">
              <input v-model="backtestForm.enforceOrderBookQueue" type="checkbox" />
              盘口队列约束
            </label>
            <label class="check-row">
              <input v-model="backtestForm.allowPartialFills" type="checkbox" />
              允许部分成交
            </label>
            <label class="check-row">
              <input v-model="backtestForm.useIntrabarStops" type="checkbox" />
              启用盘中止盈止损
            </label>
            <label class="check-row">
              <input v-model="backtestForm.useThemeFactorForExecution" type="checkbox" />
              题材因子参与执行
            </label>
            <label>
              动量周期
              <input
                :value="backtestForm.momentumPeriods.join(',')"
                type="text"
                @input="backtestForm.momentumPeriods = parseNumberList(($event.target as HTMLInputElement).value)"
              />
            </label>
            <label>
              MACD 快线
              <input v-model.number="backtestForm.macdFast" type="number" min="1" />
            </label>
            <label>
              MACD 慢线
              <input v-model.number="backtestForm.macdSlow" type="number" min="1" />
            </label>
            <label>
              MACD 信号线
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
            回测计算中，后端会从当前快照主库读取 RankTrend 序列，再做交易模拟和后验统计。
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

        <section v-if="activeTab === 'theme'" class="tab-panel">
          <div class="section-heading">
            <h2>ThemeTrend 题材趋势</h2>
            <span class="status-pill" :class="statusClass(themeState.status)">{{ themeVerdict.label }}</span>
          </div>

          <!-- 回测运行 -->
          <div class="section-block">
            <h3>题材回测</h3>
            <div class="form-grid compact">
              <label>数据集ID <input v-model="themeBacktestForm.datasetId" type="text" /></label>
              <label>策略
                <select v-model="themeBacktestForm.strategyName">
                  <option value="theme_rotation">题材轮动</option>
                  <option value="leader_theme_confirmation">龙头题材确认</option>
                  <option value="hotlist_theme_confluence">热榜题材共振</option>
                </select>
              </label>
              <label>快照类型
                <select v-model="themeBacktestForm.snapshotType">
                  <option value="half_hour">半小时</option>
                  <option value="quarter_hour">15分钟</option>
                </select>
              </label>
              <label>随机种子 <input v-model.number="themeBacktestForm.randomSeed" type="number" /></label>
              <label>拥挤阻断阈值 <input v-model.number="themeBacktestForm.crowdingBlockThreshold" type="number" /></label>
              <label title="Phase 3 预留：当前只在前端表单展示，不参与后端计算">最大持仓（预留） <input v-model.number="themeBacktestForm.maxPositions" type="number" min="1" /></label>
              <label title="Phase 3 预留：当前只在前端表单展示，不参与后端计算">仓位比例（预留） <input v-model.number="themeBacktestForm.positionSize" type="number" min="0.01" max="1" step="0.01" /></label>
            </div>
            <div class="button-row">
              <button type="button" class="primary" :disabled="themeState.status === 'loading'" @click="runThemeBacktest">
                {{ themeState.status === "loading" ? "运行中..." : "运行 ThemeTrend 回测" }}
              </button>
              <button type="button" :disabled="themeState.status === 'loading'" @click="runThemeConfluence">
                运行共振回测
              </button>
            </div>
          </div>

          <!-- 查看报告 -->
          <div class="section-block">
            <h3>查看报告</h3>
            <div class="lookup-row">
              <input v-model="manualThemeBacktestId" type="text" :placeholder="lastThemeBacktestId || '回测运行 ID'" />
              <button type="button" :disabled="themeReportState.status === 'loading'" @click="fetchThemeReport">
                {{ themeReportState.status === "loading" ? "拉取中..." : "拉取报告" }}
              </button>
            </div>
            <div v-if="themeReportState.status === 'ok' && themeReportState.data" class="inline-success">
              <div><b>生命期分布:</b> {{ themeReport.lifecycleDistribution ? JSON.stringify(themeReport.lifecycleDistribution) : '-' }}</div>
              <div><b>拥挤事件:</b> {{ themeReport.crowdingEventCount ?? '-' }}</div>
              <div><b>生命周期迁移:</b> {{ themeReport.lifecycleTransitionCount ?? '-' }}</div>
              <div v-if="themeLifecycleReturns.length" class="mini-grid">
                <span v-for="row in themeLifecycleReturns" :key="String(row.lifecycle)" class="tag-stack">
                  {{ row.lifecycle }}: {{ row.tradeCount ?? 0 }}笔 / {{ (((Number(row.avgNetReturn) || 0) * 100).toFixed(2)) }}%
                </span>
              </div>
              <div v-if="themeTradeDiagnostics.length">
                <b>题材诊断:</b>
                <span v-for="row in themeTradeDiagnostics.slice(0, 4)" :key="String(row.themeName)" class="tag-stack">
                  {{ row.themeName || '未映射' }} {{ row.tradeCount ?? 0 }}笔 胜率{{ (((Number(row.winRate) || 0) * 100).toFixed(0)) }}%
                </span>
              </div>
              <div v-if="themeTierDiagnostics.length">
                <b>候选层:</b>
                <span v-for="row in themeTierDiagnostics.slice(0, 4)" :key="String(row.candidateTier)" class="tag-stack">
                  {{ row.candidateTier || 'unknown' }} {{ row.tradeCount ?? 0 }}笔
                </span>
              </div>
              <div v-if="themeRoleDiagnostics.length">
                <b>角色:</b>
                <span v-for="row in themeRoleDiagnostics.slice(0, 4)" :key="String(row.role)" class="tag-stack">
                  {{ row.role || 'unknown' }} {{ row.tradeCount ?? 0 }}笔
                </span>
              </div>
              <div><b>拥挤触发交易:</b> {{ themeCrowdingRiskDecay.triggeredTradeCount ?? 0 }}</div>
            </div>
            <div v-if="themeReportState.status === 'error'" class="inline-error">{{ themeReportState.error }}</div>
          </div>

          <!-- 优化 -->
          <div class="section-block">
            <h3>参数优化</h3>
            <div class="form-grid compact">
              <label>搜索方法
                <select v-model="themeOptimizationForm.method">
                  <option value="grid">网格搜索</option>
                  <option value="random">随机搜索</option>
                </select>
              </label>
              <label>试验次数 <input v-model.number="themeOptimizationForm.trials" type="number" min="1" /></label>
              <label>随机种子 <input v-model.number="themeOptimizationForm.randomSeed" type="number" /></label>
              <label>目标
                <select v-model="themeOptimizationForm.objective">
                  <option value="stability">样本外稳定</option>
                  <option value="totalReturn">收益率</option>
                </select>
              </label>
            </div>
            <button type="button" :disabled="themeState.status === 'loading'" @click="runThemeOptimization">
              启动优化
            </button>
          </div>

          <!-- 研究摘要 -->
          <div class="section-block">
            <div class="section-heading">
              <h3>研究摘要</h3>
              <button type="button" :disabled="themeResearchState.status === 'loading'" @click="loadThemeResearch">
                {{ themeResearchState.status === "loading" ? "加载中..." : "刷新摘要" }}
              </button>
            </div>
            <div v-if="themeResearchState.status === 'ok' && themeResearchState.data?.available" class="inline-success">
              <div><b>帧数:</b> {{ themeResearchState.data.frameCount }} | <b>主题数:</b> {{ themeResearchState.data.themeCount }}</div>
              <div v-if="themeResearchState.data.mainlineThemes?.length">
                <b>主线题材:</b>
                <span v-for="t in themeResearchState.data.mainlineThemes" :key="t.themeId" class="tag-stack">
                  {{ t.themeName }}({{ t.heatScore }})
                </span>
              </div>
              <div v-if="themeResearchState.data.crowdingAlerts?.length" class="inline-error">
                <b>拥挤警告:</b>
                <span v-for="t in themeResearchState.data.crowdingAlerts" :key="t.themeId">
                  {{ t.themeName }}(风险:{{ t.crowdingRisk }})
                </span>
              </div>
            </div>
            <div v-else-if="themeResearchState.status === 'ok' && !themeResearchState.data?.available" class="inline-note">
              研究摘要不可用：{{ themeResearchState.data?.reason || '未知原因' }}
            </div>
          </div>

          <!-- 主题回测结果原文 -->
          <div class="json-box-wrap">
            <button type="button" class="copy-button" @click="copyJsonBox('theme', themeState.raw || themeState.data)">
              {{ copyLabel("theme") }}
            </button>
            <pre class="json-box">{{ jsonPreview(themeState.raw || themeState.data) }}</pre>
          </div>
        </section>

        <section v-if="activeTab === 'optimization'" class="tab-panel">
          <div class="section-heading">
            <h2>参数优化</h2>
            <span class="status-pill" :class="statusClass(optimizationState.status)">
              {{ statusLabel(optimizationState.status, { running: '优化中' }) }}
            </span>
          </div>
          <div class="form-grid">
            <label>
              数据集 ID
              <input v-model="optimizationForm.datasetId" type="text" />
            </label>
            <label>
              搜索方法
              <select v-model="optimizationForm.method">
                <option value="grid">网格搜索</option>
                <option value="random">随机搜索</option>
                <option value="bayesian">高斯过程贝叶斯搜索</option>
                <option value="tpe">TPE 搜索</option>
              </select>
            </label>
            <label>
              策略
              <select v-model="optimizationForm.strategyName">
                <option v-for="option in strategyOptions" :key="option.value" :value="option.value">
                  {{ option.label }}
                </option>
              </select>
            </label>
            <label>
              优化目标
              <select v-model="optimizationForm.objective">
                <option value="stability">样本外稳定</option>
                <option value="risk_adjusted">风险调整</option>
                <option value="sharpe">夏普比率</option>
                <option value="return">收益率</option>
                <option value="max_drawdown">最大回撤</option>
                <option value="win_rate">胜率</option>
              </select>
            </label>
            <label>
              试验次数
              <input v-model.number="optimizationForm.trials" type="number" min="1" />
            </label>
            <label>
              随机种子
              <input v-model.number="optimizationForm.randomSeed" type="number" />
            </label>
            <label>
              样本外验证
              <select v-model="optimizationForm.validationMode">
                <option value="auto">按时间后段验证</option>
                <option value="none">全样本试跑</option>
              </select>
            </label>
            <label>
              验证比例
              <input v-model.number="optimizationForm.validationRatio" type="number" min="0.05" max="0.8" step="0.05" />
            </label>
            <label>
              验证预热快照
              <input v-model.number="optimizationForm.validationWarmupBars" type="number" min="0" />
            </label>
            <label class="check-row">
              <input v-model="optimizationForm.walkForward.enabled" type="checkbox" />
              滚动验证
            </label>
            <label>
              滚动训练天数
              <input v-model.number="optimizationForm.walkForward.trainWindowDays" type="number" min="1" />
            </label>
            <label>
              滚动验证天数
              <input v-model.number="optimizationForm.walkForward.validationWindowDays" type="number" min="1" />
            </label>
            <label>
              滚动保留试验数
              <input v-model.number="optimizationForm.walkForward.topTrials" type="number" min="1" />
            </label>
            <label>
              动量周期组
              <input v-model="gridInputs.momentumPeriods" type="text" />
            </label>
            <label>
              止盈比例组
              <input v-model="gridInputs.takeProfitPct" type="text" />
            </label>
            <label>
              止损比例组
              <input v-model="gridInputs.stopLossPct" type="text" />
            </label>
            <label>
              最大持仓数组
              <input v-model="gridInputs.maxPositions" type="text" />
            </label>
            <label title="默认沿用当前回测 MACD；需要不搜索 MACD 时可手动清空">
              MACD 快线候选
              <input v-model="gridInputs.macdFast" type="text" placeholder="默认 21；可填 19,21,24" />
            </label>
            <label title="默认沿用当前回测 MACD；需要不搜索 MACD 时可手动清空">
              MACD 慢线候选
              <input v-model="gridInputs.macdSlow" type="text" placeholder="默认 34；可填 30,34,38" />
            </label>
            <label title="默认沿用当前回测 MACD；需要不搜索 MACD 时可手动清空">
              MACD 信号线候选
              <input v-model="gridInputs.macdSignal" type="text" placeholder="默认 13；可填 10,13,16" />
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
            参数优化会按组合重复执行训练/验证回测；真实数据集建议先把试验次数降到 3-6 做试跑。
            <span v-if="optimizationPollMessage"> {{ optimizationPollMessage }}</span>
          </div>
          <div v-else-if="optimizationPollMessage" class="inline-note">
            {{ optimizationPollMessage }}
          </div>
          <div v-if="optimizationRunId" class="inline-note">
            <b>优化运行：</b>{{ optimizationRunId }}
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
              <b>{{ getNestedString(optimizationBestTrial, ["trialId"]) || getNestedString(optimizationBestTrial, ["trial_id"]) || "-" }}</b>
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
                    <th>试验</th>
                    <th>评分</th>
                    <th>训练收益</th>
                    <th>验证收益</th>
                    <th>验证 Sharpe</th>
                    <th>验证交易</th>
                    <th>风险</th>
                    <th>回测运行</th>
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
                      <div>训练 {{ shortId(getNestedString(trial, ["train", "runId"])) }}</div>
                      <div>验证 {{ shortId(getNestedString(trial, ["validation", "runId"])) }}</div>
                    </td>
                    <td>{{ formatTrialParameters(trial.parameters || trial.params || trial.optunaParams) }}</td>
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
              {{ statusLabel(backtestDetailState.status, { ok: '已载入' }) }}
            </span>
          </div>
          <div class="lookup-row">
            <input v-model="manualBacktestId" type="text" placeholder="回测运行 ID" />
            <button type="button" :disabled="backtestDetailState.status === 'loading'" @click="fetchBacktest">
              {{ backtestDetailState.status === "loading" ? "拉取中..." : "拉取报告" }}
            </button>
            <button
              type="button"
              class="danger-button"
              :disabled="backtestDetailState.status === 'loading' || !(manualBacktestId || lastBacktestId)"
              @click="deleteCurrentBacktest"
            >
              删除本次回测
            </button>
          </div>
          <div v-if="deleteBacktestMessage" class="inline-note">{{ deleteBacktestMessage }}</div>
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
              <span v-if="getNestedString(reportSource, ['snapshotType']) === 'quarter_hour'">15分钟样本</span>
            </div>
            <ul v-if="reportVerdict.reasons.length" class="narrative-list">
              <li v-for="reason in reportVerdict.reasons" :key="reason">{{ reason }}</li>
            </ul>
          </div>

          <!-- 跨期状态指示器 -->
          <div v-if="layer1SignalEfficacy || layer2ExecutionQuality" style="display:flex;gap:16px;padding:8px 12px;background:#f8f9fa;border-radius:6px;margin-bottom:8px;font-size:0.85rem;flex-wrap:wrap">
            <span v-if="layer1SignalEfficacy?.layer1Status === 'red'" style="color:#721c24">
              <b>L1 红灯</b> · {{ layer1SignalEfficacy?.aMainSamples || 0 }} 个 A_MAIN · 方向精度 {{ formatPercent(Number(layer1SignalEfficacy?.directionAccuracy)) }}
            </span>
            <span v-else-if="layer1SignalEfficacy?.layer1Status === 'green'" style="color:#155724">
              <b>L1 绿灯</b> · 信号有效性达标
            </span>
            <span v-if="layer2ExecutionQuality?.layer2Status === 'yellow'" style="color:#856404">
              <b>L2 黄灯</b> · H1-H2 偏差 {{ formatPercent(Number(layer2ExecutionQuality?.bias)) }} > 阈值 {{ formatPercent(Number(layer2ExecutionQuality?.biasThreshold)) }}
            </span>
            <span v-else-if="layer2ExecutionQuality?.layer2Status === 'green'" style="color:#155724">
              <b>L2 绿灯</b> · 执行偏差在阈值内
            </span>
            <span v-else-if="layer2ExecutionQuality?.layer2Status === 'red'" style="color:#721c24">
              <b>L2 红灯</b> · H2 反超 H1（追高/抢跑风险）
            </span>
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
                <div><span>数据集</span><b>{{ getNestedString(reportSource, ["datasetId"]) || "-" }}</b></div>
                <div><span>快照类型</span><b>{{ formatSnapshotTypeLabel(getNestedString(reportSource, ["snapshotType"])) }}</b></div>
                <div><span>策略</span><b>{{ getNestedString(reportSource, ["strategyName"]) || "-" }}</b></div>
                <div><span>版本</span><b>{{ getNestedString(reportSource, ["strategyVersion"]) || "-" }}</b></div>
                <div><span>配置</span><b>{{ shortId(getNestedString(reportSource, ["configHash"])) }}</b></div>
                <div><span>随机种子</span><b>{{ getNestedString(reportSource, ["randomSeed"]) || "-" }}</b></div>
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
                    <th>持有快照</th>
                    <th>分层</th>
                    <th>阶段/环境</th>
                    <th>退出原因</th>
                    <th>成交细节</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="trade in (trades as BacktestTrade[]).slice(0, 80)" :key="`${trade.id}-${trade.code}`">
                    <td><b>{{ trade.code || "-" }}</b><br /><small>{{ trade.name || "-" }}</small></td>
                    <td>{{ formatTradeTime(trade, "entry") }}<br />{{ formatPrice(Number(trade.entryPrice)) }}</td>
                    <td>{{ formatTradeTime(trade, "exit") }}<br />{{ formatPrice(Number(trade.exitPrice)) }}</td>
                    <td>{{ trade.quantity ?? "-" }}</td>
                    <td>{{ formatPercent(Number(trade.netReturn)) }}</td>
                    <td>{{ formatNumber(Number(trade.profit)) }}</td>
                    <td>{{ trade.holdingBars ?? "-" }}</td>
                    <td>{{ trade.candidateTier || "-" }}</td>
                    <td>{{ trade.stage || "-" }} / {{ trade.regime || "-" }}</td>
                    <td>{{ trade.reason || "-" }}</td>
                    <td>{{ formatTradeFill(trade) }}</td>
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
              <div><span>买入信号</span><b>{{ signalSummary.signalCounts.buy || 0 }}</b></div>
              <div><span>观察信号</span><b>{{ signalSummary.signalCounts.watch || 0 }}</b></div>
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
                <option value="buy">买入</option>
                <option value="watch">观察</option>
                <option value="hold">持有</option>
                <option value="sell">卖出</option>
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
                    <td>{{ formatSignalActionLabel(signal.signal) }}</td>
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
                  <thead><tr><th>日期</th><th>时间</th><th>热榜行数</th><th>模式</th><th>snapshotId</th></tr></thead>
                  <tbody>
                    <tr v-for="row in dataQualityExamples" :key="String(row.snapshotId)">
                      <td>{{ row.tradingDate || "-" }}</td>
                      <td>{{ row.slotTime || "-" }}</td>
                      <td>{{ row.stockRowCount ?? "-" }}</td>
                      <td>{{ row.captureMode || "-" }}</td>
                      <td>{{ row.snapshotId }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>

              <!-- V2 Layer 1: 信号有效性 -->
              <div v-if="layer1SignalEfficacy" class="section-block quality-block">
                <h3>V2 Layer 1 — 信号有效性
                  <span :class="['status-badge', layer1SignalEfficacy.layer1Status === 'green' ? 'badge-green' : 'badge-red']">
                    {{ signalLightLabel(layer1SignalEfficacy.layer1Status) }}
                  </span>
                </h3>
                <div class="diagnostic-grid compact-diagnostic">
                  <div><span>分层比例 (A+B)</span><b>{{ formatPercent(Number(layer1SignalEfficacy.tierRatio)) }} <small>(2%-15%)</small></b></div>
                  <div><span>方向精度</span><b>{{ formatPercent(Number(layer1SignalEfficacy.directionAccuracy)) }} <small>(>55%)</small></b></div>
                  <div><span>层级区分度</span><b>{{ formatPercent(Number(layer1SignalEfficacy.tierDiscrimination)) }} <small>(>5pp)</small></b></div>
                  <div><span>二项检验 p 值</span><b>{{ Number(layer1SignalEfficacy.binomialPValue).toFixed(4) }} <small>(<0.10)</small></b></div>
                  <div><span>A_MAIN 样本</span><b>{{ layer1SignalEfficacy.aMainSamples }}</b></div>
                  <div><span>总信号数</span><b>{{ layer1SignalEfficacy.totalSignals }}</b></div>
                </div>
                <div class="inline-note">
                  <b>信号层级分布：</b>
                  <span v-for="(cnt, tier) in asRecord(layer1SignalEfficacy.tierCounts)" :key="String(tier)" style="margin-right:12px">
                    {{ tier }}: {{ cnt }}
                  </span>
                </div>
              </div>

              <!-- V2 Layer 2: 执行质量 -->
              <div v-if="layer2ExecutionQuality" class="section-block quality-block">
                <h3>V2 Layer 2 — 执行质量 (H1 vs H2)
                  <span :class="['status-badge',
                    layer2ExecutionQuality.layer2Status === 'green' ? 'badge-green' :
                    layer2ExecutionQuality.layer2Status === 'yellow' ? 'badge-yellow' : 'badge-red']">
                    {{ signalLightLabel(layer2ExecutionQuality.layer2Status) }}
                  </span>
                </h3>
                <div class="diagnostic-grid compact-diagnostic">
                  <div><span>偏差 (H1-H2)</span><b>{{ formatPercent(Number(layer2ExecutionQuality.bias)) }} <small>(&lt; {{ formatPercent(Number(layer2ExecutionQuality.biasThreshold)) }})</small></b></div>
                  <div><span>方向占比 (近4期)</span><b>{{ formatPercent(Number(layer2ExecutionQuality.directionRatio)) }} <small>(≥75%)</small></b></div>
                  <div><span>交易数差异</span><b>{{ layer2ExecutionQuality.tradeCountDiff }}</b></div>
                  <div><span>回撤差异</span><b>{{ formatPercent(Number(layer2ExecutionQuality.drawdownDiff)) }} <small>(<5pp)</small></b></div>
                  <div><span>biasOk</span><b>{{ layer2ExecutionQuality.biasOk ? '✓' : '✗' }}</b></div>
                  <div><span>drawdownOk</span><b>{{ layer2ExecutionQuality.drawdownDiffOk ? '✓' : '✗' }}</b></div>
                </div>
              </div>

              <!-- 价格质量诊断 -->
              <div v-if="priceQualityDiagnostics" class="section-block quality-block">
                <h3>价格质量诊断 (report-only)</h3>
                <div class="diagnostic-grid compact-diagnostic">
                  <div><span>跨市场零行情</span><b>{{ priceQualityDiagnostics.crossMarketZeroPriceRows?.rowCount ?? 0 }} 行 / {{ priceQualityDiagnostics.crossMarketZeroPriceRows?.snapshotCount ?? 0 }} 快照</b></div>
                  <div><span>全零异常帧</span><b>{{ priceQualityDiagnostics.allZeroPriceFrames?.frameCount ?? 0 }} 帧</b></div>
                  <div><span>A股局部零价</span><b>{{ priceQualityDiagnostics.partialAshareZeroPriceRows?.rowCount ?? 0 }} 行 / {{ priceQualityDiagnostics.partialAshareZeroPriceRows?.snapshotCount ?? 0 }} 快照</b></div>
                </div>
                <div class="inline-note">诊断不参与过滤，不改变收益和质量等级。部分快照帧为合成数据（captureMode=synthesized），来自缺失 bar 的线性插值补齐。</div>
              </div>
            </div>
            <div v-else class="empty-explanation"><b>没有质量报告</b><p>兼容报告和归一化 quality 端点都没有返回质量信息。</p></div>
          </div>

          <div v-if="activeReportTab === 'alignment'" class="report-tab-panel">
            <div class="section-block quality-block">
              <h3>V2 Layer 3 — 实盘对齐</h3>
              <div v-if="alignmentLoading" class="inline-note">加载中...</div>
              <div v-else-if="alignmentError" class="inline-note" style="color:#721c24">{{ alignmentError }}</div>
              <div v-else-if="!alignmentResult" class="inline-note">
                点击"实盘对齐"标签自动加载。需要 MongoDB trade_journal 中有已执行的候选记录（含 entryPrice）。
              </div>
              <template v-else>
              <div class="diagnostic-grid compact-diagnostic">
                <div><span>已执行交易</span><b>{{ alignmentResult.journalExecutedCount ?? 0 }}</b></div>
                <div><span>回测信号标的</span><b>{{ alignmentResult.signalCodeCount ?? 0 }}</b></div>
                <div><span>交集标的</span><b>{{ alignmentResult.intersectionCount ?? 0 }}</b></div>
                <div><span>交集 P&L</span><b>{{ Number(alignmentResult.intersectionPnl || 0).toFixed(2) }}</b></div>
                <div><span>交集 P&L %</span><b>{{ formatPercent(Number(alignmentResult.intersectionPnlPct)) }}</b></div>
                <div><span>对齐状态</span><b>{{ alignmentResult.alignmentStatus }}</b></div>
                </div>
                <div v-if="alignmentResult.sufficientSample" class="inline-note" style="color:#155724">
                  ✓ 样本充足（≥10 笔），对齐报告有效
                </div>
                <div v-else class="inline-note">
                  ⚠ 样本不足（<10 笔），暂不判定对齐质量
                </div>
                <div v-if="(alignmentResult.intersectionCodes as any[])?.length" style="margin-top:12px">
                  <b>交集标的：</b>{{ (alignmentResult.intersectionCodes as string[])?.join(', ') }}
                </div>
              </template>
            </div>
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
              <div><span>数据集</span><b>{{ getNestedString(reportSource, ["datasetId"]) || "-" }}</b></div>
              <div><span>快照类型</span><b>{{ formatSnapshotTypeLabel(getNestedString(reportSource, ["snapshotType"])) }}</b></div>
              <div><span>策略</span><b>{{ getNestedString(reportSource, ["strategyName"]) || "-" }}</b></div>
              <div><span>版本</span><b>{{ getNestedString(reportSource, ["strategyVersion"]) || "-" }}</b></div>
              <div><span>配置</span><b>{{ shortId(getNestedString(reportSource, ["configHash"])) }}</b></div>
              <div><span>随机种子</span><b>{{ getNestedString(reportSource, ["randomSeed"]) || "-" }}</b></div>
              <div><span>开始日期</span><b>{{ getNestedString(reportSource, ["dateStart"]) || "-" }}</b></div>
              <div><span>结束日期</span><b>{{ getNestedString(reportSource, ["dateEnd"]) || "-" }}</b></div>
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
            <span>{{ replaySteps.length }} 条</span>
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

        <!-- 长测趋势 -->
        <section v-if="activeTab === 'trends'" class="tab-panel">
          <div class="panel-header" style="display:flex;justify-content:space-between;align-items:center">
            <h2>长测 Checkpoint 趋势</h2>
            <span style="display:flex;gap:8px;align-items:center">
              <span v-if="checkpointList.length" style="font-size:0.8rem;color:#666">{{ checkpointList.length }} 期</span>
              <button type="button" @click="fetchCheckpoints()" :disabled="checkpointLoading">
                {{ checkpointLoading ? '加载中...' : '刷新' }}
              </button>
            </span>
          </div>
          <div v-if="checkpointError" class="inline-note" style="color:#721c24;margin-bottom:12px">{{ checkpointError }}</div>
          <div v-if="recentCheckpoints.length" class="diagnostic-grid compact-diagnostic" style="margin-bottom:16px">
            <div v-if="latestCheckpoint">
              <span>最新 {{ h1CheckpointLabel }} 收益</span>
              <b :class="checkpointNumber(latestCheckpoint.h1TotalReturn) == null ? '' : checkpointNumber(latestCheckpoint.h1TotalReturn)! >= 0 ? 'pos' : 'neg'">{{ formatCheckpointPercent(latestCheckpoint.h1TotalReturn) }}</b>
            </div>
            <div v-if="latestCheckpoint">
              <span>最新 {{ h2CheckpointLabel }} 收益</span>
              <b :class="checkpointNumber(latestCheckpoint.h2TotalReturn) == null ? '' : checkpointNumber(latestCheckpoint.h2TotalReturn)! >= 0 ? 'pos' : 'neg'">{{ formatCheckpointPercent(latestCheckpoint.h2TotalReturn) }}</b>
            </div>
            <div v-if="latestCheckpoint">
              <span>最新 {{ e1CheckpointLabel }} 信号数</span>
              <b>{{ latestCheckpoint.e1SignalCount ?? '-' }}</b>
            </div>
            <div v-if="latestCheckpoint">
              <span>最新 {{ e1CheckpointLabel }} A+B占比</span>
              <b>{{ formatCheckpointPercent(latestCheckpoint.e1TierRatio) }}</b>
            </div>
            <div v-if="latestCheckpoint">
              <span>最新 L2</span>
              <b>
                <span v-if="latestCheckpoint.h1Layer2Status" :class="['status-badge',
                  latestCheckpoint.h1Layer2Status === 'green' ? 'badge-green' :
                  latestCheckpoint.h1Layer2Status === 'yellow' ? 'badge-yellow' : 'badge-red']" style="font-size:0.7rem">{{ signalLightLabel(latestCheckpoint.h1Layer2Status) }}</span>
                <span v-else>-</span>
              </b>
            </div>
            <div v-if="latestCheckpoint">
              <span>熔断</span>
              <b :style="latestCheckpoint.meltdown ? 'color:#721c24' : ''">{{ latestCheckpoint.meltdown ? '⚠ 触发' : '正常' }} <small>({{ latestCheckpoint.consecutiveRedPeriods || 0 }}期)</small></b>
            </div>
            <div><span>总期数</span><b>{{ checkpointList.length }}</b></div>
          </div>
          <div v-if="recentCheckpoints.length" class="table-wrap compact-table" style="max-height:70vh;overflow-y:auto">
            <table>
              <thead>
                <tr>
                  <th>日期</th>
                  <th>{{ h1CheckpointLabel }} 收益</th>
                  <th>{{ h1CheckpointLabel }} Sharpe</th>
                  <th>{{ h1CheckpointLabel }} 笔</th>
                  <th>{{ h2CheckpointLabel }} 收益</th>
                  <th>{{ h2CheckpointLabel }} Sharpe</th>
                  <th v-if="showQ1CheckpointColumns">{{ q1CheckpointLabel }} 收益</th>
                  <th v-if="showQ1CheckpointColumns">{{ q1CheckpointLabel }} Sharpe</th>
                  <th>{{ e1CheckpointLabel }} 信号数</th>
                  <th>{{ e1CheckpointLabel }} A+B占比</th>
                  <th>L2 偏差</th>
                  <th>L2</th>
                  <th>熔断</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="cp in recentCheckpoints" :key="String(cp.checkpointId)">
                  <td><small>{{ (String(cp.checkpointId)).replace('checkpoint_2026-', '').replace(/_/g, ' ') }}</small></td>
                  <td :class="checkpointNumber(cp.h1TotalReturn) == null ? '' : checkpointNumber(cp.h1TotalReturn)! >= 0 ? 'pos' : 'neg'">{{ formatCheckpointPercent(cp.h1TotalReturn) }}</td>
                  <td :class="checkpointNumber(cp.h1Sharpe) == null ? '' : checkpointNumber(cp.h1Sharpe)! >= 0 ? 'pos' : 'neg'">{{ formatCheckpointFixed(cp.h1Sharpe) }}</td>
                  <td>{{ cp.h1Trades ?? '-' }}</td>
                  <td :class="checkpointNumber(cp.h2TotalReturn) == null ? '' : checkpointNumber(cp.h2TotalReturn)! >= 0 ? 'pos' : 'neg'">{{ formatCheckpointPercent(cp.h2TotalReturn) }}</td>
                  <td :class="checkpointNumber(cp.h2Sharpe) == null ? '' : checkpointNumber(cp.h2Sharpe)! >= 0 ? 'pos' : 'neg'">{{ formatCheckpointFixed(cp.h2Sharpe) }}</td>
                  <td v-if="showQ1CheckpointColumns" :class="checkpointNumber(cp.q1TotalReturn) == null ? '' : checkpointNumber(cp.q1TotalReturn)! >= 0 ? 'pos' : 'neg'">{{ formatCheckpointPercent(cp.q1TotalReturn) }}</td>
                  <td v-if="showQ1CheckpointColumns" :class="checkpointNumber(cp.q1Sharpe) == null ? '' : checkpointNumber(cp.q1Sharpe)! >= 0 ? 'pos' : 'neg'">{{ formatCheckpointFixed(cp.q1Sharpe) }}</td>
                  <td>{{ cp.e1SignalCount ?? '-' }}</td>
                  <td>{{ formatCheckpointPercent(cp.e1TierRatio) }}</td>
                  <td>{{ checkpointNumber(cp.h1Layer2Bias) != null ? formatPercent(checkpointNumber(cp.h1Layer2Bias)!) : '-' }}</td>
                  <td>
                    <span v-if="cp.h1Layer2Status" :class="['status-badge',
                      cp.h1Layer2Status === 'green' ? 'badge-green' :
                      cp.h1Layer2Status === 'yellow' ? 'badge-yellow' : 'badge-red']" style="font-size:0.6rem;padding:1px 5px">{{ signalLightLabel(cp.h1Layer2Status) }}</span>
                    <span v-else>-</span>
                  </td>
                  <td><span v-if="cp.meltdown" style="color:#721c24">⚠ {{ cp.consecutiveRedPeriods || 0 }}期</span><span v-else>-</span></td>
                </tr>
              </tbody>
            </table>
          </div>
          <div v-else-if="!checkpointLoading" class="empty-state">点击"刷新"加载长测 checkpoint 列表。<br/><small>数据来源：quant-board/data/reports/long_test_runs.jsonl</small></div>
        </section>

      </section>
    </section>
  </main>
</template>
