"""Chat mechanics, hardened.

- Posting is idempotent on (workspace, client_msg_id): a retried POST returns the original event.
- Attachments are uploaded first (multipart), stored under the user's home, and referenced by id/key.
- Replies arrive on the event stream; the client reconciles by event id, not by request/response.
"""
from __future__ import annotations

import mimetypes

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from mainforte.auth.deps import Identity, current_identity, require_membership
from mainforte.chat.attachments import extract_text
from mainforte.db.base import utcnow
from mainforte.db.models import ClientMessage, ComposerDraft, MemoryChunk, Upload
from mainforte.db.session import get_db
from mainforte.events import emit
from mainforte.ids import new_id
from mainforte.storage import get_storage, upload_key

router = APIRouter(prefix="/api/workspaces/{workspace_id}", tags=["chat"])

MAX_UPLOAD = 25 * 1024 * 1024
ALLOWED_PREFIXES = ("image/", "text/", "application/pdf", "application/json", "text/csv",
                    "application/vnd.openxmlformats-officedocument", "application/zip",
                    "application/msword", "application/vnd.ms-excel", "application/vnd.ms-powerpoint")


class AttachmentRef(BaseModel):
    id: str
    name: str | None = None
    content_type: str | None = None
    size: int | None = None


class MessageIn(BaseModel):
    client_msg_id: str = Field(min_length=8, max_length=64)
    thread_id: str | None = None
    text: str = Field(default="", max_length=20_000)
    attachments: list[AttachmentRef] = []


class FeedbackIn(BaseModel):
    event_id: str
    kind: str = Field(pattern="^(not_important|up|down)$")
    note: str | None = None


class CancelIn(BaseModel):
    thread_id: str | None = None
    correlation_id: str | None = None


class DraftIn(BaseModel):
    text: str = Field(default="", max_length=20_000)


def _upload_out(u: Upload) -> dict:
    return {"id": u.id, "key": u.key, "name": u.name, "content_type": u.content_type, "size": u.size,
            "url": f"/api/workspaces/{u.ws_id}/uploads/{u.id}"}


@router.post("/uploads", status_code=201)
async def upload(workspace_id: str, file: UploadFile = File(...), ident: Identity = Depends(current_identity),
                 db: Session = Depends(get_db)):
    ws = require_membership(workspace_id, ident, db)
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "max 25MB")
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "empty file")
    ctype = file.content_type or mimetypes.guess_type(file.filename or "")[0] or "application/octet-stream"
    if not ctype.startswith(ALLOWED_PREFIXES):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, f"unsupported type {ctype}")
    uid = new_id()
    key = upload_key(ident.user.id, uid, file.filename or "file")
    # get_storage().put() is a blocking network call (BackboneS3's sync httpx client); run it off
    # the event loop so one large upload's S3 PUT doesn't stall every other concurrent request
    # this worker process is handling (ticket T02791 -- "stuck at 100%" is consistent with a
    # second request queued behind a blocked event loop, not just this upload's own latency).
    stored = await run_in_threadpool(get_storage().put, key, data, ctype)
    extracted = await run_in_threadpool(extract_text, content_type=ctype, data=data)
    now = utcnow()
    up = Upload(id=uid, ws_id=ws.id, user_id=ident.user.id, key=key, name=file.filename or "file",
                content_type=ctype, size=stored.size, sha256=stored.sha256, extracted_text=extracted,
                created_at=now)
    db.add(up)
    if extracted:
        db.add(MemoryChunk(ws_id=ws.id, source_type="upload", source_id=uid, text=extracted, occurred_at=now))
    emit(db, "chat.attachment.uploaded", ws_id=ws.id, user_id=ident.user.id, actor=("user", ident.user.id),
         payload={"upload_id": uid, "name": up.name, "content_type": ctype, "size": stored.size})
    return _upload_out(up)


@router.get("/uploads/{upload_id}")
def get_upload(workspace_id: str, upload_id: str, ident: Identity = Depends(current_identity),
               db: Session = Depends(get_db)):
    ws = require_membership(workspace_id, ident, db)
    up = db.get(Upload, upload_id)
    if not up or up.ws_id != ws.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
    data = get_storage().get(up.key)
    if data is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "object missing")
    return Response(content=data, media_type=up.content_type,
                    headers={"Cache-Control": "private, max-age=3600", "Content-Disposition": f'inline; filename="{up.name}"'})


@router.post("/chat", status_code=201)
def post_message(workspace_id: str, body: MessageIn, ident: Identity = Depends(current_identity),
                 db: Session = Depends(get_db)):
    ws = require_membership(workspace_id, ident, db)
    if not body.text.strip() and not body.attachments:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "empty message")

    # idempotency: same client_msg_id → same event
    dup = db.get(ClientMessage, (ws.id, body.client_msg_id))
    if dup:
        return {"event_id": dup.event_id, "thread_id": dup.thread_id, "duplicate": True}

    # resolve attachments (must exist and belong to this workspace)
    atts: list[dict] = []
    for a in body.attachments:
        up = db.get(Upload, a.id)
        if not up or up.ws_id != ws.id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"unknown attachment {a.id}")
        atts.append(_upload_out(up))

    thread_id = body.thread_id
    if not thread_id:
        thread_id = new_id()
        emit(db, "chat.thread.created", ws_id=ws.id, user_id=ident.user.id, actor=("user", ident.user.id),
             payload={"thread_id": thread_id, "kind": "global"})
    ev = emit(db, "chat.message.created", ws_id=ws.id, user_id=ident.user.id, actor=("user", ident.user.id),
              correlation_id=thread_id,
              payload={"thread_id": thread_id, "text": body.text, "attachments": atts, "client_msg_id": body.client_msg_id})
    db.add(ClientMessage(ws_id=ws.id, client_msg_id=body.client_msg_id, event_id=ev["id"], thread_id=thread_id))
    return {"event_id": ev["id"], "thread_id": thread_id, "duplicate": False}


@router.post("/chat/feedback", status_code=201)
def feedback(workspace_id: str, body: FeedbackIn, ident: Identity = Depends(current_identity), db: Session = Depends(get_db)):
    ws = require_membership(workspace_id, ident, db)
    ev = emit(db, "chat.message.feedback", ws_id=ws.id, user_id=ident.user.id, actor=("user", ident.user.id),
              causation_id=body.event_id, payload={"kind": body.kind, "note": body.note})
    return {"event_id": ev["id"]}


@router.post("/chat/cancel", status_code=202)
def cancel(workspace_id: str, body: CancelIn, ident: Identity = Depends(current_identity), db: Session = Depends(get_db)):
    """Interrupt: personas replying in this thread (or the given correlation) stop at their next checkpoint.
    Workers check the cancel flag between LLM chunks / tool calls (P1)."""
    from mainforte.events.stream import sync_redis
    ws = require_membership(workspace_id, ident, db)
    target = body.correlation_id or body.thread_id or "*"
    sync_redis().setex(f"cancel:{ws.id}:{target}", 300, ident.user.id)
    ev = emit(db, "persona.reply.cancel_requested", ws_id=ws.id, user_id=ident.user.id, actor=("user", ident.user.id),
              correlation_id=body.correlation_id or body.thread_id, payload={"target": target})
    return {"event_id": ev["id"]}


@router.get("/drafts/{thread_id}")
def get_draft(workspace_id: str, thread_id: str, ident: Identity = Depends(current_identity), db: Session = Depends(get_db)):
    """Server-side backstop for the composer draft (frontend's own localStorage copy is the
    fast path; this is what lets a draft survive a device switch or cleared browser)."""
    ws = require_membership(workspace_id, ident, db)
    row = db.get(ComposerDraft, (ident.user.id, ws.id, thread_id))
    return {"text": row.text if row else "", "updated_at": row.updated_at if row else None}


@router.put("/drafts/{thread_id}")
def put_draft(workspace_id: str, thread_id: str, body: DraftIn, ident: Identity = Depends(current_identity),
             db: Session = Depends(get_db)):
    ws = require_membership(workspace_id, ident, db)
    if not body.text:
        db.query(ComposerDraft).filter_by(user_id=ident.user.id, ws_id=ws.id, thread_id=thread_id).delete()
        db.commit()
        return {"ok": True}

    now = utcnow()
    stmt = pg_insert(ComposerDraft).values(
        user_id=ident.user.id, ws_id=ws.id, thread_id=thread_id, text=body.text, updated_at=now,
    ).on_conflict_do_update(
        index_elements=["user_id", "ws_id", "thread_id"],
        set_={"text": body.text, "updated_at": now},
    )
    db.execute(stmt)
    db.commit()
    return {"ok": True}
