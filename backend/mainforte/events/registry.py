"""Handler registry. `@on("type")` registers a function; `dispatch` runs them.

Handlers run as Celery tasks (see mainforte.tasks.events) so they can live on any worker.
Glob patterns are allowed: on("task.*"), on("*").
"""
from __future__ import annotations

import fnmatch
import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

Handler = Callable[[dict[str, Any]], Any]


@dataclass
class Registration:
    pattern: str
    fn: Handler
    queue: str = "system"
    sync: bool = False  # sync handlers run in-process at emit time (metrics only; must be cheap + safe)
    name: str = field(default="")

    def __post_init__(self) -> None:
        self.name = self.name or f"{self.fn.__module__}.{self.fn.__qualname__}"


_REGISTRY: dict[str, list[Registration]] = defaultdict(list)


def on(pattern: str, *, queue: str = "system", sync: bool = False) -> Callable[[Handler], Handler]:
    def deco(fn: Handler) -> Handler:
        _REGISTRY[pattern].append(Registration(pattern=pattern, fn=fn, queue=queue, sync=sync))
        return fn
    return deco


def handlers_for(event_type: str) -> list[Registration]:
    out: list[Registration] = []
    for pattern, regs in _REGISTRY.items():
        if pattern == event_type or fnmatch.fnmatchcase(event_type, pattern):
            out.extend(regs)
    return out


def all_registrations() -> list[Registration]:
    return [r for regs in _REGISTRY.values() for r in regs]


def resolve(name: str) -> Handler | None:
    for r in all_registrations():
        if r.name == name:
            return r.fn
    return None


def run_sync_handlers(event: dict[str, Any]) -> None:
    for reg in handlers_for(event["type"]):
        if reg.sync:
            try:
                reg.fn(event)
            except Exception:  # never let a metrics hook break an emit
                log.exception("sync handler %s failed", reg.name)
