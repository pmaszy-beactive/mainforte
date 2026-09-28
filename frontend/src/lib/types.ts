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

export interface Connection {
  provider: string;
  email: string | null;
  scopes: string[];
  connected_at: string;
  expires_at: string | null;
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
  pools: { full: number; sandbox: number };
  reconciler_configured: boolean;
  app_version: string;
  workers: {
    id: string;
    status: string;
    node: string;
    container_name: string;
    version: string | null;
    last_heartbeat: string;
    current_job: string | null;
  }[];
}
export interface AdminTaskSummary {
  id: string;
  ws_id: string;
  ws_name: string | null;
  persona_id: string | null;
  persona_name: string | null;
  status: string;
  current_stage: number;
  plan_len: number;
  attempt: number;
  schedule: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}
export interface AdminTasks {
  tasks: AdminTaskSummary[];
}
export interface AdminTaskDetail {
  task: AdminTaskSummary & { plan: unknown[]; result: unknown; correlation_id: string | null; thread_id: string | null };
  events: WsEvent[];
}
/** GET/PUT /api/admin/settings/bastion-jenkins response shape: secret fields (the two SSH keys) are
 * masked to a boolean (whether a value is currently set), never the plaintext or ciphertext. */
export interface AdminBastionJenkinsSettings {
  bastion_host: string | null;
  bastion_port: number | null;
  bastion_username: string | null;
  bastion_ssh_key: boolean;
  jenkins_host: string | null;
  jenkins_port: number | null;
  jenkins_username: string | null;
  jenkins_ssh_key: boolean;
  jenkins_provision_job: string | null;
  jenkins_destroy_job: string | null;
  worker_api_url: string | null;
}

/* Billing */
export interface BillingPrice {
  id: string;
  amount_cents: number;
  currency: string;
  interval: string;
}

export interface BillingPlan {
  id: string;
  slug: string;
  name: string;
  features: Record<string, unknown>;
  prices: BillingPrice[];
}

export type BillingSubscriptionStatus =
  | "incomplete"
  | "requires_action"
  | "active"
  | "past_due"
  | "canceled"
  | "unpaid";

export interface BillingSubscription {
  id: string;
  plan_id: string;
  status: BillingSubscriptionStatus;
  current_period_end: string | null;
  cancel_at_period_end: boolean;
}

export interface BillingState {
  plans: BillingPlan[];
  subscription: BillingSubscription | null;
  has_card: boolean;
}
