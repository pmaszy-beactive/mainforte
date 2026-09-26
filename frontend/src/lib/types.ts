export type Role = "user" | "superuser";

export interface User {
  id: string;
  email: string;
  name: string;
  role: Role;
  locale?: string | null;
  timezone?: string | null;
}

export interface Workspace {
  id: string;
  name: string;
  role: string;
}

export interface Impersonation {
  by_user_id: string;
  by_email: string;
}

export interface Me {
  user: User;
  workspaces: Workspace[];
  impersonating: Impersonation | null;
}

export interface AuthResponse {
  token: string;
  user: User;
}

export interface Actor {
  type: string;
  id: string;
}

export interface WsEvent<P = Record<string, unknown>> {
  id: string;
  ts: string;
  type: string;
  ws_id: string;
  user_id: string | null;
  actor: Actor;
  correlation_id: string | null;
  causation_id: string | null;
  ephemeral?: boolean;
  payload: P;
}

export interface ChatMessagePayload {
  thread_id: string | null;
  text: string;
  client_msg_id?: string;
  attachments?: Attachment[];
}

/** Server-side upload record; `url` needs auth (Bearer or `?token=`). */
export interface UploadResult {
  id: string;
  key: string;
  name: string;
  content_type: string;
  size: number;
  url: string;
}

export interface Attachment extends UploadResult {
  /** Present only on optimistic (not yet sent) attachments. */
  localId?: string;
}

export interface ChatPostResponse {
  event_id: string;
  thread_id: string;
  duplicate: boolean;
}

export interface ReplyPayload {
  thread_id: string | null;
  text: string;
}

export type TaskStatus = "planned" | "approved" | "running" | "blocked" | "qa" | "completed" | "failed" | "canceled";

export interface TaskBlockedPayload {
  task_id: string;
  stage_index: number;
  thread_id: string | null;
  reason: string;
}

export interface Task {
  id: string;
  status: TaskStatus;
  plan: unknown[];
  current_stage: number;
  thread_id: string | null;
  persona_id: string | null;
  result: unknown;
}

export interface Widget {
  id: string;
  title: string;
  slug: string;
  version: number;
  status: "active" | "disabled";
  token: string;
  url: string;
}

/* Admin */
export interface AdminUser {
  id: string;
  email: string;
  name: string;
  role: Role;
  created_at: string;
  plan: string | null;
}
export interface AdminUsageByWorkspace {
  ws_id: string;
  ws_name: string;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
}
export interface AdminFinances {
  mrr_cents: number;
  active_subscriptions: number;
  failed_payments: number;
  ai_cost_usd: number;
  ai_charged_usd: number;
  usage_by_workspace: AdminUsageByWorkspace[];
}
export interface AdminError {
  id: string;
  ts: string;
  type: string;
  message: string;
  user_id: string | null;
  path: string | null;
}
export interface AdminJobs {
  queues: { name: string; depth: number }[];
  running: { id: string; name: string; queue: string; started_at: string; workspace_id: string | null }[];
}
export interface AdminWorkers {
  desired: number;
  workers: { id: string; status: string; node: string; last_heartbeat: string; current_job: string | null }[];
}
