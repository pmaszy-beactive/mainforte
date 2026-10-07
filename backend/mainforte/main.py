from __future__ import annotations

import logging
import traceback
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from mainforte.admin.routes import router as admin_router
from mainforte.auth.routes import me_router
from mainforte.auth.routes import router as auth_router
from mainforte.billing.routes import router as billing_router
from mainforte.billing.webhooks import router as stripe_webhook_router
from mainforte.chat.routes import router as chat_router
from mainforte.config import get_settings
from mainforte.db.models import ApiError
from mainforte.db.session import db_session, get_engine
from mainforte.events import governor  # noqa: F401  (register governor handlers)
from mainforte.events import handlers  # noqa: F401  (register default handlers)
from mainforte.events import onboarding  # noqa: F401  (register onboarding handler)
from mainforte.events.stream import sync_redis
from mainforte.marketplace.routes import router as marketplace_router
from mainforte.personas.routes import router as personas_router
from mainforte.push import router as push_router
from mainforte.scheduler import scheduler
from mainforte.sites.routes import router as sites_router
from mainforte.tasks.routes import router as tasks_router

# The in-process scheduler (below) looks tasks up by name in `celery.tasks`, which Celery only
# populates by importing celery_app.py's `imports` tuple -- and that import only happens
# automatically inside a real `celery worker` process. This uvicorn process never runs one, so
# without importing these modules directly, `celery.tasks` stays empty here and every scheduled
# entry fails with "unknown task" (see PLAN.md's in-process-scheduler note above).
from mainforte.tasks import billing as _tasks_billing  # noqa: F401
from mainforte.tasks import healing as _tasks_healing  # noqa: F401
from mainforte.tasks import schedule as _tasks_schedule  # noqa: F401
from mainforte.tasks import system as _tasks_system  # noqa: F401
from mainforte.tasks import work as _tasks_work  # noqa: F401
from mainforte.widgets import router as widgets_router
from mainforte.workspaces.routes import router as ws_router
from mainforte.ws.routes import close_all_connections
from mainforte.ws.routes import router as socket_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("mainforte")
settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if settings.in_process_scheduler_enabled:
        scheduler.start()
    try:
        yield
    finally:
        if settings.in_process_scheduler_enabled:
            scheduler.stop()
        # Force-close every open websocket on shutdown. uvicorn/ASGI won't do this for you --
        # an idle-but-open socket (client asleep/backgrounded) otherwise just sits on
        # `receive_text()`, which is what let a deploy's connection-drain wait hang.
        await close_all_connections()


app = FastAPI(title="Mainforte", version="0.1.65", docs_url="/api/docs", openapi_url="/api/openapi.json",
              lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[settings.frontend_url, settings.app_url, "capacitor://localhost", "http://localhost"],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

for r in (auth_router, me_router, ws_router, chat_router, personas_router, admin_router, socket_router,
          tasks_router, widgets_router, billing_router, stripe_webhook_router, push_router, marketplace_router,
          sites_router):
    app.include_router(r)


@app.get("/health")
def health():
    out = {"status": "ok", "db": "ok", "redis": "ok"}
    try:
        with get_engine().connect() as c:
            c.execute(text("select 1"))
    except Exception as e:  # noqa: BLE001
        out["db"] = f"error: {e.__class__.__name__}"
    try:
        sync_redis().ping()
    except Exception as e:  # noqa: BLE001
        out["redis"] = f"error: {e.__class__.__name__}"
    code = 200 if out["db"] == "ok" else 503
    return JSONResponse(out, status_code=code)


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("unhandled error on %s", request.url.path)
    try:
        ident = getattr(request.state, "identity", None)
        with db_session() as db:
            db.add(ApiError(type=exc.__class__.__name__, message=str(exc)[:4000], path=str(request.url.path),
                            user_id=ident.user.id if ident else None, trace=traceback.format_exc()[-8000:]))
    except Exception:
        log.exception("could not record api error")
    return JSONResponse({"detail": "internal error"}, status_code=500)


# ---- static frontend (built by Dockerfile into /app/frontend/dist) ----
_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _dist.exists():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        f = _dist / full_path
        if full_path and f.is_file():
            return FileResponse(f)
        return FileResponse(_dist / "index.html")
