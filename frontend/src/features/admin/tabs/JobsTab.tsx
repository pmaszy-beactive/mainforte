import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Play } from "lucide-react";
import { api } from "@/lib/api";
import type { AdminJobs, AdminScheduledJobs } from "@/lib/types";
import { useFormat } from "@/hooks/useFormat";
import { Table, type Column } from "@/components/ui/Table";
import { Card } from "@/components/ui/Card";

type Running = AdminJobs["running"][number];
type ScheduledJob = AdminScheduledJobs["jobs"][number];

function ScheduledJobsTable() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [justRan, setJustRan] = useState<string | null>(null);
  const q = useQuery({ queryKey: ["admin", "scheduled-jobs"], queryFn: api.admin.scheduledJobs });
  const runNow = useMutation({
    mutationFn: (name: string) => api.admin.runScheduledJob(name),
    onSuccess: (_data, name) => {
      setJustRan(name);
      setTimeout(() => setJustRan(null), 2000);
      qc.invalidateQueries({ queryKey: ["admin", "jobs"] });
    },
  });

  const columns: Column<ScheduledJob>[] = [
    { key: "name", header: t("admin.jobs.job"), render: (j) => <span className="font-medium">{j.name}</span> },
    { key: "task", header: t("admin.jobs.task"), render: (j) => <span className="font-mono text-xs text-fog-500">{j.task}</span> },
    { key: "schedule", header: t("admin.jobs.schedule"), render: (j) => <span className="font-mono text-xs text-fog-500">{j.schedule}</span> },
    { key: "queue", header: t("admin.jobs.queue"), render: (j) => <span className="font-mono text-xs">{j.queue ?? "system"}</span> },
    {
      key: "run",
      header: "",
      render: (j) => (
        <button
          onClick={() => runNow.mutate(j.name)}
          disabled={runNow.isPending && runNow.variables === j.name}
          className="flex items-center gap-1 rounded-lg border border-white/10 bg-ink-950/60 px-2.5 py-1 text-xs text-fog-300 hover:border-ember-500/60 hover:text-fog-100 disabled:opacity-50"
        >
          <Play className="size-3" />
          {justRan === j.name ? t("admin.jobs.queued") : t("admin.jobs.runNow")}
        </button>
      ),
    },
  ];

  return (
    <div className="space-y-2">
      <h2 className="text-sm font-semibold text-fog-300">{t("admin.jobs.scheduled")}</h2>
      <Table columns={columns} rows={q.data?.jobs} rowKey={(j) => j.name} loading={q.isLoading} error={q.error} empty={t("admin.jobs.scheduledEmpty")} />
    </div>
  );
}

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
    <div className="space-y-6">
      <ScheduledJobsTable />
      <div className="space-y-3">
        <div className="flex flex-wrap gap-3">
          {(q.data?.queues ?? []).map((qu) => (
            <Card key={qu.name} className="min-w-36 px-4 py-3">
              <div className="text-xs uppercase tracking-wider text-fog-500">{qu.name}</div>
              <div className="mt-1 text-xl font-semibold tabular-nums">{f.number(qu.depth)}</div>
            </Card>
          ))}
          {q.data && q.data.queues.length === 0 && <p className="text-sm text-fog-700">{t("admin.jobs.noQueues")}</p>}
        </div>
        <h2 className="text-sm font-semibold text-fog-300">{t("admin.jobs.live")}</h2>
        <Table columns={columns} rows={q.data?.running} rowKey={(j) => j.id} loading={q.isLoading} error={q.error} empty={t("admin.jobs.empty")} />
      </div>
    </div>
  );
}
