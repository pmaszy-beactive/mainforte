import { LayoutGrid } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { RailItem, RailSection } from "./RailSection";
import { EmptyState } from "@/components/ui/EmptyState";
import { api } from "@/lib/api";
import { useUi } from "@/stores/ui";

export function WidgetsSection({ collapsed }: { collapsed: boolean }) {
  const { t } = useTranslation();
  const wsId = useUi((s) => s.workspaceId);
  const { data: widgets = [] } = useQuery({
    queryKey: ["widgets", wsId],
    queryFn: () => api.widgets.list(wsId!),
    enabled: !!wsId,
  });

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
      ) : (
        <div className="space-y-0.5">
          {widgets.map((w) => (
            <RailItem
              key={w.id}
              collapsed={collapsed}
              icon={<LayoutGrid className="size-4" />}
              label={w.title}
              onClick={() => window.open(w.url, "_blank", "noopener,noreferrer")}
            />
          ))}
        </div>
      )}
    </RailSection>
  );
}
