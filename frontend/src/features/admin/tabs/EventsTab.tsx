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
import { Spinner } from "@/components/ui/Spinner";
import { cn } from "@/lib/cn";

function statusTone(status: string): "neutral" | "amber" | "green" | "red" {
  if (status === "error") return "red";
  if (status === "canceled") return "amber";
  if (status === "in_flight") return "amber";
  return "green";
}

// Only events emitted with a correlation_id are worth offering a debug drill-down for — today
// that's persona replies, but this stays generic since chat-turns/{correlation_id} is generic too.
function isDebuggable(e: WsEvent): boolean {
  return e.type.startsWith("persona.reply.") && !!e.correlation_id;
}

function ChatTurnDebug({ correlationId }: { correlationId: string }) {
  const { t } = useTranslation();
  const f = useFormat();
  const [copied, setCopied] = useState(false);
  const q = useQuery({ queryKey: ["admin", "chat-turn", correlationId], queryFn: () => api.admin.chatTurnDetail(correlationId) });

  if (q.isLoading) return <Spinner className="mx-auto my-6" />;
  if (q.error) return <p className="px-1 py-4 text-sm text-red-300">{q.error instanceof Error ? q.error.message : t("admin.events.debugLoadFailed")}</p>;
  if (!q.data) return null;
  const data = q.data;

  const copy = () => {
    navigator.clipboard.writeText(JSON.stringify(data, null, 2)).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  };

  return (
    <div className="space-y-4 border-t border-white/5 p-4">
      <div className="flex flex-wrap items-center gap-3 text-xs">
        <Badge tone={statusTone(data.status)}>{data.status}</Badge>
        <span className="text-fog-500">{t("admin.events.debugRounds")}: <span className="tabular-nums text-fog-300">{data.rounds}</span></span>
        <span className="text-fog-500">{t("admin.events.debugStarted")}: <span className="text-fog-300">{data.started_at ? f.dateTime(data.started_at) : "—"}</span></span>
        <span className="text-fog-500">{t("admin.events.debugEnded")}: <span className="text-fog-300">{data.ended_at ? f.dateTime(data.ended_at) : "—"}</span></span>
        <button
          onClick={copy}
          className="ml-auto rounded-lg border border-white/10 bg-ink-950/60 px-2.5 py-1 text-fog-300 hover:border-ember-500/60 hover:text-fog-100"
        >
          {copied ? t("admin.events.debugCopied") : t("admin.events.debugCopy")}
        </button>
      </div>

      {data.debug.length === 0 ? (
        <p className="text-sm text-fog-500">{t("admin.events.debugEmpty")}</p>
      ) : (
        <div className="space-y-4">
          {data.debug.map((ev, i) => (
            <div key={ev.id} className="rounded-xl bg-ink-950/60 p-3">
              <div className="mb-2 flex flex-wrap items-center gap-2 text-[11px] text-fog-500">
                <span className="font-mono">#{i + 1}</span>
                <span>{f.dateTime(ev.ts)}</span>
                <span className="font-mono">{ev.payload.model ?? "—"}</span>
                {ev.payload.fallback && <Badge tone="amber">{t("admin.events.debugFallback")}</Badge>}
                {ev.payload.response.stop_reason && <Badge tone="neutral">{ev.payload.response.stop_reason}</Badge>}
              </div>
              <div className="grid gap-3 lg:grid-cols-2">
                <div>
                  <h4 className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-fog-500">{t("admin.events.debugRequest")}</h4>
                  <div className="mb-1.5">
                    <div className="mb-0.5 text-[10px] uppercase tracking-wide text-fog-700">{t("admin.events.debugSystem")}</div>
                    <pre className="max-h-40 overflow-auto rounded-lg bg-ink-900/70 p-2 text-[11px] text-fog-500">{ev.payload.request.system ?? "—"}</pre>
                  </div>
                  <div>
                    <div className="mb-0.5 text-[10px] uppercase tracking-wide text-fog-700">{t("admin.events.debugMessages")}</div>
                    <pre className="max-h-64 overflow-auto rounded-lg bg-ink-900/70 p-2 text-[11px] text-fog-500">{JSON.stringify(ev.payload.request.messages, null, 2)}</pre>
                  </div>
                </div>
                <div>
                  <h4 className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-fog-500">{t("admin.events.debugResponse")}</h4>
                  <pre className="max-h-80 overflow-auto rounded-lg bg-ink-900/70 p-2 text-[11px] text-fog-500">{JSON.stringify(ev.payload.response, null, 2)}</pre>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      <details className="text-xs">
        <summary className="cursor-pointer text-fog-500 hover:text-fog-300">{t("admin.tasks.events")} ({f.number(data.events.length)})</summary>
        <ul className="mt-2 max-h-64 space-y-0.5 overflow-y-auto rounded-xl bg-ink-950/60 p-1.5 font-mono text-[11px]">
          {data.events.map((e) => (
            <li key={e.id} className="flex items-start gap-2 rounded-md px-2 py-1 hover:bg-white/5">
              <span className="whitespace-nowrap text-fog-700">{f.dateTime(e.ts)}</span>
              <Badge tone={/\.(error|failed)$/.test(e.type) ? "red" : "neutral"}>{e.type}</Badge>
              <span className="min-w-0 flex-1 truncate text-fog-500">{JSON.stringify(e.payload)}</span>
            </li>
          ))}
        </ul>
      </details>
    </div>
  );
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
          <ChatTurnDebug correlationId={expandedCorrelationId} />
        </Card>
      )}
    </div>
  );
}
