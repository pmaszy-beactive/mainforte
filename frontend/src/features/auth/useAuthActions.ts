import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router";
import type { AuthResponse } from "@/lib/types";
import { useAuth } from "@/stores/auth";

/** Shared "got a session, go to /app" handling for every auth page. */
export function useLoginMutation<V>(fn: (v: V) => Promise<AuthResponse>) {
  const setSession = useAuth((s) => s.setSession);
  const qc = useQueryClient();
  const nav = useNavigate();
  return useMutation({
    mutationFn: fn,
    onSuccess: ({ token, user }) => {
      setSession(token, user);
      qc.clear();
      nav("/app", { replace: true });
    },
  });
}

export function errorMessage(e: unknown, fallback = "Something went wrong"): string {
  return e instanceof Error ? e.message : fallback;
}
