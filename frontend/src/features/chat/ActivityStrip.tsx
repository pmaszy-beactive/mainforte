import { Activity, ChevronDown } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { WsEvent } from "@/lib/types";
import { useUi } from "@/stores/ui";
import { useFormat } from "@/hooks/useFormat";
import { Badge } from "@/components/ui/Badge";
import { cn } from "@/lib/cn";

/** Everything that isn't a chat bubble, collapsible, newest last. */
export function ActivityStrip({ events }: { events: WsEvent[] }) {
  const { t } = useTranslation();
  const f = useFormat();
  const open = useUi((s) => s.activityOpen);
  const toggle = useUi((s) => s.toggleActivity);
  const latest = events[events.length - 1];

  return (
    <div className="mt-2">
      <button onClick={toggle} className="flex w-full items-center gap-2 rounded-lg px-2 py-1 text-[11px] text-fog-500 hover:text-fog-300 ring-focus" aria-expanded={open}>
        <Activity className="size-3.5" />
        <span className="font-medium uppercase tracking-wider">{t("chat.activity")}</span>
        <span className="text-fog-700">({f.number(events.length)})</span>
        {!open && latest && <span className="ml-1 truncate font-mono text-fog-700">{latest.type}</span>}
        <ChevronDown className={cn("ml-auto size-3.5 transition", open && "rotate-180")} />
      </button>
      {open && (
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
      )}
    </div>
  );
}
