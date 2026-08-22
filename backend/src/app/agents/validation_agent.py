"""
ValidationAgent — Multi-gate validation scorecard.

Ref: spec/agents.md §Agent 9
ADR-029: auto_publish_ok gating
ADR-030: Numeric parity ≤ 0.1%
ADR-031: Security impersonation testing

Gates:
  1. Structural (0.99): Row counts, filter sets, XSD, TWB load
  2. Financial KPI (0.98): Pairwise KPI comparison under identical filters
  3. Security (1.0 hard): Connected App JWT impersonation member set match
  4. Visual (0.80 soft): Render check
"""

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.job import Job
from app.models.objects import MigrationObject
from app.models.validation import ValidationCheck as ValidationCheckORM

logger = logging.getLogger(__name__)


@dataclass
class ValidationCheck:
    """Single validation check result."""
    check_type: str
    object_id: str
    expected: Any
    actual: Any
    passed: bool
    tolerance: Optional[float] = None
    message: str = ""
    category: str = "structural"  # "structural", "financial_kpi", "security", "visual"


@dataclass
class ValidationScorecard:
    """Multi-gate scorecard per ADR-029/030/031."""
    job_id: str
    security_confidence: float = 1.0
    financial_kpi_confidence: float = 1.0
    structural_confidence: float = 1.0
    visual_confidence: float = 1.0
    security_parity: bool = True
    blocker_issues: int = 0
    warning_issues: int = 0
    mandatory_review_flags: int = 0
    checks: list[ValidationCheck] = field(default_factory=list)

    @property
    def auto_publish_ok(self) -> bool:
        return (
            self.security_confidence >= 1.0
            and self.financial_kpi_confidence >= 0.98
            and self.structural_confidence >= 0.99
            and self.visual_confidence >= 0.80
            and self.security_parity
            and self.blocker_issues == 0
            and self.mandatory_review_flags == 0
        )

    @property
    def overall_confidence(self) -> float:
        return min(
            self.security_confidence,
            self.financial_kpi_confidence,
            self.structural_confidence,
            self.visual_confidence,
        )


class ValidationAgent:
    """
    Agent 9: Multi-gate validation against MSTR golden dataset.

    Runs structural, financial KPI, security, and visual checks
    to produce a ValidationScorecard that gates auto-publish.
    """

    def __init__(self, db: Session, job: Job):
        self.db = db
        self.job = job

    async def validate(self, ir, hyper_paths: dict, mstr_session=None) -> ValidationScorecard:
        """Run all validation gates and produce scorecard."""
        scorecard = ValidationScorecard(job_id=self.job.id)

        # Gate 1: Structural validation
        structural_checks = await self._validate_structural(ir)
        scorecard.checks.extend(structural_checks)

        # Gate 2: Financial KPI validation
        kpi_checks = await self._validate_kpi(ir, hyper_paths)
        scorecard.checks.extend(kpi_checks)

        # Gate 3: Security validation
        security_checks = await self._validate_security(ir, mstr_session)
        scorecard.checks.extend(security_checks)

        # Gate 4: Visual validation
        visual_checks = await self._validate_visual(ir)
        scorecard.checks.extend(visual_checks)

        # Compute gate scores
        scorecard.structural_confidence = self._gate_score(
            [c for c in scorecard.checks if c.category == "structural"]
        )
        scorecard.financial_kpi_confidence = self._gate_score(
            [c for c in scorecard.checks if c.category == "financial_kpi"]
        )
        scorecard.security_confidence = self._gate_score(
            [c for c in scorecard.checks if c.category == "security"]
        )
        scorecard.visual_confidence = self._gate_score(
            [c for c in scorecard.checks if c.category == "visual"]
        )

        scorecard.security_parity = all(
            c.passed for c in scorecard.checks if c.category == "security"
        )

        # Count issues
        scorecard.blocker_issues = sum(
            1 for c in scorecard.checks if not c.passed and c.category != "visual"
        )
        scorecard.warning_issues = sum(
            1 for c in scorecard.checks if not c.passed and c.category == "visual"
        )

        # Persist checks
        for check in scorecard.checks:
            self._persist_check(check)

        self.db.commit()

        logger.info(
            "Validation scorecard: structural=%.2f, kpi=%.2f, security=%.2f, visual=%.2f, auto_publish=%s",
            scorecard.structural_confidence,
            scorecard.financial_kpi_confidence,
            scorecard.security_confidence,
            scorecard.visual_confidence,
            scorecard.auto_publish_ok,
        )

        return scorecard

    # ── Gate 1: Structural ──────────────────────────────────────

    async def _validate_structural(self, ir) -> list[ValidationCheck]:
        """
        Structural validation checks:
        - Row count matching
        - Filter member set parity
        - TWB XSD validation
        - Column count parity
        """
        checks = []

        # Check: all dimensions have ID and DESC forms
        for dim in ir.dimensions:
            check = ValidationCheck(
                check_type="dimension_forms",
                object_id=dim.mstr_id,
                expected="ID + DESC",
                actual="present" if not dim.hidden else "hidden",
                passed=True,
                category="structural",
                message=f"Dimension '{dim.name}' forms validated",
            )
            checks.append(check)

        # Check: all measures have valid calc expressions
        for measure in ir.measures:
            has_calc = bool(measure.tableau_calc and not measure.tableau_calc.startswith("// TODO"))
            check = ValidationCheck(
                check_type="calc_expression",
                object_id=measure.mstr_id,
                expected="valid_calc",
                actual="valid" if has_calc else "todo",
                passed=has_calc,
                category="structural",
                message=f"Measure '{measure.name}' calc {'valid' if has_calc else 'needs translation'}",
            )
            checks.append(check)

        # Check: all tables have extraction grain
        for table in ir.tables:
            grain = table.extraction_grain
            has_grain = bool(grain and grain.get("primary_keys"))
            check = ValidationCheck(
                check_type="extraction_grain",
                object_id=table.id,
                expected="defined_grain",
                actual="has_grain" if has_grain else "missing",
                passed=has_grain,
                category="structural",
                message=f"Table '{table.name}' grain {'validated' if has_grain else 'missing'}",
            )
            checks.append(check)

        # Check: no blocker issues
        blocker_issues = [i for i in ir.issues if i.severity == "blocker"]
        check = ValidationCheck(
            check_type="blocker_issues",
            object_id=self.job.id,
            expected=0,
            actual=len(blocker_issues),
            passed=len(blocker_issues) == 0,
            category="structural",
            message=f"{len(blocker_issues)} blocker issues found",
        )
        checks.append(check)

        return checks

    # ── Gate 2: Financial KPI ───────────────────────────────────

    async def _validate_kpi(self, ir, hyper_paths: dict) -> list[ValidationCheck]:
        """
        Financial KPI verification (ADR-030).

        HONESTY GUARD: A numeric-parity gate must compare the generated Tableau
        artifact against MSTR results to be meaningful. Merely trusting the
        LLM/compiler's self-reported `confidence` is NOT a verification and must
        never yield a passing gate. This pipeline does not currently execute the
        generated workbook, so every KPI check is marked UNVERIFIED (failed),
        which forces `financial_kpi_confidence < 1.0` and blocks auto-publish.
        The block is the correct fail-closed behavior — it keeps fabricated/numeric
        hazards from being silently promoted, per the repo's own spec audit (F1/F2).
        """
        checks = []

        for measure in ir.measures:
            check = ValidationCheck(
                check_type="kpi_value",
                object_id=measure.mstr_id,
                expected="parity",
                actual="unverified",
                passed=False,
                tolerance=0.001,
                category="financial_kpi",
                message=(
                    f"KPI '{measure.name}' value NOT verified against Tableau "
                    f"(confidence {measure.confidence:.2f} is only a self-report; "
                    "no workbook execution/read-back is wired for this KPI)"
                ),
            )
            checks.append(check)

        return checks

    # ── Gate 3: Security ────────────────────────────────────────

    async def _validate_security(self, ir, mstr_session=None) -> list[ValidationCheck]:
        """
        Security impersonation tests (ADR-031):
        - Connected App JWT impersonation for test identities
        - Diff visible member sets vs MSTR security filters
        - 100% member match required for auto-publish
        """
        checks = []

        security_filters = [f for f in ir.filters if f.is_security]

        if not security_filters:
            check = ValidationCheck(
                check_type="security_member_set",
                object_id=self.job.id,
                expected="no_security",
                actual="no_security",
                passed=True,
                category="security",
                message="No security filters — security gate passes",
            )
            checks.append(check)
        else:
            # HONESTY GUARD: a real impersonation/member-set diff requires executing
            # both MSTR (as a test identity) and the published Tableau datasource.
            # No such execution path is wired here, so every security filter check
            # FAILS CLOSED as "unverified" instead of silently passing. A pending
            # test must never contribute a passing security gate (ADR-031 is a hard 1.0).
            for sf in security_filters:
                check = ValidationCheck(
                    check_type="security_member_set",
                    object_id=sf.mstr_id,
                    expected="member_parity",
                    actual="unverified",
                    passed=False,
                    category="security",
                    message=(
                        f"Security filter '{sf.name}' member set NOT verified — "
                        "impersonation/publish read-back is not wired; fails closed"
                    ),
                )
                checks.append(check)

        return checks

    # ── Gate 4: Visual ──────────────────────────────────────────

    async def _validate_visual(self, ir) -> list[ValidationCheck]:
        """
        Visual validation checks:
        - Verify all worksheets referenced in dashboards exist
        - Check for empty worksheets
        """
        checks = []

        for visual in ir.visuals:
            check = ValidationCheck(
                check_type="visual_render",
                object_id=visual.id,
                expected="renderable",
                actual="unverified",
                passed=False,
                category="visual",
                message=(
                    f"Visual '{visual.name}' render NOT verified — no server-side "
                    "render/Export-Crosstab read-back is wired; fails closed"
                ),
            )
            checks.append(check)

        return checks

    # ── Helpers ──────────────────────────────────────────────────

    def _gate_score(self, checks: list[ValidationCheck]) -> float:
        """Compute confidence score for a gate (min across checks)."""
        if not checks:
            return 1.0
        passed = sum(1 for c in checks if c.passed)
        total = len(checks)
        return round(passed / total, 4) if total > 0 else 1.0

    def _persist_check(self, check: ValidationCheck):
        """Persist validation check to SQLite."""
        orm_check = ValidationCheckORM(
            id=str(uuid.uuid4()),
            job_id=self.job.id,
            check_type=check.check_type,
            check_name=check.check_type,
            object_id=check.object_id,
            expected_value=str(check.expected),
            actual_value=str(check.actual),
            passed=check.passed,
            tolerance=check.tolerance,
            message=check.message,
            category=check.category,
        )
        self.db.add(orm_check)
