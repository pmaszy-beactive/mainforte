import { create } from "zustand";
import { persist } from "zustand/middleware";

interface UiState {
  railCollapsed: boolean;
  viewPaneOpen: boolean;
  activeThreadId: string | null; // null = global channel
  workspaceId: string | null;
  /** Composer drafts keyed by `${workspaceId}:${threadId ?? "global"}`. */
  drafts: Record<string, string>;
  setDraft: (key: string, text: string) => void;
  toggleRail: () => void;
  toggleViewPane: () => void;
  setThread: (id: string | null) => void;
  setWorkspace: (id: string | null) => void;
  /** User-initiated workspace switch (the rail's WorkspaceSelect): unlike setWorkspace (also used
   * by AppLayout's auto-pick-a-default effect), this also clears activeThreadId, since a thread
   * id from the previous workspace is meaningless in the new one. */
  switchWorkspace: (id: string) => void;
}

export const useUi = create<UiState>()(
  persist(
    (set) => ({
      railCollapsed: false,
      viewPaneOpen: false,
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
      setThread: (activeThreadId) => set({ activeThreadId }),
      setWorkspace: (workspaceId) => set({ workspaceId }),
      switchWorkspace: (workspaceId) => set({ workspaceId, activeThreadId: null }),
    }),
    { name: "mainforte.ui", partialize: (s) => ({ railCollapsed: s.railCollapsed, workspaceId: s.workspaceId, drafts: s.drafts }) },
  ),
);
