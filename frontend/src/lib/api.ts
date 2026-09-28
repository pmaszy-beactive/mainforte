import { getToken, useAuth } from "@/stores/auth";
import type {
  AdminBastionJenkinsSettings,
  AdminChatTurnDetail,
  AdminError,
  AdminFinances,
  AdminJobs,
  AdminScheduledJobs,
  AdminTaskDetail,
  AdminTasks,
  AdminUser,
  AdminWorkers,
  AuthResponse,
  BillingState,
  BillingSubscription,
  ChatPostResponse,
  Connection,
  Me,
  Task,
  Widget,
  Workspace,
  WsEvent,
} from "./types";

export const API_URL: string = (import.meta.env.VITE_API_URL as string | undefined) ?? "";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public body?: unknown,
  ) {
    super(message);
  }
}

type Query = Record<string, string | number | boolean | null | undefined>;

function qs(q?: Query): string {
  if (!q) return "";
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(q)) if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
}

async function request<T>(method: string, path: string, body?: unknown, query?: Query): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";

  const res = await fetch(`${API_URL}${path}${qs(query)}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  if (res.status === 401 && token) useAuth.getState().clear();
  if (res.status === 204) return undefined as T;

  const text = await res.text();
  let data: unknown = undefined;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }
  if (!res.ok) {
    const d = data as { detail?: unknown; message?: string } | undefined;
    const msg =
      (typeof d?.detail === "string" && d.detail) || d?.message || (typeof data === "string" && data) || res.statusText;
    throw new ApiError(res.status, msg || `HTTP ${res.status}`, data);
  }
  return data as T;
}

const get = <T>(path: string, query?: Query) => request<T>("GET", path, undefined, query);
const post = <T>(path: string, body?: unknown) => request<T>("POST", path, body ?? {});
const patch = <T>(path: string, body: unknown) => request<T>("PATCH", path, body);
const put = <T>(path: string, body: unknown) => request<T>("PUT", path, body);

/** True when a failed request should be retried (network, 5xx, 408, 429). */
export function isRetryable(e: unknown): boolean {
  if (e instanceof ApiError) return e.status >= 500 || e.status === 408 || e.status === 429 || e.status === 0;
  return true;
}

/** Append `?token=` so an authenticated resource can be used in <img src> / <a href>. */
export function authedUrl(path: string): string {
  const token = getToken();
  const u = new URL(path, API_URL || window.location.origin);
  if (token) u.searchParams.set("token", token);
  return u.toString();
}

/** URL of the /ws endpoint for the configured API origin. */
export function wsUrl(params: Record<string, string>): string {
  const base = API_URL || window.location.origin;
  const u = new URL("/ws", base);
  u.protocol = u.protocol === "https:" ? "wss:" : "ws:";
  for (const [k, v] of Object.entries(params)) u.searchParams.set(k, v);
  return u.toString();
}

export const api = {
  auth: {
    register: (b: { email: string; password: string; name: string }) => post<AuthResponse>("/api/auth/register", b),
    login: (b: { email: string; password: string }) => post<AuthResponse>("/api/auth/login", b),
    magicLink: (email: string) => post<void>("/api/auth/magic-link", { email }),
    magicVerify: (token: string) => post<AuthResponse>("/api/auth/magic-link/verify", { token }),
    forgotPassword: (email: string) => post<void>("/api/auth/forgot-password", { email }),
    resetPassword: (b: { token: string; password: string }) => post<void>("/api/auth/reset-password", b),
    logout: () => post<void>("/api/auth/logout"),
    googleStartUrl: () => `${API_URL}/api/auth/google/start`,
    connectGoogleUrl: (scopes: string[]) =>
      authedUrl(`${API_URL}/api/auth/google/connect${qs({ scopes: scopes.join(",") })}`),
    impersonate: (userId: string) => post<{ token: string }>(`/api/auth/impersonate/${encodeURIComponent(userId)}`),
    stopImpersonate: () => post<{ token: string }>("/api/auth/impersonate/stop"),
  },
  settings: {
    connections: () => get<{ connections: Connection[] }>("/api/auth/connections"),
    disconnect: (provider: string) => post<void>(`/api/auth/connections/${encodeURIComponent(provider)}/disconnect`),
  },
  push: {
    register: (b: { platform: string; token: string }) => post<void>("/api/push/register", b),
  },
  me: Object.assign(() => get<Me>("/api/me"), {
    update: (b: { locale?: string; timezone?: string }) => patch<Me>("/api/me", b),
  }),
  workspaces: {
    list: () => get<Workspace[]>("/api/workspaces"),
    create: (name: string) => post<Workspace>("/api/workspaces", { name }),
    addMember: (id: string, b: { email: string; role: string }) =>
      post<void>(`/api/workspaces/${encodeURIComponent(id)}/members`, b),
    events: (id: string, q: { after?: string; limit?: number }) =>
      get<{ events: WsEvent[] }>(`/api/workspaces/${encodeURIComponent(id)}/events`, q),
    chat: (id: string, b: { client_msg_id: string; thread_id?: string | null; text: string; attachments?: { id: string }[] }) =>
      post<ChatPostResponse>(`/api/workspaces/${encodeURIComponent(id)}/chat`, b),
    cancelReply: (id: string, b: { thread_id?: string | null; correlation_id?: string | null }) =>
      post<void>(`/api/workspaces/${encodeURIComponent(id)}/chat/cancel`, b),
    uploadUrl: (id: string) => `${API_URL}/api/workspaces/${encodeURIComponent(id)}/uploads`,
  },
  tasks: {
    get: (wsId: string, taskId: string) =>
      get<Task>(`/api/workspaces/${encodeURIComponent(wsId)}/tasks/${encodeURIComponent(taskId)}`),
    approve: (wsId: string, taskId: string) =>
      post<{ event_id: string; status: string }>(`/api/workspaces/${encodeURIComponent(wsId)}/tasks/${encodeURIComponent(taskId)}/approve`),
    reject: (wsId: string, taskId: string) =>
      post<{ event_id: string; status: string }>(`/api/workspaces/${encodeURIComponent(wsId)}/tasks/${encodeURIComponent(taskId)}/reject`),
    input: (wsId: string, taskId: string, text: string) =>
      post<{ event_id: string; status: string }>(`/api/workspaces/${encodeURIComponent(wsId)}/tasks/${encodeURIComponent(taskId)}/input`, { text }),
  },
  widgets: {
    list: (wsId: string) => get<Widget[]>(`/api/workspaces/${encodeURIComponent(wsId)}/widgets`),
  },
  billing: {
    get: (wsId: string) => get<BillingState>(`/api/workspaces/${encodeURIComponent(wsId)}/billing`),
    createSetupIntent: (wsId: string) =>
      post<{ client_secret: string }>(`/api/workspaces/${encodeURIComponent(wsId)}/billing/setup-intent`),
    confirmSetupIntent: (wsId: string, setupIntentId: string) =>
      post<{ ok: boolean }>(
        `/api/workspaces/${encodeURIComponent(wsId)}/billing/setup-intent/confirm${qs({ setup_intent_id: setupIntentId })}`,
      ),
    subscribe: (wsId: string, b: { price_id: string; coupon_code?: string | null }) =>
      post<BillingSubscription>(`/api/workspaces/${encodeURIComponent(wsId)}/billing/subscribe`, b),
    cancel: (wsId: string) => post<BillingSubscription>(`/api/workspaces/${encodeURIComponent(wsId)}/billing/cancel`),
  },
  admin: {
    users: (q?: string) => get<{ users: AdminUser[] }>("/api/admin/users", { q }),
    finances: () => get<AdminFinances>("/api/admin/finances"),
    errors: (limit = 100) => get<{ errors: AdminError[] }>("/api/admin/errors", { limit }),
    jobs: () => get<AdminJobs>("/api/admin/jobs"),
    scheduledJobs: () => get<AdminScheduledJobs>("/api/admin/scheduled-jobs"),
    runScheduledJob: (name: string) => post<{ queued: boolean; task: string; task_id: string }>(`/api/admin/scheduled-jobs/${encodeURIComponent(name)}/run`),
    tasks: (q?: { status?: string; workspace_id?: string; limit?: number }) =>
      get<AdminTasks>("/api/admin/tasks", q),
    taskDetail: (id: string) => get<AdminTaskDetail>(`/api/admin/tasks/${encodeURIComponent(id)}`),
    workers: () => get<AdminWorkers>("/api/admin/workers"),
    setDesiredWorkers: (count: number) => post<void>("/api/admin/workers/desired", { count }),
    setDesiredSandboxWorkers: (count: number) => post<void>("/api/admin/workers/desired/sandbox", { count }),
    events: (q: { type?: string; workspace_id?: string; limit?: number }) =>
      get<{ events: WsEvent[] }>("/api/admin/events", q),
    chatTurnDetail: (correlationId: string) =>
      get<AdminChatTurnDetail>(`/api/admin/chat-turns/${encodeURIComponent(correlationId)}`),
    bastionJenkinsSettings: () => get<AdminBastionJenkinsSettings>("/api/admin/settings/bastion-jenkins"),
    setBastionJenkinsSettings: (b: Partial<Record<keyof AdminBastionJenkinsSettings, string | number | null>>) =>
      put<AdminBastionJenkinsSettings>("/api/admin/settings/bastion-jenkins", b),
  },
};
