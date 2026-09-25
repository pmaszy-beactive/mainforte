import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { api } from "@/lib/api";
import type { AdminError } from "@/lib/types";
import { useFormat } from "@/hooks/useFormat";
import { Table, type Column } from "@/components/ui/Table";
import { Badge } from "@/components/ui/Badge";

export default function ErrorsTab() {
  const { t } = useTranslation();
  const f = useFormat();
  const q = useQuery({ queryKey: ["admin", "errors"], queryFn: () => api.admin.errors(200), refetchInterval: 30_000 });
  const columns: Column<AdminError>[] = [
    { key: "ts", header: t("admin.errors.time"), render: (e) => <span className="whitespace-nowrap text-fog-500">{f.dateTime(e.ts)}</span> },
    { key: "type", header: t("admin.errors.type"), render: (e) => <Badge tone="red">{e.type}</Badge> },
    { key: "message", header: t("admin.errors.message"), render: (e) => <span className="font-mono text-xs">{e.message}</span> },
    { key: "path", header: t("admin.errors.path"), render: (e) => <span className="font-mono text-xs text-fog-500">{e.path ?? "—"}</span> },
    { key: "user", header: t("admin.errors.user"), render: (e) => <span className="font-mono text-xs text-fog-500">{e.user_id ?? "—"}</span> },
  ];
  return <Table columns={columns} rows={q.data?.errors} rowKey={(e) => e.id} loading={q.isLoading} error={q.error} empty={t("admin.errors.empty")} />;
}
