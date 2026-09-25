import { FileText, RotateCw, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useAttachments } from "@/stores/attachments";
import { useFormat } from "@/hooks/useFormat";
import { cn } from "@/lib/cn";

/** Pending uploads shown above the composer input, with progress and remove/retry. */
export function AttachmentTray({ localIds, onRemove }: { localIds: string[]; onRemove: (localId: string) => void }) {
  const { t } = useTranslation();
  const f = useFormat();
  const items = useAttachments((s) => s.items);
  const remove = useAttachments((s) => s.remove);
  const retry = useAttachments((s) => s.retry);
  const list = localIds.map((id) => items[id]).filter(Boolean);
  if (list.length === 0) return null;

  return (
    <ul className="mb-2 flex flex-wrap gap-2 px-1">
      {list.map((a) => {
        const failed = a.status === "failed";
        const tooLarge = a.error === "tooLarge";
        return (
          <li key={a.localId} className={cn("relative flex items-center gap-2 rounded-xl border bg-ink-950/60 p-1.5 pr-8 text-xs", failed ? "border-red-500/40" : "border-white/10")}>
            {a.objectUrl ? (
              <img src={a.objectUrl} alt={a.name} className="size-10 rounded-lg object-cover" />
            ) : (
              <span className="grid size-10 place-items-center rounded-lg bg-white/5 text-fog-500">
                <FileText className="size-4" />
              </span>
            )}
            <div className="min-w-0 max-w-40">
              <div className="truncate font-medium text-fog-100">{a.name}</div>
              <div className={cn("truncate", failed ? "text-red-300" : "text-fog-700")}>
                {failed
                  ? tooLarge
                    ? t("chat.tooLarge")
                    : t("chat.uploadFailed")
                  : a.status === "done"
                    ? f.bytes(a.size)
                    : t("chat.uploading", { pct: Math.round(a.progress * 100) })}
              </div>
              {a.status === "uploading" && (
                <div className="mt-1 h-1 overflow-hidden rounded-full bg-white/10">
                  <div className="h-full bg-ember-500 transition-[width]" style={{ width: `${Math.round(a.progress * 100)}%` }} />
                </div>
              )}
            </div>
            {failed && !tooLarge && (
              <button onClick={() => retry(a.localId)} className="rounded-md p-1 text-fog-500 hover:text-fog-100" aria-label={t("chat.uploadRetry")} title={t("chat.uploadRetry")}>
                <RotateCw className="size-3.5" />
              </button>
            )}
            <button
              onClick={() => {
                remove(a.localId);
                onRemove(a.localId);
              }}
              className="absolute right-1.5 top-1.5 rounded-md p-0.5 text-fog-500 hover:bg-white/10 hover:text-fog-100"
              aria-label={t("chat.removeAttachment")}
              title={t("chat.removeAttachment")}
            >
              <X className="size-3.5" />
            </button>
          </li>
        );
      })}
    </ul>
  );
}
