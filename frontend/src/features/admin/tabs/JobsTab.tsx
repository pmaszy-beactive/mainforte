import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { api } from "@/lib/api";
import type { AdminJobs } from "@/lib/types";
import { useFormat } from "@/hooks/useFormat";
import { Table, type Column } from "@/components/ui/Table";
import { Card } from "@/components/ui/Card";

type Running = AdminJobs["running"][number];

export default function JobsTab() {
  const { t } = useTranslation();
  const f = useFormat();
  const q = useQuery({ queryKey: ["admin", "jobs"], queryFn: api.admin.jobs, refetchInterval: 10_000 });
  const columns: Column<Running>[] = [
    { key: "name", header: t("admin.jobs.job"), render: (j) => <span className="font-medium">{j.name}</span> },
    { key: "queue", header: t("admin.jobs.queue"), render: (j) => <span className="font-mono text-xs">{j.queue}</span> },
    { key: "ws", header: t("admin.jobs.workspace"), render: (j) => <span className="font-mono text-xs text-fog-500">{j.workspace_id ?? "—"}</span> },
    { key: "started", header: t("admin.jobs.started"), render: (j) => <span className="text-fog-500">{f.relative(j.started_at)}</span> },
    { key: "id", header: "ID", render: (j) => <span className="font-mono text-xs text-fog-700">{j.id}</span> },
  ];
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap gap-3">
        {(q.data?.queues ?? []).map((qu) => (
          <Card key={qu.name} className="min-w-36 px-4 py-3">
            <div className="text-xs uppercase tracking-wider text-fog-500">{qu.name}</div>
            <div className="mt-1 text-xl font-semibold tabular-nums">{f.number(qu.depth)}</div>
          </Card>
        ))}
        {q.data && q.data.queues.length === 0 && <p className="text-sm text-fog-700">{t("admin.jobs.noQueues")}</p>}
      </div>
      <h2 className="text-sm font-semibold text-fog-300">{t("admin.jobs.running")}</h2>
      <Table columns={columns} rows={q.data?.running} rowKey={(j) => j.id} loading={q.isLoading} error={q.error} empty={t("admin.jobs.empty")} />
    </div>
  );
}
