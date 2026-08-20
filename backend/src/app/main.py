"""
FastAPI application entrypoint — mstr-tableau-migrator.

Ref: spec/architecture.md §3.1, §3.4
Deployment: uvicorn app.main:app --host 0.0.0.0 --port 8000
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.db.session import init_db, SessionLocal
from app.models.audit import BatchedAuditLogger

# ── Logging ──────────────────────────────────────────────────────

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("mstr-tableau-migrator")

# ── Global audit logger instance (ADR-020) ───────────────────────

audit_logger = BatchedAuditLogger(
    session_factory=SessionLocal,
    batch_size=settings.audit_batch_size,
    flush_interval=settings.audit_flush_interval_s,
)


# ── Application lifecycle ────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: init DB + start audit flusher. Shutdown: flush remaining audit entries."""
    logger.info("Initializing database...")
    init_db()
    logger.info("Database initialized.")

    logger.info("Starting batched audit logger...")
    await audit_logger.start()

    yield

    logger.info("Shutting down audit logger...")
    await audit_logger.stop()
    logger.info("Shutdown complete.")


# ── FastAPI App ──────────────────────────────────────────────────

app = FastAPI(
    title="MSTR → Tableau Migration Platform",
    description="AI-augmented migration from MicroStrategy to Tableau Server",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — allow Next.js frontend during development
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Route Registration ───────────────────────────────────────────

from app.api.v1.jobs import router as jobs_router, list_cross_references          # noqa: E402
from app.api.v1.discovery import router as discovery_router  # noqa: E402
from app.api.v1.review import router as review_router        # noqa: E402
from app.api.v1.audit import router as audit_router          # noqa: E402

app.include_router(jobs_router, prefix="/api/v1")
app.include_router(discovery_router, prefix="/api/v1")
app.include_router(review_router, prefix="/api/v1")
app.include_router(audit_router, prefix="/api/v1")
app.add_api_route("/api/v1/cross-reference", list_cross_references, methods=["GET"], tags=["cross-reference"])


# ── Health Check ─────────────────────────────────────────────────

@app.get("/health", tags=["health"])
async def health_check():
    """Health check endpoint for monitoring."""
    return {
        "status": "healthy",
        "service": "mstr-tableau-migrator",
        "version": "0.1.0",
    }


@app.get("/api/v1/status", tags=["health"])
async def api_status():
    """API status with configuration summary."""
    return {
        "status": "operational",
        "database": settings.database_url,
        "template_version": settings.template_version,
        "mstr_configured": bool(settings.mstr_base_url and settings.mstr_username),
        "tableau_configured": bool(settings.tableau_server_url),
    }
