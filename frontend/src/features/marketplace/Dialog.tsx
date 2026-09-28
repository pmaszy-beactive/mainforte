import type { ReactNode } from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/cn";

/** Minimal modal — no Dialog component exists in the shared UI kit yet, so this is feature-local
 * to marketplace (buy / report dialogs) rather than a premature promotion to components/ui/. */
export function Dialog({ open, onClose, title, children, className }: { open: boolean; onClose: () => void; title: string; children: ReactNode; className?: string }) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-ink-950/70 backdrop-blur-sm" onClick={onClose} />
      <div className={cn("glass relative w-full max-w-md rounded-2xl p-5", className)}>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-fog-100">{title}</h2>
          <button onClick={onClose} className="rounded-lg p-1 text-fog-500 hover:bg-white/5 hover:text-fog-100 ring-focus" aria-label="Close">
            <X className="size-4" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
