import type {
  DatasetInfo,
  DatasetItemInfo,
  DemoStatus,
  ErrorBody,
  ExperimentDetail,
  ExperimentSummary,
  ModelInfo,
  MutationInfo,
  Paged,
  ResultsBundle,
  TokenResponse,
} from "../types";

const TOKEN_KEY = "diffmia_token";
const USER_KEY = "diffmia_user";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setAuth(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearAuth(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

export function setStoredUser(user: unknown): void {
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function getStoredUser<T>(): T | null {
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}

export class ApiError extends Error {
  code: string;
  status: number;
  requestId?: string;
  constructor(body: ErrorBody, status: number) {
    super(body.message || body.error);
    this.code = body.error;
    this.status = status;
    this.requestId = body.request_id;
  }
}

const REAUTH_GUARD_KEY = "diffmia_reauth_at";
const REAUTH_GUARD_MS = 10_000;

/**
 * A rejected token is replaced by reloading the app, which then signs in again
 * at startup. Guarded so a server that keeps rejecting cannot reload in a loop
 * — the caller's error then surfaces instead.
 */
function restartSession(): void {
  const last = Number(sessionStorage.getItem(REAUTH_GUARD_KEY) ?? "0");
  if (Date.now() - last < REAUTH_GUARD_MS) return;
  sessionStorage.setItem(REAUTH_GUARD_KEY, String(Date.now()));
  window.location.reload();
}

async function request<T>(path: string, options: RequestInit = {}, retry = false): Promise<T> {
  const headers = new Headers(options.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (options.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`/api${path}`, { ...options, headers });
  if (response.status === 401 && token && !retry && !path.startsWith("/auth/login")) {
    clearAuth();
    restartSession();
    throw new ApiError({ error: "AUTHENTICATION_REQUIRED", message: "Session expired." }, 401);
  }
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = text;
  }
  if (!response.ok) {
    const errorBody = (typeof body === "object" && body !== null ? body : {
      error: "HTTP_ERROR",
      message: `Request failed (${response.status})`,
    }) as ErrorBody;
    throw new ApiError(errorBody, response.status);
  }
  return body as T;
}

const get = <T>(path: string) => request<T>(path);
const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
const patch = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "PATCH", body: body === undefined ? undefined : JSON.stringify(body) });
const del = <T>(path: string) => request<T>(path, { method: "DELETE" });

export const api = {
  // auth
  login: (username: string, password: string) =>
    post<TokenResponse>("/auth/login", { username, password }),
  /** Credential-free session for installations that run without a login page. */
  autoLogin: () => post<TokenResponse>("/auth/auto-login"),
  oauthStatus: () =>
    get<{ google_enabled: boolean; self_registration: boolean }>("/auth/oauth/status"),
  register: (username: string, email: string, password: string) =>
    post<TokenResponse>("/auth/register", { username, email, password }),
  verifyEmail: (token: string) =>
    post<TokenResponse["user"]>("/auth/verify-email", { token }),
  resendVerificationEmail: (email: string) =>
    post<{ status: string; development_token?: string }>("/auth/resend-verification-email", { email }),
  forgotPassword: (email: string) =>
    post<{ status: string; development_token?: string }>("/auth/forgot-password", { email }),
  resetPassword: (token: string, new_password: string) =>
    post<TokenResponse["user"]>("/auth/reset-password", { token, new_password }),
  oauthExchange: (handoffToken: string) =>
    request<TokenResponse>("/auth/oauth/exchange", {
      method: "POST",
      headers: { Authorization: `Bearer ${handoffToken}` },
    }),
  me: () => get<UserShape>("/auth/me"),
  changePassword: (old_password: string, new_password: string) =>
    post("/auth/change-password", { old_password, new_password }),
  // Google account linking (Settings → Connected accounts). The start call
  // returns the consent URL to navigate to; the callback binds the account on
  // the server, so nothing here carries a session token in a URL.
  googleLinkStart: () => post<{ authorize_url: string }>("/auth/google/link/start"),
  googleUnlink: () => post<UserShape>("/auth/google/unlink"),

  // demo
  demoStatus: () => get<DemoStatus>("/demo/status"),
  demoBootstrap: () => post<{ status: string; dataset_id: number; model_id: number }>("/demo/bootstrap"),
  demoRun: () => post<{ status: string; experiment_id: number }>("/demo/run"),

  // experiments
  experiments: () => get<Paged<ExperimentSummary>>("/experiments?limit=200"),
  experiment: (id: number) => get<ExperimentDetail>(`/experiments/${id}`),
  createExperiment: (body: unknown) => post<ExperimentDetail>("/experiments", body),
  runExperiment: (id: number) => post<ExperimentDetail>(`/experiments/${id}/run`),
  cancelExperiment: (id: number) => post<ExperimentDetail>(`/experiments/${id}/cancel`),
  results: (id: number) => get<ResultsBundle>(`/experiments/${id}/results`),
  mutations: (id: number, snippetId?: number) =>
    get<Paged<MutationInfo>>(
      `/experiments/${id}/mutations${snippetId ? `?snippet_id=${snippetId}` : ""}`
    ),
  logs: (id: number) => get<Paged<LogRow>>(`/experiments/${id}/logs`),

  // datasets
  datasets: () => get<Paged<DatasetInfo>>("/datasets?limit=200"),
  datasetItems: (id: number, offset = 0, limit = 500) =>
    get<Paged<DatasetItemInfo>>(`/datasets/${id}/items?offset=${offset}&limit=${limit}`),
  createDataset: (payload: unknown) => post<{ dataset_id: number; items_added: number }>("/datasets", payload),
  uploadDataset: (form: FormData) =>
    request<{ dataset_id: number; name: string; items_added: number; items_skipped: number }>(
      "/datasets/upload",
      { method: "POST", body: form }
    ),
  deleteDataset: (id: number) => del(`/datasets/${id}`),
  datasetExportUrl: (id: number) => `/api/datasets/${id}/export`,

  // models
  models: () => get<Paged<ModelInfo>>("/models"),
  modelStatus: (id: number) => get(`/models/${id}/status`),

  // admin: user management
  users: () => get<UserShape[]>("/users"),
  createUser: (body: unknown) => post<UserShape>("/users", body),
  updateUser: (id: number, body: unknown) => patch<UserShape>(`/users/${id}`, body),

  // export files (with auth)
  download: (path: string, filename: string) => downloadFile(path, filename),
};

export interface UserShape {
  id: number;
  username: string;
  email: string;
  role: string;
  is_active: boolean;
  auth_provider?: string;
  email_verified?: boolean;
  /** True when a Google identity is attached (Settings → Connected accounts). */
  google_linked?: boolean;
}

export interface LogRow {
  id: number;
  level: string;
  message: string;
  context_json: string;
  created_at?: string;
}

export async function downloadFile(path: string, filename: string): Promise<void> {
  const token = getToken();
  const headers = new Headers();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`/api${path}`, { headers });
  if (!response.ok) throw new ApiError({ error: "HTTP_ERROR", message: "Download failed" }, response.status);
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export function fmt(value: number | null | undefined, digits = 4): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toFixed(digits);
}
