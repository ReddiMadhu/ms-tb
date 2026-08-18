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

        for visual in self.ir.visuals:
            ws = self._plan_worksheet(visual)
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

        # Create default dashboard
        if result.worksheets:
            dashboard = DashboardSpec(
                id=str(uuid.uuid4()),
                name="Migrated Dashboard",
                worksheets=[ws.name for ws in result.worksheets if not ws.is_failed],
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
            filters=filters,
        )
