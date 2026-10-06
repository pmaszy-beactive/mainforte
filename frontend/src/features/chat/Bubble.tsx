import { useState } from "react";
import { AlertCircle, Check, ChevronDown, Loader2, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import ReactMarkdown from "react-markdown";
import type { Bubble as BubbleT } from "@/hooks/useEventStream";
import { useFormat } from "@/hooks/useFormat";
import { useOutbox, type OutboxStatus } from "@/stores/outbox";
import { kickSender } from "@/lib/sender";
import { cn } from "@/lib/cn";
import { BubbleAttachments } from "./BubbleAttachments";
import { ActivityList } from "./ActivityList";
import { describeActivity } from "./activityLabels";

export function Bubble({ bubble }: { bubble: BubbleT }) {
  const { t } = useTranslation();
  const f = useFormat();
  const mine = bubble.actorType === "user";
  const name = mine ? null : bubble.actorId;
  const local = bubble.local;
  const [stepsOpen, setStepsOpen] = useState(false);

  const thinking = !mine && bubble.streaming && !bubble.text;
  const latestActivity = bubble.activity[bubble.activity.length - 1];

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

        {thinking && (
          <button
            onClick={() => setStepsOpen((v) => !v)}
            className="flex items-center gap-2 text-fog-300 ring-focus rounded-md"
            aria-expanded={stepsOpen}
          >
            <span className="size-2 animate-pulse-soft rounded-full bg-ember-400" />
            <span>{t("chat.thinking.working")}</span>
            {latestActivity && <span className="text-fog-500">· {describeActivity(t, latestActivity)}</span>}
            {bubble.activity.length > 0 && <ChevronDown className={cn("size-3.5 transition", stepsOpen && "rotate-180")} />}
          </button>
        )}
        {thinking && stepsOpen && bubble.activity.length > 0 && <ActivityList events={bubble.activity} />}

        {bubble.text && (
          <div className={cn("prose-chat whitespace-pre-wrap break-words", mine && "prose-chat-mine")}>
            <ReactMarkdown>{bubble.text}</ReactMarkdown>
            {bubble.streaming && <span className="ml-0.5 inline-block h-3.5 w-1.5 animate-pulse-soft rounded-sm bg-ember-400 align-middle" />}
          </div>
        )}
        <BubbleAttachments attachments={bubble.attachments} mine={mine} />
        <div className={cn("mt-1 flex items-center gap-2 text-[10px]", mine ? "text-ink-900/70" : "text-fog-700")}>
          <span>{f.time(bubble.ts)}</span>
          {bubble.canceled && <span className="text-red-300">{t("chat.canceled")}</span>}
          {local && <LocalStatus clientMsgId={bubble.clientMsgId!} status={local.status} error={local.error} />}
          {!bubble.streaming && bubble.activity.length > 0 && (
            <button onClick={() => setStepsOpen((v) => !v)} className="ml-auto flex items-center gap-1 ring-focus rounded-md" aria-expanded={stepsOpen}>
              <span>{t("chat.steps", { count: bubble.activity.length })}</span>
              <ChevronDown className={cn("size-3 transition", stepsOpen && "rotate-180")} />
            </button>
          )}
        </div>
        {!bubble.streaming && stepsOpen && bubble.activity.length > 0 && <ActivityList events={bubble.activity} />}
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
      <span className="inline-flex items-center gap-1.5 text-red-300">
        <AlertCircle className="size-3" />
        <span title={reason ?? undefined}>{t("chat.failed")}</span>
        <button
          className="font-semibold underline underline-offset-2 ring-focus rounded-sm hover:text-red-100"
          onClick={() => {
            retry(clientMsgId);
            kickSender();
          }}
        >
          {t("chat.retry")}
        </button>
        <button
          className="inline-flex items-center gap-0.5 underline underline-offset-2 ring-focus rounded-sm hover:text-red-100"
          onClick={() => remove(clientMsgId)}
        >
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
