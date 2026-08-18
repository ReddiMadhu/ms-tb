"""
ReviewQueueAgent — Human review task management.

Ref: spec/agents.md §Agent 11
ADR-033: IR patch + re-validation cascade
ADR-034: Human review confidence model

Responsibilities:
  1. Create review tasks for failed/low-confidence objects
  2. Apply IR patches from human review
  3. Cascade re-validation to dependents
  4. Compute post-review confidence with boost model
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.job import Job
from app.models.objects import Issue, MigrationObject, ReviewTask

logger = logging.getLogger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Confidence boost model (ADR-034)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

BASE_REVIEW_BOOST = 0.10
COMMENT_BOOST = 0.05           # For justification >= 100 chars
ROLE_BOOST = 0.05              # For BI_ARCHITECT reviewer role
CONFIDENCE_CEILING = 0.99


def compute_post_review_confidence(
    original: float,
    comment_length: int,
    reviewer_role: str,
) -> float:
    """
    Compute post-review confidence per ADR-034.

    confidence_post = min(original + 0.10 + comment_boost + role_boost, 0.99)
    """
    boost = BASE_REVIEW_BOOST

    if comment_length >= 100:
        boost += COMMENT_BOOST

    if reviewer_role == "BI_ARCHITECT":
        boost += ROLE_BOOST

    return min(original + boost, CONFIDENCE_CEILING)


class ReviewQueueAgent:
    """
    Agent 11: Manages human review tasks for failed/low-confidence migrations.
    """

    def __init__(self, db: Session, job: Job):
        self.db = db
        self.job = job

    def enqueue_from_scorecard(self, ir, scorecard) -> int:
        """
        Create review tasks from scorecard failures and low-confidence items.

        Returns count of tasks created.
        """
        count = 0

        # Create tasks for failed validation checks
        for check in scorecard.checks:
            if not check.passed:
                task = ReviewTask(
                    id=str(uuid.uuid4()),
                    job_id=self.job.id,
                    object_id=check.object_id,
                    severity="blocker" if check.category != "visual" else "warning",
                    reason=f"Validation failed: {check.message}",
                    confidence=0.0,
                    status="pending",
                )
                self.db.add(task)
                count += 1

        # Create tasks for low-confidence measures
        for measure in ir.measures:
            if measure.confidence < 0.85:
                existing = (
                    self.db.query(ReviewTask)
                    .filter(
                        ReviewTask.job_id == self.job.id,
                        ReviewTask.object_id == measure.mstr_id,
                        ReviewTask.status == "pending",
                    )
                    .first()
                )
                if not existing:
                    task = ReviewTask(
                        id=str(uuid.uuid4()),
                        job_id=self.job.id,
                        object_id=measure.mstr_id,
                        severity="warning" if measure.confidence >= 0.50 else "blocker",
                        reason=f"Low confidence: {measure.confidence:.2f}",
                        mstr_expression=measure.expression_text,
                        generated_calc=measure.tableau_calc,
                        confidence=measure.confidence,
                        status="pending",
                    )
                    self.db.add(task)
                    count += 1

        # Create tasks for blocker issues
        for issue in ir.issues:
            if issue.severity == "blocker":
                task = ReviewTask(
                    id=str(uuid.uuid4()),
                    job_id=self.job.id,
                    object_id=issue.object_id or self.job.id,
                    severity="blocker",
                    reason=f"Blocker: {issue.message}",
                    confidence=0.0,
                    status="pending",
                )
                self.db.add(task)
                count += 1

        self.db.commit()
        logger.info("Created %d review tasks", count)
        return count

    async def apply_patch(
        self,
        task_id: str,
        new_tableau_calc: str,
        resolution_notes: str,
        reviewer: str = "anonymous",
        reviewer_role: str = "USER",
    ) -> dict:
        """
        Apply a human IR patch and cascade re-validation (ADR-033).

        Returns updated validation status.
        """
        task = self.db.query(ReviewTask).filter(ReviewTask.id == task_id).first()
        if not task:
            raise ValueError(f"Review task {task_id} not found")

        # Update task
        task.status = "approved"
        task.resolution_notes = resolution_notes
        task.resolved_at = datetime.now(timezone.utc)
        task.generated_calc = new_tableau_calc

        # Compute post-review confidence
        new_confidence = compute_post_review_confidence(
            task.confidence or 0.0,
            len(resolution_notes),
            reviewer_role,
        )
        task.confidence = new_confidence

        # Update the migration object
        obj = (
            self.db.query(MigrationObject)
            .filter(
                MigrationObject.job_id == self.job.id,
                MigrationObject.mstr_id == task.object_id,
            )
            .first()
        )
        if obj:
            obj.tableau_calc = new_tableau_calc
            obj.confidence = new_confidence
            obj.status = "reviewed"

        self.db.commit()

        return {
            "task_id": task_id,
            "status": "approved",
            "new_confidence": new_confidence,
            "requires_re_validation": True,
        }

    async def reject_task(self, task_id: str, reason: str):
        """Mark a review task as rejected (excluded from migration)."""
        task = self.db.query(ReviewTask).filter(ReviewTask.id == task_id).first()
        if task:
            task.status = "rejected"
            task.resolution_notes = reason
            task.resolved_at = datetime.now(timezone.utc)
            self.db.commit()

    async def assign_task(self, task_id: str, assignee: str):
        """Assign a review task to a specific developer."""
        task = self.db.query(ReviewTask).filter(ReviewTask.id == task_id).first()
        if task:
            task.status = "assigned"
            task.assigned_to = assignee
            self.db.commit()

    def get_queue_stats(self) -> dict:
        """Get review queue statistics for the job."""
        tasks = (
            self.db.query(ReviewTask)
            .filter(ReviewTask.job_id == self.job.id)
            .all()
        )

        return {
            "total": len(tasks),
            "pending": sum(1 for t in tasks if t.status == "pending"),
            "approved": sum(1 for t in tasks if t.status == "approved"),
            "rejected": sum(1 for t in tasks if t.status == "rejected"),
            "assigned": sum(1 for t in tasks if t.status == "assigned"),
            "blockers": sum(1 for t in tasks if t.severity == "blocker" and t.status == "pending"),
        }
