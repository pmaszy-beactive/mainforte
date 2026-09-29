import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router";
import { ArrowLeft } from "lucide-react";
import { useTranslation } from "react-i18next";
import { api } from "@/lib/api";
import type { Role } from "@/lib/types";
import { useFormat } from "@/hooks/useFormat";
import { useAuth } from "@/stores/auth";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Alert } from "@/components/ui/Alert";
import { FullPageSpinner } from "@/components/ui/Spinner";
import { cn } from "@/lib/cn";

const PLAN_OPTIONS = ["trial", "good", "better", "best"] as const;
const TABS = ["profile", "usage", "license"] as const;
type Tab = (typeof TABS)[number];

function subscriptionTone(status: string | null): "neutral" | "amber" | "green" | "red" {
  if (status === "active") return "green";
  if (status === "past_due" || status === "requires_action" || status === "incomplete") return "amber";
  if (status === "canceled" || status === "unpaid") return "red";
  return "neutral";
}

export default function UserDetail() {
  const { t } = useTranslation();
  const f = useFormat();
  const { id = "" } = useParams<{ id: string }>();
  const me = useAuth((s) => s.user);
  const qc = useQueryClient();
  const [tab, setTab] = useState<Tab>("profile");

  const q = useQuery({ queryKey: ["admin", "user", id], queryFn: () => api.admin.userDetail(id) });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["admin", "user", id] });
    qc.invalidateQueries({ queryKey: ["admin", "users"] });
  };

  const setActive = useMutation({ mutationFn: (is_active: boolean) => api.admin.setUserActive(id, is_active), onSuccess: invalidate });
  const setRole = useMutation({ mutationFn: (role: string) => api.admin.setUserRole(id, role), onSuccess: invalidate });
  const removeMembership = useMutation({ mutationFn: (workspaceId: string) => api.admin.removeMembership(id, workspaceId), onSuccess: invalidate });
  const overridePlan = useMutation({
    mutationFn: ({ workspaceId, plan }: { workspaceId: string; plan: string }) => api.admin.overridePlan(workspaceId, plan),
    onSuccess: invalidate,
  });
  const addMembership = useMutation({
    mutationFn: (b: { workspace_id: string; role?: string }) => api.admin.addMembership(id, b),
    onSuccess: () => {
      invalidate();
      setNewWsId("");
    },
  });

  const [armedSuspend, setArmedSuspend] = useState(false);
  const [pendingRole, setPendingRole] = useState<Role | null>(null);
  const [newWsId, setNewWsId] = useState("");
  const [newWsRole, setNewWsRole] = useState("member");
  const [planDraft, setPlanDraft] = useState<Record<string, string>>({});

  if (q.isLoading) return <FullPageSpinner />;
  if (q.error) return <Alert tone="error">{q.error instanceof Error ? q.error.message : t("common.loadFailed")}</Alert>;
  if (!q.data) return null;
  const { user, memberships, usage_by_workspace } = q.data;

  return (
    <div className="space-y-4">
      <Link to="/admin/users" className="inline-flex items-center gap-1.5 text-xs text-fog-500 hover:text-fog-100">
        <ArrowLeft className="size-3.5" /> {t("admin.users.back")}
      </Link>

      <div className="glass flex flex-wrap items-center gap-3 rounded-2xl p-4">
        <div>
          <div className="text-lg font-semibold">{user.name || user.email}</div>
          <div className="text-sm text-fog-500">{user.email}</div>
        </div>
        <Badge tone={user.role === "superuser" ? "amber" : "neutral"}>{user.role}</Badge>
        <Badge tone={user.is_active ? "green" : "red"}>{user.is_active ? t("admin.users.isActive") : t("admin.users.suspended")}</Badge>
      </div>

      <nav className="flex gap-1 border-b border-white/10">
        {TABS.map((tb) => (
          <button
            key={tb}
            onClick={() => setTab(tb)}
            className={cn(
              "-mb-px whitespace-nowrap border-b-2 px-3 py-2.5 text-sm transition",
              tab === tb ? "border-ember-500 text-fog-100" : "border-transparent text-fog-500 hover:text-fog-300",
            )}
          >
            {t(`admin.users.${tb}`)}
          </button>
        ))}
      </nav>

      {tab === "profile" && (
        <div className="glass space-y-4 rounded-2xl p-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <div className="text-xs uppercase tracking-wider text-fog-500">{t("admin.users.created")}</div>
              <div className="text-sm">{f.dateTime(user.created_at)}</div>
            </div>
            <div>
              <div className="text-xs uppercase tracking-wider text-fog-500">{t("admin.users.lastLogin")}</div>
              <div className="text-sm">{user.last_login_at ? f.relative(user.last_login_at) : "—"}</div>
            </div>
            <div>
              <div className="text-xs uppercase tracking-wider text-fog-500">{t("admin.users.lastActive")}</div>
              <div className="text-sm">{user.last_active_at ? f.relative(user.last_active_at) : "—"}</div>
            </div>
            <div>
              <div className="text-xs uppercase tracking-wider text-fog-500">{t("admin.users.emailVerified")}</div>
              <div className="text-sm">{user.email_verified_at ? f.dateTime(user.email_verified_at) : t("admin.users.notVerified")}</div>
            </div>
            <div>
              <div className="text-xs uppercase tracking-wider text-fog-500">{t("admin.users.locale")}</div>
              <div className="text-sm">{user.locale ?? "—"}</div>
            </div>
            <div>
              <div className="text-xs uppercase tracking-wider text-fog-500">{t("admin.users.timezone")}</div>
              <div className="text-sm">{user.timezone ?? "—"}</div>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3 border-t border-white/5 pt-4">
            <label className="flex items-center gap-2 text-sm">
              <span className="text-fog-500">{t("admin.users.role")}</span>
              <select
                value={pendingRole ?? user.role}
                onChange={(e) => setPendingRole(e.target.value as Role)}
                className="h-9 rounded-lg border border-white/10 bg-ink-950/60 px-2 text-sm"
              >
                <option value="user">user</option>
                <option value="superuser">superuser</option>
              </select>
            </label>
            {pendingRole && pendingRole !== user.role && (
              <Button
                size="sm"
                loading={setRole.isPending}
                onClick={() => {
                  if (window.confirm(t("admin.users.roleConfirm"))) {
                    setRole.mutate(pendingRole, { onSuccess: () => setPendingRole(null) });
                  }
                }}
              >
                {t("common.save")}
              </Button>
            )}
            {setRole.isError && <span className="text-xs text-red-300">{setRole.error.message}</span>}

            <div className="ml-auto flex items-center gap-2">
              {me?.id === user.id ? null : (
                <Button
                  size="sm"
                  variant={user.is_active ? "danger" : "outline"}
                  loading={setActive.isPending}
                  onClick={() => {
                    if (user.is_active && !armedSuspend) {
                      setArmedSuspend(true);
                      return;
                    }
                    setArmedSuspend(false);
                    setActive.mutate(!user.is_active);
                  }}
                >
                  {user.is_active ? (armedSuspend ? t("admin.users.suspendConfirm") : t("admin.users.suspend")) : t("admin.users.reactivate")}
                </Button>
              )}
            </div>
          </div>
          {setActive.isError && <Alert tone="error">{setActive.error.message}</Alert>}
        </div>
      )}

      {tab === "usage" && (
        <div className="glass overflow-hidden rounded-2xl">
          {usage_by_workspace.length === 0 ? (
            <p className="px-4 py-8 text-center text-sm text-fog-700">{t("admin.users.noUsage")}</p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-white/10 text-left text-[11px] uppercase tracking-wider text-fog-500">
                  <th className="px-4 py-3 font-medium">{t("admin.finances.workspace")}</th>
                  <th className="px-4 py-3 font-medium">{t("admin.users.plan")}</th>
                  <th className="px-4 py-3 font-medium">{t("admin.finances.inputTokens")}</th>
                  <th className="px-4 py-3 font-medium">{t("admin.finances.outputTokens")}</th>
                  <th className="px-4 py-3 font-medium">{t("admin.finances.cost")}</th>
                </tr>
              </thead>
              <tbody>
                {usage_by_workspace.map((u) => {
                  const m = memberships.find((mm) => mm.workspace_id === u.ws_id);
                  return (
                    <tr key={u.ws_id} className="border-b border-white/5 last:border-0">
                      <td className="px-4 py-2.5">{u.ws_name}</td>
                      <td className="px-4 py-2.5">{m?.plan ?? "—"}</td>
                      <td className="px-4 py-2.5 tabular-nums">{f.number(u.input_tokens)}</td>
                      <td className="px-4 py-2.5 tabular-nums">{f.number(u.output_tokens)}</td>
                      <td className="px-4 py-2.5 tabular-nums">{f.usd(u.cost_usd)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      )}

      {tab === "license" && (
        <div className="space-y-4">
          <p className="text-xs text-fog-500">{t("admin.users.planOverrideNote")}</p>

          {memberships.length === 0 ? (
            <p className="glass rounded-2xl px-4 py-8 text-center text-sm text-fog-700">{t("admin.users.noMemberships")}</p>
          ) : (
            <div className="space-y-3">
              {memberships.map((m) => (
                <div key={m.membership_id} className="glass space-y-3 rounded-2xl p-4">
                  <div className="flex flex-wrap items-center gap-3">
                    <div className="font-medium">{m.workspace_name}</div>
                    <Badge tone="neutral">{m.role}</Badge>
                    <Badge tone={subscriptionTone(m.subscription_status)}>{m.subscription_status ?? "no subscription"}</Badge>
                    <Button
                      size="sm"
                      variant="danger"
                      className="ml-auto"
                      loading={removeMembership.isPending && removeMembership.variables === m.workspace_id}
                      onClick={() => {
                        if (window.confirm(t("admin.users.removeMembership") + "?")) removeMembership.mutate(m.workspace_id);
                      }}
                    >
                      {t("admin.users.removeMembership")}
                    </Button>
                  </div>
                  {removeMembership.isError && removeMembership.variables === m.workspace_id && (
                    <Alert tone="error">{removeMembership.error.message}</Alert>
                  )}
                  <div className="flex flex-wrap items-center gap-2 border-t border-white/5 pt-3">
                    <span className="text-sm text-fog-500">{t("admin.users.overridePlan")}</span>
                    <select
                      value={planDraft[m.workspace_id] ?? m.plan}
                      onChange={(e) => setPlanDraft((d) => ({ ...d, [m.workspace_id]: e.target.value }))}
                      className="h-9 rounded-lg border border-white/10 bg-ink-950/60 px-2 text-sm"
                    >
                      {PLAN_OPTIONS.map((p) => (
                        <option key={p} value={p}>
                          {p}
                        </option>
                      ))}
                    </select>
                    <Button
                      size="sm"
                      variant="outline"
                      loading={overridePlan.isPending && overridePlan.variables?.workspaceId === m.workspace_id}
                      disabled={(planDraft[m.workspace_id] ?? m.plan) === m.plan}
                      onClick={() => overridePlan.mutate({ workspaceId: m.workspace_id, plan: planDraft[m.workspace_id] ?? m.plan })}
                    >
                      {t("common.save")}
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}

          <form
            className="glass flex flex-wrap items-end gap-3 rounded-2xl p-4"
            onSubmit={(e) => {
              e.preventDefault();
              if (newWsId.trim()) addMembership.mutate({ workspace_id: newWsId.trim(), role: newWsRole });
            }}
          >
            <label className="block space-y-1.5">
              <span className="text-xs font-medium uppercase tracking-wider text-fog-500">{t("admin.users.workspace")}</span>
              <input
                value={newWsId}
                onChange={(e) => setNewWsId(e.target.value)}
                placeholder="workspace id"
                className="block h-9 w-64 rounded-lg border border-white/10 bg-ink-950/60 px-3 text-sm"
              />
            </label>
            <label className="block space-y-1.5">
              <span className="text-xs font-medium uppercase tracking-wider text-fog-500">{t("admin.users.membershipRole")}</span>
              <select value={newWsRole} onChange={(e) => setNewWsRole(e.target.value)} className="block h-9 rounded-lg border border-white/10 bg-ink-950/60 px-2 text-sm">
                <option value="member">member</option>
                <option value="admin">admin</option>
                <option value="owner">owner</option>
              </select>
            </label>
            <Button type="submit" size="sm" loading={addMembership.isPending} disabled={!newWsId.trim()}>
              {t("admin.users.addToWorkspace")}
            </Button>
            {addMembership.isError && <span className="text-xs text-red-300">{addMembership.error.message}</span>}
          </form>
        </div>
      )}
    </div>
  );
}
