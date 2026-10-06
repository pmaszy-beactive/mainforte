import { Building } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useMe } from "@/hooks/useMe";
import { useUi } from "@/stores/ui";

/** Only rendered when the user belongs to more than one workspace -- with just one, there's
 * nothing to switch between, so omit the control entirely rather than show it disabled. */
export function WorkspaceSelect({ collapsed }: { collapsed: boolean }) {
  const { t } = useTranslation();
  const me = useMe();
  const workspaceId = useUi((s) => s.workspaceId);
  const switchWorkspace = useUi((s) => s.switchWorkspace);
  const workspaces = me.data?.workspaces ?? [];

  if (workspaces.length < 2) return null;

  return (
    <div className={collapsed ? "" : "relative"} title={t("app.rail.workspace")}>
      <Building className="pointer-events-none absolute left-1.5 top-1/2 size-3.5 -translate-y-1/2 text-fog-500" />
      <select
        aria-label={t("app.rail.workspace")}
        value={workspaceId ?? ""}
        onChange={(e) => switchWorkspace(e.target.value)}
        className="appearance-none rounded-lg bg-transparent py-1.5 pl-7 pr-1.5 text-xs text-fog-300 hover:bg-white/5 hover:text-fog-100 ring-focus"
      >
        {workspaces.map((w) => (
          <option key={w.id} value={w.id} className="bg-ink-950 text-fog-100">
            {collapsed ? w.name.slice(0, 2).toUpperCase() : w.name}
          </option>
        ))}
      </select>
    </div>
  );
}
