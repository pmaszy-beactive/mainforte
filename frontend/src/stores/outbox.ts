import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { UploadResult } from "@/lib/types";
import { useAttachments } from "./attachments";

export type OutboxStatus = "queued" | "sending" | "sent" | "failed";

export interface OutboxAttachment {
  localId: string;
  name: string;
  size: number;
  content_type: string;
  /** Filled in once the upload finished. */
  id?: string;
  key?: string;
  url?: string;
}

export interface OutboxMessage {
  client_msg_id: string;
  workspace_id: string;
  thread_id: string | null;
  text: string;
  attachments: OutboxAttachment[];
  status: OutboxStatus;
  attempts: number;
  error: string | null;
  event_id: string | null;
  created_at: string;
}

interface OutboxState {
  messages: OutboxMessage[];
  enqueue: (m: Omit<OutboxMessage, "status" | "attempts" | "error" | "event_id" | "created_at">) => void;
  update: (clientMsgId: string, patch: Partial<OutboxMessage>) => void;
  remove: (clientMsgId: string) => void;
  retry: (clientMsgId: string) => void;
  attachUploaded: (localId: string, r: UploadResult) => void;
  /** Called once at startup: nothing can still be "sending" after a reload; drop stale sent rows. */
  normalize: () => void;
}

const SENT_TTL_MS = 60 * 60 * 1000;

export const useOutbox = create<OutboxState>()(
  persist(
    (set) => ({
      messages: [],
      enqueue: (m) =>
        set((s) => ({
          messages: [...s.messages, { ...m, status: "queued", attempts: 0, error: null, event_id: null, created_at: new Date().toISOString() }],
        })),
      update: (id, patch) => set((s) => ({ messages: s.messages.map((m) => (m.client_msg_id === id ? { ...m, ...patch } : m)) })),
      remove: (id) => set((s) => (s.messages.some((m) => m.client_msg_id === id) ? { messages: s.messages.filter((m) => m.client_msg_id !== id) } : s)),
      retry: (id) =>
        set((s) => {
          // Flipping status back to "queued" alone only works for a message that failed with no
          // attachments, or whose attachments already finished uploading -- sender.ts's nextReady()
          // re-checks every attachment's upload status on each pass, so a message that failed
          // because an attachment upload itself failed (status "failed" in useAttachments, not
          // merely missing) was immediately re-failed with the same error the instant the sender
          // looked at it again: same text, same buttons, nothing visibly happens (ticket T02797).
          // Retrying the message must also retry any attachment that's actually retryable.
          const msg = s.messages.find((m) => m.client_msg_id === id);
          if (msg) {
            const attachRetry = useAttachments.getState().retry;
            for (const a of msg.attachments) if (!a.id) attachRetry(a.localId);
          }
          return { messages: s.messages.map((m) => (m.client_msg_id === id ? { ...m, status: "queued", error: null } : m)) };
        }),
      attachUploaded: (localId, r) =>
        set((s) => ({
          messages: s.messages.map((m) =>
            m.attachments.some((a) => a.localId === localId)
              ? { ...m, attachments: m.attachments.map((a) => (a.localId === localId ? { ...a, id: r.id, key: r.key, url: r.url } : a)) }
              : m,
          ),
        })),
      normalize: () =>
        set((s) => {
          const cutoff = Date.now() - SENT_TTL_MS;
          return {
            messages: s.messages
              .filter((m) => !(m.status === "sent" && new Date(m.created_at).getTime() < cutoff))
              .map((m) => (m.status === "sending" ? { ...m, status: "queued" } : m)),
          };
        }),
    }),
    { name: "mainforte.outbox" },
  ),
);
