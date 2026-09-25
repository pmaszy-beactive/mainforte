import { AlertCircle, Check, Loader2, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { Bubble as BubbleT } from "@/hooks/useEventStream";
import { useFormat } from "@/hooks/useFormat";
import { useOutbox, type OutboxStatus } from "@/stores/outbox";
import { kickSender } from "@/lib/sender";
import { cn } from "@/lib/cn";
import { BubbleAttachments } from "./BubbleAttachments";

export function Bubble({ bubble }: { bubble: BubbleT }) {
  const { t } = useTranslation();
  const f = useFormat();
  const mine = bubble.actorType === "user";
  const name = mine ? null : bubble.actorId;
  const local = bubble.local;

  return (
    <div className={cn("flex items-end gap-2.5 animate-fade-up", mine ? "justify-end" : "justify-start")}>
      {!mine && (
        <span className="grid size-8 shrink-0 place-items-center rounded-full bg-gradient-to-br from-ink-600 to-ink-800 text-xs font-semibold text-ember-300 ring-1 ring-white/10">
          {(name ?? "?").slice(0, 1).toUpperCase()}
        </span>
      )}
      <div
        className={cn(
          "max-w-[78%] rounded-bubble px-4 py-2.5 text-sm leading-relaxed transition-opacity",
          mine ? "rounded-br-md bg-ember-500 text-ink-950 shadow-glow" : "rounded-bl-md bg-ink-700/80 text-fog-100 ring-1 ring-white/5",
          local && local.status !== "sent" && "opacity-80",
          bubble.canceled && "ring-1 ring-red-500/30",
        )}
      >
        {!mine && <div className="mb-0.5 text-[11px] font-medium text-fog-500">{name}</div>}
        {bubble.text && (
          <p className="whitespace-pre-wrap break-words">
            {bubble.text}
            {bubble.streaming && <span className="ml-0.5 inline-block h-3.5 w-1.5 animate-pulse-soft rounded-sm bg-ember-400 align-middle" />}
          </p>
        )}
        <BubbleAttachments attachments={bubble.attachments} mine={mine} />
        <div className={cn("mt-1 flex items-center gap-2 text-[10px]", mine ? "text-ink-900/70" : "text-fog-700")}>
          <span>{f.time(bubble.ts)}</span>
          {bubble.canceled && <span className="text-red-300">{t("chat.canceled")}</span>}
          {local && <LocalStatus clientMsgId={bubble.clientMsgId!} status={local.status} error={local.error} />}
        </div>
      </div>
    </div>
  );
}

function LocalStatus({ clientMsgId, status, error }: { clientMsgId: string; status: OutboxStatus; error: string | null }) {
  const { t } = useTranslation();
  const retry = useOutbox((s) => s.retry);
  const remove = useOutbox((s) => s.remove);
  if (status === "sent") return <Check className="size-3" aria-label={t("chat.sent")} />;
  if (status === "failed") {
    const reason = error === "attachmentLost" ? t("chat.attachmentLost") : error === "uploadFailed" ? t("chat.uploadFailed") : error;
    return (
      <span className="inline-flex items-center gap-1.5 text-red-900">
        <AlertCircle className="size-3" />
        <span title={reason ?? undefined}>{t("chat.failed")}</span>
        <button
          className="font-semibold underline underline-offset-2"
          onClick={() => {
            retry(clientMsgId);
            kickSender();
          }}
        >
          {t("chat.retry")}
        </button>
        <button className="inline-flex items-center gap-0.5 underline underline-offset-2" onClick={() => remove(clientMsgId)}>
          <Trash2 className="size-3" /> {t("chat.discard")}
        </button>
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1">
      <Loader2 className="size-3 animate-spin" /> {t("chat.sending")}
    </span>
  );
}
