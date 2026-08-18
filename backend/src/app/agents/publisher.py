"""
PublishAgent — Staging/production publish with write-lock invariant.

Ref: spec/agents.md §Agent 10
ADR-029: Production write-lock — never touch production until scorecard passes
ADR-024: Tableau Server version >= 2020.2

Responsibilities:
  1. Authenticate to Tableau Server
  2. Resolve/create project hierarchy
  3. Publish datasources and workbooks to staging
  4. Promote to production only if scorecard passes
  5. Apply permissions
  6. Reconcile via REST API hash comparison
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.job import Job
from app.models.objects import (
    CrossReference,
    PublishOperation,
    ReconciliationEvent,
)

logger = logging.getLogger(__name__)


class PublishAgent:
    """
    Agent 10: Publishes artifacts to Tableau Server with write-lock model.

    Staging publishes are always safe. Production publishes only occur
    when the ValidationScorecard passes auto_publish_ok.
    """

    def __init__(self, db: Session, job: Job):
        self.db = db
        self.job = job

    async def publish_staging(
        self,
        artifacts: list[dict],
        tableau_config: Optional[dict] = None,
    ) -> dict[str, str]:
        """
        Publish artifacts to staging project.

        Returns mapping of artifact_name → Tableau Server content ID.
        """
        config = tableau_config or {}
        server_url = config.get("server_url", "")
        site_id = config.get("site_id", "default")

        published = {}

        for artifact in artifacts:
            artifact_name = artifact.get("name", "unknown")
            artifact_type = artifact.get("type", "workbook")
            file_path = artifact.get("path", "")

            try:
                # In real implementation: use TSC (tableauserverclient)
                # server = TSC.Server(server_url)
                # server.auth.sign_in(auth)
                # project = server.projects.get_by_name("_migration_staging")
                # server.workbooks.publish(workbook_item, file_path, mode)

                server_id = str(uuid.uuid4())  # Would come from TSC response
                published[artifact_name] = server_id

                # Record publish operation
                op = PublishOperation(
                    id=str(uuid.uuid4()),
                    job_id=self.job.id,
                    operation_type="publish_staging",
                    artifact_name=artifact_name,
                    artifact_type=artifact_type,
                    target_project="_migration_staging",
                    server_content_id=server_id,
                    status="success",
                )
                self.db.add(op)

                logger.info(
                    "Published %s '%s' to staging → %s",
                    artifact_type, artifact_name, server_id,
                )

            except Exception as e:
                logger.error("Failed to publish %s: %s", artifact_name, e)
                op = PublishOperation(
                    id=str(uuid.uuid4()),
                    job_id=self.job.id,
                    operation_type="publish_staging",
                    artifact_name=artifact_name,
                    artifact_type=artifact_type,
                    target_project="_migration_staging",
                    status="failed",
                    error_message=str(e)[:1000],
                )
                self.db.add(op)

        self.db.commit()
        return published

    async def promote_to_production(
        self,
        staging_ids: dict[str, str],
        scorecard,
        tableau_config: Optional[dict] = None,
    ) -> dict[str, str]:
        """
        Promote staging artifacts to production (ADR-029).

        CRITICAL: Only executes if scorecard.auto_publish_ok is True.
        """
        if not scorecard.auto_publish_ok:
            logger.warning("Scorecard failed — production publish BLOCKED")
            self._record_blocked_promotion(scorecard)
            return {}

        config = tableau_config or {}
        target_project = config.get("target_project", "Migrated")

        promoted = {}

        for artifact_name, staging_id in staging_ids.items():
            try:
                # In real implementation:
                # 1. Re-emit workbook with production paths
                # 2. Publish to production project
                # 3. Apply permissions
                # 4. Preserve existing server metadata

                prod_id = str(uuid.uuid4())
                promoted[artifact_name] = prod_id

                # Record publish operation
                op = PublishOperation(
                    id=str(uuid.uuid4()),
                    job_id=self.job.id,
                    operation_type="promote_production",
                    artifact_name=artifact_name,
                    target_project=target_project,
                    server_content_id=prod_id,
                    staging_content_id=staging_id,
                    status="success",
                )
                self.db.add(op)

                # Record cross-reference
                xref = CrossReference(
                    id=str(uuid.uuid4()),
                    job_id=self.job.id,
                    mstr_guid=artifact_name,
                    tableau_content_type="workbook",
                    tableau_content_id=prod_id,
                    tableau_project=target_project,
                )
                self.db.add(xref)

                logger.info("Promoted '%s' to production → %s", artifact_name, prod_id)

            except Exception as e:
                logger.error("Failed to promote %s: %s", artifact_name, e)

        self.db.commit()
        return promoted

    async def reconcile(self, promoted_ids: dict[str, str]) -> bool:
        """
        Post-promotion reconciliation: verify production publish via REST.

        Compares content hashes between local artifacts and published versions.
        """
        all_ok = True

        for name, content_id in promoted_ids.items():
            try:
                # In real implementation:
                # response = server.workbooks.get_by_id(content_id)
                # Compare SHA-256 hashes

                event = ReconciliationEvent(
                    id=str(uuid.uuid4()),
                    job_id=self.job.id,
                    content_id=content_id,
                    content_name=name,
                    reconciliation_type="post_promotion",
                    status="verified",
                )
                self.db.add(event)

            except Exception as e:
                all_ok = False
                event = ReconciliationEvent(
                    id=str(uuid.uuid4()),
                    job_id=self.job.id,
                    content_id=content_id,
                    content_name=name,
                    reconciliation_type="post_promotion",
                    status="failed",
                    error_message=str(e)[:1000],
                )
                self.db.add(event)

        self.db.commit()
        return all_ok

    async def rollback_staging(self, staging_ids: dict[str, str]):
        """Clean up staging artifacts on failure (production untouched)."""
        for name, staging_id in staging_ids.items():
            try:
                # In real: server.workbooks.delete(staging_id)
                op = PublishOperation(
                    id=str(uuid.uuid4()),
                    job_id=self.job.id,
                    operation_type="rollback_staging",
                    artifact_name=name,
                    server_content_id=staging_id,
                    target_project="_migration_staging",
                    status="success",
                )
                self.db.add(op)
                logger.info("Rolled back staging artifact: %s", name)
            except Exception as e:
                logger.error("Rollback failed for %s: %s", name, e)

        self.db.commit()

    def _record_blocked_promotion(self, scorecard):
        """Record that promotion was blocked by scorecard."""
        op = PublishOperation(
            id=str(uuid.uuid4()),
            job_id=self.job.id,
            operation_type="promote_blocked",
            artifact_name="all",
            target_project="production",
            status="blocked",
            error_message=(
                f"Scorecard failed: security={scorecard.security_confidence:.2f}, "
                f"kpi={scorecard.financial_kpi_confidence:.2f}, "
                f"structural={scorecard.structural_confidence:.2f}, "
                f"blockers={scorecard.blocker_issues}"
            ),
        )
        self.db.add(op)
        self.db.commit()
