import type {
  ApiErrorDetail,
  BacktestRequest,
  DatasetSummary,
  GoldenValidateRequest,
  GoldenImportPayload,
  HealthResponse,
  ImportPayload,
  OptimizationRequest,
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
  runOptimization: (payload: OptimizationRequest) =>
    requestApi<unknown>("/api/optimizations/rank-trend", {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  getOptimization: (id: string) =>
    requestApi<unknown>(`/api/optimizations/${encodeURIComponent(id)}`),
  validateGolden: (payload: GoldenValidateRequest) =>
    requestApi<unknown>("/api/golden/validate", {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  createGoldenBaseline: (payload: GoldenValidateRequest & { sampleLimit?: number }) =>
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
  if (error && typeof error === "object" && "message" in error) {
    return String((error as { message: unknown }).message);
  }
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}
