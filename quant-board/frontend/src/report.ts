import type {
  BacktestEquityPoint,
  BacktestQualityReport,
  BacktestReportVerdict,
  BacktestSignal,
  BacktestTrade,
  ReplayStep
} from "./types";

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

function getNumber(value: unknown): number | undefined {
  const number = Number(value);
  return Number.isFinite(number) ? number : undefined;
}

export function safeFiniteNumber(value: unknown): number | undefined {
  return getNumber(value);
}

function pickArray(value: unknown, keys: string[]): unknown[] {
  const record = asRecord(value);
  for (const key of keys) {
    const current = record[key];
    if (Array.isArray(current)) {
      return current;
    }
  }
  return [];
}

function pickArrayDeep(value: unknown, keys: string[]): unknown[] {
  const root = asRecord(value);
  const direct = pickArray(root, keys);
  if (direct.length) {
    return direct;
  }
  return pickArray(asRecord(root.result), keys);
}

export function getRunId(value: unknown): string {
  const record = asRecord(value);
  const nested = asRecord(record.run);
  return String(record.id || record.runId || record.run_id || nested.id || "");
}

export function getMetric(value: unknown, keys: string[]): number | undefined {
  const root = asRecord(value);
  const result = asRecord(root.result);
  const metrics = asRecord(root.metrics);
  const resultMetrics = asRecord(result.metrics);
  const candidates = [root, result, metrics, resultMetrics];

  for (const source of candidates) {
    for (const key of keys) {
      if (source[key] !== undefined) {
        return getNumber(source[key]);
      }
    }
  }

  return undefined;
}

export function getEquityCurve(value: unknown): Array<{ index: number; label: string; value: number }> {
  const curve = pickArrayDeep(value, ["equityCurve", "equity_curve", "curve"]);

  return curve
    .map((item, index) => {
      if (typeof item === "number") {
        return { index, label: String(index + 1), value: item };
      }
      const row = asRecord(item);
      return {
        index,
        label: String(row.date || row.time || row.timestamp || index + 1),
        value: getNumber(row.equity || row.value || row.nav || row.cash) ?? 0
      };
    })
    .filter((item) => Number.isFinite(item.value));
}

export function getTrades(value: unknown): unknown[] {
  return pickArrayDeep(value, ["trades", "roundTripTrades", "round_trip_trades", "positions", "orders", "tradeEvents", "trade_events"]);
}

export function getArrayField(value: unknown, keys: string[]): unknown[] {
  return pickArrayDeep(value, keys);
}

export function getObjectField(value: unknown, keys: string[]): Record<string, unknown> {
  const root = asRecord(value);
  const result = asRecord(root.result);
  for (const source of [root, result]) {
    for (const key of keys) {
      const item = source[key];
      if (item && typeof item === "object" && !Array.isArray(item)) {
        return item as Record<string, unknown>;
      }
    }
  }
  return {};
}

export function getOptimizationTrials(value: unknown): Array<Record<string, unknown>> {
  return pickArrayDeep(value, ["trials", "results"]).map((item) => asRecord(item));
}

export function getNestedNumber(value: unknown, path: string[]): number | undefined {
  for (const source of [value, asRecord(value).result]) {
    let current: unknown = source;
    for (const key of path) {
      current = asRecord(current)[key];
    }
    const number = getNumber(current);
    if (number !== undefined) {
      return number;
    }
  }
  return undefined;
}

export function getNestedString(value: unknown, path: string[]): string {
  for (const source of [value, asRecord(value).result]) {
    let current: unknown = source;
    for (const key of path) {
      current = asRecord(current)[key];
    }
    if (current !== undefined && current !== null && current !== "") {
      return String(current);
    }
  }
  return "";
}

function countBy<T>(rows: T[], keyOf: (row: T) => string | undefined): Record<string, number> {
  const result: Record<string, number> = {};
  for (const row of rows) {
    const key = keyOf(row) || "-";
    result[key] = (result[key] || 0) + 1;
  }
  return result;
}

function sum(values: number[]): number {
  return values.reduce((total, value) => total + value, 0);
}

function normalizedPercentValue(value: number | undefined): number | undefined {
  if (value === undefined || !Number.isFinite(value)) {
    return undefined;
  }
  return Math.abs(value) <= 1 ? value : value / 100;
}

export function buildBacktestVerdict(
  report: unknown,
  quality: BacktestQualityReport | null | undefined,
  trades: BacktestTrade[],
  signals: BacktestSignal[]
): BacktestReportVerdict {
  const reportRecord = asRecord(report);
  const totalReturn = getMetric(report, ["totalReturn", "total_return", "return"]);
  const maxDrawdown = getMetric(report, ["maxDrawdown", "max_drawdown", "drawdown"]);
  const tradeCount = getMetric(report, ["tradeCount", "trade_count"]) ?? trades.length;
  const snapshotType = String(reportRecord.snapshotType || reportRecord.snapshot_type || "");
  const severity = String(quality?.severity || getNestedString(report, ["dataQuality", "severity"]) || "pass");
  const researchGrade = String(quality?.researchGrade || getNestedString(report, ["dataQuality", "researchGrade"]) || "research_ready");
  const reasons: string[] = [];

  let level: BacktestReportVerdict["level"] = "usable";
  let tone: BacktestReportVerdict["tone"] = "good";
  let label = "可参考";

  if (severity === "fail" || researchGrade === "blocked") {
    level = "blocked";
    tone = "bad";
    label = "不建议采信";
    reasons.push("质量门禁失败或研究等级 blocked，报告不适合作为策略判断依据。");
  } else if (severity === "warn" || researchGrade === "degraded") {
    level = "degraded";
    tone = "warn";
    label = "质量观察";
    reasons.push("样本质量 degraded/warn，收益和胜率需要结合质量诊断解读。");
  }

  if (!tradeCount) {
    if (level === "usable") {
      level = "degraded";
      tone = "warn";
      label = "无成交";
    }
    reasons.push("本次没有真实成交，应优先查看信号解释和撮合诊断。");
  }

  const normalizedReturn = normalizedPercentValue(totalReturn);
  const normalizedDrawdown = normalizedPercentValue(maxDrawdown);
  if (
    normalizedReturn !== undefined &&
    normalizedReturn > 0 &&
    normalizedDrawdown !== undefined &&
    normalizedDrawdown > -0.1 &&
    tradeCount > 0 &&
    severity === "pass" &&
    researchGrade !== "degraded"
  ) {
    level = "usable";
    tone = "good";
    label = "可参考";
  }

  if (snapshotType === "quarter_hour") {
    reasons.push("本次使用 quarter_hour 快照，不能和默认 half_hour 结果直接混读。");
  }

  const performanceLabel =
    normalizedReturn === undefined
      ? "表现未知"
      : normalizedReturn > 0.005
        ? "表现为正"
        : normalizedReturn < -0.005
          ? "表现为负"
          : "表现持平";
  const tradeLabel = tradeCount > 0 ? "有成交" : "无成交";
  const qualityLabel = severity || researchGrade || "unknown";
  const signalHint = signals.length ? `已记录 ${signals.length} 条候选/信号解释。` : "尚未读取到候选/信号解释。";
  const summary = `${performanceLabel}，${tradeLabel}，质量状态 ${qualityLabel}。${reasons[0] || signalHint}`;

  return { level, label, tone, performanceLabel, tradeLabel, qualityLabel, summary, reasons };
}

export function buildTradeSummary(trades: BacktestTrade[]) {
  const netReturns = trades.map((trade) => safeFiniteNumber(trade.netReturn));
  const profits = trades.map((trade) => safeFiniteNumber(trade.profit));
  const winning = trades.filter((trade) => (safeFiniteNumber(trade.netReturn) ?? safeFiniteNumber(trade.profit) ?? 0) > 0);
  const losing = trades.filter((trade) => (safeFiniteNumber(trade.netReturn) ?? safeFiniteNumber(trade.profit) ?? 0) < 0);
  const validNetReturns = netReturns.filter((value): value is number => value !== undefined);
  const validProfits = profits.filter((value): value is number => value !== undefined);
  return {
    total: trades.length,
    winning: winning.length,
    losing: losing.length,
    averageNetReturn: validNetReturns.length ? sum(validNetReturns) / validNetReturns.length : undefined,
    maxProfit: validProfits.length ? Math.max(...validProfits) : undefined,
    maxLoss: validProfits.length ? Math.min(...validProfits) : undefined
  };
}

export function buildSignalSummary(signals: BacktestSignal[]) {
  const tierCounts = countBy(signals, (signal) => signal.candidateTier || undefined);
  const signalCounts = countBy(signals, (signal) => signal.signal || undefined);
  const riskCounts: Record<string, number> = {};
  for (const signal of signals) {
    for (const flag of signal.riskFlags || []) {
      riskCounts[flag] = (riskCounts[flag] || 0) + 1;
    }
  }
  const riskTop = Object.entries(riskCounts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5)
    .map(([key, count]) => ({ key, count }));
  return {
    total: signals.length,
    strongCandidates: tierCounts.A_MAIN || 0,
    watchCandidates: tierCounts.B_IGNITION || 0,
    excludedCandidates: (tierCounts.C_CROWDED || 0) + (tierCounts.D_EXIT_RISK || 0),
    tierCounts,
    signalCounts,
    riskTop
  };
}

export function buildDrawdownCurve(equityCurve: BacktestEquityPoint[] | Array<{ value: number; label?: string }>) {
  let peak: number | undefined;
  return equityCurve
    .map((point, index) => {
      const record = asRecord(point);
      const value = safeFiniteNumber(record.equity ?? record.value);
      if (value === undefined) {
        return undefined;
      }
      peak = peak === undefined ? value : Math.max(peak, value);
      const drawdown = peak ? (value - peak) / peak : 0;
      return {
        index,
        label: String(record.tradingDate || record.label || record.timestamp || index + 1),
        value: drawdown
      };
    })
    .filter((point): point is { index: number; label: string; value: number } => Boolean(point));
}

export function buildQualityNarratives(dataQuality: Record<string, unknown>, quality: BacktestQualityReport | null | undefined): string[] {
  const narratives: string[] = [];
  const researchGrade = String(quality?.researchGrade || dataQuality.researchGrade || "");
  const sampleOkShare = safeFiniteNumber(dataQuality.sampleOkShare);
  const lowHotlistShare = safeFiniteNumber(dataQuality.lowHotlistShare);
  const infCounts = quality?.infCounts || {};
  const nanCounts = quality?.nanCounts || {};

  if (researchGrade === "degraded") {
    narratives.push("样本质量降级，收益和胜率只能作为观察，不适合作为最终参数依据。");
  }
  if (sampleOkShare === 0) {
    narratives.push("样本 OK 占比为 0%，早期信号和 MACD 解释需要降权。");
  }
  if (lowHotlistShare !== undefined && lowHotlistShare > 0.05) {
    narratives.push("低热榜快照偏多，候选分层可能不稳定。");
  }
  if ((infCounts.price || 0) > 0 || (nanCounts.price || 0) > 0) {
    narratives.push("价格字段存在异常，交易撮合可信度下降。");
  }
  const warnings = quality?.warnings || (Array.isArray(dataQuality.warnings) ? dataQuality.warnings.map(String) : []);
  return [...narratives, ...warnings.slice(0, 4)];
}

export function buildControlConclusion(report: unknown, controlBacktests: Array<Record<string, unknown>>): string[] {
  const conclusions: string[] = [];
  const totalReturn = getMetric(report, ["totalReturn", "total_return"]);
  const hotTop10 = controlBacktests.find((row) => String(row.key || row.label || "").includes("hot_top10") || String(row.label || "").includes("Top10"));
  const aMain = controlBacktests.find((row) => String(row.key || row.label || "").includes("A_MAIN"));
  const bIgnition = controlBacktests.find((row) => String(row.key || row.label || "").includes("B_IGNITION"));
  const combined = controlBacktests.find((row) => String(row.key || row.label || "").includes("A+B"));

  const hotReturn = safeFiniteNumber(hotTop10?.totalReturn);
  if (totalReturn !== undefined && hotReturn !== undefined && totalReturn < hotReturn) {
    conclusions.push("当前策略未跑赢热榜 Top10。");
  }
  if ((safeFiniteNumber(aMain?.tradeCount) || 0) === 0 && aMain) {
    conclusions.push("A_MAIN 没有形成真实交易，主升候选不足。");
  }
  const bReturn = safeFiniteNumber(bIgnition?.totalReturn);
  const combinedReturn = safeFiniteNumber(combined?.totalReturn);
  if (bReturn !== undefined && combinedReturn !== undefined && Math.abs(bReturn - combinedReturn) < 0.001) {
    conclusions.push("交易主要来自 B_IGNITION 连贯确认信号。");
  }
  return conclusions.length ? conclusions : ["对照组未显示明显差异，建议结合交易明细和样本质量继续判断。"];
}

export function buildReplaySteps(value: unknown, stockCode: string): ReplayStep[] {
  const code = stockCode.trim();
  const trades = getTrades(value);
  const signals = pickArrayDeep(value, ["signals", "decisions"]);
  const rows = trades.length ? trades : signals;

  return rows
    .map((item, index) => {
      const row = asRecord(item);
      const rowCode = String(row.code || row.symbol || row.stockCode || "");
      const entrySnapshotId = String(row.entrySnapshotId || "");
      const exitSnapshotId = String(row.exitSnapshotId || "");
      const snapshotId = String(row.snapshotId || "");
      const time =
        row.displayTime ||
        row.time ||
        row.date ||
        row.timestamp ||
        row.entryTime ||
        row.exitTime ||
        snapshotId ||
        entrySnapshotId ||
        exitSnapshotId ||
        `step-${index + 1}`;
      return {
        time: String(time),
        code: rowCode,
        name: String(row.name || row.stockName || ""),
        action: String(row.action || row.side || row.signal || "observe"),
        reason: String(row.explanation || row.reason || row.memo || "无解释字段，展示原始交易/信号记录"),
        score: getNumber(row.score || row.confidence),
        rank: getNumber(row.rank),
        price: getNumber(row.price || row.fillPrice || row.entryPrice || row.exitPrice),
        holdingBars: getNumber(row.holdingBars),
        candidateTier: row.candidateTier ? String(row.candidateTier) : undefined,
        stage: row.stage ? String(row.stage) : undefined,
        regime: row.regime ? String(row.regime) : undefined
      };
    })
    .filter((step) => !code || step.code.includes(code))
    .slice(0, 80);
}

export function formatDisplayTime(value: string): string {
  if (!value || value === "-") {
    return "-";
  }
  if (/^\d{4}-\d{2}-\d{2}/.test(value)) {
    return value.replace("T", " ").replace(/\.\d+Z?$/, "").slice(0, 19);
  }
  const numeric = Number(value);
  if (Number.isFinite(numeric) && numeric > 1000000000) {
    const date = new Date(numeric);
    if (!Number.isNaN(date.getTime())) {
      return date.toLocaleString("zh-CN", {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false
      });
    }
  }
  const snapshot = value.match(/(?:quarter_hour|half_hour):(\d{4}-\d{2}-\d{2}):(.+)$/);
  if (snapshot) {
    return `${snapshot[1]} ${snapshot[2]}`;
  }
  return value;
}

function snapshotTime(value: unknown): string {
  const snapshot = String(value || "").match(/(?:quarter_hour|half_hour):(\d{4}-\d{2}-\d{2}):(.+)$/);
  return snapshot ? `${snapshot[1]} ${snapshot[2]}` : "";
}

export function formatTradeTime(trade: BacktestTrade, side: "entry" | "exit"): string {
  const snapshotId =
    side === "entry"
      ? trade.entrySnapshotId || trade.entrySignalSnapshotId
      : trade.exitSnapshotId || trade.exitSignalSnapshotId;
  const fromSnapshot = snapshotTime(snapshotId);
  if (fromSnapshot) {
    return fromSnapshot;
  }

  const rawTime = side === "entry" ? trade.entryTime : trade.exitTime;
  const fromTime = formatDisplayTime(String(rawTime || ""));
  if (fromTime !== "-") {
    return fromTime;
  }

  const tradingDate = side === "entry" ? trade.entryTradingDate : trade.exitTradingDate;
  return tradingDate || "-";
}

export function formatTradeFill(trade: BacktestTrade): string {
  const fill = asRecord(trade.fillDetail || trade.fill);
  if (!Object.keys(fill).length) {
    return "-";
  }
  const parts = [
    fill.priceSource ? `价源:${fill.priceSource}` : "",
    fill.partial === true ? "部分成交" : "",
    fill.snapshotPriceFallback === true ? "快照价回退" : "",
    Array.isArray(fill.capacityReasons) && fill.capacityReasons.length
      ? `容量:${fill.capacityReasons.slice(0, 2).join("/")}`
      : ""
  ].filter(Boolean);
  return parts.length ? parts.join(" / ") : Object.keys(fill).slice(0, 3).join(" / ");
}

export function formatPercent(value: number | undefined): string {
  if (value === undefined || !Number.isFinite(value)) {
    return "-";
  }
  const normalized = Math.abs(value) <= 1 ? value * 100 : value;
  return `${normalized.toFixed(2)}%`;
}

export function formatNumber(value: number | undefined, digits = 2): string {
  return value === undefined || !Number.isFinite(value) ? "-" : value.toFixed(digits);
}

export function formatPrice(value: number | undefined): string {
  return value === undefined || !Number.isFinite(value) ? "-" : value.toFixed(2);
}
