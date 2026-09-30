from __future__ import annotations

import asyncio
import logging
import os
import socket
from datetime import timedelta

from mainforte import __version__
from mainforte.aiproxy import client as aiproxy
from mainforte.aiproxy.keys import get_or_mint
from mainforte.celery_app import celery
from mainforte.db.base import utcnow
from mainforte.db.models import AgentWorker, AuthToken, Event, Memory, Setting, Task, Widget, Workspace
from mainforte.db.session import db_session
from mainforte.events import emit
from mainforte.events.bus import dispatch, to_dict

log = logging.getLogger(__name__)


def _version_tuple(v: str | None) -> tuple[int, ...]:
    """Parses 'MAJOR.MINOR.PATCH' into a comparable tuple. Falls back to (0,) (sorts oldest) for
    anything unparseable, so a garbage/missing version never wins a comparison it should not."""
    if not v:
        return (0,)
    parts: list[int] = []
    for p in v.split("."):
        if not p.isdigit():
            return (0,)
        parts.append(int(p))
    return tuple(parts) or (0,)

WORKER_ID = os.environ.get("MAINFORTE_WORKER_ID") or f"w-{socket.gethostname()}"
ROLLUP_MODEL = "claude-haiku-4-5-20251001"


@celery.task(name="mainforte.tasks.system.worker_heartbeat")
def worker_heartbeat() -> None:
    """Beat-driven self-registration so the admin Workers page sees backbone's standard worker as #1."""
    with db_session() as db:
        w = db.query(AgentWorker).filter_by(container_name=WORKER_ID).first()
        if not w:
            # DEBUG (investigating unexplained pool churn -- 2026-09-30): this is the ONLY place a
            # pooled worker's AgentWorker row is created. _provision() never inserts the row itself,
            # it only triggers Jenkins and emits worker.provisioning -- so if a container's process
            # boots and heartbeats here WITHOUT a matching recent worker.provisioning event, its
            # existence was never decided by _reconcile_pool/_provision at all, and something else
            # (Jenkins-side trigger, a crash-restart under `--restart unless-stopped` reviving an old
            # container under the same name, a manual docker run, etc.) created the container.
            # Logging every field that could distinguish those cases: hostname, PID, container uptime
            # proxy (we don't have real uptime, but boot time via psutil isn't worth the dep -- PID +
            # parent env is enough to correlate against the host's own `docker ps`/`docker inspect`),
            # and whether ANY worker.provisioning event for this exact name exists at all, regardless
            # of age (not just inside the 300s grace window) -- if none ever existed, this container
            # was never provisioned through the reconciler, full stop.
            ever_provisioned = (
                db.query(Event.id, Event.ts)
                .filter(Event.type == "worker.provisioning", Event.payload["container_name"].astext == WORKER_ID)
                .order_by(Event.ts.desc())
                .first()
            )
            # Process (not container) start time, read from /proc so it survives even if this is a
            # respawn of a container Docker never actually recreated (e.g. `--restart unless-stopped`
            # reviving the SAME container after its main process died -- container creation time would
            # then look old/misleading, but this process's own start time is exact).
            try:
                with open("/proc/self/stat") as f:
                    _clk_ticks_at_boot = int(f.read().split(")")[-1].split()[19])
                with open("/proc/uptime") as f:
                    _uptime_s = float(f.read().split()[0])
                import os as _os
                _clk_tck = _os.sysconf("SC_CLK_TCK")
                proc_age_s = round(_uptime_s - (_clk_ticks_at_boot / _clk_tck), 1)
            except Exception:
                proc_age_s = None
            log.warning(
                "worker_heartbeat: NEW AgentWorker row for container_name=%s (first heartbeat ever seen "
                "for this name) pid=%s proc_age_s=%s hostname=%s node=%s MAINFORTE_WORKER_ID_env=%s "
                "matching_worker.provisioning_event=%s",
                WORKER_ID, os.getpid(), proc_age_s, socket.gethostname(), os.environ.get("NODE_NAME"),
                os.environ.get("MAINFORTE_WORKER_ID"),
                (ever_provisioned[0], ever_provisioned[1].isoformat()) if ever_provisioned else None,
            )
            w = AgentWorker(container_name=WORKER_ID, node=os.environ.get("NODE_NAME"), status="online")
            db.add(w)
        # A draining worker's own heartbeat must not flip it back to "online" — reconcile is what
        # moves it out of draining (by destroying it once idle), never the worker itself.
        if w.status != "draining":
            w.status = "online"
        w.last_heartbeat = utcnow()
        w.version = __version__
        w.stats = {"pid": os.getpid()}


@celery.task(name="mainforte.tasks.system.sweep_outbox")
def sweep_outbox() -> int:
    """Re-dispatch events that were committed but never published/enqueued (process died mid-dispatch,
    Redis/RabbitMQ blip, redeploy). Runs every 30s; only touches events older than 60s."""
    cutoff = utcnow() - timedelta(seconds=60)
    with db_session() as db:
        rows = (db.query(Event).filter(Event.dispatched_at.is_(None), Event.ts < cutoff)
                .order_by(Event.id.asc()).limit(500).all())
        n = 0
        for ev in rows:
            if dispatch(to_dict(ev)):
                ev.dispatched_at = utcnow()
                n += 1
    return n


@celery.task(name="mainforte.tasks.system.sweep_auth_tokens")
def sweep_auth_tokens() -> int:
    with db_session() as db:
        n = db.query(AuthToken).filter(AuthToken.expires_at < utcnow()).delete()
    return n


# billing.* rows are excluded from retention: admin/routes.py's finances() sums
# billing.usage.recorded across all time for MRR/cost reporting, so pruning them would silently
# corrupt historical totals rather than just shrinking search/grounding lookback (PLAN.md task #37).
EVENT_RETENTION_EXCLUDE_PREFIX = "billing."


@celery.task(name="mainforte.tasks.system.sweep_old_events")
def sweep_old_events() -> int:
    """Daily: hard-deletes `events` rows older than `event_retention_days`, except billing.* (kept
    forever for finance reporting). This must run *before* the FTS index is trusted to reflect "all
    history" -- otherwise the index just gets more expensive to maintain over an unbounded table
    with no corresponding search-reach guarantee (PLAN.md task #37 risk analysis). Deletes in
    bounded batches so one run never holds a long-running lock on a large sweep."""
    from mainforte.config import get_settings

    settings = get_settings()
    cutoff = utcnow() - timedelta(days=settings.event_retention_days)
    total = 0
    while True:
        with db_session() as db:
            ids = [
                row[0] for row in db.query(Event.id)
                .filter(Event.ts < cutoff, ~Event.type.like(f"{EVENT_RETENTION_EXCLUDE_PREFIX}%"))
                .order_by(Event.id.asc()).limit(1000).all()
            ]
            if not ids:
                break
            db.query(Event).filter(Event.id.in_(ids)).delete(synchronize_session=False)
            total += len(ids)
        if len(ids) < 1000:
            break
    return total


async def _summarize(*, api_key: str, transcript: str) -> str:
    system = ("Summarize this chat thread's activity into 2-4 sentences of durable, useful notes "
              "(preferences stated, decisions made, open items). Skip small talk.")
    full = ""
    async for chunk in aiproxy.stream_reply(
        api_key=api_key, model=ROLLUP_MODEL, system=system,
        messages=[{"role": "user", "content": transcript}], max_tokens=400,
    ):
        full += chunk
    return full.strip()


@celery.task(name="mainforte.tasks.system.rollup_threads")
def rollup_threads() -> int:
    """Daily: for each thread with chat.message.created events older than 24h and no existing
    rollup_day Memory row for that thread+day, summarize via ai-proxy and write one Memory row,
    then emit chat.thread.rolled_up."""
    cutoff = utcnow() - timedelta(hours=24)
    n = 0
    with db_session() as db:
        thread_ids = [
            row[0] for row in db.query(Event.correlation_id).distinct()
            .filter(Event.type == "chat.message.created", Event.ts < cutoff, Event.correlation_id.isnot(None))
            .all()
        ]
        for thread_id in thread_ids:
            already = db.query(Memory).filter_by(kind="rollup_day", thread_id=thread_id).first()
            if already:
                continue
            msgs = (
                db.query(Event)
                .filter(Event.correlation_id == thread_id,
                        Event.type.in_(("chat.message.created", "persona.reply.ended")))
                .order_by(Event.id.asc()).limit(200).all()
            )
            if not msgs:
                continue
            ws = db.get(Workspace, msgs[0].ws_id)
            if ws is None:
                continue
            api_key = get_or_mint(db, ws)
            if api_key is None:
                continue
            transcript = "\n".join(
                f"{'User' if ev.type == 'chat.message.created' else 'Persona'}: {ev.payload.get('text', '')}"
                for ev in msgs if ev.payload.get("text")
            )
            if not transcript.strip():
                continue
            try:
                summary = asyncio.run(_summarize(api_key=api_key, transcript=transcript))
            except aiproxy.AiProxyError:
                log.exception("rollup summarize failed for thread %s", thread_id)
                continue
            if not summary:
                continue
            mem = Memory(ws_id=ws.id, kind="rollup_day", thread_id=thread_id, source="rollup", text=summary)
            db.add(mem)
            db.flush()
            emit(db, "chat.thread.rolled_up", ws_id=ws.id, actor=("system", None),
                 payload={"thread_id": thread_id, "memory_id": mem.id, "period": "day"})
            n += 1
    return n


@celery.task(name="mainforte.tasks.system.refresh_due_widgets")
def refresh_due_widgets() -> int:
    """Beat-driven sweep (P2 phase 7): dispatches `refresh_widget` for every active widget that
    carries a `refresh_spec`. Runs every 5min; `refresh_spec` itself owns *when* a given widget is
    actually due (checked inside `refresh_widget`, not here) so this sweep stays a cheap fan-out."""
    with db_session() as db:
        ids = [row[0] for row in db.query(Widget.id)
               .filter(Widget.status == "active", Widget.refresh_spec.isnot(None)).all()]
    for widget_id in ids:
        refresh_widget_task.delay(widget_id=widget_id)
    return len(ids)


@celery.task(name="mainforte.tasks.system.refresh_due_tasks")
def refresh_due_tasks() -> int:
    """Beat-driven sweep (P4 recurrence), parallel to `refresh_due_widgets`: fans out
    `fire_scheduled_task` for every `scheduled` template whose `schedule.next_run_at` has passed.
    Runs every 60s -- more time-sensitive than widgets' 300s, since a task recurrence is often
    wall-clock-meaningful (e.g. "every morning at 8") in a way a data-refresh cadence isn't.
    `next_run_at` is stored as an ISO-8601 UTC string inside the `schedule` JSONB; string comparison
    against another ISO-8601 UTC string sorts identically to a timestamp comparison, so this stays a
    plain JSONB text match rather than needing a cast."""
    from mainforte.tasks.work import fire_scheduled_task

    now_iso = utcnow().isoformat()
    with db_session() as db:
        ids = [
            row[0] for row in db.query(Task.id)
            .filter(Task.status == "scheduled",
                    Task.schedule["active"].astext == "true",
                    Task.schedule["next_run_at"].astext <= now_iso)
            .all()
        ]
    for task_id in ids:
        fire_scheduled_task.delay(task_id=task_id)
    return len(ids)


AGENT_WORKER_PREFIX = "mainforte-agent-worker-"
AGENT_WORKER_SANDBOX_PREFIX = f"{AGENT_WORKER_PREFIX}sandbox-"
AGENT_WORKER_MAX_PROVISION_PER_TICK = 2  # cap Jenkins job bursts, mirrors backbone's vexa_spare_pool.py

# Two independently-scalable pools, both provisioned via the same Jenkins job
# (now CELERY_QUEUES-parameterized, see Dockerfile.worker) but tracked under
# distinct container-name prefixes so each pool's reconciliation never touches
# the other's containers. Desired counts for both pools live together in the
# single "workers.desired" Setting row (see get_pool_desired_counts below).
#   "full"    — chat,work,system. Keeps the original mainforte-agent-worker-N
#               naming (back-compat with any already-provisioned workers) but
#               excludes the sandbox pool's names, which also start with that prefix.
#   "sandbox" — work only (browser/bash tool execution, scaled independently
#               of chat/LLM capacity), under its own mainforte-agent-worker-sandbox-N names.
AGENT_WORKER_POOLS = {
    "full": {"prefix": AGENT_WORKER_PREFIX, "exclude_prefix": AGENT_WORKER_SANDBOX_PREFIX,
             "queues": None, "desired_field": "full"},
    "sandbox": {"prefix": AGENT_WORKER_SANDBOX_PREFIX, "exclude_prefix": None,
                "queues": "work", "desired_field": "sandbox"},
}

WORKERS_DESIRED_KEY = "workers.desired"
_LEGACY_SANDBOX_DESIRED_KEY = "workers.desired.sandbox"  # pre-merge key, read once as a migration fallback


def get_pool_desired_counts(db) -> dict:
    """Returns {"full": N, "sandbox": M} from the single workers.desired Setting row.

    Migration note: before pool counts were merged into one row, "full" lived at this same
    "workers.desired" key and "sandbox" lived separately at "workers.desired.sandbox". A merged
    row's "full"/"sandbox" fields always win; either field missing from it (e.g. a row saved
    before the merge, which only ever had "count") falls back to that pool's old default, or to
    the legacy sandbox row if one still exists, so existing desired counts aren't silently reset.
    """
    row = db.get(Setting, WORKERS_DESIRED_KEY)
    value = row.value if row else {}

    full = value.get("full", value.get("count", 1))

    if "sandbox" in value:
        sandbox = value["sandbox"]
    else:
        legacy = db.get(Setting, _LEGACY_SANDBOX_DESIRED_KEY)
        sandbox = legacy.value.get("count", 0) if legacy else 0

    return {"full": full, "sandbox": sandbox}


def set_current_job(worker_id: str, job: str | None) -> None:
    """Marks (or clears) the AgentWorker row's current_job — the reconciler's idle signal for
    draining (see drain_worker/_worker_is_idle below). Called from task entrypoints in tasks/work.py
    at start/end of a unit of work, not just from worker_heartbeat's own beat tick, so it reflects
    reality immediately rather than lagging up to 30s behind the next heartbeat."""
    with db_session() as db:
        w = db.query(AgentWorker).filter_by(container_name=worker_id).first()
        if w:
            w.current_job = job


def drain_worker(db, container_name: str, queues: str | None) -> None:
    """Tells a running worker to stop consuming *new* tasks (Celery cancel_consumer on each of its
    queues) while it keeps running and finishes whatever it already has, and marks it draining in
    the DB. Idempotent — safe to call every reconcile tick until the worker is destroyed.

    cancel_consumer is a RabbitMQ/Redis broker control command (mainforte uses amqp:// per
    config.py) — no effect on brokers without remote-control support, but we still set the DB
    status either way so _worker_is_idle/destroy logic isn't broker-dependent."""
    queue_names = (queues or "chat,work,system").split(",")
    try:
        for q in queue_names:
            celery.control.cancel_consumer(q, destination=[f"celery@{container_name}"])
    except Exception as e:  # noqa: BLE001 — best-effort; DB draining flag is the source of truth below
        log.warning("drain_worker: cancel_consumer failed for %s: %s", container_name, e)

    w = db.query(AgentWorker).filter_by(container_name=container_name).first()
    if w:
        w.status = "draining"


def _worker_is_idle(w: AgentWorker) -> bool:
    """DB heartbeat state (current_job) is the source of truth for idleness, not a live broker RPC
    (celery.control.inspect().active()) — a busy broker/connection blip can make inspect return no
    reply within its timeout even for a genuinely idle worker, per Celery's own docs."""
    return w.current_job is None


def _worker_sort_key(container_name: str | None, prefix: str) -> tuple[int, str]:
    """Numeric-aware sort key so 'worker-2' sorts before 'worker-10' -- plain string ordering
    (AgentWorker.container_name.asc(), and this function's own former reliance on it via
    `reversed(managed)`) put '-10' before '-2' (string "1" < "10" < "2"), so the old "destroy
    newest-named first" logic picked the freshest real worker as its victim while an ancient,
    long-stale double-digit-named row (e.g. '...-sandbox-10') never got selected and sat there
    forever, un-destroyed, permanently occupying a `managed` slot. Falls back to pure string
    sort for anything that doesn't parse as prefix+int (should never happen for reconciler-owned
    names, but never crash sorting over it if it does)."""
    name = container_name or ""
    if name.startswith(prefix):
        suffix = name[len(prefix):]
        if suffix.isdigit():
            return (int(suffix), name)
    return (10**9, name)  # unparseable names sort last either direction; never expected in practice


def _reconcile_pool(db, s, pool: str, cfg: dict) -> dict:
    from mainforte.jenkins_ssh import trigger_jenkins_build

    prefix = cfg["prefix"]
    desired = get_pool_desired_counts(db)[cfg["desired_field"]]

    q = db.query(AgentWorker).filter(AgentWorker.container_name.like(f"{prefix}%"))
    if cfg["exclude_prefix"]:
        q = q.filter(~AgentWorker.container_name.like(f"{cfg['exclude_prefix']}%"))
    managed = sorted(q.all(), key=lambda w: _worker_sort_key(w.container_name, prefix))

    now_for_staleness = utcnow()
    stale = now_for_staleness - timedelta(seconds=90)
    def is_stale(w: AgentWorker) -> bool:
        return w.status == "online" and (w.last_heartbeat or stale) <= stale
    live_workers = [w for w in managed if not is_stale(w)]
    live = len(live_workers)
    stale_workers = [w for w in managed if is_stale(w)]

    log.info(
        "reconcile_agent_workers[%s]: managed=%s live=%s desired=%s reconciler_version=%s "
        "rows=%s",
        pool, len(managed), live, desired, __version__,
        [(w.container_name, w.status, w.version, w.last_heartbeat.isoformat() if w.last_heartbeat else None)
         for w in managed],
    )
    # DEBUG (investigating unexplained pool churn -- 2026-09-30): every worker's staleness
    # decision spelled out explicitly, every tick, not just when a stale row exists -- specifically
    # to catch a worker whose heartbeat is landing close to the 90s cutoff, where DB replication
    # lag, clock skew between the app container and whichever worker last wrote last_heartbeat, or
    # simple bad luck in scheduling could flip is_stale() to True for a worker that is actually
    # fine, making `live` undercount for exactly one tick -- enough to trigger a real, correct-per-
    # its-own-logic `live < desired` provision call that then races the worker's next heartbeat.
    # age_seconds is None only when last_heartbeat itself is None (a row that was inserted but has
    # never actually heartbeat yet).
    log.warning(
        "reconcile_agent_workers[%s]: staleness_detail (cutoff=90s, now=%s) %s",
        pool, now_for_staleness.isoformat(),
        [
            (
                w.container_name,
                w.status,
                w.last_heartbeat.isoformat() if w.last_heartbeat else None,
                round((now_for_staleness - w.last_heartbeat).total_seconds(), 2) if w.last_heartbeat else None,
                is_stale(w),
            )
            for w in managed
        ],
    )
    if stale_workers:
        # DEBUG (investigating unexplained pool churn -- 2026-09-30): a stale row (status="online"
        # but no heartbeat in 90s+) is excluded from `live` but still counted in `managed`, and
        # under the OLD string-sort destroy-candidate ordering could permanently dodge being
        # picked as a destroy victim (see _worker_sort_key's docstring) -- log every stale row's
        # age explicitly so a recurring zombie is visible in the log even after the sort fix,
        # rather than silently inflating `managed` forever.
        now = utcnow()
        log.warning(
            "reconcile_agent_workers[%s]: %s stale row(s) present (online but no heartbeat in "
            ">=90s, excluded from live but still in managed): %s",
            pool, len(stale_workers),
            [(w.container_name, round((now - w.last_heartbeat).total_seconds(), 1) if w.last_heartbeat else None)
             for w in stale_workers],
        )

    # Rolling replace: some live worker is running an older build than this reconciler's own
    # process — i.e. a redeploy happened. Handled before the plain count-based branches below so
    # a version bump doesn't need a separate desired-count bump to kick off a swap.
    #
    # A worker provisioned within the last AGENT_WORKER_PROVISION_GRACE_SECONDS is exempt from
    # being classified outdated even if its version doesn't match yet: it still counts toward
    # `live`/`current_count` once it heartbeats, but it gets the rest of its grace window to catch
    # up before it's eligible for drain. Without this, a worker that registers (first heartbeat)
    # before a stale/lagging version tag propagates gets immediately drained and destroyed, its
    # replacement repeats the same race, and the pool churns forever instead of settling -- this is
    # the bug the debug logging above was added to confirm.
    # STRICTLY older than this reconciler's own version, never merely "different" -- confirmed in
    # production 2026-09-30: a deploy that took 9 minutes to swap left the OLD (0.1.56) container's
    # scheduler alive and reconciling well past its own 5-minute startup hold-off, and the old
    # code's `!= __version__` check made it treat every worker running the NEW, already-deployed
    # 0.1.57 image as "outdated" simply because 0.1.57 != 0.1.56 -- there is no way for a plain
    # inequality to know which side is actually stale. It then endlessly reprovisioned replacements
    # (which booted running the new 0.1.57 image, since that is what the image build actually
    # produces) and immediately reclassified each one as outdated too, forever, for as long as the
    # old process survived -- explaining the unbounded managed-count growth (13 -> 19+) we watched
    # live. Comparing version TUPLES and only ever calling a worker outdated when its version is
    # older than __version__ makes the old reconciler correctly see the new workers as current
    # (nothing to replace) while the new reconciler still correctly retires any genuinely old one --
    # breaking the war regardless of how long the two processes actually overlap for.
    __version_tuple = _version_tuple(__version__)
    recently_provisioned = _recently_provisioned_names(db, cfg["prefix"])
    outdated = [
        w for w in live_workers
        if w.status != "draining" and w.version and _version_tuple(w.version) < __version_tuple
        and w.container_name not in recently_provisioned
    ]
    draining = [w for w in live_workers if w.status == "draining"]

    if outdated:
        log.info(
            "reconcile_agent_workers[%s]: outdated=%s (each: worker_version older than reconciler_version=%s) "
            "provisioning_events_last_%ss=%s",
            pool, [(w.container_name, w.version) for w in outdated], __version__,
            AGENT_WORKER_PROVISION_GRACE_SECONDS, sorted(recently_provisioned),
        )

    if outdated and live >= desired:
        # Not-outdated, i.e. version >= this reconciler's own -- not `== __version__`, so a worker
        # already running something newer than this process (the other side of the same race this
        # whole fix is for) still counts as "good enough" rather than being forced to match exactly.
        current_count = sum(1 for w in live_workers if w.version and _version_tuple(w.version) >= __version_tuple)
        if current_count < desired:
            log.info(
                "reconcile_agent_workers[%s]: current_count=%s < desired=%s -> provisioning replacement(s) "
                "instead of draining outdated=%s yet",
                pool, current_count, desired, [w.container_name for w in outdated],
            )
            return _provision(db, s, pool, cfg, managed, to_add=min(desired - current_count, AGENT_WORKER_MAX_PROVISION_PER_TICK))
        # Enough current-version workers are up — start (or continue) retiring the oldest outdated one.
        # Numeric-aware key (see _worker_sort_key): plain string min() would treat '-10' as
        # "earlier" than '-2' and pick the wrong victim, same bug as the destroy branch below.
        victim = min(outdated, key=lambda w: _worker_sort_key(w.container_name, prefix))
        log.info(
            "reconcile_agent_workers[%s]: draining victim=%s (version=%s, last_heartbeat=%s) "
            "because current_count=%s >= desired=%s",
            pool, victim.container_name, victim.version,
            victim.last_heartbeat.isoformat() if victim.last_heartbeat else None,
            current_count, desired,
        )
        drain_worker(db, victim.container_name, cfg["queues"])
        emit(db, "worker.draining", ws_id=None, actor=("system", None),
             payload={"container_name": victim.container_name, "pool": pool})
        return {"ok": True, "live": live, "desired": desired, "action": "drain", "container_name": victim.container_name}

    # A previously-draining worker becomes destroyable once idle, regardless of the count branches
    # below — this runs every tick so a worker that finishes its in-flight job gets torn down
    # promptly rather than waiting for the next live/desired mismatch.
    #
    # destroy-worker.sh runs synchronously over SSH (stop+rm, then returns) — by the time
    # trigger_jenkins_build reports ok, the container is already gone. The AgentWorker row must be
    # deleted right here: nothing else ever removes it, and leaving it behind (even as
    # "draining") means it keeps winning idle_draining[0] forever, re-triggering a no-op destroy
    # against an already-gone container on every single tick while every other drained worker
    # behind it in the list never gets a turn. (This is exactly what happened to worker #1 /
    # sandbox-1 across three version bumps -- see incident notes.)
    idle_draining = [w for w in draining if _worker_is_idle(w)]
    if idle_draining:
        victim = idle_draining[0]
        log.info(
            "reconcile_agent_workers[%s]: destroying idle_draining victim=%s (of %s draining total: %s)",
            pool, victim.container_name, len(draining), [w.container_name for w in draining],
        )
        result = trigger_jenkins_build(db, s.jenkins_destroy_job, {"WORKER_NAME": victim.container_name})
        if not result.get("ok"):
            log.warning("reconcile_agent_workers[%s]: destroy trigger failed for draining %s: %s",
                        pool, victim.container_name, result.get("reason"))
            return {"ok": True, "live": live, "desired": desired, "action": "destroy_drained_failed",
                    "container_name": victim.container_name}
        db.delete(victim)
        emit(db, "worker.destroying", ws_id=None, actor=("system", None),
             payload={"container_name": victim.container_name, "pool": pool})
        return {"ok": True, "live": live, "desired": desired, "action": "destroy_drained", "container_name": victim.container_name}

    if live == desired:
        return {"ok": True, "live": live, "desired": desired, "action": "none"}

    if live < desired:
        # DEBUG (investigating unexplained pool churn -- 2026-09-30): bumped to WARNING and paired
        # with the staleness_detail log above -- if `live` undercounts because a genuinely healthy
        # worker's row got flipped stale for one tick (heartbeat landed a hair over the 90s cutoff,
        # clock skew, a slow DB write), this line fires immediately after staleness_detail shows
        # exactly which row(s) were marked stale and by how much, on the SAME tick, so the two log
        # lines together show the full "why did we decide to provision" chain.
        log.warning(
            "reconcile_agent_workers[%s]: live=%s < desired=%s -> provisioning "
            "(stale_workers_this_tick=%s)",
            pool, live, desired, [w.container_name for w in stale_workers],
        )
        return _provision(db, s, pool, cfg, managed, to_add=min(desired - live, AGENT_WORKER_MAX_PROVISION_PER_TICK))

    # live > desired, no version drift: destroy the newest-named non-draining workers first, never
    # worker #1 (excluded by prefix match). Same as the idle_draining branch above: the row must
    # be deleted once the (synchronous) destroy trigger succeeds, or it lingers and gets
    # re-selected forever.
    #
    # `managed` is now numerically sorted (see _worker_sort_key), so reversed(managed) is genuinely
    # newest-first -- under the old plain-string sort, '-10' preceded '-2' alphabetically, so a
    # long-stale double-digit-named zombie row (never destroyed, since it's excluded from `live`
    # by staleness but still occupies a `managed` slot) could sit in front of any real, freshly-
    # heartbeated worker in the reversed list forever, meaning the FRESH worker got chosen as the
    # destroy victim every single tick while the zombie was never even a candidate for removal --
    # this is the exact shape confirmed in production 2026-09-30 for mainforte-agent-worker-sandbox-10.
    #
    # Exclude workers still inside their provisioning grace window: a worker that just heartbeated
    # for the first time (bumping live above desired transiently) shouldn't be torn down before it
    # ever gets used, only to have the reconciler provision a replacement for it next tick.
    candidates = [w for w in reversed(managed) if w.status != "draining" and w.container_name not in recently_provisioned]
    to_remove = min(live - desired, AGENT_WORKER_MAX_PROVISION_PER_TICK)
    victims = candidates[:to_remove]
    log.info(
        "reconcile_agent_workers[%s]: live=%s > desired=%s -> destroying victims=%s (candidates were %s)",
        pool, live, desired, [w.container_name for w in victims], [w.container_name for w in candidates],
    )
    n = 0
    for w in victims:
        result = trigger_jenkins_build(db, s.jenkins_destroy_job, {"WORKER_NAME": w.container_name})
        if not result.get("ok"):
            log.warning("reconcile_agent_workers[%s]: destroy trigger failed for %s: %s", pool, w.container_name, result.get("reason"))
            continue
        db.delete(w)
        emit(db, "worker.destroying", ws_id=None, actor=("system", None),
             payload={"container_name": w.container_name, "pool": pool})
        n += 1
    return {"ok": True, "live": live, "desired": desired, "action": "destroy", "triggered": n}


AGENT_WORKER_PROVISION_GRACE_SECONDS = 300  # deploy-worker.sh's two sequential `docker compose build`
# calls plus container start comfortably fit inside this; reconcile_agent_workers ticks every 60s,
# so without this a name with no AgentWorker row yet (build still running, or heartbeat not landed)
# looks identical to "never provisioned" and gets re-triggered on every single tick -- Jenkins queues
# a fresh deploy-worker.sh run, which docker stop/rm's whatever the PREVIOUS run just started,
# forever outrunning any container's ability to boot and heartbeat before it's torn down again.


def _recently_provisioned_names(db, prefix: str) -> set[str]:
    cutoff = utcnow() - timedelta(seconds=AGENT_WORKER_PROVISION_GRACE_SECONDS)
    rows = (
        db.query(Event.payload)
        .filter(Event.type == "worker.provisioning", Event.ts >= cutoff)
        .all()
    )
    return {
        payload["container_name"]
        for (payload,) in rows
        if payload.get("container_name", "").startswith(prefix)
    }


def _provision(db, s, pool: str, cfg: dict, managed: list, to_add: int) -> dict:
    from mainforte.jenkins_ssh import trigger_jenkins_build

    prefix = cfg["prefix"]
    recently_provisioned = _recently_provisioned_names(db, prefix)
    used = {w.container_name for w in managed} | recently_provisioned
    # DEBUG (investigating unexplained pool churn -- 2026-09-30): every call into _provision, with
    # exactly which names it considered already-used and how many it's about to trigger. If a new
    # AgentWorker row shows up in worker_heartbeat's own new-row log (above) with no corresponding
    # "about_to_trigger" name here in the prior ~2 reconcile ticks, that container was not created
    # by this function -- ruling the reconciler entirely out as the source.
    log.warning(
        "reconcile_agent_workers[%s]: _provision called to_add=%s managed=%s recently_provisioned=%s",
        pool, to_add, [w.container_name for w in managed], sorted(recently_provisioned),
    )
    n = 0
    idx = 1
    while n < to_add:
        name = f"{prefix}{idx}"
        idx += 1
        if name in used:
            continue
        log.warning("reconcile_agent_workers[%s]: about_to_trigger provision name=%s", pool, name)
        params = {"WORKER_NAME": name}
        if s.worker_api_url:
            params["API_URL"] = s.worker_api_url
        if cfg["queues"]:
            params["CELERY_QUEUES"] = cfg["queues"]
        result = trigger_jenkins_build(db, s.jenkins_provision_job, params)
        if not result.get("ok"):
            log.warning("reconcile_agent_workers[%s]: provision trigger failed for %s: %s", pool, name, result.get("reason"))
            break
        emit(db, "worker.provisioning", ws_id=None, actor=("system", None),
             payload={"container_name": name, "pool": pool})
        n += 1
    return {"ok": True, "live": len(managed), "action": "provision", "triggered": n}


AGENT_WORKER_RECONCILE_LOCK_KEY = 0x6D61696E666F7274  # arbitrary fixed int64 ("mainfort" in hex-ish), namespaced to this one lock


@celery.task(name="mainforte.tasks.system.reconcile_agent_workers")
def reconcile_agent_workers() -> dict:
    """Converges each pool's live AgentWorker count to its admin-set desired count via Jenkins
    provision/destroy jobs over SSH-through-bastion (PLAN.md §1.8). Scoped ONLY to rows whose
    container_name carries this reconciler's own per-pool naming convention (AGENT_WORKER_POOLS) —
    the only names it ever assigns via its own Jenkins-triggered deploy calls. Worker #1 (backbone's
    fixed worker, self-registered by `worker_heartbeat` under an arbitrary
    MAINFORTE_WORKER_ID/hostname-derived name) is excluded by construction, never by fragile "is
    this worker #1" detection.

    Guarded by a Postgres advisory lock, transaction-scoped (pg_try_advisory_xact_lock): it
    auto-releases on this db_session's own commit/rollback/close, so a crash between acquire and
    an explicit unlock can never leak the lock onto a pooled connection for some later, unrelated
    task to inherit (get_engine() pools connections; a session-scoped lock plus db.close() returning
    the raw connection to the pool would do exactly that). The lock only needs to cover the read-
    decide-act sequence for THIS tick, which is exactly one transaction's lifetime here. This exists
    because during a rolling deploy, backbone's zero-downtime swap keeps the OLD app
    container's in-process scheduler (main.py's lifespan) alive and ticking for as long as the NEW
    container takes to become healthy -- confirmed in production 2026-09-30: `worker.provisioning`
    events for full/sandbox workers 2 through 13 were emitted continuously from 13:00-13:12, all
    while a NEW app container (mainforte-app-22065, started 13:08:43) was simultaneously already
    destroying workers down to desired=1. Both processes' schedulers were reconciling the SAME
    pools against the SAME desired count at the SAME time, so the old one kept provisioning
    replacements for workers the new one had already destroyed (or vice versa) -- neither one's
    view of `managed`/`live` ever accounted for the other's in-flight decision, because both read
    then acted within their own separate `with db_session()` block with no coordination at all.
    Skips (does not block) when the lock is already held, since this task recurs every 60s anyway
    -- a held lock almost always means the other holder's own tick is still finishing, and next
    tick will just try again.

    Fails soft (never raises) when Jenkins/bastion settings are unset, matching jenkins_ssh's own
    not_configured convention -- this task runs on every beat tick regardless of whether the
    reconciler has been set up for this environment yet."""
    from sqlalchemy import text

    from mainforte.db_settings import get_bastion_jenkins_config
    from mainforte.jenkins_ssh import _is_configured

    with db_session() as db:
        got_lock = db.execute(
            text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": AGENT_WORKER_RECONCILE_LOCK_KEY}
        ).scalar()
        if not got_lock:
            log.info("reconcile_agent_workers: skipped tick, another process already holds the reconcile lock")
            return {"ok": False, "reason": "lock_held_elsewhere"}
        s = get_bastion_jenkins_config(db)
        if not _is_configured(s):
            return {"ok": False, "reason": "not_configured"}
        return {pool: _reconcile_pool(db, s, pool, cfg) for pool, cfg in AGENT_WORKER_POOLS.items()}


@celery.task(name="mainforte.tasks.system.refresh_widget")
def refresh_widget_task(*, widget_id: str) -> None:
    """Re-runs `refresh_spec`'s tool to get fresh data, rewrites the widget's data.json (bumping
    version), and emits `widget.updated`. `refresh_spec` shape: {"tool": <name in tools.catalog.TOOLS>,
    "input": {...}, "due": {...}} — `due` is interpreted here (e.g. a next-run timestamp updated
    after each successful refresh) so this task, not the sweep, owns cadence."""
    from mainforte.tools.catalog import TOOLS
    from mainforte.widgets import refresh_widget as _refresh

    with db_session() as db:
        widget = db.get(Widget, widget_id)
        if not widget or widget.status != "active" or not widget.refresh_spec:
            return
        spec = widget.refresh_spec
        tool = TOOLS.get(spec.get("tool", ""))
        if tool is None or tool.sandboxed:
            log.warning("widget %s refresh_spec names unusable tool %r", widget_id, spec.get("tool"))
            return
        try:
            data = tool.handler(**spec.get("input", {}))
        except Exception:
            log.exception("widget %s refresh failed", widget_id)
            return
        _refresh(widget, data if isinstance(data, dict) else {"result": data})
        emit(db, "widget.updated", ws_id=widget.ws_id, actor=("system", None), correlation_id=None,
             payload={"widget_id": widget.id, "version": widget.version})
