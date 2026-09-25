# Mainforte frontend

Vite 7 + React 19 + TypeScript + Tailwind v4 + react-router v7 + TanStack Query + zustand.

```sh
pnpm install
pnpm dev        # http://localhost:5173, proxies /api and /ws to http://localhost:8000
pnpm build      # typecheck + bundle to ./dist
pnpm typecheck
```

## Layout

- `src/lib/api.ts` — the only HTTP client. Base URL from `VITE_API_URL` (empty = same origin). Adds `Authorization: Bearer <token>` from the auth store.
- `src/lib/ws.ts` — `EventSocket`: reconnecting `/ws` client with `after=` resume, acks every 10 events, pings every 25s, and closes/reconnects after 45s without an event or `_heartbeat`.
- `src/stores/outbox.ts` + `src/lib/sender.ts` — persisted outbound queue (`client_msg_id` per message) and the single sender loop: in order per workspace, backoff 1s→30s, kicked on `online`, socket reconnect and upload completion; fails only on non-retryable 4xx.
- `src/stores/attachments.ts` + `src/lib/upload.ts` — XHR uploads with progress and retry; a message waits in the queue until its uploads finish. Files themselves cannot survive a reload, so a queued message whose upload never finished is marked failed ("attachment lost").
- `src/stores/stream.ts` — last event id per workspace, so a restart resumes the socket from where it left off (after hydrating recent history from `GET /events`).
- `src/stores/auth.ts` — zustand store, persisted to localStorage (`mainforte.auth`).
- `src/hooks/useEventStream.ts` — turns the socket into chat bubbles + activity events for `ChatPane`.
- `src/features/*` — one folder per route group (marketing, auth, app, chat, admin, settings, billing).
- `src/i18n/` + `src/locales/{en-US,fr-CA}.json` — react-i18next. Browser `fr*` maps to `fr-CA`, everything else `en-US`; the server's `me.user.locale` wins once logged in (`useLocaleSync` PATCHes `/api/me` with detected locale/timezone when they differ). Dates/numbers/currency go through `useFormat()` (Intl, user locale + timezone).

Routes are plain (no hash) and lazy-loaded; there is no SSR so the bundle can be wrapped by Capacitor as-is.

## Mobile

Set `VITE_API_URL` to the public API origin before `pnpm build`, then point Capacitor's `webDir` at `frontend/dist`.
