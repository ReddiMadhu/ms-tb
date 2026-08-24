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
import re
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

# MSTR expression-tree function codes (ft / aggFunc) observed in real
# dossier-instance responses (datasets[].mx[]). Only codes verified against
# captured API output are mapped; unknown codes fail closed to text compilation.
MSTR_FT_AGG = {12: "SUM", 13: "COUNT", 14: "AVG"}

# Aggregate calls recognized when classifying division operands (Rule 1).
# ZN( counts as aggregate-neutral here: ZN(SUM(x)) is aggregate, but a bare
# ZN([col]) operand reaching the division guard implies a row-level policy
# that the caller (emitter) resolves for physical columns.
_AGG_CALL_START_RE = re.compile(
    r"^(?:SUM|AVG|COUNT|COUNTD|MIN|MAX|MEDIAN|STDEV|VAR|ATTR|TOTAL)\s*\(",
    re.IGNORECASE,
)

# Bare operand shapes: [Field Name], Field_Name, or plain identifier
_BARE_OPERAND_RE = re.compile(r"^(?:\[([^\]]+)\]|([A-Za-z_][\w ]*))$")


def _strip_formula_decorations(text: str) -> tuple[str, Optional[str]]:
    """Strip MSTR <param> blocks and trailing {dimty} from a native formula.

    Returns (core_text, dimty) where dimty is None when absent/default.
    """
    t = re.sub(r"<[^<>]*>", "", text or "")
    dimty = None
    m = re.search(r"\{([^{}]*)\}\s*$", t)
    if m:
        dimty = m.group(1).strip()
        t = t[: m.start()]
    return t.strip(), dimty


def _split_top_level(s: str) -> list[str]:
    """Split on top-level commas (depth-0 relative to the string)."""
    parts, depth, cur = [], 0, []
    for ch in s:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return parts


def _is_mexp(node: Any) -> bool:
    return isinstance(node, dict) and "ft" in node and "args" in node


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
    precomputed_calc: Optional[str] = None   # set for managed metrics — skip re-compilation
    confidence: float = 1.0
    scope: str = "local"       # "shared" | "local" (ADR-027)
    fingerprint_hash: Optional[str] = None
    dependencies: list[str] = field(default_factory=list)
    null_policy: str = "propagate"
    zero_division_policy: str = "null"
    # True when MicroStrategy reported this metric as derived/computed
    # (instance datasets.mx entry carries `f`/`mexp` or um=true). Derived metrics
    # must be Tableau calculated fields, never materialized extract columns.
    is_derived: bool = False


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
    chapter_name: Optional[str] = None
    page_name: Optional[str] = None
    viz_key: Optional[str] = None
    mstr_metrics: list[str] = field(default_factory=list)
    mstr_attributes: list[str] = field(default_factory=list)
    metric_ids: list[str] = field(default_factory=list)
    attribute_ids: list[str] = field(default_factory=list)
    number_formatting: dict = field(default_factory=dict)


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
        # MSTR object-id → display-name map, populated from the semantic bundle.
        # Used to resolve {did, t} references in real mexp trees and formula text.
        self._id_to_name: dict = {}
        # Lowercased display + local names of all METRICS in the bundle.
        # Used by Rule-1 aggregation alignment: a bare reference to a metric
        # inside a division is an aggregate/LOD field — never a row value —
        # so it must carry an outer aggregation before entering arithmetic.
        self._metric_names: set = set()

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

        # ── Step 0: MSTR id → name resolution map ───────────────
        for d in getattr(semantic_bundle, "dimensions", []) or []:
            self._id_to_name[d.mstr_id] = d.name
        for fa in getattr(semantic_bundle, "facts", []) or []:
            self._id_to_name[fa.mstr_id] = fa.name
        for m in getattr(semantic_bundle, "measures", []) or []:
            self._id_to_name[m.mstr_id] = m.name
            self._metric_names.add(m.name.lower())
            self._metric_names.add(self._make_local_name(m.name).lower())

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
        # NOTE: We create only the primary display-form column per attribute.
        # The MSTR Data API grid response returns one value per attribute
        # (either DESC or ID form, depending on the cube definition).
        # Creating hidden (ID) duplicate columns would inflate the schema
        # beyond what the API provides, causing column misalignment.

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

            # Persist compiled calculation to MigrationObject in DB for API & Logic Explorer
            if self.db and self.job:
                try:
                    obj = (
                        self.db.query(MigrationObject)
                        .filter(
                            MigrationObject.job_id == self.job.id,
                            MigrationObject.mstr_id == measure.mstr_id,
                        )
                        .first()
                    )
                    if obj:
                        obj.tableau_calc = tableau_calc
                        obj.expression_text = measure.expression_text
                        obj.confidence = measure.confidence
                        obj.translation_method = "AST Expression Engine"
                except Exception as db_err:
                    logger.debug("Could not update MigrationObject for %s: %s", measure.name, db_err)

        if self.db:
            try:
                self.db.commit()
            except Exception:
                pass

        # ── Step 5: Filters ─────────────────────────────────────

        for flt in semantic_bundle.filters:
            predicate = self._compile_filter(flt)
            if predicate is None:
                # HONESTY GUARD: an uncompilable MSTR filter must never become a
                # placeholder string that silently flows into the workbook. Record
                # a blocker so validation fails closed, and ship NO predicate.
                ir.issues.append(IRIssue(
                    id=str(uuid.uuid4()),
                    severity="blocker",
                    category="filter",
                    object_id=flt.mstr_id,
                    message=(
                        f"Filter '{flt.name}' could not be compiled from its MSTR "
                        "definition (predicate tree missing or unsupported). The "
                        "generated workbook does NOT apply this filter."
                    ),
                ))
                logger.warning(
                    "Filter '%s' (%s) has no compilable predicate — recorded as blocker",
                    flt.name, flt.mstr_id,
                )
                predicate = ""
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

        Priority order (all ground-truth driven, no name heuristics):
        1. Pre-computed calc from managed metrics (ADR-032)
        2. mexp tree from the dossier instance / Model API ({ft, args} shape)
        3. Native formula text `f` (datasets[].mx[].f) with params/dimty handling
        4. Modeling-API AST ({type, function, children} shape)
        5. Plain expression text
        """
        # ── Fast path: pre-computed calc (managed metrics, ADR-032) ──
        if getattr(measure, "precomputed_calc", None):
            return measure.precomputed_calc

        ast = measure.expression_ast
        expr_text = measure.expression_text

        if not ast and not expr_text:
            local = self._make_local_name(measure.name)
            return f"SUM([{local}])"

        # ── mexp tree shape from real MSTR instance responses ──
        if _is_mexp(ast):
            agg = MSTR_FT_AGG.get(ast.get("ft"))
            args = ast.get("args") or []
            if (
                agg
                and len(args) == 1
                and isinstance(args[0], dict)
                and args[0].get("t") in (4, 12)   # metric or attribute reference
            ):
                ref_name = self._id_to_name.get(args[0].get("did")) or measure.name
                return f"{agg}([{self._make_local_name(ref_name)}])"
            # Non-trivial mexp → fall through to native-formula text, which is richer.

        # ── Native MSTR formula text (`f`) — primary text path ──
        if expr_text and isinstance(expr_text, str):
            _, dimty_probe = _strip_formula_decorations(expr_text)
            if dimty_probe not in (None, "~+", "+"):
                # Non-default dimensionality is LOD-unsafe under filters — fail closed.
                logger.info(
                    "Measure '%s' uses dimty {%s} — requires human review (filter-unsafe)",
                    measure.name, dimty_probe,
                )
                return (
                    f"// NEEDS_REVIEW: {measure.name} — MSTR formula carries non-default "
                    f"dimensionality {{{dimty_probe}}}; select a filter-safe strategy first"
                )
            compiled = self._compile_mstr_formula(expr_text, zero_div_policy)
            if compiled:
                return compiled

        # Try to compile from Modeling-API AST shape
        if ast and isinstance(ast, dict) and not _is_mexp(ast):
            compiled = self._ast_to_tableau(ast, null_policy, zero_div_policy)
            if compiled:
                return compiled

        # Fallback: legacy text wrapper
        if expr_text:
            return self._text_to_tableau(expr_text, null_policy, zero_div_policy)

        local = self._make_local_name(measure.name)
        return f"SUM([{local}])"

    def _aggregate_metric_ref(self, expr: str) -> str:
        """
        Rule-1 helper: wrap a bare reference to a known METRIC in SUM(...).

        In MSTR, `[Litigation Claims] / Total_Claims` divides metric-by-metric
        at report grain. In Tableau those operands are aggregate or LOD
        calculated fields; an unwrapped LOD reference is row-level and makes
        the division (and its IIF guard) fail with "Cannot mix aggregate and
        non-aggregate". Operands that are already aggregate calls, literals,
        arithmetic, or unknown (raw column/attribute) names pass through
        unchanged.
        """
        e = (expr or "").strip()
        if not e or _AGG_CALL_START_RE.match(e):
            return e
        m = _BARE_OPERAND_RE.match(e)
        if not m:
            return e
        name = (m.group(1) if m.group(1) is not None else m.group(2)).strip()
        # getattr fallback: bare instances built by tests bypass __init__
        metric_names = getattr(self, "_metric_names", None) or set()
        if not name or name.lower() not in metric_names:
            return e
        return f"SUM([{name}])"

    def _compile_mstr_formula(self, f_text: str, zero_div_policy: str = "null") -> Optional[str]:
        """
        Compile a native MSTR formula string (datasets[].mx[].f) to Tableau syntax.

        Real examples this handles (from captured API responses):
          "Avg<UseLookupForAttributes=False >([Fraud Score]){~+}"     → AVG([Fraud Score])
          "[High Fraud Claims] / Total_Claims"                         → guarded division
          "Sum<UseLookupForAttributes=False >(IF((Litigation@ID = \"1\"),[Total Incurred],0)){~+}"
               → SUM(IF (...) THEN [Total Incurred] ELSE 0 END)

        Returns None (fail-closed) for formulas we cannot translate honestly,
        e.g. non-default dimensionality ({Year}) which is LOD-unsafe.
        """
        if not f_text or not isinstance(f_text, str):
            return None

        core, dimty = _strip_formula_decorations(f_text)
        if not core:
            return None
        if dimty and dimty not in ("~+", "+"):
            logger.info(
                "Formula has non-default dimty {%s} — not auto-translatable (filter semantics); failing closed",
                dimty,
            )
            return None

        # IF(cond, a, b) → IF cond THEN a ELSE b END — balanced-paren scan,
        # because MSTR nests IFs inside aggregate wrappers: Sum(IF(c,x,0))
        def _translate_if_calls(s: str) -> str:
            out, i, low = [], 0, s.lower()
            while True:
                j = low.find("if", i)
                if j == -1:
                    break
                if j > 0 and (s[j - 1].isalnum() or s[j - 1] in "_["):
                    i = j + 2
                    continue
                k = s.find("(", j)
                if k == -1:
                    break
                depth, end = 0, -1
                for p in range(k, len(s)):
                    if s[p] == "(":
                        depth += 1
                    elif s[p] == ")":
                        depth -= 1
                        if depth == 0:
                            end = p
                            break
                if end == -1:
                    break
                parts = _split_top_level(s[k + 1 : end])
                if len(parts) != 3:
                    i = end + 1
                    continue
                out.append(s[i:j])
                out.append(
                    f"IF {parts[0].strip()} THEN {parts[1].strip()} ELSE {parts[2].strip()} END"
                )
                i = end + 1
            out.append(s[i:])
            return "".join(out)

        core = _translate_if_calls(core)

        # Attribute@ID → [Attribute]
        core = re.sub(r"([A-Za-z_][\w ]*?)@ID", lambda mm: f"[{mm.group(1).strip()}]", core)

        # Bracket bare identifiers outside of existing [..] refs, so MSTR's
        # unbracketed metric/attribute names become valid Tableau fields.
        _KEYWORDS = {"IF", "THEN", "ELSE", "END", "AND", "OR", "NOT", "NULL", "TRUE", "FALSE"}
        segments = re.split(r"(\[[^\]]*\])", core)
        for si, seg in enumerate(segments):
            if seg.startswith("["):
                continue
            def _bracket(mm):
                tok = mm.group(0).strip()
                if tok.upper() in _KEYWORDS:
                    return mm.group(0)
                return f"[{tok}]"
            segments[si] = re.sub(
                r"\b[A-Za-z_][A-Za-z0-9_]*\b(?!\s*\()", _bracket, seg,
            )
        core = "".join(segments)

        # Normalize leading aggregation casing: Sum(...) → SUM(...)
        core = re.sub(
            r"^(sum|avg|count|min|max|median|stdev|stdevp|var|varp)\(",
            lambda mm: f"{mm.group(1).upper()}(",
            core,
            flags=re.IGNORECASE,
        )

        # Top-level simple division gets the zero-division guard.
        # Rule 1 aggregation alignment: a bare reference to another METRIC on
        # the denominator side is an aggregate/LOD field (row-level when the
        # LOD is referenced) — Tableau rejects aggregate ÷ non-aggregate, so
        # wrap it in SUM(...) before guarding. Raw row-level operands are
        # left untouched (row ÷ row is valid); physical-column wrapping is
        # applied later by the emitter's _wrap_bare_aggregate_refs.
        # The slash must sit at paren depth 0: exactly one top-level slash
        # and no other slash anywhere (nested x/y inside SUM(...) stays put).
        if core.count("/") == 1:
            depth = 0
            split_at = -1
            for idx, ch in enumerate(core):
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                elif ch == "/" and depth == 0:
                    split_at = idx
                    break
            if split_at > 0:
                left = core[:split_at].strip()
                right = self._aggregate_metric_ref(core[split_at + 1:].strip())
                if zero_div_policy == "zero":
                    return f"IIF({right} = 0, 0, {left} / {right})"
                return f"IIF({right} = 0, NULL, {left} / {right})"

        return core

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
                    # Handle division with zero-division policy.
                    # Rule 1: align the denominator to the numerator's
                    # aggregation level — a bare metric/LOD ref on the right
                    # is row-level when referenced and must be wrapped.
                    if op == "/":
                        right = self._aggregate_metric_ref(right)
                        if zero_div_policy == "null":
                            return f"IIF({right} = 0, NULL, {left} / {right})"
                        if zero_div_policy == "zero":
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

    def _compile_filter(self, flt) -> Optional[str]:
        """
        Compile filter definition to a Tableau predicate expression.

        Returns None when the MSTR predicate cannot be compiled honestly
        (no predicate tree / unsupported shape). Callers must treat None as
        fail-closed (blocker + empty predicate), never as a TODO placeholder.
        """
        if flt.predicate_ast:
            compiled = self._ast_to_tableau(flt.predicate_ast, "propagate", "null")
            if compiled and not compiled.lstrip().startswith("//"):
                return compiled
        return None

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
        """Register field caption in the CaptionRegistry (idempotent)."""
        existing = (
            self.db.query(CaptionRegistry)
            .filter(
                CaptionRegistry.job_id == self.job.id,
                CaptionRegistry.datasource_id == "default",
                CaptionRegistry.caption == caption,
            )
            .first()
        )
        if existing:
            existing.ir_id = ir_id
            existing.local_name = local_name
            existing.remote_name = remote_name
            existing.mstr_name = mstr_name
        else:
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
