"""Task approval/rejection and HITL input endpoints (P2 phase 5). Mirrors chat/routes.py's
pattern exactly: require_membership first, then an event emit, then (where the action starts or
resumes work) a Celery dispatch."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from mainforte.auth.deps import Identity, current_identity, require_membership
from mainforte.db.models import Task
from mainforte.db.session import get_db
from mainforte.events import emit
from mainforte.tasks.work import run_task_stage

router = APIRouter(prefix="/api/workspaces/{workspace_id}/tasks", tags=["tasks"])


class InputIn(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)


def _task_out(t: Task) -> dict:
    return {"id": t.id, "status": t.status, "plan": t.plan, "current_stage": t.current_stage,
            "thread_id": t.thread_id, "persona_id": t.persona_id, "result": t.result}


def _get_task(workspace_id: str, task_id: str, db: Session) -> Task:
    t = db.get(Task, task_id)
    if not t or t.ws_id != workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")
    return t


@router.get("/{task_id}")
def get_task(workspace_id: str, task_id: str, ident: Identity = Depends(current_identity),
             db: Session = Depends(get_db)):
    require_membership(workspace_id, ident, db)
    return _task_out(_get_task(workspace_id, task_id, db))


@router.post("/{task_id}/approve", status_code=202)
def approve_task(workspace_id: str, task_id: str, ident: Identity = Depends(current_identity),
                  db: Session = Depends(get_db)):
    ws = require_membership(workspace_id, ident, db)
    task = _get_task(workspace_id, task_id, db)
    if task.status != "planned":
        raise HTTPException(status.HTTP_409_CONFLICT, f"task is {task.status}, not planned")
    task.status = "approved"
    ev = emit(db, "task.approved", ws_id=ws.id, user_id=ident.user.id, actor=("user", ident.user.id),
              correlation_id=task.correlation_id, payload={"task_id": task_id, "thread_id": task.thread_id})
    db.commit()
    run_task_stage.delay(task_id=task_id, ws_id=ws.id)
    return {"event_id": ev["id"], "status": task.status}


@router.post("/{task_id}/reject", status_code=202)
def reject_task(workspace_id: str, task_id: str, ident: Identity = Depends(current_identity),
                 db: Session = Depends(get_db)):
    ws = require_membership(workspace_id, ident, db)
    task = _get_task(workspace_id, task_id, db)
    if task.status != "planned":
        raise HTTPException(status.HTTP_409_CONFLICT, f"task is {task.status}, not planned")
    task.status = "canceled"
    ev = emit(db, "task.rejected", ws_id=ws.id, user_id=ident.user.id, actor=("user", ident.user.id),
              correlation_id=task.correlation_id, payload={"task_id": task_id, "thread_id": task.thread_id})
    return {"event_id": ev["id"], "status": task.status}


@router.post("/{task_id}/input", status_code=202)
def submit_input(workspace_id: str, task_id: str, body: InputIn, ident: Identity = Depends(current_identity),
                  db: Session = Depends(get_db)):
    """Resumes a `blocked` task: records the human's answer against the current stage's own
    correlation_id (so the Governor can ground claims the *next* stage makes about having used
    this input), then re-dispatches the same stage index — the await_input stage itself doesn't
    re-run, current_stage already points past it once run_task_stage advances normally, matching
    the tool-stage advance semantics rather than a special-cased resume path."""
    ws = require_membership(workspace_id, ident, db)
    task = _get_task(workspace_id, task_id, db)
    if task.status != "blocked":
        raise HTTPException(status.HTTP_409_CONFLICT, f"task is {task.status}, not blocked")
    stage_corr = f"{task.correlation_id or task.id}:{task.current_stage}"
    ev = emit(db, "task.input.received", ws_id=ws.id, user_id=ident.user.id, actor=("user", ident.user.id),
              correlation_id=stage_corr, payload={"task_id": task_id, "stage_index": task.current_stage,
                                                    "thread_id": task.thread_id, "text": body.text})
    task.status = "approved"
    task.current_stage = task.current_stage + 1
    db.commit()
    run_task_stage.delay(task_id=task_id, ws_id=ws.id)
    return {"event_id": ev["id"], "status": task.status}
