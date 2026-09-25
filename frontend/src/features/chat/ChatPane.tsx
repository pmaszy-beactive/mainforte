import { useMemo } from "react";
import { useMutation } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { api } from "@/lib/api";
import { newId } from "@/lib/ids";
import { kickSender } from "@/lib/sender";
import { useEventStream, type Bubble } from "@/hooks/useEventStream";
import { useUi } from "@/stores/ui";
import { useAuth } from "@/stores/auth";
import { useOutbox } from "@/stores/outbox";
import { useAttachments } from "@/stores/attachments";
import { cn } from "@/lib/cn";
import { ChatHeader } from "./ChatHeader";
import { MessageList } from "./MessageList";
import { Composer } from "./Composer";
import { ActivityStrip } from "./ActivityStrip";
import { ViewPane } from "./ViewPane";
import { Lightbox } from "./Lightbox";

export function ChatPane({ workspaceId }: { workspaceId: string | null }) {
  const { t } = useTranslation();
  const threadId = useUi((s) => s.activeThreadId);
  const viewPaneOpen = useUi((s) => s.viewPaneOpen);
  const user = useAuth((s) => s.user);
  const stream = useEventStream(workspaceId);
  const outbox = useOutbox((s) => s.messages);

  // Optimistic bubbles: outbox rows not yet seen as chat.message.created (dedupe by client_msg_id).
  const bubbles = useMemo<Bubble[]>(() => {
    if (!workspaceId) return stream.bubbles;
    const known = new Set(stream.bubbles.map((b) => b.clientMsgId).filter(Boolean));
    const local = outbox
      .filter((m) => m.workspace_id === workspaceId && !known.has(m.client_msg_id))
      .map<Bubble>((m) => ({
        id: `local:${m.client_msg_id}`,
        threadId: m.thread_id,
        actorType: "user",
        actorId: user?.id ?? "me",
        userId: user?.id ?? null,
        text: m.text,
        ts: m.created_at,
        streaming: false,
        canceled: false,
        clientMsgId: m.client_msg_id,
        correlationId: null,
        attachments: m.attachments.map((a) => ({ id: a.id ?? a.localId, key: a.key ?? "", name: a.name, content_type: a.content_type, size: a.size, url: a.url ?? "", localId: a.localId })),
        local: { status: m.status, attempts: m.attempts, error: m.error },
      }));
    return local.length ? [...stream.bubbles, ...local] : stream.bubbles;
  }, [stream.bubbles, outbox, workspaceId, user]);

  const visible = useMemo(() => bubbles.filter((b) => (threadId === null ? true : b.threadId === threadId)), [bubbles, threadId]);
  const streaming = useMemo(() => visible.filter((b) => b.streaming), [visible]);

  const cancel = useMutation({
    mutationFn: async () => {
      if (!workspaceId) return;
      const seen = new Set<string>();
      for (const b of streaming) {
        const body = b.correlationId ? { correlation_id: b.correlationId } : { thread_id: b.threadId };
        const key = JSON.stringify(body);
        if (seen.has(key)) continue;
        seen.add(key);
        await api.workspaces.cancelReply(workspaceId, body);
      }
    },
  });

  const send = (text: string, localIds: string[]) => {
    if (!workspaceId) return;
    const items = useAttachments.getState().items;
    useOutbox.getState().enqueue({
      client_msg_id: newId(),
      workspace_id: workspaceId,
      thread_id: threadId,
      text,
      attachments: localIds
        .map((localId) => items[localId])
        .filter(Boolean)
        .map((a) => ({ localId: a.localId, name: a.name, size: a.size, content_type: a.content_type, id: a.result?.id, key: a.result?.key, url: a.result?.url })),
    });
    kickSender();
  };

  return (
    <div className="flex h-full min-h-0 flex-1 flex-col">
      <ChatHeader connection={stream.connection} />
      <div className="flex min-h-0 flex-1">
        <div className={cn("flex min-w-0 flex-1 flex-col", viewPaneOpen && "lg:max-w-[55%]")}>
          <MessageList bubbles={visible} empty={workspaceId ? t("chat.empty") : t("chat.noWorkspace")} />
          <div className="border-t border-white/5 bg-ink-950/40 px-4 pb-4 pt-3 backdrop-blur-md">
            <Composer
              workspaceId={workspaceId}
              draftKey={`${workspaceId ?? "-"}:${threadId ?? "global"}`}
              streaming={streaming.length > 0}
              stopping={cancel.isPending}
              onStop={() => cancel.mutate()}
              onSend={send}
            />
            <ActivityStrip events={stream.activity} />
          </div>
        </div>
        {viewPaneOpen && <ViewPane />}
      </div>
      <Lightbox />
    </div>
  );
}
