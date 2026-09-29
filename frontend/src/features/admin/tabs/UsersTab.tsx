import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router";
import { Search, UserCog } from "lucide-react";
import { useTranslation } from "react-i18next";
import { api } from "@/lib/api";
import type { AdminUser } from "@/lib/types";
import { useAuth } from "@/stores/auth";
import { useFormat } from "@/hooks/useFormat";
import { Table, type Column } from "@/components/ui/Table";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";

const PAGE_SIZE = 50;

export default function UsersTab() {
  const { t } = useTranslation();
  const f = useFormat();
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const users = useQuery({
    queryKey: ["admin", "users", q, offset],
    queryFn: () => api.admin.users(q, offset, PAGE_SIZE),
  });
  const setSession = useAuth((s) => s.setSession);
  const qc = useQueryClient();
  const nav = useNavigate();

  const setSearch = (v: string) => {
    setQ(v);
    setOffset(0);
  };

  const impersonate = useMutation({
    mutationFn: api.auth.impersonate,
    onSuccess: ({ token }) => {
      setSession(token, null);
      qc.clear();
      nav("/app", { replace: true });
    },
  });

  const columns: Column<AdminUser>[] = [
    { key: "email", header: t("admin.users.email"), render: (u) => <span className="font-medium">{u.email}</span> },
    { key: "name", header: t("admin.users.name"), render: (u) => u.name },
    { key: "role", header: t("admin.users.role"), render: (u) => <Badge tone={u.role === "superuser" ? "amber" : "neutral"}>{u.role}</Badge> },
    { key: "plan", header: t("admin.users.plan"), render: (u) => u.plan ?? "—" },
    { key: "last_login", header: t("admin.users.lastLogin"), render: (u) => <span className="text-fog-500">{u.last_login_at ? f.relative(u.last_login_at) : "—"}</span> },
    { key: "last_active", header: t("admin.users.lastActive"), render: (u) => <span className="text-fog-500">{u.last_active_at ? f.relative(u.last_active_at) : "—"}</span> },
    {
      key: "actions",
      header: "",
      className: "text-right",
      render: (u) => (
        <Button
          size="sm"
          variant="outline"
          onClick={(e) => {
            e.stopPropagation();
            impersonate.mutate(u.id);
          }}
          loading={impersonate.isPending && impersonate.variables === u.id}
        >
          <UserCog className="size-3.5" /> {t("admin.users.impersonate")}
        </Button>
      ),
    },
  ];

  const total = users.data?.total ?? 0;
  const rangeStart = total === 0 ? 0 : offset + 1;
  const rangeEnd = Math.min(offset + PAGE_SIZE, total);

  return (
    <div className="space-y-4">
      <label className="glass flex h-10 max-w-md items-center gap-2 rounded-xl px-3">
        <Search className="size-4 text-fog-500" />
        <input value={q} onChange={(e) => setSearch(e.target.value)} placeholder={t("admin.users.search")} className="flex-1 bg-transparent text-sm placeholder:text-fog-700" />
      </label>
      <Table
        columns={columns}
        rows={users.data?.users}
        rowKey={(u) => u.id}
        loading={users.isLoading}
        error={users.error}
        empty={t("admin.users.empty")}
        onRowClick={(u) => nav(`/admin/users/${u.id}`)}
      />
      <div className="flex items-center justify-between text-sm text-fog-500">
        <span>{t("admin.users.showingRange", { start: rangeStart, end: rangeEnd, total })}</span>
        <div className="flex gap-2">
          <Button size="sm" variant="outline" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
            {t("admin.users.prev")}
          </Button>
          <Button size="sm" variant="outline" disabled={offset + PAGE_SIZE >= total} onClick={() => setOffset(offset + PAGE_SIZE)}>
            {t("admin.users.next")}
          </Button>
        </div>
      </div>
    </div>
  );
}
