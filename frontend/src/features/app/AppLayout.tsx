import { Suspense, useEffect } from "react";
import { Outlet } from "react-router";
import { useMe } from "@/hooks/useMe";
import { useLocaleSync } from "@/hooks/useLocaleSync";
import { useUi } from "@/stores/ui";
import { Rail } from "./Rail";
import { FullPageSpinner } from "@/components/ui/Spinner";

/** Three-column dashboard: rail | center | (right, none yet). */
export default function AppLayout() {
  const me = useMe();
  useLocaleSync(me.data);

  const workspaceId = useUi((s) => s.workspaceId);
  const setWorkspace = useUi((s) => s.setWorkspace);
  const workspaces = me.data?.workspaces ?? [];

  // Pick a workspace: keep the stored one if it still exists, else the first.
  useEffect(() => {
    if (!me.data) return;
    const ok = workspaces.some((w) => w.id === workspaceId);
    if (!ok) setWorkspace(workspaces[0]?.id ?? null);
  }, [me.data, workspaces, workspaceId, setWorkspace]);

  return (
    <div className="flex min-h-0 flex-1 overflow-hidden">
      <Rail />
      <main className="relative flex min-w-0 flex-1 flex-col">
        <Suspense fallback={<FullPageSpinner />}>
          <Outlet />
        </Suspense>
      </main>
    </div>
  );
}
