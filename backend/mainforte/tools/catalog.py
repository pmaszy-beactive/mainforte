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


def _create_widget(*, ws_id: str, owner_id: str, title: str, slug: str, html: str,
                    data: dict[str, Any] | None = None, refresh_spec: dict[str, Any] | None = None,
                    correlation_id: str | None = None, **_kwargs: Any) -> dict[str, Any]:
    """In-process handler for the `create_widget` tool: writes the bundle to storage and creates
    the Widget row. No sandbox needed — this only touches Storage/DB, never runs the persona's
    HTML (see PLAN.md P2 phase 7)."""
    from mainforte.config import get_settings
    from mainforte.db.session import db_session
    from mainforte.events import emit
    from mainforte.storage import safe_name
    from mainforte.widgets import create_widget as _create

    safe_slug = safe_name(slug)
    with db_session() as db:
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


def _car_search_template_id(db: Any, task_id: str) -> str:
    """A run row's own template id if it's a recurring clone (`result.schedule_template_id`,
    set by `fire_scheduled_task`), else the run's own id — covering the template's first,
    pre-recurrence run, where there is no prior clone to point back to yet."""
    from mainforte.db.models import Task

    task = db.get(Task, task_id)
    if task is not None and task.result and task.result.get("schedule_template_id"):
        return task.result["schedule_template_id"]
    return task_id


def _car_search_state_get(*, task_id: str, **_kwargs: Any) -> dict[str, Any]:
    """In-process handler for `car_search_state` (verb=get): accumulates `seen_urls`/`shortlist`
    from every prior run of this task's template, oldest first. Narrowly scoped to the car-search
    proof case — not a general state-store tool (see PLAN.md's car-search plan, Part 3): reuses
    `Task.result` JSONB exactly like `fire_scheduled_task` already does for `schedule_template_id`,
    rather than adding a new table."""
    from mainforte.db.models import Task
    from mainforte.db.session import db_session

    with db_session() as db:
        template_id = _car_search_template_id(db, task_id)
        rows = (
            db.query(Task.result)
            .filter(
                (Task.result["schedule_template_id"].astext == template_id)
                | (Task.id == template_id)
            )
            .order_by(Task.created_at.asc())
            .all()
        )
        seen_urls: list[str] = []
        shortlist: list[dict[str, Any]] = []
        for (result,) in rows:
            if not result:
                continue
            for url in result.get("seen_urls", []):
                if url not in seen_urls:
                    seen_urls.append(url)
            shortlist.extend(result.get("shortlist", []))
    return {"template_id": template_id, "seen_urls": seen_urls, "shortlist": shortlist}


def _car_search_state_put(*, task_id: str, **_kwargs: Any) -> dict[str, Any]:
    """In-process handler for `car_search_state` (verb=put): finds this run's own `web_search`
    stage result, excludes any listing URL already surfaced by an earlier run of this same
    template, and writes the genuinely-new URLs/shortlist into this run's own `Task.result` —
    without disturbing the `schedule_template_id` key `fire_scheduled_task` already wrote there.

    A stage's `input` is authored once, statically, at `create_task` time (`fire_scheduled_task`
    clones `plan` verbatim on every firing — see `_run_stage_tool`'s docstring), so this can't
    receive the prior `web_search` stage's own result as a literal argument the way a normal
    function call would. Instead it finds that stage's own `tool.ended` event — emitted by
    `_run_stage_tool` under the deterministic `f"{task.correlation_id}:{stage_index}"` correlation
    id — by scanning this task's own `plan` for the (single, expected) `web_search` stage, and pulls
    the citations straight out of that event's payload."""
    from mainforte.db.models import Event, Task
    from mainforte.db.session import db_session

    with db_session() as db:
        task = db.get(Task, task_id)
        if task is None:
            raise ValueError(f"no such task: {task_id}")
        prior = _car_search_state_get(task_id=task_id)
        already_seen = set(prior["seen_urls"])

        base_corr = task.correlation_id or task_id
        new_urls: list[str] = []
        shortlist: list[dict[str, Any]] = []
        for stage_index, stage in enumerate(task.plan or []):
            if stage.get("type") == "tool" and stage.get("tool") == "web_search":
                stage_corr = f"{base_corr}:{stage_index}"
                event = (
                    db.query(Event)
                    .filter(Event.type == "tool.ended", Event.correlation_id == stage_corr)
                    .order_by(Event.id.desc())
                    .first()
                )
                if event is not None:
                    search_result = event.payload.get("result") or {}
                    for citation in search_result.get("citations", []):
                        url = citation.get("url")
                        if url and url not in already_seen and url not in new_urls:
                            new_urls.append(url)
                            shortlist.append(citation)
        result = dict(task.result or {})
        result["seen_urls"] = new_urls
        result["shortlist"] = shortlist
        task.result = result
    return {"ok": True, "stored_urls": len(new_urls), "stored_shortlist": len(shortlist)}


def _car_search_state(*, verb: str, task_id: str, **_kwargs: Any) -> dict[str, Any]:
    if verb == "get":
        return _car_search_state_get(task_id=task_id)
    if verb == "put":
        return _car_search_state_put(task_id=task_id)
    raise ValueError(f"unknown verb {verb!r}, expected 'get' or 'put'")


_register(Tool(
    name="car_search_state",
    description=(
        "Read or write this recurring car-search task's cross-run memory: which listing URLs have "
        "already been surfaced to the user, and the accumulated shortlist. Call with verb='get' at "
        "the start of a run to load what prior runs already showed (empty on the first run); call "
        "with verb='put' at the end of a run to record newly-seen URLs and the updated shortlist so "
        "the next weekly run doesn't repeat them. Scoped to this one task's own recurrence — not a "
        "general-purpose state store."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "verb": {"type": "string", "enum": ["get", "put"]},
            "new_urls": {
                "type": "array", "items": {"type": "string"},
                "description": "put only: all listing URLs seen this run (merged with prior runs' on the next get)",
            },
            "shortlist": {
                "type": "array", "items": {"type": "object"},
                "description": "put only: this run's shortlist entries to append to the accumulated list",
            },
        },
        "required": ["verb"],
    },
    handler=_car_search_state,
    sandboxed=False,
))
