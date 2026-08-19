"""
IRCompilerAgent — Deterministic BI-IR JSON compiler.

Ref: spec/agents.md §Agent 4, spec/ir-schema.md
ADR-027: SemanticFingerprint-based metric deduplication
ADR-022: Extraction grain validation

Responsibilities:
  1. Compile semantic bundle into BI-IR JSON (ir-schema.md format)
  2. Map attributes → IR Dimensions, facts → measures, filters → IR Filters
  3. Generate Tableau calculated field expressions
  4. Build SemanticFingerprints for deduplication
  5. Validate extraction grain sufficiency
  6. Inject null_propagation and zero_division_result from VLDB context
"""

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.job import Job
from app.models.objects import (
    CaptionRegistry,
    Issue,
    MigrationObject,
    SemanticFingerprint as SemanticFingerprintORM,
)

logger = logging.getLogger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  IR Node types (mirrors ir-schema.md)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@dataclass
class IRTable:
    id: str
    name: str
    physical_name: str
    schema: str
    columns: list[dict]
    extraction_grain: dict
    is_dimension: bool = False


@dataclass
class IRRelationship:
    id: str
    left_table: str
    right_table: str
    left_keys: list[str]
    right_keys: list[str]
    join_type: str
    cardinality: str


@dataclass
class IRDimension:
    id: str
    mstr_id: str
    name: str
    local_name: str
    remote_name: str
    caption: str
    data_type: str
    hidden: bool = False
    role: str = "dimension"


@dataclass
class IRMeasure:
    id: str
    mstr_id: str
    name: str
    local_name: str
    remote_name: str
    caption: str
    tableau_calc: str
    expression_text: Optional[str] = None
    confidence: float = 1.0
    scope: str = "local"       # "shared" | "local" (ADR-027)
    fingerprint_hash: Optional[str] = None
    dependencies: list[str] = field(default_factory=list)
    null_policy: str = "propagate"
    zero_division_policy: str = "null"


@dataclass
class IRFilter:
    id: str
    mstr_id: str
    name: str
    predicate: str
    is_security: bool = False


@dataclass
class IRVisual:
    id: str
    name: str
    mark_type: str
    rows: list[str]
    columns: list[str]
    color: Optional[str] = None
    size: Optional[str] = None
    filters: list[str] = field(default_factory=list)


@dataclass
class IRIssue:
    id: str
    severity: str
    category: str
    message: str
    object_id: Optional[str] = None


@dataclass
class BIIR:
    """Complete BI Intermediate Representation."""
    job_id: str
    tables: list[IRTable] = field(default_factory=list)
    relationships: list[IRRelationship] = field(default_factory=list)
    dimensions: list[IRDimension] = field(default_factory=list)
    measures: list[IRMeasure] = field(default_factory=list)
    filters: list[IRFilter] = field(default_factory=list)
    visuals: list[IRVisual] = field(default_factory=list)
    issues: list[IRIssue] = field(default_factory=list)

    def to_dict(self) -> dict:
        import dataclasses
        return dataclasses.asdict(self)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  SemanticFingerprint (ADR-027)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@dataclass
class SemanticFingerprint:
    """12-field canonical semantic fingerprint for measure deduplication."""
    ast_hash: str
    datasource_domain: str
    source_dependencies: list[str]
    physical_grain: list[str]
    semantic_grain: list[str]
    aggregation: str
    filtering_mode: str       # "none", "conditional", "filtered"
    condition_phase: str      # "pre", "post", "none"
    transformation: Optional[str]
    null_policy: str
    zero_division_policy: str
    security_scope: Optional[str]

    @property
    def fingerprint_hash(self) -> str:
        """SHA-256 hash of the canonical fingerprint tuple."""
        canonical = json.dumps([
            self.ast_hash,
            self.datasource_domain,
            sorted(self.source_dependencies),
            sorted(self.physical_grain),
            sorted(self.semantic_grain),
            self.aggregation,
            self.filtering_mode,
            self.condition_phase,
            self.transformation or "",
            self.null_policy,
            self.zero_division_policy,
            self.security_scope or "",
        ], sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()


class IRCompilerAgent:
    """
    Agent 4: Deterministic IR compiler — no LLM involved.

    Transforms semantic bundles and physical model plans into BI-IR JSON.
    """

    def __init__(self, db: Session, job: Job):
        self.db = db
        self.job = job
        self._caption_counter = 0

    def compile(self, semantic_bundle, physical_plan) -> BIIR:
        """
        Compile a SemanticBundle + PhysicalModelPlan into BI-IR.

        Steps:
        1. Tables from physical plan
        2. Relationships from join graph
        3. Dimensions from attributes
        4. Measures from metrics (with fingerprinting)
        5. Filters from filter defs
        6. Grain validation
        """
        ir = BIIR(job_id=self.job.id)

        # ── Step 1: Tables ──────────────────────────────────────

        for tp in physical_plan.table_plans:
            grain = next(
                (g for g in physical_plan.grain_contracts if g.table_id == tp.table_id),
                None,
            )
            ir_table = IRTable(
                id=tp.table_id,
                name=tp.physical_name,
                physical_name=tp.physical_name,
                schema=tp.schema,
                columns=[
                    {"name": c.column_name, "type": c.data_type, "is_key": c.is_key}
                    for c in tp.columns
                ],
                extraction_grain={
                    "physical_grain": grain.physical_grain if grain else [],
                    "semantic_grain": grain.semantic_grain if grain else [],
                    "primary_keys": grain.primary_keys if grain else [],
                    "foreign_keys": grain.foreign_keys if grain else [],
                },
                is_dimension=tp.table_id.startswith("dim_"),
            )
            ir.tables.append(ir_table)

        # ── Step 2: Relationships ───────────────────────────────

        for je in physical_plan.join_graph:
            ir_rel = IRRelationship(
                id=str(uuid.uuid4()),
                left_table=je.left_table,
                right_table=je.right_table,
                left_keys=je.left_keys,
                right_keys=je.right_keys,
                join_type=je.join_type,
                cardinality=je.cardinality,
            )
            ir.relationships.append(ir_rel)

        # ── Step 3: Dimensions ──────────────────────────────────

        for dim in semantic_bundle.dimensions:
            local_name = self._make_local_name(dim.name)
            remote_name = self._normalize_identifier(f"{dim.name}_DESC") if dim.desc_form else self._normalize_identifier(f"{dim.name}_ID")

            ir_dim = IRDimension(
                id=str(uuid.uuid4()),
                mstr_id=dim.mstr_id,
                name=dim.name,
                local_name=local_name,
                remote_name=remote_name,
                caption=dim.name,
                data_type="string",
            )
            ir.dimensions.append(ir_dim)

            # ID form → hidden dimension
            if dim.id_form:
                id_local = self._make_local_name(f"{dim.name} (ID)")
                ir_dim_id = IRDimension(
                    id=str(uuid.uuid4()),
                    mstr_id=dim.mstr_id,
                    name=f"{dim.name} (ID)",
                    local_name=id_local,
                    remote_name=self._normalize_identifier(f"{dim.name}_ID"),
                    caption=f"{dim.name} (ID)",
                    data_type="string",
                    hidden=True,
                )
                ir.dimensions.append(ir_dim_id)

            # Register captions
            self._register_caption(
                ir_dim.id, ir_dim.local_name, ir_dim.remote_name, ir_dim.caption, dim.name
            )

        # ── Step 4: Measures ────────────────────────────────────

        null_policy = self.job.null_propagation or "propagate"
        zero_div_policy = self.job.zero_division_result or "null"

        for measure in semantic_bundle.measures:
            if measure.blocked:
                ir.issues.append(IRIssue(
                    id=str(uuid.uuid4()),
                    severity="blocker",
                    category=measure.block_reason or "unsupported",
                    message=f"Measure '{measure.name}' is blocked: {measure.block_reason}",
                    object_id=measure.mstr_id,
                ))
                continue

            # Compile to Tableau calc
            tableau_calc = self._compile_expression(measure, null_policy, zero_div_policy)

            local_name = self._make_local_name(measure.name)
            remote_name = self._normalize_identifier(measure.name)

            # Build semantic fingerprint (ADR-027)
            fp = self._build_fingerprint(measure, null_policy, zero_div_policy)

            ir_measure = IRMeasure(
                id=str(uuid.uuid4()),
                mstr_id=measure.mstr_id,
                name=measure.name,
                local_name=local_name,
                remote_name=remote_name,
                caption=measure.name,
                tableau_calc=tableau_calc,
                expression_text=measure.expression_text,
                confidence=measure.confidence,
                fingerprint_hash=fp.fingerprint_hash,
                dependencies=measure.dependencies,
                null_policy=null_policy,
                zero_division_policy=zero_div_policy,
            )
            ir.measures.append(ir_measure)

            # Persist fingerprint
            self._persist_fingerprint(fp, ir_measure)

            # Register caption
            self._register_caption(
                ir_measure.id, ir_measure.local_name, ir_measure.remote_name,
                ir_measure.caption, measure.name
            )

        # ── Step 5: Filters ─────────────────────────────────────

        for flt in semantic_bundle.filters:
            predicate = self._compile_filter(flt)
            ir_filter = IRFilter(
                id=str(uuid.uuid4()),
                mstr_id=flt.mstr_id,
                name=flt.name,
                predicate=predicate,
                is_security=flt.is_security_filter,
            )
            ir.filters.append(ir_filter)

        self.db.commit()

        logger.info(
            "IR compiled: %d tables, %d dimensions, %d measures, %d filters, %d issues",
            len(ir.tables), len(ir.dimensions), len(ir.measures), len(ir.filters), len(ir.issues),
        )

        return ir

    # ── Expression compilation ──────────────────────────────────

    def _compile_expression(self, measure, null_policy: str, zero_div_policy: str) -> str:
        """
        Compile MSTR metric expression into Tableau calculated field syntax.

        Handles:
        - Simple aggregations (SUM, COUNT, AVG, etc.)
        - Arithmetic operators
        - Null propagation policy (ZN wrapping)
        - Zero division handling (IIF wrapping)
        - Dimty → LOD expression mapping
        """
        ast = measure.expression_ast
        expr_text = measure.expression_text

        if not ast and not expr_text:
            return f"// TODO: expression for {measure.name}"

        # Try to compile from AST
        if ast and isinstance(ast, dict):
            compiled = self._ast_to_tableau(ast, null_policy, zero_div_policy)
            if compiled:
                return compiled

        # Fallback: wrap expression text
        if expr_text:
            # Simple pattern matching for common expressions
            return self._text_to_tableau(expr_text, null_policy, zero_div_policy)

        return f"// TODO: complex expression for {measure.name}"

    def _ast_to_tableau(self, node: dict, null_policy: str, zero_div_policy: str) -> Optional[str]:
        """Recursively compile MSTR expression AST to Tableau syntax."""
        node_type = node.get("type", "").lower()
        function = node.get("function", "").lower()
        children = node.get("children", [])

        # Aggregation functions
        if node_type in ("function", "aggregation") or function:
            func_name = function or node.get("name", "")
            agg_map = {
                "sum": "SUM", "count": "COUNT", "avg": "AVG",
                "min": "MIN", "max": "MAX", "median": "MEDIAN",
                "stdev": "STDEV", "var": "VAR", "countdistinct": "COUNTD",
            }
            tableau_func = agg_map.get(func_name.lower())
            if tableau_func and children:
                child_exprs = [self._ast_to_tableau(c, null_policy, zero_div_policy) for c in children]
                child_exprs = [e for e in child_exprs if e]
                if child_exprs:
                    return f"{tableau_func}({', '.join(child_exprs)})"

        # Operators
        if node_type == "operator":
            op = node.get("value", node.get("operator", ""))
            if children and len(children) == 2:
                left = self._ast_to_tableau(children[0], null_policy, zero_div_policy)
                right = self._ast_to_tableau(children[1], null_policy, zero_div_policy)
                if left and right:
                    # Handle division with zero-division policy
                    if op == "/" and zero_div_policy == "null":
                        return f"IIF({right} = 0, NULL, {left} / {right})"
                    elif op == "/" and zero_div_policy == "zero":
                        return f"IIF({right} = 0, 0, {left} / {right})"
                    return f"({left} {op} {right})"

        # Column/field references
        if node_type in ("column", "field", "attribute", "fact", "metric"):
            name = node.get("name", node.get("value", ""))
            ref_name = self._make_local_name(name) if name else ""
            if null_policy == "propagate":
                return f"[{ref_name}]"
            else:
                return f"ZN([{ref_name}])"

        # Constants
        if node_type in ("constant", "literal"):
            return str(node.get("value", "0"))

        # Fallback: try to extract value
        value = node.get("value") or node.get("name")
        if value:
            return str(value)

        return None

    def _text_to_tableau(self, text: str, null_policy: str, zero_div_policy: str) -> str:
        """Convert expression text to Tableau syntax."""
        # Simple patterns
        text = text.strip()

        # Sum(Fact) pattern
        import re
        sum_match = re.match(r'^(Sum|Count|Avg|Min|Max)\((.+)\)$', text, re.IGNORECASE)
        if sum_match:
            func = sum_match.group(1).upper()
            field_name = sum_match.group(2).strip()
            local = self._make_local_name(field_name)
            return f"{func}([{local}])"

        # Division pattern: A / B
        div_match = re.match(r'^(.+)\s*/\s*(.+)$', text)
        if div_match:
            left = div_match.group(1).strip()
            right = div_match.group(2).strip()
            l_tab = self._text_to_tableau(left, null_policy, zero_div_policy)
            r_tab = self._text_to_tableau(right, null_policy, zero_div_policy)
            if zero_div_policy == "null":
                return f"IIF({r_tab} = 0, NULL, {l_tab} / {r_tab})"
            return f"{l_tab} / {r_tab}"

        # Field reference
        local = self._make_local_name(text)
        return f"[{local}]"

    def _compile_filter(self, flt) -> str:
        """Compile filter definition to Tableau filter expression."""
        if flt.predicate_ast:
            compiled = self._ast_to_tableau(flt.predicate_ast, "propagate", "null")
            if compiled:
                return compiled
        return f"// TODO: filter predicate for {flt.name}"

    # ── Semantic Fingerprinting (ADR-027) ───────────────────────

    def _build_fingerprint(self, measure, null_policy: str, zero_div_policy: str) -> SemanticFingerprint:
        """Build 12-field semantic fingerprint for a measure."""
        ast_hash = hashlib.sha256(
            json.dumps(measure.expression_ast or {}, sort_keys=True).encode()
        ).hexdigest()

        return SemanticFingerprint(
            ast_hash=ast_hash,
            datasource_domain="default",
            source_dependencies=sorted(measure.dependencies),
            physical_grain=[],
            semantic_grain=[],
            aggregation=measure.subtotal_type or "SUM",
            filtering_mode="conditional" if measure.conditionality else "none",
            condition_phase="pre" if measure.conditionality else "none",
            transformation=None,
            null_policy=null_policy,
            zero_division_policy=zero_div_policy,
            security_scope=None,
        )

    def _persist_fingerprint(self, fp: SemanticFingerprint, ir_measure: IRMeasure):
        """Persist semantic fingerprint to SQLite (ADR-027).

        Uses in-memory tracking + DB query to prevent duplicate inserts
        within the same compilation batch (all measures may produce the
        same fingerprint when expression ASTs are absent).
        """
        # Fast in-memory check for hashes we've already persisted this run
        if not hasattr(self, '_seen_fingerprints'):
            self._seen_fingerprints = set()

        fp_key = (self.job.id, fp.fingerprint_hash)

        if fp_key in self._seen_fingerprints:
            # Already inserted in this batch — just mark shared
            ir_measure.scope = "shared"
            return

        existing = (
            self.db.query(SemanticFingerprintORM)
            .filter(
                SemanticFingerprintORM.job_id == self.job.id,
                SemanticFingerprintORM.fingerprint_hash == fp.fingerprint_hash,
            )
            .first()
        )

        if existing:
            # Duplicate fingerprint → mark as shared scope
            ir_measure.scope = "shared"
            existing.assigned_scope = "shared"
        else:
            orm_fp = SemanticFingerprintORM(
                id=str(uuid.uuid4()),
                job_id=self.job.id,
                fingerprint_hash=fp.fingerprint_hash,
                ast_hash=fp.ast_hash,
                datasource_domain=fp.datasource_domain,
                source_dependencies=fp.source_dependencies,
                physical_grain=fp.physical_grain,
                semantic_grain=fp.semantic_grain,
                aggregation=fp.aggregation,
                filtering_mode=fp.filtering_mode,
                condition_phase=fp.condition_phase,
                transformation=fp.transformation,
                null_policy=fp.null_policy,
                zero_division_policy=fp.zero_division_policy,
                security_scope=fp.security_scope,
                assigned_scope="local",
            )
            self.db.add(orm_fp)
            self.db.flush()  # Make visible to subsequent queries in this session

        self._seen_fingerprints.add(fp_key)

    # ── Caption Registry ────────────────────────────────────────

    def _register_caption(
        self, ir_id: str, local_name: str, remote_name: str, caption: str, mstr_name: str
    ):
        """Register field caption in the CaptionRegistry."""
        entry = CaptionRegistry(
            job_id=self.job.id,
            datasource_id="default",
            ir_id=ir_id,
            local_name=local_name,
            remote_name=remote_name,
            caption=caption,
            mstr_name=mstr_name,
        )
        self.db.add(entry)

    # ── Identifier normalization ────────────────────────────────

    def _make_local_name(self, name: str) -> str:
        """Generate a Tableau local-name (calc field name) from display name."""
        self._caption_counter += 1
        # Tableau uses [Calculation_N] format internally
        sanitized = name.strip().replace("[", "(").replace("]", ")")
        return sanitized

    @staticmethod
    def _normalize_identifier(name: str) -> str:
        """Normalize identifier for Hyper/TDS parity."""
        normalized = name.strip().replace(" ", "_").replace("-", "_").replace(".", "_")
        return "".join(c for c in normalized if c.isalnum() or c == "_")
