import { create } from "zustand";
import { persist } from "zustand/middleware";

interface UiState {
  railCollapsed: boolean;
  viewPaneOpen: boolean;
  activityOpen: boolean;
  activeThreadId: string | null; // null = global channel
  workspaceId: string | null;
  /** Composer drafts keyed by `${workspaceId}:${threadId ?? "global"}`. */
  drafts: Record<string, string>;
  setDraft: (key: string, text: string) => void;
  toggleRail: () => void;
  toggleViewPane: () => void;
  toggleActivity: () => void;
  setThread: (id: string | null) => void;
  setWorkspace: (id: string | null) => void;
}

export const useUi = create<UiState>()(
  persist(
    (set) => ({
      railCollapsed: false,
      viewPaneOpen: false,
      activityOpen: false,
      activeThreadId: null,
      workspaceId: null,
      drafts: {},
      setDraft: (key, text) =>
        set((s) => {
          if ((s.drafts[key] ?? "") === text) return s;
          const drafts = { ...s.drafts };
          if (text) drafts[key] = text;
          else delete drafts[key];
          return { drafts };
        }),
      toggleRail: () => set((s) => ({ railCollapsed: !s.railCollapsed })),
      toggleViewPane: () => set((s) => ({ viewPaneOpen: !s.viewPaneOpen })),
      toggleActivity: () => set((s) => ({ activityOpen: !s.activityOpen })),
      setThread: (activeThreadId) => set({ activeThreadId }),
      setWorkspace: (workspaceId) => set({ workspaceId }),
    }),
    { name: "mainforte.ui", partialize: (s) => ({ railCollapsed: s.railCollapsed, workspaceId: s.workspaceId, drafts: s.drafts }) },
  ),
);
