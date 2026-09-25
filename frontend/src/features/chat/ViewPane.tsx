import { MonitorPlay } from "lucide-react";
import { useTranslation } from "react-i18next";

/** Placeholder for the live browser / results pane (not in v1, see PLAN decision 6). */
export function ViewPane() {
  const { t } = useTranslation();
  return (
    <aside className="hidden w-[45%] flex-col border-l border-white/5 bg-ink-950/30 lg:flex">
      <div className="flex flex-1 flex-col items-center justify-center gap-3 p-8 text-center text-fog-700">
        <div className="grid size-14 place-items-center rounded-2xl border border-dashed border-white/10">
          <MonitorPlay className="size-6" />
        </div>
        <p className="text-sm font-medium text-fog-500">{t("chat.viewPaneTitle")}</p>
        <p className="max-w-xs text-xs">{t("chat.viewPaneHint")}</p>
      </div>
    </aside>
  );
}
