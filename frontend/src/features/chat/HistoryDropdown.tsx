import { useEffect, useRef, useState } from "react";
import { ChevronDown, History } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/Button";

// Thread history comes with chat.thread.* events (P1). Shell: empty dropdown.
export function HistoryDropdown() {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const threads: { id: string; title: string }[] = [];

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <Button size="sm" variant="ghost" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <History className="size-4" /> <span className="hidden sm:inline">{t("chat.history")}</span> <ChevronDown className="size-3.5" />
      </Button>
      {open && (
        <div className="glass absolute right-0 top-full z-20 mt-1.5 w-64 rounded-xl bg-ink-950/95 p-1.5 animate-fade-up">
          {threads.length === 0 ? (
            <p className="px-2.5 py-3 text-center text-xs text-fog-700">{t("chat.historyEmpty")}</p>
          ) : (
            threads.map((th) => (
              <button key={th.id} className="block w-full truncate rounded-lg px-2.5 py-1.5 text-left text-sm hover:bg-white/5">
                {th.title}
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}
