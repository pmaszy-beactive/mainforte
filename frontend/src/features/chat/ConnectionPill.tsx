import { useTranslation } from "react-i18next";
import type { StreamConnection } from "@/hooks/useEventStream";
import { useOnline } from "@/hooks/useOnline";
import { cn } from "@/lib/cn";

export function ConnectionPill({ connection }: { connection: StreamConnection }) {
  const { t } = useTranslation();
  const online = useOnline();
  const kind = !online ? "offline" : connection.status === "open" ? "live" : connection.status === "closed" ? "closed" : "reconnecting";
  const label =
    kind === "offline"
      ? t("chat.status.offline")
      : kind === "live"
        ? t("chat.status.open")
        : kind === "closed"
          ? t("chat.status.closed")
          : connection.attempt > 0
            ? t("chat.status.reconnectingN", { n: connection.attempt })
            : t("chat.status.connecting");
  const tone = {
    live: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
    reconnecting: "border-ember-500/30 bg-ember-500/10 text-ember-300",
    offline: "border-red-500/30 bg-red-500/10 text-red-300",
    closed: "border-white/10 bg-white/5 text-fog-500",
  }[kind];
  const dot = { live: "bg-emerald-400", reconnecting: "bg-ember-400 animate-pulse-soft", offline: "bg-red-400", closed: "bg-fog-700" }[kind];
  return (
    <span className={cn("inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium", tone)} role="status">
      <span className={cn("size-1.5 rounded-full", dot)} />
      {label}
    </span>
  );
}
