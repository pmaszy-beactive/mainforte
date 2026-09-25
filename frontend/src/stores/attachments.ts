import { create } from "zustand";
import { ApiError, isRetryable } from "@/lib/api";
import { MAX_UPLOAD_BYTES, uploadXhr } from "@/lib/upload";
import { newId } from "@/lib/ids";
import type { UploadResult } from "@/lib/types";
import { useOutbox } from "./outbox";
import { kickSender } from "@/lib/sender";

export type UploadStatus = "uploading" | "done" | "failed";

export interface PendingAttachment {
  localId: string;
  workspaceId: string;
  name: string;
  size: number;
  content_type: string;
  objectUrl: string | null;
  progress: number; // 0..1
  status: UploadStatus;
  attempts: number;
  /** i18n key or raw server message */
  error: string | null;
  result: UploadResult | null;
}

interface AttachmentsState {
  items: Record<string, PendingAttachment>;
  add: (workspaceId: string, file: File) => string;
  remove: (localId: string) => void;
  retry: (localId: string) => void;
}

/** Files and in-flight XHRs live outside the store (not serializable). */
const ctl = new Map<string, { file: File; xhr: XMLHttpRequest | null; timer: ReturnType<typeof setTimeout> | null; aborted: boolean }>();

const sleep = (ms: number, localId: string) =>
  new Promise<void>((r) => {
    const c = ctl.get(localId);
    const t = setTimeout(r, ms);
    if (c) c.timer = t;
  });

export const useAttachments = create<AttachmentsState>()((set, get) => {
  const patch = (localId: string, p: Partial<PendingAttachment>) =>
    set((s) => (s.items[localId] ? { items: { ...s.items, [localId]: { ...s.items[localId], ...p } } } : s));

  async function run(localId: string) {
    const c = ctl.get(localId);
    if (!c) return;
    let backoff = 1000;
    for (;;) {
      const item = get().items[localId];
      if (!item || c.aborted) return;
      patch(localId, { status: "uploading", progress: 0, attempts: item.attempts + 1 });
      try {
        const result = await uploadXhr(item.workspaceId, c.file, (p) => patch(localId, { progress: p }), (x) => (c.xhr = x));
        patch(localId, { status: "done", progress: 1, result, error: null });
        useOutbox.getState().attachUploaded(localId, result);
        kickSender();
        return;
      } catch (e) {
        if (c.aborted) return;
        const msg = e instanceof Error ? e.message : String(e);
        if (!isRetryable(e)) {
          patch(localId, { status: "failed", error: msg });
          kickSender(); // lets the sender fail messages that depend on it
          return;
        }
        patch(localId, { error: msg });
        await sleep(backoff, localId);
        backoff = Math.min(backoff * 2, 30_000);
      }
    }
  }

  return {
    items: {},
    add: (workspaceId, file) => {
      const localId = newId();
      const objectUrl = file.type.startsWith("image/") ? URL.createObjectURL(file) : null;
      const item: PendingAttachment = {
        localId,
        workspaceId,
        name: file.name,
        size: file.size,
        content_type: file.type || "application/octet-stream",
        objectUrl,
        progress: 0,
        status: "uploading",
        attempts: 0,
        error: null,
        result: null,
      };
      set((s) => ({ items: { ...s.items, [localId]: item } }));
      ctl.set(localId, { file, xhr: null, timer: null, aborted: false });
      if (file.size > MAX_UPLOAD_BYTES) {
        patch(localId, { status: "failed", error: new ApiError(413, "tooLarge").message });
      } else {
        void run(localId);
      }
      return localId;
    },
    remove: (localId) => {
      const c = ctl.get(localId);
      if (c) {
        c.aborted = true;
        c.xhr?.abort();
        if (c.timer) clearTimeout(c.timer);
        ctl.delete(localId);
      }
      const item = get().items[localId];
      if (item?.objectUrl) URL.revokeObjectURL(item.objectUrl);
      set((s) => {
        const items = { ...s.items };
        delete items[localId];
        return { items };
      });
    },
    retry: (localId) => {
      const c = ctl.get(localId);
      const item = get().items[localId];
      if (!c || !item || item.status !== "failed") return;
      if (item.size > MAX_UPLOAD_BYTES) return;
      c.aborted = false;
      patch(localId, { error: null });
      void run(localId);
    },
  };
});
