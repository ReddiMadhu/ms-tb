"""
Audit log API routes.

Ref: spec/api.md §10, spec/database.md §2.7
ADR-010: Full append-only audit trail
ADR-020: Batched writes to prevent lock convoys
"""

from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.v1.schemas import AuditListResponse, AuditEventResponse
from app.db.session import get_db
from app.models.audit import AuditLog

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=AuditListResponse)
async def list_audit_events(
    job_id: Optional[str] = None,
    event_type: Optional[str] = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """GET /audit — Retrieve immutable audit trail events."""
    query = db.query(AuditLog)

    if job_id:
        query = query.filter(AuditLog.job_id == job_id)
    if event_type and event_type != "all":
        query = query.filter(AuditLog.event_type == event_type)

    total = query.count()
    events = query.order_by(AuditLog.timestamp.desc(), AuditLog.id.desc()).offset(offset).limit(limit).all()

    return AuditListResponse(
        events=[AuditEventResponse.model_validate(e) for e in events],
        total=total,
    )
