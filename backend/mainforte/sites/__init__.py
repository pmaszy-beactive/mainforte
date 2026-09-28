"""Sites: chat-built, live-editable, publishable business web apps (see PLAN.md's Sites section,
`db/models.py`'s `Site` docstring). A `Site` is a real provisioned container running a full
Node.js app — not a static bundle like `widgets.py`'s `Widget`.

- `service.py` — CRUD for `Site` rows, plus the plain-language status the frontend/persona read
  instead of raw `status`/`last_error`.
- `provisioning.py` — triggers the mainforte-owned Jenkins provision/destroy jobs and handles the
  Jenkins job's callback into mainforte.
- `container_agent.py` — reaches a *specific, already-running* site container via a local `docker
  exec` (the calling Celery worker lives on the same backbone deploy host as the site containers —
  see that module's docstring for the single-host assumption this relies on), for live file edits.
  Deliberately NOT built on `tasks/work.py`'s
  `run_tool`/`sandbox.get_sandbox()`: that machinery creates a fresh throwaway workspace (local
  dir or a brand-new container) per tool call, which is the right shape for isolating one LLM
  `bash` call but the wrong shape for repeatedly editing files inside one long-lived, externally
  provisioned site container addressed by `Site.container_name`.
- `routes.py` — the REST API (create/list/get a site, publish, the Jenkins callback, the preview
  proxy).

Every user-facing surface in this package must never serialize `Site.last_error` or any raw
infra detail (container names, ports, Jenkins job names, file paths) — see `service.py`'s
`site_out`/`plain_status`.
"""
from __future__ import annotations
