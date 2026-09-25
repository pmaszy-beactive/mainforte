import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { api } from "@/lib/api";
import type { WsEvent } from "@/lib/types";
import { useFormat } from "@/hooks/useFormat";
import { Table, type Column } from "@/components/ui/Table";
import { Badge } from "@/components/ui/Badge";

export default function EventsTab() {
  const { t } = useTranslation();
  const f = useFormat();
  const [type, setType] = useState("");
  const [ws, setWs] = useState("");
  const q = useQuery({
    queryKey: ["admin", "events", type, ws],
    queryFn: () => api.admin.events({ type: type || undefined, workspace_id: ws || undefined, limit: 200 }),
  });
  const columns: Column<WsEvent>[] = [
    { key: "ts", header: t("admin.events.time"), render: (e) => <span className="whitespace-nowrap text-fog-500">{f.dateTime(e.ts)}</span> },
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
    </div>
  );
}
