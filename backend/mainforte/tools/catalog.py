"""Tool registry (PLAN.md P2 item 9: port tool schemas from ActiveClaw, not code — see
../beactive-claw/TOOLS.md for the source shapes). `sandboxed=True` tools carry a `_not_implemented`
placeholder handler that is never actually called: `personas/router.py` special-cases
`tool.sandboxed` and dispatches to `mainforte.tasks.work.run_tool` instead, which runs the real
implementation out-of-process, dropped to the sandbox uid, via `mainforte.tools.sandbox_exec`. The
placeholder exists only so `Tool.handler` can stay non-optional. `now` is the one real in-process,
non-sandboxed handler.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[..., Any]
    sandboxed: bool = False


def _not_implemented(**_kwargs: Any) -> Any:
    raise NotImplementedError("tool handler not wired yet (see P2 plan)")


def to_anthropic_schema(tools: dict[str, Tool] | None = None) -> list[dict[str, Any]]:
    """Shape TOOLS (or a subset) for the Anthropic Messages API `tools` param."""
    items = tools if tools is not None else TOOLS
    return [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        for t in items.values()
    ]


TOOLS: dict[str, Tool] = {}


def _register(tool: Tool) -> Tool:
    TOOLS[tool.name] = tool
    return tool


_register(Tool(
    name="bash",
    description=(
        "Run a shell command in the workspace. Use for arbitrary file or system work that has no "
        "purpose-built tool. Prefer purpose-built tools when they exist."
    ),
    input_schema={
        "type": "object",
        "properties": {"command": {"type": "string", "description": "Shell command to run"}},
        "required": ["command"],
    },
    handler=_not_implemented,
    sandboxed=True,
))

_register(Tool(
    name="read_file",
    description="Read a file inside the workspace. Cannot escape the workspace root.",
    input_schema={
        "type": "object",
        "properties": {"path": {"type": "string", "description": "Path relative to the workspace root"}},
        "required": ["path"],
    },
    handler=_not_implemented,
    sandboxed=True,
))

_register(Tool(
    name="write_file",
    description="Write a file inside the workspace. Cannot escape the workspace root.",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path relative to the workspace root"},
            "content": {"type": "string"},
        },
        "required": ["path", "content"],
    },
    handler=_not_implemented,
    sandboxed=True,
))

_register(Tool(
    name="list_dir",
    description="Enumerate a directory in the workspace. Cheaper than `bash` for the same work.",
    input_schema={
        "type": "object",
        "properties": {"path": {"type": "string", "description": "Path relative to the workspace root"}},
        "required": ["path"],
    },
    handler=_not_implemented,
    sandboxed=True,
))

_register(Tool(
    name="grep",
    description="Search file contents in the workspace.",
    input_schema={
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Regex pattern to search for"},
            "path": {"type": "string", "description": "Path to search under, relative to workspace root"},
        },
        "required": ["pattern"],
    },
    handler=_not_implemented,
    sandboxed=True,
))

_register(Tool(
    name="glob",
    description="Match file paths in the workspace by glob pattern.",
    input_schema={
        "type": "object",
        "properties": {"pattern": {"type": "string", "description": "Glob pattern, e.g. **/*.py"}},
        "required": ["pattern"],
    },
    handler=_not_implemented,
    sandboxed=True,
))

_register(Tool(
    name="browser_navigate",
    description="Navigate a sandboxed browser to a URL and return the page title and final URL.",
    input_schema={
        "type": "object",
        "properties": {"url": {"type": "string", "description": "URL to navigate to"}},
        "required": ["url"],
    },
    handler=_not_implemented,
    sandboxed=True,
))

_register(Tool(
    name="browser_extract_text",
    description="Extract the visible text content of the current sandboxed-browser page.",
    input_schema={"type": "object", "properties": {}},
    handler=_not_implemented,
    sandboxed=True,
))

_register(Tool(
    name="web_search",
    description=(
        "Grounded web search (Gemini's native google_search tool): returns a synthesized answer "
        "plus source citations. Use this for anything that needs current, real-world information — "
        "prefer it over guessing, and follow up promising citations with browser_navigate/"
        "browser_extract_text when you need more than the snippet gives you."
    ),
    input_schema={
        "type": "object",
        "properties": {"query": {"type": "string", "description": "Search query"}},
        "required": ["query"],
    },
    handler=_not_implemented,
    sandboxed=True,
))

_register(Tool(
    name="gmail_send",
    description=(
        "Send an email from the user's own connected Gmail account (not the app's transactional "
        "sender) — use only when the user asked you to send mail as them, and only after they've "
        "connected Gmail in Settings."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "to": {"type": "string", "description": "Recipient email address"},
            "subject": {"type": "string"},
            "body": {"type": "string"},
        },
        "required": ["to", "subject", "body"],
    },
    handler=_not_implemented,
    sandboxed=True,
))

_register(Tool(
    name="calendar_list_events",
    description=(
        "List the user's upcoming events from their own connected Google Calendar — use only "
        "after they've connected Calendar in Settings."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "max_results": {"type": "integer", "description": "Max events to return (default 10)"},
        },
    },
    handler=_not_implemented,
    sandboxed=True,
))


def _now(**_kwargs: Any) -> dict[str, str]:
    return {"utc": datetime.now(UTC).isoformat()}


_register(Tool(
    name="now",
    description="Get the current date and time (UTC, ISO 8601).",
    input_schema={"type": "object", "properties": {}},
    handler=_now,
    sandboxed=False,
))


def _create_task(*, ws_id: str, title: str, plan: list[dict[str, Any]],
                  thread_id: str | None = None, persona_id: str | None = None,
                  correlation_id: str | None = None, schedule: dict[str, Any] | None = None,
                  **_kwargs: Any) -> dict[str, Any]:
    """In-process handler for the `create_task` tool: creates a `Task` row in `planned` status
    and requests human approval. Deliberately does NOT auto-approve — every task, however it was
    proposed, waits for a `POST .../approve` before `run_task_stage` ever runs (see Phase 5 of
    the P2 plan: task.planned -> task.approval.requested -> task.approved is a hard gate, not a
    default-on convenience). An optional `schedule` proposes recurrence up front (P4) -- it's stored
    on the row now but stays inert (`set_task_schedule` doesn't flip status to "scheduled" until
    approval; see the `/approve` route) since the same approval gate must apply to recurring work,
    not just its first run."""
    from mainforte.db.models import Task
    from mainforte.db.session import db_session
    from mainforte.events import emit
    from mainforte.ids import new_id

    task_id = new_id()
    corr = correlation_id or task_id
    with db_session() as db:
        task = Task(
            id=task_id, ws_id=ws_id, thread_id=thread_id, persona_id=persona_id,
            status="planned", plan=plan, current_stage=0, result=None, correlation_id=corr,
        )
        if schedule is not None:
            from mainforte.tasks.schedule import set_task_schedule

            set_task_schedule(db, task, schedule)
            task.status = "planned"  # set_task_schedule sets "scheduled"; approval gate still applies first
        db.add(task)
        db.flush()
        emit(db, "task.planned", ws_id=ws_id, actor=("persona", persona_id), correlation_id=corr,
             payload={"task_id": task_id, "title": title, "plan": plan, "thread_id": thread_id})
        emit(db, "task.approval.requested", ws_id=ws_id, actor=("system", None), correlation_id=corr,
             payload={"task_id": task_id, "title": title, "thread_id": thread_id})
    return {"task_id": task_id, "status": "planned", "stage_count": len(plan)}


_register(Tool(
    name="create_task",
    description=(
        "Propose a multi-stage task for human approval. Use this instead of `bash`/`browser_*` "
        "directly when the work needs several tool calls in sequence, may need to pause for human "
        "input partway through (e.g. a login code, a purchase confirmation), or should be visible "
        "to the user as a trackable unit of work rather than an inline reply. The task will NOT run "
        "until the user approves it. Each stage is either {\"type\": \"tool\", \"tool\": <name>, "
        "\"input\": {...}} or {\"type\": \"await_input\", \"prompt\": <string>} to pause for a human "
        "response before continuing."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Short human-readable summary of the task"},
            "plan": {
                "type": "array",
                "description": "Ordered list of stage specs",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": ["tool", "await_input"]},
                        "tool": {"type": "string", "description": "Tool name, required when type=tool"},
                        "input": {"type": "object", "description": "Arguments for the tool call"},
                        "prompt": {"type": "string", "description": "What to ask the human, when type=await_input"},
                    },
                    "required": ["type"],
                },
            },
            "schedule": {
                "type": "object",
                "description": (
                    "Optional recurrence to propose alongside this task, e.g. \"every morning\". "
                    "Surfaced to the human as part of the approval request; only takes effect once "
                    "approved, same as the task itself."
                ),
                "properties": {
                    "kind": {"type": "string", "enum": ["interval", "cron"]},
                    "interval_seconds": {"type": "integer", "description": "Required when kind=interval"},
                    "cron": {"type": "string", "description": "5-field cron string, required when kind=cron"},
                },
                "required": ["kind"],
            },
        },
        "required": ["title", "plan"],
    },
    handler=_create_task,
    sandboxed=False,
))


def _create_widget(*, ws_id: str, title: str, slug: str, html: str,
                    data: dict[str, Any] | None = None, refresh_spec: dict[str, Any] | None = None,
                    correlation_id: str | None = None, **_kwargs: Any) -> dict[str, Any]:
    """In-process handler for the `create_widget` tool: writes the bundle to storage and creates
    the Widget row. No sandbox needed — this only touches Storage/DB, never runs the persona's
    HTML (see PLAN.md P2 phase 7). `owner_id` isn't caller-supplied (the LLM has no user id to
    give, and personas/router.py only injects ws_id) — resolved here from Workspace.owner_id, the
    same collapse-to-one-user convention tasks/work.py's `_home_owner` already uses."""
    from mainforte.config import get_settings
    from mainforte.db.models import Workspace
    from mainforte.db.session import db_session
    from mainforte.events import emit
    from mainforte.storage import safe_name
    from mainforte.widgets import create_widget as _create

    safe_slug = safe_name(slug)
    with db_session() as db:
        ws = db.get(Workspace, ws_id)
        if ws is None:
            raise ValueError(f"workspace {ws_id!r} not found")
        owner_id = ws.owner_id
        widget = _create(db, ws_id=ws_id, owner_id=owner_id, title=title, slug=safe_slug,
                          html=html, data=data or {}, refresh_spec=refresh_spec)
        emit(db, "widget.created", ws_id=ws_id, actor=("persona", owner_id), correlation_id=correlation_id,
             payload={"widget_id": widget.id, "title": title, "slug": safe_slug, "token": widget.token})
        widget_id, token = widget.id, widget.token

    url = f"{get_settings().api_url}/w/{token}/"
    return {"widget_id": widget_id, "url": url, "token": token}


_register(Tool(
    name="create_widget",
    description=(
        "Publish a small HTML+data widget that the human can view at a stable URL and that shows "
        "up in their rail. Use this for a dashboard, chart, or summary the human should be able to "
        "revisit without asking again — not for one-off answers in chat. `html` should read its "
        "data from a sibling `data.json` (fetch('./data.json')) rather than inlining values, so a "
        "refresh can update the data without re-publishing the template. Pass `refresh_spec` only "
        "if the widget's data should be recomputed on a schedule."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Short human-readable title"},
            "slug": {"type": "string", "description": "URL-safe identifier, unique per user"},
            "html": {"type": "string", "description": "Full HTML document for index.html"},
            "data": {"type": "object", "description": "JSON data the HTML reads from data.json"},
            "refresh_spec": {
                "type": "object",
                "description": "Optional schedule/instructions for periodic refresh (shape owned by the refresh job)",
            },
        },
        "required": ["title", "slug", "html"],
    },
    handler=_create_widget,
    sandboxed=False,
))


def _watch_state_template_id(db: Any, task_id: str) -> str:
    """A run row's own template id if it's a recurring clone (`result.schedule_template_id`,
    set by `fire_scheduled_task`), else the run's own id — covering the template's first,
    pre-recurrence run, where there is no prior clone to point back to yet."""
    from mainforte.db.models import Task

    task = db.get(Task, task_id)
    if task is not None and task.result and task.result.get("schedule_template_id"):
        return task.result["schedule_template_id"]
    return task_id


def _watch_state_get(*, task_id: str, **_kwargs: Any) -> dict[str, Any]:
    """In-process handler for `watch_state` (verb=get): accumulates `seen_keys`/`data` from every
    prior run of this task's template, oldest first. Domain-agnostic generalization of the
    car-search proof case's `car_search_state` — same `Task.result` JSONB reuse
    (`fire_scheduled_task` already writes `schedule_template_id` there), just without any
    car/web-search-specific field shape."""
    from mainforte.db.models import Task
    from mainforte.db.session import db_session

    with db_session() as db:
        template_id = _watch_state_template_id(db, task_id)
        rows = (
            db.query(Task.result)
            .filter(
                (Task.result["schedule_template_id"].astext == template_id)
                | (Task.id == template_id)
            )
            .order_by(Task.created_at.asc())
            .all()
        )
        seen_keys: list[str] = []
        data: list[Any] = []
        for (result,) in rows:
            if not result:
                continue
            for key in result.get("seen_keys", []):
                if key not in seen_keys:
                    seen_keys.append(key)
            data.extend(result.get("data", []))
    return {"template_id": template_id, "seen_keys": seen_keys, "data": data}


def _watch_state_put(*, task_id: str, new_keys: list[str] | None = None,
                      data: list[Any] | None = None, **_kwargs: Any) -> dict[str, Any]:
    """In-process handler for `watch_state` (verb=put): excludes any key already surfaced by an
    earlier run of this same template, and writes the genuinely-new keys/data into this run's own
    `Task.result` — without disturbing the `schedule_template_id` key `fire_scheduled_task` already
    wrote there. Unlike `car_search_state`'s put, this takes `new_keys`/`data` directly as tool
    arguments rather than re-deriving them from a hardcoded `web_search` stage's event — the
    calling persona already knows what it found this run and what's genuinely new."""
    from mainforte.db.models import Task
    from mainforte.db.session import db_session

    with db_session() as db:
        task = db.get(Task, task_id)
        if task is None:
            raise ValueError(f"no such task: {task_id}")
        prior = _watch_state_get(task_id=task_id)
        already_seen = set(prior["seen_keys"])

        deduped_keys: list[str] = []
        for key in new_keys or []:
            if key not in already_seen and key not in deduped_keys:
                deduped_keys.append(key)

        result = dict(task.result or {})
        result["seen_keys"] = deduped_keys
        result["data"] = data or []
        task.result = result
    return {"ok": True, "stored_keys": len(deduped_keys), "stored_data": len(data or [])}


def _watch_state(*, verb: str, task_id: str, new_keys: list[str] | None = None,
                  data: list[Any] | None = None, **_kwargs: Any) -> dict[str, Any]:
    if verb == "get":
        return _watch_state_get(task_id=task_id)
    if verb == "put":
        return _watch_state_put(task_id=task_id, new_keys=new_keys, data=data)
    raise ValueError(f"unknown verb {verb!r}, expected 'get' or 'put'")


_register(Tool(
    name="watch_state",
    description=(
        "Read or write this recurring task's cross-run memory: which result keys (e.g. listing "
        "URLs, flight ids — whatever this watch is tracking) have already been surfaced to the "
        "user, and the accumulated result data. Call with verb='get' at the start of a run to "
        "load what prior runs already showed (empty on the first run); call with verb='put' at "
        "the end of a run, passing `new_keys` (all keys seen this run — already-seen ones are "
        "filtered out automatically) and `data` (this run's result data to keep), so the next "
        "scheduled run doesn't repeat them. Scoped to this one task's own recurrence — not a "
        "general-purpose state store shared across tasks."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "verb": {"type": "string", "enum": ["get", "put"]},
            "new_keys": {
                "type": "array", "items": {"type": "string"},
                "description": "put only: all result keys seen this run (merged with prior runs' on the next get)",
            },
            "data": {
                "type": "array", "items": {"type": "object"},
                "description": "put only: this run's result data to keep for the next get",
            },
        },
        "required": ["verb"],
    },
    handler=_watch_state,
    sandboxed=False,
))


# ---------------------------------------------------------------- sites (PLAN.md Sites section)
#
# These are sandboxed=False, in-process handlers — same category as _create_widget above — even
# though they run arbitrary-looking file I/O, because the isolation problem they solve is
# different from bash/read_file/etc.'s: those need protection from a single untrusted LLM-directed
# command running on *this* machine, so they're dispatched into a throwaway sandboxed workspace
# per call. These tools instead need to reach ONE specific, already-provisioned remote container
# (Site.container_name) over SSH through the bastion — an authorization/addressing concern, not a
# local-execution-isolation one. See sites/container_agent.py's docstring for the full rationale.


def _create_site(*, ws_id: str, name: str, brief: str, thread_id: str | None = None,
                  correlation_id: str | None = None, **_kwargs: Any) -> dict[str, Any]:
    """Creates the Site row and kicks off provisioning. owner_id resolved from Workspace.owner_id
    (same convention as _create_widget above) — the LLM has no user id to supply. Returns only the
    plain-language status shape (sites.service.site_out) — never raw status/container detail; see
    that module's docstring."""
    from mainforte.db.models import Workspace
    from mainforte.db.session import db_session
    from mainforte.events import emit
    from mainforte.sites import service as site_service
    from mainforte.sites.provisioning import trigger_provision

    with db_session() as db:
        ws = db.get(Workspace, ws_id)
        if ws is None:
            raise ValueError(f"workspace {ws_id!r} not found")
        site, api_key = site_service.create_site(
            db, ws_id=ws_id, owner_id=ws.owner_id, name=name, brief=brief, agent_thread_id=thread_id,
        )
        emit(db, "site.created", ws_id=ws_id, actor=("persona", None), correlation_id=correlation_id,
             payload={"site_id": site.id, "name": name, "slug": site.slug})
        trigger_provision(db, site=site, api_key=api_key, correlation_id=correlation_id)
        out = site_service.site_out(site)
    return out


_register(Tool(
    name="create_site",
    description=(
        "Start building a real, live web app for the user's business from a plain-language "
        "description. Use this the first time a user describes a business they want a site for. "
        "This kicks off provisioning in the background — it will not be ready instantly; tell the "
        "user you're setting things up, never mention containers, builds, or infrastructure."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "User-facing business/site name"},
            "brief": {"type": "string", "description": "The user's description of what the site should be/do"},
        },
        "required": ["name", "brief"],
    },
    handler=_create_site,
    sandboxed=False,
))


def _load_site(*, site_id: str, ws_id: str):
    from mainforte.db.models import Site

    from mainforte.db.session import db_session

    with db_session() as db:
        site = db.get(Site, site_id)
        if site is None or site.ws_id != ws_id:
            raise ValueError("site not found")
        db.expunge(site)
        return site


def _scratch_file_path(site_id: str, correlation_id: str, rel_path: str):
    """Resolves `rel_path` against this turn's local scratch checkout and rejects any escape from
    it. Mirrors container_agent.py's `_assert_safe_rel_path`, reimplemented here since this now
    guards local filesystem access rather than a remote `docker exec` path.

    Pulls the S3 master into scratch on first access within a turn (idempotent — pull_master wipes
    and redoes the scratch dir, so this is safe to call from every one of a turn's tool calls; it
    only actually hits S3 the first time since subsequent calls in the same turn find the dir
    already populated). This keeps the "pull once per turn" behavior self-contained in the tool
    handlers rather than requiring router.py's dispatch loop to know about Sites specifically
    before it ever sees a site tool call."""
    from mainforte.sites import source as site_source
    from mainforte.sites.container_agent import ContainerAgentError, _assert_safe_rel_path

    if not correlation_id:
        raise ContainerAgentError("site file tools require a correlation_id (turn scratch not available)")
    base = site_source._scratch_path(site_id, correlation_id)
    if not base.exists():
        site_source.pull_master(site_id, correlation_id)
    safe = _assert_safe_rel_path(rel_path) if rel_path not in (".", "") else "."
    return (base / safe) if safe != "." else base


def _read_site_file(*, site_id: str, path: str, ws_id: str, correlation_id: str | None = None,
                     **_kwargs: Any) -> dict[str, Any]:
    """Reads from the turn's local scratch checkout, not the live container — see
    sites/source.py's module docstring for why. _load_site is still called first purely to
    enforce ws_id scoping (a persona must never read a site outside its own workspace), even
    though the file bytes themselves come from local disk."""
    _load_site(site_id=site_id, ws_id=ws_id)
    fp = _scratch_file_path(site_id, correlation_id, path)
    if not fp.is_file():
        raise ValueError(f"no such file: {path!r}")
    return {"content": fp.read_text(errors="replace")[:200_000]}


_register(Tool(
    name="read_site_file",
    description="Read a file from a site's live workspace, relative to the app root. Use before "
                "editing to see current content.",
    input_schema={
        "type": "object",
        "properties": {
            "site_id": {"type": "string"},
            "path": {"type": "string", "description": "Path relative to the site's app root"},
        },
        "required": ["site_id", "path"],
    },
    handler=_read_site_file,
    sandboxed=False,
))


def _write_site_file(*, site_id: str, path: str, content: str, ws_id: str,
                      correlation_id: str | None = None, **_kwargs: Any) -> dict[str, Any]:
    """Writes into the turn's local scratch checkout — plain filesystem I/O, no docker exec. The
    change only reaches the running container (and S3) at turn end, via router.py's
    _commit_dirty_site_scratches, once validation (source.validate_scratch) passes; see
    sites/source.py's module docstring for the full per-turn flow."""
    from mainforte.db.session import db_session
    from mainforte.events import emit

    _load_site(site_id=site_id, ws_id=ws_id)
    fp = _scratch_file_path(site_id, correlation_id, path)
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(content)
    with db_session() as db:
        emit(db, "site.file.changed", ws_id=ws_id, actor=("persona", None), correlation_id=correlation_id,
             payload={"site_id": site_id, "path": path})
    return {"ok": True}


_register(Tool(
    name="write_site_file",
    description="Write (create or overwrite) a file in a site's live workspace. The site's dev "
                "server hot-reloads automatically — do not mention files, containers, or servers "
                "when describing this to the user; describe the visible product change instead.",
    input_schema={
        "type": "object",
        "properties": {
            "site_id": {"type": "string"},
            "path": {"type": "string", "description": "Path relative to the site's app root"},
            "content": {"type": "string", "description": "Full new file content"},
        },
        "required": ["site_id", "path", "content"],
    },
    handler=_write_site_file,
    sandboxed=False,
))


def _list_site_files(*, site_id: str, path: str = ".", ws_id: str, correlation_id: str | None = None,
                      **_kwargs: Any) -> dict[str, Any]:
    _load_site(site_id=site_id, ws_id=ws_id)
    dp = _scratch_file_path(site_id, correlation_id, path)
    if not dp.is_dir():
        raise ValueError(f"no such directory: {path!r}")
    entries = sorted(
        (p.name + "/" if p.is_dir() else p.name) for p in dp.iterdir() if not p.name.startswith(".")
    )
    return {"entries": entries}


_register(Tool(
    name="list_site_files",
    description="List files and directories in a site's live workspace, relative to the app root.",
    input_schema={
        "type": "object",
        "properties": {
            "site_id": {"type": "string"},
            "path": {"type": "string", "description": "Directory path relative to the app root; defaults to root"},
        },
        "required": ["site_id"],
    },
    handler=_list_site_files,
    sandboxed=False,
))


def _read_site_logs(*, site_id: str, ws_id: str, **_kwargs: Any) -> dict[str, Any]:
    from mainforte.db.session import db_session
    from mainforte.sites.container_agent import read_logs

    site = _load_site(site_id=site_id, ws_id=ws_id)
    with db_session() as db:
        return {"logs": read_logs(db, site)}


_register(Tool(
    name="read_site_logs",
    description="Read recent server logs from a site's running container — use to diagnose a "
                "problem before telling the user something is wrong; never quote raw log lines "
                "back to the user, translate the underlying issue into plain language instead.",
    input_schema={
        "type": "object",
        "properties": {"site_id": {"type": "string"}},
        "required": ["site_id"],
    },
    handler=_read_site_logs,
    sandboxed=False,
))
