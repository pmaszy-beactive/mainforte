import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { User } from "@/lib/types";

interface AuthState {
  token: string | null;
  user: User | null;
  setSession: (token: string, user?: User | null) => void;
  setUser: (user: User | null) => void;
  clear: () => void;
}

export const useAuth = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      user: null,
      setSession: (token, user) => set((s) => ({ token, user: user === undefined ? s.user : user })),
      setUser: (user) => set({ user }),
      clear: () => set({ token: null, user: null }),
    }),
    { name: "mainforte.auth" },
  ),
);

/** Non-hook access for the API client / socket. */
export const getToken = () => useAuth.getState().token;
