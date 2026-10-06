import { getToken, useAuth } from "@/stores/auth";
import type {
  AdminBastionJenkinsSettings,
  AdminError,
  AdminFinances,
  AdminJobs,
  AdminScheduledJobs,
  AdminSites,
  AdminTaskDetail,
  AdminTasks,
  AdminUserDetail,
  AdminUsersPage,
  AdminWorkers,
  AdminWorkItemDetail,
  AdminWorkLog,
  AuthResponse,
  BillingState,
  BillingSubscription,
  ChatPostResponse,
  Connection,
  LibraryUpload,
  Me,
  MarketplaceListing,
  MarketplaceListingIn,
  MarketplaceOrder,
  Site,
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

/** FastAPI's automatic request-validation errors (422s, e.g. pydantic's EmailStr rejecting the
 * email field) shape `detail` as an array of {loc, msg, type}, not the plain string every
 * explicit `HTTPException(status, "...")` in this backend uses -- without this, those errors fell
 * through to `res.statusText` ("Unprocessable Entity") instead of pydantic's actual, specific
 * message (ticket T02742). */
function detailMessage(detail: unknown): string | null {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const msgs = detail.map((e) => (e && typeof e === "object" && "msg" in e ? String((e as { msg: unknown }).msg) : null)).filter((m): m is string => !!m);
    return msgs.length ? msgs.join(" ") : null;
  }
  return null;
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
    const msg = detailMessage(d?.detail) || d?.message || (typeof data === "string" && data) || res.statusText;
    throw new ApiError(res.status, msg || `HTTP ${res.status}`, data);
  }
  return data as T;
}

const get = <T>(path: string, query?: Query) => request<T>("GET", path, undefined, query);
const post = <T>(path: string, body?: unknown) => request<T>("POST", path, body ?? {});
const patch = <T>(path: string, body: unknown) => request<T>("PATCH", path, body);
const put = <T>(path: string, body: unknown) => request<T>("PUT", path, body);
const del = <T>(path: string) => request<T>("DELETE", path);

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
    update: (b: { name?: string; locale?: string; timezone?: string }) => patch<Me>("/api/me", b),
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
  drafts: {
    get: (wsId: string, threadId: string) =>
      get<{ text: string; updated_at: string | null }>(
        `/api/workspaces/${encodeURIComponent(wsId)}/drafts/${encodeURIComponent(threadId)}`,
      ),
    save: (wsId: string, threadId: string, text: string) =>
      put<{ ok: boolean }>(`/api/workspaces/${encodeURIComponent(wsId)}/drafts/${encodeURIComponent(threadId)}`, { text }),
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
    remove: (wsId: string, widgetId: string) =>
      del<void>(`/api/workspaces/${encodeURIComponent(wsId)}/widgets/${encodeURIComponent(widgetId)}`),
  },
  sites: {
    list: (wsId: string) => get<Site[]>(`/api/workspaces/${encodeURIComponent(wsId)}/sites`),
    destroy: (wsId: string, siteId: string) =>
      post<{ ok: boolean; site_id: string }>(`/api/workspaces/${encodeURIComponent(wsId)}/sites/${encodeURIComponent(siteId)}/destroy`),
  },
  library: {
    uploads: {
      list: (wsId: string) => get<LibraryUpload[]>(`/api/workspaces/${encodeURIComponent(wsId)}/uploads`),
      remove: (wsId: string, uploadId: string) =>
        del<void>(`/api/workspaces/${encodeURIComponent(wsId)}/uploads/${encodeURIComponent(uploadId)}`),
    },
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
  marketplace: {
    listings: (q?: {
      kind?: string;
      category?: string;
      min_price_cents?: number;
      max_price_cents?: number;
      q?: string;
      lat?: number;
      lng?: number;
      radius_km?: number;
      limit?: number;
    }) => get<{ listings: MarketplaceListing[] }>("/api/marketplace/listings", q),
    search: (b: {
      query?: string;
      category?: string | null;
      min_price_cents?: number | null;
      max_price_cents?: number | null;
      kind?: string | null;
      lat?: number | null;
      lng?: number | null;
      radius_km?: number | null;
    }) => post<{ listings: MarketplaceListing[] }>("/api/marketplace/search", b),
    get: (id: string) => get<MarketplaceListing>(`/api/marketplace/listings/${encodeURIComponent(id)}`),
    mine: () => get<{ listings: MarketplaceListing[] }>("/api/marketplace/mine"),
    create: (b: MarketplaceListingIn) => post<MarketplaceListing>("/api/marketplace/listings", b),
    update: (id: string, b: Partial<MarketplaceListingIn> & { photo_upload_ids?: string[] }) =>
      patch<MarketplaceListing>(`/api/marketplace/listings/${encodeURIComponent(id)}`, b),
    publish: (id: string) => post<MarketplaceListing>(`/api/marketplace/listings/${encodeURIComponent(id)}/publish`),
    remove: (id: string) => post<MarketplaceListing>(`/api/marketplace/listings/${encodeURIComponent(id)}/remove`),
    report: (id: string, reason?: string) =>
      post<MarketplaceListing>(`/api/marketplace/listings/${encodeURIComponent(id)}/report`, { reason }),
    placeOrder: (listingId: string, b: { payment_method: string; notes?: string | null }) =>
      post<MarketplaceOrder>(`/api/marketplace/listings/${encodeURIComponent(listingId)}/orders`, b),
    myOrders: () => get<{ orders: MarketplaceOrder[] }>("/api/marketplace/orders/mine"),
    getOrder: (id: string) => get<MarketplaceOrder>(`/api/marketplace/orders/${encodeURIComponent(id)}`),
    releaseEscrow: (id: string) => post<MarketplaceOrder>(`/api/marketplace/orders/${encodeURIComponent(id)}/escrow/release`),
    refundEscrow: (id: string) => post<MarketplaceOrder>(`/api/marketplace/orders/${encodeURIComponent(id)}/escrow/refund`),
    disputeOrder: (id: string, reason?: string) =>
      post<MarketplaceOrder>(`/api/marketplace/orders/${encodeURIComponent(id)}/dispute`, { reason }),
  },
  admin: {
    users: (q?: string, offset?: number, limit?: number) =>
      get<AdminUsersPage>("/api/admin/users", { q, offset, limit }),
    userDetail: (id: string) => get<AdminUserDetail>(`/api/admin/users/${encodeURIComponent(id)}`),
    setUserActive: (id: string, is_active: boolean) =>
      post<{ ok: boolean; user_id: string; is_active: boolean }>(`/api/admin/users/${encodeURIComponent(id)}/active`, { is_active }),
    setUserRole: (id: string, role: string) =>
      post<{ ok: boolean; user_id: string; role: string }>(`/api/admin/users/${encodeURIComponent(id)}/role`, { role }),
    addMembership: (id: string, b: { workspace_id: string; role?: string }) =>
      post<{ ok: boolean; membership_id: string }>(`/api/admin/users/${encodeURIComponent(id)}/memberships`, b),
    removeMembership: (id: string, workspaceId: string) =>
      post<{ ok: boolean }>(`/api/admin/users/${encodeURIComponent(id)}/memberships/${encodeURIComponent(workspaceId)}/remove`, {}),
    overridePlan: (workspaceId: string, plan: string) =>
      post<{ ok: boolean; workspace_id: string; plan: string }>(`/api/admin/workspaces/${encodeURIComponent(workspaceId)}/plan-override`, { plan }),
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
    destroyWorker: (id: string) => post<{ ok: boolean; container_name: string }>(`/api/admin/workers/${encodeURIComponent(id)}/destroy`),
    sites: () => get<AdminSites>("/api/admin/sites"),
    destroySite: (id: string) =>
      post<{ ok: boolean; site_id: string; container_name: string | null }>(`/api/admin/sites/${encodeURIComponent(id)}/destroy`),
    events: (q: { type?: string; workspace_id?: string; limit?: number }) =>
      get<{ events: WsEvent[] }>("/api/admin/events", q),
    workLog: () => get<AdminWorkLog>("/api/admin/work-log"),
    workItemDetail: (correlationId: string) =>
      get<AdminWorkItemDetail>(`/api/admin/work/${encodeURIComponent(correlationId)}`),
    bastionJenkinsSettings: () => get<AdminBastionJenkinsSettings>("/api/admin/settings/bastion-jenkins"),
    setBastionJenkinsSettings: (b: Partial<Record<keyof AdminBastionJenkinsSettings, string | number | null>>) =>
      put<AdminBastionJenkinsSettings>("/api/admin/settings/bastion-jenkins", b),
  },
};
