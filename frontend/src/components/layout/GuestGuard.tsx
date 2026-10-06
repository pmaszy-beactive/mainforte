import { Navigate, Outlet } from "react-router";
import { useAuth } from "@/stores/auth";

/**
 * Login/signup replace "/login" with "/app" on success (useAuthActions), so back-navigating from
 * "/app" lands back on "/login" -- the token is still valid, but the form makes it look like the
 * session was lost (T02803). Redirect away immediately whenever a token is already present.
 */
export function GuestGuard() {
  const token = useAuth((s) => s.token);
  if (token) return <Navigate to="/app" replace />;
  return <Outlet />;
}
