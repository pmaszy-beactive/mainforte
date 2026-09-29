import { wsUrl } from "./api";
import type { WsEvent } from "./types";

export type SocketStatus = "connecting" | "open" | "reconnecting" | "closed";

export interface EventSocketOptions {
  token: string;
  workspaceId: string;
  after?: string | null;
  onEvent: (ev: WsEvent) => void;
  onStatus?: (s: SocketStatus, attempt: number) => void;
}

const ACK_EVERY = 10;
const PING_MS = 25_000;
const DEAD_AFTER_MS = 45_000; // no event and no _heartbeat for this long => dead
const BACKOFF_MS = [500, 1000, 2000, 4000, 8000, 15000];

interface ControlFrame {
  type: "_hello" | "_heartbeat" | string;
  last_id?: string;
  replayed?: number;
}

/**
 * One reconnecting socket per (token, workspace). Resumes with `after=<last id>`,
 * acks every 10 events, pings every 25s, and treats 45s of silence as a dead socket.
 */
export class EventSocket {
  private ws: WebSocket | null = null;
  private lastId: string | null;
  private unacked = 0;
  private attempt = 0;
  private closed = false;
  private pingTimer: ReturnType<typeof setInterval> | null = null;
  private deadTimer: ReturnType<typeof setTimeout> | null = null;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(private opts: EventSocketOptions) {
    this.lastId = opts.after ?? null;
    this.connect();
  }

  get lastEventId() {
    return this.lastId;
  }

  /** Force an immediate reconnect (e.g. the browser came back online). */
  reconnectNow() {
    if (this.closed) return;
    if (this.retryTimer) {
      clearTimeout(this.retryTimer);
      this.retryTimer = null;
      this.connect();
    } else if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      this.ws?.close();
    }
  }

  /**
   * Force a reconnect even if the socket still reports OPEN. Backgrounded/suspended tabs can leave a
   * socket whose underlying connection died silently (no onclose fires, so scheduleReconnect never
   * runs) — call this when the tab regains visibility to guarantee recovery instead of waiting on the
   * setTimeout-based watchdog, which browsers throttle while the tab is hidden.
   */
  forceReconnect() {
    if (this.closed) return;
    if (this.retryTimer) {
      clearTimeout(this.retryTimer);
      this.retryTimer = null;
      this.connect();
      return;
    }
    this.ws?.close();
  }

  private setStatus(s: SocketStatus) {
    this.opts.onStatus?.(s, this.attempt);
  }

  private armWatchdog() {
    if (this.deadTimer) clearTimeout(this.deadTimer);
    this.deadTimer = setTimeout(() => this.ws?.close(), DEAD_AFTER_MS);
  }

  private connect() {
    if (this.closed) return;
    this.setStatus(this.attempt === 0 ? "connecting" : "reconnecting");
    const params: Record<string, string> = { token: this.opts.token, workspace_id: this.opts.workspaceId };
    if (this.lastId) params.after = this.lastId;

    const ws = new WebSocket(wsUrl(params));
    this.ws = ws;

    ws.onopen = () => {
      this.attempt = 0;
      this.setStatus("open");
      this.pingTimer = setInterval(() => this.send({ type: "ping" }), PING_MS);
      this.armWatchdog();
    };
    ws.onmessage = (m) => {
      this.armWatchdog();
      let frame: WsEvent | ControlFrame;
      try {
        frame = JSON.parse(String(m.data)) as WsEvent | ControlFrame;
      } catch {
        return;
      }
      if (!frame || typeof frame !== "object") return;
      if (!("id" in frame) || !frame.id) {
        // _hello / _heartbeat / pong: liveness only.
        return;
      }
      const ev = frame as WsEvent;
      this.lastId = ev.id;
      this.opts.onEvent(ev);
      if (++this.unacked >= ACK_EVERY) {
        this.unacked = 0;
        this.send({ type: "ack", id: ev.id });
      }
    };
    ws.onclose = () => {
      if (this.ws === ws) this.scheduleReconnect();
    };
    ws.onerror = () => ws.close();
  }

  private scheduleReconnect() {
    this.cleanupSocket();
    if (this.closed) return;
    const delay = BACKOFF_MS[Math.min(this.attempt, BACKOFF_MS.length - 1)];
    this.attempt++;
    this.setStatus("reconnecting");
    this.retryTimer = setTimeout(() => {
      this.retryTimer = null;
      this.connect();
    }, delay);
  }

  private cleanupSocket() {
    if (this.pingTimer) clearInterval(this.pingTimer);
    if (this.deadTimer) clearTimeout(this.deadTimer);
    this.pingTimer = null;
    this.deadTimer = null;
    this.ws = null;
  }

  private send(msg: unknown) {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(msg));
  }

  close() {
    this.closed = true;
    if (this.retryTimer) clearTimeout(this.retryTimer);
    const ws = this.ws;
    this.cleanupSocket();
    if (ws && ws.readyState === WebSocket.OPEN && this.lastId) {
      try {
        ws.send(JSON.stringify({ type: "ack", id: this.lastId }));
      } catch {
        /* ignore */
      }
    }
    ws?.close();
    this.setStatus("closed");
  }
}
