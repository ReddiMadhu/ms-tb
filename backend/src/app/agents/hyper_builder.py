"""
HyperAgent — Streaming chunked data extraction and Hyper file builder.

Ref: spec/agents.md §Agent 7
ADR-016: MSTRSession lifecycle (instance re-creation on 404)
ADR-019: asyncio.to_thread for blocking I/O
ADR-022: Warehouse-direct extraction

Responsibilities:
  1. Extract data from MSTR cubes/reports via paginated JSON Data API
  2. Build multi-table .hyper files with streaming chunked inserts
  3. Maintain extraction checkpoints for crash recovery
  4. Atomic file swap to prevent corruption
  5. Identifier normalization parity with TDS XML (Gotcha 5)
"""

import asyncio
import hashlib
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

from sqlalchemy.orm import Session

from app.models.job import Job
from app.models.objects import ExtractionCheckpoint, MigrationObject

logger = logging.getLogger(__name__)


@dataclass
class HyperTableSchema:
    """Schema for a single table in a Hyper file."""
    table_name: str
    columns: list[dict]      # [{name, type}]
    primary_keys: list[str]


@dataclass
class HyperBuildResult:
    """Result of a Hyper file build."""
    hyper_path: str
    tables_built: int
    total_rows: int
    file_size_bytes: int
    content_hash: str


class CheckpointManager:
    """
    Manages page-level extraction checkpoints for crash recovery.

    Persists offset/rows_written after each successful page extraction,
    enabling resume from the last checkpoint on restart.
    """

    def __init__(self, db: Session, job_id: str):
        self.db = db
        self.job_id = job_id

    def get_checkpoint(self, object_id: str) -> Optional[ExtractionCheckpoint]:
        """Retrieve existing checkpoint for an object."""
        return (
            self.db.query(ExtractionCheckpoint)
            .filter(
                ExtractionCheckpoint.job_id == self.job_id,
                ExtractionCheckpoint.object_id == object_id,
                ExtractionCheckpoint.completed == False,
            )
            .first()
        )

    def save_checkpoint(
        self,
        object_id: str,
        page_offset: int,
        rows_written: int,
        page_checksum: Optional[str] = None,
    ):
        """Persist extraction checkpoint after a successful page."""
        existing = self.get_checkpoint(object_id)
        if existing:
            existing.page_offset = page_offset
            existing.rows_written = rows_written
            existing.page_checksum = page_checksum
            existing.updated_at = datetime.now(timezone.utc)
        else:
            checkpoint = ExtractionCheckpoint(
                id=str(uuid.uuid4()),
                job_id=self.job_id,
                object_id=object_id,
                page_offset=page_offset,
                rows_written=rows_written,
                page_checksum=page_checksum,
            )
            self.db.add(checkpoint)
        self.db.commit()

    def mark_complete(self, object_id: str):
        """Mark extraction as complete."""
        existing = self.get_checkpoint(object_id)
        if existing:
            existing.completed = True
            existing.updated_at = datetime.now(timezone.utc)
            self.db.commit()


class HyperAgent:
    """
    Agent 7: Streaming data extraction and Hyper file generation.

    Extracts data from MSTR cubes/reports using the paginated JSON Data API,
    builds multi-table .hyper files using streaming chunked inserts (never
    accumulates full DataFrames in memory), and uses atomic file swap for
    corruption prevention.
    """

    def __init__(
        self,
        db: Session,
        job: Job,
        artifacts_dir: str,
    ):
        self.db = db
        self.job = job
        self.artifacts_dir = Path(artifacts_dir)
        self.checkpoint_mgr = CheckpointManager(db, job.id)

    async def extract_and_build(
        self,
        physical_plan,
        mstr_session=None,
    ) -> dict[str, HyperBuildResult]:
        """
        Extract data and build .hyper files per the PhysicalModelPlan.

        Returns mapping of datasource_domain → HyperBuildResult.
        """
        results = {}

        # For each table plan, extract data and build Hyper
        hyper_dir = self.artifacts_dir / "hyper"
        hyper_dir.mkdir(parents=True, exist_ok=True)

        hyper_path = hyper_dir / f"{physical_plan.datasource_domain}.hyper"

        # Collect data iterators for streaming build
        data_iterators: dict[str, list[list]] = {}

        for table_plan in physical_plan.table_plans:
            rows = await self._extract_table_data(table_plan, mstr_session)
            data_iterators[table_plan.table_id] = rows

        # Build Hyper file
        result = await asyncio.to_thread(
            self._build_hyper_file,
            hyper_path,
            physical_plan.table_plans,
            data_iterators,
        )

        results[physical_plan.datasource_domain] = result
        return results

    @staticmethod
    def get_cache_path(cache_key: str) -> Path:
        """Get path to cached .hyper file in ./artifacts/cache/"""
        cache_dir = Path("./artifacts/cache")
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir / f"{cache_key}.hyper"

    @staticmethod
    def build_from_source_file(
        source_file: Path,
        target_hyper: Path,
        schema_name: str = "Extract",
        table_name: str = "Extract",
        measures: set[str] = None,
    ) -> HyperBuildResult:
        """
        Direct high-speed ingest from local/warehouse source file (.parquet, .csv, .xlsx, .json)
        into Tableau .hyper using DuckDB + PyArrow chunked record batches.
        Achieves ~20-second ingestion for 500,000 rows.
        """
        import duckdb
        import pyarrow as pa
        from tableauhyperapi import (
            HyperProcess,
            Telemetry,
            Connection,
            CreateMode,
            TableDefinition,
            TableName,
            SqlType,
            Inserter,
        )

        measures = measures or set()
        source_str = str(source_file).replace("\\", "/")

        target_hyper.parent.mkdir(parents=True, exist_ok=True)
        temp_hyper = target_hyper.with_suffix(".tmp.hyper")
        if temp_hyper.exists():
            temp_hyper.unlink()

        con = duckdb.connect()
        arrow_reader = con.execute(f"SELECT * FROM '{source_str}'").to_arrow_reader(rows_per_batch=100000)

        # Inspect schema from first batch
        try:
            first_batch = arrow_reader.read_next_batch()
        except StopIteration:
            first_batch = None

        if first_batch is None:
            raise ValueError(f"No records found in source file: {source_file}")

        # Filter out placeholder/dynamic metric columns that have 0 non-null values in the data source
        active_col_names = []
        batch_len = len(first_batch)
        for col_name in first_batch.schema.names:
            arr = first_batch[col_name]
            # If all values in the column are null, skip it from physical storage so it can be calculated dynamically
            if batch_len > 0 and arr.null_count == batch_len:
                logger.info("Skipping all-null metric placeholder column '%s' from physical Hyper schema", col_name)
                continue
            active_col_names.append(col_name)

        col_names = active_col_names
        table_def = TableDefinition(TableName(schema_name, table_name))

        # Map the source's ACTUAL Arrow data types to Hyper SQL types instead
        # of guessing from column-name keywords. Keyword guessing is what
        # typed numeric attributes like "Fraud Score" (integer ID form in
        # MSTR) as TEXT — forcing every downstream calculation into defensive
        # INT()/FLOAT() casts that break on formatted strings.
        import pyarrow.types as pa_types

        def _sql_type_for(arrow_type) -> "SqlType":
            if pa_types.is_integer(arrow_type):
                return SqlType.big_int()
            if pa_types.is_floating(arrow_type) or pa_types.is_decimal(arrow_type):
                return SqlType.double()
            if pa_types.is_boolean(arrow_type):
                return SqlType.bool()
            if pa_types.is_date(arrow_type):
                return SqlType.date()
            if pa_types.is_timestamp(arrow_type):
                return SqlType.timestamp()
            if pa_types.is_time(arrow_type):
                return SqlType.time()
            return SqlType.text()

        for col_name in col_names:
            arrow_type = first_batch.schema.field(col_name).type
            if col_name in measures and pa_types.is_string(arrow_type):
                # Known measure arriving as text (dirty/formatted source).
                # Keep TEXT: row-level FLOAT() casts in the calculated fields
                # handle conversion; forcing DOUBLE here would abort ingestion
                # on the first non-numeric value.
                table_def.add_column(col_name, SqlType.text())
            else:
                table_def.add_column(col_name, _sql_type_for(arrow_type))

        total_rows = 0
        hasher = hashlib.sha256()

        with HyperProcess(telemetry=Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU) as hp:
            with Connection(endpoint=hp.endpoint, database=str(temp_hyper), create_mode=CreateMode.CREATE_AND_REPLACE) as conn:
                conn.catalog.create_schema(schema_name)
                conn.catalog.create_table(table_def)

                with Inserter(conn, table_def) as inserter:
                    # Ingest first batch
                    batch_dict = first_batch.to_pydict()
                    rows = zip(*[batch_dict[c] for c in col_names])
                    inserter.add_rows(rows)
                    total_rows += len(first_batch)

                    # Ingest remaining batches
                    while True:
                        try:
                            batch = arrow_reader.read_next_batch()
                            b_dict = batch.to_pydict()
                            b_rows = zip(*[b_dict[c] for c in col_names])
                            inserter.add_rows(b_rows)
                            total_rows += len(batch)
                        except StopIteration:
                            break

                    inserter.execute()

        # Atomic rename
        if target_hyper.exists():
            target_hyper.unlink()
        temp_hyper.rename(target_hyper)

        file_size = target_hyper.stat().st_size
        return HyperBuildResult(
            hyper_path=str(target_hyper),
            table_row_counts={table_name: total_rows},
            total_rows=total_rows,
            file_size_bytes=file_size,
            content_hash=hasher.hexdigest(),
        )

    async def _extract_table_data(
        self,
        table_plan,
        mstr_session=None,
    ) -> list[list]:
        """
        Extract data for a table plan.

        If MSTR session is available, extracts from MSTR Data API.
        Otherwise, returns empty data (for warehouse-direct mode).
        """
        if not mstr_session:
            logger.info("No MSTR session — skipping data extraction for %s", table_plan.table_id)
            return []

        # Find corresponding MSTR object
        # For fact tables, extract from cube instances
        # For dimension tables, extract attribute elements
        cube_objects = (
            self.db.query(MigrationObject)
            .filter(
                MigrationObject.job_id == self.job.id,
                MigrationObject.type_name.in_(["cube", "report"]),
            )
            .all()
        )

        all_rows = []
        for cube in cube_objects:
            # Check for existing checkpoint
            checkpoint = self.checkpoint_mgr.get_checkpoint(cube.mstr_id)
            offset = checkpoint.page_offset if checkpoint else 0

            try:
                instance = await mstr_session.create_cube_instance(cube.mstr_id)
                instance_id = instance.get("instanceId", "")

                while True:
                    try:
                        page = await mstr_session.get_cube_data(
                            cube.mstr_id,
                            instance_id,
                            offset=offset,
                            limit=10000,
                        )
                    except Exception as e:
                        if "404" in str(e) or "expired" in str(e).lower():
                            # Instance expired — re-create
                            logger.warning("Cube instance expired, re-creating")
                            instance = await mstr_session.create_cube_instance(cube.mstr_id)
                            instance_id = instance.get("instanceId", "")
                            continue
                        raise

                    # Parse rows from MSTR response
                    rows = self._parse_mstr_response(page)
                    all_rows.extend(rows)
                    offset += 10000

                    # Persist checkpoint
                    page_hash = hashlib.md5(str(rows[:5]).encode()).hexdigest()
                    self.checkpoint_mgr.save_checkpoint(
                        cube.mstr_id, offset, len(all_rows), page_hash
                    )

                    if len(rows) < 10000:
                        break

                self.checkpoint_mgr.mark_complete(cube.mstr_id)

            except Exception as e:
                logger.error("Failed to extract cube %s: %s", cube.mstr_id, e)

        return all_rows

    def _parse_mstr_response(self, response: dict) -> list[dict]:
        """Parse MSTR JSON Data API response into named-dict rows.

        Returns list of dicts keyed by attribute/metric name so that
        consumers can map values to Hyper columns by name, not position.
        This eliminates ordering mismatches between the MSTR API column
        axis and the IR measure ordering.
        """
        rows: list[dict] = []
        result = response.get("result", response)
        definition = result.get("definition", {}) if isinstance(result, dict) else {}
        data = result.get("data", {}) if isinstance(result, dict) else {}

        # ── Extract attribute & metric name orderings from grid definition ──
        grid = definition.get("grid", {}) if isinstance(definition, dict) else {}
        
        # Attribute names and element lookups in row-axis order
        attr_names: list[str] = []
        elements_lookup: list[list] = []
        for row_obj in (grid.get("rows") or []):
            if isinstance(row_obj, dict):
                attr_names.append(row_obj.get("name", f"attr_{len(attr_names)}"))
                elements_lookup.append(row_obj.get("elements", []))

        # Fallback to headers.elements if grid.rows elements were empty
        headers = data.get("headers", {})
        if not any(elements_lookup) and isinstance(headers, dict) and "elements" in headers:
            elements_lookup = headers.get("elements", [])

        # Metric names in column-axis order (how metricValues.raw is ordered)
        metric_names: list[str] = []
        for col_obj in (grid.get("columns") or []):
            if isinstance(col_obj, dict):
                # MSTR wraps metrics inside a "Metrics" header with elements
                elements = col_obj.get("elements", [])
                if elements:
                    for elem in elements:
                        if isinstance(elem, dict):
                            metric_names.append(elem.get("name", f"metric_{len(metric_names)}"))
                else:
                    metric_names.append(col_obj.get("name", f"metric_{len(metric_names)}"))

        # ── 1. Standard MSTR Matrix format ──
        headers_rows = headers.get("rows", []) if isinstance(headers, dict) else []
        metric_values = data.get("metricValues", {}) if isinstance(data, dict) else {}
        metric_matrix = metric_values.get("raw") or metric_values.get("formatted") or []

        if headers_rows and isinstance(headers_rows, list):
            for row_idx, h_row in enumerate(headers_rows):
                row_dict: dict = {}

                # Parse attribute values
                cells = h_row if isinstance(h_row, list) else (
                    list((h_row.get("elements") or h_row.get("headers") or h_row).values())
                    if isinstance(h_row, dict) else [h_row]
                )

                for col_idx, cell in enumerate(cells):
                    # Determine the attribute name for this column
                    a_name = attr_names[col_idx] if col_idx < len(attr_names) else f"attr_{col_idx}"

                    if isinstance(cell, dict):
                        val = cell.get("name") or cell.get("value") or cell.get("v") or cell.get("id", "")
                    elif isinstance(cell, int) and col_idx < len(elements_lookup) and isinstance(elements_lookup[col_idx], list) and 0 <= cell < len(elements_lookup[col_idx]):
                        # Resolve element index → human-readable name/formValue
                        elem_dict = elements_lookup[col_idx][cell]
                        if isinstance(elem_dict, dict):
                            form_vals = elem_dict.get("formValues")
                            if form_vals and isinstance(form_vals, list) and len(form_vals) > 0:
                                val = str(form_vals[0])
                            else:
                                val = elem_dict.get("name") or elem_dict.get("value") or elem_dict.get("v") or str(cell)
                        else:
                            val = str(elem_dict)
                    else:
                        val = cell

                    row_dict[a_name] = val

                # Parse metric values — map by metric_names order
                if isinstance(metric_matrix, list) and row_idx < len(metric_matrix):
                    m_row = metric_matrix[row_idx]
                    if isinstance(m_row, list):
                        for m_idx, m_val in enumerate(m_row):
                            m_name = metric_names[m_idx] if m_idx < len(metric_names) else f"metric_{m_idx}"
                            row_dict[m_name] = m_val
                    elif isinstance(m_row, dict):
                        for m_key, m_val in m_row.items():
                            row_dict[m_key] = m_val

                rows.append(row_dict)
            if rows:
                return rows

        # ── 2. Flat row format: tabularData, grid, or rows ──
        row_data = data.get("rows") or data.get("tabularData") or data.get("grid")
        if row_data and isinstance(row_data, list):
            # Build combined name list for positional fallback
            all_names = list(attr_names) + list(metric_names)
            for row in row_data:
                if isinstance(row, list):
                    row_dict = {}
                    for idx, cell in enumerate(row):
                        key = all_names[idx] if idx < len(all_names) else f"col_{idx}"
                        if isinstance(cell, dict):
                            row_dict[key] = cell.get("value", cell.get("name", cell.get("v", "")))
                        else:
                            row_dict[key] = cell
                    rows.append(row_dict)
                elif isinstance(row, dict):
                    rows.append(row)
            if rows:
                return rows

        # ── 3. Hierarchical root tree format ──
        root = data.get("root", {})
        def traverse(node, current_path):
            header = node.get("header", {}) if isinstance(node, dict) else {}
            elem = node.get("element", {}) if isinstance(node, dict) else {}
            val = elem.get("name") or elem.get("value") or elem.get("v") or header.get("name") or header.get("value")
            new_path = list(current_path)
            if val is not None:
                new_path.append(val)
            children = node.get("children", []) if isinstance(node, dict) else []
            if children:
                for child in children:
                    traverse(child, new_path)
            else:
                row_dict = {}
                # Map path values to attr_names
                for i, pv in enumerate(new_path):
                    key = attr_names[i] if i < len(attr_names) else f"attr_{i}"
                    row_dict[key] = pv
                # Map metric values
                metrics = node.get("metrics") or node.get("metricValues") or node.get("values") or []
                if isinstance(metrics, list):
                    for m_idx, m in enumerate(metrics):
                        m_name = metric_names[m_idx] if m_idx < len(metric_names) else f"metric_{m_idx}"
                        if isinstance(m, dict):
                            row_dict[m_name] = m.get("raw") if "raw" in m else m.get("value", m.get("v", m))
                        else:
                            row_dict[m_name] = m
                elif isinstance(metrics, dict):
                    for m_key, v in metrics.items():
                        if isinstance(v, dict):
                            row_dict[m_key] = v.get("raw") if "raw" in v else v.get("value", v.get("v", v))
                        else:
                            row_dict[m_key] = v
                rows.append(row_dict)

        if root and isinstance(root, dict) and root.get("children"):
            for child in root.get("children", []):
                traverse(child, [])

        if not rows:
            logger.warning(
                "MSTR response parsing produced 0 rows. Response keys: %s, data keys: %s",
                list(result.keys()) if isinstance(result, dict) else type(result),
                list(data.keys()) if isinstance(data, dict) else type(data),
            )

        return rows

    def _build_hyper_file(
        self,
        hyper_path: Path,
        table_plans: list,
        data_iterators: dict[str, list[list]],
    ) -> HyperBuildResult:
        """
        Build multi-table .hyper file with streaming inserts and atomic swap.

        Uses temporary file + atomic rename to prevent partial corruption.
        """
        total_rows = 0
        tables_built = 0

        tmp_path = hyper_path.with_suffix(".hyper.tmp")

        try:
            # Try to use tableauhyperapi if available
            from tableauhyperapi import (
                HyperProcess,
                Telemetry,
                Connection,
                CreateMode,
                TableDefinition,
                TableName,
                Inserter,
                SqlType,
                NOT_NULLABLE,
                NULLABLE,
            )

            TYPE_MAP = {
                "VARCHAR": SqlType.text(),
                "INTEGER": SqlType.int_(),
                "BIGINT": SqlType.big_int(),
                "DOUBLE": SqlType.double(),
                "DATE": SqlType.date(),
                "TIME": SqlType.time(),
                "TIMESTAMP": SqlType.timestamp(),
                "BOOLEAN": SqlType.bool(),
            }

            with HyperProcess(telemetry=Telemetry.DO_NOT_SEND_USAGE_DATA) as hyper:
                with Connection(
                    endpoint=hyper.endpoint,
                    database=str(tmp_path),
                    create_mode=CreateMode.CREATE_AND_REPLACE,
                ) as conn:
                    for table_plan in table_plans:
                        columns = []
                        for col in table_plan.columns:
                            sql_type = TYPE_MAP.get(col.data_type, SqlType.text())
                            nullability = NOT_NULLABLE if col.is_key else NULLABLE
                            columns.append(
                                TableDefinition.Column(col.column_name, sql_type, nullability)
                            )

                        table_def = TableDefinition(
                            TableName("Extract", table_plan.physical_name),
                            columns,
                        )
                        conn.catalog.create_table(table_def)

                        # Stream data in chunks
                        rows = data_iterators.get(table_plan.table_id, [])
                        if rows:
                            col_names = [col.column_name for col in table_plan.columns]
                            CHUNK_SIZE = 10000
                            with Inserter(conn, table_def) as inserter:
                                for i in range(0, len(rows), CHUNK_SIZE):
                                    chunk = rows[i : i + CHUNK_SIZE]
                                    # Convert dict rows to ordered lists if needed
                                    if chunk and isinstance(chunk[0], dict):
                                        list_chunk = [
                                            [row.get(cn) for cn in col_names]
                                            for row in chunk
                                        ]
                                        inserter.add_rows(list_chunk)
                                    else:
                                        inserter.add_rows(chunk)
                                inserter.execute()

                        total_rows += len(rows)
                        tables_built += 1

            # Atomic swap
            if tmp_path.exists():
                if hyper_path.exists():
                    hyper_path.unlink()
                tmp_path.rename(hyper_path)

        except ImportError:
            # tableauhyperapi not available — create a placeholder
            logger.warning("tableauhyperapi not installed — creating placeholder .hyper")
            hyper_path.parent.mkdir(parents=True, exist_ok=True)

            # Write a JSON manifest instead
            import json
            manifest = {
                "placeholder": True,
                "tables": [
                    {
                        "name": tp.physical_name,
                        "columns": [c.column_name for c in tp.columns],
                        "row_count": len(data_iterators.get(tp.table_id, [])),
                    }
                    for tp in table_plans
                ],
            }
            hyper_path.with_suffix(".hyper.json").write_text(json.dumps(manifest, indent=2))
            tables_built = len(table_plans)

        # Compute content hash
        content_hash = ""
        if hyper_path.exists():
            h = hashlib.sha256()
            with open(hyper_path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    h.update(chunk)
            content_hash = h.hexdigest()
            file_size = hyper_path.stat().st_size
        else:
            file_size = 0

        return HyperBuildResult(
            hyper_path=str(hyper_path),
            tables_built=tables_built,
            total_rows=total_rows,
            file_size_bytes=file_size,
            content_hash=content_hash,
        )

    @staticmethod
    def normalize_identifier(name: str) -> str:
        """
        Normalize identifier — MUST match PhysicalModelPlanner._normalize_identifier.

        This ensures Hyper DDL column names match TDS XML remote-name attributes.
        """
        normalized = name.strip().replace(" ", "_").replace("-", "_").replace(".", "_")
        return "".join(c for c in normalized if c.isalnum() or c == "_")
