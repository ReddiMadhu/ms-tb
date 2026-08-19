"""
Validation check ORM model.

Ref: spec/database.md §2.4
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import relationship

from app.db.base import Base


def _utcnow():
    return datetime.now(timezone.utc)


def _uuid():
    return str(uuid.uuid4())


class ValidationCheck(Base):
    """Individual validation check result within a job's scorecard."""

    __tablename__ = "validation_checks"
    __table_args__ = (
        Index("idx_validation_job", "job_id"),
        Index("idx_validation_passed", "passed"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False)
    object_id = Column(String)

    check_type = Column(String, nullable=False)
    check_name = Column(String, nullable=True)
    category = Column(String, nullable=True)
    filter_scenario = Column(String)

    expected_value = Column(Text)
    actual_value = Column(Text)
    tolerance = Column(Float)
    passed = Column(Boolean, nullable=False)
    message = Column(Text)

    executed_at = Column(DateTime, default=_utcnow)

    job = relationship("Job", back_populates="validation_checks")
