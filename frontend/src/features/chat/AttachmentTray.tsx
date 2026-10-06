import { useEffect, useState } from "react";
import { FileText, RotateCw, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useAttachments } from "@/stores/attachments";
import { useFormat } from "@/hooks/useFormat";
import { cn } from "@/lib/cn";

/** An "uploading" attachment stuck past this long gets a visible unstick hint (ticket T02791) —
 * the XHR itself still has its own 180s timeout (lib/upload.ts), this is just earlier, user-facing
 * reassurance that something can be done rather than waiting the full timeout out blind. */
const SLOW_UPLOAD_MS = 20_000;

/** Pending uploads shown above the composer input, with progress and remove/retry. */
export function AttachmentTray({ localIds, onRemove }: { localIds: string[]; onRemove: (localId: string) => void }) {
  const { t } = useTranslation();
  const f = useFormat();
  const items = useAttachments((s) => s.items);
  const remove = useAttachments((s) => s.remove);
  const retry = useAttachments((s) => s.retry);
  const list = localIds.map((id) => items[id]).filter(Boolean);
  const anyUploading = list.some((a) => a.status === "uploading");

  // Ticks ~1/s while something is uploading, purely to re-evaluate each item's elapsed time
  // against SLOW_UPLOAD_MS below -- no timer runs once nothing is mid-upload.
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!anyUploading) return;
    const id = setInterval(() => setTick((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, [anyUploading]);

  if (list.length === 0) return null;

  return (
    <ul className="mb-2 flex max-h-40 flex-wrap gap-2 overflow-y-auto px-1">
      {list.map((a) => {
        const failed = a.status === "failed";
        const tooLarge = a.error === "tooLarge";
        const slow = a.status === "uploading" && !!a.uploadStartedAt && Date.now() - a.uploadStartedAt > SLOW_UPLOAD_MS;
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
              <div className={cn("truncate", failed ? "text-red-300" : slow ? "text-amber-300" : "text-fog-700")}>
                {failed
                  ? tooLarge
                    ? t("chat.tooLarge")
                    : t("chat.uploadFailed")
                  : a.status === "done"
                    ? f.bytes(a.size)
                    : slow
                      ? t("chat.uploadSlow")
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
