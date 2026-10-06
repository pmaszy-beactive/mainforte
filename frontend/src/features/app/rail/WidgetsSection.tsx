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
    // A real, focusable control (not a decorative <div>) even when collapsed: opens the most
    // recent widget directly, same as clicking it in the expanded list, instead of an icon that
    // looked interactive but did nothing (ticket T02798).
    const first = widgets[0];
    return (
      <RailItem
        collapsed={collapsed}
        icon={<LayoutGrid className="size-4" />}
        label={widgets.length > 1 ? t("app.widgets.titleCount", { count: widgets.length }) : t("app.widgets.title")}
        onClick={first ? () => window.open(first.url, "_blank", "noopener,noreferrer") : undefined}
      />
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
