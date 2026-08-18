"""
Pydantic request/response schemas for the REST API.

Ref: spec/api.md §1–§5
"""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Job Schemas (api.md §1)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class JobCreateRequest(BaseModel):
    """POST /jobs — create a new migration job."""

    name: str
    mstr_base_url: str
    mstr_username: str
    mstr_password: str
    mstr_project_id: str

    tableau_server_url: Optional[str] = None
    tableau_site_id: str = "default"
    tableau_token_name: Optional[str] = None
    tableau_token_value: Optional[str] = None
    tableau_target_project: Optional[str] = None

    template_version: str = "2024.2"
    skip_unused: bool = True
    extract_data: bool = True
    auto_publish: bool = True
    publish_mode: str = "partial"
    numeric_threshold: float = 0.98

    # Dossier selection (optional — if not provided, scan full estate)
    selected_dossier_ids: Optional[list[str]] = None

    # Warehouse connection for direct extraction (ADR-022)
    warehouse_connection: Optional[dict[str, Any]] = None


class JobStatusResponse(BaseModel):
    """GET /jobs/{id} — job status response."""

    id: str
    name: str
    status: str
    current_stage: Optional[str] = None

    mstr_project_name: Optional[str] = None
    tableau_target_project: Optional[str] = None

    # Progress
    current_wave: int = 0
    total_waves: int = 0
    objects_total: int = 0
    objects_processed: int = 0
    objects_succeeded: int = 0
    objects_failed: int = 0
    objects_skipped: int = 0

    # Scores
    numeric_score: Optional[float] = None
    structural_score: Optional[float] = None
    security_parity: Optional[bool] = None
    security_confidence: Optional[float] = None
    financial_kpi_confidence: Optional[float] = None
    structural_confidence: Optional[float] = None
    visual_confidence: Optional[float] = None

    # Timestamps
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None

    model_config = {"from_attributes": True}


class JobListResponse(BaseModel):
    """GET /jobs — paginated job list."""
    jobs: list[JobStatusResponse]
    total: int


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Discovery Schemas (api.md §2)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class DiscoveryRequest(BaseModel):
    """POST /discovery/dossiers — initiate pre-job dossier scan."""

    mstr_base_url: str
    mstr_username: str
    mstr_password: str
    mstr_project_id: str


class DiscoveredDossier(BaseModel):
    """Individual dossier discovered during scan."""

    mstr_id: str
    name: str
    path: Optional[str] = None
    description: Optional[str] = None
    owner: Optional[str] = None
    date_modified: Optional[str] = None
    datasets: list[str] = Field(default_factory=list)
    metric_count: int = 0
    attribute_count: int = 0


class DiscoveryResponse(BaseModel):
    """Response from dossier discovery scan."""

    dossiers: list[DiscoveredDossier]
    total: int
    scan_duration_ms: int


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Object Schemas (api.md §3)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class ObjectResponse(BaseModel):
    """Individual migration object."""

    id: str
    mstr_id: str
    type_name: str
    name: str
    path: Optional[str] = None
    status: str
    confidence: float = 0.0
    translation_method: Optional[str] = None
    expression_text: Optional[str] = None
    tableau_calc: Optional[str] = None
    issue_count: int = 0
    blocker_count: int = 0

    model_config = {"from_attributes": True}


class ObjectListResponse(BaseModel):
    """GET /jobs/{id}/objects — paginated object list."""
    objects: list[ObjectResponse]
    total: int


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Review Schemas (api.md §4)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class ReviewTaskResponse(BaseModel):
    """Individual review task."""

    id: str
    job_id: str
    object_id: str
    severity: str
    reason: str
    mstr_expression: Optional[str] = None
    generated_calc: Optional[str] = None
    confidence: Optional[float] = None
    status: str
    assigned_to: Optional[str] = None
    resolution_notes: Optional[str] = None
    edited_calc: Optional[str] = None
    blast_radius: Optional[list[str]] = None
    created_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ReviewTaskListResponse(BaseModel):
    """GET /review — paginated review task list."""
    tasks: list[ReviewTaskResponse]
    total: int


class ReviewEditRequest(BaseModel):
    """PUT /review/{task_id} — edit expression and re-validate (ADR-033)."""

    edited_calc: str
    resolution_notes: Optional[str] = None
    approved_by_user: Optional[str] = None


class ReviewApproveRequest(BaseModel):
    """POST /review/{task_id}/approve — approve and promote (ADR-034)."""

    approved_by_user: str
    reason: Optional[str] = None


class BlastRadiusResponse(BaseModel):
    """GET /review/{task_id}/blast-radius."""

    task_id: str
    expression_id: Optional[str] = None
    direct_dependents: int = 0
    high_confidence_dependents: int = 0
    low_confidence_dependents: int = 0
    affected_worksheets: list[str] = Field(default_factory=list)
    summary: str = ""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Validation Schemas (api.md §5)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class ValidationCheckResponse(BaseModel):
    """Individual validation check result."""

    check_type: str
    check_name: str
    passed: bool
    expected_value: Optional[str] = None
    actual_value: Optional[str] = None
    tolerance: Optional[float] = None
    message: Optional[str] = None

    model_config = {"from_attributes": True}


class ValidationScorecardResponse(BaseModel):
    """GET /jobs/{id}/validation — full validation scorecard."""

    job_id: str
    security_confidence: float
    financial_kpi_confidence: float
    structural_confidence: float
    visual_confidence: float
    security_parity: bool
    auto_publish_ok: bool
    blocker_issues: int
    warning_issues: int
    mandatory_review_flags: int
    checks: list[ValidationCheckResponse]
