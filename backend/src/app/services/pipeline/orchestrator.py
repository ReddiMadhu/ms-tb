"""
Pipeline Orchestrator — Two-Phase migration state machine.

Ref: spec/architecture.md §4, spec/agents.md (all agents)
ADR-029: Production write-lock invariant

Orchestrates the full migration pipeline:
  Phase 1 (Staging):  Discovery → Graph → Semantic → IR Compile → AI → Viz → Hyper → Emit → Stage → Validate
  Phase 2 (Promote):  Scorecard check → Production emit → Publish → Reconcile → Report

State machine transitions are persisted to SQLite for crash recovery.
"""

import asyncio
import logging
import traceback
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.job import Job

logger = logging.getLogger(__name__)

# Pipeline stages in execution order
PIPELINE_STAGES = [
    "DISCOVERY",
    "GRAPH",
    "SEMANTIC",
    "METRIC_DEDUPLICATION",
    "IR_COMPILE",
    "AI_TRANSLATE",
    "VIZ",
    "HYPER_BUILD",
    "DATASOURCE_EMIT",
    "DATASOURCE_PUBLISH",
    "WORKBOOK_EMIT_STAGING",
    "STAGING_PUBLISH",
    "SERVER_RENDER_VALIDATE",
    "STATIC_VALIDATE",
    "SECURITY_VALIDATE",
    "NUMERIC_VALIDATE",
    "WORKBOOK_EMIT_PRODUCTION",
    "PROMOTE",
    "RECONCILE",
    "REPORT",
]


class PipelineOrchestrator:
    """
    Two-Phase migration orchestrator.

    Drives the 11-wave pipeline by executing agents sequentially,
    transitioning job state, and handling failures with compensating actions.
    """

    def __init__(self, job_id: str, selected_dossier_ids: Optional[list[str]] = None):
        self.job_id = job_id
        self.selected_dossier_ids = selected_dossier_ids

    async def run(self):
        """Execute the full migration pipeline."""
        db = SessionLocal()
        try:
            job = db.query(Job).filter(Job.id == self.job_id).first()
            if not job:
                logger.error("Job %s not found", self.job_id)
                return

            job.status = "RUNNING"
            job.started_at = datetime.now(timezone.utc)
            db.commit()

            try:
                # ── Phase 1: Staging Pipeline ────────────────────────

                # Stage 1: Discovery
                await self._run_stage(db, job, "DISCOVERY", self._run_discovery)

                # Stage 2: Graph Compilation
                await self._run_stage(db, job, "GRAPH", self._run_graph)

                # Stage 3: Semantic Extraction
                await self._run_stage(db, job, "SEMANTIC", self._run_semantic)

                # Stage 4: Metric Deduplication (ADR-027)
                await self._run_stage(db, job, "METRIC_DEDUPLICATION", self._run_dedup)

                # Stage 5: IR Compilation
                await self._run_stage(db, job, "IR_COMPILE", self._run_ir_compile)

                # Stage 6: AI Translation (low-confidence fallback)
                await self._run_stage(db, job, "AI_TRANSLATE", self._run_ai_translate)

                # Stage 7: Visualization Planning
                await self._run_stage(db, job, "VIZ", self._run_viz)

                # Stage 8: Hyper Extract Building
                await self._run_stage(db, job, "HYPER_BUILD", self._run_hyper)

                # Stage 9: Datasource XML Emission
                await self._run_stage(db, job, "DATASOURCE_EMIT", self._run_ds_emit)

                # Stage 10: Workbook Emission (Staging)
                await self._run_stage(db, job, "WORKBOOK_EMIT_STAGING", self._run_wb_emit_staging)

                # Stage 11: Staging Publication
                await self._run_stage(db, job, "STAGING_PUBLISH", self._run_staging_publish)

                # Stage 12: Multi-Gate Validation
                await self._run_stage(db, job, "STATIC_VALIDATE", self._run_static_validate)
                await self._run_stage(db, job, "SECURITY_VALIDATE", self._run_security_validate)
                await self._run_stage(db, job, "NUMERIC_VALIDATE", self._run_numeric_validate)

                # ── Phase 2: Production Promotion ────────────────────

                # Check scorecard for auto-publish eligibility
                if job.auto_publish:
                    await self._run_stage(db, job, "WORKBOOK_EMIT_PRODUCTION", self._run_wb_emit_prod)
                    await self._run_stage(db, job, "PROMOTE", self._run_promote)
                    await self._run_stage(db, job, "RECONCILE", self._run_reconcile)

                # Final report generation
                await self._run_stage(db, job, "REPORT", self._run_report)

                # Mark complete
                job.status = "COMPLETE"
                job.completed_at = datetime.now(timezone.utc)
                db.commit()
                logger.info("Pipeline complete for job %s", self.job_id)

            except Exception as e:
                job.status = "FAILED"
                job.error_message = str(e)[:2000]
                job.completed_at = datetime.now(timezone.utc)
                db.commit()
                logger.error(
                    "Pipeline failed for job %s at stage %s: %s",
                    self.job_id,
                    job.current_stage,
                    traceback.format_exc(),
                )

        finally:
            db.close()

    async def _run_stage(self, db: Session, job: Job, stage: str, handler):
        """Execute a single pipeline stage with state tracking."""
        # Check if job was cancelled
        db.refresh(job)
        if job.status == "CANCELLED":
            raise RuntimeError("Job cancelled")

        # Skip if we're resuming past this stage
        if job.checkpoint_stage and PIPELINE_STAGES.index(stage) <= PIPELINE_STAGES.index(job.checkpoint_stage):
            logger.info("Skipping already-completed stage: %s", stage)
            return

        logger.info("Starting stage: %s", stage)
        job.current_stage = stage
        job.status = stage
        db.commit()

        await handler(db, job)

        # Mark checkpoint for crash recovery
        job.checkpoint_stage = stage
        db.commit()
        logger.info("Completed stage: %s", stage)

    # ── Stage Handlers ───────────────────────────────────────────

    async def _run_discovery(self, db: Session, job: Job):
        from app.agents.discovery import DiscoveryAgent
        agent = DiscoveryAgent(db=db, job=job)
        await agent.run(selected_dossier_ids=self.selected_dossier_ids)

    async def _run_graph(self, db: Session, job: Job):
        from app.agents.graph import DependencyGraph
        graph = DependencyGraph(db=db, job=job)
        graph.build()

    async def _run_semantic(self, db: Session, job: Job):
        # TODO: Implement SemanticAgent (Agent 3)
        logger.info("SemanticAgent: placeholder — extracting typed definitions")

    async def _run_dedup(self, db: Session, job: Job):
        # TODO: Implement SemanticFingerprint deduplication (ADR-027, Wave 4)
        logger.info("MetricDeduplication: placeholder — fingerprinting & caption registry")

    async def _run_ir_compile(self, db: Session, job: Job):
        # TODO: Implement IRCompilerAgent (Agent 4)
        logger.info("IRCompiler: placeholder — compiling BI-IR JSON")

    async def _run_ai_translate(self, db: Session, job: Job):
        # TODO: Implement AITranslationAgent (Agent 5)
        logger.info("AITranslation: placeholder — 3-tier fallback for low-confidence")

    async def _run_viz(self, db: Session, job: Job):
        # TODO: Implement VisualizationAgent (Agent 6)
        logger.info("VisualizationAgent: placeholder — mark type & shelf planning")

    async def _run_hyper(self, db: Session, job: Job):
        # TODO: Implement HyperAgent (Agent 7)
        logger.info("HyperAgent: placeholder — streaming chunked extraction & build")

    async def _run_ds_emit(self, db: Session, job: Job):
        # TODO: Implement datasource XML emission
        logger.info("DatasourceEmit: placeholder — TDS XML generation")

    async def _run_wb_emit_staging(self, db: Session, job: Job):
        # TODO: Implement TableauEmitterAgent (Agent 8) — staging emit
        logger.info("WorkbookEmitStaging: placeholder — TWB XML with staging paths")

    async def _run_staging_publish(self, db: Session, job: Job):
        # TODO: Implement PublishAgent staging phase (Agent 10)
        logger.info("StagingPublish: placeholder — publish to _migration_staging")

    async def _run_static_validate(self, db: Session, job: Job):
        # TODO: Implement ValidationAgent static checks (Agent 9)
        logger.info("StaticValidation: placeholder — XSD, row counts, filter sets")

    async def _run_security_validate(self, db: Session, job: Job):
        # TODO: Implement security impersonation testing (ADR-031)
        logger.info("SecurityValidation: placeholder — Connected App JWT impersonation")

    async def _run_numeric_validate(self, db: Session, job: Job):
        # TODO: Implement numeric parity gate (ADR-030)
        logger.info("NumericValidation: placeholder — KPI parity ≤ 0.1%%")

    async def _run_wb_emit_prod(self, db: Session, job: Job):
        # TODO: Implement TableauEmitterAgent — production emit (ADR-023)
        logger.info("WorkbookEmitProduction: placeholder — TWB XML with production paths")

    async def _run_promote(self, db: Session, job: Job):
        # TODO: Implement PublishAgent production promotion (ADR-029)
        logger.info("Promote: placeholder — production write-lock → publish → reconcile")

    async def _run_reconcile(self, db: Session, job: Job):
        # TODO: Implement remote reconciliation
        logger.info("Reconcile: placeholder — verify production publish via REST hash")

    async def _run_report(self, db: Session, job: Job):
        # TODO: Implement report generation
        logger.info("Report: placeholder — Excel/PDF migration report generation")


async def run_pipeline(job_id: str, selected_dossier_ids: Optional[list[str]] = None):
    """Entry point for background pipeline execution."""
    orchestrator = PipelineOrchestrator(job_id, selected_dossier_ids)
    await orchestrator.run()
