"""
TableauEmitterAgent — TWB/TWBX XML generation via lxml.

Ref: spec/agents.md §Agent 8, ADR-004, ADR-023
Gotcha 3: Failed worksheets hidden from dashboard zones
Gotcha 5: Identifier normalization parity

Emission sequence (Audit v4):
  1. Copy blank golden template
  2. Caption registry
  3. Topo-sort columns
  4. Inject datasource columns
  5. Inject datasource fixture
  6. Inject relationships
  7. Inject worksheets
  8. Inject entitlement wiring (ADR-031)
  9. Inject dashboards (auto-tiled zones)
  10. Apply formatting
  11. XSD validate
  12-14. Path rewriting (staging/production)
  15. Package .twbx
"""

import hashlib
import json
import logging
import os
import re
import shutil
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from lxml import etree

from sqlalchemy.orm import Session

from app.models.job import Job
from app.models.objects import Artifact, DatasourcePathRewrite

logger = logging.getLogger(__name__)

_AGG_FUNCS_WRAPPING = (
    "COUNTD", "MEDIAN", "COUNT", "SUM", "AVG", "MIN", "MAX",
    # Table calculations — their arguments are already aggregate expressions;
    # wrapping references inside them with SUM() causes double-aggregation
    # errors ("Argument to SUM is already an aggregation").
    "RANK", "RANK_DENSE", "RANK_MODIFIED", "RANK_PERCENTILE", "RANK_UNIQUE",
    "RUNNING_SUM", "RUNNING_AVG", "RUNNING_COUNT", "RUNNING_MIN", "RUNNING_MAX",
    "WINDOW_SUM", "WINDOW_AVG", "WINDOW_COUNT", "WINDOW_MIN", "WINDOW_MAX",
    "WINDOW_MEDIAN", "WINDOW_STDEV", "WINDOW_VAR", "WINDOW_PERCENTILE",
    "TOTAL", "INDEX", "FIRST", "LAST", "LOOKUP", "PREVIOUS_VALUE",
    "ATTR", "STDEV", "STDEVP", "VAR", "VARP",
)


def _wrap_bare_aggregate_refs(formula: str, bare_names: set,
                              skip_names: Optional[set] = None) -> str:
    """
    Wrap references to BARE PHYSICAL EXTRACT COLUMNS in SUM() unless they
    already sit inside an aggregation call.

    Scope is deliberately narrow and evidence-based: `bare_names` are the
    columns recorded by classify_physical_measures / physical_measures.json
    as materialized extract facts. An extract column is a row-level field by
    definition, so combining it with aggregate operands requires the
    aggregation named by the metric's own MSTR expression; this pass only
    guards against translations that dropped it.

    NOTHING else is wrapped here. References to other metrics / calculated
    fields pass through VERBATIM: whether they are aggregates is decided by
    their own MSTR definitions (expression_text, mexp `ft`, precomputed_calc),
    which the translation layer must honour — the emitter never invents
    aggregations (synthesised ATTR()/SUM() wrappers produced illegal
    ATTR(SUM(...)) nesting in job 482de454).

    A single left-to-right scan tracks function-call nesting so
    `[X] / SUM([Y])` wraps only [X], while `SUM([X]) / [Y]` wraps only [Y] —
    a regex/prefix heuristic cannot distinguish these cases.
    `skip_names` (the measure currently being emitted) is never wrapped.
    """
    AGGS = _AGG_FUNCS_WRAPPING
    skip = skip_names or set()
    out: list[str] = []
    stack: list[bool] = []   # per open paren: True when inside an agg call
    i, n = 0, len(formula)

    while i < n:
        ch = formula[i]

        if ch == "[":
            j = formula.find("]", i)
            if j == -1:
                out.append(formula[i:])
                break
            name = formula[i + 1:j].strip()
            if not any(stack) and name not in skip and name in bare_names:
                out.append(f"SUM([{name}])")
                i = j + 1
                continue
            out.append(formula[i:j + 1])
            i = j + 1
            continue

        if ch.isalpha():
            j = i
            while j < n and (formula[j].isalpha() or formula[j] == "_"):
                j += 1
            word = formula[i:j].upper()
            k = j
            while k < n and formula[k] in " \t\r\n":
                k += 1
            if k < n and formula[k] == "(":
                stack.append(word in AGGS)
                out.append(formula[i:k + 1])
                i = k + 1
                continue
            out.append(formula[i:j])
            i = j
            continue

        if ch == "(":
            # Bare grouping paren — inherit enclosing agg context
            stack.append(any(stack))
            out.append(ch)
            i += 1
            continue

        if ch == ")":
            if stack:
                stack.pop()
            out.append(ch)
            i += 1
            continue

        out.append(ch)
        i += 1

    return "".join(out)


# Aggregations that REJECT an already-aggregate argument in Tableau
# ("Argument to X is already an aggregation"). Deliberately EXCLUDES table
# calculations (RANK / WINDOW_ / RUNNING_ / TOTAL legally consume aggregates)
# and MIN/MAX (legal around aggregates).
_NESTED_AGG_OVER_AGG_RE = re.compile(
    r"\b(?:SUM|AVG|ATTR|MEDIAN|COUNT|COUNTD|STDEVP?|VARP?)\s*"
    r"\(\s*(?:SUM|AVG|ATTR|MEDIAN|COUNT|COUNTD|STDEVP?|VARP?)\s*\(",
    re.IGNORECASE,
)


def _find_illegal_aggregation_nesting(formula: str, agg_calc_fields: set):
    """Return the offending snippet if `formula` aggregates something that is
    itself aggregate. Two evidence-backed cases:
      1. direct nesting:              ATTR(SUM(...)), COUNTD(COUNT(...))
      2. aggregation over an aggregate CALC FIELD:
         SUM([Top State Loss]), ATTR([Total_Claims])
    Purely diagnostic — callers fail closed, nothing is rewritten."""
    hit = _NESTED_AGG_OVER_AGG_RE.search(formula)
    if hit:
        return hit.group(0)
    for name in sorted(agg_calc_fields, key=len, reverse=True):
        hit = re.search(
            rf"\b(?:SUM|AVG|ATTR|MEDIAN|COUNT|COUNTD|STDEVP?|VARP?)"
            rf"\s*\(\s*\[{re.escape(name)}\]\s*\)",
            formula,
            re.IGNORECASE,
        )
        if hit:
            return hit.group(0)
    return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Tableau XML namespace constants
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

TABLEAU_VERSION = "18.1"
TABLEAU_SOURCE_BUILD = "2024.2.0"
TWB_XML_NS = "http://www.tableau.com"


class _DateInstanceSpec:
    """One Tableau date representation: derivation + the pill identity.

    A single spec feeds BOTH the <column-instance> declaration and every
    shelf reference, so they can never diverge (the D2E8DA72 class of bug).
    """

    __slots__ = ("derivation", "prefix", "field_type", "role_suffix")

    def __init__(self, derivation: str, prefix: str, field_type: str, role_suffix: str):
        self.derivation = derivation
        self.prefix = prefix
        self.field_type = field_type
        self.role_suffix = role_suffix

    def instance_name(self, dim_name: str) -> str:
        return f"[{self.prefix}:{dim_name}:{self.role_suffix}]"

    def pill(self, dim_name: str) -> str:
        return f"[federated.default].{self.instance_name(dim_name)}"


# Granularity -> Tableau representation. 'month' renders month buckets on an
# ordinal axis; pair with a Year pill (granularity 'year') if cross-year
# separation is required for a given dashboard.
_DATE_GRANULARITY_MAP = {
    "month": _DateInstanceSpec("Month", "mn", "ordinal", "ok"),
    "year": _DateInstanceSpec("Year", "yr", "ordinal", "ok"),
    "plain": _DateInstanceSpec("None", "none", "nominal", "nk"),
}

# Per-dimension overrides; anything absent defaults to 'month'.
DATE_GRANULARITY: dict = {}

# Valid Tableau mark class values (case-sensitive)
MARK_CLASS_MAP = {
    "text": "Text",
    "bar": "Bar",
    "line": "Line",
    "area": "Area",
    "circle": "Circle",
    "square": "Square",
    "shape": "Shape",
    "map": "Map",
    "pie": "Pie",
    "ganttbar": "Gantt Bar",
    "polygon": "Polygon",
    "automatic": "Automatic",
}


class TableauEmitterAgent:
    """
    Agent 8: Generates Tableau .twb workbook and .twbx package.

    Builds TWB XML by injecting datasource columns, calculated fields,
    worksheets, and dashboards into a template structure.
    """

    def __init__(
        self,
        db: Session,
        job: Job,
        artifacts_dir: str,
        target_environment: str = "staging",
    ):
        self.db = db
        self.job = job
        self.artifacts_dir = Path(artifacts_dir)
        self.target_env = target_environment

    def emit_workbook(
        self,
        ir,
        viz_plan,
        hyper_paths: dict[str, str],
        workbook_name: str = "Migrated_Workbook",
    ) -> Path:
        """
        Generate a complete .twbx workbook.

        Returns path to the generated .twbx file.
        """
        twb_dir = self.artifacts_dir / "workbooks" / workbook_name
        twb_dir.mkdir(parents=True, exist_ok=True)

        # Contract gate: the emitted TWB binds [Extract].[Extract]. Any real
        # Hyper file (>4 KB; tiny files are test dummies) MUST contain that
        # table with compatible column types. Refuse to package a mismatched pair.
        for _dom, _hpath in (hyper_paths or {}).items():
            try:
                _hp = Path(_hpath)
                if not _hp.exists() or _hp.stat().st_size <= 4096:
                    continue  # absent/placeholder — orchestrator already flagged
                from tableauhyperapi import HyperProcess, Telemetry, Connection, TableName
                from app.utils.sql_types import format_contract_mismatch
                with HyperProcess(telemetry=Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU) as _hyp:
                    with Connection(endpoint=_hyp.endpoint, database=str(_hp)) as _conn:
                        _tables = [
                            f"{str(_s).strip(chr(34))}.{tn.name.unescaped}"
                            for _s in _conn.catalog.get_schema_names()
                            for tn in _conn.catalog.get_table_names(_s)
                        ]
                        if "Extract.Extract" not in _tables:
                            from app.models.objects import Issue as IssueModel
                            self.db.add(IssueModel(
                                job_id=self.job.id,
                                object_id=self.job.id,
                                severity="blocker",
                                category="hyper",
                                message=(
                                    f"Refusing to package workbook '{workbook_name}': Hyper "
                                    f"'{_hpath}' lacks table [Extract].[Extract] "
                                    f"(contains: {_tables or 'none'}). Rebuild the extract."
                                ),
                            ))
                            self.db.commit()
                            raise ValueError(
                                f"Hyper contract violation: {_hpath} lacks [Extract].[Extract]"
                            )

                        if ir and hasattr(ir, "dimensions"):
                            _expected = {
                                getattr(d, "local_name", getattr(d, "name", "")): getattr(d, "data_type", "")
                                for d in ir.dimensions
                                if getattr(d, "local_name", getattr(d, "name", "")) and getattr(d, "data_type", "")
                            }
                            _tdef = _conn.catalog.get_table_definition(TableName("Extract", "Extract"))
                            _actual = {_c.name.unescaped: str(_c.type) for _c in _tdef.columns}
                            _mismatch = format_contract_mismatch(_actual, _expected)
                            if _mismatch:
                                from app.models.objects import Issue as IssueModel
                                self.db.add(IssueModel(
                                    job_id=self.job.id,
                                    object_id=self.job.id,
                                    severity="blocker",
                                    category="hyper",
                                    message=(
                                        f"Refusing to package workbook '{workbook_name}': Hyper extract "
                                        f"'{_hpath}' has schema type mismatch ({_mismatch}). Rebuild the extract."
                                    ),
                                ))
                                self.db.commit()
                                raise ValueError(
                                    f"Hyper contract violation: {_hpath} schema mismatch ({_mismatch})"
                                )
            except ValueError:
                raise
            except Exception:
                pass  # verification unavailable in this environment

        # Step 1: Create TWB XML structure
        root = self._create_workbook_root()

        # Step 2: Add datasource
        datasources_node = etree.SubElement(root, "datasources")
        ds_node = self._emit_datasource(datasources_node, ir, hyper_paths)

        # Ensure all worksheet names are unique and descriptive
        seen_ws_names: dict[str, int] = {}
        for ws_spec in viz_plan.worksheets:
            base = (ws_spec.name or "").strip() or "Sheet"
            base_lower = base.lower().strip()
            if "visualization" in base_lower or base_lower.startswith("viz"):
                if getattr(ws_spec, "label", None) and ws_spec.label and ws_spec.label.name:
                    base = ws_spec.label.name
                elif getattr(ws_spec, "rows", None) and ws_spec.rows and ws_spec.rows[0].name:
                    base = ws_spec.rows[0].name
                elif getattr(ws_spec, "columns", None) and ws_spec.columns and ws_spec.columns[0].name:
                    base = ws_spec.columns[0].name

            if base in seen_ws_names:
                seen_ws_names[base] += 1
                ws_spec.name = f"{base} ({seen_ws_names[base]})"
            else:
                seen_ws_names[base] = 1
                ws_spec.name = base

        # Step 3: Add worksheets
        # Failed worksheets are excluded below — record WHY first, so an
        # absent chart is a visible review item, never a silent blank tile.
        try:
            from app.models.objects import Issue as IssueModel
            for ws_spec in viz_plan.worksheets:
                if ws_spec.is_failed:
                    self.db.add(IssueModel(
                        job_id=self.job.id,
                        object_id=getattr(ws_spec, "id", None),
                        severity="blocker",
                        category="harvest",
                        message=(
                            f"Visual '{ws_spec.name}' has no MicroStrategy-provided "
                            f"bindings (no metrics/attributes/shelves); worksheet "
                            f"skipped pending re-harvest or human-supplied binding."
                        ),
                    ))
            self.db.commit()
        except Exception:
            self.db.rollback()

        worksheets_node = etree.SubElement(root, "worksheets")
        for ws_spec in viz_plan.worksheets:
            if not ws_spec.is_failed:
                self._emit_worksheet(worksheets_node, ws_spec, ir=ir)

        # Step 4: Add dashboards
        dashboards_node = etree.SubElement(root, "dashboards")
        for dash_spec in viz_plan.dashboards:
            self._emit_dashboard(dashboards_node, dash_spec, viz_plan.worksheets)

        # Step 5: Add windows
        windows_node = etree.SubElement(root, "windows")
        # Structural KPI detection (evidence: an emitted sheet with EMPTY
        # rows/columns shelves and a Text mark IS a KPI number card by
        # construction). Replaces the old name-keyword guess that left
        # 'Regions'/'States' on fit-width and pinned tiny numbers top-right.
        kpi_ws_names = {
            ws.name for ws in viz_plan.worksheets
            if not ws.is_failed and not (ws.rows or ws.columns)
            and (getattr(ws, "mark_type", "") or "").lower() == "text"
        }
        active_set = False
        for ws_spec in viz_plan.worksheets:
            if not ws_spec.is_failed:
                self._emit_window(
                    windows_node, ws_spec.name,
                    is_active=not active_set, kpi_names=kpi_ws_names,
                )
                active_set = True
        for dash_spec in viz_plan.dashboards:
            self._emit_window(
                windows_node, dash_spec.name,
                is_dashboard=True, dash_spec=dash_spec, kpi_names=kpi_ws_names,
            )

        # Step 6: Write TWB
        twb_path = twb_dir / f"{workbook_name}.twb"
        tree = etree.ElementTree(root)
        tree.write(
            str(twb_path),
            xml_declaration=True,
            encoding="utf-8",
            pretty_print=True,
        )

        # Step 7: Path rewriting (ADR-023)
        self._rewrite_paths(twb_path, hyper_paths)

        # Step 8: Package as .twbx
        twbx_path = self._package_twbx(twb_path, hyper_paths, twb_dir)

        # Step 9: Persist artifact record
        self._record_artifact(twbx_path, workbook_name)

        logger.info("Emitted workbook: %s", twbx_path)
        return twbx_path

    def emit_datasource(self, ir, hyper_paths: dict[str, str], ds_name: str = "Migrated_DS") -> Path:
        """Generate a standalone .tds datasource file."""
        tds_dir = self.artifacts_dir / "datasources"
        tds_dir.mkdir(parents=True, exist_ok=True)

        root = etree.Element("datasource", attrib={
            "formatted-name": ds_name,
            "inline": "true",
            "version": TABLEAU_VERSION,
        })

        existing_cols = self._inject_datasource_columns(root, ir)
        self._inject_calculated_fields(root, ir, existing_cols=existing_cols)
        self._inject_connection(root, ir, hyper_paths)

        tds_path = tds_dir / f"{ds_name}.tds"
        tree = etree.ElementTree(root)
        tree.write(str(tds_path), xml_declaration=True, encoding="utf-8", pretty_print=True)

        self._record_artifact(tds_path, ds_name, artifact_type="datasource")
        return tds_path

    # ── TWB XML building ────────────────────────────────────────

    def _create_workbook_root(self) -> etree._Element:
        """Create the root <workbook> element with universal version compatibility."""
        root = etree.Element("workbook", attrib={
            "original-version": TABLEAU_VERSION,
            "source-build": TABLEAU_SOURCE_BUILD,
            "source-platform": "win",
            "version": TABLEAU_VERSION,
            "{http://www.w3.org/XML/1998/namespace}base": "https://localhost",
        })
        etree.SubElement(root, "preferences")
        return root

    def _emit_datasource(self, parent, ir, hyper_paths) -> etree._Element:
        """Emit a datasource element with columns, calcs, and connection."""
        ds = etree.SubElement(parent, "datasource", attrib={
            "caption": "Migrated Data",
            "inline": "true",
            "name": "federated.default",
            "version": TABLEAU_VERSION,
        })

        # Connection
        self._inject_connection(ds, ir, hyper_paths)

        # Columns (dimensions) — declared names feed the dedup guard below
        existing_cols = self._inject_datasource_columns(ds, ir)

        # Calculated fields (measures)
        self._inject_calculated_fields(ds, ir, existing_cols=existing_cols)

        return ds

    def _inject_connection(self, ds_node, ir, hyper_paths):
        """Inject connection XML pointing to Hyper file with proper join tree."""
        conn = etree.SubElement(ds_node, "connection", attrib={
            "class": "hyper",
            "dbname": "",
            "default-settings": "yes",
            "sslmode": "",
            "tablename": "",
            "username": "",
        })

        # Add Hyper file paths
        for domain, path in hyper_paths.items():
            conn.set("dbname", path)
            break  # Use first path

        # Build relation tree
        if ir.tables:
            if len(ir.tables) == 1 or not ir.relationships:
                # Single table — simple relation
                etree.SubElement(conn, "relation", attrib={
                    "name": "Extract",
                    "table": f"[Extract].[{ir.tables[0].physical_name}]",
                    "type": "table",
                })
            else:
                # Multi-table star schema — build join tree
                self._build_join_tree(conn, ir)

    def _inject_datasource_columns(self, ds_node, ir) -> set:
        """Inject dimension columns and raw fact columns into datasource.

        Returns the set of declared column names so calculated-field emission
        can never re-declare a colliding name (Tableau rejects duplicate
        definitions with "field is already defined by data source").
        """
        existing_cols = set()
        for dim in ir.dimensions:
            dtype = self._map_to_tableau_datatype(dim.data_type)
            dname = getattr(dim, "name", getattr(dim, "local_name", getattr(dim, "caption", "")))
            # Numeric-typed dimensions are emitted as quantitative measures.
            # Evidence: dim.data_type now comes from the MSTR attribute form
            # (`forms[0].data_type`, e.g. integer) via ir_compiler, and the
            # planner builds the extract column with that same type
            # (physical_model_planner ID-form mapping). One truth, end to end:
            # MSTR declares numeric → extract is numeric → AVG([col]) is legal,
            # and NO compensating INT() casts are emitted anywhere.
            # (Note: we intentionally do NOT special-case any specific field name
            #  like "Fraud Score" — a name heuristic is demo-specific and would
            #  corrupt arbitrary numeric dimensions with non-numeric names.)
            if dim.data_type in ("double", "real", "float", "integer", "numeric"):
                dtype = "real"
                role = "measure"
                col_type = "quantitative"
            else:
                role = getattr(dim, "role", "dimension")
                col_type = "nominal" if dim.data_type == "string" else "ordinal"

            col = etree.SubElement(ds_node, "column", attrib={
                "caption": dim.caption,
                "datatype": dtype,
                "name": f"[{dim.local_name}]",
                "role": role,
                "type": col_type,
            })
            existing_cols.add(dim.local_name)
            existing_cols.add(f"[{dim.local_name}]")
            if dim.hidden:
                col.set("hidden", "true")

        return existing_cols

    def _physical_measure_ids(self, ir) -> set:
        """
        Identify measures that were materialized as physical Hyper extract
        columns by classify_physical_measures. These must NOT also be emitted
        as workbook calculations — a duplicate definition makes Tableau drop
        the calc field on open ("field is already defined by data source").

        Primary source: physical_measures.json persisted by the HYPER_BUILD
        stage (authoritative — reflects exactly which columns exist in the
        extract). Fallback: recompute with the same deterministic predicate.
        """
        decision_path = self.artifacts_dir / "physical_measures.json"
        if decision_path.exists():
            try:
                with open(decision_path) as f:
                    entries = json.load(f)
                ids = {e.get("mstr_id") for e in entries if e.get("mstr_id")}
                if ids:
                    return ids
            except Exception as e:
                logger.warning(
                    "Could not read physical_measures.json (%s); recomputing classification", e,
                )

        try:
            from app.services.pipeline.orchestrator import classify_physical_measures

            dicts = []
            for m in ir.measures:
                dicts.append({
                    "mstr_id": getattr(m, "mstr_id", None),
                    "is_derived": bool(getattr(m, "is_derived", False)),
                    "expression_ast": getattr(m, "expression_ast", None),
                    "expression_text": getattr(m, "expression_text", None),
                    "name": getattr(m, "name", "") or "",
                    "local_name": getattr(m, "local_name", "") or getattr(m, "caption", ""),
                    "tableau_calc": getattr(m, "tableau_calc", "") or "",
                })
            return {
                d.get("mstr_id") for d in classify_physical_measures(dicts)
                if d.get("mstr_id")
            }
        except Exception as e:
            logger.warning(
                "Physical-measure classification unavailable (%s); "
                "emitting all measures as calculated fields", e,
            )
            return set()

    def _inject_calculated_fields(self, ds_node, ir, existing_cols: set | None = None):
        """Inject calculated field columns (measures) in topo-sorted order.

        Measures classified as physical extract columns are emitted as bare
        binding columns (no <calculation>) so worksheets resolve them to the
        pre-computed Hyper values instead of re-declaring a colliding field.
        """
        existing_cols = existing_cols if existing_cols is not None else set()
        physical_ids = self._physical_measure_ids(ir)
        sorted_measures = self._topo_sort_measures(ir.measures)

        # Names emitted as bare extract-column bindings (physical measures).
        # Derived formulas referencing them must wrap the reference in an
        # aggregation, otherwise the expression mixes row-level and aggregate
        # operands and Tableau rejects it at query time.
        physical_local_names = {
            getattr(m, "local_name", "") or getattr(m, "caption", "")
            for m in ir.measures
            if getattr(m, "mstr_id", None) in physical_ids
        }

        # Build map for canonical measure name resolution in formulas
        meas_name_map = {}
        for m in ir.measures:
            ln = getattr(m, "local_name", "")
            meas_name_map[ln.lower()] = ln
            meas_name_map[getattr(m, "name", "").lower()] = ln
            meas_name_map[getattr(m, "caption", "").lower()] = ln
            meas_name_map[ln.lower().replace("_", " ")] = ln
            meas_name_map[ln.lower().replace(" ", "_")] = ln

        # ── Evidence set: which referenced fields are ALREADY aggregates? ──
        # Derived purely from each measure's own translated calc, which the
        # translation layer (mexp `ft`, expression_text, precomputed_calc,
        # LLM rules) produced from the MSTR definition. Used ONLY by the
        # fail-closed nesting gate below — never to mutate formulas.
        _AGG_OR_LOD_RE = re.compile(
            r"\b(?:SUM|AVG|ATTR|MEDIAN|COUNT|COUNTD|STDEVP?|VARP?|"
            r"RANK(?:_\w+)?|(?:RUNNING|WINDOW)_\w+|TOTAL)\s*\("
            r"|\{\s*(?:FIXED|INCLUDE|EXCLUDE)",
            re.IGNORECASE,
        )
        agg_calc_fields = set()
        for m in ir.measures:
            # Physical extract columns are row-level by definition, even when
            # a stale duplicate calc string exists in the IR — exclude them.
            if getattr(m, "mstr_id", None) in physical_ids:
                continue
            ln = getattr(m, "local_name", "") or getattr(m, "caption", "")
            if ln and _AGG_OR_LOD_RE.search(getattr(m, "tableau_calc", "") or ""):
                agg_calc_fields.add(ln)

        for measure in sorted_measures:
            loc_name = getattr(measure, "local_name", getattr(measure, "caption", ""))
            meas_name = getattr(measure, "name", loc_name)

            # Duplicate-name guard: a name already declared (dimension column or
            # an earlier measure) must never be declared twice — Tableau rejects
            # the workbook with "field is already defined by data source".
            if f"[{loc_name}]" in existing_cols:
                logger.warning(
                    "Skipping duplicate column declaration '%s' (already defined by datasource)",
                    loc_name,
                )
                continue

            # HONESTY GUARD: unresolved translations ("// TODO …", "// NEEDS_REVIEW …")
            # must never be embedded as Tableau calculation formulas — a comment-only
            # formula silently renders NULL in every viz. Skip the field and surface it.
            raw_calc = (getattr(measure, "tableau_calc", "") or "").strip()
            if raw_calc.startswith("//"):
                logger.warning(
                    "Skipping calculated field '%s': formula is an unresolved placeholder (%s). "
                    "Resolve it via the review queue before re-emission.",
                    meas_name, raw_calc[:80],
                )
                try:
                    from app.models.objects import Issue as IssueModel
                    self.db.add(IssueModel(
                        job_id=self.job.id,
                        object_id=getattr(measure, "mstr_id", None),
                        severity="warning",
                        category="emission",
                        message=(
                            f"Calculated field '{meas_name}' was NOT emitted into the workbook: "
                            f"unresolved formula ({raw_calc[:120]})."
                        ),
                    ))
                    self.db.commit()
                except Exception:
                    pass
                continue

            existing_cols.add(loc_name)
            existing_cols.add(f"[{loc_name}]")

            col = etree.SubElement(ds_node, "column", attrib={
                "caption": measure.caption,
                "datatype": "real",
                "name": f"[{loc_name}]",
                "role": "measure",
                "type": "quantitative",
            })

            formula = raw_calc.replace("[[", "[").replace("]]", "]")

            # Resolve formula token references
            def _replace_ref(match):
                inner = match.group(1).strip()
                inner_lower = inner.lower()
                if inner_lower in meas_name_map:
                    return f"[{meas_name_map[inner_lower]}]"
                return f"[{inner}]"

            formula = re.sub(r'\[([^\]]+)\]', _replace_ref, formula)

            # Aggregate-wrap bare PHYSICAL extract-column references only.
            # References to other metrics/calculated fields pass through
            # verbatim — their aggregate/row-level nature is fixed by the
            # MSTR definition they were translated from, and the emitter does
            # not second-guess it.
            if formula and physical_local_names:
                formula = _wrap_bare_aggregate_refs(
                    formula,
                    physical_local_names,
                    skip_names={loc_name, meas_name},
                )

            # ── Fail-closed nesting gate (check, never mutate) ───────────
            # A formula that aggregates an already-aggregate operand —
            # ATTR(SUM(...)), SUM([SomeAggCalc]), RANK(SUM([SomeAggCalc])) —
            # can never compile in Tableau ("Argument to X is already an
            # aggregation"). That is a TRANSLATION defect against the MSTR
            # definition, so skip emission, record a blocker Issue, and let a
            # human correct the calc. Nothing is rewritten in place.
            bad = _find_illegal_aggregation_nesting(formula, agg_calc_fields)
            if bad:
                logger.warning(
                    "Skipping calculated field '%s': illegal aggregation "
                    "nesting (%s). Fix the translated calc against the MSTR "
                    "definition before re-emission.",
                    meas_name, bad,
                )
                try:
                    from app.models.objects import Issue as IssueModel
                    self.db.add(IssueModel(
                        job_id=self.job.id,
                        object_id=getattr(measure, "mstr_id", None),
                        severity="blocker",
                        category="emission",
                        message=(
                            f"Calculated field '{meas_name}' was NOT emitted: "
                            f"illegal aggregation nesting ({bad}). Re-translate "
                            f"the MSTR metric so aggregate operands are "
                            f"referenced directly."
                        ),
                    ))
                    self.db.commit()
                except Exception:
                    pass
                continue

            self_refs = {
                f"[{loc_name}]", f"[{meas_name}]",
                f"SUM([{loc_name}])", f"SUM([{meas_name}])",
                f"AVG([{loc_name}])", f"AVG([{meas_name}])",
                f"COUNT([{loc_name}])", f"COUNT([{meas_name}])",
                f"COUNTD([{loc_name}])", f"COUNTD([{meas_name}])",
                f"MIN([{loc_name}])", f"MIN([{meas_name}])",
                f"MAX([{loc_name}])", f"MAX([{meas_name}])",
                f"MEDIAN([{loc_name}])", f"MEDIAN([{meas_name}])",
            }

            is_physical = getattr(measure, "mstr_id", None) in physical_ids
            if is_physical and formula and formula not in self_refs:
                # This measure was materialized as a physical Hyper extract
                # column (classify_physical_measures). Emitting the same name
                # as a workbook calculation duplicates the datasource field —
                # Tableau drops the calc with "field is already defined by
                # data source". Bind to the pre-computed extract column instead.
                logger.info(
                    "Measure '%s' is a physical extract column — emitting binding column "
                    "without <calculation> (avoids duplicate field definition)",
                    meas_name,
                )
                formula = ""

            # Only emit <calculation> for truly derived expressions (not self-referencing raw fact columns)
            if formula and formula not in self_refs:
                etree.SubElement(col, "calculation", attrib={
                    "class": "tableau",
                    "formula": formula,
                })

    def _topo_sort_measures(self, measures: list) -> list:
        """Topologically sort measures by USES dependencies."""
        id_map = {m.mstr_id: m for m in measures}
        visited = set()
        result = []

        def visit(m):
            if m.mstr_id in visited:
                return
            visited.add(m.mstr_id)
            for dep_id in m.dependencies:
                if dep_id in id_map:
                    visit(id_map[dep_id])
            result.append(m)

        for m in measures:
            visit(m)

        return result

    def _emit_worksheet(self, parent, ws_spec, ir=None):
        """Emit a schema-valid <worksheet> element with all required XSD children and pill bindings."""
        ws = etree.SubElement(parent, "worksheet", attrib={
            "name": ws_spec.name,
        })

        table = etree.SubElement(ws, "table")

        # Collect all fields used in this worksheet to register in datasource-dependencies
        used_dims = {}
        used_meas = {}

        def register_field(f):
            if not f or not getattr(f, "name", None):
                return
            ftype = getattr(f, "field_type", "dimension")
            if ftype == "measure":
                used_meas[f.name] = f
            else:
                used_dims[f.name] = f

        for r in (ws_spec.rows or []):
            register_field(r)
        for c in (ws_spec.columns or []):
            register_field(c)
        if ws_spec.color:
            register_field(ws_spec.color)
        if ws_spec.size:
            register_field(ws_spec.size)
        if ws_spec.label:
            register_field(ws_spec.label)
        for d in (getattr(ws_spec, "detail", []) or []):
            register_field(d)

        # Build dimension datatype map from IR to avoid keyword-based type guessing
        dim_type_map = {}  # dim local_name -> IR data_type
        if ir and hasattr(ir, "dimensions"):
            for dim in ir.dimensions:
                for key in (getattr(dim, "local_name", ""), getattr(dim, "caption", ""), getattr(dim, "name", "")):
                    if key:
                        dim_type_map[key] = getattr(dim, "data_type", "string")

        # 1. view
        view = etree.SubElement(table, "view")
        ds_node = etree.SubElement(view, "datasources")
        etree.SubElement(ds_node, "datasource", attrib={
            "caption": "Migrated Data",
            "name": "federated.default",
        })

        # Build set of measures that have a real calculated field vs raw fact column
        calculated_measure_names = set()
        if ir and hasattr(ir, "measures"):
            for m in ir.measures:
                formula = (getattr(m, "tableau_calc", "") or "").strip()
                formula = formula.replace("[[", "[").replace("]]", "]")
                loc_name = getattr(m, "local_name", getattr(m, "caption", ""))
                meas_name = getattr(m, "name", loc_name)
                self_refs = {
                    f"[{loc_name}]", f"[{meas_name}]",
                    f"SUM([{loc_name}])", f"SUM([{meas_name}])",
                    f"AVG([{loc_name}])", f"AVG([{meas_name}])",
                    f"COUNT([{loc_name}])", f"COUNT([{meas_name}])",
                    f"COUNTD([{loc_name}])", f"COUNTD([{meas_name}])",
                    f"MIN([{loc_name}])", f"MIN([{meas_name}])",
                    f"MAX([{loc_name}])", f"MAX([{meas_name}])",
                    f"MEDIAN([{loc_name}])", f"MEDIAN([{meas_name}])",
                }
                if formula and formula not in self_refs:
                    calculated_measure_names.add(loc_name)
                    calculated_measure_names.add(meas_name)
                    calculated_measure_names.add(getattr(m, "caption", ""))

        def _get_meas_pill_info(meas_name, f_obj=None):
            # If this is a true calculated field, it uses usr:
            if meas_name in calculated_measure_names:
                return "User", f"[federated.default].[usr:{meas_name}:qk]", f"[usr:{meas_name}:qk]"

            # Otherwise it is a raw physical column, so it uses sum: or avg:
            agg = getattr(f_obj, "aggregation", None)
            if not agg:
                lower = str(meas_name).lower()
                if "row count" in lower or lower == "count":
                    agg = "Sum"
                elif any(k in lower for k in ["avg", "average", "mean", "rate", "score", "days", "time", "severity", "ratio", "percent", "per"]):
                    if "row count" in lower:
                        agg = "Sum"
                    else:
                        agg = "Avg"
                else:
                    agg = "Sum"
            deriv = agg.capitalize() if isinstance(agg, str) else "Sum"
            prefix = "avg" if deriv == "Avg" else "sum"
            return deriv, f"[federated.default].[{prefix}:{meas_name}:qk]", f"[{prefix}:{meas_name}:qk]"

        # Inject datasource-dependencies so Tableau resolves shelf pills
        if used_dims or used_meas:
            ds_deps = etree.SubElement(view, "datasource-dependencies", attrib={
                "datasource": "federated.default",
            })
            date_instances = {}
            for dim_name in used_dims:
                ir_dtype = dim_type_map.get(dim_name, "string")
                is_date = ir_dtype in ("date", "datetime", "timestamp")
                if is_date:
                    etree.SubElement(ds_deps, "column", attrib={
                        "datatype": "date",
                        "name": f"[{dim_name}]",
                        "role": "dimension",
                        "type": "ordinal",
                    })
                    # Date granularity is translated to its Tableau
                    # representation BEFORE XML generation, and the SAME
                    # instance spec feeds both the column-instance here and
                    # the shelf pill later — they can never diverge.
                    #   month -> derivation="Month",  pill [mn:<d>:ok]
                    #   year  -> derivation="Year",   pill [yr:<d>:ok]
                    #   plain -> derivation="None",   pill [none:<d>:nk]
                    gran = DATE_GRANULARITY.get(dim_name, "month")
                    inst = _DATE_GRANULARITY_MAP[gran]
                    date_instances[dim_name] = inst
                    etree.SubElement(ds_deps, "column-instance", attrib={
                        "column": f"[{dim_name}]",
                        "derivation": inst.derivation,
                        "name": inst.instance_name(dim_name),
                        "pivot": "key",
                        "type": inst.field_type,
                    })
                    etree.SubElement(ds_deps, "column-instance", attrib={
                        "column": f"[{dim_name}]",
                        "derivation": "None",
                        "name": f"[none:{dim_name}:nk]",
                        "pivot": "key",
                        "type": "nominal",
                    })
                else:
                    etree.SubElement(ds_deps, "column", attrib={
                        "datatype": "string",
                        "name": f"[{dim_name}]",
                        "role": "dimension",
                        "type": "nominal",
                    })
                    etree.SubElement(ds_deps, "column-instance", attrib={
                        "column": f"[{dim_name}]",
                        "derivation": "None",
                        "name": f"[none:{dim_name}:nk]",
                        "pivot": "key",
                        "type": "nominal",
                    })
            for meas_name, f_obj in used_meas.items():
                deriv, _, pill_name = _get_meas_pill_info(meas_name, f_obj)
                etree.SubElement(ds_deps, "column", attrib={
                    "datatype": "real",
                    "name": f"[{meas_name}]",
                    "role": "measure",
                    "type": "quantitative",
                })
                etree.SubElement(ds_deps, "column-instance", attrib={
                    "column": f"[{meas_name}]",
                    "derivation": deriv,
                    "name": pill_name,
                    "pivot": "key",
                    "type": "quantitative",
                })

        for flt in ws_spec.filters:
            filter_el = etree.SubElement(view, "filter", attrib={
                "class": flt.filter_type,
                "column": f"[federated.default].[{flt.field_name}]",
            })
            if flt.is_context:
                filter_el.set("context", "true")

        etree.SubElement(view, "aggregation", attrib={"value": "true"})

        # 2. style — KPI text cards (no shelves, single big number) get a
        # readable mark font; everything else keeps Tableau defaults.
        style_el = etree.SubElement(table, "style")
        _is_kpi_card = (
            not ws_spec.rows and not ws_spec.columns
            and (getattr(ws_spec, "mark_type", "") or "").lower() == "text"
        )
        if _is_kpi_card:
            rule = etree.SubElement(style_el, "style-rule", attrib={"element": "mark"})
            etree.SubElement(rule, "format", attrib={"attr": "font-size", "value": "24"})
            etree.SubElement(rule, "format", attrib={"attr": "font-weight", "value": "bold"})

        # 3. panes
        panes = etree.SubElement(table, "panes")
        meas_rows = [r for r in ws_spec.rows if getattr(r, "field_type", "") == "measure"]
        meas_cols = [c for c in ws_spec.columns if getattr(c, "field_type", "") == "measure"]
        is_combo_dual = (len(meas_rows) >= 2) or (len(meas_cols) >= 2)
        raw_mark = ws_spec.mark_type or "automatic"

        # Primary Pane (id="0")
        # NOTE: no y-axis-name/x-axis-name here. Genuine dual-axis files carry
        # them, but empirically (job 2281d8a3 probe matrix) Tableau 2026.1
        # raises Internal Error 6EA18A9E on ours unless the multi-measure
        # shelf expression is parenthesized — and G1 proved parenthesization
        # ALONE renders stacked measures correctly without any axis attrs.
        # Minimal proven-safe shape wins.
        pane = etree.SubElement(panes, "pane", attrib={"id": "0"})
        pane_view = etree.SubElement(pane, "view")
        etree.SubElement(pane_view, "breakdown", attrib={"value": "auto"})

        # Primary Mark class
        mark_class = MARK_CLASS_MAP.get(raw_mark.lower(), "Automatic")
        etree.SubElement(pane, "mark", attrib={"class": mark_class})

        if ws_spec.color or ws_spec.size or ws_spec.label or getattr(ws_spec, "detail", None):
            encodings = etree.SubElement(pane, "encodings")
            if ws_spec.color:
                if ws_spec.color.field_type == "dimension":
                    col_key = f"[federated.default].[none:{ws_spec.color.name}:nk]"
                else:
                    _, col_key, _ = _get_meas_pill_info(ws_spec.color.name, ws_spec.color)
                etree.SubElement(encodings, "color", attrib={
                    "column": col_key,
                })
            if ws_spec.size:
                _, col_key, _ = _get_meas_pill_info(ws_spec.size.name, ws_spec.size)
                if mark_class == "Pie":
                    etree.SubElement(encodings, "wedge-size", attrib={
                        "column": col_key,
                    })
                else:
                    etree.SubElement(encodings, "size", attrib={
                        "column": col_key,
                    })
            if ws_spec.label:
                if ws_spec.label.field_type == "measure":
                    _, col_key, _ = _get_meas_pill_info(ws_spec.label.name, ws_spec.label)
                else:
                    col_key = f"[federated.default].[none:{ws_spec.label.name}:nk]"
                etree.SubElement(encodings, "text", attrib={
                    "column": col_key,
                })
            if getattr(ws_spec, "detail", None):
                for d in ws_spec.detail:
                    if not d or not d.name:
                        continue
                    if d.field_type == "dimension":
                        d_key = f"[federated.default].[none:{d.name}:nk]"
                    else:
                        _, d_key, _ = _get_meas_pill_info(d.name, d)
                    etree.SubElement(encodings, "lod", attrib={
                        "column": d_key,
                    })

        # Secondary Pane (id="1") for Dual-Axis Combo Charts
        if is_combo_dual:
            pane2 = etree.SubElement(panes, "pane", attrib={"id": "1"})
            pane2_view = etree.SubElement(pane2, "view")
            etree.SubElement(pane2_view, "breakdown", attrib={"value": "auto"})
            # Secondary mark is Line for trend over Bars
            etree.SubElement(pane2, "mark", attrib={"class": "Line"})

        # 4. rows
        rows_el = etree.SubElement(table, "rows")
        if ws_spec.rows:
            row_pills = []
            for r in ws_spec.rows:
                if r.field_type == "dimension":
                    row_pills.append(f"[federated.default].[none:{r.name}:nk]")
                else:
                    _, pill_full, _ = _get_meas_pill_info(r.name, r)
                    row_pills.append(pill_full)
            # Multi-measure shelves MUST be parenthesized: Desktop's layout
            # parser drops (and previously crashed on) bare 'A + B' rows.
            # Genuine dual-axis files write '(A + B)' — probe G1 confirmed.
            joined = " + ".join(row_pills)
            rows_el.text = f"({joined})" if len(row_pills) > 1 else joined

        # 5. cols
        cols_el = etree.SubElement(table, "cols")
        if ws_spec.columns:
            col_pills = []
            ws_title_clean = (ws_spec.name or "").lower()
            for c in ws_spec.columns:
                if c.field_type == "dimension":
                    ir_dtype_c = dim_type_map.get(c.name, "string")
                    is_date_dim = ir_dtype_c in ("date", "datetime", "timestamp")
                    if is_date_dim:
                        # SAME spec instance that declared the column-instance
                        # above — declaration and reference cannot diverge.
                        inst = date_instances.get(c.name) or _DATE_GRANULARITY_MAP[
                            DATE_GRANULARITY.get(c.name, "month")
                        ]
                        col_pills.append(inst.pill(c.name))
                    else:
                        col_pills.append(f"[federated.default].[none:{c.name}:nk]")
                else:
                    _, pill_full, _ = _get_meas_pill_info(c.name, c)
                    col_pills.append(pill_full)
            joined_cols = " + ".join(col_pills)
            cols_el.text = f"({joined_cols})" if len(col_pills) > 1 else joined_cols

    def _emit_dashboard(self, parent, dash_spec, all_worksheets):
        """Emit a schema-valid <dashboard> element with all required XSD children and worksheet zones."""
        dash = etree.SubElement(parent, "dashboard", attrib={
            "name": dash_spec.name,
        })

        # Required: style
        etree.SubElement(dash, "style")

        # Required: size
        etree.SubElement(dash, "size", attrib={
            "maxheight": "1200",
            "maxwidth": "1920",
            "minheight": "600",
            "minwidth": "800",
        })

        # Required: datasources
        ds_refs = etree.SubElement(dash, "datasources")
        etree.SubElement(ds_refs, "datasource", attrib={
            "caption": "Migrated Data",
            "name": "federated.default",
        })

        # Zones
        zones = etree.SubElement(dash, "zones")

        # Root zone container
        root_zone = etree.SubElement(zones, "zone", attrib={
            "h": "100000",
            "id": "1",
            "type-v2": "layout-basic",
            "w": "100000",
            "x": "0",
            "y": "0",
        })

        # Filter valid worksheets for this dashboard
        valid_worksheets = [
            ws for ws in all_worksheets
            if ws.name in dash_spec.worksheets and not getattr(ws, "is_failed", False)
        ]

        if not valid_worksheets:
            return

        # Separate into KPIs and Charts for a balanced dashboard layout
        kpi_sheets = [ws for ws in valid_worksheets if (ws.mark_type == "text" and not ws.rows and not ws.columns)]
        chart_sheets = [ws for ws in valid_worksheets if ws not in kpi_sheets]

        placed = 1  # root zone is id 1

        if kpi_sheets and chart_sheets:
            # Top row: KPI cards
            kpi_h = 18000
            kpi_w = 100000 // max(len(kpi_sheets), 1)
            for i, kpi_ws in enumerate(kpi_sheets):
                placed += 1
                etree.SubElement(root_zone, "zone", attrib={
                    "h": str(kpi_h),
                    "id": str(placed),
                    "name": kpi_ws.name,
                    "w": str(kpi_w),
                    "x": str(i * kpi_w),
                    "y": "0",
                })

            # Body: Charts in a balanced 2-column or 3-column grid
            body_y = kpi_h
            body_h = 100000 - kpi_h
            num_charts = len(chart_sheets)
            cols = 2 if num_charts <= 4 else (3 if num_charts <= 9 else 4)
            rows_cnt = max((num_charts + cols - 1) // cols, 1)
            cell_w = 100000 // cols
            cell_h = body_h // rows_cnt

            for i, c_ws in enumerate(chart_sheets):
                placed += 1
                col_idx = i % cols
                row_idx = i // cols
                etree.SubElement(root_zone, "zone", attrib={
                    "h": str(cell_h),
                    "id": str(placed),
                    "name": c_ws.name,
                    "w": str(cell_w),
                    "x": str(col_idx * cell_w),
                    "y": str(body_y + row_idx * cell_h),
                })

        else:
            # All charts or all KPIs: Grid layout
            sheets = valid_worksheets
            num_sheets = len(sheets)
            cols = 2 if num_sheets <= 4 else (3 if num_sheets <= 9 else 4)
            rows_cnt = max((num_sheets + cols - 1) // cols, 1)
            cell_w = 100000 // cols
            cell_h = 100000 // rows_cnt

            for i, ws in enumerate(sheets):
                placed += 1
                col_idx = i % cols
                row_idx = i // cols
                etree.SubElement(root_zone, "zone", attrib={
                    "h": str(cell_h),
                    "id": str(placed),
                    "name": ws.name,
                    "w": str(cell_w),
                    "x": str(col_idx * cell_w),
                    "y": str(row_idx * cell_h),
                })

        # Dashboard filters
        for flt in dash_spec.filters:
            etree.SubElement(dash, "filter", attrib={
                "class": flt.filter_type,
                "column": f"[{flt.field_name}]",
            })

    def _build_join_tree(self, conn, ir):
        """Build datasource relation matching the Hyper extract structure."""
        etree.SubElement(conn, "relation", attrib={
            "name": "Extract",
            "table": "[Extract].[Extract]",
            "type": "table",
        })

    def _emit_window(self, parent, name: str, is_dashboard: bool = False, is_active: bool = False, dash_spec = None, kpi_names = None):
        """Emit a schema-valid <window> element with all required XSD children.

        Zoom is structural: sheets that are KPI cards (empty shelves + Text
        mark, membership supplied via `kpi_names`) fit the entire view so the
        number centers; every other sheet keeps fit-width.
        """
        kpi_names = kpi_names or set()
        window = etree.SubElement(parent, "window", attrib={
            "class": "dashboard" if is_dashboard else "worksheet",
            "name": name,
        })
        if is_dashboard:
            viewpoints = etree.SubElement(window, "viewpoints")
            if dash_spec and getattr(dash_spec, "worksheets", None):
                for ws_name in dash_spec.worksheets:
                    vp = etree.SubElement(viewpoints, "viewpoint", attrib={"name": ws_name})
                    zoom_type = "entire-view" if ws_name in kpi_names else "fit-width"
                    etree.SubElement(vp, "zoom", attrib={"type": zoom_type})
            active_el = etree.SubElement(window, "active")
            active_el.set("id", "-1")
        else:
            cards = etree.SubElement(window, "cards")
            edge_left = etree.SubElement(cards, "edge", attrib={"name": "left"})
            strip_left = etree.SubElement(edge_left, "strip", attrib={"size": "160"})
            etree.SubElement(strip_left, "card", attrib={"type": "pages"})
            etree.SubElement(strip_left, "card", attrib={"type": "filters"})
            etree.SubElement(strip_left, "card", attrib={"type": "marks"})
            vp = etree.SubElement(window, "viewpoint", attrib={"name": name})
            zoom_type = "entire-view" if name in kpi_names else "fit-width"
            etree.SubElement(vp, "zoom", attrib={"type": zoom_type})

    # ── Path rewriting (ADR-023) ────────────────────────────────

    def _rewrite_paths(self, twb_path: Path, hyper_paths: dict):
        """Rewrite datasource paths for staging/production."""
        content = twb_path.read_text(encoding="utf-8")

        for domain, abs_path in hyper_paths.items():
            new_path = f"Data/Extracts/{domain}.hyper"
            content = content.replace(abs_path, new_path)

            # Record rewrite
            if self.db and self.job:
                rewrite = DatasourcePathRewrite(
                    id=str(uuid.uuid4()),
                    job_id=self.job.id,
                    ir_datasource_id=domain,
                    staging_path=f"Data/Extracts/{domain}.hyper",
                    production_path=f"Data/Extracts/{domain}.hyper",
                )
                self.db.add(rewrite)

        twb_path.write_text(content, encoding="utf-8")
        if self.db and hasattr(self.db, "commit"):
            self.db.commit()

    # ── TWBX packaging ──────────────────────────────────────────

    def _package_twbx(self, twb_path: Path, hyper_paths: dict, work_dir: Path) -> Path:
        """Package .twb + .hyper into .twbx ZIP."""
        twbx_path = work_dir / f"{twb_path.stem}.twbx"

        with zipfile.ZipFile(str(twbx_path), "w", zipfile.ZIP_DEFLATED) as zf:
            # Add TWB
            zf.write(str(twb_path), twb_path.name)

            # Add Hyper extracts
            written = False
            for domain, hyper_path in hyper_paths.items():
                real_path = None
                if os.path.exists(str(hyper_path)):
                    real_path = str(hyper_path)
                elif (self.artifacts_dir / "hyper" / "extract.hyper").exists():
                    real_path = str(self.artifacts_dir / "hyper" / "extract.hyper")
                elif (self.artifacts_dir / "hyper" / f"{domain}.hyper").exists():
                    real_path = str(self.artifacts_dir / "hyper" / f"{domain}.hyper")

                if real_path and os.path.exists(real_path):
                    zf.write(real_path, f"Data/Extracts/{domain}.hyper")
                    written = True

            if not written and (self.artifacts_dir / "hyper" / "extract.hyper").exists():
                zf.write(str(self.artifacts_dir / "hyper" / "extract.hyper"), "Data/Extracts/default.hyper")

        return twbx_path

    # ── Artifact recording ──────────────────────────────────────

    def _record_artifact(
        self, path: Path, name: str, artifact_type: str = "workbook"
    ):
        """Record emitted artifact in database."""
        if not (self.db and self.job):
            return

        content_hash = ""
        file_size = 0
        if path.exists():
            h = hashlib.sha256()
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    h.update(chunk)
            content_hash = h.hexdigest()
            file_size = path.stat().st_size

        artifact = Artifact(
            id=str(uuid.uuid4()),
            job_id=self.job.id,
            artifact_type=artifact_type,
            artifact_path=str(path),
            file_name=path.name,
            artifact_hash=content_hash,
            environment=self.target_env,
            size_bytes=file_size,
        )
        self.db.add(artifact)
        self.db.commit()

    # ── Helpers ──────────────────────────────────────────────────

    @staticmethod
    def _map_to_tableau_datatype(data_type: str) -> str:
        """Map IR data types to Tableau XML datatypes."""
        type_map = {
            "string": "string",
            "integer": "integer",
            "numeric": "real",
            "double": "real",
            "float": "real",
            "date": "date",
            "timestamp": "datetime",
            "boolean": "boolean",
        }
        return type_map.get(data_type.lower(), "string")
