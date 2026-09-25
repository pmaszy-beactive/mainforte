import { api, isRetryable } from "./api";
import { getToken } from "@/stores/auth";
import { useOutbox, type OutboxMessage } from "@/stores/outbox";
import { useAttachments } from "@/stores/attachments";

/**
 * The single outbound sender loop. Walks the persisted outbox in order (per workspace),
 * POSTs each queued message once its uploads are done, and retries with backoff
 * (1s → 30s) until the tab dies or the server answers with a non-retryable 4xx.
 */
let started = false;
let running = false;
let timer: ReturnType<typeof setTimeout> | null = null;
let backoff = 1000;

export function startSender() {
  if (started) return;
  started = true;
  useOutbox.getState().normalize();
  window.addEventListener("online", kickSender);
  kickSender();
}

/** Reset backoff and run now (online event, socket reconnect, new message, upload done). */
export function kickSender() {
  backoff = 1000;
  if (timer) {
    clearTimeout(timer);
    timer = null;
  }
  void loop();
}

function nextReady(): OutboxMessage | null {
  const { messages, update } = useOutbox.getState();
  const uploads = useAttachments.getState().items;
  const blocked = new Set<string>();
  for (const m of messages) {
    if (m.status === "sent" || m.status === "failed" || blocked.has(m.workspace_id)) continue;
    const missing = m.attachments.filter((a) => !a.id);
    if (missing.length === 0) return m;
    let failed: string | null = null;
    let pending = false;
    for (const a of missing) {
      const u = uploads[a.localId];
      if (!u) failed = "attachmentLost";
      else if (u.status === "failed") failed = u.error ?? "uploadFailed";
      else pending = true;
    }
    if (failed) {
      update(m.client_msg_id, { status: "failed", error: failed });
      continue; // failed messages do not block the queue
    }
    if (pending) blocked.add(m.workspace_id);
  }
  return null;
}

function schedule() {
  if (timer) return;
  timer = setTimeout(() => {
    timer = null;
    void loop();
  }, backoff);
  backoff = Math.min(backoff * 2, 30_000);
}

async function loop() {
  if (running) return;
  running = true;
  try {
    for (;;) {
      if (!getToken()) return;
      const m = nextReady();
      if (!m) return;
      const { update } = useOutbox.getState();
      update(m.client_msg_id, { status: "sending" });
      try {
        const r = await api.workspaces.chat(m.workspace_id, {
          client_msg_id: m.client_msg_id,
          thread_id: m.thread_id,
          text: m.text,
          attachments: m.attachments.map((a) => ({ id: a.id! })),
        });
        update(m.client_msg_id, { status: "sent", event_id: r.event_id, error: null });
        backoff = 1000;
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        if (!isRetryable(e)) {
          update(m.client_msg_id, { status: "failed", error: msg });
          continue;
        }
        update(m.client_msg_id, { status: "queued", attempts: m.attempts + 1, error: msg });
        schedule();
        return;
      }
    }
  } finally {
    running = false;
  }
}
