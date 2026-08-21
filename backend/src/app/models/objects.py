"""
Migration object ORM models — objects, issues, cross_references,
caption_registry, semantic_fingerprints, extraction_checkpoints,
datasource_path_rewrites, physical_model_plans, artifacts,
publish_operations, reconciliation_events, discovery_sessions,
discovery_objects, wave_executions.

Ref: spec/database.md §2.2 – §2.18
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Index, Integer,
    String, Text, UniqueConstraint,
)
from sqlalchemy.types import JSON
from sqlalchemy.orm import relationship

from app.db.base import Base


def _utcnow():
    return datetime.now(timezone.utc)


def _uuid():
    return str(uuid.uuid4())


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  §2.2 — objects
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class MigrationObject(Base):
    """Discovered MSTR object tracked through the migration pipeline."""

    __tablename__ = "objects"
    __table_args__ = (
        UniqueConstraint("job_id", "mstr_id", name="uq_objects_job_mstr"),
        Index("idx_objects_job_id", "job_id"),
        Index("idx_objects_type", "type_name"),
        Index("idx_objects_status", "status"),
        Index("idx_objects_mstr_id", "mstr_id"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False)

    # MSTR Identity
    mstr_id = Column(String, nullable=False)
    mstr_type = Column(Integer, nullable=False)
    mstr_sub_type = Column(Integer)
    type_name = Column(String, nullable=False)
    name = Column(String, nullable=False)
    path = Column(String)
    version_id = Column(String)

    # Migration Status
    status = Column(String, nullable=False, default="discovered")

    # Extracted Definition
    mstr_definition = Column(JSON)
    expression_text = Column(Text)

    # Compiled IR
    ir_node = Column(JSON)

    # Tableau Output
    tableau_calc = Column(Text)
    tableau_field_name = Column(String)

    # Quality
    confidence = Column(Float, default=0.0)
    translation_method = Column(String)

    # Dependencies
    dependency_ids = Column(JSON)

    # Compound key structure for attributes
    compound_key_json = Column(JSON)

    # Scope for measures (shared vs local) — ADR-027
    scope = Column(String)

    # Issues
    issue_count = Column(Integer, default=0)
    blocker_count = Column(Integer, default=0)

    # Timestamps
    discovered_at = Column(DateTime, default=_utcnow)
    compiled_at = Column(DateTime)
    published_at = Column(DateTime)

    # Relationships
    job = relationship("Job", back_populates="objects")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  §2.3 — issues
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class Issue(Base):
    """Compilation or extraction issue tied to an object."""

    __tablename__ = "issues"
    __table_args__ = (
        Index("idx_issues_job_id", "job_id"),
        Index("idx_issues_severity", "severity"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False)
    object_id = Column(String)

    severity = Column(String, nullable=False)
    category = Column(String, nullable=False)
    message = Column(String, nullable=False)
    suggestion = Column(String)

    affected_objects = Column(JSON)

    created_at = Column(DateTime, default=_utcnow)

    job = relationship("Job", back_populates="issues")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  §2.5 — review_tasks
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class ReviewTask(Base):
    """Human review task for low-confidence or blocked objects."""

    __tablename__ = "review_tasks"
    __table_args__ = (
        Index("idx_review_job", "job_id"),
        Index("idx_review_status", "status"),
        Index("idx_review_severity", "severity"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False)
    object_id = Column(String, ForeignKey("objects.id"), nullable=True)

    severity = Column(String, nullable=False)
    reason = Column(String, nullable=False)

    mstr_expression = Column(Text)
    generated_calc = Column(Text)
    confidence = Column(Float)

    ir_snapshot = Column(JSON)

    status = Column(String, nullable=False, default="pending")
    assigned_to = Column(String)
    resolution_notes = Column(Text)
    edited_calc = Column(Text)

    blast_radius = Column(JSON)

    created_at = Column(DateTime, default=_utcnow)
    resolved_at = Column(DateTime)

    job = relationship("Job", back_populates="review_tasks")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  §2.6 — cross_references
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class CrossReference(Base):
    """MSTR GUID → Tableau entity cross-reference for lineage tracking."""

    __tablename__ = "cross_references"
    __table_args__ = (
        Index("idx_xref_mstr", "mstr_id"),
        Index("idx_xref_tableau", "tableau_workbook_id"),
        Index("idx_xref_job", "job_id"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False)

    mstr_id = Column(String, nullable=False)
    mstr_name = Column(String, nullable=False)
    mstr_type = Column(String, nullable=False)
    mstr_path = Column(String)

    tableau_workbook_id = Column(String)
    tableau_workbook_name = Column(String)
    tableau_datasource_id = Column(String)
    tableau_field_name = Column(String)
    published_field_name = Column(String)
    tableau_field_type = Column(String)
    tableau_project = Column(String)

    migrated_at = Column(DateTime, default=_utcnow)

    job = relationship("Job", back_populates="cross_references")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  §2.9 — caption_registry  (ADR-027)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class CaptionRegistry(Base):
    """Post-disambiguation Tableau captions scoped per published datasource."""

    __tablename__ = "caption_registry"
    __table_args__ = (
        UniqueConstraint("job_id", "datasource_id", "ir_id", name="uq_caption_ir"),
        UniqueConstraint("job_id", "datasource_id", "caption", name="uq_caption_display"),
        Index("idx_caption_job", "job_id"),
        Index("idx_caption_ds", "datasource_id"),
        Index("idx_caption_ir", "ir_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False)
    datasource_id = Column(String, nullable=False)
    ir_id = Column(String, nullable=False)
    local_name = Column(String, nullable=False)
    remote_name = Column(String, nullable=False)
    caption = Column(String, nullable=False)
    mstr_name = Column(String, nullable=False)
    scope = Column(String, default="shared")
    created_at = Column(DateTime, default=_utcnow)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  §2.10 — extraction_checkpoints  (ADR-016)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class ExtractionCheckpoint(Base):
    """Page-level checkpoint for crash-recoverable paginated MSTR extraction."""

    __tablename__ = "extraction_checkpoints"
    __table_args__ = (
        Index("idx_checkpoint_job", "job_id"),
        Index("idx_checkpoint_object", "object_id"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False)
    object_id = Column(String, nullable=False)
    page_offset = Column(Integer, default=0)
    rows_written = Column(Integer, default=0)
    etag = Column(String)
    snapshot_identity = Column(String)
    page_checksum = Column(String)
    hyper_batch_id = Column(String)
    artifact_version = Column(String)
    completed = Column(Boolean, default=False)
    updated_at = Column(DateTime, default=_utcnow)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  §2.11 — datasource_path_rewrites  (ADR-023)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class DatasourcePathRewrite(Base):
    """Staging ↔ production datasource path rewriting."""

    __tablename__ = "datasource_path_rewrites"
    __table_args__ = (
        Index("idx_dsrewrite_job", "job_id"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False)
    ir_datasource_id = Column(String, nullable=False)
    staging_path = Column(String)
    production_path = Column(String)
    staging_ds_id = Column(String)
    production_ds_id = Column(String)
    updated_at = Column(DateTime, default=_utcnow)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  §2.12 — semantic_fingerprints  (ADR-027)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class SemanticFingerprint(Base):
    """12-field canonical semantic fingerprint for measure deduplication."""

    __tablename__ = "semantic_fingerprints"
    __table_args__ = (
        UniqueConstraint("job_id", "fingerprint_hash", name="uq_fingerprint"),
        Index("idx_fingerprint_job", "job_id"),
        Index("idx_fingerprint_hash", "fingerprint_hash"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False)
    fingerprint_hash = Column(String, nullable=False)
    ast_hash = Column(String, nullable=False)
    datasource_domain = Column(String, nullable=False)
    source_dependencies = Column(JSON, nullable=False)
    physical_grain = Column(JSON, nullable=False)
    semantic_grain = Column(JSON, nullable=False)
    aggregation = Column(String, nullable=False)
    filtering_mode = Column(String, nullable=False)
    condition_phase = Column(String, nullable=False)
    transformation = Column(String)
    null_policy = Column(String, nullable=False)
    zero_division_policy = Column(String, nullable=False)
    security_scope = Column(String)
    assigned_scope = Column(String, default="local")
    created_at = Column(DateTime, default=_utcnow)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  §2.13 — physical_model_plans  (ADR-026)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class PhysicalModelPlan(Base):
    """Cached output of the PhysicalModelPlanner semantic SQL compiler."""

    __tablename__ = "physical_model_plans"
    __table_args__ = (
        Index("idx_modelplan_job", "job_id"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False)
    datasource_domain = Column(String, nullable=False)
    table_plans_json = Column(JSON, nullable=False)
    join_graph_json = Column(JSON, nullable=False)
    grain_contract_json = Column(JSON, nullable=False)
    vldb_overrides_json = Column(JSON)
    created_at = Column(DateTime, default=_utcnow)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  §2.14 — artifacts
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class Artifact(Base):
    """Generated migration artifact with content hash and environment tag."""

    __tablename__ = "artifacts"
    __table_args__ = (
        Index("idx_artifact_job", "job_id"),
        Index("idx_artifact_hash", "artifact_hash"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False)
    artifact_type = Column(String, nullable=False)
    artifact_path = Column(String, nullable=False)
    file_name = Column(String)
    artifact_hash = Column(String, nullable=False, default="")
    environment = Column(String, nullable=False, default="staging")
    datasource_id = Column(String)
    workbook_id = Column(String)
    version = Column(Integer, default=1)
    size_bytes = Column(Integer, nullable=False, default=0)
    status = Column(String, default="created")
    created_at = Column(DateTime, default=_utcnow)

    job = relationship("Job", back_populates="artifacts")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  §2.15 — publish_operations  (ADR-029)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class PublishOperation(Base):
    """Transactional publish operation with idempotency key."""

    __tablename__ = "publish_operations"
    __table_args__ = (
        Index("idx_pubop_job", "job_id"),
        Index("idx_pubop_key", "idempotency_key"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False)
    artifact_id = Column(String, ForeignKey("artifacts.id"), nullable=False)
    environment = Column(String, nullable=False)
    remote_id = Column(String)
    remote_project_id = Column(String, nullable=False)
    operation = Column(String, nullable=False)
    idempotency_key = Column(String, unique=True, nullable=False)
    status = Column(String, nullable=False)
    remote_hash = Column(String)
    error_message = Column(Text)
    started_at = Column(DateTime, default=_utcnow)
    completed_at = Column(DateTime)

    job = relationship("Job", back_populates="publish_ops")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  §2.16 — reconciliation_events
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class ReconciliationEvent(Base):
    """Promotion verification, staging cleanup, and rollback events."""

    __tablename__ = "reconciliation_events"
    __table_args__ = (
        Index("idx_reconciliation_job", "job_id"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False)
    event_type = Column(String, nullable=False)
    target_entity_id = Column(String, nullable=False)
    environment = Column(String, nullable=False)
    details = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=_utcnow)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  §2.17 — discovery_sessions & discovery_objects
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class DiscoverySession(Base):
    """Tracks resumable pre-job discovery catalog walks."""

    __tablename__ = "discovery_sessions"

    job_id = Column(String, ForeignKey("jobs.id"), primary_key=True)
    started_at = Column(DateTime, default=_utcnow)
    last_checkpoint_at = Column(DateTime)
    current_phase = Column(String, nullable=False)
    dossiers_scanned = Column(Integer, default=0)
    dossiers_total = Column(Integer, default=0)
    status = Column(String, nullable=False, default="in_progress")


class DiscoveryObject(Base):
    """Individual object discovered during pre-job catalog scan."""

    __tablename__ = "discovery_objects"
    __table_args__ = (
        Index("idx_disc_obj_job", "job_id"),
        Index("idx_disc_obj_type", "object_type"),
    )

    job_id = Column(String, ForeignKey("jobs.id"), primary_key=True)
    object_id = Column(String, primary_key=True)
    object_type = Column(String, nullable=False)
    object_name = Column(String, nullable=False)
    parent_id = Column(String)
    discovered_at = Column(DateTime, default=_utcnow)
    extraction_status = Column(String, nullable=False, default="pending")
    error_reason = Column(String)
    metadata_json = Column(Text, nullable=False)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  §2.18 — wave_executions  (ADR-003)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class WaveExecution(Base):
    """SCC unit wave execution state for crash recovery."""

    __tablename__ = "wave_executions"
    __table_args__ = (
        Index("idx_wave_exec_job", "job_id"),
        Index("idx_wave_exec_status", "status"),
    )

    job_id = Column(String, ForeignKey("jobs.id"), primary_key=True)
    wave_id = Column(Integer, primary_key=True)
    scc_id = Column(Integer, primary_key=True)
    object_id = Column(String)
    dependency_hash = Column(String, nullable=False)
    status = Column(String, nullable=False, default="PENDING")
    attempt = Column(Integer, nullable=False, default=1)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    failure_reason = Column(String)
    failure_class = Column(String)
    blocker_issues = Column(Text)
    ir_json_path = Column(String)
