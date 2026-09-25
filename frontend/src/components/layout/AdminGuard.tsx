import { Navigate, Outlet } from "react-router";
import { useMe } from "@/hooks/useMe";
import { FullPageSpinner } from "@/components/ui/Spinner";

export function AdminGuard() {
  const me = useMe();
  if (me.isLoading) return <FullPageSpinner />;
  if (me.data?.user.role !== "superuser") return <Navigate to="/app" replace />;
  return <Outlet />;
}
