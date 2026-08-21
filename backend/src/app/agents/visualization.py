"""
VisualizationAgent — Viz type mapping and shelf planning.

Ref: spec/agents.md §Agent 6

Maps MSTR visualization types to Tableau mark types
and generates WorksheetSpec/DashboardSpec for the emitter.
"""

import logging
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
    """Dashboard specification — maps to MSTR chapter/page."""
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
            result.worksheets.append(ws)

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

        # Map fields to shelves based on explicit visual definitions if present
        vis_rows = getattr(visual, "rows", []) or []
        vis_cols = getattr(visual, "columns", []) or []

        for field_name in vis_rows:
            rows.append(FieldRef(name=field_name))

        for field_name in vis_cols:
            columns.append(FieldRef(name=field_name))

        if hasattr(visual, "color") and visual.color:
            color = FieldRef(name=visual.color, field_type="dimension")

        if hasattr(visual, "size") and visual.size:
            size = FieldRef(name=visual.size, field_type="measure")

        # If visual has no explicit rows/columns, infer meaningful shelves from IR dimensions & measures
        if not rows and not columns and not label:
            dims = [d for d in getattr(self.ir, "dimensions", []) if not getattr(d, "hidden", False)]
            measures = getattr(self.ir, "measures", [])
            vis_title = (getattr(visual, "name", "") or "").strip()
            vis_clean = vis_title.lower()

            v_metrics = getattr(visual, "mstr_metrics", None)
            v_attrs = getattr(visual, "mstr_attributes", None)
            matched_measure = self._match_measure_for_visual(vis_clean, measures, mstr_metrics=v_metrics)
            matched_dim = self._match_dimension_for_visual(vis_clean, dims, mstr_attributes=v_attrs)

            # Date/Time dimension preference for trends/times
            date_dim = next(
                (d for d in dims if any(k in d.name.lower() for k in ["date", "time", "month", "year", "day"])),
                None,
            )
            other_dims = [d for d in dims if d != matched_dim and d != date_dim]
            secondary_dim = other_dims[0] if other_dims else None

            if raw_type in ("kpi", "metric_value", "card", "gauge"):
                # KPI Card: Single Measure value on Text label
                if matched_measure:
                    is_avg = False
                    if v_metrics and any("avg" in str(m).lower() for m in v_metrics):
                        is_avg = True
                    elif any(k in vis_clean for k in ["severity", "per claim", "per unit", "avg", "rate", "ratio", "score", "days", "time"]):
                        is_avg = True
                    if is_avg:
                        label = FieldRef(name=matched_measure.caption or matched_measure.name, field_type="measure", aggregation="avg")
                    else:
                        label = FieldRef(name=matched_measure.caption or matched_measure.name, field_type="measure", aggregation="sum")
                tableau_mark = "text"

            elif raw_type in ("grid", "crosstab", "table"):
                # Tabular Grid: Dimension on Rows, Measure on Columns & Text Label
                dim_to_use = matched_dim or (dims[0] if dims else None)
                meas_to_use = matched_measure or (measures[0] if measures else None)
                if dim_to_use:
                    rows.append(FieldRef(name=dim_to_use.caption or dim_to_use.name, field_type="dimension"))
                if meas_to_use:
                    columns.append(FieldRef(name=meas_to_use.caption or meas_to_use.name, field_type="measure"))
                    label = FieldRef(name=meas_to_use.caption or meas_to_use.name, field_type="measure")
                tableau_mark = "text"

            elif raw_type in ("combo", "combo_chart", "dual_axis"):
                # Dual-Axis Combo Chart: If trend / timeline, Date Dimension on Columns, Primary + Secondary Measure on Rows
                dim_to_use = date_dim or matched_dim or (dims[0] if dims else None)
                meas_to_use = matched_measure or (measures[0] if measures else None)
                remaining_measures = [m for m in measures if m != meas_to_use]
                second_meas = self._match_secondary_measure_for_visual(vis_clean, remaining_measures, meas_to_use)
                is_timeline = (date_dim is not None) or any(k in vis_clean for k in ["trend", "month", "year", "date", "time", "day"])
                if is_timeline:
                    if dim_to_use:
                        columns.append(FieldRef(name=dim_to_use.caption or dim_to_use.name, field_type="dimension"))
                    if meas_to_use:
                        rows.append(FieldRef(name=meas_to_use.caption or meas_to_use.name, field_type="measure"))
                    if second_meas:
                        rows.append(FieldRef(name=second_meas.caption or second_meas.name, field_type="measure"))
                else:
                    if dim_to_use:
                        rows.append(FieldRef(name=dim_to_use.caption or dim_to_use.name, field_type="dimension"))
                    if meas_to_use:
                        columns.append(FieldRef(name=meas_to_use.caption or meas_to_use.name, field_type="measure"))
                    if second_meas:
                        columns.append(FieldRef(name=second_meas.caption or second_meas.name, field_type="measure"))
                tableau_mark = "bar"

            elif tableau_mark == "bar":
                # Bar Chart: Check if vertical column breakdown vs horizontal ranking
                dim_to_use = matched_dim or (dims[0] if dims else None)
                meas_to_use = matched_measure or (measures[0] if measures else None)
                is_vertical_column = any(k in vis_clean for k in ["driver", "coverage", "distribution", "mix", "category", "line of business", "type"]) and not any(k in vis_clean for k in ["highest", "top", "rank", "ranking", "state", "adjuster", "by loss cause"])
                if is_vertical_column:
                    if dim_to_use:
                        columns.append(FieldRef(name=dim_to_use.caption or dim_to_use.name, field_type="dimension"))
                    if meas_to_use:
                        rows.append(FieldRef(name=meas_to_use.caption or meas_to_use.name, field_type="measure"))
                else:
                    if dim_to_use:
                        rows.append(FieldRef(name=dim_to_use.caption or dim_to_use.name, field_type="dimension"))
                    if meas_to_use:
                        columns.append(FieldRef(name=meas_to_use.caption or meas_to_use.name, field_type="measure"))
                if secondary_dim and any(k in vis_clean for k in ["mix", "segment", "breakdown", "by"]):
                    color = FieldRef(name=secondary_dim.caption or secondary_dim.name, field_type="dimension")

            elif tableau_mark == "pie":
                # Donut / Pie: Slice Dimension on Color, Measure on Size & Text Label
                dim_to_use = matched_dim or (dims[0] if dims else None)
                meas_to_use = matched_measure or (measures[0] if measures else None)
                if dim_to_use:
                    color = FieldRef(name=dim_to_use.caption or dim_to_use.name, field_type="dimension")
                if meas_to_use:
                    size = FieldRef(name=meas_to_use.caption or meas_to_use.name, field_type="measure")
                    label = FieldRef(name=meas_to_use.caption or meas_to_use.name, field_type="measure")

            elif tableau_mark == "line":
                # Line / Trend Chart: Date Dimension on Columns, Measure on Rows
                dim_to_use = date_dim or matched_dim or (dims[0] if dims else None)
                meas_to_use = matched_measure or (measures[0] if measures else None)
                if dim_to_use:
                    columns.append(FieldRef(name=dim_to_use.caption or dim_to_use.name, field_type="dimension"))
                if meas_to_use:
                    rows.append(FieldRef(name=meas_to_use.caption or meas_to_use.name, field_type="measure"))
                if secondary_dim and "trend" in vis_clean:
                    color = FieldRef(name=secondary_dim.caption or secondary_dim.name, field_type="dimension")

            elif tableau_mark in ("circle", "square"):
                # Scatter / Bubble / Heatmap
                dim_to_use = matched_dim or (dims[0] if dims else None)
                meas_to_use = matched_measure or (measures[0] if measures else None)
                other_meas = [m for m in measures if m != meas_to_use]
                second_meas = other_meas[0] if other_meas else None

                if second_meas:
                    columns.append(FieldRef(name=meas_to_use.caption or meas_to_use.name, field_type="measure"))
                    rows.append(FieldRef(name=second_meas.caption or second_meas.name, field_type="measure"))
                    if dim_to_use:
                        detail.append(FieldRef(name=dim_to_use.caption or dim_to_use.name, field_type="dimension"))
                        color = FieldRef(name=dim_to_use.caption or dim_to_use.name, field_type="dimension")
                else:
                    if dim_to_use:
                        rows.append(FieldRef(name=dim_to_use.caption or dim_to_use.name, field_type="dimension"))
                    if meas_to_use:
                        columns.append(FieldRef(name=meas_to_use.caption or meas_to_use.name, field_type="measure"))

            elif tableau_mark == "map":
                geo_dim = next(
                    (d for d in dims if any(k in d.name.lower() for k in ["country", "state", "city", "zip", "region", "geo"])),
                    None,
                )
                dim_to_use = geo_dim or matched_dim or (dims[0] if dims else None)
                meas_to_use = matched_measure or (measures[0] if measures else None)
                if dim_to_use:
                    detail.append(FieldRef(name=dim_to_use.caption or dim_to_use.name, field_type="dimension"))
                if meas_to_use:
                    color = FieldRef(name=meas_to_use.caption or meas_to_use.name, field_type="measure")
                tableau_mark = "automatic"

            else:
                # Default / Grid: Dimension on Rows, Measure on Label
                dim_to_use = matched_dim or (dims[0] if dims else None)
                meas_to_use = matched_measure or (measures[0] if measures else None)
                if dim_to_use:
                    rows.append(FieldRef(name=dim_to_use.caption or dim_to_use.name, field_type="dimension"))
                if meas_to_use:
                    label = FieldRef(name=meas_to_use.caption or meas_to_use.name, field_type="measure")

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
        )

    def _match_measure_for_visual(self, vis_clean: str, measures: list, mstr_metrics: Optional[list[str]] = None) -> Optional[Any]:
        """Find the measure that best matches keywords in the visual title or MSTR ground-truth metrics."""
        if not measures:
            return None

        # Priority 0: MicroStrategy ground-truth metrics from visualization instance definition
        if mstr_metrics:
            for target_m in mstr_metrics:
                if not target_m:
                    continue
                target_clean = target_m.lower().strip()
                # Direct word or substring match against measures
                for m in measures:
                    m_name = (getattr(m, "name", "") or "").lower()
                    m_cap = (getattr(m, "caption", "") or "").lower()
                    if target_clean in m_name or target_clean in m_cap or m_name in target_clean or m_cap in target_clean:
                        self._used_kpi_measures.add(getattr(m, "mstr_id", getattr(m, "name", "")))
                        return m
                # Specialized semantic keyword mapping
                for m in measures:
                    m_combined = f"{(getattr(m, 'name', '') or '').lower()} {(getattr(m, 'caption', '') or '').lower()}"
                    if ("fraud" in target_clean or "score" in target_clean) and ("fraud" in m_combined or "score" in m_combined):
                        self._used_kpi_measures.add(getattr(m, "mstr_id", getattr(m, "name", "")))
                        return m
                    if "subrogation" in target_clean and "subrogation" in m_combined:
                        self._used_kpi_measures.add(getattr(m, "mstr_id", getattr(m, "name", "")))
                        return m
                    if "salvage" in target_clean and "salvage" in m_combined:
                        self._used_kpi_measures.add(getattr(m, "mstr_id", getattr(m, "name", "")))
                        return m
                    if "recovery" in target_clean and "recovery" in m_combined:
                        self._used_kpi_measures.add(getattr(m, "mstr_id", getattr(m, "name", "")))
                        return m
                    if ("claim_cnt" in target_clean or "count" in target_clean or "volume" in target_clean) and ("count" in m_combined or "row" in m_combined):
                        self._used_kpi_measures.add(getattr(m, "mstr_id", getattr(m, "name", "")))
                        return m
                    if "resolution" in target_clean and ("resolution" in m_combined or "days" in m_combined or "time" in m_combined):
                        self._used_kpi_measures.add(getattr(m, "mstr_id", getattr(m, "name", "")))
                        return m
                    if "incurred" in target_clean and ("incurred" in m_combined or "loss" in m_combined):
                        self._used_kpi_measures.add(getattr(m, "mstr_id", getattr(m, "name", "")))
                        return m
                    if "paid" in target_clean and "paid" in m_combined:
                        self._used_kpi_measures.add(getattr(m, "mstr_id", getattr(m, "name", "")))
                        return m
                    if "reserve" in target_clean and "reserve" in m_combined:
                        self._used_kpi_measures.add(getattr(m, "mstr_id", getattr(m, "name", "")))
                        return m

                # Check if dimension contains numeric score / metric field (e.g. Fraud Score)
                if ("fraud" in target_clean or "score" in target_clean) and hasattr(self, "ir"):
                    for d in getattr(self.ir, "dimensions", []):
                        d_name = (getattr(d, "name", "") or "").lower()
                        if "fraud" in d_name or "score" in d_name:
                            from app.agents.ir_compiler import IRMeasure
                            synthetic_m = IRMeasure(
                                id=getattr(d, "id", "fraud_score"),
                                mstr_id=getattr(d, "mstr_id", ""),
                                name=getattr(d, "name", "Fraud Score"),
                                local_name=getattr(d, "local_name", "Fraud Score"),
                                remote_name=getattr(d, "remote_name", "Fraud_Score"),
                                caption=getattr(d, "caption", "Fraud Score"),
                                tableau_calc="AVG([Fraud Score])",
                                expression_text="AVG(Fraud Score)",
                                precomputed_calc=None,
                                confidence=1.0,
                                scope="local",
                                fingerprint_hash="",
                                dependencies=[],
                                null_policy="propagate",
                                zero_division_policy="null",
                            )
                            self._used_kpi_measures.add(synthetic_m.name)
                            return synthetic_m

        # Priority 1: Exact match on name or caption
        for m in measures:
            m_name = (getattr(m, "name", "") or "").lower()
            m_cap = (getattr(m, "caption", "") or "").lower()
            if (m_name and m_name == vis_clean) or (m_cap and m_cap == vis_clean):
                self._used_kpi_measures.add(getattr(m, "mstr_id", getattr(m, "name", "")))
                return m

        # Priority 2: Keyword overlap with visual title
        best_measure = None
        best_score = -1
        vis_words = set(re.findall(r"\w+", vis_clean))

        for m in measures:
            m_name = (getattr(m, "name", "") or "").lower()
            m_cap = (getattr(m, "caption", "") or "").lower()
            m_words = set(re.findall(r"\w+", f"{m_name} {m_cap}"))
            score = len(vis_words & m_words)

            # Domain keyword bonuses
            if ("loss" in vis_words or "incurred" in vis_words or "severity" in vis_words) and ("incurred" in m_words or "loss" in m_words):
                score += 3
            if "paid" in vis_words and "paid" in m_words:
                score += 4
            if "reserve" in vis_words and "reserve" in m_words:
                score += 4
            if "recovery" in vis_words and "recovery" in m_words:
                score += 4
            if "subrogation" in vis_words and "subrogation" in m_words:
                score += 4
            if "salvage" in vis_words and "salvage" in m_words:
                score += 4
            if ("fraud" in vis_words or "score" in vis_words) and ("fraud" in m_words or "score" in m_words):
                score += 5
            if ("resolution" in vis_words or "days" in vis_words or "time" in vis_words) and ("resolution" in m_words or "days" in m_words or "time" in m_words):
                score += 4
            if ("claim" in vis_words or "volume" in vis_words or "count" in vis_words or "total" in vis_words) and ("count" in m_words or "row" in m_words):
                score += 3

            if score > best_score:
                best_score = score
                best_measure = m

        if best_measure and best_score > 0:
            self._used_kpi_measures.add(getattr(best_measure, "mstr_id", getattr(best_measure, "name", "")))
            return best_measure

        # Priority 3: For generic titles ("Visualization 2 copy", etc.), pick the first unused measure
        for m in measures:
            m_key = getattr(m, "mstr_id", getattr(m, "name", ""))
            if m_key not in self._used_kpi_measures:
                self._used_kpi_measures.add(m_key)
                return m

        return measures[0]

    @staticmethod
    def _match_dimension_for_visual(vis_clean: str, dims: list, mstr_attributes: Optional[list[str]] = None) -> Optional[Any]:
        """Find the dimension that best matches keywords in the visual title or MSTR ground-truth attributes."""
        if not dims:
            return None

        # Priority 0: Ground-truth attributes from MSTR
        if mstr_attributes:
            for target_a in mstr_attributes:
                if not target_a:
                    continue
                target_clean = target_a.lower().strip()
                for d in dims:
                    d_name = (getattr(d, "name", "") or "").lower()
                    d_cap = (getattr(d, "caption", "") or "").lower()
                    if target_clean in d_name or target_clean in d_cap or d_name in target_clean or d_cap in target_clean:
                        return d

        vis_words = set(re.findall(r"\w+", vis_clean))
        best_dim = None
        best_score = -1

        for d in dims:
            d_name = (getattr(d, "name", "") or "").lower()
            d_cap = (getattr(d, "caption", "") or "").lower()
            d_words = set(re.findall(r"\w+", f"{d_name} {d_cap}"))
            score = len(vis_words & d_words)

            # Keyword bonuses
            if ("cause" in vis_words or "causes" in vis_words) and "cause" in d_words:
                score += 4
            if "status" in vis_words and "status" in d_words:
                score += 4
            if ("state" in vis_words or "states" in vis_words or "geography" in vis_words) and "state" in d_words:
                score += 4
            if "region" in vis_words and ("region" in d_words or "state" in d_words):
                score += 3
            if "coverage" in vis_words and "coverage" in d_words:
                score += 4
            if ("business" in vis_words or "lob" in vis_words or "policy" in vis_words) and "policy" in d_words:
                score += 4
            if ("date" in vis_words or "month" in vis_words or "trend" in vis_words or "year" in vis_words) and ("date" in d_words or "time" in d_words):
                score += 4
            if ("adjuster" in vis_words or "adjusters" in vis_words or "workload" in vis_words) and "adjuster" in d_words:
                score += 4

            if score > best_score:
                best_score = score
                best_dim = d

        return best_dim if best_dim else (dims[0] if dims else None)

    @staticmethod
    def _match_secondary_measure_for_visual(vis_clean: str, remaining_measures: list, primary_measure: Any) -> Optional[Any]:
        """Find the secondary measure that best complements the primary measure for combo charts."""
        if not remaining_measures:
            return None

        # Priority 1: Check keywords in title specifically for second measure concepts
        vis_words = set(re.findall(r"\w+", vis_clean))
        for m in remaining_measures:
            m_name = (getattr(m, "name", "") or "").lower()
            m_cap = (getattr(m, "caption", "") or "").lower()
            m_words = set(re.findall(r"\w+", f"{m_name} {m_cap}"))

            if ("resolution" in vis_words or "days" in vis_words) and ("resolution" in m_words or "days" in m_words):
                return m
            if ("incurred" in vis_words or "loss" in vis_words or "amount" in vis_words) and ("incurred" in m_words or "paid" in m_words):
                return m
            if ("claims" in vis_words or "volume" in vis_words or "count" in vis_words) and ("count" in m_words or "row" in m_words):
                return m
            if ("fraud" in vis_words or "score" in vis_words) and "fraud" in m_words:
                return m

        # Priority 2: If primary is volume/count, choose monetary measure (Incurred / Paid)
        p_name = (getattr(primary_measure, "name", "") or "").lower() if primary_measure else ""
        if "count" in p_name or "row" in p_name:
            incurred = next((m for m in remaining_measures if "incurred" in (getattr(m, "name", "") or "").lower()), None)
            if incurred:
                return incurred

        # Priority 3: First available remaining measure
        return remaining_measures[0]
