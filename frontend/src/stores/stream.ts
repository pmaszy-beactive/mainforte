import { create } from "zustand";
import { persist } from "zustand/middleware";

interface StreamState {
  /** Last seen event id per workspace, so a restart resumes with `after=`. */
  lastIds: Record<string, string>;
  setLastId: (workspaceId: string, id: string) => void;
}

export const useStream = create<StreamState>()(
  persist(
    (set) => ({
      lastIds: {},
      setLastId: (workspaceId, id) => set((s) => (s.lastIds[workspaceId] === id ? s : { lastIds: { ...s.lastIds, [workspaceId]: id } })),
    }),
    { name: "mainforte.stream" },
  ),
);
