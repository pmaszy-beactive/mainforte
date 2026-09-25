import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/stores/auth";

export const ME_KEY = ["me"] as const;

/** Current session. Keeps the auth store's cached user in sync. */
export function useMe() {
  const token = useAuth((s) => s.token);
  const setUser = useAuth((s) => s.setUser);
  const q = useQuery({
    queryKey: ME_KEY,
    queryFn: api.me,
    enabled: !!token,
    staleTime: 60_000,
    retry: false,
  });
  useEffect(() => {
    if (q.data) setUser(q.data.user);
  }, [q.data, setUser]);
  return q;
}
