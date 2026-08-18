"""
Job ORM model.

Ref: spec/database.md §2.1, §3
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text
from sqlalchemy.types import JSON
from sqlalchemy.orm import relationship

from app.db.base import Base


def _utcnow():
    return datetime.now(timezone.utc)


def _uuid():
    return str(uuid.uuid4())


class Job(Base):
    """Migration job — top-level unit of work for one dossier or project estate."""

    __tablename__ = "jobs"

    id = Column(String, primary_key=True, default=_uuid)
    name = Column(String, nullable=False)
    status = Column(String, nullable=False, default="PENDING")

    # ── MSTR Connection ──────────────────────────────────────
    mstr_base_url = Column(String, nullable=False)
    mstr_project_id = Column(String, nullable=False)
    mstr_project_name = Column(String)
    mstr_version = Column(String)

    # ── Tableau Target (optional — download-only mode if blank) ─
    tableau_server_url = Column(String, nullable=True, default="")
    tableau_site_id = Column(String, nullable=True, default="default")
    tableau_target_project = Column(String)

    # ── Options & Configuration ───────────────────────────────
    template_version = Column(String, nullable=False, default="2024.2")
    skip_unused = Column(Boolean, default=True)
    extract_data = Column(Boolean, default=True)
    auto_publish = Column(Boolean, default=True)
    publish_mode = Column(String, default="partial")
    numeric_threshold = Column(Float, default=0.98)

    # ── VLDB, Warehouse & Watermark Settings (ADR-022/030) ────
    vldb_settings_json = Column(JSON)
    null_propagation = Column(String, default="propagate")
    zero_division_result = Column(String, default="null")
    warehouse_connection_json = Column(JSON)
    datasource_scope = Column(String, default="project")
    validation_watermark = Column(DateTime)
    security_test_identities_json = Column(JSON)
    entitlement_datasource_mode = Column(String, default="locked_separate_datasource")

    # ── Progress & Checkpoint State ───────────────────────────
    current_stage = Column(String)
    checkpoint_stage = Column(String)
    current_wave = Column(Integer, default=0)
    total_waves = Column(Integer, default=0)
    objects_total = Column(Integer, default=0)
    objects_processed = Column(Integer, default=0)
    objects_succeeded = Column(Integer, default=0)
    objects_failed = Column(Integer, default=0)
    objects_skipped = Column(Integer, default=0)

    # ── Category-Weighted Confidence Scores (ADR-025) ─────────
    security_confidence = Column(Float, default=1.0)
    financial_kpi_confidence = Column(Float, default=1.0)
    structural_confidence = Column(Float, default=1.0)
    visual_confidence = Column(Float, default=1.0)
    numeric_score = Column(Float)
    structural_score = Column(Float)
    security_parity = Column(Boolean, default=True)

    # ── Artifacts & Timestamps ────────────────────────────────
    artifacts_dir = Column(String)
    created_at = Column(DateTime, default=_utcnow)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    error_message = Column(Text)

    # ── Relationships ─────────────────────────────────────────
    objects = relationship("MigrationObject", back_populates="job", cascade="all, delete-orphan")
    issues = relationship("Issue", back_populates="job", cascade="all, delete-orphan")
    review_tasks = relationship("ReviewTask", back_populates="job", cascade="all, delete-orphan")
    artifacts = relationship("Artifact", back_populates="job", cascade="all, delete-orphan")
    publish_ops = relationship("PublishOperation", back_populates="job", cascade="all, delete-orphan")
    validation_checks = relationship("ValidationCheck", back_populates="job", cascade="all, delete-orphan")
    cross_references = relationship("CrossReference", back_populates="job", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Job id={self.id!r} name={self.name!r} status={self.status!r}>"
