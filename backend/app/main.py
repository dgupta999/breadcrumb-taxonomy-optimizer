"""FastAPI entrypoint:  uvicorn app.main:app --reload --port 8000"""
from __future__ import annotations

import hmac
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api.routes import router
from .config import settings
from .db import init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if settings.embedded_worker:
        from .jobs import recover_stale_jobs
        from .worker import start_background, stop

        recover_stale_jobs()
        start_background()
        yield
        stop()
    else:
        yield


app = FastAPI(title="Breadcrumb Taxonomy Optimizer", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)


@app.middleware("http")
async def token_auth(request: Request, call_next):
    path = request.url.path
    if settings.api_token and path.startswith("/api") and path != "/api/health" and request.method != "OPTIONS":
        auth = request.headers.get("authorization", "")
        token = auth.removeprefix("Bearer ").strip()
        if not hmac.compare_digest(token.encode(), settings.api_token.encode()):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    return await call_next(request)


@app.get("/api/auth/check")
def auth_check():
    """Protected by the middleware: 200 means the team password is valid."""
    return {"ok": True}


@app.get("/api/health")
def health():
    return {"ok": True, "llm_available": settings.llm_available, "llm_model": settings.llm_model if settings.llm_available else None,
            "database": "postgres" if settings.database_url.startswith("postgres") else "sqlite",
            "auth_required": bool(settings.api_token)}


app.include_router(router)

# Serve the built frontend (frontend/dist) when present, so one process can host everything.
_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _dist.exists():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        f = _dist / full_path
        if full_path and f.is_file():
            return FileResponse(f)
        return FileResponse(_dist / "index.html")
