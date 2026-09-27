import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { ChevronDown } from "lucide-react";
import { api } from "@/lib/api";
import type { AdminTaskSummary } from "@/lib/types";
import { useFormat } from "@/hooks/useFormat";
import { Table, type Column } from "@/components/ui/Table";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Spinner } from "@/components/ui/Spinner";
import { cn } from "@/lib/cn";

function statusTone(status: string): "neutral" | "amber" | "green" | "red" {
  if (status === "completed") return "green";
  if (status === "failed" || status === "qa_failed") return "red";
  if (status === "blocked" || status === "retrying") return "amber";
  return "neutral";
}

function TaskDetail({ taskId }: { taskId: string }) {
  const { t } = useTranslation();
  const f = useFormat();
  const q = useQuery({ queryKey: ["admin", "task", taskId], queryFn: () => api.admin.taskDetail(taskId) });

  if (q.isLoading) return <Spinner className="mx-auto my-6" />;
  if (q.error) return <p className="px-1 py-4 text-sm text-red-300">{q.error instanceof Error ? q.error.message : t("common.loadFailed")}</p>;
  if (!q.data) return null;

  const { task, events } = q.data;
  return (
    <div className="space-y-4 border-t border-white/5 p-4">
      <div>
        <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-fog-500">
          {t("admin.tasks.events")} ({f.number(events.length)})
        </h3>
        <ul className="max-h-80 space-y-0.5 overflow-y-auto rounded-xl bg-ink-950/60 p-1.5 font-mono text-[11px]">
          {events.length === 0 && <li className="px-2 py-2 text-fog-700">{t("admin.tasks.empty")}</li>}
          {events.map((e) => (
            <li key={e.id} className="flex items-start gap-2 rounded-md px-2 py-1 hover:bg-white/5">
              <span className="whitespace-nowrap text-fog-700">{f.dateTime(e.ts)}</span>
              <Badge tone={/\.(error|failed)$/.test(e.type) ? "red" : "neutral"}>{e.type}</Badge>
              <span className="min-w-0 flex-1 truncate text-fog-500">{JSON.stringify(e.payload)}</span>
            </li>
          ))}
        </ul>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-fog-500">{t("admin.tasks.plan")}</h3>
          <pre className="max-h-64 overflow-auto rounded-xl bg-ink-950/60 p-2.5 text-[11px] text-fog-500">{JSON.stringify(task.plan, null, 2)}</pre>
        </div>
        <div>
          <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-fog-500">{t("admin.tasks.result")}</h3>
          <pre className="max-h-64 overflow-auto rounded-xl bg-ink-950/60 p-2.5 text-[11px] text-fog-500">{JSON.stringify(task.result, null, 2)}</pre>
        </div>
      </div>
    </div>
  );
}

export default function TasksTab() {
  const { t } = useTranslation();
  const f = useFormat();
  const [status, setStatus] = useState("");
  const [ws, setWs] = useState("");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const q = useQuery({
    queryKey: ["admin", "tasks", status, ws],
    queryFn: () => api.admin.tasks({ status: status || undefined, workspace_id: ws || undefined, limit: 200 }),
    refetchInterval: 10_000,
  });

  const columns: Column<AdminTaskSummary>[] = [
    {
      key: "id",
      header: "ID",
      render: (t_) => (
        <button
          onClick={() => setExpandedId(expandedId === t_.id ? null : t_.id)}
          className="flex items-center gap-1 font-mono text-xs text-fog-300 hover:text-fog-100"
          aria-expanded={expandedId === t_.id}
        >
          <ChevronDown className={cn("size-3.5 shrink-0 transition", expandedId === t_.id && "rotate-180")} />
          {t_.id}
        </button>
      ),
    },
    { key: "status", header: t("admin.tasks.status"), render: (t_) => <Badge tone={statusTone(t_.status)}>{t_.status}</Badge> },
    { key: "ws", header: t("admin.tasks.workspace"), render: (t_) => <span className="text-fog-500">{t_.ws_name ?? t_.ws_id}</span> },
    { key: "persona", header: t("admin.tasks.persona"), render: (t_) => <span className="text-fog-500">{t_.persona_name ?? "—"}</span> },
    { key: "stage", header: t("admin.tasks.stage"), render: (t_) => <span className="tabular-nums text-fog-500">{t_.current_stage + 1}/{t_.plan_len}</span> },
    { key: "attempt", header: t("admin.tasks.attempt"), render: (t_) => <span className="tabular-nums text-fog-500">{t_.attempt}</span> },
    { key: "created", header: t("admin.tasks.created"), render: (t_) => <span className="whitespace-nowrap text-fog-500">{f.relative(t_.created_at)}</span> },
  ];

  const inputCls = "h-10 rounded-xl border border-white/10 bg-ink-950/60 px-3 text-sm placeholder:text-fog-700 focus:border-ember-500/60";
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        <input value={status} onChange={(e) => setStatus(e.target.value)} placeholder={t("admin.tasks.filterStatus")} className={inputCls} />
        <input value={ws} onChange={(e) => setWs(e.target.value)} placeholder={t("admin.tasks.filterWorkspace")} className={inputCls} />
      </div>
      <Table columns={columns} rows={q.data?.tasks} rowKey={(t_) => t_.id} loading={q.isLoading} error={q.error} empty={t("admin.tasks.empty")} />
      {expandedId && (
        <Card className="overflow-hidden !p-0">
          <TaskDetail taskId={expandedId} />
        </Card>
      )}
    </div>
  );
}
