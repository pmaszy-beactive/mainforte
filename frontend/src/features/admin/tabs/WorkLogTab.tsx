import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { ChevronDown } from "lucide-react";
import { api } from "@/lib/api";
import type { AdminWorkLogItem } from "@/lib/types";
import { useFormat } from "@/hooks/useFormat";
import { Table, type Column } from "@/components/ui/Table";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { cn } from "@/lib/cn";
import { WorkItemDebug, statusTone } from "@/features/admin/WorkItemDebug";

/** Every deferred unit of work in the system regardless of source — a chat turn, a Stripe
 * reconcile run, an agent-worker dispatch, a browser session, a build. Backed by
 * GET /api/admin/work-log, which groups Event rows by base correlation_id (plan part B.2). Row
 * click opens the same detail view as the Events tab's debug drill-down. */
export default function WorkLogTab() {
  const { t } = useTranslation();
  const f = useFormat();
  const [expanded, setExpanded] = useState<string | null>(null);
  const q = useQuery({ queryKey: ["admin", "work-log"], queryFn: api.admin.workLog, refetchInterval: 15_000 });

  const columns: Column<AdminWorkLogItem>[] = [
    {
      key: "started",
      header: t("admin.workLog.started"),
      render: (i) => (
        <button
          onClick={() => setExpanded(expanded === i.correlation_id ? null : i.correlation_id)}
          className="flex items-center gap-1 whitespace-nowrap text-fog-300 hover:text-fog-100"
          aria-expanded={expanded === i.correlation_id}
          title={t("admin.workLog.detail")}
        >
          <ChevronDown className={cn("size-3.5 shrink-0 transition", expanded === i.correlation_id && "rotate-180")} />
          {i.started_at ? f.dateTime(i.started_at) : "—"}
        </button>
      ),
    },
    { key: "kind", header: t("admin.workLog.kind"), render: (i) => <Badge tone="neutral">{i.kind}</Badge> },
    { key: "ws", header: t("admin.workLog.workspace"), render: (i) => <span className="font-mono text-xs text-fog-500">{i.ws_id ?? "—"}</span> },
    { key: "events", header: t("admin.workLog.events"), render: (i) => <span className="tabular-nums text-fog-300">{f.number(i.event_count)}</span> },
    { key: "ended", header: t("admin.workLog.ended"), render: (i) => <span className="text-fog-500">{i.ended_at ? f.dateTime(i.ended_at) : "—"}</span> },
    { key: "status", header: t("admin.workLog.status"), render: (i) => <Badge tone={statusTone(i.status)}>{t(`admin.workLog.status_${i.status}`)}</Badge> },
    { key: "id", header: t("admin.workLog.id"), render: (i) => <span className="font-mono text-xs text-fog-700">{i.correlation_id}</span> },
  ];

  return (
    <div className="space-y-4">
      <Table columns={columns} rows={q.data?.items} rowKey={(i) => i.correlation_id} loading={q.isLoading} error={q.error} empty={t("admin.workLog.empty")} />
      {expanded && (
        <Card className="overflow-hidden !p-0">
          <WorkItemDebug correlationId={expanded} />
        </Card>
      )}
    </div>
  );
}
