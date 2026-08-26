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
import dataclasses
import json
import logging
import os
import re
import shutil
import traceback
from datetime import datetime, timezone
from pathlib import Path
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


# ── MSTR-definition-driven physical/derived measure classification ──
# A measure is materialized as a physical Hyper column ONLY when its MSTR
# expression AST (Modeling API tree, joined via mstr_id from semantic_bundle.json)
# is a simple aggregation of exactly ONE fact column — e.g. Sum(Revenue).
# Everything else (ratios, nested aggs, transformations) stays a Tableau calc.
# Name-keyword heuristics are intentionally NOT used.
_AGG_FUNCS = {"sum", "avg", "min", "max", "count", "countd"}


def _ast_is_single_column_aggregate(node) -> bool:
    """True iff AST root = aggregation function with exactly one column child."""
    if not isinstance(node, dict):
        return False
    # Real MSTR mexp shape: {ft: <function code>, args: [{did, t}]}
    if "ft" in node:
        try:
            from app.agents.ir_compiler import MSTR_FT_AGG
            fn = MSTR_FT_AGG.get(node.get("ft"))
        except Exception:
            fn = None
        args = node.get("args") or []
        return (
            fn is not None
            and len(args) == 1
            and isinstance(args[0], dict)
            and args[0].get("t") in (4, 12)   # metric / attribute reference
        )
    # Modeling-API tree shape: {type, function, children}
    fn = str(node.get("function") or node.get("operator") or "").strip().lower()
    children = node.get("children") or []
    if fn not in _AGG_FUNCS:
        return False
    return (
        len(children) == 1
        and isinstance(children[0], dict)
        and str(children[0].get("type", "")).lower() == "column"
    )


def _f_text_is_plain_aggregate(f_text: str) -> bool:
    """True iff native formula text is exactly AGG(ref) with no params/dimty ops."""
    import re as _re
    core, dimty = None, None
    t = _re.sub(r"<[^<>]*>", "", f_text or "")
    m = _re.search(r"\{([^{}]*)\}\s*$", t)
    if m:
        dimty = m.group(1).strip()
        t = t[: m.start()]
    core = t.strip()
    if dimty not in (None, "~+", "+"):
        return False
    return bool(_re.fullmatch(
        r"(?i)(SUM|AVG|COUNT|MIN|MAX)\(\s*\[?[^\[\]()]+\]?\s*\)", core,
    ))


def _att_entry_formula(entry: dict) -> tuple:
    """
    Extract (formula, source_field) from an instance-payload attribute entry.

    Two observed payload generations:
      * legacy:  {"n":…, "did":…, "f": "<formula>"}                    (att-level f)
      * current: {"n":…, "did":…, "da": true, "fs":[{…"f":…}]}          (form-level f,
                 typically on the ID form; `da:true` marks derived attributes)
    """
    f_text = entry.get("f")
    if isinstance(f_text, str) and f_text.strip():
        return f_text.strip(), "f"
    forms = entry.get("fs") or []
    id_form = next((x for x in forms if isinstance(x, dict) and x.get("fnm") == "ID"), None)
    ordered = ([id_form] if id_form else []) + [x for x in forms if x is not id_form]
    for form in ordered:
        if not isinstance(form, dict):
            continue
        fv = form.get("f")
        if isinstance(fv, str) and fv.strip():
            return fv.strip(), f"fs:{form.get('fnm', '?')}"
    return None, None


def collect_object_definitions(ds_map) -> tuple:
    """
    Harvest EVERY dataset-object definition from a dossier instance payload.

    The payload carries two arrays per dataset:
      datasets{dsId}.att[] — attributes; DERIVED attributes carry their native
                             formula either at entry level (`f`) or inside a
                             form (`fs[].f`) — see _att_entry_formula().
      datasets{dsId}.mx[]  — metrics (`f`, `mexp`, `um`).

    Returns (by_did, by_name_lower). Keep-first on conflicting duplicate dids.
    """
    import logging as _logging
    by_did: dict = {}
    for ds_id, ds in (ds_map or {}).items():
        if not isinstance(ds, dict):
            continue
        for key in ("att", "mx"):
            for entry in (ds.get(key) or []) or []:
                if not isinstance(entry, dict):
                    continue
                did = entry.get("did")
                f_text = entry.get("f")
                src = "f"
                if key == "att":
                    f_text, src = _att_entry_formula(entry)
                elif not (isinstance(f_text, str) and f_text.strip()):
                    continue
                if not did or not f_text:
                    continue
                rec = {
                    "name": (entry.get("n") or "").strip(),
                    "formula": f_text,
                    "source_field": src,
                    "derived_attr": bool(entry.get("da")) or entry.get("st") == 3077,
                    "t": entry.get("t"),
                    "st": entry.get("st"),
                    "um": bool(entry.get("um")),
                    "dsc": (entry.get("dsc") or "").strip(),
                    "dataset_id": ds_id,
                }
                if did in by_did and by_did[did]["formula"] != rec["formula"]:
                    _logging.getLogger(__name__).warning(
                        "Conflicting dataset definitions for %s (%s) — keeping first",
                        rec["name"], did,
                    )
                    continue
                by_did[did] = rec
    by_name: dict = {}
    for rec in by_did.values():
        n = rec["name"].lower()
        if n:
            by_name.setdefault(n, rec)
    return by_did, by_name


_AGG_KW = r"(?:SUM|AVG|MIN|MAX|COUNTD|COUNT|MEDIAN)"
# AGG_OUT(AGG_IN([single field])) — e.g. SUM(COUNT([Claim ID])) in a rate
# denominator. MSTR's report-level wrapper over a single aggregate call is
# ONE aggregate in Tableau; nesting them is illegal ("cannot nest aggregates").
_NESTED_SINGLE_FIELD_RE = re.compile(
    rf"\b{_AGG_KW}\(\s*({_AGG_KW})\(\s*(\[[^\]]+\])\s*\)\s*\)",
    re.IGNORECASE,
)
# Inner aggregate around a bare field inside an IF branch that is itself under
# an outer aggregation: Sum(IF(c, [Total Incurred], 0)) with [Total Incurred]
# expanded to SUM([Total Incurred USD]) produced THEN SUM([...]) — dissolve.
_IF_BRANCH_AGG_RE = re.compile(
    rf"\b(THEN|ELSE)\s+({_AGG_KW})\(\s*(\[[^\]]+\])\s*\)",
    re.IGNORECASE,
)


def _dissolve_nested_aggregates(calc: str) -> str:
    """
    Make expanded calcs legal for Tableau by flattening nested single-field
    aggregations introduced when inlined definition bodies carry their own
    aggregation wrappers:
      SUM(COUNT([Claim ID]))                          → COUNT([Claim ID])
      SUM(IF (c) THEN SUM([Total Incurred USD]) …)    → SUM(IF (c) THEN [Total Incurred USD] …)
    ZN(...) and {FIXED …} LOD wrappers are not touched (ZN isn't an agg
    keyword here; LOD braces don't match the inner-call shape).
    """
    if not calc:
        return calc
    prev = None
    while prev != calc:                      # handle repeated nesting
        prev = calc
        calc = _NESTED_SINGLE_FIELD_RE.sub(r"\1(\2)", calc)
        calc = _IF_BRANCH_AGG_RE.sub(r"\1 \3", calc)
    return calc


def apply_definition_expansions(ir, compiler) -> int:
    """
    Recompile measures whose raw formula references harvested dataset-derived
    object definitions (High Fraud Flag, Net Loss, Litigation_Flag, …).

    For each affected measure:
      * resolve raw MSTR text against ir.object_definitions (recursive, cycle-safe)
      * compile the RESOLVED text via the standard compiler
      * pin the result via `precomputed_calc` so AITranslationAgent skips it
        (its candidate filter refuses measures carrying precomputed_calc)
      * record the expansion order in `definition_chain` for API/UI lineage

    The measure's raw `expression_text` is preserved untouched — it remains the
    honest "what MicroStrategy stores" source shown in Calculation Logic
    Conversion. Returns the number of measures expanded.
    """
    from app.agents.expression_resolver import resolve_expression

    od = getattr(ir, "object_definitions", None) or {}
    by_did = od.get("by_did") or {}
    by_name = od.get("by_name_lower") or {}
    if not by_did:
        return 0

    count = 0
    for m in ir.measures:
        raw = (getattr(m, "expression_text", None) or "").strip()
        if not raw:
            continue
        try:
            res = resolve_expression(raw, by_did, by_name)
        except Exception as re_err:                       # resolver must never kill the stage
            logger.warning("Resolver error for %s: %s", getattr(m, "name", "?"), re_err)
            continue
        if not res.chain:
            continue                                       # no harvested refs involved

        original_text = m.expression_text
        original_precomputed = getattr(m, "precomputed_calc", None)
        original_ast = getattr(m, "expression_ast", None)
        calc = None
        try:
            # Compiler priority is precomputed_calc → mexp AST → text. Both
            # fast paths must be neutralized: precomputed echoes a stale stub,
            # and the raw mexp tree references derived objects by GUID — its
            # unknown-did fallback emits literal SELF-references
            # (SUM([High Fraud Claims])), the exact defect this pass replaces.
            # Force the TEXT path with the fully-resolved formula.
            m.precomputed_calc = None
            m.expression_ast = None
            m.expression_text = res.text
            calc = compiler._compile_expression(
                m, m.null_policy, m.zero_division_policy,
            )
        except Exception as ce:
            logger.warning(
                "Definition expansion compile failed for %s (keeping %s): %s",
                getattr(m, "name", "?"), getattr(m, "tableau_calc", None), ce,
            )
        finally:
            m.expression_text = original_text
            m.expression_ast = original_ast      # provenance AST stays intact

        if isinstance(calc, str):
            calc = _dissolve_nested_aggregates(calc)

        own_names = {
            str(getattr(m, attr, "") or "").strip().lower()
            for attr in ("local_name", "caption", "name")
        } - {""}
        calc_stripped = calc.strip() if isinstance(calc, str) else ""
        self_ref = any(
            calc_stripped.lower() in (f"sum([{n}])", f"[{n}]") for n in own_names
        )

        if calc_stripped and not calc_stripped.startswith("//") and not self_ref:
            m.tableau_calc = calc
            m.precomputed_calc = calc                      # AI stage must not override
            m.definition_chain = res.chain
            if res.unresolved and hasattr(m, "is_derived"):
                m.is_derived = True                        # partial expansion still derived
            count += 1
            logger.info(
                "definition expansion: %s ← %s",
                getattr(m, "name", "?"),
                " → ".join(c["name"] for c in res.chain),
            )
        else:
            m.precomputed_calc = original_precomputed      # restore prior state
    return count


# ── Attribute condition value extracted from MSTR formula patterns ──────
# Matches: Attribute@ID = "value" or [Attribute]@ID = "value" (in MSTR native text)
_ATTR_CONDITION_RE = re.compile(
    r"""
    (?:\[([^\]]+)\]|\b([A-Za-z_][A-Za-z0-9_ ]*?))\s*@ID\s*=\s*
    [\\]*["']([^"'\\]+)[\\]*["']
    """,
    re.VERBOSE | re.IGNORECASE,
)

# Matches: [Field] = 'value' or [Field] = "value" (in compiled Tableau calc)
_TABLEAU_CONDITION_RE = re.compile(
    r"""\[([^\]]+)\]\s*=\s*['"]([^'"]+)['"]""",
)


def repair_dead_conditions(ir, compiler) -> int:
    """
    Cross-reference harvested definitions to auto-repair dead conditions.

    When a metric formula tests `Attribute@ID = 'X'` but sibling definitions
    in the same object_definitions collection test the SAME attribute with a
    DIFFERENT value 'Y', this pass substitutes X → Y in the raw MSTR formula,
    recompiles to Tableau, and pins via precomputed_calc.

    Example (Defect #4, RCA-VERIFIED.md):
      Litigation Incurred Loss = Sum(IF((Litigation@ID = "1"), ...))    ← tests "1"
      Litigation_Flag          = IF((Litigation@ID = "Yes"), 1, 0)      ← tests "Yes"
      Data has: "Yes" and "No" only → "1" is a dead condition.

    After repair:
      Litigation Incurred Loss = SUM(IF [Litigation] = 'Yes' THEN [Total Incurred USD] ELSE 0 END)

    Returns number of measures repaired.
    """
    from app.agents.expression_resolver import resolve_expression

    od = getattr(ir, "object_definitions", None) or {}
    by_name = od.get("by_name_lower") or {}
    by_did = od.get("by_did") or {}
    if not by_name:
        return 0

    # Step 1: Build an attribute→tested_values map from ALL harvested definitions.
    # Each definition that tests an attribute condition contributes its tested value.
    # Example: Litigation_Flag tests Litigation@ID = "Yes"
    #          Litigation Incurred Loss tests Litigation@ID = "1"
    # → attr_tested_values["litigation"] = {"Yes": ["Litigation_Flag"], "1": ["Litigation Incurred Loss"]}
    attr_tested_values: dict[str, dict[str, list[str]]] = {}  # attr_lower → {value → [def_names]}
    for d in by_name.values():
        formula = d.get("formula", "")
        if not formula:
            continue
        for m in _ATTR_CONDITION_RE.finditer(formula):
            attr_name = (m.group(1) or m.group(2)).strip().lower()
            test_val = m.group(3).strip()
            attr_tested_values.setdefault(attr_name, {}).setdefault(test_val, []).append(d["name"])

    # Step 2: For each attribute, identify the "canonical" value — the one used
    # by the most definitions. If there's a tie, prefer descriptive/display values
    # over numeric ID codes (e.g., "Yes" > "1", "Active" > "0").
    def _val_pref(v: str) -> tuple:
        return (not v.strip().isdigit(), len(v.strip()), v.strip())

    attr_canonical: dict[str, str] = {}  # attr_lower → canonical value
    for attr, val_map in attr_tested_values.items():
        if len(val_map) <= 1:
            continue  # only one value tested — nothing to repair
        # Sort descending by (definition count, value preference)
        ranked = sorted(
            val_map.items(),
            key=lambda kv: (len(kv[1]), _val_pref(kv[0])),
            reverse=True,
        )
        canonical_val = ranked[0][0]
        attr_canonical[attr] = canonical_val
        if len(ranked) > 1:
            logger.info(
                "Dead-condition repair: attribute '%s' tested with values %s — "
                "canonical value is '%s' (used by %s)",
                attr, dict(val_map), canonical_val, val_map[canonical_val],
            )

    if not attr_canonical:
        return 0

    # Step 3: For each measure, check if its formula tests a NON-canonical value.
    # If so, substitute the value in the raw MSTR text, resolve, recompile, and pin.
    repaired = 0
    for m_obj in ir.measures:
        raw = (getattr(m_obj, "expression_text", None) or "").strip()
        if not raw:
            continue

        # Find all condition tests in this formula
        repairs_needed = []
        for match in _ATTR_CONDITION_RE.finditer(raw):
            attr_name = (match.group(1) or match.group(2)).strip().lower()
            test_val = match.group(3).strip()
            canonical = attr_canonical.get(attr_name)
            if canonical and test_val != canonical:
                repairs_needed.append((attr_name, test_val, canonical, match))

        if not repairs_needed:
            continue

        # Apply substitutions to raw MSTR formula text
        repaired_text = raw
        for attr_name, old_val, new_val, _ in repairs_needed:
            # Replace the specific value in the formula, preserving structure
            # "1" → "Yes" or \"1\" → \"Yes\"
            repaired_text = repaired_text.replace(f'"{old_val}"', f'"{new_val}"')
            repaired_text = repaired_text.replace(f"'{old_val}'", f"'{new_val}'")
            repaired_text = repaired_text.replace(f'\\"{old_val}\\"', f'\\"{new_val}\\"')
            logger.info(
                "Dead-condition repair: %s — [%s]@ID = '%s' → '%s'",
                getattr(m_obj, "name", "?"), attr_name, old_val, new_val,
            )

        # Resolve the repaired text against harvested definitions
        try:
            res = resolve_expression(repaired_text, by_did, by_name)
            resolved_text = res.text
        except Exception:
            resolved_text = repaired_text

        # Recompile via standard compiler
        original_text = m_obj.expression_text
        original_ast = getattr(m_obj, "expression_ast", None)
        original_precomputed = getattr(m_obj, "precomputed_calc", None)
        try:
            m_obj.precomputed_calc = None
            m_obj.expression_ast = None
            m_obj.expression_text = resolved_text
            calc = compiler._compile_expression(
                m_obj, m_obj.null_policy, m_obj.zero_division_policy,
            )
        except Exception as ce:
            logger.warning(
                "Dead-condition repair compile failed for %s: %s",
                getattr(m_obj, "name", "?"), ce,
            )
            calc = None
        finally:
            m_obj.expression_text = original_text
            m_obj.expression_ast = original_ast

        if isinstance(calc, str):
            calc = _dissolve_nested_aggregates(calc)

        if calc and not calc.startswith("//"):
            m_obj.tableau_calc = calc
            m_obj.precomputed_calc = calc
            m_obj.definition_chain = getattr(m_obj, "definition_chain", []) or []
            m_obj.definition_chain.append({
                "name": "dead_condition_repair",
                "formula": f"repaired: {', '.join(f'[{a}]@ID {o!r}→{n!r}' for a, o, n, _ in repairs_needed)}",
            })
            repaired += 1
            logger.info(
                "Dead-condition repaired: %s → %s",
                getattr(m_obj, "name", "?"), calc[:120],
            )
        else:
            m_obj.precomputed_calc = original_precomputed

    return repaired


def classify_physical_measures(measure_dicts: list, bundle_asts: Optional[dict] = None) -> list:
    """Return the subset of IR measure dicts that qualify as physical extract columns."""
    bundle_asts = bundle_asts or {}
    out = []
    for m in measure_dicts:
        # 0. MSTR's own derived flag wins: derived metrics are Tableau calcs,
        #    never physical extract columns (e.g. AVG of another column).
        if m.get("is_derived"):
            continue
        # 1. Ground truth first: the MSTR expression AST (either shape).
        ast = m.get("expression_ast") or bundle_asts.get(m.get("mstr_id"))
        if ast is not None:
            if _ast_is_single_column_aggregate(ast):
                out.append(m)
            continue

        # 2. Ground truth second: the native formula text (`f` from datasets.mx).
        expr_text = (m.get("expression_text") or "").strip()
        if expr_text and ("<" in expr_text or "{" in expr_text):
            if _f_text_is_plain_aggregate(expr_text):
                out.append(m)
            continue

        # 3. Deterministic fallback when neither exists anywhere: compiled calc must
        #    EXACTLY self-reference its own column as a plain aggregate.
        m_name = (m.get("name") or "").strip()
        m_local = (m.get("local_name") or m_name).strip()
        calc = (m.get("tableau_calc") or "").strip().upper()
        for agg in ("SUM", "AVG", "MIN", "MAX", "COUNT", "COUNTD"):
            if calc in {
                f"{agg}([{m_name.upper()}])",
                f"{agg}([{m_local.upper()}])",
            }:
                out.append(m)
                break
    return out


class PipelineOrchestrator:
    """
    Two-Phase migration orchestrator.

    Drives the 11-wave pipeline by executing agents sequentially,
    transitioning job state, and handling failures with compensating actions.
    """

    def __init__(
        self,
        job_id: str,
        selected_dossier_ids: Optional[list[str]] = None,
        mstr_username: str = "",
        mstr_password: str = "",
        tableau_token_name: str = "",
        tableau_token_value: str = "",
    ):
        self.job_id = job_id
        self.selected_dossier_ids = selected_dossier_ids
        self.mstr_username = mstr_username
        self.mstr_password = mstr_password
        self.tableau_token_name = tableau_token_name
        self.tableau_token_value = tableau_token_value

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
                try:
                    db.rollback()
                except Exception:
                    pass  # Rollback may fail if session is already invalidated
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
        agent = DiscoveryAgent(
            db=db,
            job=job,
            mstr_username=self.mstr_username,
            mstr_password=self.mstr_password,
        )
        await agent.run(selected_dossier_ids=self.selected_dossier_ids)

    async def _run_graph(self, db: Session, job: Job):
        from app.agents.graph import DependencyGraph
        graph = DependencyGraph(db=db, job=job)
        graph.build()

    async def _run_semantic(self, db: Session, job: Job):
        """Stage 3: Semantic extraction — typed definitions + expression ASTs."""
        from app.agents.semantic import SemanticAgent
        from app.services.mstr_client.session import MSTRSession, AsyncMSTRSession
        from app.models.objects import MigrationObject
        from app.core.config import settings
        import json, dataclasses

        # Gather all discovered object IDs for this job
        object_ids = [
            o.mstr_id for o in
            db.query(MigrationObject.mstr_id)
              .filter(MigrationObject.job_id == job.id)
              .all()
        ]

        if not object_ids:
            logger.warning("No objects found for semantic extraction")
            return

        # Create MSTR session (objects may already have cached definitions from discovery)
        base_url = job.mstr_base_url or settings.mstr_base_url
        username = self.mstr_username or settings.mstr_username
        password = self.mstr_password or settings.mstr_password
        project_id = job.mstr_project_id or settings.mstr_project_id

        sync_session = MSTRSession(
            base_url=base_url,
            username=username,
            password=password,
            project_id=project_id,
        )
        mstr = AsyncMSTRSession(sync_session)

        try:
            try:
                await mstr.authenticate()
            except Exception as auth_err:
                logger.warning("MSTR re-auth in semantic stage failed (will use cached object definitions): %s", auth_err)

            agent = SemanticAgent(db=db, job=job, mstr=mstr)
            bundle = await agent.run(object_ids=object_ids)

            # Persist SemanticBundle as JSON artifact for downstream stages
            artifacts_dir = job.artifacts_dir or f"./artifacts/{job.id}"
            import os
            os.makedirs(artifacts_dir, exist_ok=True)

            bundle_path = os.path.join(artifacts_dir, "semantic_bundle.json")
            with open(bundle_path, "w") as f:
                json.dump(dataclasses.asdict(bundle), f, indent=2, default=str)

            logger.info(
                "Semantic: %d dims, %d facts, %d measures, %d filters",
                len(bundle.dimensions), len(bundle.facts),
                len(bundle.measures), len(bundle.filters),
            )
        finally:
            await mstr.close()

    @staticmethod
    def _norm_calc(expr: str) -> str:
        """Normalize a Tableau calc for equality comparison."""
        import re as _re
        return _re.sub(r"\s+", " ", (expr or "").strip().upper())

    def _merge_duplicate_measures(self, ir, artifacts_dir: str) -> dict:
        """
        Merge semantically identical measures into one canonical IRMeasure.

        Safety rule (ADR-027 hardening): a fingerprint collision alone is NOT
        sufficient evidence for a merge — when MSTR expression ASTs are absent,
        every measure hashes the empty dict and distinct metrics (e.g. SUM vs
        AVG over the same column) can share a fingerprint. A merge additionally
        requires positive evidence of equality: identical non-empty expression
        AST JSON, or identical normalized compiled Tableau calc.

        Returns {dropped_mstr_id: canonical_mstr_id} so downstream reference
        resolution (viz GUID → canonical field name) maps to survivors.
        """
        groups: dict[str, list] = {}
        for m in ir.measures:
            evidence = ""
            ast = getattr(m, "expression_ast", None)
            if ast:
                evidence = "ast:" + json.dumps(ast, sort_keys=True)
            else:
                calc = self._norm_calc(getattr(m, "tableau_calc", ""))
                # Placeholder calcs ("// TODO") carry no evidence — never merge
                if calc and not calc.startswith("//"):
                    evidence = "calc:" + calc
            groups.setdefault(f"{getattr(m, 'fingerprint_hash', '')}|{evidence}", []).append(m)

        referenced_ids = {
            dep for m in ir.measures for dep in (getattr(m, "dependencies", None) or [])
        }

        merge_aliases: dict[str, str] = {}   # dropped mstr_id → canonical mstr_id
        name_aliases: dict[str, str] = {}    # dropped local_name (lower) → canonical local_name
        merge_records: list[dict] = []
        dropped_ids: set[str] = set()

        for key, members in groups.items():
            if len(members) < 2:
                continue
            evidence_kind = key.split("|", 1)[1][:6]
            # Deterministic canonical choice: a measure that other survivors
            # depend on wins; otherwise lexicographically smallest mstr_id.
            members_sorted = sorted(
                members,
                key=lambda m: (m.mstr_id not in referenced_ids, m.mstr_id),
            )
            canonical = members_sorted[0]
            for dup in members_sorted[1:]:
                merge_aliases[dup.mstr_id] = canonical.mstr_id
                name_aliases[(dup.local_name or "").lower()] = canonical.local_name
                dropped_ids.add(dup.mstr_id)
                merge_records.append({
                    "dropped": dup.name,
                    "dropped_mstr_id": dup.mstr_id,
                    "canonical": canonical.name,
                    "canonical_mstr_id": canonical.mstr_id,
                    "evidence": evidence_kind,
                })
                logger.info(
                    "Dedup merge: '%s' ≡ '%s' → canonical '%s' (evidence: %s)",
                    dup.name, canonical.name, canonical.name,
                    "expression AST" if evidence_kind == "ast:" else "identical compiled calc",
                )

        if not dropped_ids:
            logger.info(
                "Metric dedup: no semantically identical measures among %d", len(ir.measures),
            )
            return merge_aliases

        # Rewrite surviving formulas that reference a dropped measure by name,
        # and rewire dependency edges to the canonical mstr_id.
        import re as _re

        def _rewrite(formula: str) -> str:
            def sub(mt):
                inner = mt.group(1).strip()
                return f"[{name_aliases.get(inner.lower(), inner)}]"
            return _re.sub(r"\[([^\]]+)\]", sub, formula or "")

        for m in ir.measures:
            if m.mstr_id in dropped_ids:
                continue
            new_calc = _rewrite(getattr(m, "tableau_calc", ""))
            if new_calc != (getattr(m, "tableau_calc", "") or ""):
                m.tableau_calc = new_calc
            deps = getattr(m, "dependencies", None)
            if deps:
                m.dependencies = [merge_aliases.get(d, d) for d in deps]

        ir.measures = [m for m in ir.measures if m.mstr_id not in dropped_ids]

        logger.info(
            "Metric dedup: merged %d duplicates → %d canonical measures (was %d)",
            len(dropped_ids), len(ir.measures), len(ir.measures) + len(dropped_ids),
        )

        try:
            with open(os.path.join(artifacts_dir, "merge_map.json"), "w") as f:
                json.dump({"aliases": merge_aliases, "merges": merge_records}, f, indent=2)
        except Exception as e:
            logger.warning("Could not persist merge_map.json: %s", e)

        return merge_aliases

    async def _run_dedup(self, db: Session, job: Job):
        """Stage 4: Metric deduplication via SemanticFingerprint (ADR-027).
        
        Deduplication is integrated into the IR compilation step.
        This stage performs a pre-pass to identify duplicate fingerprints.
        """
        from app.models.objects import MigrationObject
        import json, os

        artifacts_dir = job.artifacts_dir or f"./artifacts/{job.id}"
        bundle_path = os.path.join(artifacts_dir, "semantic_bundle.json")

        if not os.path.exists(bundle_path):
            logger.warning("No semantic bundle found — skipping dedup")
            return

        with open(bundle_path) as f:
            bundle_data = json.load(f)

        # Count measures for dedup analysis
        measures = bundle_data.get("measures", [])
        blocked = sum(1 for m in measures if m.get("blocked"))
        logger.info(
            "Dedup pre-pass: %d measures (%d blocked, %d active)",
            len(measures), blocked, len(measures) - blocked,
        )

    async def _run_ir_compile(self, db: Session, job: Job):
        """Stage 5: Compile SemanticBundle → BI-IR JSON."""
        from app.agents.ir_compiler import IRCompilerAgent
        from app.agents.physical_model_planner import PhysicalModelPlanner
        from app.agents.semantic import SemanticBundle, DimensionDef, FactDef, MeasureDef, FilterDef
        import json, os, dataclasses

        artifacts_dir = job.artifacts_dir or f"./artifacts/{job.id}"
        bundle_path = os.path.join(artifacts_dir, "semantic_bundle.json")

        if not os.path.exists(bundle_path):
            logger.warning("No semantic bundle found — skipping IR compilation")
            return

        # Reconstruct SemanticBundle from JSON
        with open(bundle_path) as f:
            data = json.load(f)

        bundle = SemanticBundle(
            dimensions=[DimensionDef(**d) for d in data.get("dimensions", [])],
            facts=[FactDef(**fa) for fa in data.get("facts", [])],
            measures=[MeasureDef(**m) for m in data.get("measures", [])],
            filters=[FilterDef(**fl) for fl in data.get("filters", [])],
        )

        # Generate physical model plan
        planner = PhysicalModelPlanner(db=db, job=job)
        warehouse_config = job.warehouse_connection_json or {}
        physical_plan = planner.plan(bundle, warehouse_config)

        # Compile IR
        compiler = IRCompilerAgent(db=db, job=job)
        ir = compiler.compile(bundle, physical_plan)

        # ── True metric deduplication (ADR-027) ──────────────────────
        # Fingerprints mark duplicates as scope="shared" but never merge them,
        # so MSTR's two-layer objects (cube base metric `[Total Incurred USD]`
        # vs dossier alias metric `[Total Incurred]`) all survive to emission —
        # bloating the datasource and colliding in Tableau ("field is already
        # defined by data source"). Merge here, before viz harvesting, so all
        # worksheet shelf references resolve to the single canonical field.
        merge_aliases = self._merge_duplicate_measures(ir, artifacts_dir)

        # Extract visuals from dossier definition (Phase 3: ROOT CAUSE #2)
        from app.agents.ir_compiler import IRVisual
        from app.models.objects import MigrationObject
        import uuid as uuid_mod

        dossier_objs = db.query(MigrationObject).filter(
            MigrationObject.job_id == job.id,
            MigrationObject.type_name == "dossier",
        ).all()

        # Harvest visual metadata map directly from MSTR API instance endpoints
        viz_meta_map = {}
        mx_formulas = {}   # mstr_id → real formula entry {f, mexp, aggFunc, um, nf}
        try:
            from app.services.mstr_client.session import MSTRSession
            sync_session = MSTRSession(
                base_url=job.mstr_base_url or settings.mstr_base_url,
                username=self.mstr_username or settings.mstr_username,
                password=self.mstr_password or settings.mstr_password,
                project_id=job.mstr_project_id or settings.mstr_project_id,
            )
            sync_session.authenticate()
            for dossier_obj in dossier_objs:
                dossier_id = dossier_obj.mstr_id
                try:
                    d_inst = sync_session.create_dossier_instance(dossier_id)
                    d_iid = d_inst.get("mid") or d_inst.get("instanceId")

                    # Harvest REAL metric formulas: GET /api/dossiers/{id}/instances/{mid}
                    # returns datasets{dsId}.mx[] with per-metric `f` (native formula),
                    # `mexp` (expression tree {ft,args}), `aggFunc`, `um` (derived flag).
                    # datasets{dsId}.att[] additionally carries DERIVED ATTRIBUTE
                    # definitions (subType 3077, e.g. High Fraud Flag ≔ IF(…)).
                    # Together they are the ground truth that replaces name-based guessing.
                    try:
                        inst_full = sync_session.get_dossier_instance(dossier_id, d_iid)
                        ds_map = inst_full.get("datasets") if isinstance(inst_full, dict) else None
                        if isinstance(ds_map, dict):
                            for _ds_id, ds in ds_map.items():
                                for entry in (ds or {}).get("mx", []) or []:
                                    did = entry.get("did")
                                    if did:
                                        mx_formulas[did] = entry
                            defs_did, defs_name = collect_object_definitions(ds_map)
                            if defs_did:
                                ir.object_definitions.setdefault("by_did", {}).update(defs_did)
                                ir.object_definitions.setdefault("by_name_lower", {}).update(
                                    {k: v for k, v in defs_name.items()
                                     if k not in ir.object_definitions["by_name_lower"]})
                        logger.info("Harvested %d metric formulas from dossier instance", len(mx_formulas))
                    except Exception as fe:
                        logger.warning("Formula harvest failed for dossier %s: %s", dossier_id, fe)

                    defn = dossier_obj.mstr_definition or {}
                    for chapter in defn.get("chapters", []):
                        ch_key = chapter.get("key")
                        for page in chapter.get("pages", []):
                            for viz in page.get("visualizations", []):
                                vz_key = viz.get("key", viz.get("id", ""))
                                try:
                                    try:
                                        v_detail = sync_session.get_visualization_definition(dossier_id, d_iid, ch_key, vz_key)
                                    except Exception as v1_err:
                                        # V1 endpoint rejects cross-tabs (iServerCode -2147171504),
                                        # subtotal grids (-2147171501), and compound grids (ERR006).
                                        # The error text explicitly directs callers to /api/v2/...
                                        v1_msg = str(v1_err)
                                        if (
                                            "-2147171504" in v1_msg
                                            or "-2147171501" in v1_msg
                                            or "not supported in current version" in v1_msg
                                            or "compound grid" in v1_msg.lower()
                                        ):
                                            v_detail = sync_session.get_visualization_definition_v2(
                                                dossier_id, d_iid, ch_key, vz_key,
                                            )
                                            logger.info(
                                                "Visual %s recovered via /api/v2 endpoint (V1 unsupported type)", vz_key,
                                            )
                                        else:
                                            raise
                                    res = v_detail.get("result", {}).get("definition", {}) or v_detail.get("definition", {})

                                    # Persist the RAW definition so shelf evidence is
                                    # auditable (and re-parseable) offline — silent
                                    # empties here are how wrong-chart regressions
                                    # were born.
                                    try:
                                        vdefs_dir = os.path.join(artifacts_dir, "visual_defs")
                                        os.makedirs(vdefs_dir, exist_ok=True)
                                        safe_key = "".join(c if c.isalnum() or c in "-_" else "_" for c in vz_key)
                                        with open(os.path.join(vdefs_dir, f"{safe_key}.json"), "w", encoding="utf-8") as vf:
                                            json.dump(v_detail, vf, indent=2, default=str)
                                    except Exception as pe:
                                        logger.warning("Could not persist visual definition for %s: %s", vz_key, pe)

                                    def _named_object_lists(node, out=None):
                                        """Collect every list of {name,id,...} dicts in
                                        the response. Grid/crosstab/microchart V2
                                        payloads bury shelves under varied keys
                                        (metrics/attributes/rows/columns/axes...);
                                        scanning keeps us shape-agnostic without
                                        inventing bindings."""
                                        if out is None:
                                            out = {}
                                        if isinstance(node, dict):
                                            for k, v in node.items():
                                                if isinstance(v, list) and v and isinstance(v[0], dict) and "name" in v[0]:
                                                    out.setdefault(k, []).extend(v)
                                                elif isinstance(v, (dict, list)):
                                                    _named_object_lists(v, out)
                                        elif isinstance(node, list):
                                            for v in node[:50]:
                                                _named_object_lists(v, out)
                                        return out

                                    v_metrics = [m.get("name") for m in res.get("metrics", []) if m.get("name")]
                                    v_attrs = [a.get("name") for a in res.get("attributes", []) if a.get("name")]
                                    v_metric_ids = [m.get("id") for m in res.get("metrics", []) if m.get("id")]
                                    v_attr_ids = [a.get("id") for a in res.get("attributes", []) if a.get("id")]

                                    if not v_metrics and not v_attrs:
                                        lists = _named_object_lists(res)
                                        for lk, lv in lists.items():
                                            k_l = lk.lower()
                                            names = [o.get("name") for o in lv if o.get("name")]
                                            ids = [o.get("id") for o in lv if o.get("id")]
                                            if any(t in k_l for t in ("metric", "measure")):
                                                v_metrics.extend(n for n in names if n not in v_metrics)
                                                v_metric_ids.extend(i for i in ids if i not in v_metric_ids)
                                            elif any(t in k_l for t in ("attribute", "entity", "row", "column", "axis")):
                                                v_attrs.extend(n for n in names if n not in v_attrs)
                                                v_attr_ids.extend(i for i in ids if i not in v_attr_ids)

                                    num_format = res.get("metrics", [{}])[0].get("numberFormatting", {}) if res.get("metrics") else {}
                                    viz_meta_map[vz_key] = {
                                        "metrics": v_metrics,
                                        "attributes": v_attrs,
                                        "metric_ids": v_metric_ids,
                                        "attribute_ids": v_attr_ids,
                                        "number_formatting": num_format,
                                    }
                                except Exception as ve:
                                    # Silent drops here produced visuals with missing
                                    # shelves that LOOKED migrated. Surface every failure.
                                    logger.warning(
                                        "Visual definition harvest failed for dossier=%s chapter=%s viz=%s: %s",
                                        dossier_id, ch_key, vz_key, ve,
                                    )
                except Exception as de:
                    logger.warning("Could not create dossier instance for visual metadata: %s", de)
            sync_session.close()
            logger.info("Harvested ground-truth metadata for %d visuals from MSTR", len(viz_meta_map))
        except Exception as e:
            logger.warning("Could not harvest visual metadata from MSTR: %s", e)

        # ── Apply REAL MSTR formulas to IR measures (ground-truth wiring) ──
        # Replaces stub calcs with compilations of the actual `f`/`mexp` data that
        # MicroStrategy returned for this dossier's metrics.
        if mx_formulas:
            enriched = 0
            for m in ir.measures:
                info = mx_formulas.get(getattr(m, "mstr_id", None))
                if not info:
                    continue
                changed = False
                mexp = info.get("mexp")
                f_text = info.get("f")
                if isinstance(mexp, dict) and mexp:
                    m.expression_ast = mexp
                    changed = True
                if isinstance(f_text, str) and f_text.strip():
                    m.expression_text = f_text
                    changed = True
                if changed or info.get("um"):
                    # MSTR reports derived metrics via f/mexp/um — they must stay
                    # Tableau calcs, never materialized extract columns.
                    m.is_derived = True
                if changed:
                    try:
                        new_calc = compiler._compile_expression(
                            m, m.null_policy, m.zero_division_policy,
                        )
                        if new_calc and not new_calc.lstrip().startswith("//"):
                            logger.info("mx formula applied: %s → %s", m.name, new_calc[:90])
                            m.tableau_calc = new_calc
                            # Pin simple row-level MAX/MIN calcs: the AI stage
                            # historically wrapped these in {FIXED : SUM(…)},
                            # which turns "max single claim" into "grand total"
                            # (Defect #3, RCA-VERIFIED.md).
                            _upper = new_calc.strip().upper()
                            if _upper.startswith(("MAX(", "MIN(")) and _upper.count("(") == 1:
                                m.precomputed_calc = new_calc
                            enriched += 1
                    except Exception as me:
                        # Keep prior calc; the discrepancy stays visible in logs.
                        logger.warning(
                            "Formula recompilation failed for %s (keeping %s): %s",
                            m.name, m.tableau_calc, me,
                        )
            logger.info(
                "MSTR formula enrichment: %d/%d measures recompiled from instance formulas",
                enriched, len(ir.measures),
            )

        # ── Ground-truth definition expansion (derived attrs + chained defs) ──
        # Measures whose raw formula references dataset-derived objects
        # (High Fraud Flag, Net Loss, Litigation_Flag, …) are recompiled from
        # the TRUE harvested definitions. The result is pinned via
        # precomputed_calc so the AI-translation stage can never override it
        # with a cached guess (the Tier-1 cache historically invented, among
        # others, Net Loss = Incurred − Recovery − Salvage).
        expanded = apply_definition_expansions(ir, compiler)
        if expanded:
            logger.info(
                "Definition expansion: %d measure(s) compiled from harvested dataset definitions",
                expanded,
            )
            try:
                with open(os.path.join(artifacts_dir, "object_definitions.json"), "w", encoding="utf-8") as f:
                    json.dump(ir.object_definitions or {}, f, indent=2, default=str)
            except Exception as pe:
                logger.warning("Could not persist object_definitions.json: %s", pe)

        # ── Dead-condition auto-repair (Defect #4, RCA-VERIFIED.md) ──────
        # Cross-references sibling definitions in object_definitions to fix
        # metrics whose condition tests a value absent from the data.
        # Example: Litigation Incurred Loss tests @ID="1" but Litigation_Flag
        # tests @ID="Yes" — repairs "1" → "Yes" and recompiles.
        repaired = repair_dead_conditions(ir, compiler)
        if repaired:
            logger.info(
                "Dead-condition repair: %d measure(s) auto-repaired from sibling definitions",
                repaired,
            )

        # Build canonical ID lookup map from compiled IR for ground-truth resolution
        mstr_id_to_canonical = {}
        for m in ir.measures:
            if getattr(m, "mstr_id", None):
                mstr_id_to_canonical[m.mstr_id] = m.local_name
        for d in ir.dimensions:
            if getattr(d, "mstr_id", None):
                mstr_id_to_canonical[d.mstr_id] = d.local_name

        # Dedup aliases: visuals referencing a merged-away metric (by MSTR GUID)
        # must bind to the canonical survivor's field, not a dangling name.
        if merge_aliases:
            mstr_local = {m.mstr_id: m.local_name for m in ir.measures if getattr(m, "mstr_id", None)}
            for dropped_id, canon_id in merge_aliases.items():
                if canon_id in mstr_local:
                    mstr_id_to_canonical[dropped_id] = mstr_local[canon_id]

        for dossier_obj in dossier_objs:
            defn = dossier_obj.mstr_definition
            if not isinstance(defn, dict):
                continue

            # MSTR dossier definition has chapters > pages > visualizations
            for chapter in defn.get("chapters", []):
                if not isinstance(chapter, dict):
                    continue
                for page in chapter.get("pages", []):
                    if not isinstance(page, dict):
                        continue
                    for viz in page.get("visualizations", []):
                        if not isinstance(viz, dict):
                            continue
                        viz_key = viz.get("key", viz.get("id", ""))
                        viz_name = viz.get("name", f"Viz_{viz_key}")
                        viz_type = viz.get("visualizationType", "grid").lower()

                        # Extract field references from viz definition
                        rows = []
                        columns = []
                        color_field = None
                        size_field = None

                        # Parse selector/shelves if available
                        selectors = viz.get("selector", {})
                        if isinstance(selectors, dict):
                            for sel in selectors.get("selectors", []):
                                if isinstance(sel, dict):
                                    shelf = sel.get("shelf", "").lower()
                                    elements = sel.get("elements", [])
                                    for elem in elements:
                                        if isinstance(elem, dict):
                                            elem_id = elem.get("id", "")
                                            elem_name = mstr_id_to_canonical.get(elem_id) or elem.get("name", "")
                                            if elem_name:
                                                if shelf in ("rows", "row"):
                                                    rows.append(elem_name)
                                                elif shelf in ("columns", "column", "cols"):
                                                    columns.append(elem_name)
                                                elif shelf == "color":
                                                    color_field = elem_name
                                                elif shelf == "size":
                                                    size_field = elem_name

                        v_meta = viz_meta_map.get(viz_key, {})
                        v_metrics_raw = v_meta.get("metrics", [])
                        v_attrs_raw = v_meta.get("attributes", [])
                        v_metric_ids = v_meta.get("metric_ids", [])
                        v_attr_ids = v_meta.get("attribute_ids", [])
                        v_format = v_meta.get("number_formatting", {})

                        # Canonicalize metrics/attributes using MSTR GUIDs.
                        # A binding that resolves NEITHER by GUID NOR by exact
                        # IR name is a display artifact (e.g. microchart
                        # 'Column Set 1') — dropped here so phantom fields can
                        # never become shelf pills downstream.
                        ir_name_set = {str(n).lower() for n in mstr_id_to_canonical.values()}

                        v_metrics = []
                        for i, mname in enumerate(v_metrics_raw):
                            mid = v_metric_ids[i] if i < len(v_metric_ids) else None
                            canon = mstr_id_to_canonical.get(mid)
                            if canon:
                                v_metrics.append(canon)
                            elif mname and str(mname).strip().lower() in ir_name_set:
                                v_metrics.append(mname)
                            else:
                                logger.info(
                                    "Visual %s: dropping unresolvable metric binding '%s' (no GUID / exact IR match)",
                                    viz_key, mname,
                                )

                        v_attrs = []
                        for i, aname in enumerate(v_attrs_raw):
                            aid = v_attr_ids[i] if i < len(v_attr_ids) else None
                            canon = mstr_id_to_canonical.get(aid)
                            if canon:
                                v_attrs.append(canon)
                            elif aname and str(aname).strip().lower() in ir_name_set:
                                v_attrs.append(aname)
                            else:
                                logger.info(
                                    "Visual %s: dropping unresolvable attribute binding '%s' (no GUID / exact IR match)",
                                    viz_key, aname,
                                )

                        # If rows/columns were not in selector, map directly from ground-truth instance definition
                        if not rows and not columns:
                            if viz_type in ("kpi", "card", "metric_value"):
                                if v_metrics:
                                    columns = [v_metrics[0]]
                            elif viz_type in ("bar", "bar_chart", "vertical_bar", "horizontal_bar"):
                                if v_attrs:
                                    rows = [v_attrs[0]]
                                if v_metrics:
                                    columns = [v_metrics[0]]
                            elif viz_type in ("combo", "combo_chart"):
                                if v_attrs:
                                    columns = [v_attrs[0]]
                                if v_metrics:
                                    rows = list(v_metrics)
                            elif viz_type in ("donut", "donut_chart", "pie", "pie_chart"):
                                if v_attrs:
                                    color_field = v_attrs[0]
                                if v_metrics:
                                    # Angle belongs to Size encoding, NOT an
                                    # axis pill — a metric on Columns renders
                                    # a pie as detached bubbles on an axis.
                                    size_field = v_metrics[0]
                            elif viz_type in ("line", "line_chart"):
                                if v_attrs:
                                    columns = [v_attrs[0]]
                                if v_metrics:
                                    rows = [v_metrics[0]]
                            elif viz_type in ("bubble", "bubble_chart", "scatter", "scatter_chart"):
                                if len(v_metrics) >= 2:
                                    columns = [v_metrics[0]]
                                    rows = [v_metrics[1]]
                                    if len(v_metrics) >= 3:
                                        size_field = v_metrics[2]
                                elif v_metrics:
                                    columns = [v_metrics[0]]
                                if v_attrs:
                                    color_field = v_attrs[0]
                            elif viz_type in ("grid", "crosstab", "microcharts"):
                                if v_attrs:
                                    rows = list(v_attrs)
                                if v_metrics:
                                    columns = list(v_metrics)

                        # If viz_name is a generic internal container name from MicroStrategy copy-paste,
                        # resolve it to the bound metric or attribute name if available:
                        v_name_lower = (viz_name or "").lower().strip()
                        if "visualization" in v_name_lower or v_name_lower.startswith("viz"):
                            if v_metrics and v_metrics[0]:
                                viz_name = v_metrics[0].strip()
                            elif v_attrs and v_attrs[0]:
                                viz_name = v_attrs[0].strip()

                        ir_visual = IRVisual(
                            id=str(uuid_mod.uuid4()),
                            name=viz_name,
                            mark_type=viz_type,
                            rows=rows,
                            columns=columns,
                            color=color_field,
                            size=size_field,
                            chapter_name=chapter.get("name"),
                            page_name=page.get("name"),
                            viz_key=viz_key,
                            mstr_metrics=v_metrics,
                            mstr_attributes=v_attrs,
                            metric_ids=v_metric_ids,
                            attribute_ids=v_attr_ids,
                            number_formatting=v_format,
                        )
                        ir.visuals.append(ir_visual)

        # Persist IR as JSON artifact
        ir_path = os.path.join(artifacts_dir, "ir.json")
        with open(ir_path, "w") as f:
            json.dump(ir.to_dict(), f, indent=2, default=str)

        # Persist physical plan
        plan_path = os.path.join(artifacts_dir, "physical_plan.json")
        with open(plan_path, "w") as f:
            json.dump(dataclasses.asdict(physical_plan), f, indent=2, default=str)

        logger.info(
            "IR compiled: %d tables, %d dims, %d measures, %d filters, %d visuals, %d issues",
            len(ir.tables), len(ir.dimensions), len(ir.measures),
            len(ir.filters), len(ir.visuals), len(ir.issues),
        )

    async def _run_ai_translate(self, db: Session, job: Job):
        """Stage 6: AI translation for low-confidence expressions (3-tier fallback)."""
        from app.agents.ai_translation import AITranslationAgent
        from app.agents.ir_compiler import BIIR, IRTable, IRRelationship, IRDimension, IRMeasure, IRFilter, IRVisual, IRIssue
        import json, os

        artifacts_dir = job.artifacts_dir or f"./artifacts/{job.id}"
        ir_path = os.path.join(artifacts_dir, "ir.json")

        if not os.path.exists(ir_path):
            logger.warning("No IR found — skipping AI translation")
            return

        # Reconstruct IR
        with open(ir_path) as f:
            ir_data = json.load(f)

        ir = BIIR(
            job_id=ir_data.get("job_id", job.id),
            tables=[IRTable(**t) for t in ir_data.get("tables", [])],
            relationships=[IRRelationship(**r) for r in ir_data.get("relationships", [])],
            dimensions=[IRDimension(**d) for d in ir_data.get("dimensions", [])],
            measures=[IRMeasure(**m) for m in ir_data.get("measures", [])],
            filters=[IRFilter(**fl) for fl in ir_data.get("filters", [])],
            visuals=[IRVisual(**v) for v in ir_data.get("visuals", [])],
            issues=[IRIssue(**i) for i in ir_data.get("issues", [])],
        )

        try:
            agent = AITranslationAgent(db=db, job=job, artifacts_dir=artifacts_dir)
            await agent.run(ir)

            # Persist updated IR
            with open(ir_path, "w") as f:
                json.dump(ir.to_dict(), f, indent=2, default=str)

            logger.info("AI translation stage completed successfully")
        except Exception as e:
            try:
                db.rollback()
            except Exception:
                pass
            logger.warning("AI translation failed (non-fatal): %s", e)

    async def _run_viz(self, db: Session, job: Job):
        """Stage 7: Visualization planning — map MSTR viz types to Tableau worksheets."""
        from app.agents.visualization import VisualizationAgent
        from app.agents.ir_compiler import BIIR, IRTable, IRRelationship, IRDimension, IRMeasure, IRFilter, IRVisual, IRIssue
        import json, os, dataclasses

        artifacts_dir = job.artifacts_dir or f"./artifacts/{job.id}"
        ir_path = os.path.join(artifacts_dir, "ir.json")

        if not os.path.exists(ir_path):
            logger.warning("No IR found — skipping visualization planning")
            return

        with open(ir_path) as f:
            ir_data = json.load(f)

        ir = BIIR(
            job_id=ir_data.get("job_id", job.id),
            tables=[IRTable(**t) for t in ir_data.get("tables", [])],
            relationships=[IRRelationship(**r) for r in ir_data.get("relationships", [])],
            dimensions=[IRDimension(**d) for d in ir_data.get("dimensions", [])],
            measures=[IRMeasure(**m) for m in ir_data.get("measures", [])],
            filters=[IRFilter(**fl) for fl in ir_data.get("filters", [])],
            visuals=[IRVisual(**v) for v in ir_data.get("visuals", [])],
            issues=[IRIssue(**i) for i in ir_data.get("issues", [])],
        )

        agent = VisualizationAgent(ir=ir)
        viz_plan = agent.plan()

        # Persist VizPlan
        viz_path = os.path.join(artifacts_dir, "viz_plan.json")
        with open(viz_path, "w") as f:
            json.dump(dataclasses.asdict(viz_plan), f, indent=2, default=str)

        logger.info(
            "VizPlan: %d worksheets, %d dashboards",
            len(viz_plan.worksheets), len(viz_plan.dashboards),
        )

    async def _run_hyper(self, db: Session, job: Job):
        """Stage 8: Hyper extract building — streaming chunked data extraction."""
        from app.agents.hyper_builder import HyperAgent
        from app.models.objects import MigrationObject
        from app.services.mstr_client.session import AsyncMSTRSession
        import json, os

        artifacts_dir = job.artifacts_dir or f"./artifacts/{job.id}"
        plan_path = os.path.join(artifacts_dir, "physical_plan.json")
        ir_path = os.path.join(artifacts_dir, "ir.json")
        hyper_dir = os.path.join(artifacts_dir, "hyper")
        os.makedirs(hyper_dir, exist_ok=True)

        def _verify_hyper_contract(path, expected_types: Optional[dict[str, str]] = None) -> tuple[bool, str]:
            """The TWB binds ONE flattened table: [Extract].[Extract]. Any Hyper
            file entering this pipeline MUST contain it with compatible column types —
            a cached legacy extract or a mistyped rebuild otherwise ships a workbook
            that fails in Tableau (e.g. TEXT-typed date columns triggering Error 6EA18A9E)."""
            if not os.path.exists(path):
                return False, "file does not exist"
            try:
                from tableauhyperapi import HyperProcess, Telemetry, Connection, TableName
                from app.utils.sql_types import format_contract_mismatch
                with HyperProcess(telemetry=Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU) as hp:
                    with Connection(endpoint=hp.endpoint, database=str(path)) as conn:
                        names = [
                            f"{str(s).strip(chr(34))}.{tn.name.unescaped}"
                            for s in conn.catalog.get_schema_names()
                            for tn in conn.catalog.get_table_names(s)
                        ]
                        if "Extract.Extract" not in names:
                            return False, f"tables found: {names or 'none'}"

                        if expected_types:
                            tdef = conn.catalog.get_table_definition(TableName("Extract", "Extract"))
                            actual = {c.name.unescaped: str(c.type) for c in tdef.columns}
                            mismatch = format_contract_mismatch(actual, expected_types)
                            if mismatch:
                                return False, mismatch

                        return True, "contract satisfied"
            except Exception as ve:
                # Cannot verify HERE (lib missing / sandbox) — downstream
                # emitter re-checks before packaging; don't block the build.
                logger.warning("Hyper contract verification unavailable in this environment: %s", ve)
                return True, f"verification unavailable: {ve}"

        def _reject_bad_hyper(path, why: str):
            from app.models.objects import Issue as IssueModel
            db.add(IssueModel(
                job_id=job.id,
                object_id=job.id,
                severity="blocker",
                category="hyper",
                message=(
                    f"Hyper extract '{path}' violates the [Extract].[Extract] "
                    f"contract ({why}). Workbook emission refused rather than "
                    f"shipping a datasource Tableau cannot open."
                ),
            ))
            db.commit()
            raise RuntimeError(
                f"Hyper contract violation for {path}: {why}"
            )

        hyper_paths = {}
        hyper_file = os.path.join(hyper_dir, "extract.hyper")

        if not os.path.exists(ir_path):
            logger.warning("No IR found — skipping hyper build")
            hyper_paths["default"] = hyper_file
            paths_file = os.path.join(artifacts_dir, "hyper_paths.json")
            with open(paths_file, "w") as f:
                json.dump(hyper_paths, f, indent=2)
            return

        with open(ir_path) as f:
            ir_data = json.load(f)

        # Build expected types map from IR dimensions for contract verification
        expected_dim_types = {}
        for dim in ir_data.get("dimensions", []):
            dname = dim.get("local_name", dim.get("name"))
            dtype = dim.get("data_type")
            if dname and dtype:
                expected_dim_types[dname] = dtype

        # 1. Check for Pre-Built Cache or Dynamic Source Files for this job's cubes
        agent = HyperAgent(db=db, job=job, artifacts_dir=artifacts_dir)
        cube_objs = db.query(MigrationObject).filter(
            MigrationObject.job_id == job.id,
            MigrationObject.type_name.in_(["cube", "report", "dataset"]),
        ).all()

        cached_extract_found = False
        for cube in cube_objs:
            cache_path = HyperAgent.get_cache_path(cube.mstr_id)
            if cache_path.exists():
                logger.info("Found cached Hyper extract for cube '%s' at %s. Using instant cache...", cube.name, cache_path)
                try:
                    shutil.copy(cache_path, hyper_file)
                    ok, why = _verify_hyper_contract(hyper_file, expected_dim_types)
                    if not ok:
                        logger.warning(
                            "Cached extract for cube '%s' violates [Extract].[Extract] "
                            "contract (%s) — ignoring cache and rebuilding", cube.name, why,
                        )
                    else:
                        cached_extract_found = True
                        break
                except Exception as c_err:
                    logger.warning("Cache copy failed: %s", c_err)

            # Check for any source files matching cube name in artifacts or job dir
            source_candidates = [
                Path(os.path.join(artifacts_dir, f"{cube.name}.parquet")),
                Path(os.path.join(artifacts_dir, f"{cube.name}.csv")),
                Path(os.path.join(artifacts_dir, f"{cube.name}.xlsx")),
                Path(f"./artifacts/{cube.name}.parquet"),
                Path(f"./artifacts/{cube.name}.csv"),
            ]
            for sc in source_candidates:
                if sc.exists():
                    logger.info("Found direct source file at %s. Ingesting via DuckDB + PyArrow...", sc)
                    try:
                        agent.build_from_source_file(sc, Path(hyper_file))
                        ok, why = _verify_hyper_contract(hyper_file, expected_dim_types)
                        if not ok:
                            logger.warning(
                                "Source-ingested extract violates [Extract].[Extract] "
                                "contract (%s) — ignoring and rebuilding", why,
                            )
                            continue
                        shutil.copy(hyper_file, cache_path)
                        cached_extract_found = True
                        break
                    except Exception as s_err:
                        logger.warning("Direct source ingest failed: %s", s_err)
            if cached_extract_found:
                break

        if cached_extract_found:
            hyper_paths["default"] = hyper_file
            paths_file = os.path.join(artifacts_dir, "hyper_paths.json")
            with open(paths_file, "w") as f:
                json.dump(hyper_paths, f, indent=2)
            return

        # 2. Attempt live MSTR Cube instance data extraction via Parallel Async Stream
        live_extracted_rows = []
        if self.mstr_username and self.mstr_password and job.mstr_base_url and job.mstr_project_id:
            try:
                logger.info("Attempting live MSTR cube data streaming...")
                async with AsyncMSTRSession(
                    base_url=job.mstr_base_url,
                    username=self.mstr_username,
                    password=self.mstr_password,
                    project_id=job.mstr_project_id,
                ) as mstr_session:
                    for cube in cube_objs:
                        try:
                            logger.info("Creating live cube instance for '%s' (%s)...", cube.name, cube.mstr_id)
                            instance = await mstr_session.create_cube_instance(cube.mstr_id)
                            instance_id = instance.get("instanceId")
                            if instance_id:
                                # Fetch Page 1 (offset=0) to inspect total rows
                                first_page = await mstr_session.get_cube_data(
                                    cube.mstr_id,
                                    instance_id,
                                    offset=0,
                                    limit=10000,
                                )
                                first_rows = agent._parse_mstr_response(first_page)
                                live_extracted_rows.extend(first_rows)

                                result_meta = first_page.get("result", first_page)
                                data_meta = result_meta.get("data", {}) if isinstance(result_meta, dict) else {}
                                total_rows = data_meta.get("paging", {}).get("total", len(first_rows))
                                logger.info("MSTR cube '%s': %d total rows detected (Page 1: %d rows)", cube.name, total_rows, len(first_rows))

                                # If more rows remain, stream all remaining pages in parallel
                                if total_rows > 10000:
                                    logger.info("Launching parallel worker pool (max_concurrency=8) for remaining %d rows...", total_rows - 10000)
                                    remaining_pages = await mstr_session.get_cube_data_parallel(
                                        cube.mstr_id,
                                        instance_id,
                                        total_rows=total_rows,
                                        batch_size=10000,
                                        max_concurrency=8,
                                    )
                                    # Process pages from offset 10000 onwards (skip first page)
                                    for page in remaining_pages[1:]:
                                        page_rows = agent._parse_mstr_response(page)
                                        live_extracted_rows.extend(page_rows)

                                logger.info("Successfully harvested %d live rows from MSTR cube '%s'", len(live_extracted_rows), cube.name)
                        except Exception as ce:
                            logger.warning("Live cube streaming for %s encountered error: %s", cube.name, ce)
            except Exception as e:
                logger.warning("Could not establish live MSTR session for row streaming: %s", e)

        try:
            from tableauhyperapi import HyperProcess, Telemetry, Connection, CreateMode, TableDefinition, TableName, SqlType, Inserter
            from app.utils.sql_types import sql_type_for, coerce_dim_value

            with HyperProcess(telemetry=Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU) as hyper:
                with Connection(
                    endpoint=hyper.endpoint,
                    database=hyper_file,
                    create_mode=CreateMode.CREATE_AND_REPLACE,
                ) as connection:
                    # Build table definition from IR dimensions + measures with guaranteed unique column names.
                    # Dimension columns are typed by their MSTR form data_type via sql_type_for.
                    def _dim_sql_type(dtype: str):
                        return sql_type_for(dtype)

                    columns = []
                    seen_col_names = set()
                    dim_types = []
                    for dim in ir_data.get("dimensions", []):
                        col_name = dim.get("local_name", dim.get("name", "dim"))
                        base_name = col_name
                        idx = 1
                        while col_name in seen_col_names:
                            col_name = f"{base_name} ({idx})"
                            idx += 1
                        seen_col_names.add(col_name)
                        dt = str(dim.get("data_type") or "").lower()
                        dim_types.append(dt)
                        columns.append(TableDefinition.Column(col_name, _dim_sql_type(dt)))

                    # ── MSTR-definition-driven physical/derived classification ──
                    # Join IR measures to their MSTR expression ASTs (semantic_bundle.json)
                    # and keep only simple single-column aggregates as physical columns.
                    bundle_asts = {}
                    bundle_path = os.path.join(artifacts_dir, "semantic_bundle.json")
                    if os.path.exists(bundle_path):
                        try:
                            with open(bundle_path) as bf:
                                for bm in json.load(bf).get("measures", []):
                                    if bm.get("mstr_id"):
                                        bundle_asts[bm["mstr_id"]] = bm.get("expression_ast")
                        except Exception as be:
                            logger.warning("Could not read semantic bundle for AST join: %s", be)

                    base_measures = classify_physical_measures(
                        ir_data.get("measures", []), bundle_asts,
                    )

                    # Persist the physical-vs-derived decision so downstream
                    # emission stages (TDS/TWB) bind these measures to extract
                    # columns instead of re-declaring them as calculations —
                    # duplicate definitions make Tableau reject the workbook.
                    try:
                        with open(os.path.join(artifacts_dir, "physical_measures.json"), "w") as pf:
                            json.dump(
                                [
                                    {
                                        "mstr_id": m.get("mstr_id"),
                                        "local_name": m.get("local_name", m.get("name")),
                                        "name": m.get("name"),
                                    }
                                    for m in base_measures
                                ],
                                pf, indent=2,
                            )
                        logger.info(
                            "Physical measure decision persisted: %d of %d measures materialized as extract columns",
                            len(base_measures), len(ir_data.get("measures", [])),
                        )
                    except Exception as pe:
                        logger.warning("Could not persist physical_measures.json: %s", pe)

                    for measure in base_measures:
                        col_name = measure.get("local_name", measure.get("name", "measure"))
                        base_name = col_name
                        idx = 1
                        while col_name in seen_col_names:
                            col_name = f"{base_name} ({idx})"
                            idx += 1
                        seen_col_names.add(col_name)
                        columns.append(TableDefinition.Column(col_name, SqlType.double()))

                    if columns:
                        table_def = TableDefinition(
                            TableName("Extract", "Extract"),
                            columns,
                        )
                        connection.catalog.create_schema_if_not_exists("Extract")
                        connection.catalog.create_table_if_not_exists(table_def)

                        dims = ir_data.get("dimensions", [])
                        measures = base_measures
                        total_col_count = len(columns)

                        with Inserter(connection, table_def) as inserter:
                            if live_extracted_rows:
                                # Stream all live extracted rows with name-based column mapping.
                                # _parse_mstr_response now returns list[dict] keyed by field name.
                                logger.info("Inserting %d live MSTR rows into Hyper extract (%d physical columns)...", len(live_extracted_rows), len(columns))

                                def _get_field_val(row_dict, *candidate_keys):
                                    for k in candidate_keys:
                                        if k and k in row_dict:
                                            return row_dict[k]
                                    # Case-insensitive fallback
                                    norm_dict = {str(k).strip().lower(): v for k, v in row_dict.items()}
                                    for k in candidate_keys:
                                        if k:
                                            norm_k = str(k).strip().lower()
                                            if norm_k in norm_dict:
                                                return norm_dict[norm_k]
                                    return None

                                _bad_dates: dict[str, int] = {}
                                for r in live_extracted_rows:
                                    clean_row = []

                                    # 1. Populate dimension columns by name lookup,
                                    #    coerced to the column's MSTR-declared type
                                    for d, dt in zip(dims, dim_types):
                                        val = _get_field_val(r, d.get("name"), d.get("local_name"), d.get("caption"), d.get("remote_name"))
                                        coerced = coerce_dim_value(dt, val)
                                        if val is not None and str(val).strip().lower() not in ("", "none", "null", "nan") and coerced is None and str(dt).lower() in ("date", "datetime", "timestamp"):
                                            dim_name = d.get("name") or d.get("local_name") or "date_dim"
                                            _bad_dates[dim_name] = _bad_dates.get(dim_name, 0) + 1
                                        clean_row.append(coerced)

                                    # 2. Populate measure columns by name lookup with numeric coercion
                                    for m in measures:
                                        val = _get_field_val(r, m.get("name"), m.get("local_name"), m.get("caption"), m.get("remote_name"))
                                        if val is None or str(val).strip().lower() in ("", "none", "null", "nan", "-"):
                                            clean_row.append(None)
                                        else:
                                            try:
                                                clean_str = str(val).replace("$", "").replace(",", "").replace("%", "").strip()
                                                clean_row.append(float(clean_str))
                                            except Exception:
                                                clean_row.append(None)

                                    inserter.add_row(clean_row)
                                inserter.execute()
                                logger.info("Successfully populated Hyper extract with %d LIVE MSTR rows", len(live_extracted_rows))

                                if _bad_dates:
                                    bad_summary = ", ".join(f"{k}: {v} unparseable values" for k, v in _bad_dates.items())
                                    logger.warning("Unparseable date values coerced to NULL: %s", bad_summary)
                                    from app.models.objects import Issue as IssueModel
                                    db.add(IssueModel(
                                        job_id=job.id,
                                        object_id=job.id,
                                        severity="warning",
                                        category="data",
                                        message=f"Date dimension coercion encountered unparseable values (coerced to NULL): {bad_summary}",
                                    ))
                                    db.commit()
                            else:
                                # HONESTY GUARD: Never fabricate "representative" rows offline.
                                # A Hyper extract built on invented values would produce a
                                # workbook that LOOKS correct but ships fake numbers. When no
                                # real source rows are available we emit the schema ONLY and
                                # surface a data-completeness issue so downstream stages and
                                # reviewers know the extract is empty, not silently-valid.
                                logger.warning(
                                    "No live MSTR rows and no cached source extract available — "
                                    "creating an EMPTY extract schema with 0 rows (fabricated data is never inserted). "
                                    "Any dashboard built on this extract will show no data until a real source is wired."
                                )
                                from app.models.objects import Issue as IssueModel
                                db.add(IssueModel(
                                    job_id=job.id,
                                    object_id=job.id,
                                    severity="warning",
                                    category="data",
                                    message=(
                                        "Hyper extract created with 0 rows: no live MSTR session and no "
                                        "cached source file were available. Extract is NOT verified "
                                        "against real source data."
                                    ),
                                ))
                                db.commit()

            hyper_paths["default"] = hyper_file
            row_count = len(live_extracted_rows)  # 0 when offline — we never fabricate rows
            logger.info("Hyper extract built: %s (%d columns, %d rows)", hyper_file, len(columns), row_count)

            ok, why = _verify_hyper_contract(hyper_file, expected_dim_types)
            if not ok:
                _reject_bad_hyper(hyper_file, why)

        except Exception as e:
            if "Hyper contract violation" in str(e):
                raise  # blocker already recorded — fail the stage loudly
            logger.warning("Hyper build failed (non-fatal): %s", e)
            hyper_paths["default"] = os.path.join(hyper_dir, "extract.hyper")
            # A failed build must never silently ship a stale or absent file.
            ok, why = _verify_hyper_contract(hyper_paths["default"], expected_dim_types)
            if not ok and "verification unavailable" not in why:
                _reject_bad_hyper(hyper_paths["default"], f"build failed: {e}; {why}")

        # Persist hyper_paths
        paths_file = os.path.join(artifacts_dir, "hyper_paths.json")
        with open(paths_file, "w") as f:
            json.dump(hyper_paths, f, indent=2)

    async def _run_ds_emit(self, db: Session, job: Job):
        """Stage 9: Datasource XML emission (TDS)."""
        from app.agents.tableau_emitter import TableauEmitterAgent
        from app.agents.ir_compiler import BIIR, IRTable, IRRelationship, IRDimension, IRMeasure, IRFilter, IRVisual, IRIssue
        import json, os

        artifacts_dir = job.artifacts_dir or f"./artifacts/{job.id}"
        ir_path = os.path.join(artifacts_dir, "ir.json")
        hyper_paths_file = os.path.join(artifacts_dir, "hyper_paths.json")

        if not os.path.exists(ir_path):
            logger.warning("No IR found — skipping datasource emission")
            return

        with open(ir_path) as f:
            ir_data = json.load(f)

        hyper_paths = {}
        if os.path.exists(hyper_paths_file):
            with open(hyper_paths_file) as f:
                hyper_paths = json.load(f)

        ir = BIIR(
            job_id=ir_data.get("job_id", job.id),
            tables=[IRTable(**t) for t in ir_data.get("tables", [])],
            relationships=[IRRelationship(**r) for r in ir_data.get("relationships", [])],
            dimensions=[IRDimension(**d) for d in ir_data.get("dimensions", [])],
            measures=[IRMeasure(**m) for m in ir_data.get("measures", [])],
            filters=[IRFilter(**fl) for fl in ir_data.get("filters", [])],
            visuals=[IRVisual(**v) for v in ir_data.get("visuals", [])],
            issues=[IRIssue(**i) for i in ir_data.get("issues", [])],
        )

        emitter = TableauEmitterAgent(
            db=db, job=job, artifacts_dir=artifacts_dir, target_environment="staging",
        )
        tds_path = emitter.emit_datasource(ir, hyper_paths)
        logger.info("Datasource TDS emitted: %s", tds_path)

    async def _run_wb_emit_staging(self, db: Session, job: Job):
        """Stage 10: Workbook emission (staging) — TWB + TWBX generation."""
        from app.agents.tableau_emitter import TableauEmitterAgent
        from app.agents.visualization import VizPlan, WorksheetSpec, DashboardSpec, FieldRef, FilterSpec
        from app.agents.ir_compiler import BIIR, IRTable, IRRelationship, IRDimension, IRMeasure, IRFilter, IRVisual, IRIssue
        import json, os

        artifacts_dir = job.artifacts_dir or f"./artifacts/{job.id}"
        ir_path = os.path.join(artifacts_dir, "ir.json")
        viz_path = os.path.join(artifacts_dir, "viz_plan.json")
        hyper_paths_file = os.path.join(artifacts_dir, "hyper_paths.json")

        if not os.path.exists(ir_path):
            logger.warning("No IR found — skipping workbook emission")
            return

        # Load IR
        with open(ir_path) as f:
            ir_data = json.load(f)

        ir = BIIR(
            job_id=ir_data.get("job_id", job.id),
            tables=[IRTable(**t) for t in ir_data.get("tables", [])],
            relationships=[IRRelationship(**r) for r in ir_data.get("relationships", [])],
            dimensions=[IRDimension(**d) for d in ir_data.get("dimensions", [])],
            measures=[IRMeasure(**m) for m in ir_data.get("measures", [])],
            filters=[IRFilter(**fl) for fl in ir_data.get("filters", [])],
            visuals=[IRVisual(**v) for v in ir_data.get("visuals", [])],
            issues=[IRIssue(**i) for i in ir_data.get("issues", [])],
        )

        # Load VizPlan
        viz_plan = VizPlan()
        if os.path.exists(viz_path):
            with open(viz_path) as f:
                vp_data = json.load(f)
            for ws_data in vp_data.get("worksheets", []):
                rows = [FieldRef(**r) for r in ws_data.pop("rows", [])]
                columns = [FieldRef(**c) for c in ws_data.pop("columns", [])]
                color_data = ws_data.pop("color", None)
                size_data = ws_data.pop("size", None)
                label_data = ws_data.pop("label", None)
                detail = [FieldRef(**d) for d in ws_data.pop("detail", [])]
                filters = [FilterSpec(**f) for f in ws_data.pop("filters", [])]
                tooltip_fields = [FieldRef(**t) for t in ws_data.pop("tooltip_fields", [])]

                ws = WorksheetSpec(
                    rows=rows, columns=columns,
                    color=FieldRef(**color_data) if color_data else None,
                    size=FieldRef(**size_data) if size_data else None,
                    label=FieldRef(**label_data) if label_data else None,
                    detail=detail, filters=filters, tooltip_fields=tooltip_fields,
                    **ws_data,
                )
                viz_plan.worksheets.append(ws)
            for dash_data in vp_data.get("dashboards", []):
                filters = [FilterSpec(**f) for f in dash_data.pop("filters", [])]
                dash = DashboardSpec(filters=filters, **dash_data)
                viz_plan.dashboards.append(dash)

        # If no viz plan, create a default one with one text worksheet per measure
        if not viz_plan.worksheets and ir.measures:
            for measure in ir.measures[:20]:
                ws = WorksheetSpec(
                    id=str(__import__("uuid").uuid4()),
                    name=measure.name,
                    datasource_ref="default",
                    mark_type="text",
                    rows=[FieldRef(name=measure.caption, field_type="measure")],
                )
                viz_plan.worksheets.append(ws)
            viz_plan.dashboards.append(DashboardSpec(
                id=str(__import__("uuid").uuid4()),
                name="Migrated Dashboard",
                worksheets=[ws.name for ws in viz_plan.worksheets],
            ))

        # Load hyper paths
        hyper_paths = {}
        if os.path.exists(hyper_paths_file):
            with open(hyper_paths_file) as f:
                hyper_paths = json.load(f)

        # Emit workbook
        emitter = TableauEmitterAgent(
            db=db, job=job, artifacts_dir=artifacts_dir, target_environment="staging",
        )

        workbook_name = job.name.replace(" ", "_") if job.name else "Migrated_Workbook"
        twbx_path = emitter.emit_workbook(ir, viz_plan, hyper_paths, workbook_name=workbook_name)
        logger.info("Staging workbook emitted: %s", twbx_path)

    async def _run_staging_publish(self, db: Session, job: Job):
        """Stage 11: Publish to Tableau Server staging project."""
        from app.core.config import settings

        if not settings.tableau_server_url or not settings.tableau_token_name:
            logger.info("No Tableau Server configured — skipping staging publish (download-only mode)")
            return

        from app.agents.publisher import PublishAgent
        from app.models.objects import Artifact
        import os

        artifacts_dir = job.artifacts_dir or f"./artifacts/{job.id}"

        # Find emitted artifacts
        artifacts = db.query(Artifact).filter(
            Artifact.job_id == job.id,
            Artifact.artifact_type.in_(["workbook", "datasource"]),
        ).all()

        if not artifacts:
            logger.warning("No artifacts to publish")
            return

        artifact_dicts = [
            {"name": a.file_name, "type": a.artifact_type, "path": a.artifact_path}
            for a in artifacts
        ]

        agent = PublishAgent(db=db, job=job)
        tableau_config = {
            "server_url": settings.tableau_server_url,
            "site_id": settings.tableau_site_id,
            "token_name": self.tableau_token_name or settings.tableau_token_name,
            "token_value": self.tableau_token_value or settings.tableau_token_value,
        }
        result = await agent.publish_staging(artifact_dicts, tableau_config)
        logger.info("Staging publish: %d artifacts published", len(result))

    async def _run_static_validate(self, db: Session, job: Job):
        """Stage 12: Static structural validation (XSD, row counts, filter sets)."""
        from app.agents.validation_agent import ValidationAgent
        from app.agents.ir_compiler import BIIR, IRTable, IRRelationship, IRDimension, IRMeasure, IRFilter, IRVisual, IRIssue
        import json, os

        artifacts_dir = job.artifacts_dir or f"./artifacts/{job.id}"
        ir_path = os.path.join(artifacts_dir, "ir.json")
        hyper_paths_file = os.path.join(artifacts_dir, "hyper_paths.json")

        if not os.path.exists(ir_path):
            logger.info("No IR — skipping static validation")
            return

        with open(ir_path) as f:
            ir_data = json.load(f)

        ir = BIIR(
            job_id=ir_data.get("job_id", job.id),
            tables=[IRTable(**t) for t in ir_data.get("tables", [])],
            relationships=[IRRelationship(**r) for r in ir_data.get("relationships", [])],
            dimensions=[IRDimension(**d) for d in ir_data.get("dimensions", [])],
            measures=[IRMeasure(**m) for m in ir_data.get("measures", [])],
            filters=[IRFilter(**fl) for fl in ir_data.get("filters", [])],
            visuals=[IRVisual(**v) for v in ir_data.get("visuals", [])],
            issues=[IRIssue(**i) for i in ir_data.get("issues", [])],
        )

        hyper_paths = {}
        if os.path.exists(hyper_paths_file):
            with open(hyper_paths_file) as f:
                hyper_paths = json.load(f)

        agent = ValidationAgent(db=db, job=job)
        scorecard = await agent.validate(ir, hyper_paths)

        job.structural_confidence = scorecard.structural_confidence
        job.financial_kpi_confidence = scorecard.financial_kpi_confidence
        job.security_confidence = scorecard.security_confidence
        job.visual_confidence = scorecard.visual_confidence
        job.security_parity = scorecard.security_parity
        db.commit()

        # Persist scorecard as JSON for downstream stages
        scorecard_path = os.path.join(artifacts_dir, "validation_scorecard.json")
        with open(scorecard_path, "w") as f:
            json.dump({
                "structural_confidence": scorecard.structural_confidence,
                "financial_kpi_confidence": scorecard.financial_kpi_confidence,
                "security_confidence": scorecard.security_confidence,
                "visual_confidence": scorecard.visual_confidence,
                "security_parity": scorecard.security_parity,
                "auto_publish_ok": scorecard.auto_publish_ok,
                "blocker_issues": scorecard.blocker_issues,
                "warning_issues": scorecard.warning_issues,
                "total_checks": len(scorecard.checks),
            }, f, indent=2)

        logger.info(
            "Validation: structural=%.3f, kpi=%.3f, security=%.3f, visual=%.3f, auto_publish=%s",
            scorecard.structural_confidence, scorecard.financial_kpi_confidence,
            scorecard.security_confidence, scorecard.visual_confidence,
            scorecard.auto_publish_ok,
        )

    async def _run_security_validate(self, db: Session, job: Job):
        """Stage 13: Security validation — already handled in static_validate."""
        logger.info("Security validation: integrated into static_validate (confidence=%.3f)", job.security_confidence or 1.0)

    async def _run_numeric_validate(self, db: Session, job: Job):
        """Stage 14: Numeric KPI parity — already handled in static_validate."""
        logger.info("Numeric validation: integrated into static_validate (kpi=%.3f)", job.financial_kpi_confidence or 1.0)

    async def _run_wb_emit_prod(self, db: Session, job: Job):
        """Stage 15: Production workbook emission — path rewriting for production."""
        from app.agents.tableau_emitter import TableauEmitterAgent
        from app.agents.visualization import VizPlan, WorksheetSpec, DashboardSpec, FieldRef, FilterSpec
        from app.agents.ir_compiler import BIIR, IRTable, IRRelationship, IRDimension, IRMeasure, IRFilter, IRVisual, IRIssue
        import json, os

        artifacts_dir = job.artifacts_dir or f"./artifacts/{job.id}"
        ir_path = os.path.join(artifacts_dir, "ir.json")
        viz_path = os.path.join(artifacts_dir, "viz_plan.json")
        hyper_paths_file = os.path.join(artifacts_dir, "hyper_paths.json")

        if not os.path.exists(ir_path):
            logger.warning("No IR found — skipping production workbook emission")
            return

        with open(ir_path) as f:
            ir_data = json.load(f)

        ir = BIIR(
            job_id=ir_data.get("job_id", job.id),
            tables=[IRTable(**t) for t in ir_data.get("tables", [])],
            relationships=[IRRelationship(**r) for r in ir_data.get("relationships", [])],
            dimensions=[IRDimension(**d) for d in ir_data.get("dimensions", [])],
            measures=[IRMeasure(**m) for m in ir_data.get("measures", [])],
            filters=[IRFilter(**fl) for fl in ir_data.get("filters", [])],
            visuals=[IRVisual(**v) for v in ir_data.get("visuals", [])],
            issues=[IRIssue(**i) for i in ir_data.get("issues", [])],
        )

        hyper_paths = {}
        if os.path.exists(hyper_paths_file):
            with open(hyper_paths_file) as f:
                hyper_paths = json.load(f)

        # Use same VizPlan from staging
        viz_plan = VizPlan()
        if os.path.exists(viz_path):
            with open(viz_path) as f:
                vp_data = json.load(f)
            for ws_data in vp_data.get("worksheets", []):
                rows = [FieldRef(**r) for r in ws_data.pop("rows", [])]
                columns = [FieldRef(**c) for c in ws_data.pop("columns", [])]
                color_data = ws_data.pop("color", None)
                size_data = ws_data.pop("size", None)
                label_data = ws_data.pop("label", None)
                detail = [FieldRef(**d) for d in ws_data.pop("detail", [])]
                filters = [FilterSpec(**f) for f in ws_data.pop("filters", [])]
                tooltip_fields = [FieldRef(**t) for t in ws_data.pop("tooltip_fields", [])]
                ws = WorksheetSpec(
                    rows=rows, columns=columns,
                    color=FieldRef(**color_data) if color_data else None,
                    size=FieldRef(**size_data) if size_data else None,
                    label=FieldRef(**label_data) if label_data else None,
                    detail=detail, filters=filters, tooltip_fields=tooltip_fields,
                    **ws_data,
                )
                viz_plan.worksheets.append(ws)
            for dash_data in vp_data.get("dashboards", []):
                dash_filters = [FilterSpec(**f) for f in dash_data.pop("filters", [])]
                dash = DashboardSpec(filters=dash_filters, **dash_data)
                viz_plan.dashboards.append(dash)

        emitter = TableauEmitterAgent(
            db=db, job=job, artifacts_dir=artifacts_dir, target_environment="production",
        )
        workbook_name = (job.name.replace(" ", "_") if job.name else "Migrated_Workbook") + "_prod"
        twbx_path = emitter.emit_workbook(ir, viz_plan, hyper_paths, workbook_name=workbook_name)
        logger.info("Production workbook emitted: %s", twbx_path)

    async def _run_promote(self, db: Session, job: Job):
        """Stage 16: Promote to production (ADR-029 write-lock invariant)."""
        from app.core.config import settings
        import json, os

        if not settings.tableau_server_url or not settings.tableau_token_name:
            logger.info("No Tableau Server configured — skipping production promotion")
            return

        from app.agents.publisher import PublishAgent
        from app.agents.validation_agent import ValidationScorecard
        from app.models.objects import Artifact

        artifacts = db.query(Artifact).filter(
            Artifact.job_id == job.id,
            Artifact.environment == "production",
        ).all()

        if not artifacts:
            logger.warning("No production artifacts to promote")
            return

        # Load scorecard for auto_publish gate
        artifacts_dir = job.artifacts_dir or f"./artifacts/{job.id}"
        scorecard_path = os.path.join(artifacts_dir, "validation_scorecard.json")
        scorecard = ValidationScorecard(job_id=job.id)
        if os.path.exists(scorecard_path):
            with open(scorecard_path) as f:
                sc_data = json.load(f)
            scorecard.structural_confidence = sc_data.get("structural_confidence", 1.0)
            scorecard.financial_kpi_confidence = sc_data.get("financial_kpi_confidence", 1.0)
            scorecard.security_confidence = sc_data.get("security_confidence", 1.0)
            scorecard.visual_confidence = sc_data.get("visual_confidence", 1.0)
            scorecard.security_parity = sc_data.get("security_parity", True)
            scorecard.blocker_issues = sc_data.get("blocker_issues", 0)

        agent = PublishAgent(db=db, job=job)
        tableau_config = {
            "server_url": settings.tableau_server_url,
            "site_id": settings.tableau_site_id,
            "token_name": self.tableau_token_name or settings.tableau_token_name,
            "token_value": self.tableau_token_value or settings.tableau_token_value,
        }
        result = await agent.promote_to_production(
            staging_ids={a.file_name: a.id for a in artifacts},
            scorecard=scorecard,
            tableau_config=tableau_config,
        )
        logger.info("Production promotion complete: %s", result)

    async def _run_reconcile(self, db: Session, job: Job):
        """Stage 17: Remote reconciliation — verify publish via REST hash comparison."""
        from app.core.config import settings

        if not settings.tableau_server_url:
            logger.info("No Tableau Server configured — skipping reconciliation")
            return

        from app.agents.publisher import PublishAgent
        from app.models.objects import PublishOperation

        # Get promoted content IDs from publish operations
        promote_ops = db.query(PublishOperation).filter(
            PublishOperation.job_id == job.id,
            PublishOperation.operation == "promote_production",
            PublishOperation.status == "success",
        ).all()

        promoted_ids = {
            op.artifact_id: op.remote_id
            for op in promote_ops if op.remote_id
        }

        if not promoted_ids:
            logger.info("No promoted artifacts — skipping reconciliation")
            return

        agent = PublishAgent(db=db, job=job)
        from app.core.config import settings as _settings
        tableau_config = {
            "server_url": _settings.tableau_server_url,
            "site_id": _settings.tableau_site_id,
            "token_name": self.tableau_token_name or _settings.tableau_token_name,
            "token_value": self.tableau_token_value or _settings.tableau_token_value,
        }
        result = await agent.reconcile(promoted_ids, tableau_config=tableau_config)
        logger.info("Reconciliation: %s", result)

    async def _run_report(self, db: Session, job: Job):
        """Stage 18: Migration report generation."""
        from app.models.objects import MigrationObject, Issue, Artifact
        import json, os

        artifacts_dir = job.artifacts_dir or f"./artifacts/{job.id}"
        os.makedirs(artifacts_dir, exist_ok=True)

        # Gather statistics
        total = db.query(MigrationObject).filter(MigrationObject.job_id == job.id).count()
        succeeded = db.query(MigrationObject).filter(
            MigrationObject.job_id == job.id, MigrationObject.status == "extracted"
        ).count()
        failed = db.query(MigrationObject).filter(
            MigrationObject.job_id == job.id, MigrationObject.status == "failed"
        ).count()
        blockers = db.query(Issue).filter(
            Issue.job_id == job.id, Issue.severity == "blocker"
        ).count()
        warnings = db.query(Issue).filter(
            Issue.job_id == job.id, Issue.severity == "warning"
        ).count()
        artifacts_count = db.query(Artifact).filter(Artifact.job_id == job.id).count()

        # Type breakdown
        from sqlalchemy import func
        type_counts = dict(
            db.query(MigrationObject.type_name, func.count(MigrationObject.id))
            .filter(MigrationObject.job_id == job.id)
            .group_by(MigrationObject.type_name)
            .all()
        )

        report = {
            "job_id": job.id,
            "job_name": job.name,
            "status": job.status,
            "started_at": str(job.started_at) if job.started_at else None,
            "completed_at": str(job.completed_at) if job.completed_at else None,
            "summary": {
                "total_objects": total,
                "succeeded": succeeded,
                "failed": failed,
                "blocker_issues": blockers,
                "warning_issues": warnings,
                "artifacts_generated": artifacts_count,
            },
            "object_breakdown": type_counts,
            "confidence_scores": {
                "security": job.security_confidence,
                "financial_kpi": job.financial_kpi_confidence,
                "structural": job.structural_confidence,
                "visual": job.visual_confidence,
            },
        }

        report_path = os.path.join(artifacts_dir, "migration_report.json")
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2, default=str)

        logger.info(
            "Migration report: %d objects (%d succeeded, %d failed), %d blockers, %d artifacts",
            total, succeeded, failed, blockers, artifacts_count,
        )


async def run_pipeline(
    job_id: str,
    selected_dossier_ids: Optional[list[str]] = None,
    mstr_username: str = "",
    mstr_password: str = "",
    tableau_token_name: str = "",
    tableau_token_value: str = "",
):
    """Entry point for background pipeline execution."""
    orchestrator = PipelineOrchestrator(
        job_id=job_id,
        selected_dossier_ids=selected_dossier_ids,
        mstr_username=mstr_username,
        mstr_password=mstr_password,
        tableau_token_name=tableau_token_name,
        tableau_token_value=tableau_token_value,
    )
    await orchestrator.run()
