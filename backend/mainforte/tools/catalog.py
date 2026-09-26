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


def _now(**_kwargs: Any) -> dict[str, str]:
    return {"utc": datetime.now(UTC).isoformat()}


_register(Tool(
    name="now",
    description="Get the current date and time (UTC, ISO 8601).",
    input_schema={"type": "object", "properties": {}},
    handler=_now,
    sandboxed=False,
))
