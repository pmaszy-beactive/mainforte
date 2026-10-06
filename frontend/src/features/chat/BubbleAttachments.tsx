import { FileText } from "lucide-react";
import type { Attachment } from "@/lib/types";
import { authedUrl } from "@/lib/api";
import { useAttachments } from "@/stores/attachments";
import { useFormat } from "@/hooks/useFormat";
import { useLightbox } from "./Lightbox";
import { cn } from "@/lib/cn";

export function BubbleAttachments({ attachments, mine }: { attachments: Attachment[]; mine: boolean }) {
  const f = useFormat();
  const pending = useAttachments((s) => s.items);
  const open = useLightbox((s) => s.open);
  if (!attachments.length) return null;

  const resolve = (a: Attachment): string | null => {
    const local = a.localId ? pending[a.localId] : undefined;
    if (local?.objectUrl) return local.objectUrl;
    return a.url ? authedUrl(a.url) : null;
  };

  return (
    <div className={cn("flex flex-wrap gap-2", "mt-2")}>
      {attachments.map((a) => {
        const src = resolve(a);
        const isImage = a.content_type?.startsWith("image/");
        const isVideo = a.content_type?.startsWith("video/");
        if (isImage && src) {
          return (
            <button key={a.localId ?? a.id} type="button" onClick={() => open(src, a.name)} className="overflow-hidden rounded-xl ring-1 ring-white/10 ring-focus">
              <img src={src} alt={a.name} loading="lazy" className="max-h-64 max-w-full object-cover" />
            </button>
          );
        }
        if (isVideo && src) {
          return (
            <video key={a.localId ?? a.id} src={src} controls preload="metadata" className="max-h-64 max-w-full rounded-xl ring-1 ring-white/10" />
          );
        }
        const chip = (
          <>
            <FileText className="size-4 shrink-0" />
            <span className="min-w-0">
              <span className="block truncate text-xs font-medium">{a.name}</span>
              <span className={cn("block text-[10px]", mine ? "text-ink-900/70" : "text-fog-500")}>{f.bytes(a.size)}</span>
            </span>
          </>
        );
        const cls = cn("flex max-w-56 items-center gap-2 rounded-lg px-2.5 py-1.5", mine ? "bg-black/10" : "bg-white/5");
        return src ? (
          <a key={a.localId ?? a.id} href={src} target="_blank" rel="noreferrer" className={cls}>
            {chip}
          </a>
        ) : (
          <span key={a.localId ?? a.id} className={cls}>
            {chip}
          </span>
        );
      })}
    </div>
  );
}
