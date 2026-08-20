"""
Job management API routes.

Ref: spec/api.md §1 — Jobs
"""

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.v1.schemas import (
    JobCreateRequest,
    JobListResponse,
    JobStatusResponse,
)
from app.core.config import settings
from app.db.session import get_db
from app.models.job import Job
from app.services.pipeline.orchestrator import run_pipeline

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("", response_model=JobStatusResponse, status_code=201)
async def create_job(
    request: JobCreateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    POST /jobs — Create a new migration job.

    Creates the job record, sets up the artifacts directory,
    and launches the migration pipeline as a background task.
    """
    job_id = str(uuid.uuid4())
    artifacts_dir = str(Path(settings.artifacts_dir) / job_id)
    Path(artifacts_dir).mkdir(parents=True, exist_ok=True)

    job = Job(
        id=job_id,
        name=request.name,
        status="PENDING",
        mstr_base_url=request.mstr_base_url,
        mstr_project_id=request.mstr_project_id,
        tableau_server_url=request.tableau_server_url,
        tableau_site_id=request.tableau_site_id,
        tableau_target_project=request.tableau_target_project,
        template_version=request.template_version,
        skip_unused=request.skip_unused,
        extract_data=request.extract_data,
        auto_publish=request.auto_publish,
        publish_mode=request.publish_mode,
        numeric_threshold=request.numeric_threshold,
        warehouse_connection_json=request.warehouse_connection,
        artifacts_dir=artifacts_dir,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Launch pipeline in background
    background_tasks.add_task(
        run_pipeline,
        job_id,
        selected_dossier_ids=request.selected_dossier_ids,
        mstr_username=request.mstr_username,
        mstr_password=request.mstr_password,
        tableau_token_name=request.tableau_token_name or "",
        tableau_token_value=request.tableau_token_value or "",
    )

    return job


@router.get("", response_model=JobListResponse)
async def list_jobs(
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """GET /jobs — List all migration jobs with pagination."""
    query = db.query(Job)
    if status:
        query = query.filter(Job.status == status)

    total = query.count()
    jobs = query.order_by(Job.created_at.desc()).offset(offset).limit(limit).all()

    return JobListResponse(
        jobs=[JobStatusResponse.model_validate(j) for j in jobs],
        total=total,
    )


@router.get("/{job_id}", response_model=JobStatusResponse)
async def get_job(job_id: str, db: Session = Depends(get_db)):
    """GET /jobs/{id} — Get job status and progress."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return JobStatusResponse.model_validate(job)


@router.post("/{job_id}/cancel", response_model=JobStatusResponse)
async def cancel_job(job_id: str, db: Session = Depends(get_db)):
    """POST /jobs/{id}/cancel — Cancel a running job."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    if job.status in ("COMPLETE", "CANCELLED"):
        raise HTTPException(status_code=400, detail=f"Job is already {job.status}")

    job.status = "CANCELLED"
    job.completed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(job)
    return JobStatusResponse.model_validate(job)


@router.get("/{job_id}/artifacts")
async def list_artifacts(job_id: str, db: Session = Depends(get_db)):
    """GET /jobs/{id}/artifacts — List all generated artifacts (twbx, hyper, tds)."""
    from app.models.objects import Artifact

    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    artifacts = db.query(Artifact).filter(Artifact.job_id == job_id).all()

    return {
        "artifacts": [
            {
                "id": a.id,
                "type": a.artifact_type,
                "file_name": a.file_name,
                "file_path": a.artifact_path,
                "size_bytes": a.size_bytes,
                "artifact_hash": a.artifact_hash,
                "environment": a.environment,
            }
            for a in artifacts
        ],
        "total": len(artifacts),
    }


@router.get("/{job_id}/download/{artifact_id}")
async def download_artifact(job_id: str, artifact_id: str, db: Session = Depends(get_db)):
    """GET /jobs/{id}/download/{artifact_id} — Download a .twbx / .hyper / .tds artifact."""
    from fastapi.responses import FileResponse
    from app.models.objects import Artifact

    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    artifact = db.query(Artifact).filter(
        Artifact.id == artifact_id, Artifact.job_id == job_id
    ).first()
    if not artifact:
        raise HTTPException(status_code=404, detail=f"Artifact {artifact_id} not found")

    file_path = Path(artifact.artifact_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Artifact file not found on disk")

    return FileResponse(
        path=str(file_path),
        filename=artifact.file_name or file_path.name,
        media_type="application/octet-stream",
    )


@router.get("/cross-reference", tags=["cross-reference"])
async def list_cross_references(
    job_id: Optional[str] = None,
    mstr_id: Optional[str] = None,
    tableau_id: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """GET /cross-reference — Retrieve cross-reference lineage mappings."""
    from app.models.objects import CrossReference, MigrationObject

    query = db.query(CrossReference)
    if job_id:
        query = query.filter(CrossReference.job_id == job_id)
    if mstr_id:
        query = query.filter(CrossReference.mstr_id == mstr_id)
    if tableau_id:
        query = query.filter(CrossReference.tableau_workbook_id == tableau_id)

    records = query.all()

    # If cross_references table has records, return them
    if records:
        return {
            "mappings": [
                {
                    "id": r.id,
                    "job_id": r.job_id,
                    "mstr_id": r.mstr_id,
                    "mstr_name": r.mstr_name,
                    "mstr_type": r.mstr_type,
                    "mstr_path": r.mstr_path,
                    "tableau_workbook_id": r.tableau_workbook_id,
                    "tableau_workbook_name": r.tableau_workbook_name,
                    "tableau_datasource_id": r.tableau_datasource_id,
                    "tableau_field_name": r.tableau_field_name,
                    "published_field_name": r.published_field_name,
                    "tableau_field_type": r.tableau_field_type,
                    "tableau_project": r.tableau_project,
                    "migrated_at": r.migrated_at.isoformat() if r.migrated_at else None,
                }
                for r in records
            ],
            "total": len(records),
        }

    # Fallback to deriving mappings directly from MigrationObjects if not separately populated
    if job_id:
        objects = db.query(MigrationObject).filter(MigrationObject.job_id == job_id).all()
        job = db.query(Job).filter(Job.id == job_id).first()
        target_proj = job.tableau_target_project if job else "Migrated Dashboards"
        mappings = []
        for o in objects:
            mappings.append({
                "id": o.id,
                "job_id": o.job_id,
                "mstr_id": o.mstr_id,
                "mstr_name": o.name,
                "mstr_type": o.type_name,
                "mstr_path": o.path or "/Public Objects/",
                "tableau_workbook_id": f"wb-{o.job_id[:8]}",
                "tableau_workbook_name": job.name if job else "Target Tableau Model",
                "tableau_datasource_id": f"ds-{o.job_id[:8]}",
                "tableau_field_name": o.tableau_calc or o.name,
                "published_field_name": o.name,
                "tableau_field_type": "measure" if o.type_name == "metric" else "dimension",
                "tableau_project": target_proj,
                "migrated_at": o.published_at.isoformat() if o.published_at else (o.compiled_at.isoformat() if o.compiled_at else o.discovered_at.isoformat() if o.discovered_at else None),
            })
        return {"mappings": mappings, "total": len(mappings)}

    return {"mappings": [], "total": 0}


@router.get("/{job_id}/checkpoints")
async def get_checkpoints(job_id: str, db: Session = Depends(get_db)):
    """GET /jobs/{id}/checkpoints — Retrieve extraction checkpoints."""
    from app.models.objects import ExtractionCheckpoint

    checkpoints = db.query(ExtractionCheckpoint).filter(ExtractionCheckpoint.job_id == job_id).all()
    job = db.query(Job).filter(Job.id == job_id).first()

    return {
        "job_id": job_id,
        "current_stage": job.current_stage if job else "DISCOVERY",
        "checkpoints": [
            {
                "id": c.id,
                "job_id": c.job_id,
                "object_id": c.object_id,
                "object_name": c.object_id,
                "page_offset": c.page_offset,
                "rows_written": c.rows_written,
                "completed": c.completed,
                "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            }
            for c in checkpoints
        ],
        "total": len(checkpoints),
    }


@router.post("/{job_id}/report")
async def generate_job_report(job_id: str, payload: dict = None, db: Session = Depends(get_db)):
    """POST /jobs/{id}/report — Generate and return executive report summary."""
    from app.models.objects import MigrationObject, Artifact
    from app.models.validation import ValidationCheck

    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    objects = db.query(MigrationObject).filter(MigrationObject.job_id == job_id).all()
    checks = db.query(ValidationCheck).filter(ValidationCheck.job_id == job_id).all()
    artifacts = db.query(Artifact).filter(Artifact.job_id == job_id).all()

    report_format = (payload or {}).get("format", "json")

    summary = {
        "job_id": job.id,
        "job_name": job.name,
        "status": job.status,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "source": {
            "base_url": job.mstr_base_url,
            "project_id": job.mstr_project_id,
            "project_name": job.mstr_project_name,
            "version": job.mstr_version,
        },
        "target": {
            "server_url": job.tableau_server_url,
            "site_id": job.tableau_site_id,
            "target_project": job.tableau_target_project,
            "template_version": job.template_version,
        },
        "confidence_scores": {
            "security": job.security_confidence,
            "financial_kpi": job.financial_kpi_confidence,
            "structural": job.structural_confidence,
            "visual": job.visual_confidence,
            "security_parity": job.security_parity,
        },
        "metrics": {
            "objects_total": len(objects),
            "objects_succeeded": sum(1 for o in objects if o.status in ("compiled", "published", "extracted")),
            "objects_failed": sum(1 for o in objects if o.status == "failed"),
            "validation_checks_total": len(checks),
            "validation_checks_passed": sum(1 for c in checks if c.passed),
            "artifacts_count": len(artifacts),
        },
        "artifacts": [
            {"id": a.id, "name": a.file_name, "type": a.artifact_type, "size_bytes": a.size_bytes}
            for a in artifacts
        ]
    }

    return {
        "job_id": job_id,
        "report_url": f"/api/v1/jobs/{job_id}/report/download",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "format": report_format,
        "summary": summary,
    }

