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
from xml.sax.saxutils import escape as xml_escape

from lxml import etree

from sqlalchemy.orm import Session

from app.models.job import Job
from app.models.objects import Artifact, DatasourcePathRewrite

logger = logging.getLogger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Tableau XML namespace constants
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

TABLEAU_VERSION = "2024.2"
TWB_XML_NS = "http://www.tableau.com"

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

        # Step 1: Create TWB XML structure
        root = self._create_workbook_root()

        # Step 2: Add datasource
        datasources_node = etree.SubElement(root, "datasources")
        ds_node = self._emit_datasource(datasources_node, ir, hyper_paths)

        # Step 3: Add worksheets
        worksheets_node = etree.SubElement(root, "worksheets")
        ws_number = 1
        for ws_spec in viz_plan.worksheets:
            if not ws_spec.is_failed:
                self._emit_worksheet(worksheets_node, ws_spec, ws_number)
                ws_number += 1

        # Step 4: Add dashboards
        dashboards_node = etree.SubElement(root, "dashboards")
        for dash_spec in viz_plan.dashboards:
            self._emit_dashboard(dashboards_node, dash_spec, viz_plan.worksheets)

        # Step 5: Add windows
        windows_node = etree.SubElement(root, "windows")
        active_set = False
        for ws_spec in viz_plan.worksheets:
            if not ws_spec.is_failed:
                self._emit_window(windows_node, ws_spec.name, is_active=not active_set)
                active_set = True
        for dash_spec in viz_plan.dashboards:
            self._emit_window(windows_node, dash_spec.name, is_dashboard=True)

        # Step 5b: Add required trailing workbook elements
        etree.SubElement(root, "thumbnails")
        etree.SubElement(root, "datagraph")

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

        self._inject_datasource_columns(root, ir)
        self._inject_calculated_fields(root, ir)
        self._inject_connection(root, ir, hyper_paths)

        tds_path = tds_dir / f"{ds_name}.tds"
        tree = etree.ElementTree(root)
        tree.write(str(tds_path), xml_declaration=True, encoding="utf-8", pretty_print=True)

        self._record_artifact(tds_path, ds_name, artifact_type="datasource")
        return tds_path

    # ── TWB XML building ────────────────────────────────────────

    def _create_workbook_root(self) -> etree._Element:
        """Create the root <workbook> element with required attributes and children."""
        root = etree.Element("workbook", attrib={
            "original-version": TABLEAU_VERSION,
            "source-build": TABLEAU_VERSION,
            "source-platform": "win",
            "version": TABLEAU_VERSION,
            "{http://www.w3.org/XML/1998/namespace}base": "https://localhost",
        })

        # Document format change manifest (required for XSD validation)
        manifest = etree.SubElement(root, "document-format-change-manifest")
        etree.SubElement(manifest, "_.fcp.MarkAnimation.true...fcp.MarkAnimation")
        etree.SubElement(manifest, "_.fcp.ObjectModelEncapsulateLegacy.true...fcp.ObjectModelEncapsulateLegacy")
        etree.SubElement(manifest, "_.fcp.ObjectModelTableType.true...fcp.ObjectModelTableType")
        etree.SubElement(manifest, "_.fcp.SchemaViewerObjectModel.true...fcp.SchemaViewerObjectModel")
        etree.SubElement(manifest, "SheetIdentifierTracking", attrib={"consideredSheetIdentifierTracking": "true"})

        etree.SubElement(root, "preferences")

        # Global style
        style = etree.SubElement(root, "style")
        rule = etree.SubElement(style, "style-rule", attrib={"element": "worksheet"})
        format_el = etree.SubElement(rule, "format", attrib={"attr": "sheet-title-font-size", "value": "12"})

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

        # Columns (dimensions)
        self._inject_datasource_columns(ds, ir)

        # Calculated fields (measures)
        self._inject_calculated_fields(ds, ir)

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

    def _inject_datasource_columns(self, ds_node, ir):
        """Inject dimension columns into datasource."""
        for dim in ir.dimensions:
            col = etree.SubElement(ds_node, "column", attrib={
                "caption": xml_escape(dim.caption),
                "datatype": self._map_to_tableau_datatype(dim.data_type),
                "name": f"[{dim.local_name}]",
                "role": dim.role,
                "type": "nominal" if dim.data_type == "string" else "ordinal",
            })
            if dim.hidden:
                col.set("hidden", "true")

    def _inject_calculated_fields(self, ds_node, ir):
        """Inject calculated field columns (measures) in topo-sorted order."""
        # Topological sort by dependencies
        sorted_measures = self._topo_sort_measures(ir.measures)

        for measure in sorted_measures:
            col = etree.SubElement(ds_node, "column", attrib={
                "caption": xml_escape(measure.caption),
                "datatype": "real",
                "name": f"[{measure.local_name}]",
                "role": "measure",
                "type": "quantitative",
            })

            # Formula with XML entity encoding
            calc = etree.SubElement(col, "calculation", attrib={
                "class": "tableau",
                "formula": xml_escape(measure.tableau_calc),
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

    def _emit_worksheet(self, parent, ws_spec, ws_number: int = 1):
        """Emit a schema-valid <worksheet> element with all required XSD children."""
        ws = etree.SubElement(parent, "worksheet", attrib={
            "name": ws_spec.name,
        })

        table = etree.SubElement(ws, "table")

        # 1. view
        view = etree.SubElement(table, "view")
        ds_node = etree.SubElement(view, "datasources")
        etree.SubElement(ds_node, "datasource", attrib={
            "caption": "Migrated Data",
            "name": "federated.default",
        })

        for flt in ws_spec.filters:
            filter_el = etree.SubElement(view, "filter", attrib={
                "class": flt.filter_type,
                "column": f"[federated.default].[{flt.field_name}]",
            })
            if flt.is_context:
                filter_el.set("context", "true")

        etree.SubElement(view, "aggregation", attrib={"value": "true"})

        # 2. style
        etree.SubElement(table, "style")

        # 3. panes
        panes = etree.SubElement(table, "panes")
        pane = etree.SubElement(panes, "pane", attrib={"id": "0"})
        pane_view = etree.SubElement(pane, "view")
        etree.SubElement(pane_view, "breakdown", attrib={"value": "auto"})

        # Fix mark class: capitalize properly for Tableau XSD
        raw_mark = ws_spec.mark_type or "automatic"
        mark_class = MARK_CLASS_MAP.get(raw_mark.lower(), "Automatic")
        etree.SubElement(pane, "mark", attrib={"class": mark_class})

        encodings = etree.SubElement(pane, "encodings")
        if ws_spec.color:
            etree.SubElement(encodings, "color", attrib={
                "column": f"[federated.default].[{ws_spec.color.name}]",
            })
        if ws_spec.size:
            etree.SubElement(encodings, "size", attrib={
                "column": f"[federated.default].[{ws_spec.size.name}]",
            })

        # 4. rows
        rows_el = etree.SubElement(table, "rows")
        if ws_spec.rows:
            rows_el.text = " ".join(f"[federated.default].[{r.name}]" for r in ws_spec.rows)

        # 5. cols
        cols_el = etree.SubElement(table, "cols")
        if ws_spec.columns:
            cols_el.text = " ".join(f"[federated.default].[{c.name}]" for c in ws_spec.columns)

        # 6. Required XSD children: simple-id and worksheet-number
        etree.SubElement(ws, "simple-id", attrib={
            "uuid": "{" + str(uuid.uuid4()).upper() + "}",
        })
        ws_num_el = etree.SubElement(ws, "worksheet-number")
        ws_num_el.set("value", str(ws_number))

    def _emit_dashboard(self, parent, dash_spec, all_worksheets):
        """Emit a schema-valid <dashboard> element with all required XSD children."""
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

        # Add worksheet zones (auto-tiled layout)
        valid_worksheets = [
            ws for ws in all_worksheets
            if ws.name in dash_spec.worksheets and not ws.is_failed
        ]

        for i, ws in enumerate(valid_worksheets):
            zone_id = str(i + 2)
            zone_h = 100000 // max(len(valid_worksheets), 1)
            etree.SubElement(root_zone, "zone", attrib={
                "h": str(zone_h),
                "id": zone_id,
                "name": ws.name,
                "type-v2": "layout-basic",
                "w": "100000",
                "x": "0",
                "y": str(i * zone_h),
            })

        # Dashboard filters
        for flt in dash_spec.filters:
            etree.SubElement(dash, "filter", attrib={
                "class": flt.filter_type,
                "column": f"[{flt.field_name}]",
            })

        # Required: devicelayouts
        etree.SubElement(dash, "devicelayouts")

        # Required: simple-id
        etree.SubElement(dash, "simple-id", attrib={
            "uuid": "{" + str(uuid.uuid4()).upper() + "}",
        })

    def _build_join_tree(self, conn, ir):
        """Build a proper join-tree relation for multi-table star schemas."""
        # Find fact table (or first table as anchor)
        fact_tables = [t for t in ir.tables if t.name.startswith("FACT")]
        anchor = fact_tables[0] if fact_tables else ir.tables[0]
        dim_tables = [t for t in ir.tables if t.name != anchor.name]

        if not dim_tables:
            # Single table
            etree.SubElement(conn, "relation", attrib={
                "name": anchor.physical_name,
                "table": f"[Extract].[{anchor.physical_name}]",
                "type": "table",
            })
            return

        # Build nested join relations: ((anchor JOIN dim1) JOIN dim2) ...
        # Construct the join tree bottom-up to avoid lxml parent-child issues
        joinable_dims = []
        for dim in dim_tables:
            for rel in ir.relationships:
                if (rel.left_table == anchor.name and rel.right_table == dim.name) or \
                   (rel.left_table == dim.name and rel.right_table == anchor.name):
                    joinable_dims.append((dim, rel))
                    break

        if not joinable_dims:
            # No joinable dims found — emit as single table
            etree.SubElement(conn, "relation", attrib={
                "name": anchor.physical_name,
                "table": f"[Extract].[{anchor.physical_name}]",
                "type": "table",
            })
            return

        # Start with the first join: anchor JOIN dim[0]
        dim0, rel0 = joinable_dims[0]
        current_join = etree.Element("relation", attrib={
            "join": "inner",
            "type": "join",
        })
        etree.SubElement(current_join, "relation", attrib={
            "name": anchor.physical_name,
            "table": f"[Extract].[{anchor.physical_name}]",
            "type": "table",
        })
        etree.SubElement(current_join, "relation", attrib={
            "name": dim0.physical_name,
            "table": f"[Extract].[{dim0.physical_name}]",
            "type": "table",
        })
        l_keys = rel0.left_keys if rel0.left_table == anchor.name else rel0.right_keys
        r_keys = rel0.right_keys if rel0.left_table == anchor.name else rel0.left_keys
        clause = etree.SubElement(current_join, "clause", attrib={"type": "join"})
        expr = etree.SubElement(clause, "expression", attrib={"op": "="})
        etree.SubElement(expr, "expression", attrib={
            "op": f"[{anchor.physical_name}].[{l_keys[0]}]",
        })
        etree.SubElement(expr, "expression", attrib={
            "op": f"[{dim0.physical_name}].[{r_keys[0]}]",
        })

        # Wrap each subsequent dim as an outer join
        for dim, rel in joinable_dims[1:]:
            outer_join = etree.Element("relation", attrib={
                "join": "inner",
                "type": "join",
            })
            outer_join.append(current_join)
            etree.SubElement(outer_join, "relation", attrib={
                "name": dim.physical_name,
                "table": f"[Extract].[{dim.physical_name}]",
                "type": "table",
            })
            l_keys = rel.left_keys if rel.left_table == anchor.name else rel.right_keys
            r_keys = rel.right_keys if rel.left_table == anchor.name else rel.left_keys
            clause = etree.SubElement(outer_join, "clause", attrib={"type": "join"})
            expr = etree.SubElement(clause, "expression", attrib={"op": "="})
            etree.SubElement(expr, "expression", attrib={
                "op": f"[{anchor.physical_name}].[{l_keys[0]}]",
            })
            etree.SubElement(expr, "expression", attrib={
                "op": f"[{dim.physical_name}].[{r_keys[0]}]",
            })
            current_join = outer_join

        # Attach the complete join tree to conn
        conn.append(current_join)

    def _emit_window(self, parent, name: str, is_dashboard: bool = False, is_active: bool = False):
        """Emit a schema-valid <window> element with all required XSD children."""
        window = etree.SubElement(parent, "window", attrib={
            "class": "dashboard" if is_dashboard else "worksheet",
            "name": name,
        })
        if is_dashboard:
            viewpoints = etree.SubElement(window, "viewpoints")
            etree.SubElement(viewpoints, "viewpoint", attrib={"name": name})
            etree.SubElement(window, "active", attrib={"name": name})
            etree.SubElement(window, "simple-id", attrib={
                "uuid": "{" + str(uuid.uuid4()).upper() + "}",
            })
        else:
            cards = etree.SubElement(window, "cards")
            edge_left = etree.SubElement(cards, "edge", attrib={"name": "left"})
            strip_left = etree.SubElement(edge_left, "strip", attrib={"size": "160"})
            etree.SubElement(strip_left, "card", attrib={"type": "pages"})
            etree.SubElement(strip_left, "card", attrib={"type": "filters"})
            etree.SubElement(strip_left, "card", attrib={"type": "marks"})
            etree.SubElement(window, "viewpoint", attrib={"name": name})
            etree.SubElement(window, "simple-id", attrib={
                "uuid": "{" + str(uuid.uuid4()).upper() + "}",
            })

    # ── Path rewriting (ADR-023) ────────────────────────────────

    def _rewrite_paths(self, twb_path: Path, hyper_paths: dict):
        """Rewrite datasource paths for staging/production."""
        content = twb_path.read_text(encoding="utf-8")

        for domain, abs_path in hyper_paths.items():
            if self.target_env == "staging":
                new_path = f"_migration_staging/Datasources/{domain}"
            else:
                new_path = f"Data/Extracts/{domain}.hyper"

            content = content.replace(abs_path, new_path)

            # Record rewrite
            rewrite = DatasourcePathRewrite(
                id=str(uuid.uuid4()),
                job_id=self.job.id,
                ir_datasource_id=domain,
                staging_path=f"_migration_staging/Datasources/{domain}",
                production_path=f"Data/Extracts/{domain}.hyper",
            )
            self.db.add(rewrite)

        twb_path.write_text(content, encoding="utf-8")
        self.db.commit()

    # ── TWBX packaging ──────────────────────────────────────────

    def _package_twbx(self, twb_path: Path, hyper_paths: dict, work_dir: Path) -> Path:
        """Package .twb + .hyper into .twbx ZIP."""
        twbx_path = work_dir / f"{twb_path.stem}.twbx"

        with zipfile.ZipFile(str(twbx_path), "w", zipfile.ZIP_DEFLATED) as zf:
            # Add TWB
            zf.write(str(twb_path), twb_path.name)

            # Add Hyper extracts
            for domain, hyper_path in hyper_paths.items():
                if os.path.exists(hyper_path):
                    zf.write(hyper_path, f"Data/Extracts/{domain}.hyper")

        return twbx_path

    # ── Artifact recording ──────────────────────────────────────

    def _record_artifact(
        self, path: Path, name: str, artifact_type: str = "workbook"
    ):
        """Record emitted artifact in database."""
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
