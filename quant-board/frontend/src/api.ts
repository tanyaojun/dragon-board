import type {
  ApiErrorDetail,
  BacktestEquityResponse,
  BacktestDeleteResponse,
  BacktestQualityResponse,
  BacktestRequest,
  BacktestSignal,
  BacktestTrade,
  CheckpointSummary,
  DatasetDeleteResponse,
  DatasetSummary,
  GoldenValidateRequest,
  GoldenImportPayload,
  HealthResponse,
  ImportPayload,
  OptimizationRequest,
  PaginatedBacktestResponse,
  UploadPayload
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE || "";

async function readBody(response: Response): Promise<unknown> {
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return response.json();
  }
  const text = await response.text();
  return text || undefined;
}

function toApiError(response: Response, body: unknown): ApiErrorDetail {
  let message = `${response.status} ${response.statusText}`.trim();

  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail?: unknown }).detail;
    message = typeof detail === "string" ? detail : JSON.stringify(detail);
  } else if (body && typeof body === "object") {
    message = JSON.stringify(body);
  } else if (typeof body === "string" && body.trim()) {
    message = body;
  }

  return {
    status: response.status,
    statusText: response.statusText,
    message,
    body
  };
}

export async function requestApi<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(init.headers || {})
    },
    ...init
  });
  const body = await readBody(response);

  if (!response.ok) {
    throw toApiError(response, body);
  }

  return body as T;
}

export const api = {
  health: () => requestApi<HealthResponse>("/api/health"),
  datasets: () => requestApi<DatasetSummary[]>("/api/datasets"),
  deleteDataset: (id: string) =>
    requestApi<DatasetDeleteResponse>(`/api/datasets/${encodeURIComponent(id)}`, {
      method: "DELETE"
    }),
  snapshotCounts: (datasetId?: string) => {
    const query = datasetId ? `?dataset_id=${encodeURIComponent(datasetId)}` : "";
    return requestApi<unknown>(`/api/snapshots/counts${query}`);
  },
  importDataset: (payload: ImportPayload) =>
    requestApi<DatasetSummary | { dataset: DatasetSummary }>("/api/datasets/import", {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  uploadDataset: (payload: UploadPayload) =>
    requestApi<DatasetSummary | { dataset: DatasetSummary }>("/api/datasets/upload", {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  runBacktest: (payload: BacktestRequest) =>
    requestApi<unknown>("/api/backtests/rank-trend", {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  getBacktest: (id: string) => requestApi<unknown>(`/api/backtests/${encodeURIComponent(id)}`),
  deleteBacktest: (id: string) =>
    requestApi<BacktestDeleteResponse>(`/api/backtests/${encodeURIComponent(id)}`, {
      method: "DELETE"
    }),
  getBacktestTrades: (id: string, limit = 100, offset = 0) =>
    requestApi<PaginatedBacktestResponse<BacktestTrade>>(
      `/api/backtests/${encodeURIComponent(id)}/trades?limit=${limit}&offset=${offset}`
    ),
  getBacktestEquity: (id: string) =>
    requestApi<BacktestEquityResponse>(`/api/backtests/${encodeURIComponent(id)}/equity`),
  getBacktestSignals: (id: string, limit = 200, offset = 0, tier?: string, regime?: string) => {
    const params = new URLSearchParams({
      limit: String(limit),
      offset: String(offset)
    });
    if (tier) {
      params.set("tier", tier);
    }
    if (regime) {
      params.set("regime", regime);
    }
    return requestApi<PaginatedBacktestResponse<BacktestSignal>>(
      `/api/backtests/${encodeURIComponent(id)}/signals?${params.toString()}`
    );
  },
  getBacktestQuality: (id: string) =>
    requestApi<BacktestQualityResponse>(`/api/backtests/${encodeURIComponent(id)}/quality`),
  getAlignment: (runIds: string) =>
    requestApi<Record<string, unknown>>(`/api/backtests/alignment?run_ids=${encodeURIComponent(runIds)}`),
  getCheckpoints: (limit = 20) =>
    requestApi<CheckpointSummary[]>(`/api/backtests/checkpoints?limit=${limit}`),
  runOptimization: (payload: OptimizationRequest) =>
    requestApi<unknown>("/api/optimizations/rank-trend", {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  getOptimization: (id: string) =>
    requestApi<unknown>(`/api/optimizations/${encodeURIComponent(id)}`),
  // ThemeTrend
  runThemeTrend: (payload: import("./types").ThemeBacktestRequest) =>
    requestApi<unknown>("/api/backtests/theme-trend", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  runThemeConfluence: (payload: import("./types").ThemeBacktestRequest) =>
    requestApi<unknown>("/api/backtests/theme-confluence", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  getThemeReport: (id: string) =>
    requestApi<unknown>(`/api/reports/theme-trend/${encodeURIComponent(id)}`),
  getThemeResearchSummary: (params: { dataset_id: string; snapshot_type: string }) => {
    const query = new URLSearchParams(params).toString();
    return requestApi<import("./types").ThemeResearchSummary>(`/api/research/theme-summary?${query}`);
  },
  runThemeOptimization: (payload: import("./types").ThemeOptimizationRequest) =>
    requestApi<unknown>("/api/optimizations/theme-trend", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  validateGolden: (payload: GoldenValidateRequest) =>
    requestApi<unknown>("/api/golden/validate", {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  createGoldenBaseline: (payload: GoldenValidateRequest) =>
    requestApi<unknown>("/api/golden/baseline", {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  importGolden: (payload: GoldenImportPayload) =>
    requestApi<unknown>("/api/golden/import", {
      method: "POST",
      body: JSON.stringify(payload)
    })
};

export function formatApiError(error: unknown): string {
  if (error && typeof error === "object" && "body" in error) {
    const body = (error as { body?: unknown }).body;
    if (body && typeof body === "object" && "detail" in body) {
      const detail = (body as { detail?: unknown }).detail;
      return typeof detail === "string" ? detail : JSON.stringify(detail, null, 2);
    }
  }
  if (error && typeof error === "object" && "message" in error) {
    return String((error as { message: unknown }).message);
  }
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}
