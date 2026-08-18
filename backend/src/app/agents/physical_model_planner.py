"""
PhysicalModelPlanner — Semantic-to-physical SQL compiler.

Ref: spec/agents.md §Agent 3.5
ADR-022: Extraction grain derivation
ADR-026: Physical model plan persistence

Responsibilities:
  1. Map MSTR logical tables to physical warehouse tables
  2. Reconstruct attribute forms (ID, DESC, compound keys)
  3. Compile fact expressions into SQL ASTs
  4. Plan join paths respecting VLDB settings
  5. Derive ExtractionGrain per Hyper target table
  6. Generate warehouse-dialect SQL extraction queries
"""

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

import sqlglot

from sqlalchemy.orm import Session

from app.models.job import Job
from app.models.objects import PhysicalModelPlan as PhysicalModelPlanORM

logger = logging.getLogger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Data structures
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@dataclass
class PhysicalColumnDef:
    """Physical column in a warehouse table."""
    column_name: str
    data_type: str            # "VARCHAR", "INTEGER", "DECIMAL", "DATE", "TIMESTAMP", etc.
    source_type: str          # "attribute_form", "fact_expression", "key"
    source_id: str            # MSTR attribute/fact ID
    source_form: Optional[str] = None  # form name for attributes
    nullable: bool = True
    is_key: bool = False


@dataclass
class PhysicalTablePlan:
    """Plan for a single Hyper table extracted from warehouse."""
    table_id: str
    physical_name: str
    schema: str
    catalog: Optional[str] = None
    columns: list[PhysicalColumnDef] = field(default_factory=list)
    extract_sql: Optional[str] = None
    expected_grain: list[str] = field(default_factory=list)
    row_estimate: Optional[int] = None


@dataclass
class PhysicalJoinEdge:
    """Join relationship between two physical tables."""
    left_table: str
    right_table: str
    left_keys: list[str]
    right_keys: list[str]
    join_type: str = "INNER"    # "INNER", "LEFT", "RIGHT", "FULL"
    cardinality: str = "many-to-one"


@dataclass
class ExtractionGrain:
    """Grain contract for a Hyper table — physical and semantic levels."""
    table_id: str
    physical_grain: list[str]     # Physical column names forming the grain
    semantic_grain: list[str]     # MSTR attribute IDs forming the semantic grain
    primary_keys: list[str]
    foreign_keys: list[dict]      # [{column, references_table, references_column}]
    semi_additive: bool = False


@dataclass
class PhysicalModelPlanData:
    """Complete physical model plan for a datasource domain."""
    job_id: str
    datasource_domain: str
    table_plans: list[PhysicalTablePlan]
    join_graph: list[PhysicalJoinEdge]
    grain_contracts: list[ExtractionGrain]
    vldb_overrides: dict[str, Any] = field(default_factory=dict)


class PhysicalModelPlanner:
    """
    Agent 3.5: Deterministic semantic-to-physical SQL compiler.

    Transforms MSTR semantic metadata into executable warehouse extraction
    plans. No LLM involved — purely rule-based compilation.
    """

    def __init__(self, db: Session, job: Job):
        self.db = db
        self.job = job

    def plan(self, semantic_bundle, warehouse_config: Optional[dict] = None) -> PhysicalModelPlanData:
        """
        Generate a PhysicalModelPlan from the SemanticBundle.

        Args:
            semantic_bundle: Output of SemanticAgent
            warehouse_config: Optional warehouse connection details

        Returns:
            PhysicalModelPlanData with SQL extraction queries and grain contracts.
        """
        wh = warehouse_config or {}
        schema = wh.get("schema", "public")
        catalog = wh.get("catalog")
        dialect = wh.get("dialect", "ansi")

        table_plans = []
        join_edges = []
        grain_contracts = []

        # ── Build dimension tables from attributes ──────────────

        for dim in semantic_bundle.dimensions:
            columns = []

            # ID form → primary key column
            if dim.id_form:
                columns.append(PhysicalColumnDef(
                    column_name=self._normalize_identifier(f"{dim.name}_ID"),
                    data_type="VARCHAR",
                    source_type="attribute_form",
                    source_id=dim.mstr_id,
                    source_form="ID",
                    is_key=True,
                    nullable=False,
                ))

            # DESC form → display column
            if dim.desc_form:
                columns.append(PhysicalColumnDef(
                    column_name=self._normalize_identifier(f"{dim.name}_DESC"),
                    data_type="VARCHAR",
                    source_type="attribute_form",
                    source_id=dim.mstr_id,
                    source_form="DESC",
                ))

            # Additional forms
            for form in dim.forms:
                if form["form_name"].upper() not in ("ID", "DESC", "DESCRIPTION", "KEY"):
                    columns.append(PhysicalColumnDef(
                        column_name=self._normalize_identifier(f"{dim.name}_{form['form_name']}"),
                        data_type=self._map_data_type(form["data_type"]),
                        source_type="attribute_form",
                        source_id=dim.mstr_id,
                        source_form=form["form_name"],
                    ))

            # Compound key columns
            if dim.compound_key:
                for i, key_id in enumerate(dim.compound_key):
                    key_col = PhysicalColumnDef(
                        column_name=self._normalize_identifier(f"{dim.name}_KEY_{i}"),
                        data_type="VARCHAR",
                        source_type="attribute_form",
                        source_id=dim.mstr_id,
                        source_form=f"KEY_{i}",
                        is_key=True,
                        nullable=False,
                    )
                    if key_col.column_name not in [c.column_name for c in columns]:
                        columns.append(key_col)

            table_name = self._normalize_identifier(f"DIM_{dim.name}")

            # Generate extraction SQL
            pk_cols = [c.column_name for c in columns if c.is_key]
            all_col_names = [c.column_name for c in columns]
            extract_sql = self._generate_select_sql(
                table_name, all_col_names, schema, catalog, dialect
            )

            plan = PhysicalTablePlan(
                table_id=f"dim_{dim.mstr_id}",
                physical_name=table_name,
                schema=schema,
                catalog=catalog,
                columns=columns,
                extract_sql=extract_sql,
                expected_grain=pk_cols,
            )
            table_plans.append(plan)

            grain_contracts.append(ExtractionGrain(
                table_id=plan.table_id,
                physical_grain=pk_cols,
                semantic_grain=[dim.mstr_id],
                primary_keys=pk_cols,
                foreign_keys=[],
            ))

        # ── Build fact table from facts + measures ──────────────

        if semantic_bundle.facts or semantic_bundle.measures:
            fact_columns = []
            grain_keys = set()

            for fact in semantic_bundle.facts:
                col_name = self._normalize_identifier(fact.name)
                fact_columns.append(PhysicalColumnDef(
                    column_name=col_name,
                    data_type=self._map_data_type(fact.data_type),
                    source_type="fact_expression",
                    source_id=fact.mstr_id,
                ))

            # Add FK columns for grain from dimensions
            for dim in semantic_bundle.dimensions:
                fk_col = self._normalize_identifier(f"{dim.name}_ID")
                if fk_col not in [c.column_name for c in fact_columns]:
                    fact_columns.append(PhysicalColumnDef(
                        column_name=fk_col,
                        data_type="VARCHAR",
                        source_type="key",
                        source_id=dim.mstr_id,
                        is_key=True,
                    ))
                    grain_keys.add(fk_col)

            fact_table_name = self._normalize_identifier("FACT_MAIN")
            all_col_names = [c.column_name for c in fact_columns]

            extract_sql = self._generate_select_sql(
                fact_table_name, all_col_names, schema, catalog, dialect
            )

            fact_plan = PhysicalTablePlan(
                table_id="fact_main",
                physical_name=fact_table_name,
                schema=schema,
                catalog=catalog,
                columns=fact_columns,
                extract_sql=extract_sql,
                expected_grain=list(grain_keys),
            )
            table_plans.append(fact_plan)

            # Detect semi-additive
            semi_additive = any(
                m.subtotal_type and m.subtotal_type.upper() not in ("SUM", "")
                for m in semantic_bundle.measures
            )

            grain_contracts.append(ExtractionGrain(
                table_id="fact_main",
                physical_grain=list(grain_keys),
                semantic_grain=[d.mstr_id for d in semantic_bundle.dimensions],
                primary_keys=list(grain_keys),
                foreign_keys=[
                    {
                        "column": self._normalize_identifier(f"{d.name}_ID"),
                        "references_table": self._normalize_identifier(f"DIM_{d.name}"),
                        "references_column": self._normalize_identifier(f"{d.name}_ID"),
                    }
                    for d in semantic_bundle.dimensions
                ],
                semi_additive=semi_additive,
            ))

            # Build join edges
            for dim in semantic_bundle.dimensions:
                fk_col = self._normalize_identifier(f"{dim.name}_ID")
                pk_col = self._normalize_identifier(f"{dim.name}_ID")
                join_edges.append(PhysicalJoinEdge(
                    left_table=fact_table_name,
                    right_table=self._normalize_identifier(f"DIM_{dim.name}"),
                    left_keys=[fk_col],
                    right_keys=[pk_col],
                    join_type=self._resolve_join_type(),
                    cardinality="many-to-one",
                ))

        # ── Persist to SQLite (ADR-026) ─────────────────────────

        plan_data = PhysicalModelPlanData(
            job_id=self.job.id,
            datasource_domain="default",
            table_plans=table_plans,
            join_graph=join_edges,
            grain_contracts=grain_contracts,
            vldb_overrides=self._get_vldb_overrides(),
        )

        orm_plan = PhysicalModelPlanORM(
            id=str(uuid.uuid4()),
            job_id=self.job.id,
            datasource_domain="default",
            table_plans_json=[self._table_plan_to_dict(t) for t in table_plans],
            join_graph_json=[self._join_edge_to_dict(e) for e in join_edges],
            grain_contract_json=[self._grain_to_dict(g) for g in grain_contracts],
            vldb_overrides_json=self._get_vldb_overrides(),
        )
        self.db.add(orm_plan)
        self.db.commit()

        logger.info(
            "Physical model plan: %d tables, %d joins, %d grain contracts",
            len(table_plans), len(join_edges), len(grain_contracts),
        )

        return plan_data

    # ── Helpers ──────────────────────────────────────────────────

    def _normalize_identifier(self, name: str) -> str:
        """
        Normalize identifier for Hyper/TDS parity.

        Case-fold + replace special chars. This MUST be identical
        between Hyper DDL and TDS XML remote-name attributes.
        """
        normalized = name.strip()
        normalized = normalized.replace(" ", "_")
        normalized = normalized.replace("-", "_")
        normalized = normalized.replace(".", "_")
        # Remove any characters that are not alphanumeric or underscore
        normalized = "".join(c for c in normalized if c.isalnum() or c == "_")
        return normalized

    def _map_data_type(self, mstr_type: str) -> str:
        """Map MSTR data type to Hyper-compatible type."""
        type_map = {
            "string": "VARCHAR",
            "char": "VARCHAR",
            "integer": "INTEGER",
            "int32": "INTEGER",
            "int64": "BIGINT",
            "numeric": "DOUBLE",
            "decimal": "DOUBLE",
            "float": "DOUBLE",
            "double": "DOUBLE",
            "date": "DATE",
            "time": "TIME",
            "timestamp": "TIMESTAMP",
            "datetime": "TIMESTAMP",
            "boolean": "BOOLEAN",
            "bool": "BOOLEAN",
        }
        return type_map.get(mstr_type.lower(), "VARCHAR")

    def _generate_select_sql(
        self,
        table_name: str,
        columns: list[str],
        schema: str,
        catalog: Optional[str],
        dialect: str,
    ) -> str:
        """Generate a SELECT SQL statement for extraction."""
        col_list = ", ".join(f'"{c}"' for c in columns)
        full_table = f'"{schema}"."{table_name}"'
        if catalog:
            full_table = f'"{catalog}".{full_table}'

        sql = f"SELECT {col_list} FROM {full_table}"

        # Validate with sqlglot
        try:
            sqlglot.transpile(sql, read=dialect, write="ansi")
        except Exception as e:
            logger.warning("SQL validation warning for %s: %s", table_name, e)

        return sql

    def _resolve_join_type(self) -> str:
        """Resolve join type from VLDB settings."""
        vldb = self.job.vldb_settings_json or {}
        join_setting = vldb.get("propertyValues", {}).get("JoinType", {}).get("value", "1")
        # 1 = INNER, 2 = LEFT OUTER, 3 = RIGHT OUTER, 4 = FULL OUTER
        return {
            "1": "INNER",
            "2": "LEFT",
            "3": "RIGHT",
            "4": "FULL",
        }.get(str(join_setting), "INNER")

    def _get_vldb_overrides(self) -> dict:
        """Extract relevant VLDB overrides."""
        return {
            "null_propagation": self.job.null_propagation or "propagate",
            "zero_division_result": self.job.zero_division_result or "null",
        }

    def _table_plan_to_dict(self, plan: PhysicalTablePlan) -> dict:
        return {
            "table_id": plan.table_id,
            "physical_name": plan.physical_name,
            "schema": plan.schema,
            "columns": [
                {
                    "column_name": c.column_name,
                    "data_type": c.data_type,
                    "source_type": c.source_type,
                    "source_id": c.source_id,
                    "is_key": c.is_key,
                }
                for c in plan.columns
            ],
            "extract_sql": plan.extract_sql,
            "expected_grain": plan.expected_grain,
        }

    def _join_edge_to_dict(self, edge: PhysicalJoinEdge) -> dict:
        return {
            "left_table": edge.left_table,
            "right_table": edge.right_table,
            "left_keys": edge.left_keys,
            "right_keys": edge.right_keys,
            "join_type": edge.join_type,
            "cardinality": edge.cardinality,
        }

    def _grain_to_dict(self, grain: ExtractionGrain) -> dict:
        return {
            "table_id": grain.table_id,
            "physical_grain": grain.physical_grain,
            "semantic_grain": grain.semantic_grain,
            "primary_keys": grain.primary_keys,
            "foreign_keys": grain.foreign_keys,
            "semi_additive": grain.semi_additive,
        }
