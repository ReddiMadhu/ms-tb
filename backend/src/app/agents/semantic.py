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

Fix (ADR-032): Managed metrics (auto-created from file-based cube imports)
  return HTTP 500 from /api/model/metrics/{id} with error code 8004d72a
  "We do not support managed metric". These metrics have no Modeling Service
  representation — their definition lives only in the cube's availableObjects.
  Detection: subType == 'managed_metric' OR 'managed' flag in definition.
  Fallback: derive tableau_calc from subtotalType (SUM/AVG/COUNT) captured
  during discovery from GET /api/v2/cubes/{cubeId}.
"""

import asyncio
import logging
import re
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
    precomputed_calc: Optional[str] = None  # Pre-derived Tableau calc (managed metrics, ADR-032)
    provenance: str = "mstr"  # "mstr" = formula quoted from MSTR; "derived" = synthesized here (no stored MSTR formula)


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

# MSTR subType values that indicate a managed metric
# These metrics are auto-generated from file imports and have no Modeling Service representation.
# Error code 8004d72a: "We do not support managed metric"
MANAGED_METRIC_SUBTYPES = {
    "managed_metric",
    "managed",
    "agg_metric",             # aggregation-only metric in a cube dataset
    "cube_metric",            # cube-scoped metric (no project schema entry)
}

# Mapping from MSTR subtotalType → Tableau SUM/AVG/COUNT expression pattern
SUBTOTAL_TO_TABLEAU: dict[str, str] = {
    "SUM":    "SUM([{name}])",
    "AVG":    "AVG([{name}])",
    "COUNT":  "COUNT([{name}])",
    "CNTD":   "COUNTD([{name}])",
    "MIN":    "MIN([{name}])",
    "MAX":    "MAX([{name}])",
    "MEDIAN": "MEDIAN([{name}])",
    "STDEV":  "STDEV([{name}])",
    "VAR":    "VAR([{name}])",
    "FIRST":  "MIN([{name}])",   # semi-additive FIRST → MIN proxy
    "LAST":   "MAX([{name}])",   # semi-additive LAST  → MAX proxy
    "NONE":   "[{name}]",
}


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
                    if measure.expression_text:
                        obj.expression_text = measure.expression_text
                    if getattr(measure, "provenance", "mstr") != "mstr":
                        obj.translation_method = (
                            "Derived from cube base column - MSTR stores no formula"
                        )

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

    @staticmethod
    def _is_managed_metric(detail: dict) -> bool:
        """
        Detect managed metrics that cannot be fetched via /api/model/metrics.

        Managed metrics are auto-generated when a cube is created from a
        file import (Excel/CSV/JSON). They return HTTP 500 with error code
        8004d72a: "We do not support managed metric".

        Detection strategy (any one is sufficient):
          1. subType field contains a managed-metric marker string
          2. 'managed' or 'isManaged' flag is truthy
          3. Minimal stub dict: only {id, name, type:'metric'} — no expression,
             no subType, no formula, no objectId, no dataType.
             This is exactly what MSTR returns in cube availableObjects for
             managed metrics — they have no Modeling Service representation.
        """
        if not isinstance(detail, dict):
            return False

        # Check 1: explicit subType marker
        sub_type = str(detail.get("subType", detail.get("subtype", ""))).lower()
        if any(m in sub_type for m in MANAGED_METRIC_SUBTYPES):
            return True

        # Check 2: explicit managed / derived flags
        if detail.get("managed") or detail.get("isManaged") or detail.get("isDerived"):
            return True

        # Check 3: runtime mx indicator with explicit formula f or mexp
        if "f" in detail and "mexp" in detail:
            return True

        # Check 4: minimal stub — format from cube availableObjects
        STUB_KEYS = {"id", "name", "type"}
        MANAGED_INDICATOR_KEYS = {
            "expression", "formula", "formulaText", "subType",
            "dataType", "objectId", "metricSubtotals", "aggregateFromBase",
            "information", "dimty", "conditionality",
        }
        dict_keys = set(detail.keys())
        has_id_and_name = "id" in dict_keys and "name" in dict_keys
        if has_id_and_name and \
           dict_keys <= (STUB_KEYS | {"subtype", "description", "hidden", "subtotalType", "aggregation", "defaultAggregationFunction"}) and \
           not (dict_keys & MANAGED_INDICATOR_KEYS):
            if str(detail.get("type", "")).lower() in ("metric", "4", ""):
                return True

        return False

    @staticmethod
    def _convert_mstr_formula_to_tableau(formula_str: Any, name: str = "", agg_func: Optional[int] = None, format_spec: Optional[dict] = None) -> tuple[str, float]:
        """
        Convert a MicroStrategy formula string 'f' or aggregation into a valid Tableau calculation.
        Returns (tableau_calc, confidence).
        """
        if isinstance(formula_str, dict):
            formula_str = formula_str.get("text", "")
        if not formula_str or not isinstance(formula_str, str):
            agg_map = {12: "SUM", 13: "COUNT", 14: "AVG", 15: "MIN", 16: "MAX", 17: "MEDIAN", 18: "STDEV", 19: "VAR"}
            agg = agg_map.get(agg_func, "SUM")
            return f"{agg}([{name}])", 0.90

        s = formula_str.strip()
        # Strip trailing level markers like {~+} or {~, Region+}
        s_clean = re.sub(r'\{[^\}]*\}', '', s).strip()

        # Pattern 1: Count<Distinct=True ...>(...) -> COUNTD(...)
        if re.search(r'Count<[^>]*Distinct\s*=\s*True[^>]*>', s_clean, re.IGNORECASE):
            m = re.search(r'Count<[^>]*>\((.+?)\)', s_clean, re.IGNORECASE)
            if m:
                inner = m.group(1).strip()
                inner = re.sub(r'@[A-Za-z0-9_]+', '', inner).strip('[] ')
                return f"COUNTD([{inner}])", 1.0

        # Pattern 2: Standard aggregates with angle options: Func<...>(arg)
        m_agg = re.match(r'^(Avg|Sum|Count|Min|Max|Median|Stdev|Var)(?:<[^>]*>)?\((.+)\)$', s_clean, re.IGNORECASE)
        if m_agg:
            func = m_agg.group(1).upper()
            inner = m_agg.group(2).strip()

            # Check if inner is an IF condition: IF((Attr@ID = "1"), [Metric], 0)
            m_if = re.match(r'^IF\s*\(\s*\((.+?)\s*=\s*("[^"]*"|\'[^\']*\'|\d+)\)\s*,\s*(.+?)\s*,\s*(.+?)\s*\)$', inner, re.IGNORECASE)
            if m_if:
                attr_part = m_if.group(1).strip()
                attr_part = re.sub(r'@[A-Za-z0-9_]+', '', attr_part).strip('[] ')
                val_part = m_if.group(2).strip()
                then_part = m_if.group(3).strip().strip('[] ')
                else_part = m_if.group(4).strip()
                return f"{func}(IF [{attr_part}] = {val_part} THEN [{then_part}] ELSE {else_part} END)", 0.98

            inner_clean = re.sub(r'@[A-Za-z0-9_]+', '', inner).strip('[] ')
            return f"{func}([{inner_clean}])", 1.0

        # Pattern 3: Rank(arg)
        if re.match(r'^Rank(?:<[^>]*>)?\((.+)\)$', s_clean, re.IGNORECASE):
            m_rank = re.search(r'Rank(?:<[^>]*>)?\((.+)\)', s_clean, re.IGNORECASE)
            inner = m_rank.group(1).strip().strip('[] ') if m_rank else name
            return f"RANK([{inner}])", 0.95

        # Pattern 4: Ratios like [MetricA] / MetricB
        if "/" in s_clean:
            parts = [p.strip().strip('[] ') for p in s_clean.split("/")]
            if len(parts) == 2:
                return f"[{parts[0]}] / [{parts[1]}]", 0.95

        # Fallback to subtotalType template
        return f"SUM([{name}])", 0.80

    def _build_managed_metric_def(self, obj: MigrationObject, detail: dict) -> MeasureDef:
        """
        Build a MeasureDef for a managed metric using dataset mx formulas and cube metadata.
        """
        f_str = obj.expression_text or detail.get("f") or detail.get("formula") or detail.get("expression") or ""
        # Provenance: only a non-empty MSTR-supplied formula counts as quoted
        # evidence; anything else is OUR derived subtotal default and must be
        # labeled as such, never shown as a MicroStrategy expression.
        had_f = bool(str(f_str or "").strip())
        agg_func = detail.get("aggFunc")
        nf = detail.get("nf") or detail.get("onf") or detail.get("format")

        raw_subtotal = (
            detail.get("subtotalType")
            or detail.get("aggregation")
            or detail.get("defaultAggregationFunction")
        )

        if f_str:
            tableau_calc, confidence = self._convert_mstr_formula_to_tableau(
                f_str, obj.name, agg_func=agg_func, format_spec=nf
            )
        elif raw_subtotal:
            subtotal_type = str(raw_subtotal).upper().strip()
            calc_template = SUBTOTAL_TO_TABLEAU.get(subtotal_type, "SUM([{name}])")
            tableau_calc = calc_template.format(name=obj.name)
            confidence = 0.85
        elif agg_func:
            agg_map = {12: "SUM", 13: "COUNT", 14: "AVG", 15: "MIN", 16: "MAX", 17: "MEDIAN", 18: "STDEV", 19: "VAR"}
            subtotal_type = agg_map.get(agg_func, "SUM")
            tableau_calc = f"{subtotal_type}([{obj.name}])"
            confidence = 0.85
        else:
            subtotal_type = "SUM"
            tableau_calc = f"SUM([{obj.name}])"
            confidence = 0.85

        subtotal_type = "SUM"
        if "AVG" in tableau_calc[:4]:
            subtotal_type = "AVG"
        elif "COUNTD" in tableau_calc[:7]:
            subtotal_type = "COUNTD"
        elif "COUNT" in tableau_calc[:6]:
            subtotal_type = "COUNT"
        elif "MAX" in tableau_calc[:4]:
            subtotal_type = "MAX"
        elif "MIN" in tableau_calc[:4]:
            subtotal_type = "MIN"

        logger.info(
            "Managed metric '%s' (%s): formula=%r -> tableau_calc=%r (confidence=%.2f)",
            obj.name, obj.mstr_id, f_str, tableau_calc, confidence,
        )

        return MeasureDef(
            mstr_id=obj.mstr_id,
            name=obj.name,
            expression_ast=detail.get("mexp"),
            # Never persist a synthesized formula as if MSTR supplied it.
            expression_text=(str(f_str).strip() if had_f else None),
            provenance=("mstr" if had_f else "derived"),
            precomputed_calc=tableau_calc,
            dimty=None,
            conditionality=None,
            subtotal_type=subtotal_type,
            format_spec=nf,
            thresholds=[],
            dependencies=[],
            confidence=confidence,
            blocked=False,
            block_reason=None,
        )

    async def _extract_metric(self, obj: MigrationObject) -> MeasureDef:
        """
        Extract metric with expression tree, dimty, conditionality.

        Detects blocked types: training, extreme, relationship, derived elements,
        prompt-in-condition, and semi-additive facts.

        For managed metrics (error 8004d72a from /api/model/metrics):
        - Detected upfront via mstr_definition flags
        - Skips Model API call entirely
        - Derives tableau_calc from subtotalType in cube availableObjects
        """
        cached_def = obj.mstr_definition or {}
        if not isinstance(cached_def, dict):
            cached_def = {}

        # ── Fast path: managed metric detection ─────────────────
        # Check the cached discovery definition BEFORE hitting the Model API.
        # Managed metrics always 500 on /api/model/metrics/{id}.
        if self._is_managed_metric(cached_def):
            logger.info(
                "Metric '%s' (%s) is a managed metric — skipping Model API, "
                "using cube-level definition (avoids error 8004d72a)",
                obj.name, obj.mstr_id,
            )
            return self._build_managed_metric_def(obj, cached_def)

        # ── Standard path: fetch via Model API ──────────────────
        # Always fetch via dedicated Model API to get expression tree
        # (the cached mstr_definition from discovery often lacks expressions)
        detail = None
        try:
            detail = await self.mstr.get_metric(obj.mstr_id)
        except MSTRAPIError as e:
            # 404 (not in metadata 8004c767) or 500 (managed/subtotal 8004d72a/8004d706)
            if e.status_code in (404, 500) or any(code in str(e) for code in ("8004c767", "8004d72a", "8004d706")):
                logger.info(
                    "Metric '%s' (%s) not in Modeling metadata — using harvested dossier/cube definition",
                    obj.name, obj.mstr_id,
                )
                return self._build_managed_metric_def(obj, cached_def)
            logger.warning("Could not fetch metric %s via Model API: %s", obj.mstr_id, e)
        except Exception as e:
            logger.warning("Could not fetch metric %s via Model API: %s", obj.mstr_id, e)

        # Fallback to cached definition
        if not detail or not isinstance(detail, dict):
            # If the cached definition looks managed, treat it as such now
            if self._is_managed_metric(cached_def):
                return self._build_managed_metric_def(obj, cached_def)
            detail = cached_def
        if not isinstance(detail, dict):
            detail = {}

        # Some MSTR APIs wrap the metric definition under "information" key
        # or return the metric info at the top level
        metric_info = detail.get("information", {})
        if not metric_info:
            metric_info = detail

        # Expression AST — try multiple known locations
        expression_ast = None
        expression_text = None

        expression = detail.get("expression")
        if isinstance(expression, dict):
            expression_ast = expression.get("tree", expression.get("tokens"))
            expression_text = expression.get("text")

            # If no text, try to build from tokens
            if not expression_text and expression.get("tokens"):
                tokens = expression["tokens"]
                if isinstance(tokens, list):
                    text_parts = []
                    for tok in tokens:
                        if isinstance(tok, dict):
                            val = tok.get("value", tok.get("name", ""))
                            if val:
                                text_parts.append(str(val))
                    if text_parts:
                        expression_text = " ".join(text_parts)
        elif isinstance(expression, str):
            expression_ast = None
            expression_text = expression

        # Fallback to obj.expression_text or other known fields
        if not expression_text:
            expression_text = obj.expression_text or detail.get("formula") or detail.get("formulaText")

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
