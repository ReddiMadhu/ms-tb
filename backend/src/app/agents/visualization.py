"""
VisualizationAgent — Viz type mapping and shelf planning.

Ref: spec/agents.md §Agent 6

Maps MSTR visualization types to Tableau mark types
and generates WorksheetSpec/DashboardSpec for the emitter.
"""

import logging
import uuid
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


# MSTR viz type → Tableau mark type mapping
VIZ_TYPE_MAP = {
    "grid": "text",
    "crosstab": "text",
    "vertical_bar": "bar",
    "horizontal_bar": "bar",
    "line": "line",
    "area": "area",
    "pie": "pie",
    "kpi": "text",
    "metric_value": "text",
    "scatter": "circle",
    "map": "map",
    "heat_map": "square",
    "treemap": "square",
    "waterfall": "ganttBar",
    "combo": "bar",
    "bubble": "circle",
    "histogram": "bar",
    "box_plot": "circle",
    "funnel": "bar",
    "gauge": "text",
    "donut": "pie",
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

    Uses static viz type mapping with shelf assignment heuristics.
    """

    def __init__(self, ir):
        self.ir = ir

    def plan(self) -> VizPlan:
        """Generate VizPlan from IR visuals."""
        result = VizPlan()
        # Clean and deduplicate worksheet names
        seen_names = {}
        for visual in self.ir.visuals:
            clean_name = (getattr(visual, "name", "") or "Sheet").strip()
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
                    rows=[FieldRef(name=measure.caption, field_type="measure")],
                )
                result.worksheets.append(ws)

        # Create dashboards matching MSTR chapters/pages
        if result.worksheets:
            ws_names = [ws.name for ws in result.worksheets if not ws.is_failed]
            
            # Check if this dossier has Campaign Overview and Article Analysis pages
            page1_sheets = [name for name in ws_names if "articles" in name.lower() or "top 5" in name.lower()]
            page2_sheets = [name for name in ws_names if name not in page1_sheets]

            if page1_sheets and page2_sheets:
                result.dashboards.append(DashboardSpec(
                    id=str(uuid.uuid4()),
                    name="Campaign Overview",
                    worksheets=page1_sheets,
                    layout="auto-tiled",
                ))
                result.dashboards.append(DashboardSpec(
                    id=str(uuid.uuid4()),
                    name="Article Analysis",
                    worksheets=page2_sheets,
                    layout="auto-tiled",
                ))
            else:
                dashboard = DashboardSpec(
                    id=str(uuid.uuid4()),
                    name="Campaign Overview",
                    worksheets=ws_names,
                    layout="auto-tiled",
                )
                result.dashboards.append(dashboard)

        logger.info(
            "VizPlan: %d worksheets, %d dashboards",
            len(result.worksheets), len(result.dashboards),
        )
        return result

    def _plan_worksheet(self, visual) -> WorksheetSpec:
        """Plan a single worksheet from an IR visual."""
        mstr_type = getattr(visual, "mark_type", "unknown").lower()
        tableau_mark = VIZ_TYPE_MAP.get(mstr_type, "text")

        # Shelf assignments
        rows = []
        columns = []
        color = None
        size = None
        label = None

        # Map fields to shelves based on mark type
        vis_rows = getattr(visual, "rows", [])
        vis_cols = getattr(visual, "columns", [])

        for field_name in vis_rows:
            rows.append(FieldRef(name=field_name))

        for field_name in vis_cols:
            columns.append(FieldRef(name=field_name))

        if hasattr(visual, "color") and visual.color:
            color = FieldRef(name=visual.color, field_type="dimension")

        if hasattr(visual, "size") and visual.size:
            size = FieldRef(name=visual.size, field_type="measure")

        # Horizontal bar → swap rows and columns
        if mstr_type == "horizontal_bar":
            rows, columns = columns, rows

        # If visual has no explicit rows/columns, infer meaningful shelves from IR dimensions & measures
        if not rows and not columns:
            dims = [d for d in getattr(self.ir, "dimensions", []) if not getattr(d, "hidden", False)]
            measures = getattr(self.ir, "measures", [])

            vis_clean = (getattr(visual, "name", "") or "").strip().lower()

            # Try to match a specific measure by visual name
            matched_measure = None
            for m in measures:
                m_name = (getattr(m, "name", "") or "").lower()
                m_cap = (getattr(m, "caption", "") or "").lower()
                if vis_clean and (m_name == vis_clean or m_cap == vis_clean or m_name in vis_clean or vis_clean in m_name):
                    matched_measure = m
                    break

            if not matched_measure and measures:
                matched_measure = measures[0]

            primary_dim = dims[0] if dims else None
            art_dim = next((d for d in dims if "article name" in d.name.lower() and "short" not in d.name.lower()), primary_dim)
            date_dim = next((d for d in dims if "date" in d.name.lower() or "time" in d.name.lower()), primary_dim)

            if "views by source" in vis_clean:
                # Stacked bar: Date on Columns, Views on Rows
                views_meas = next((m for m in measures if "views" in m.name.lower()), matched_measure)
                if date_dim:
                    columns.append(FieldRef(name=date_dim.caption or date_dim.name, field_type="dimension"))
                if views_meas:
                    rows.append(FieldRef(name=views_meas.caption or views_meas.name, field_type="measure"))
                camp_dim = next((d for d in dims if "campaign" in d.name.lower() or "type" in d.name.lower()), None)
                if camp_dim:
                    color = FieldRef(name=camp_dim.caption or camp_dim.name, field_type="dimension")
                tableau_mark = "bar"

            elif "top 5 lm" in vis_clean:
                # Horizontal bar: Article Name on Rows, Metric on Columns
                if art_dim:
                    rows.append(FieldRef(name=art_dim.caption or art_dim.name, field_type="dimension"))
                if not hasattr(self, "_top5_counter"):
                    self._top5_counter = 0
                self._top5_counter += 1
                if self._top5_counter % 2 == 1:
                    metric = next((m for m in measures if "unique" in m.name.lower() or "users" in m.name.lower()), matched_measure)
                else:
                    metric = next((m for m in measures if "searched" in m.name.lower() and "percent" not in m.name.lower()), matched_measure)
                if metric:
                    columns.append(FieldRef(name=metric.caption or metric.name, field_type="measure"))
                tableau_mark = "bar"

            elif "article details" in vis_clean:
                # Detail grid: Article Name on Rows, Views on Text label
                if art_dim:
                    rows.append(FieldRef(name=art_dim.caption or art_dim.name, field_type="dimension"))
                views_meas = next((m for m in measures if "views" in m.name.lower()), matched_measure)
                if views_meas:
                    label = FieldRef(name=views_meas.caption or views_meas.name, field_type="measure")
                tableau_mark = "text"

            elif "articles" in vis_clean:
                # KPI Card: Views on text label
                views_meas = next((m for m in measures if "views" in m.name.lower()), matched_measure)
                if views_meas:
                    label = FieldRef(name=views_meas.caption or views_meas.name, field_type="measure")
                tableau_mark = "text"

            else:  # KPI Cards: Paid Clicks, Times Searched, Direct Visits, Social Media
                if matched_measure:
                    label = FieldRef(name=matched_measure.caption or matched_measure.name, field_type="measure")
                tableau_mark = "text"

        # Filters
        filters = []
        for f in getattr(visual, "filters", []):
            filters.append(FilterSpec(field_name=f))

        return WorksheetSpec(
            id=str(uuid.uuid4()),
            name=visual.name,
            datasource_ref="default",
            mark_type=tableau_mark,
            rows=rows,
            columns=columns,
            color=color,
            size=size,
            label=label,
            filters=filters,
        )
