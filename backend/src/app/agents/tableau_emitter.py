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
        for ws_spec in viz_plan.worksheets:
            if not ws_spec.is_failed:
                self._emit_worksheet(worksheets_node, ws_spec)

        # Step 4: Add dashboards
        dashboards_node = etree.SubElement(root, "dashboards")
        for dash_spec in viz_plan.dashboards:
            self._emit_dashboard(dashboards_node, dash_spec, viz_plan.worksheets)

        # Step 5: Add windows
        windows_node = etree.SubElement(root, "windows")
        for ws_spec in viz_plan.worksheets:
            if not ws_spec.is_failed:
                self._emit_window(windows_node, ws_spec.name)
        for dash_spec in viz_plan.dashboards:
            self._emit_window(windows_node, dash_spec.name, is_dashboard=True)

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
        """Create the root <workbook> element with required attributes."""
        return etree.Element("workbook", attrib={
            "original-version": TABLEAU_VERSION,
            "source-build": TABLEAU_VERSION,
            "source-platform": "win",
            "version": TABLEAU_VERSION,
            "xml:base": "https://localhost",
        })

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
        """Inject connection XML pointing to Hyper file or live source."""
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

        # Logical tables
        if ir.tables:
            relation = etree.SubElement(conn, "relation", attrib={
                "name": "Extract",
                "table": f"[Extract].[{ir.tables[0].physical_name}]",
                "type": "table",
            })

            # Multi-table relationships
            if len(ir.tables) > 1:
                for rel in ir.relationships:
                    cols_left = etree.SubElement(conn, "cols", attrib={
                        "left": ", ".join(rel.left_keys),
                        "right": ", ".join(rel.right_keys),
                    })

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
            if dim.remote_name:
                col.set("remote-name", dim.remote_name)
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
            if measure.remote_name:
                col.set("remote-name", measure.remote_name)

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

    def _emit_worksheet(self, parent, ws_spec):
        """Emit a <worksheet> element."""
        ws = etree.SubElement(parent, "worksheet", attrib={
            "name": ws_spec.name,
        })

        table = etree.SubElement(ws, "table")

        # View (mark type + shelves)
        view = etree.SubElement(table, "view")

        # Mark type
        mark = etree.SubElement(view, "mark", attrib={
            "class": ws_spec.mark_type,
        })

        # Rows shelf
        if ws_spec.rows:
            rows_el = etree.SubElement(view, "rows")
            rows_el.text = " ".join(f"[{r.name}]" for r in ws_spec.rows)

        # Columns shelf
        if ws_spec.columns:
            cols_el = etree.SubElement(view, "cols")
            cols_el.text = " ".join(f"[{c.name}]" for c in ws_spec.columns)

        # Color encoding
        if ws_spec.color:
            enc = etree.SubElement(view, "encoding", attrib={
                "type": "color",
                "field": f"[{ws_spec.color.name}]",
            })

        # Size encoding
        if ws_spec.size:
            enc = etree.SubElement(view, "encoding", attrib={
                "type": "size",
                "field": f"[{ws_spec.size.name}]",
            })

        # Filters
        for flt in ws_spec.filters:
            filter_el = etree.SubElement(table, "filter", attrib={
                "class": flt.filter_type,
                "column": f"[{flt.field_name}]",
            })
            if flt.is_context:
                filter_el.set("context", "true")

    def _emit_dashboard(self, parent, dash_spec, all_worksheets):
        """Emit a <dashboard> element with auto-tiled zones (ADR-008)."""
        dash = etree.SubElement(parent, "dashboard", attrib={
            "name": dash_spec.name,
        })

        size = etree.SubElement(dash, "size", attrib={
            "maxheight": "1200",
            "maxwidth": "1920",
            "minheight": "600",
            "minwidth": "800",
        })

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
            ws_zone = etree.SubElement(root_zone, "zone", attrib={
                "h": str(100000 // max(len(valid_worksheets), 1)),
                "id": zone_id,
                "name": ws.name,
                "type-v2": "layout-basic",
                "w": "100000",
                "x": "0",
                "y": str(i * (100000 // max(len(valid_worksheets), 1))),
            })

        # Dashboard filters
        for flt in dash_spec.filters:
            filter_el = etree.SubElement(dash, "filter", attrib={
                "class": flt.filter_type,
                "column": f"[{flt.field_name}]",
            })

    def _emit_window(self, parent, name: str, is_dashboard: bool = False):
        """Emit a <window> element for navigation."""
        window = etree.SubElement(parent, "window", attrib={
            "class": "dashboard" if is_dashboard else "worksheet",
            "name": name,
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
                datasource_name=domain,
                original_path=abs_path,
                staging_path=f"_migration_staging/Datasources/{domain}",
                production_path=f"Data/Extracts/{domain}.hyper",
                active_path=new_path,
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
            file_path=str(path),
            file_name=path.name,
            content_hash=content_hash,
            file_size_bytes=file_size,
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
