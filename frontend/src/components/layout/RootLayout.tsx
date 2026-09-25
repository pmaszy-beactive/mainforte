import { Suspense } from "react";
import { Outlet } from "react-router";
import { ImpersonationBanner } from "./ImpersonationBanner";
import { FullPageSpinner } from "@/components/ui/Spinner";
import { useAuth } from "@/stores/auth";

export function RootLayout() {
  const token = useAuth((s) => s.token);
  return (
    <div className="flex h-dvh flex-col overflow-y-auto">
      {token && <ImpersonationBanner />}
      <Suspense fallback={<FullPageSpinner />}>
        <Outlet />
      </Suspense>
    </div>
  );
}
