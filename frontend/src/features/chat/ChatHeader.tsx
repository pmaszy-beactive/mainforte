import { PanelRight, Plus } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { StreamConnection } from "@/hooks/useEventStream";
import { useUi } from "@/stores/ui";
import { Button } from "@/components/ui/Button";
import { HistoryDropdown } from "./HistoryDropdown";
import { ConnectionPill } from "./ConnectionPill";

export function ChatHeader({ connection }: { connection: StreamConnection }) {
  const { t } = useTranslation();
  const threadId = useUi((s) => s.activeThreadId);
  const setThread = useUi((s) => s.setThread);
  const viewPaneOpen = useUi((s) => s.viewPaneOpen);
  const toggleViewPane = useUi((s) => s.toggleViewPane);

  return (
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-white/5 px-4">
      <div className="flex min-w-0 items-center gap-3">
        <h1 className="truncate text-sm font-semibold">{threadId === null ? t("app.staff.global") : threadId}</h1>
        <ConnectionPill connection={connection} />
      </div>
      <div className="flex items-center gap-1.5">
        <Button size="sm" variant={viewPaneOpen ? "outline" : "ghost"} onClick={toggleViewPane} aria-pressed={viewPaneOpen}>
          <PanelRight className="size-4" /> <span className="hidden sm:inline">{t("chat.viewPane")}</span>
        </Button>
        <HistoryDropdown />
        <Button size="sm" onClick={() => setThread(null)}>
          <Plus className="size-4" /> {t("chat.newChat")}
        </Button>
      </div>
    </header>
  );
}
