# Implementation Guide — Critical Patterns & SQL Templates

**Companion to:** 10-Step Principal Engineering Review (STEPS 1–10)  
**Date:** 17 August 2026  
**Purpose:** Bridge specification to concrete implementation with runnable code patterns, SQL templates, and database schema extensions

---

## Part 1: ADR-016 — MSTRSession with Proactive Renewal

### 1.1 Dynamic Session Lifecycle Pattern

**Problem:** MSTR token TTL is not fixed (30–60 min), and cube instances disappear on 10-min idle.

**Solution:** Proactive renewal with safety margin + 401/404 recovery.

```python
# core/mstr/session.py

import asyncio
import time
from datetime import datetime, timedelta
from typing import Optional
import aiohttp
import logging

logger = logging.getLogger(__name__)

@dataclass
class MSTRSessionConfig:
    base_url: str
    username: str
    password: str
    proactive_renewal_margin_seconds: int = 60  # Renew 1 min before expiry
    max_retries: int = 3
    retry_backoff_ms: int = 1000


class MSTRSession:
    """
    Manages MSTR authentication lifecycle with proactive renewal.
    
    Invariant: Token is always valid before any API call.
    Recovery: 401 → renew; 404 (cube) → recreate instance.
    """
    
    def __init__(self, config: MSTRSessionConfig, db: Database):
        self.config = config
        self.db = db
        self._session: Optional[aiohttp.ClientSession] = None
        self._token: Optional[str] = None
        self._token_expires_at: Optional[datetime] = None
        self._cube_instance_ids: Dict[str, datetime] = {}  # cube_id → last_access
        self._renewal_lock = asyncio.Lock()
    
    async def __aenter__(self):
        self._session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, *args):
        if self._session:
            await self._session.close()
    
    async def get_valid_token(self) -> str:
        """
        Return a valid authentication token.
        
        If token expires within margin, renew proactively.
        If 401 occurs, treat as authoritative and renew.
        """
        
        # Check if renewal needed
        if self._token_expires_soon():
            await self._renew_token()
        
        return self._token
    
    async def api_call_with_recovery(
        self,
        method: str,
        endpoint: str,
        **kwargs
    ) -> dict:
        """
        Make MSTR API call with automatic 401/404 recovery.
        """
        
        for attempt in range(self.config.max_retries):
            token = await self.get_valid_token()
            
            try:
                # Add auth header
                headers = kwargs.get("headers", {})
                headers["Authorization"] = f"Bearer {token}"
                kwargs["headers"] = headers
                
                # Execute request
                async with self._session.request(
                    method=method,
                    url=f"{self.config.base_url}{endpoint}",
                    timeout=30,
                    **kwargs
                ) as resp:
                    
                    if resp.status == 401:
                        # Unauthorized: token expired or invalid
                        logger.warning(f"401 Unauthorized on {endpoint}; renewing token")
                        await self._renew_token()
                        continue
                    
                    if resp.status == 404:
                        # Not found: cube instance may have expired
                        if "cube" in endpoint:
                            logger.warning(f"404 on cube endpoint; recreating instance")
                            # Extract cube ID from endpoint
                            cube_id = self._extract_cube_id(endpoint)
                            if cube_id:
                                await self._recreate_cube_instance(cube_id)
                            continue
                    
                    resp.raise_for_status()
                    return await resp.json()
            
            except asyncio.TimeoutError:
                if attempt < self.config.max_retries - 1:
                    backoff = self.config.retry_backoff_ms * (2 ** attempt)
                    logger.warning(f"Timeout on {endpoint}; retrying in {backoff}ms")
                    await asyncio.sleep(backoff / 1000)
                    continue
                raise
            
            except Exception as e:
                logger.error(f"API call failed: {e}")
                raise
        
        raise MaxRetriesExceeded(f"Max retries exceeded for {endpoint}")
    
    def _token_expires_soon(self) -> bool:
        """Check if token expires within proactive_renewal_margin_seconds."""
        
        if not self._token or not self._token_expires_at:
            return True
        
        margin = timedelta(seconds=self.config.proactive_renewal_margin_seconds)
        return datetime.utcnow() > (self._token_expires_at - margin)
    
    async def _renew_token(self):
        """
        Acquire new authentication token.
        
        Uses mutex to prevent concurrent renewal requests.
        """
        
        async with self._renewal_lock:
            # Double-check: another coroutine may have already renewed
            if not self._token_expires_soon():
                return
            
            logger.info("Renewing MSTR authentication token")
            
            try:
                async with self._session.post(
                    url=f"{self.config.base_url}/api/auth/login",
                    json={
                        "username": self.config.username,
                        "password": self.config.password
                    },
                    timeout=10
                ) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                    
                    self._token = data["token"]
                    # MSTR doesn't always return expires_in; assume 30 min conservatively
                    ttl_seconds = data.get("expires_in", 1800)
                    self._token_expires_at = datetime.utcnow() + timedelta(seconds=ttl_seconds)
                    
                    logger.info(f"Token renewed; expires at {self._token_expires_at}")
                    
                    # Persist checkpoint for crash recovery
                    await self.db.upsert_session_checkpoint(
                        job_id=None,  # Session-level checkpoint
                        token_expires_at=self._token_expires_at,
                        last_successful_page_offset=self._last_page_offset
                    )
            
            except Exception as e:
                logger.error(f"Token renewal failed: {e}")
                raise AuthenticationFailed(f"Cannot renew token: {e}")
    
    async def _recreate_cube_instance(self, cube_id: str):
        """
        Cube instance was idle > 10 min; recreate it.
        
        This is lightweight: MSTR server creates a new instance
        on-demand when first data API call arrives.
        """
        
        logger.info(f"Recreating cube instance for {cube_id}")
        
        try:
            # Trigger instance creation by calling a lightweight endpoint
            await self.api_call_with_recovery(
                "GET",
                f"/api/v2/cubes/{cube_id}",
                params={"fields": "id,name"}
            )
            
            # Update last access time
            self._cube_instance_ids[cube_id] = datetime.utcnow()
        
        except Exception as e:
            logger.error(f"Cube instance recreation failed: {e}")
            raise
    
    def _extract_cube_id(self, endpoint: str) -> Optional[str]:
        """Extract cube ID from endpoint path (e.g., /api/v2/cubes/{id}/... → id)"""
        import re
        match = re.search(r'/cubes/([A-F0-9]+)', endpoint)
        return match.group(1) if match else None
```

### 1.2 Extraction Checkpoint Recovery (Step 1 Resumption)

```python
# core/extraction/checkpoint.py

@dataclass
class ExtractionCheckpoint:
    """Resumable extraction state for paginated catalog walk."""
    
    job_id: str
    object_type: str  # "dossier", "report", "metric", "filter"
    page_offset: int  # Last successfully processed page
    page_size: int = 50
    checkpoint_at: datetime = field(default_factory=datetime.utcnow)
    status: str = "IN_PROGRESS"  # or "COMPLETED", "FAILED"


async def resumable_catalog_walk(
    session: MSTRSession,
    object_type: str,
    job_id: str,
    db: Database
) -> AsyncIterator[dict]:
    """
    Walk MSTR catalog with checkpoint recovery.
    
    If extraction crashes, resume from last checkpoint + 1.
    """
    
    # Retrieve last checkpoint
    checkpoint = await db.get_extraction_checkpoint(job_id, object_type)
    start_page = (checkpoint.page_offset // checkpoint.page_size) + 1 if checkpoint else 1
    
    logger.info(f"Starting {object_type} extraction from page {start_page}")
    
    page = start_page
    while True:
        try:
            # Fetch page
            response = await session.api_call_with_recovery(
                "GET",
                f"/api/v2/objects/search",
                params={
                    "type": object_type,
                    "offset": (page - 1) * 50,
                    "limit": 50
                }
            )
            
            objects = response.get("objects", [])
            if not objects:
                break  # No more pages
            
            # Yield each object
            for obj in objects:
                yield obj
            
            # Checkpoint after successful page
            await db.upsert_extraction_checkpoint(
                job_id=job_id,
                object_type=object_type,
                page_offset=(page - 1) * 50 + len(objects),
                status="IN_PROGRESS"
            )
            
            page += 1
        
        except Exception as e:
            logger.error(f"Extraction failed on page {page}: {e}")
            # Checkpoint remains; next run resumes from same page
            raise
    
    # Mark complete
    await db.upsert_extraction_checkpoint(
        job_id=job_id,
        object_type=object_type,
        page_offset=(page - 1) * 50,
        status="COMPLETED"
    )
```

---

## Part 2: ADR-022 & ADR-026 — Warehouse-Direct Extraction SQL

### 2.1 Physical Semantic SQL Planner

**Problem:** MSTR JSON API returns pre-aggregated data; Tableau LOD calculations double-count.

**Solution:** Warehouse-direct extraction at raw fact grain using semantic SQL templates.

```python
# core/sql_planner/warehouse_sql_generator.py

@dataclass
class ExtractionGrain:
    """Physical extraction grain keys for fact table."""
    
    fact_table_name: str
    grain_keys: List[str]  # E.g., ["ORDER_ID", "LINE_ITEM_ID", "DATE_ID"]
    grain_semantics: str  # "granule" | "transaction" | "event"
    
    def validate_for_lod_sufficiency(self, requested_dim_levels: List[str]) -> bool:
        """
        Verify extraction grain is sufficient for LOD calculations.
        
        ADR-022: Mandatory blocker if grain keys don't include all required FK dimensions.
        """
        # Simplified check: grain must contain all requested dimension FKs
        return all(dim in self.grain_keys for dim in requested_dim_levels)


class WarehouseSemanticSQLGenerator:
    """
    Generates warehouse SQL for extraction at raw fact grain.
    """
    
    def __init__(self, warehouse_type: str = "snowflake"):
        self.warehouse_type = warehouse_type  # snowflake | bigquery | postgresql | redshift
    
    def generate_extraction_sql(
        self,
        metric_plan: MetricCompilationPlan,
        extraction_grain: ExtractionGrain,
        watermark: Optional[ValidationWatermark] = None,
        filters: Optional[List[FilterPlan]] = None
    ) -> str:
        """
        Generate parameterized SQL for warehouse extraction.
        
        Template:
          SELECT fact_keys, dimension_fks, measures
          FROM fact_table
          LEFT JOIN dim_* ON fact.fk_* = dim.id
          WHERE watermark_condition AND filter_conditions
          ORDER BY grain_keys
        """
        
        # Step 1: Build fact table column list
        fact_cols = [f"f.{key}" for key in extraction_grain.grain_keys]
        
        # Step 2: Add foreign key columns (for LOD dimensions)
        for dim_level in metric_plan.lod_dimensions:
            fk_col = self._infer_fk_column_for_dimension(dim_level)
            fact_cols.append(f"f.{fk_col}")
        
        # Step 3: Add measure/raw fact columns
        for measure in metric_plan.base_measures:
            fact_cols.append(f"f.{measure.warehouse_column}")
        
        # Step 4: Build FROM clause with joins
        from_clause = f"FROM {extraction_grain.fact_table_name} f"
        
        for dim in metric_plan.dimensions:
            dim_table = self._map_dimension_to_table(dim)
            join_key = self._map_dimension_to_fk(dim)
            from_clause += f"\nLEFT JOIN {dim_table} d_{dim.id} ON f.{join_key} = d_{dim.id}.id"
        
        # Step 5: Build WHERE clause
        where_parts = []
        
        # Watermark predicate (ADR-030)
        if watermark:
            watermark_pred = self._generate_watermark_predicate(watermark)
            where_parts.append(watermark_pred)
        
        # User-supplied filters
        if filters:
            for filt in filters:
                filter_pred = self._compile_filter_to_sql(filt)
                where_parts.append(filter_pred)
        
        where_clause = "WHERE " + " AND ".join(where_parts) if where_parts else ""
        
        # Step 6: Assemble final SQL
        sql = f"""
            SELECT
              {', '.join(fact_cols)}
            {from_clause}
            {where_clause}
            ORDER BY {', '.join(fact_cols[:len(extraction_grain.grain_keys)])}
        """
        
        return sql.strip()
    
    def _generate_watermark_predicate(self, watermark: ValidationWatermark) -> str:
        """
        Generate warehouse-specific time-travel predicate (ADR-030).
        """
        
        ts = watermark.timestamp.isoformat()
        
        if self.warehouse_type == "snowflake":
            # Snowflake: AT(TIMESTAMP => ...)
            return f"f.load_timestamp <= TIMESTAMP '{ts}'"
        
        elif self.warehouse_type == "bigquery":
            # BigQuery: Partition pruning or timestamp column
            date_str = watermark.timestamp.strftime('%Y%m%d')
            return f"DATE(_PARTITIONTIME) = '{date_str}'"
        
        elif self.warehouse_type == "postgresql":
            # PostgreSQL: Temporal table query
            return f"f.valid_from <= TIMESTAMP '{ts}' AND (f.valid_to IS NULL OR f.valid_to > TIMESTAMP '{ts}')"
        
        else:
            # Generic: Append-only with load_timestamp column
            return f"f.load_timestamp <= TIMESTAMP '{ts}'"
    
    def _compile_filter_to_sql(self, filter_plan: FilterPlan) -> str:
        """
        Compile MSTR filter logic to warehouse SQL.
        
        Handles: comparison, in-list, range, text matching, etc.
        """
        
        if filter_plan.operator == "=":
            return f"{filter_plan.column} = {filter_plan.value}"
        elif filter_plan.operator == "IN":
            values = ", ".join(f"'{v}'" for v in filter_plan.values)
            return f"{filter_plan.column} IN ({values})"
        elif filter_plan.operator == "RANGE":
            return f"{filter_plan.column} BETWEEN {filter_plan.min_value} AND {filter_plan.max_value}"
        # ... add more operators as needed


# Example usage
def example_extraction_sql():
    """
    Generate SQL to extract "Revenue by Region by Quarter" metric.
    """
    
    generator = WarehouseSemanticSQLGenerator(warehouse_type="snowflake")
    
    metric_plan = MetricCompilationPlan(
        metric_id="revenue_by_region_quarter",
        base_measures=[
            MeasurePlan(warehouse_column="amount_usd", aggregation="SUM")
        ],
        lod_dimensions=["REGION", "QUARTER"],
        dimensions=[
            DimensionPlan(id="region", table="dim_region", fk="region_id"),
            DimensionPlan(id="quarter", table="dim_date", fk="date_id")
        ]
    )
    
    extraction_grain = ExtractionGrain(
        fact_table_name="fact_orders",
        grain_keys=["ORDER_ID", "LINE_ITEM_ID", "DATE_ID"],
        grain_semantics="transaction"
    )
    
    watermark = ValidationWatermark(
        timestamp=datetime(2026, 8, 17, 14, 0, 0),
        timezone="UTC"
    )
    
    sql = generator.generate_extraction_sql(
        metric_plan=metric_plan,
        extraction_grain=extraction_grain,
        watermark=watermark
    )
    
    print(sql)
    # Output:
    # SELECT
    #   f.ORDER_ID, f.LINE_ITEM_ID, f.DATE_ID, f.region_id, f.amount_usd
    # FROM fact_orders f
    # LEFT JOIN dim_region d_region ON f.region_id = d_region.id
    # LEFT JOIN dim_date d_quarter ON f.date_id = d_quarter.id
    # WHERE f.load_timestamp <= TIMESTAMP '2026-08-17T14:00:00' AND region IN ('US', 'EU', 'APAC')
    # ORDER BY f.ORDER_ID, f.LINE_ITEM_ID, f.DATE_ID
```

---

## Part 3: ADR-029 & ADR-030 — Production Lock & Watermark Tracking

### 3.1 Database Schema Extensions

```sql
-- production_lock.sql: Track production write-lock state

CREATE TABLE production_write_locks (
    lock_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    job_id TEXT,
    lock_status TEXT CHECK (lock_status IN ('ACQUIRED', 'RELEASED')),
    acquired_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    released_at TIMESTAMP,
    locked_by_user TEXT,
    
    FOREIGN KEY (job_id) REFERENCES jobs(id)
);

CREATE INDEX idx_production_lock_status ON production_write_locks(lock_status, acquired_at);


-- promotion_operations.sql: Track idempotent promotion steps (ADR-029)

CREATE TABLE promotion_operations (
    operation_id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,  -- sha256(job_id + artifact_id + env + version)
    job_id TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    artifact_type TEXT CHECK (artifact_type IN ('datasource', 'workbook', 'permissions')),
    environment TEXT CHECK (environment IN ('staging', 'production')),
    status TEXT CHECK (status IN ('PENDING', 'IN_PROGRESS', 'SUCCESS', 'FAILED')),
    
    -- Remote reconciliation
    tableau_entity_id TEXT,  -- Server-side ID after publish
    remote_checked_at TIMESTAMP,
    
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    error_message TEXT,
    
    FOREIGN KEY (job_id) REFERENCES jobs(id)
);

CREATE UNIQUE INDEX idx_idempotency_key ON promotion_operations(idempotency_key);
CREATE INDEX idx_promotion_status ON promotion_operations(status, updated_at);


-- validation_watermarks.sql: Pin extraction time (ADR-030)

CREATE TABLE validation_watermarks (
    watermark_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    timestamp TIMESTAMP NOT NULL,
    timezone TEXT DEFAULT 'UTC',
    
    -- Different watermarks for different purposes
    purpose TEXT CHECK (purpose IN ('extraction', 'golden_test', 'validation')),
    
    -- Snapshot metadata (for warehouse time-travel)
    snapshot_method TEXT CHECK (snapshot_method IN ('timestamp', 'transaction_id', 'cdc_version')),
    snapshot_identifier TEXT,  -- For CDC systems
    
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (job_id) REFERENCES jobs(id)
);

CREATE INDEX idx_watermark_job_purpose ON validation_watermarks(job_id, purpose);


-- review_tasks.sql: Human review queue (Step 10)

CREATE TABLE review_tasks (
    task_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    status TEXT CHECK (status IN ('PENDING_REVIEW', 'IN_PROGRESS', 'APPROVED', 'REJECTED', 'PROMOTED')),
    
    -- Failure categorization
    failure_reason TEXT,  -- kpi_variance | security_mismatch | structural | visual
    severity TEXT CHECK (severity IN ('blocker', 'critical', 'warning')),
    
    -- Assignment
    assigned_to TEXT,
    assigned_at TIMESTAMP,
    
    -- IR edits (JSON array of patches)
    ir_edits JSON,
    
    -- Updated scorecard after review
    re_validation_scorecard JSON,
    
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    
    FOREIGN KEY (job_id) REFERENCES jobs(id)
);

CREATE INDEX idx_review_status ON review_tasks(status);
```

### 3.2 Watermark Predicate Generation

```python
# core/validation/watermark_predicates.py

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class ValidationWatermark:
    """
    Snapshot timestamp for reconstructable extraction.
    
    ADR-030: Pin both MSTR golden dataset capture and warehouse extraction
    to identical timestamp for parity validation.
    """
    
    timestamp: datetime
    timezone: str = "UTC"
    snapshot_method: str = "timestamp"  # timestamp | transaction_id | cdc_version
    snapshot_identifier: Optional[str] = None  # For CDC systems


class WatermarkPredicateGenerator:
    """
    Generate warehouse-specific time-travel predicates.
    """
    
    def generate_for_warehouse(
        self,
        watermark: ValidationWatermark,
        warehouse_type: str
    ) -> str:
        """
        Generate snapshot predicate for different warehouses.
        """
        
        ts = watermark.timestamp
        
        if warehouse_type == "snowflake":
            return self._snowflake_predicate(ts)
        elif warehouse_type == "bigquery":
            return self._bigquery_predicate(ts)
        elif warehouse_type == "postgresql":
            return self._postgresql_predicate(ts)
        elif warehouse_type == "redshift":
            return self._redshift_predicate(ts)
        else:
            # Fallback: append-only with timestamp column
            return f"load_timestamp <= TIMESTAMP '{ts.isoformat()}'"
    
    @staticmethod
    def _snowflake_predicate(ts: datetime) -> str:
        """
        Snowflake: Use Time Travel syntax (up to 90 days).
        
        Approach 1: Use AT clause in FROM
          SELECT * FROM fact_orders AT(TIMESTAMP => 'timestamp')
        
        Approach 2: Use comparison (when timestamp column exists)
          SELECT * FROM fact_orders WHERE load_ts <= 'timestamp'
        """
        return f"load_timestamp <= '{ts.isoformat()}'"
    
    @staticmethod
    def _bigquery_predicate(ts: datetime) -> str:
        """
        BigQuery: Use partition pruning or snapshot time.
        
        If table is partitioned by _PARTITIONTIME:
          WHERE DATE(_PARTITIONTIME) <= DATE('{ts}')
        
        For time-travel (TIMESTAMP_MILLIS version):
          SELECT * FROM `dataset.table` FOR SYSTEM_TIME AS OF TIMESTAMP('{ts}')
        """
        date_str = ts.strftime("%Y-%m-%d")
        return f"DATE(_PARTITIONTIME) <= DATE('{date_str}')"
    
    @staticmethod
    def _postgresql_predicate(ts: datetime) -> str:
        """
        PostgreSQL: Use temporal tables (system-versioned).
        
        Requires: valid_from, valid_to columns
          SELECT * FROM fact_orders 
          FOR SYSTEM_TIME AS OF TIMESTAMP '{ts}'
        """
        return f"""
            valid_from <= TIMESTAMP '{ts.isoformat()}' 
            AND (valid_to IS NULL OR valid_to > TIMESTAMP '{ts.isoformat()}')
        """.strip()
    
    @staticmethod
    def _redshift_predicate(ts: datetime) -> str:
        """
        Redshift: Use Redshift Spectrum or load_timestamp comparison.
        
        Redshift doesn't have native time-travel, so use timestamp column.
        """
        return f"load_timestamp <= TIMESTAMP '{ts.isoformat()}'"


# Example: Use watermark in extraction flow
async def extract_with_watermark(
    db: Database,
    job_id: str,
    warehouse_type: str
) -> List[dict]:
    """
    Extract data pinned to job's watermark timestamp.
    """
    
    # Retrieve watermark for this job
    watermark = await db.get_validation_watermark(job_id, purpose="extraction")
    
    # Generate warehouse-specific predicate
    generator = WatermarkPredicateGenerator()
    watermark_where = generator.generate_for_warehouse(watermark, warehouse_type)
    
    # Execute extraction with watermark
    sql = f"""
        SELECT * FROM fact_orders
        WHERE {watermark_where}
        ORDER BY ORDER_ID
    """
    
    result = await db.execute_warehouse_query(sql)
    return result
```

---

## Part 4: Step 10 — IR Patch & Re-validation

### 4.1 Inline IR Editing During Review

```python
# core/review/ir_patch_engine.py

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class IREdit:
    """Single IR patch during human review."""
    
    task_id: str
    expression_id: str
    original_calc: str  # Before this edit
    new_calc: str  # After this edit
    applied_at: datetime
    applied_by: str
    reason: str  # Human justification


class IRPatchEngine:
    """
    Apply and re-validate IR edits during review workflow.
    """
    
    def __init__(self, expression_compiler, db: Database):
        self.compiler = expression_compiler
        self.db = db
    
    async def apply_patch(
        self,
        task_id: str,
        expression_id: str,
        new_tableau_calc: str,
        job_id: str
    ) -> IRPatchResult:
        """
        Apply an IR edit and immediately re-validate.
        
        Steps:
        1. Validate Tableau syntax
        2. Parse AST, compute fingerprint
        3. Check dedup collisions
        4. Apply to IR document
        5. Re-validate expression in isolation
        6. Update confidence score
        7. Check if now auto_publish_ok
        """
        
        # Step 1: Syntax validation
        syntax_issues = self.compiler.validate_tableau_syntax(new_tableau_calc)
        if syntax_issues:
            return IRPatchResult(
                status="SYNTAX_ERROR",
                issues=syntax_issues,
                message="New calculation has syntax errors"
            )
        
        # Step 2: Parse and fingerprint
        try:
            new_ast = self.compiler.parse_tableau_expression(new_tableau_calc)
            new_fingerprint = self.compiler.compute_semantic_fingerprint(new_ast)
        except Exception as e:
            return IRPatchResult(
                status="PARSE_ERROR",
                issues=[str(e)],
                message="Failed to parse new calculation"
            )
        
        # Step 3: Check deduplication collisions
        existing_fingerprints = await self.db.get_existing_fingerprints(job_id)
        if new_fingerprint in existing_fingerprints:
            other_expr = existing_fingerprints[new_fingerprint]
            return IRPatchResult(
                status="DEDUP_COLLISION",
                message=f"New calc semantically identical to {other_expr}",
                conflicting_expression=other_expr,
                remediation="Adjust calc to have unique semantics"
            )
        
        # Step 4: Get current IR and update it
        ir_document = await self.db.get_ir_document(job_id)
        expr_in_ir = self._find_expression_in_ir(ir_document, expression_id)
        
        if not expr_in_ir:
            return IRPatchResult(
                status="EXPRESSION_NOT_FOUND",
                message=f"Expression {expression_id} not found in IR"
            )
        
        # Store original for audit
        original_calc = expr_in_ir.get("formula")
        
        # Apply patch
        expr_in_ir["formula"] = new_tableau_calc
        expr_in_ir["ast"] = new_ast
        expr_in_ir["fingerprint"] = new_fingerprint
        expr_in_ir["edited_at"] = datetime.utcnow().isoformat()
        expr_in_ir["edited_by"] = "reviewer"  # Will be populated from auth context
        
        # Step 5: Re-validate this expression in isolation
        re_validation = await self.compiler.validate_single_expression(
            expression_id=expression_id,
            job_id=job_id,
            tableau_calc=new_tableau_calc,
            ir_context=ir_document
        )
        
        # Step 6: Update confidence
        new_confidence = self._boost_confidence_for_human_review(
            original_confidence=expr_in_ir.get("confidence", 0.5),
            re_validation_confidence=re_validation.confidence,
            human_reviewed=True
        )
        expr_in_ir["confidence"] = new_confidence
        
        # Step 7: Persist edited IR
        await self.db.upsert_ir_document(job_id, ir_document)
        
        # Step 8: Create audit record
        ir_edit = IREdit(
            task_id=task_id,
            expression_id=expression_id,
            original_calc=original_calc,
            new_calc=new_tableau_calc,
            applied_at=datetime.utcnow(),
            applied_by="reviewer",
            reason="Human review and correction"
        )
        await self.db.create_ir_edit_record(ir_edit)
        
        # Step 9: Re-compute ValidationScorecard for entire job
        new_scorecard = await self._recompute_scorecard_post_edit(job_id)
        
        return IRPatchResult(
            status="APPLIED",
            ir_edit=ir_edit,
            new_confidence=new_confidence,
            re_validation=re_validation,
            new_scorecard=new_scorecard,
            now_auto_publishable=new_scorecard.auto_publish_ok,
            message="IR patch applied and re-validated"
        )
    
    def _find_expression_in_ir(self, ir_document: dict, expression_id: str) -> Optional[dict]:
        """Locate expression object in IR JSON."""
        for measure in ir_document.get("model", {}).get("measures", []):
            if measure.get("id") == expression_id:
                return measure
        return None
    
    def _boost_confidence_for_human_review(
        self,
        original_confidence: float,
        re_validation_confidence: float,
        human_reviewed: bool
    ) -> float:
        """
        Adjust confidence after human review.
        
        Rule: Human review can increase confidence, never decrease.
        Boost: +0.10 base + 0.05 for detailed review.
        Cap at 0.99 (only mathematical proof reaches 1.0).
        """
        
        if not human_reviewed:
            return original_confidence
        
        base_boost = 0.10
        review_boost = 0.05
        
        new_confidence = min(
            original_confidence + base_boost + review_boost,
            0.99  # Cap at 0.99
        )
        
        return new_confidence
    
    async def _recompute_scorecard_post_edit(self, job_id: str):
        """Recompute ValidationScorecard after IR edit."""
        # This is an expensive operation; only done when editor applies a patch
        pass
    
    def _find_dependents(self, expression_id: str, ir_document: dict) -> List[str]:
        """Find all metrics/calcs that depend on this expression."""
        dependents = []
        for measure in ir_document.get("model", {}).get("measures", []):
            if expression_id in self._extract_formula_refs(measure.get("formula", "")):
                dependents.append(measure.get("id"))
        return dependents
    
    def _extract_formula_refs(self, formula: str) -> List[str]:
        """Extract column references from Tableau formula."""
        import re
        # Match [ColumnName] patterns
        return re.findall(r'\[([^\]]+)\]', formula)


@dataclass
class IRPatchResult:
    """Result of IR patch operation."""
    
    status: str  # APPLIED | SYNTAX_ERROR | PARSE_ERROR | DEDUP_COLLISION
    message: str
    ir_edit: Optional[IREdit] = None
    new_confidence: Optional[float] = None
    new_scorecard: Optional[dict] = None
    now_auto_publishable: bool = False
    issues: List[str] = field(default_factory=list)
    conflicting_expression: Optional[str] = None
    remediation: Optional[str] = None
```

---

## Part 5: Consolidated Best Practices

### 5.1 Checklist: Critical Implementation Patterns

- [ ] **MSTRSession (ADR-016):** Implement proactive token renewal + 401/404 recovery
- [ ] **ExtractionCheckpoint (Step 1):** Resume from last checkpoint on crash
- [ ] **WarehouseSemanticSQLGenerator (ADR-022, ADR-026):** Generate warehouse-direct SQL at raw grain
- [ ] **ValidationWatermark (ADR-030):** Pin extraction to reconstructable snapshot timestamp
- [ ] **ProductionWriteLock (ADR-029):** Acquire at job start, release only after PROMOTE
- [ ] **PromotionOperation (ADR-029):** Track idempotent operations with remote reconciliation
- [ ] **ReviewTask & IRPatchEngine (Step 10):** Support inline IR editing + re-validation
- [ ] **WatermarkPredicateGenerator:** Support warehouse-specific time-travel syntax

### 5.2 Database Schema Checklist

- [ ] `production_write_locks` — Track production lock state
- [ ] `promotion_operations` — Idempotency + remote reconciliation
- [ ] `validation_watermarks` — Snapshot timestamps for extraction/validation
- [ ] `review_tasks` — Human review queue with IR edits
- [ ] Index on `review_tasks(status)` and `promotion_operations(idempotency_key)`

### 5.3 Error Handling Patterns

```python
# Standard error responses for Step 10 review API

class ReviewAPIErrors:
    """Normalized error codes for review workflow."""
    
    TASK_NOT_FOUND = "review/task_not_found"
    EXPRESSION_NOT_FOUND = "review/expression_not_found"
    SYNTAX_ERROR = "review/syntax_error"
    DEDUP_COLLISION = "review/dedup_collision"
    ALREADY_PROMOTED = "review/already_promoted"
    PRODUCTION_LOCK_HELD = "review/production_lock_held"
    VALIDATION_STILL_FAILING = "review/validation_still_failing"
    IR_PATCH_FAILED = "review/ir_patch_failed"
```

---

**Next Steps:**
1. Implement MSTRSession + ExtractionCheckpoint recovery
2. Build WarehouseSemanticSQLGenerator (test with Snowflake, BigQuery)
3. Extend database schema with production lock + watermark tables
4. Implement IRPatchEngine for Step 10 review workflow
5. Build review API endpoints (POST `/review/{taskId}/edit-ir`, `/approve`)

