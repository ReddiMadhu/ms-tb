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
    # background_tasks.add_task(run_pipeline, job_id, request)

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
                "file_size_bytes": a.file_size_bytes,
                "content_hash": a.content_hash,
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

    file_path = Path(artifact.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Artifact file not found on disk")

    return FileResponse(
        path=str(file_path),
        filename=artifact.file_name,
        media_type="application/octet-stream",
    )

