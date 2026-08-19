"""
SemanticAgent — Typed definition extraction and expression AST harvesting.

Ref: spec/agents.md §Agent 3
Step 3 Review Board: Multi-form attributes, dimty extraction, conditionality,
                     semi-additive fact detection, security filter predicates.

Responsibilities:
  1. For each wave's objects, extract typed definitions from MSTR
  2. Parse metric expression trees into ASTs
  3. Extract dimensionality (dimty) hints for LOD mapping
  4. Detect blocked/unsupported metric types
  5. Assign initial confidence scores
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.job import Job
from app.models.objects import Issue, MigrationObject, SemanticFingerprint
from app.services.mstr_client.session import AsyncMSTRSession, MSTRAPIError

logger = logging.getLogger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Data structures
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@dataclass
class DimensionDef:
    """Extracted attribute definition with all forms."""
    mstr_id: str
    name: str
    forms: list[dict]          # [{form_name, form_id, data_type, is_pk}]
    id_form: Optional[str] = None
    desc_form: Optional[str] = None
    compound_key: Optional[list[str]] = None
    relationships: list[str] = field(default_factory=list)


@dataclass
class FactDef:
    """Extracted fact definition with column mapping."""
    mstr_id: str
    name: str
    data_type: str
    expressions: list[dict]
    tables: list[str] = field(default_factory=list)


@dataclass
class MeasureDef:
    """Extracted metric definition with expression AST and dimty."""
    mstr_id: str
    name: str
    expression_ast: Optional[dict] = None
    expression_text: Optional[str] = None
    dimty: Optional[dict] = None            # dimensionality spec
    conditionality: Optional[dict] = None   # filter conditions
    subtotal_type: Optional[str] = None     # SUM, LAST, FIRST, etc.
    format_spec: Optional[dict] = None
    thresholds: Optional[list] = None
    dependencies: list[str] = field(default_factory=list)
    confidence: float = 0.0
    blocked: bool = False
    block_reason: Optional[str] = None


@dataclass
class FilterDef:
    """Extracted filter definition with predicate AST."""
    mstr_id: str
    name: str
    predicate_ast: Optional[dict] = None
    qualification_type: Optional[str] = None
    is_security_filter: bool = False


@dataclass
class SemanticBundle:
    """Complete semantic extraction output for a wave."""
    dimensions: list[DimensionDef] = field(default_factory=list)
    facts: list[FactDef] = field(default_factory=list)
    measures: list[MeasureDef] = field(default_factory=list)
    filters: list[FilterDef] = field(default_factory=list)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Confidence scoring rules
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

UNSUPPORTED_METRIC_SUBTYPES = {"training", "extreme", "relationship"}

# Known MSTR aggregation function names
SIMPLE_AGGREGATIONS = {"Sum", "Count", "Avg", "Min", "Max", "Median", "Stdev", "Var"}


class SemanticAgent:
    """
    Agent 3: Extracts typed definitions and expression ASTs from MSTR objects.

    Processes each wave's objects through the MSTR Model API to produce
    a SemanticBundle consumed by the IRCompiler.
    """

    def __init__(
        self,
        db: Session,
        job: Job,
        mstr: AsyncMSTRSession,
    ):
        self.db = db
        self.job = job
        self.mstr = mstr

    async def run(self, object_ids: list[str]) -> SemanticBundle:
        """
        Extract semantic definitions for the given object IDs.

        Args:
            object_ids: MSTR GUIDs to process in this wave.

        Returns:
            SemanticBundle containing all typed definitions.
        """
        bundle = SemanticBundle()

        objects = (
            self.db.query(MigrationObject)
            .filter(
                MigrationObject.job_id == self.job.id,
                MigrationObject.mstr_id.in_(object_ids),
            )
            .all()
        )

        for obj in objects:
            try:
                if obj.type_name == "attribute":
                    dim = await self._extract_attribute(obj)
                    bundle.dimensions.append(dim)
                    obj.confidence = 0.95
                    obj.status = "extracted"

                elif obj.type_name == "fact":
                    fact = await self._extract_fact(obj)
                    bundle.facts.append(fact)
                    obj.confidence = 0.95
                    obj.status = "extracted"

                elif obj.type_name == "metric":
                    measure = await self._extract_metric(obj)
                    bundle.measures.append(measure)
                    obj.confidence = measure.confidence
                    obj.status = "blocked" if measure.blocked else "extracted"
                    obj.expression_text = measure.expression_text

                    if measure.blocked:
                        issue = Issue(
                            id=str(uuid.uuid4()),
                            job_id=self.job.id,
                            object_id=obj.id,
                            severity="blocker",
                            category=measure.block_reason or "unsupported_metric_type",
                            message=f"Metric '{obj.name}' blocked: {measure.block_reason}",
                        )
                        self.db.add(issue)
                        obj.blocker_count = (obj.blocker_count or 0) + 1

                elif obj.type_name == "filter":
                    flt = await self._extract_filter(obj)
                    bundle.filters.append(flt)
                    obj.confidence = 0.90
                    obj.status = "extracted"

                obj.compiled_at = datetime.now(timezone.utc)

            except MSTRAPIError as e:
                logger.error("Semantic extraction failed for %s: %s", obj.mstr_id, e)
                obj.status = "failed"
                obj.confidence = 0.0
                issue = Issue(
                    id=str(uuid.uuid4()),
                    job_id=self.job.id,
                    object_id=obj.id,
                    severity="blocker",
                    category="extraction_failed",
                    message=f"API error during extraction: {e}",
                )
                self.db.add(issue)

            self.job.objects_processed = (self.job.objects_processed or 0) + 1

        self.db.commit()
        return bundle

    # ── Attribute extraction ────────────────────────────────────

    async def _extract_attribute(self, obj: MigrationObject) -> DimensionDef:
        """Extract attribute with all forms (ID, DESC, compound keys)."""
        detail = obj.mstr_definition or await self.mstr.get_attribute(obj.mstr_id)

        forms_raw = detail.get("forms", []) if isinstance(detail, dict) else []
        forms = []
        id_form = None
        desc_form = None

        for f in forms_raw:
            if not isinstance(f, dict):
                continue
            raw_dt = f.get("dataType", "string")
            if isinstance(raw_dt, dict):
                data_type = raw_dt.get("type", "string")
            elif isinstance(raw_dt, str):
                data_type = raw_dt
            else:
                data_type = "string"

            form_name = f.get("name", "")
            form_id = f.get("id", "")
            form_entry = {
                "form_name": form_name,
                "form_id": form_id,
                "data_type": data_type,
                "is_pk": form_name.upper() in ("ID", "KEY"),
            }
            forms.append(form_entry)

            if form_name.upper() == "ID":
                id_form = form_id
            elif form_name.upper() in ("DESC", "DESCRIPTION"):
                desc_form = form_id

        # Fallback if no forms were explicitly defined (e.g. managed objects)
        if not forms:
            id_form = "1"
            desc_form = "2"
            forms = [
                {"form_name": "ID", "form_id": id_form, "data_type": "string", "is_pk": True},
                {"form_name": "DESC", "form_id": desc_form, "data_type": "string", "is_pk": False},
            ]

        # Detect compound keys
        compound_key = None
        pk_forms = [f for f in forms if f["is_pk"]]
        if len(pk_forms) > 1:
            compound_key = [f["form_id"] for f in pk_forms]

        # Extract relationships
        relationships = []
        if isinstance(detail, dict):
            for child in detail.get("relationships", []):
                if isinstance(child, dict):
                    child_id = child.get("relatedAttribute", {}).get("objectId")
                    if child_id:
                        relationships.append(child_id)

        return DimensionDef(
            mstr_id=obj.mstr_id,
            name=obj.name,
            forms=forms,
            id_form=id_form,
            desc_form=desc_form,
            compound_key=compound_key,
            relationships=relationships,
        )

    # ── Fact extraction ─────────────────────────────────────────

    async def _extract_fact(self, obj: MigrationObject) -> FactDef:
        """Extract fact definition with column mapping."""
        detail = obj.mstr_definition or await self.mstr.get_fact(obj.mstr_id)
        if not isinstance(detail, dict):
            detail = {}

        expressions = detail.get("expressions", [])
        raw_dt = detail.get("dataType", "numeric")
        if isinstance(raw_dt, dict):
            data_type = raw_dt.get("type", "numeric")
        elif isinstance(raw_dt, str):
            data_type = raw_dt
        else:
            data_type = "numeric"

        # Extract table references
        tables = []
        for expr in expressions:
            if isinstance(expr, dict):
                for tbl in expr.get("tables", []):
                    if isinstance(tbl, dict):
                        tbl_name = tbl.get("name", "")
                        if tbl_name:
                            tables.append(tbl_name)

        return FactDef(
            mstr_id=obj.mstr_id,
            name=obj.name,
            data_type=data_type,
            expressions=expressions,
            tables=list(set(tables)),
        )

    # ── Metric extraction ───────────────────────────────────────

    async def _extract_metric(self, obj: MigrationObject) -> MeasureDef:
        """
        Extract metric with expression tree, dimty, conditionality.

        Detects blocked types: training, extreme, relationship, derived elements,
        prompt-in-condition, and semi-additive facts.
        """
        detail = obj.mstr_definition or await self.mstr.get_metric(obj.mstr_id)
        if not isinstance(detail, dict):
            detail = {}

        # Expression AST
        expression = detail.get("expression")
        if isinstance(expression, dict):
            expression_ast = expression.get("tree", expression.get("tokens"))
            expression_text = expression.get("text")
        elif isinstance(expression, str):
            expression_ast = None
            expression_text = expression
        else:
            expression_ast = None
            expression_text = None

        # Dimensionality (dimty)
        dimty = detail.get("dimty", detail.get("dimensionality"))

        # Conditionality
        conditionality = detail.get("conditionality")

        # Subtotal type (semi-additive detection)
        subtotal_type = detail.get("subtotalType", "SUM")

        # Format
        format_spec = detail.get("format")

        # Thresholds
        thresholds = detail.get("thresholds", [])

        # Dependencies
        dependencies = []
        for ref in detail.get("references", []):
            ref_id = ref.get("id") or ref.get("objectId")
            if ref_id:
                dependencies.append(ref_id)

        # ── Blocked type detection ──────────────────────────

        blocked = False
        block_reason = None

        # Check for unsupported metric subtypes
        metric_subtype = detail.get("metricSubType", "").lower()
        if metric_subtype in UNSUPPORTED_METRIC_SUBTYPES:
            blocked = True
            block_reason = f"unsupported_metric_type:{metric_subtype}"

        # Check for derived elements
        if detail.get("derivedElements"):
            blocked = True
            block_reason = "derived_elements_present"

        # Check for prompt in condition
        if conditionality:
            cond_str = str(conditionality)
            if "prompt" in cond_str.lower():
                blocked = True
                block_reason = "prompt_in_condition"

        # ── Confidence scoring ──────────────────────────────

        confidence = self._score_metric_confidence(
            expression_ast, dimty, conditionality, subtotal_type, blocked
        )

        # Semi-additive warning
        if subtotal_type and subtotal_type.upper() not in ("SUM", ""):
            issue = Issue(
                id=str(uuid.uuid4()),
                job_id=self.job.id,
                object_id=obj.id,
                severity="warning",
                category="semi_additive_measure",
                message=f"Metric '{obj.name}' uses semi-additive subtotal '{subtotal_type}'",
            )
            self.db.add(issue)

        return MeasureDef(
            mstr_id=obj.mstr_id,
            name=obj.name,
            expression_ast=expression_ast,
            expression_text=expression_text,
            dimty=dimty,
            conditionality=conditionality,
            subtotal_type=subtotal_type,
            format_spec=format_spec,
            thresholds=thresholds,
            dependencies=dependencies,
            confidence=confidence,
            blocked=blocked,
            block_reason=block_reason,
        )

    def _score_metric_confidence(
        self,
        ast: Any,
        dimty: Any,
        conditionality: Any,
        subtotal_type: Optional[str],
        blocked: bool,
    ) -> float:
        """Assign confidence score based on complexity signals."""
        if blocked:
            return 0.0

        score = 1.0

        # Complex expression tree
        if ast and isinstance(ast, dict):
            depth = self._tree_depth(ast)
            if depth > 5:
                score -= 0.15
            elif depth > 3:
                score -= 0.05

        # Dimty presence = LOD complexity
        if dimty:
            score -= 0.10

        # Conditionality
        if conditionality:
            score -= 0.10

        # Semi-additive
        if subtotal_type and subtotal_type.upper() not in ("SUM", ""):
            score -= 0.10

        # No expression at all
        if not ast:
            score -= 0.20

        return max(round(score, 2), 0.10)

    def _tree_depth(self, node: Any, depth: int = 0) -> int:
        """Calculate AST tree depth."""
        if not isinstance(node, dict):
            return depth
        children = node.get("children", [])
        if not children:
            return depth
        return max(self._tree_depth(c, depth + 1) for c in children)

    # ── Filter extraction ───────────────────────────────────────

    async def _extract_filter(self, obj: MigrationObject) -> FilterDef:
        """Extract filter definition with predicate AST."""
        detail = obj.mstr_definition or await self.mstr.get_filter(obj.mstr_id)
        if not isinstance(detail, dict):
            detail = {}

        predicate = detail.get("expression")
        if isinstance(predicate, dict):
            predicate_ast = predicate.get("tree", predicate.get("tokens"))
        else:
            predicate_ast = None

        qualification = detail.get("qualificationType", "unknown")

        return FilterDef(
            mstr_id=obj.mstr_id,
            name=obj.name,
            predicate_ast=predicate_ast,
            qualification_type=qualification,
            is_security_filter="security" in detail.get("type", "").lower(),
        )
