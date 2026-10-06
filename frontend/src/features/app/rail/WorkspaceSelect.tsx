import { Building } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useMe } from "@/hooks/useMe";
import { useUi } from "@/stores/ui";
import { Dropdown } from "@/components/ui/Dropdown";

/** Only rendered when the user belongs to more than one workspace -- with just one, there's
 * nothing to switch between, so omit the control entirely rather than show it disabled. */
export function WorkspaceSelect({ collapsed }: { collapsed: boolean }) {
  const { t } = useTranslation();
  const me = useMe();
  const workspaceId = useUi((s) => s.workspaceId);
  const switchWorkspace = useUi((s) => s.switchWorkspace);
  const workspaces = me.data?.workspaces ?? [];

  if (workspaces.length < 2) return null;

  const names = Object.fromEntries(workspaces.map((w) => [w.id, w.name]));
  const ids = workspaces.map((w) => w.id);
  const current = workspaceId ?? ids[0];

  return (
    <div className="relative" title={t("app.rail.workspace")}>
      <Building className="pointer-events-none absolute left-1.5 top-1/2 size-3.5 -translate-y-1/2 text-fog-500" />
      <Dropdown
        label={t("app.rail.workspace")}
        value={current}
        options={ids}
        onChange={switchWorkspace}
        trigger={collapsed ? names[current]?.slice(0, 2).toUpperCase() : names[current]}
        renderOption={(id) => (collapsed ? names[id]?.slice(0, 2).toUpperCase() : names[id])}
      />
    </div>
  );
}
