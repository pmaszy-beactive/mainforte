import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { ChevronDown } from "lucide-react";
import { api } from "@/lib/api";
import type { WsEvent } from "@/lib/types";
import { useFormat } from "@/hooks/useFormat";
import { Table, type Column } from "@/components/ui/Table";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { cn } from "@/lib/cn";
import { WorkItemDebug } from "@/features/admin/WorkItemDebug";

// Only events emitted with a correlation_id are worth offering a debug drill-down for — today
// that's persona replies, but this stays generic since GET /api/admin/work/{correlation_id} is
// generic too (see the Work Log tab, which opens the same WorkItemDebug for any kind of work).
function isDebuggable(e: WsEvent): boolean {
  return e.type.startsWith("persona.reply.") && !!e.correlation_id;
}

export default function EventsTab() {
  const { t } = useTranslation();
  const f = useFormat();
  const [type, setType] = useState("");
  const [ws, setWs] = useState("");
  const [expandedCorrelationId, setExpandedCorrelationId] = useState<string | null>(null);
  const q = useQuery({
    queryKey: ["admin", "events", type, ws],
    queryFn: () => api.admin.events({ type: type || undefined, workspace_id: ws || undefined, limit: 200 }),
  });
  const columns: Column<WsEvent>[] = [
    {
      key: "ts",
      header: t("admin.events.time"),
      render: (e) =>
        isDebuggable(e) ? (
          <button
            onClick={() => setExpandedCorrelationId(expandedCorrelationId === e.correlation_id ? null : e.correlation_id)}
            className="flex items-center gap-1 whitespace-nowrap text-fog-300 hover:text-fog-100"
            aria-expanded={expandedCorrelationId === e.correlation_id}
            title={t("admin.events.debug")}
          >
            <ChevronDown className={cn("size-3.5 shrink-0 transition", expandedCorrelationId === e.correlation_id && "rotate-180")} />
            {f.dateTime(e.ts)}
          </button>
        ) : (
          <span className="whitespace-nowrap text-fog-500">{f.dateTime(e.ts)}</span>
        ),
    },
    { key: "type", header: t("admin.events.type"), render: (e) => <Badge tone={/\.(error|failed)$/.test(e.type) ? "red" : "neutral"}>{e.type}</Badge> },
    { key: "actor", header: t("admin.events.actor"), render: (e) => <span className="font-mono text-xs">{e.actor.type}:{e.actor.id}</span> },
    { key: "ws", header: t("admin.events.workspace"), render: (e) => <span className="font-mono text-xs text-fog-500">{e.ws_id}</span> },
    { key: "payload", header: t("admin.events.payload"), render: (e) => <code className="block max-w-md truncate text-xs text-fog-500">{JSON.stringify(e.payload)}</code> },
  ];
  const inputCls = "h-10 rounded-xl border border-white/10 bg-ink-950/60 px-3 text-sm placeholder:text-fog-700 focus:border-ember-500/60";
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        <input value={type} onChange={(e) => setType(e.target.value)} placeholder={t("admin.events.filterType")} className={inputCls} />
        <input value={ws} onChange={(e) => setWs(e.target.value)} placeholder={t("admin.events.filterWorkspace")} className={inputCls} />
      </div>
      <Table columns={columns} rows={q.data?.events} rowKey={(e) => e.id} loading={q.isLoading} error={q.error} empty={t("admin.events.empty")} />
      {expandedCorrelationId && (
        <Card className="overflow-hidden !p-0">
          <WorkItemDebug correlationId={expandedCorrelationId} />
        </Card>
      )}
    </div>
  );
}
