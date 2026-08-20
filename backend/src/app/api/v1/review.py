"""
Review queue and validation API routes.

Ref: spec/api.md §4 — Review, §5 — Validation
ADR-033: Single-Expression Re-Validation Gate
ADR-034: Human Review Approval & Confidence Calibration
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.v1.schemas import (
    BlastRadiusResponse,
    ReviewApproveRequest,
    ReviewEditRequest,
    ReviewTaskListResponse,
    ReviewTaskResponse,
    ValidationCheckResponse,
    ValidationScorecardResponse,
)
from app.db.session import get_db
from app.models.job import Job
from app.models.objects import ReviewTask
from app.models.validation import ValidationCheck

router = APIRouter(tags=["review"])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Review Queue (api.md §4)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.get("/review", response_model=ReviewTaskListResponse)
async def list_review_tasks(
    job_id: Optional[str] = None,
    status: Optional[str] = None,
    severity: Optional[str] = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """GET /review — List review tasks with filtering."""
    query = db.query(ReviewTask)
    if job_id:
        query = query.filter(ReviewTask.job_id == job_id)
    if status:
        query = query.filter(ReviewTask.status == status)
    if severity:
        query = query.filter(ReviewTask.severity == severity)

    total = query.count()
    tasks = query.order_by(ReviewTask.created_at.desc()).offset(offset).limit(limit).all()

    return ReviewTaskListResponse(
        tasks=[ReviewTaskResponse.model_validate(t) for t in tasks],
        total=total,
    )


@router.get("/review/{task_id}", response_model=ReviewTaskResponse)
async def get_review_task(task_id: str, db: Session = Depends(get_db)):
    """GET /review/{task_id} — Get a single review task."""
    task = db.query(ReviewTask).filter(ReviewTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Review task not found")
    return ReviewTaskResponse.model_validate(task)


@router.put("/review/{task_id}", response_model=ReviewTaskResponse)
async def edit_review_task(
    task_id: str,
    request: ReviewEditRequest,
    db: Session = Depends(get_db),
):
    """
    PUT /review/{task_id} — Edit expression and trigger re-validation (ADR-033).

    Applies the edited calc, re-validates syntax/fingerprint, cascades to dependents,
    and re-aggregates the ValidationScorecard.
    """
    task = db.query(ReviewTask).filter(ReviewTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Review task not found")

    task.edited_calc = request.edited_calc
    if request.resolution_notes:
        task.resolution_notes = request.resolution_notes

    # TODO: Trigger single-expression re-validation cascade (ADR-033)
    # 1. Parse edited_calc → AST → validate syntax
    # 2. Compute new SemanticFingerprint
    # 3. Cascade re-validation to dependent metrics
    # 4. Recompute ValidationScorecard for subset

    db.commit()
    db.refresh(task)
    return ReviewTaskResponse.model_validate(task)


@router.get("/review/{task_id}/blast-radius", response_model=BlastRadiusResponse)
async def get_blast_radius(task_id: str, db: Session = Depends(get_db)):
    """
    GET /review/{task_id}/blast-radius — Get transitive dependency blast radius.

    Returns the affected downstream worksheets and metrics for this review task.
    """
    task = db.query(ReviewTask).filter(ReviewTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Review task not found")

    blast = task.blast_radius or []
    return BlastRadiusResponse(
        task_id=task_id,
        expression_id=task.object_id,
        direct_dependents=len(blast),
        affected_worksheets=[],  # TODO: resolve from dependency graph
        summary=f"Edit affects {len(blast)} downstream objects",
    )


@router.post("/review/{task_id}/approve", response_model=ReviewTaskResponse)
async def approve_review_task(
    task_id: str,
    request: ReviewApproveRequest,
    db: Session = Depends(get_db),
):
    """
    POST /review/{task_id}/approve — Approve and promote (ADR-034).

    Applies confidence calibration boost, re-emits production artifacts,
    and executes atomic promotion to Tableau Server.
    """
    task = db.query(ReviewTask).filter(ReviewTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Review task not found")

    task.status = "approved"
    task.resolution_notes = request.reason or task.resolution_notes

    # ADR-034: Confidence calibration
    # Base boost: +0.10 upon human review
    # Comment boost: +0.05 for detailed justification (>= 100 characters)
    # Role boost: +0.05 if reviewer is BI_ARCHITECT (not implemented yet)
    # Ceiling: capped at 0.99
    base_boost = 0.10
    comment_boost = 0.05 if request.reason and len(request.reason) >= 100 else 0.0
    new_confidence = min((task.confidence or 0.0) + base_boost + comment_boost, 0.99)
    task.confidence = new_confidence

    db.commit()
    db.refresh(task)

    # TODO: Trigger promotion pipeline
    # 1. Re-acquire production write-lock (ADR-029)
    # 2. Apply all registered IR edits
    # 3. Re-emit production artifacts
    # 4. Execute atomic promotion to Tableau Server

    return ReviewTaskResponse.model_validate(task)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Validation (api.md §5)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.get("/jobs/{job_id}/validation", response_model=ValidationScorecardResponse)
async def get_validation_scorecard(job_id: str, db: Session = Depends(get_db)):
    """
    GET /jobs/{id}/validation — Get the validation scorecard.

    Returns category-weighted confidence scores and individual check results.
    """
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    checks = db.query(ValidationCheck).filter(ValidationCheck.job_id == job_id).all()

    blocker_count = sum(1 for c in checks if not c.passed and c.check_type in ("row_count", "kpi_value", "xsd"))
    warning_count = sum(1 for c in checks if not c.passed and c.check_type not in ("row_count", "kpi_value", "xsd"))
    mandatory_count = (
        db.query(ReviewTask)
        .filter(ReviewTask.job_id == job_id, ReviewTask.status == "pending")
        .count()
    )

    # Compute auto_publish_ok per ADR-025
    auto_publish_ok = (
        (job.security_confidence or 0) >= 1.0
        and (job.financial_kpi_confidence or 0) >= 0.98
        and (job.structural_confidence or 0) >= 0.99
        and (job.visual_confidence or 0) >= 0.80
        and (job.security_parity is True)
        and blocker_count == 0
        and mandatory_count == 0
    )

    return ValidationScorecardResponse(
        job_id=job_id,
        security_confidence=job.security_confidence or 1.0,
        financial_kpi_confidence=job.financial_kpi_confidence or 1.0,
        structural_confidence=job.structural_confidence or 1.0,
        visual_confidence=job.visual_confidence or 1.0,
        security_parity=job.security_parity if job.security_parity is not None else True,
        auto_publish_ok=auto_publish_ok,
        blocker_issues=blocker_count,
        warning_issues=warning_count,
        mandatory_review_flags=mandatory_count,
        checks=[ValidationCheckResponse.model_validate(c) for c in checks],
    )
