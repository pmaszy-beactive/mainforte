import type { WsEvent } from "@/lib/types";

const PREFIX_LABELS: Record<string, string> = {
  "tool.started": "chat.thinking.tool",
  "tool.progress": "chat.thinking.tool",
  "tool.approval.requested": "chat.thinking.tool",
  "task.stage.started": "chat.thinking.stage",
  "agent.work.queued": "chat.thinking.working",
  "agent.work.started": "chat.thinking.working",
  "agent.work.progress": "chat.thinking.working",
  "browser.session.opened": "chat.thinking.browsing",
  "browser.navigation": "chat.thinking.browsing",
  "browser.handoff.requested": "chat.thinking.browsing",
  "build.started": "chat.thinking.building",
  "build.log": "chat.thinking.building",
  "governor.claim.extracted": "chat.thinking.checking",
  "governor.claim.checked": "chat.thinking.checking",
  "site.file.changed": "chat.thinking.editing",
};

/** Short, present-tense "vibe" label for a live activity event. Approximate by design. */
export function describeActivity(t: (key: string) => string, ev: WsEvent): string {
  return t(PREFIX_LABELS[ev.type] ?? "chat.thinking.working");
}
