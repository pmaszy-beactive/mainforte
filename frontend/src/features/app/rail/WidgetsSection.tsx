import { LayoutGrid } from "lucide-react";
import { useTranslation } from "react-i18next";
import { RailSection } from "./RailSection";
import { EmptyState } from "@/components/ui/EmptyState";

// Widgets land in P2 (PLAN 1.6). Shell only: list + empty state.
export function WidgetsSection({ collapsed }: { collapsed: boolean }) {
  const { t } = useTranslation();
  const widgets: { id: string; name: string }[] = [];
  if (collapsed) {
    return (
      <div className="grid place-items-center text-fog-700" title={t("app.widgets.title")}>
        <LayoutGrid className="size-4" />
      </div>
    );
  }
  return (
    <RailSection title={t("app.widgets.title")} collapsed={collapsed}>
      {widgets.length === 0 ? (
        <EmptyState icon={<LayoutGrid className="size-5" />} title={t("app.widgets.empty")} hint={t("app.widgets.emptyHint")} />
      ) : null}
    </RailSection>
  );
}
