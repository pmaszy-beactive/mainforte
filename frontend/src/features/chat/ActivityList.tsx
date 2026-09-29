import { useTranslation } from "react-i18next";
import type { WsEvent } from "@/lib/types";
import { useFormat } from "@/hooks/useFormat";
import { Badge } from "@/components/ui/Badge";

/** Per-event list, newest last. Shared by the thinking pill and the "N steps" toggle. */
export function ActivityList({ events }: { events: WsEvent[] }) {
  const { t } = useTranslation();
  const f = useFormat();

  return (
    <ul className="mt-1 max-h-40 space-y-0.5 overflow-y-auto rounded-xl bg-ink-950/60 p-1.5 font-mono text-[11px]">
      {events.length === 0 && <li className="px-2 py-2 text-fog-700">{t("chat.activityEmpty")}</li>}
      {events.map((e) => (
        <li key={e.id} className="flex items-center gap-2 rounded-md px-2 py-1 hover:bg-white/5">
          <span className="text-fog-700">{f.time(e.ts)}</span>
          <Badge tone={e.type.endsWith(".error") || e.type.endsWith(".failed") ? "red" : "neutral"}>{e.type}</Badge>
          <span className="text-fog-500">
            {e.actor.type}:{e.actor.id}
          </span>
          <span className="min-w-0 flex-1 truncate text-fog-500">{JSON.stringify(e.payload)}</span>
        </li>
      ))}
    </ul>
  );
}
