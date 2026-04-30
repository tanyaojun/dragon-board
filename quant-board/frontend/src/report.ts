import type { ReplayStep } from "./types";

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

function getNumber(value: unknown): number | undefined {
  const number = Number(value);
  return Number.isFinite(number) ? number : undefined;
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
  return pickArrayDeep(value, ["tradeEvents", "trade_events", "trades", "orders", "positions"]);
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
  let current: unknown = value;
  for (const key of path) {
    current = asRecord(current)[key];
  }
  return getNumber(current);
}

export function getNestedString(value: unknown, path: string[]): string {
  let current: unknown = value;
  for (const key of path) {
    current = asRecord(current)[key];
  }
  return current === undefined || current === null ? "" : String(current);
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
