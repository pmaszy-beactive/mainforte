import { Navigate, Outlet, useLocation } from "react-router";
import { useAuth } from "@/stores/auth";
import { useMe } from "@/hooks/useMe";
import { FullPageSpinner } from "@/components/ui/Spinner";

export function AuthGuard() {
  const token = useAuth((s) => s.token);
  const loc = useLocation();
  const me = useMe();
  if (!token) return <Navigate to="/login" replace state={{ from: loc.pathname }} />;
  if (me.isLoading) return <FullPageSpinner />;
  if (me.isError) return <Navigate to="/login" replace />;
  return <Outlet />;
}
