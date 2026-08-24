"""
VisualizationAgent â€” Viz type mapping and shelf planning.

Ref: spec/agents.md Â§Agent 6

Maps MSTR visualization types to Tableau mark types
and generates WorksheetSpec/DashboardSpec for the emitter.
"""

import json
import logging
import os
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


# MSTR viz type -> Tableau mark type mapping
VIZ_TYPE_MAP = {
    "grid": "text",
    "crosstab": "text",
    "vertical_bar": "bar",
    "horizontal_bar": "bar",
    "bar": "bar",
    "bar_chart": "bar",
    "stacked_bar": "bar",
    "column": "bar",
    "line": "line",
    "line_chart": "line",
    "area": "area",
    "area_chart": "area",
    "pie": "pie",
    "pie_chart": "pie",
    "donut": "pie",
    "donut_chart": "pie",
    "kpi": "text",
    "metric_value": "text",
    "card": "text",
    "scatter": "circle",
    "scatter_chart": "circle",
    "bubble": "circle",
    "bubble_chart": "circle",
    "map": "map",
    "geo": "map",
    "heat_map": "square",
    "heatmap": "square",
    "treemap": "square",
    "waterfall": "ganttBar",
    "combo": "bar",
    "combo_chart": "bar",
    "histogram": "bar",
    "box_plot": "circle",
    "funnel": "bar",
    "gauge": "text",
    "microcharts": "line",
    "network": "circle",
    "unknown": "text",
}


@dataclass
class FieldRef:
    """Reference to a field on a shelf."""
    name: str
    field_type: str = "dimension"  # "dimension" | "measure"
    aggregation: Optional[str] = None
    sort: Optional[str] = None


@dataclass
class FilterSpec:
    """Filter specification for a worksheet."""
    field_name: str
    filter_type: str = "categorical"  # "categorical" | "range" | "relative_date"
    values: list[str] = field(default_factory=list)
    is_context: bool = False


@dataclass
class WorksheetSpec:
    """Worksheet specification for Tableau emitter."""
    id: str
    name: str
    datasource_ref: str
    mark_type: str
    rows: list[FieldRef] = field(default_factory=list)
    columns: list[FieldRef] = field(default_factory=list)
    color: Optional[FieldRef] = None
    size: Optional[FieldRef] = None
    label: Optional[FieldRef] = None
    detail: list[FieldRef] = field(default_factory=list)
    filters: list[FilterSpec] = field(default_factory=list)
    tooltip_fields: list[FieldRef] = field(default_factory=list)
    is_failed: bool = False


@dataclass
class DashboardSpec:
    """Dashboard specification â€” maps to MSTR chapter/page."""
    id: str
    name: str
    worksheets: list[str] = field(default_factory=list)  # worksheet names
    layout: str = "auto-tiled"  # ADR-008
    filters: list[FilterSpec] = field(default_factory=list)


@dataclass
class VizPlan:
    """Complete visualization plan for the emitter."""
    worksheets: list[WorksheetSpec] = field(default_factory=list)
    dashboards: list[DashboardSpec] = field(default_factory=list)


class VisualizationAgent:
    """
    Agent 6: Maps MSTR dossier visuals to Tableau worksheet/dashboard specs.

    Uses dynamic viz type mapping with intelligent shelf assignment heuristics.
    """

    def __init__(self, ir):
        self.ir = ir
        self._used_kpi_measures = set()
        # Build canonical field name index for resolution
        self._field_index = self._build_field_index(ir)
        # Canonical names by object kind â€” override refs must be typed exactly
        self._measure_names = set()
        for m in getattr(ir, "measures", []):
            for k in (getattr(m, "local_name", ""), getattr(m, "caption", ""), getattr(m, "name", "")):
                if k:
                    self._measure_names.add(k.lower().strip())
        self._dimension_names = set()
        for d in getattr(ir, "dimensions", []):
            for k in (getattr(d, "local_name", ""), getattr(d, "caption", ""), getattr(d, "name", "")):
                if k:
                    self._dimension_names.add(k.lower().strip())
        # Human-supplied bindings (review-approved artifact), applied ONLY to
        # visuals that carry no MicroStrategy evidence of their own.
        self._binding_overrides = self._load_binding_overrides()

    OVERRIDE_PATH = os.path.join(
        os.path.dirname(__file__), "..", "..", "..",
        "artifacts", "visual_binding_overrides.json",
    )
    _ALLOWED_OVERRIDE_MARKS = {
        "text", "bar", "pie", "line", "circle", "square", "automatic", "map",
    }

    @classmethod
    def _load_binding_overrides(cls) -> dict:
        """Load the human-curated binding artifact. Absent file = no overrides;
        malformed file = loud warning + no overrides (never partial trust)."""
        try:
            with open(cls.OVERRIDE_PATH, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except FileNotFoundError:
            return {}
        except Exception as e:
            logger.warning("Could not read visual binding overrides: %s", e)
            return {}
        return {
            str(k).strip().lower(): v
            for k, v in raw.items()
            if not str(k).startswith("_") and isinstance(v, dict)
        }

    def _apply_human_override(self, ws: WorksheetSpec) -> bool:
        """Apply a review-board-approved binding to an evidence-less visual.
        Every field must resolve EXACTLY against the IR inventory; one unknown
        field rejects the whole override (the visual stays honestly failed)."""
        spec = self._binding_overrides.get(ws.name.strip().lower())
        if not spec:
            return False

        def resolve_ref(name: str):
            resolved = self._resolve_field_name(str(name))
            key = resolved.lower().strip()
            if key in self._measure_names:
                return FieldRef(name=resolved, field_type="measure")
            if key in self._dimension_names:
                return FieldRef(name=resolved, field_type="dimension")
            logger.warning(
                "Override for '%s': field '%s' has no exact IR match â€” override REJECTED",
                ws.name, name,
            )
            return None

        def shelf(key: str):
            vals = spec.get(key) or []
            if isinstance(vals, str):
                vals = [vals]
            out = []
            for v in vals:
                ref = resolve_ref(v)
                if ref is None:
                    return None
                out.append(ref)
            return out

        rows = shelf("rows")
        columns = shelf("columns")
        if rows is None or columns is None:
            return False
        color = shelf("color")
        size = shelf("size")
        label = shelf("label")
        detail = shelf("detail")
        mark = str(spec.get("mark", "")).strip().lower()
        if mark and mark not in self._ALLOWED_OVERRIDE_MARKS:
            logger.warning(
                "Override for '%s': unsupported mark '%s' â€” rejected", ws.name, mark,
            )
            return False

        ws.rows = rows
        ws.columns = columns
        if color:
            ws.color = color[0]
        if size:
            ws.size = size[0]
        if label:
            ws.label = label[0]
        if detail:
            ws.detail = detail
        if mark:
            ws.mark_type = mark
        ws.is_failed = False
        logger.info(
            "Human-supplied binding applied to visual '%s' (mark=%s)",
            ws.name, mark or ws.mark_type,
        )
        return True

    def plan(self) -> VizPlan:
        """Generate VizPlan from IR visuals."""
        result = VizPlan()
        self._used_kpi_measures.clear()
        # Clean and deduplicate worksheet names
        seen_names: dict[str, int] = {}
        for visual in self.ir.visuals:
            raw_name = (getattr(visual, "name", "") or "Sheet").strip()
            
            # If visual has a generic internal container name (e.g. "Visualization 2 copy copy", "Visualization 3", "Viz_W70"),
            # resolve it to the bound ground-truth metric or attribute name!
            raw_name_lower = raw_name.lower().strip()
            if "visualization" in raw_name_lower or raw_name_lower.startswith("viz"):
                if getattr(visual, "mstr_metrics", None) and visual.mstr_metrics[0]:
                    raw_name = visual.mstr_metrics[0].strip()
                elif getattr(visual, "mstr_attributes", None) and visual.mstr_attributes[0]:
                    raw_name = visual.mstr_attributes[0].strip()

            clean_name = raw_name
            if clean_name in seen_names:
                seen_names[clean_name] += 1
                unique_name = f"{clean_name} ({seen_names[clean_name]})"
            else:
                seen_names[clean_name] = 1
                unique_name = clean_name
            visual.name = unique_name
            ws = self._plan_worksheet(visual)
            ws.name = unique_name
            # Resolve all field names against IR inventory to prevent phantom refs
            self._resolve_all_field_refs(ws)
            result.worksheets.append(ws)

        # Human-supplied bindings (review-approved artifact): rescue visuals
        # that carry NO MicroStrategy evidence instead of leaving them omitted.
        # Applied only where no evidence-based binding exists; every field is
        # exact-validated, and an unresolvable override keeps the sheet failed.
        if self._binding_overrides:
            for ws in result.worksheets:
                if ws.is_failed:
                    self._apply_human_override(ws)

        # If no visuals, create default worksheets from measures
        if not result.worksheets and self.ir.measures:
            for measure in self.ir.measures[:20]:  # Cap at 20
                ws = WorksheetSpec(
                    id=str(uuid.uuid4()),
                    name=measure.name,
                    datasource_ref="default",
                    mark_type="text",
                    rows=[FieldRef(name=measure.caption or measure.name, field_type="measure")],
                )
                result.worksheets.append(ws)

        # Create dashboards matching MSTR chapters/pages
        if result.worksheets:
            pages_to_sheets: dict[str, list[str]] = {}
            for visual, ws in zip(self.ir.visuals, result.worksheets):
                if ws.is_failed:
                    continue
                p_name = getattr(visual, "page_name", None) or getattr(visual, "chapter_name", None)
                if p_name:
                    pages_to_sheets.setdefault(p_name.strip(), []).append(ws.name)

            if pages_to_sheets:
                for page_name, sheet_names in pages_to_sheets.items():
                    result.dashboards.append(DashboardSpec(
                        id=str(uuid.uuid4()),
                        name=page_name,
                        worksheets=sheet_names,
                        layout="auto-tiled",
                    ))
            else:
                ws_names = [ws.name for ws in result.worksheets if not ws.is_failed]
                result.dashboards.append(DashboardSpec(
                    id=str(uuid.uuid4()),
                    name="Overview",
                    worksheets=ws_names,
                    layout="auto-tiled",
                ))

        logger.info(
            "VizPlan: %d worksheets, %d dashboards",
            len(result.worksheets), len(result.dashboards),
        )
        return result

    # â”€â”€ Field name resolution â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    @staticmethod
    def _build_field_index(ir) -> dict[str, str]:
        """
        Build a canonical index mapping lowercased/normalized field names
        and MSTR IDs to the actual IR local_name. This covers name, local_name,
        caption, and mstr_id for both dimensions and measures.
        """
        index: dict[str, str] = {}  # normalized_key -> canonical local_name
        for dim in getattr(ir, "dimensions", []):
            canonical = getattr(dim, "local_name", "") or getattr(dim, "name", "")
            if not canonical:
                continue
            for variant in (getattr(dim, "name", ""), getattr(dim, "local_name", ""), getattr(dim, "caption", ""), getattr(dim, "mstr_id", "")):
                if variant:
                    index[str(variant).lower().strip()] = canonical
        for meas in getattr(ir, "measures", []):
            canonical = getattr(meas, "local_name", "") or getattr(meas, "name", "")
            if not canonical:
                continue
            for variant in (getattr(meas, "name", ""), getattr(meas, "local_name", ""), getattr(meas, "caption", ""), getattr(meas, "mstr_id", "")):
                if variant:
                    index[str(variant).lower().strip()] = canonical
        return index

    def _resolve_field_name(self, name: str) -> str:
        """
        Resolve a field name against the IR inventory.

        EXACT matches only: canonical name / local_name / caption / MSTR GUID.
        No fuzzy token overlap, no substring containment â€” those silently
        rebound charts to wrong fields (e.g. 'Incurred Loss' â†’ 'State Loss
        Rank' via shared token 'loss'). An unresolvable name is kept as-is
        and surfaces as an honest resolution warning instead of a wrong chart.
        """
        if not name:
            return name

        key = name.lower().strip()
        if key in self._field_index:
            resolved = self._field_index[key]
            if resolved != name:
                logger.info("Field resolution: '%s' -> '%s' (exact)", name, resolved)
            return resolved

        logger.warning(
            "Field resolution: '%s' has NO exact IR match â€” keeping as-is "
            "(fuzzy matching disabled: it produced wrong-chart regressions)", name,
        )

        return name

    def _resolve_all_field_refs(self, ws: WorksheetSpec):
        """
        Resolve all FieldRef names against the IR inventory. A reference that
        has NO exact match is a phantom (e.g. MSTR display artifacts like
        'Column Set 1'): it is DROPPED, never emitted — an unknown pill is a
        guaranteed red-'!' blank zone in Tableau. A worksheet left with no
        measure anywhere is marked failed for human/override rescue.
        """
        known = set(self._field_index.values())

        def keep(refs):
            out = []
            for ref in (refs or []):
                resolved = self._resolve_field_name(ref.name)
                if resolved in known:
                    ref.name = resolved
                    out.append(ref)
                else:
                    logger.warning(
                        "Worksheet '%s': dropping phantom field ref '%s'", ws.name, ref.name,
                    )
            return out

        ws.rows = keep(ws.rows)
        ws.columns = keep(ws.columns)
        ws.detail = keep(ws.detail)
        if ws.color is not None:
            kept_color = keep([ws.color])
            ws.color = kept_color[0] if kept_color else None
        if ws.size is not None:
            kept_size = keep([ws.size])
            ws.size = kept_size[0] if kept_size else None
        if ws.label is not None:
            kept_label = keep([ws.label])
            ws.label = kept_label[0] if kept_label else None

        has_measure = any(
            getattr(r, "field_type", "") == "measure"
            for r in list(ws.rows) + list(ws.columns) + [ws.size, ws.label, ws.color]
            if r is not None
        )
        if not has_measure or not (ws.rows or ws.columns or ws.label or ws.size or ws.color):
            logger.warning(
                "Worksheet '%s': no resolvable measure binding — marking failed "
                "instead of emitting a meaningless chart", ws.name,
            )
            ws.is_failed = True

    def _plan_worksheet(self, visual) -> WorksheetSpec:
        """Plan a single worksheet from an IR visual."""
        raw_type = (getattr(visual, "mark_type", "unknown") or "unknown").lower().replace("-", "_").replace(" ", "_")
        tableau_mark = VIZ_TYPE_MAP.get(raw_type, "text")

        # Shelf assignments
        rows: list[FieldRef] = []
        columns: list[FieldRef] = []
        color: Optional[FieldRef] = None
        size: Optional[FieldRef] = None
        label: Optional[FieldRef] = None
        detail: list[FieldRef] = []

        # Determine whether a field is a dimension or measure
        ir_meas_names = set()
        for m in getattr(self.ir, "measures", []):
            ir_meas_names.add((getattr(m, "local_name", "") or "").lower())
            ir_meas_names.add((getattr(m, "caption", "") or "").lower())
            ir_meas_names.add((getattr(m, "name", "") or "").lower())
        ir_meas_names.discard("")

        ir_dim_names = set()
        for d in getattr(self.ir, "dimensions", []):
            ir_dim_names.add((getattr(d, "local_name", "") or "").lower())
            ir_dim_names.add((getattr(d, "caption", "") or "").lower())
            ir_dim_names.add((getattr(d, "name", "") or "").lower())
        ir_dim_names.discard("")

        def is_measure_field(fname: str) -> bool:
            fl = str(fname).lower().strip()
            if fl in ir_dim_names:
                return False
            if fl in ir_meas_names:
                return True
            # Fallback only for non-IR fields
            return any(k in fl for k in ["count", "avg", "average", "sum", "usd", "amount", "rate", "ratio", "severity"])

        # Map fields to shelves based on explicit visual definitions if present
        vis_rows = getattr(visual, "rows", []) or []
        vis_cols = getattr(visual, "columns", []) or []

        for field_name in vis_rows:
            ftype = "measure" if is_measure_field(field_name) else "dimension"
            rows.append(FieldRef(name=field_name, field_type=ftype))

        for field_name in vis_cols:
            ftype = "measure" if is_measure_field(field_name) else "dimension"
            columns.append(FieldRef(name=field_name, field_type=ftype))

        if hasattr(visual, "color") and visual.color:
            ftype = "measure" if is_measure_field(visual.color) else "dimension"
            color = FieldRef(name=visual.color, field_type=ftype)

        if hasattr(visual, "size") and visual.size:
            size = FieldRef(name=visual.size, field_type="measure")

        # Scatter/bubble grain: a dimension on Color alone does NOT set the
        # mark level of detail in Tableau — every instance collapses into a
        # couple of aggregate dots. Mirror the bound attribute onto Detail.
        if tableau_mark == "circle" and color is not None and not detail:
            detail.append(FieldRef(name=color.name, field_type=color.field_type))

        # â”€â”€ Inference ONLY when the dossier selector carried no shelves â”€â”€â”€â”€
        # Strictly evidence-driven, no title keywords:
        #   P0  explicit selector shelves (consumed above)
        #   P1  MSTR object bindings resolved by EXACT GUID or EXACT
        #       canonical name â€” never substring/fuzzy/title matching
        #   P2  deterministic per-TYPE default laid out from the visual's OWN
        #       binding lists (mstr_metrics / mstr_attributes order), mirroring
        #       the orchestrator harvest fallback so both layers agree
        # Unresolvable â‡’ worksheet marked FAILED (honest skip) â€” a missing
        # chart is auditable; a wrongly-bound chart silently lies.
        ws_failed = False
        if not rows and not columns and not label and not color:
            v_metrics = [m for m in (getattr(visual, "mstr_metrics", None) or []) if m]
            v_attrs = [a for a in (getattr(visual, "mstr_attributes", None) or []) if a]
            v_metric_ids = [i for i in (getattr(visual, "metric_ids", None) or []) if i]
            v_attr_ids = [i for i in (getattr(visual, "attribute_ids", None) or []) if i]

            meas_by_id = {
                getattr(m, "mstr_id", ""): m for m in getattr(self.ir, "measures", [])
            }
            meas_by_name = {}
            for m in getattr(self.ir, "measures", []):
                for k in (getattr(m, "local_name", ""), getattr(m, "caption", ""), getattr(m, "name", "")):
                    if k:
                        meas_by_name[k.lower().strip()] = m
            dim_by_id = {
                getattr(d, "mstr_id", ""): d for d in getattr(self.ir, "dimensions", [])
            }
            dim_by_name = {}
            for d in getattr(self.ir, "dimensions", []):
                for k in (getattr(d, "local_name", ""), getattr(d, "caption", ""), getattr(d, "name", "")):
                    if k:
                        dim_by_name[k.lower().strip()] = d

            def resolve_meas(names, ids):
                for i in ids:
                    if i in meas_by_id:
                        return meas_by_id[i]
                for n in names:
                    hit = meas_by_name.get(str(n).lower().strip())
                    if hit is not None:
                        return hit
                return None

            def resolve_dim(names, ids):
                for i in ids:
                    if i in dim_by_id:
                        return dim_by_id[i]
                for n in names:
                    hit = dim_by_name.get(str(n).lower().strip())
                    if hit is not None:
                        return hit
                return None

            primary_meas = resolve_meas(v_metrics[:1], v_metric_ids[:1])
            secondary_meas = resolve_meas(v_metrics[1:], v_metric_ids[1:])
            primary_dim = resolve_dim(v_attrs[:1], v_attr_ids[:1])
            other_dims = [
                d for d in getattr(self.ir, "dimensions", [])
                if not getattr(d, "hidden", False) and d is not primary_dim
            ]
            date_like = next(
                (d for d in other_dims
                 if any(k in (d.name or "").lower() for k in ("date", "month", "year", "time"))),
                None,
            )

            def fr_m(m, agg=None):
                return FieldRef(name=m.caption or m.name, field_type="measure", aggregation=agg) if m else None

            def fr_d(d):
                return FieldRef(name=d.caption or d.name, field_type="dimension") if d else None

            if raw_type in ("kpi", "metric_value", "card", "gauge"):
                tableau_mark = "text"
                if primary_meas:
                    label = fr_m(primary_meas)

            elif raw_type in ("grid", "crosstab", "table"):
                tableau_mark = "text"
                if primary_dim:
                    rows.append(fr_d(primary_dim))
                if primary_meas:
                    columns.append(fr_m(primary_meas))
                    label = fr_m(primary_meas)

            elif raw_type in ("combo", "combo_chart", "dual_axis"):
                # MSTR combo = N measures sharing ONE categorical axis
                axis_dim = date_like or primary_dim
                if axis_dim:
                    columns.append(fr_d(axis_dim))
                if primary_meas:
                    rows.append(fr_m(primary_meas))
                if secondary_meas:
                    rows.append(fr_m(secondary_meas))
                tableau_mark = "bar"

            elif raw_type in ("pie", "donut", "donut_chart", "pie_chart"):
                # Slices = attribute on Color, Angle = metric on Size/Label.
                # NO axis pills â€” a metric on Columns renders detached bubbles.
                if primary_dim:
                    color = fr_d(primary_dim)
                if primary_meas:
                    size = fr_m(primary_meas)
                    label = fr_m(primary_meas)
                tableau_mark = "pie"

            elif raw_type in ("line", "line_chart", "area", "area_chart"):
                axis_dim = date_like or primary_dim
                if axis_dim:
                    columns.append(fr_d(axis_dim))
                if primary_meas:
                    rows.append(fr_m(primary_meas))
                tableau_mark = VIZ_TYPE_MAP.get(raw_type, "line")

            elif raw_type in ("scatter", "scatter_chart", "bubble", "bubble_chart"):
                if primary_meas:
                    columns.append(fr_m(primary_meas))
                if secondary_meas:
                    rows.append(fr_m(secondary_meas))
                # Grain: every bound instance must be its own mark
                if primary_dim:
                    detail.append(fr_d(primary_dim))
                    color = fr_d(primary_dim)
                if size is None and len(v_metrics) > 2:
                    third = resolve_meas(v_metrics[2:], v_metric_ids[2:])
                    if third:
                        size = fr_m(third)
                if not rows and not columns:
                    if primary_dim:
                        rows.append(fr_d(primary_dim))
                    elif primary_meas:
                        columns.append(fr_m(primary_meas))
                tableau_mark = VIZ_TYPE_MAP.get(raw_type, "circle")

            elif raw_type in ("map", "geo", "heat_map", "heatmap"):
                geo = next(
                    (d for d in other_dims
                     if any(k in (d.name or "").lower()
                            for k in ("country", "state", "city", "zip", "region", "lat", "lon"))),
                    primary_dim,
                )
                if geo:
                    detail.append(fr_d(geo))
                    rows.append(fr_d(geo))
                if primary_meas:
                    color = fr_m(primary_meas)
                tableau_mark = "automatic" if raw_type in ("map", "geo") else "square"

            else:  # bar family + unknown default
                if primary_dim:
                    rows.append(fr_d(primary_dim))
                if primary_meas:
                    columns.append(fr_m(primary_meas))
                tableau_mark = VIZ_TYPE_MAP.get(raw_type, "bar")

            if not rows and not columns and not label and not size and not color:
                logger.warning(
                    "Visual '%s' (%s): no MSTR binding resolved exactly â€” "
                    "marking worksheet failed instead of guessing",
                    visual.name, raw_type,
                )
                ws_failed = True

        # For KPI cards, ensure the measure is bound to the text label shelf
        if raw_type in ("kpi", "card", "metric_value", "gauge"):
            tableau_mark = "text"
            if not label:
                if columns and getattr(columns[0], "field_type", "") == "measure":
                    label = columns.pop(0)
                elif rows and getattr(rows[0], "field_type", "") == "measure":
                    label = rows.pop(0)

        # Filters
        filters = []
        for f in getattr(visual, "filters", []):
            filters.append(FilterSpec(field_name=f))

        return WorksheetSpec(
            id=str(uuid.uuid4()),
            name=visual.name or "Sheet",
            datasource_ref="default",
            mark_type=tableau_mark,
            rows=rows,
            columns=columns,
            color=color,
            size=size,
            label=label,
            detail=detail,
            filters=filters,
            is_failed=ws_failed,
        )

