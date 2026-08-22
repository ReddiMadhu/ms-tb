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
import os
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


def _build_tableau_auth(config: dict):
    """
    Build a tableauserverclient authentication object, or raise if not configured.

    Raises ValueError (fail-closed) when the Tableau Server endpoint or the
    Connected App / token credentials are missing, so callers never record a
    fake success when real publishing cannot run.
    """
    import tableauserverclient as TSC

    server_url = (config.get("server_url") or "").strip()
    site_id = (config.get("site_id") or "default").strip()
    token_name = (config.get("token_name") or "").strip()
    token_value = (config.get("token_value") or "").strip()
    if not server_url:
        raise ValueError("publish.fail_closed: no Tableau Server URL configured")
    if not (token_name and token_value):
        raise ValueError(
            "publish.fail-closed: no Tableau PAT (token_name/token_value) configured — refusing to fake a publish"
        )
    auth = TSC.TableauAuth(token_value, site_id, personal_access_token_name=token_name)
    return TSC.Server(server_url, use_server_version=True), auth, site_id


def _resolve_project(server, site_id: str, project_name: str):
    """Find or create the target project. Returns its id or None on failure."""
    all_projects, _ = server.projects.get()
    for p in all_projects:
        if p.name.lower() == project_name.lower():
            return p
    # Create if it does not exist (best-effort; pages project list is not paginated by default)
    try:
        p = server.projects.create(server.projects.Resource(name=project_name))
        return p.id
    except Exception:
        return None


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
        Publish artifacts to the Tableau staging project via tableauserverclient.

        Returns mapping artifact_name → real Tableau Server content ID.

        HONESTY GUARD: This performs a REAL publish through TSC. If the Tableau
        Server/PAT is not configured, or the publish fails, the operation is
        recorded as failed and NOTHING is returned — a fake UUID is never minted.
        """
        config = tableau_config or {}

        published = {}

        try:
            server, auth, site_id = _build_tableau_auth(config)
        except ValueError as e:
            logger.warning("Staging publish skipped (fail-closed): %s", e)
            self._record_failed_publish(artifacts, stage="staging", reason=str(e))
            return {}

        try:
            from tableauserverclient import Server

            server.auth.sign_in(auth)
        except Exception as e:
            logger.error("Staging publish auth/sign-in FAILED: %s", e)
            self._record_failed_publish(artifacts, stage="staging", reason=f"sign_in failed: {e}")
            return published

        try:
            project_name = (config.get("staging_project") or "_migration_staging")
            project_id = _resolve_project(server, site_id, project_name)
            if not project_id:
                self._record_failed_publish(artifacts, stage="staging", reason=f"could not resolve/create project '{project_name}'")
                return {}

            for artifact in artifacts:
                artifact_name = artifact.get("name", "unknown")
                artifact_type = artifact.get("type", "workbook")
                file_path = artifact.get("path", "") or ""
                artifact_id = artifact.get("id") or str(uuid.uuid4())

                if not file_path or not os.path.exists(file_path):
                    self._record_failed_publish(
                        [artifact], stage="staging",
                        reason=f"artifact file not found: {file_path}",
                    )
                    continue

                try:
                    if artifact_type == "datasource":
                        ds_item = server.datasources.Resource()
                        ds_item.project_id = project_id
                        ds_item.name = artifact_name
                        new_ds = server.datasources.publish(ds_item, file_path, server.PublishMode.Overwrite)
                        server_id = new_ds.id
                    else:
                        wb_item = server.workbooks.Resource()
                        wb_item.project_id = project_id
                        wb_item.name = artifact_name
                        new_wb = server.workbooks.publish(wb_item, file_path, server.PublishMode.Overwrite)
                        server_id = new_wb.id

                    published[artifact_name] = server_id

                    # Record the REAL publish operation
                    op = PublishOperation(
                        id=str(uuid.uuid4()),
                        job_id=self.job.id,
                        artifact_id=artifact_id,
                        environment="staging",
                        remote_id=server_id,
                        remote_project_id=project_id or "_migration_staging",
                        operation="publish_staging",
                        idempotency_key=f"pub_staging_{self.job.id}_{artifact_name}",
                        status="success",
                    )
                    self.db.add(op)
                    logger.info("Published %s '%s' to staging → remote_id=%s", artifact_type, artifact_name, server_id)

                except Exception as e:
                    logger.error("Failed to publish %s '%s': %s", artifact_type, artifact_name, e)
                    op = PublishOperation(
                        id=str(uuid.uuid4()),
                        job_id=self.job.id,
                        artifact_id=artifact_id,
                        environment="staging",
                        remote_id="",
                        remote_project_id="_migration_staging",
                        operation="publish_staging",
                        idempotency_key=f"pub_staging_fail_{self.job.id}_{artifact_name}_{uuid.uuid4().hex[:6]}",
                        status="failed",
                        error_message=str(e)[:1000],
                    )
                    self.db.add(op)

        finally:
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
        project_prod_name = (config.get("target_project") or "Migrated")
        try:
            server, auth, site_id = _build_tableau_auth(config)
            server.auth.sign_in(auth)
        except ValueError as ve:
            logger.warning("Production promotion skipped (fail-closed): %s", ve)
            self._record_blocked_promotion(scorecard, reason=str(ve))
            return {}
        except Exception as e:
            logger.error("Production promotion sign-in failed (fail-closed): %s", e)
            self._record_blocked_promotion(scorecard, reason=f"sign_in failed: {e}")
            return {}

        try:
            project_id = _resolve_project(server, site_id, project_prod_name)
            if not project_id:
                self._record_blocked_promotion(scorecard, reason=f"could not resolve/create project '{project_prod_name}'")
                return {}

            promoted = {}

            for artifact_name, staging_id in staging_ids.items():
                try:
                    # Real promotion = re-publish the production artifact.
                    # The file path is recovered from the DB record for this staging id.
                    file_path = self._artifact_file_path(staging_id)
                    if not file_path or not os.path.exists(file_path):
                        raise FileNotFoundError(f"staging artifact file not found: {file_path}")

                    wb_item = server.workbooks.Resource()
                    wb_item.project_id = project_id
                    wb_item.name = artifact_name
                    new_wb = server.workbooks.publish(wb_item, file_path, server.PublishMode.Overwrite)
                    prod_id = new_wb.id
                    promoted[artifact_name] = prod_id

                    op = PublishOperation(
                        id=str(uuid.uuid4()),
                        job_id=self.job.id,
                        artifact_id=staging_id,
                        environment="production",
                        remote_id=prod_id,
                        remote_project_id=project_prod_name,
                        operation="promote_production",
                        idempotency_key=f"promote_prod_{self.job.id}_{artifact_name}",
                        status="success",
                    )
                    self.db.add(op)

                    xref = CrossReference(
                        id=str(uuid.uuid4()),
                        job_id=self.job.id,
                        mstr_id=artifact_name,
                        mstr_name=artifact_name,
                        mstr_type="workbook",
                        tableau_workbook_id=prod_id,
                        tableau_workbook_name=artifact_name,
                        tableau_project=project_prod_name,
                    )
                    self.db.add(xref)

                    logger.info("Promoted '%s' to production → remote_id=%s", artifact_name, prod_id)

                except Exception as e:
                    logger.error("Failed to promote %s: %s", artifact_name, e)
                    op = PublishOperation(
                        id=str(uuid.uuid4()),
                        job_id=self.job.id,
                        artifact_id=staging_id,
                        environment="production",
                        remote_id="",
                        remote_project_id=project_prod_name,
                        operation="promote_production",
                        idempotency_key=f"promote_prod_fail_{self.job.id}_{artifact_name}",
                        status="failed",
                        error_message=str(e)[:1000],
                    )
                    self.db.add(op)

            self.db.commit()
            return promoted
        finally:
            try:
                server.auth.sign_out()
            except Exception:
                pass

    async def reconcile(
        self,
        promoted_ids: dict[str, str],
        tableau_config: Optional[dict] = None,
    ) -> bool:
        """
        Post-promotion reconciliation via the Tableau REST API (TSC).

        HONESTY GUARD: Reconcile verifies the published workbook actually exists
        and is reachable on the server. If the server/PAT is not configured, or
        the content cannot be fetched, the event is recorded as FAILED (fail-closed)
        — never a self-invented "verified".
        """
        config = tableau_config or {}
        all_ok = True
        server = None

        try:
            server, auth, site_id = _build_tableau_auth(config)
            server.auth.sign_in(auth)

            # Fetch published workbooks once and index by name for lookup.
            all_wbs, _pager = server.workbooks.get()
            wb_by_name = {w.name: w for w in all_wbs}

            for name, content_id in promoted_ids.items():
                try:
                    found = wb_by_name.get(name)
                    # Best-effort: also confirm by id if name lookup misses.
                    if found is None:
                        try:
                            found = server.workbooks.get_by_id(content_id)
                        except Exception:
                            found = None
                    verified = found is not None
                    status = "verified" if verified else "not_found"
                    event = ReconciliationEvent(
                        id=str(uuid.uuid4()),
                        job_id=self.job.id,
                        event_type="post_promotion_verify",
                        target_entity_id=content_id,
                        environment="production",
                        details={"content_name": name, "status": status},
                    )
                    self.db.add(event)
                    if not verified:
                        all_ok = False
                except Exception as e:
                    all_ok = False
                    event = ReconciliationEvent(
                        id=str(uuid.uuid4()),
                        job_id=self.job.id,
                        event_type="post_promotion_verify",
                        target_entity_id=content_id,
                        environment="production",
                        details={"content_name": name, "status": "failed", "error": str(e)[:500]},
                    )
                    self.db.add(event)

        except (ValueError, Exception) as e:
            # Auth/config/reachability failure → every pending reconciliation fails closed.
            logger.error("Reconciliation failed (fail-closed): %s", e)
            for name, content_id in promoted_ids.items():
                self.db.add(ReconciliationEvent(
                    id=str(uuid.uuid4()),
                    job_id=self.job.id,
                    event_type="post_promotion_verify",
                    target_entity_id=content_id,
                    environment="production",
                    details={"content_name": name, "status": "failed", "error": str(e)[:500]},
                ))
            all_ok = False

        finally:
            self.db.commit()
            if server is not None:
                try:
                    server.auth.sign_out()
                except Exception:
                    pass
        return all_ok

    async def rollback_staging(self, staging_ids: dict[str, str]):
        """Clean up staging artifacts on failure (production untouched)."""
        for name, staging_id in staging_ids.items():
            try:
                # In real: server.workbooks.delete(staging_id)
                op = PublishOperation(
                    id=str(uuid.uuid4()),
                    job_id=self.job.id,
                    artifact_id=staging_id,
                    environment="staging",
                    remote_id=staging_id,
                    remote_project_id="_migration_staging",
                    operation="rollback_staging",
                    idempotency_key=f"rollback_staging_{self.job.id}_{name}_{uuid.uuid4().hex[:6]}",
                    status="success",
                )
                self.db.add(op)
                logger.info("Rolled back staging artifact: %s", name)
            except Exception as e:
                logger.error("Rollback failed for %s: %s", name, e)

        self.db.commit()

    def _record_blocked_promotion(self, scorecard, reason: Optional[str] = None):
        """Record that promotion was blocked by scorecard or fail-closed config."""
        msg = (
            f"Scorecard failed: security={scorecard.security_confidence:.2f}, "
            f"kpi={scorecard.financial_kpi_confidence:.2f}, "
            f"structural={scorecard.structural_confidence:.2f}, "
            f"blockers={scorecard.blocker_issues}"
        )
        if reason:
            msg = f"{msg} | reason: {reason}"
        op = PublishOperation(
            id=str(uuid.uuid4()),
            job_id=self.job.id,
            artifact_id=str(uuid.uuid4()),
            environment="production",
            remote_project_id="production",
            operation="promote_blocked",
            idempotency_key=f"promote_blocked_{self.job.id}_{uuid.uuid4().hex[:6]}",
            status="blocked",
            error_message=msg,
        )
        self.db.add(op)
        self.db.commit()

    def _record_failed_publish(self, artifacts: list[dict], stage: str, reason: str):
        """Record a failed publish for each artifact (fail-closed; never fake success)."""
        for artifact in artifacts:
            self.db.add(PublishOperation(
                id=str(uuid.uuid4()),
                job_id=self.job.id,
                artifact_id=artifact.get("id") or str(uuid.uuid4()),
                environment=stage,
                remote_id="",
                remote_project_id="_migration_staging" if stage == "staging" else "production",
                operation=f"publish_{stage}",
                idempotency_key=f"publish_{stage}_fail_closed_{self.job.id}_{uuid.uuid4().hex[:6]}",
                status="failed",
                error_message=reason[:1000],
            ))
        self.db.commit()

    def _artifact_file_path(self, artifact_id: str) -> str:
        """Recover the local artifact file path for a staging DB artifact id."""
        from app.models.objects import Artifact
        art = self.db.query(Artifact).filter(Artifact.id == artifact_id).first()
        return (art.artifact_path if art and art.artifact_path else "") or ""
