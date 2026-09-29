import { useEffect, useMemo, useReducer, useRef, useState } from "react";
import { EventSocket, type SocketStatus } from "@/lib/ws";
import { api } from "@/lib/api";
import type { Attachment, ChatMessagePayload, ReplyPayload, TaskBlockedPayload, WsEvent } from "@/lib/types";
import { useAuth } from "@/stores/auth";
import { useStream } from "@/stores/stream";
import { useOutbox, type OutboxStatus } from "@/stores/outbox";
import { kickSender } from "@/lib/sender";

export interface Bubble {
  id: string;
  threadId: string | null;
  actorType: string;
  actorId: string;
  userId: string | null;
  text: string;
  ts: string;
  streaming: boolean;
  canceled: boolean;
  clientMsgId: string | null;
  correlationId: string | null;
  attachments: Attachment[];
  /** This turn's non-message events (tool/task/etc.), in order, keyed by correlation_id. */
  activity: WsEvent[];
  /** Present on optimistic bubbles that come from the outbox. */
  local?: { status: OutboxStatus; attempts: number; error: string | null };
}

export interface BlockedTask {
  taskId: string;
  threadId: string | null;
  reason: string;
  ts: string;
}

interface State {
  bubbles: Bubble[];
  activity: WsEvent[];
  seen: Record<string, 1>;
  /** Tasks currently awaiting human input, keyed by task_id. Cleared once resolved/terminal. */
  blockedTasks: Record<string, BlockedTask>;
}

type Action =
  | { type: "event"; ev: WsEvent }
  | { type: "hydrate"; events: WsEvent[] }
  | { type: "reset" }
  | { type: "clearBlocked"; taskId: string };

const MAX_ACTIVITY = 200;
const initial: State = { bubbles: [], activity: [], seen: {}, blockedTasks: {} };

function streamKey(ev: WsEvent) {
  const p = ev.payload as unknown as ReplyPayload;
  // One streaming bubble per (persona, thread, correlation).
  return `stream:${ev.actor.type}:${ev.actor.id}:${p.thread_id ?? ""}:${ev.correlation_id ?? ""}`;
}

function applyEvent(state: State, ev: WsEvent): State {
  if (state.seen[ev.id]) return state; // replayed / duplicate
  const seen = { ...state.seen, [ev.id]: 1 as const };

  switch (ev.type) {
    case "chat.message.created": {
      const p = ev.payload as unknown as ChatMessagePayload;
      const b: Bubble = {
        id: ev.id,
        threadId: p.thread_id ?? null,
        actorType: ev.actor.type,
        actorId: ev.actor.id,
        userId: ev.user_id,
        text: p.text ?? "",
        ts: ev.ts,
        streaming: false,
        canceled: false,
        clientMsgId: p.client_msg_id ?? null,
        correlationId: ev.correlation_id,
        attachments: p.attachments ?? [],
        activity: [],
      };
      return { ...state, seen, bubbles: [...state.bubbles, b] };
    }
    case "persona.reply.delta":
    case "persona.reply.ended":
    case "persona.reply.canceled": {
      const p = ev.payload as unknown as ReplyPayload;
      const key = streamKey(ev);
      const ended = ev.type === "persona.reply.ended";
      const canceled = ev.type === "persona.reply.canceled";
      const idx = state.bubbles.findIndex((b) => b.id === key || (ended && b.id === ev.id));
      const activity = canceled ? pushActivity(state.activity, ev) : state.activity;
      if (idx === -1) {
        if (canceled) return { ...state, seen, activity };
        const b: Bubble = {
          id: key,
          threadId: p.thread_id ?? null,
          actorType: ev.actor.type,
          actorId: ev.actor.id,
          userId: ev.user_id,
          text: p.text ?? "",
          ts: ev.ts,
          streaming: !ended,
          canceled: false,
          clientMsgId: null,
          correlationId: ev.correlation_id,
          attachments: [],
          activity: [],
        };
        return { ...state, seen, activity, bubbles: [...state.bubbles, b] };
      }
      const cur = state.bubbles[idx];
      let next: Bubble;
      if (ended) {
        // `ended` carries the full final text and is replayed: always reconcile to it.
        next = { ...cur, text: p.text ? p.text : cur.text, streaming: false, ts: ev.ts };
      } else if (canceled) {
        next = { ...cur, streaming: false, canceled: true };
      } else {
        if (!cur.streaming) return { ...state, seen }; // late delta after end/cancel
        next = { ...cur, text: cur.text + (p.text ?? "") };
      }
      const bubbles = state.bubbles.slice();
      bubbles[idx] = next;
      return { ...state, seen, activity, bubbles };
    }
    case "task.blocked": {
      const p = ev.payload as unknown as TaskBlockedPayload;
      const blockedTasks = { ...state.blockedTasks, [p.task_id]: { taskId: p.task_id, threadId: p.thread_id ?? null, reason: p.reason, ts: ev.ts } };
      return { ...state, seen, blockedTasks, activity: pushActivity(state.activity, ev) };
    }
    case "task.completed":
    case "task.failed":
    case "task.canceled": {
      const taskId = (ev.payload as { task_id?: string }).task_id;
      if (!taskId || !(taskId in state.blockedTasks)) return { ...state, seen, activity: pushActivity(state.activity, ev) };
      const blockedTasks = { ...state.blockedTasks };
      delete blockedTasks[taskId];
      return { ...state, seen, blockedTasks, activity: pushActivity(state.activity, ev) };
    }
    default: {
      const activity = pushActivity(state.activity, ev);
      if (ev.correlation_id == null) return { ...state, seen, activity };
      const key = streamKey(ev);
      const idx = state.bubbles.findIndex((b) => b.id === key);
      if (idx === -1) {
        const p = ev.payload as { thread_id?: string };
        const b: Bubble = {
          id: key,
          threadId: p.thread_id ?? null,
          actorType: ev.actor.type,
          actorId: ev.actor.id,
          userId: ev.user_id,
          text: "",
          ts: ev.ts,
          streaming: true,
          canceled: false,
          clientMsgId: null,
          correlationId: ev.correlation_id,
          attachments: [],
          activity: [ev],
        };
        return { ...state, seen, activity, bubbles: [...state.bubbles, b] };
      }
      const bubbles = state.bubbles.slice();
      bubbles[idx] = { ...bubbles[idx], activity: [...bubbles[idx].activity, ev] };
      return { ...state, seen, activity, bubbles };
    }
  }
}

function pushActivity(list: WsEvent[], ev: WsEvent) {
  const activity = [...list, ev];
  if (activity.length > MAX_ACTIVITY) activity.splice(0, activity.length - MAX_ACTIVITY);
  return activity;
}

function reduce(state: State, action: Action): State {
  switch (action.type) {
    case "reset":
      return initial;
    case "hydrate":
      return action.events.reduce(applyEvent, state);
    case "event":
      return applyEvent(state, action.ev);
    case "clearBlocked": {
      if (!(action.taskId in state.blockedTasks)) return state;
      const blockedTasks = { ...state.blockedTasks };
      delete blockedTasks[action.taskId];
      return { ...state, blockedTasks };
    }
  }
}

export interface StreamConnection {
  status: SocketStatus;
  attempt: number;
}

/**
 * Loads recent history over REST, then opens the workspace socket resuming from the
 * last seen id. Folds events into chat bubbles (chat.message.created / persona.reply.*)
 * and an activity list (everything else), idempotently by event id.
 */
export function useEventStream(workspaceId: string | null | undefined) {
  const token = useAuth((s) => s.token);
  const [state, dispatch] = useReducer(reduce, initial);
  const [conn, setConn] = useState<StreamConnection>({ status: "closed", attempt: 0 });
  const socketRef = useRef<EventSocket | null>(null);

  useEffect(() => {
    dispatch({ type: "reset" });
    if (!token || !workspaceId) return;
    let cancelled = false;

    const onEvent = (ev: WsEvent) => {
      if (ev.type === "chat.message.created") {
        const cid = (ev.payload as unknown as ChatMessagePayload).client_msg_id;
        if (cid) useOutbox.getState().remove(cid); // the server has it; drop the optimistic copy
      }
      dispatch({ type: "event", ev });
      useStream.getState().setLastId(workspaceId, ev.id);
    };

    (async () => {
      let after = useStream.getState().lastIds[workspaceId] ?? null;
      try {
        const { events } = await api.workspaces.events(workspaceId, { after: after ?? undefined, limit: 200 });
        if (cancelled) return;
        if (events.length) {
          dispatch({ type: "hydrate", events });
          for (const ev of events) {
            const cid = ev.type === "chat.message.created" ? (ev.payload as unknown as ChatMessagePayload).client_msg_id : undefined;
            if (cid) useOutbox.getState().remove(cid);
          }
          after = events[events.length - 1].id; // resume exactly where history ends
        }
      } catch {
        /* offline or API down: the socket replay from the stored id still covers us */
      }
      if (cancelled) return;
      socketRef.current = new EventSocket({
        token,
        workspaceId,
        after,
        onEvent,
        onStatus: (status, attempt) => {
          setConn({ status, attempt });
          if (status === "open") kickSender();
        },
      });
    })();

    const onOnline = () => socketRef.current?.reconnectNow();
    window.addEventListener("online", onOnline);
    // A backgrounded/suspended tab throttles the socket's setTimeout-based dead-link watchdog, so a
    // connection that died while hidden can sit "open" indefinitely. Force a reconnect on return.
    const onVisible = () => {
      if (document.visibilityState === "visible") socketRef.current?.forceReconnect();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      cancelled = true;
      window.removeEventListener("online", onOnline);
      document.removeEventListener("visibilitychange", onVisible);
      socketRef.current?.close();
      socketRef.current = null;
    };
  }, [token, workspaceId]);

  return useMemo(
    () => ({
      bubbles: state.bubbles,
      activity: state.activity,
      connection: conn,
      blockedTasks: state.blockedTasks,
      clearBlocked: (taskId: string) => dispatch({ type: "clearBlocked", taskId }),
    }),
    [state, conn],
  );
}
