# SQL TEMPLATES & WAREHOUSE PATTERNS

**Companion to:** `IMPLEMENTATION-GUIDE.md`, Part 2 (ADR-022 & ADR-026)  
**Date:** 17 August 2026  
**Purpose:** Concrete SQL templates for warehouse-direct extraction at raw fact grain

---

## Overview

This document provides battle-tested SQL patterns for extracting data at raw fact grain (not pre-aggregated). These templates are used in **Step 3: Warehouse-Direct Physical SQL Compilation** and support the **12-field SemanticFingerprint** deduplication in Step 5.

---

## Part 1: Snowflake Patterns

### 1.1 Basic Fact Table Extraction with Grain Keys

**Scenario:** Extract "Revenue by Region by Quarter" metric from `FACT_ORDERS` at transaction grain.

```sql
-- Template: Basic fact extraction with grain keys + dimension FKs

SELECT
    f.ORDER_ID,
    f.LINE_ITEM_ID,
    f.ORDER_DATE_ID,
    
    -- Dimension FKs (for LOD dimensions)
    f.REGION_ID,
    f.QUARTER_ID,
    
    -- Measures
    f.AMOUNT_USD,
    f.QUANTITY,
    f.DISCOUNT_AMOUNT
    
FROM FACT_ORDERS f

WHERE 
    -- Watermark predicate (ADR-030)
    f.LOAD_TIMESTAMP <= TIMESTAMP '2026-08-17 14:00:00'
    
    -- Optional: User-supplied filter (only recent orders)
    AND f.ORDER_DATE_ID >= (SELECT DATE_ID FROM DIM_DATE WHERE FISCAL_YEAR = 2026)

ORDER BY 
    f.ORDER_ID, 
    f.LINE_ITEM_ID, 
    f.ORDER_DATE_ID

-- Note: No GROUP BY — return raw rows for Tableau LOD calculations
```

**Key Design Decisions:**
- ✅ `ORDER BY` on grain keys ensures deterministic ordering (watermark pinning)
- ✅ No `GROUP BY`: Tableau will aggregate via LOD in dashboards
- ✅ Watermark predicate ensures snapshot consistency (ADR-030)
- ✅ Include all grain keys even if not in final viz (supports LOD drill-down)

---

### 1.2 Fact Table with Heterogeneous Grain (ADR-032)

**Scenario:** Multiple facts with different grains (orders at line level, shipments at package level).

```sql
-- Template: Logical relationships for heterogeneous grain isolation

-- Fact 1: Orders (line-item grain)
CREATE TEMP TABLE FACT_ORDERS_GRAIN AS
SELECT
    f.ORDER_ID,
    f.LINE_ITEM_ID,
    f.ORDER_DATE_ID,
    f.REGION_ID,
    f.AMOUNT_USD,
    1 as LINE_COUNT
FROM FACT_ORDERS f
WHERE f.LOAD_TIMESTAMP <= TIMESTAMP '2026-08-17 14:00:00';

-- Fact 2: Shipments (package grain)
CREATE TEMP TABLE FACT_SHIPMENTS_GRAIN AS
SELECT
    s.SHIPMENT_ID,
    s.PACKAGE_NUMBER,
    s.SHIP_DATE_ID,
    s.REGION_ID,
    s.WEIGHT_KG,
    1 as PACKAGE_COUNT
FROM FACT_SHIPMENTS s
WHERE s.LOAD_TIMESTAMP <= TIMESTAMP '2026-08-17 14:00:00';

-- Do NOT join on partial keys (ADR-032)
-- Instead, use Tableau logical relationships to join via Order ↔ Shipment

-- Export each grain separately to Hyper
-- Tableau will handle multi-grain aggregations via LOD

-- For visualization: Orders can have "# Packages" measure via COUNTD([Shipment.PackageNumber])
-- No double-counting because relationships enforce proper aggregation levels
```

**Why separate extraction by grain:**
- ✅ Prevents spurious joins on partial keys
- ✅ Each fact extracted at its natural grain
- ✅ Tableau's many-to-many logical relationships handle grain differences
- ⚠️ Requires Tableau Server 2020.2+ for logical relationships

---

### 1.3 Transformation Table Materialization

**Scenario:** MSTR has a transformation table (e.g., `Currency_Rate_Lookup`); must be materialized in Hyper.

```sql
-- Template: Materialized transformation table

SELECT
    t.EFFECTIVE_DATE_ID,
    t.FROM_CURRENCY_CODE,
    t.TO_CURRENCY_CODE,
    t.EXCHANGE_RATE,
    t.DATA_SOURCE,
    
    -- Add load timestamp for reproducibility
    CURRENT_TIMESTAMP() as EXTRACTED_AT

FROM TRANSFORMATION_TABLES.CURRENCY_RATE_LOOKUP t

WHERE 
    t.LOAD_TIMESTAMP <= TIMESTAMP '2026-08-17 14:00:00'

ORDER BY 
    t.EFFECTIVE_DATE_ID,
    t.FROM_CURRENCY_CODE,
    t.TO_CURRENCY_CODE
```

**When to materialize vs. use LOOKUP():**
| Pattern | Recommendation | Confidence |
|---------|-----------------|-----------|
| Transformation (< 100k rows) | Materialize | 0.99 |
| Reference table (< 10k rows) | Materialize | 0.99 |
| Slowly changing dimension (< 1M rows) | Materialize | 0.95 |
| Large lookup (> 1M rows) | Use LOOKUP() + fallback | 0.70 |

---

### 1.4 Watermark-Pinned Snapshot (ADR-030)

**Scenario:** Extract data at exact watermark timestamp for parity validation.

```sql
-- Template: Snowflake Time Travel (stream from historical state)

-- Option 1: Use AT clause (native Snowflake Time Travel)
SELECT
    f.ORDER_ID,
    f.LINE_ITEM_ID,
    f.AMOUNT_USD
FROM FACT_ORDERS AT(TIMESTAMP => '2026-08-17 14:00:00'::TIMESTAMP_NTZ) f
WHERE f.IS_ACTIVE = TRUE

-- Option 2: Use load_timestamp column (if actual snapshot not available)
SELECT
    f.ORDER_ID,
    f.LINE_ITEM_ID,
    f.AMOUNT_USD
FROM FACT_ORDERS f
WHERE f.LOAD_TIMESTAMP <= TIMESTAMP '2026-08-17 14:00:00'
ORDER BY f.ORDER_ID

-- Snowflake Time Travel requirements:
-- ✅ Retention period >= 90 days
-- ✅ Table not dropped/truncated after snapshot time
-- ✅ Supply TIMESTAMP in NTZ (no timezone)
```

---

### 1.5 Filter Predicate Compilation (MSTR → SQL)

**Scenario:** MSTR has filter "Region IN ('US', 'EU') AND Quarter = Q3-2026".

```sql
-- Template: Compiled filter predicate

SELECT
    f.ORDER_ID,
    f.LINE_ITEM_ID,
    f.AMOUNT_USD,
    r.REGION_NAME,
    q.QUARTER_NAME
    
FROM FACT_ORDERS f
JOIN DIM_REGION r ON f.REGION_ID = r.REGION_ID
JOIN DIM_QUARTER q ON f.QUARTER_ID = q.QUARTER_ID

WHERE 
    -- ADR-030: Watermark predicate
    f.LOAD_TIMESTAMP <= TIMESTAMP '2026-08-17 14:00:00'
    
    -- Compiled from MSTR filter: Region IN ('US', 'EU')
    AND r.REGION_NAME IN ('United States', 'European Union')
    
    -- Compiled from MSTR filter: Quarter = Q3-2026
    AND q.FISCAL_YEAR = 2026
    AND q.QUARTER_NUM = 3
    
    -- Best practice: Push filters to join ON clause for efficiency
    -- (But WHERE clause works; Snowflake optimizer handles both)

ORDER BY f.ORDER_ID, f.LINE_ITEM_ID
```

---

## Part 2: BigQuery Patterns

### 2.1 Partitioned Table Extraction

**Scenario:** `fact_orders` is partitioned by date; extract Q3 2026.

```sql
-- Template: BigQuery partitioned table with date range

SELECT
    f.ORDER_ID,
    f.LINE_ITEM_ID,
    f.AMOUNT_USD
    
FROM `project.dataset.fact_orders` f

WHERE 
    -- ADR-030: Partition pruning for snapshot date
    DATE(_PARTITIONTIME) >= '2026-07-01'
    AND DATE(_PARTITIONTIME) <= '2026-09-30'
    
    -- Additional filter predicates
    AND f.REGION_ID IN (1, 2)  -- US, EU

-- BigQuery cost optimization:
-- ✅ _PARTITIONTIME filter executes BEFORE scanning table
-- ✅ Reduces scanned bytes (lower query cost)
-- ⚠️ If watermark is within same partition, use load_timestamp column

ORDER BY f.ORDER_ID, f.LINE_ITEM_ID
```

### 2.2 BigQuery Snapshot Time (TIMESTAMP_VERSION)

**Scenario:** Use BigQuery snapshot time for exact parity validation.

```sql
-- BigQuery doesn't have native Time Travel like Snowflake,
-- but can use TIMESTAMP_VERSION for CDC tables

SELECT
    f.ORDER_ID,
    f.LINE_ITEM_ID,
    f.AMOUNT_USD
    
FROM `project.dataset.fact_orders` f

-- BigQuery CDC (Change Data Capture) via Dataflow export
WHERE 
    -- Snapshot at specific version
    _change_version <= TIMESTAMP '2026-08-17T14:00:00Z'
    
    -- Only active records
    AND _change_type != 'DELETE'

ORDER BY f.ORDER_ID, f.LINE_ITEM_LINE_ITEM_ID
```

---

## Part 3: PostgreSQL & Redshift Patterns

### 3.1 PostgreSQL Temporal Table Query

**Scenario:** Extract from system-versioned temporal table.

```sql
-- Template: PostgreSQL temporal table (valid_from / valid_to)

SELECT
    f.ORDER_ID,
    f.LINE_ITEM_ID,
    f.AMOUNT_USD
    
FROM public.fact_orders AS f
FOR SYSTEM_TIME AS OF TIMESTAMP '2026-08-17 14:00:00'

WHERE 
    f.REGION_ID IN (1, 2)

ORDER BY f.ORDER_ID, f.LINE_ITEM_ID;

-- Alternative (if FOR SYSTEM_TIME not supported):
SELECT
    f.ORDER_ID,
    f.LINE_ITEM_ID,
    f.AMOUNT_USD
    
FROM public.fact_orders f

WHERE 
    -- Manual temporal range query
    f.valid_from <= TIMESTAMP '2026-08-17 14:00:00'
    AND (f.valid_to IS NULL OR f.valid_to > TIMESTAMP '2026-08-17 14:00:00')
    
    AND f.REGION_ID IN (1, 2)

ORDER BY f.ORDER_ID, f.LINE_ITEM_ID;
```

### 3.2 Redshift Spectrum + S3 Snapshot

**Scenario:** Extract from Redshift Spectrum external table on S3.

```sql
-- Template: Redshift Spectrum with partition pruning

SELECT
    f.ORDER_ID,
    f.LINE_ITEM_ID,
    f.AMOUNT_USD
    
FROM spectrum.fact_orders_s3 f

WHERE 
    -- S3 partition key (typically dt=YYYY-MM-DD)
    f.dt BETWEEN '2026-07-01' AND '2026-09-30'
    
    -- Watermark on local timestamp
    AND f.LOAD_TIMESTAMP <= TIMESTAMP '2026-08-17 14:00:00'
    
    AND f.REGION_ID IN (1, 2)

ORDER BY f.ORDER_ID, f.LINE_ITEM_ID;
```

---

## Part 4: Append-Only Data Lake Patterns

### 4.1 Generic Append-Only with load_timestamp

**Scenario:** Data lake without native time-travel; use load_timestamp column.

```sql
-- Template: Append-only warehouse with load_timestamp

SELECT
    f.ORDER_ID,
    f.LINE_ITEM_ID,
    f.AMOUNT_USD,
    
    -- Include load_timestamp for audit trail
    f.LOAD_TIMESTAMP,
    
    -- Row number to identify duplicates (if any)
    ROW_NUMBER() OVER (
        PARTITION BY f.ORDER_ID, f.LINE_ITEM_ID 
        ORDER BY f.LOAD_TIMESTAMP DESC
    ) as RN
    
FROM fact_orders f

WHERE 
    -- ADR-030: Snapshot to watermark timestamp
    f.LOAD_TIMESTAMP <= TIMESTAMP '2026-08-17 14:00:00'
    
    AND f.REGION_ID IN (1, 2)

-- Get most recent version of each record as of watermark
QUALIFY RN = 1

ORDER BY f.ORDER_ID, f.LINE_ITEM_ID;
```

**Assumption:** If record appears twice with different load_timestamps, use most recent before watermark.

---

## Part 5: Complex Scenarios

### 5.1 Multi-Fact Join with Grain Sufficiency Check

**Scenario:** Join Orders (line-item) with Shipments (package) safely.

```sql
-- Template: Safe multi-fact join using logical relationships

-- Step 1: Extract Orders at line-item grain
WITH ORDERS_GRAIN AS (
    SELECT
        o.ORDER_ID,
        o.LINE_ITEM_ID,
        o.REGION_ID,
        o.QUARTER_ID,
        o.AMOUNT_USD,
        1 as ORDER_LINE_COUNT
    FROM FACT_ORDERS o
    WHERE o.LOAD_TIMESTAMP <= TIMESTAMP '2026-08-17 14:00:00'
),

-- Step 2: Extract Shipments at package grain
SHIPMENTS_GRAIN AS (
    SELECT
        s.SHIPMENT_ID,
        s.PACKAGE_NUMBER,
        s.ORDER_ID,  -- FK to order
        s.REGION_ID,
        s.WEIGHT_KG,
        1 as PACKAGE_COUNT
    FROM FACT_SHIPMENTS s
    WHERE s.LOAD_TIMESTAMP <= TIMESTAMP '2026-08-17 14:00:00'
)

-- Step 3: NO JOIN HERE — export separately to Hyper
-- Step 4: Tableau uses many-to-many logical relationship (Order ↔ Shipment)
-- Step 5: LOD expressions handle grain mismatch

SELECT * FROM ORDERS_GRAIN
UNION ALL
SELECT 
    NULL::INT as ORDER_ID,
    NULL::INT as LINE_ITEM_ID,
    REGION_ID,
    NULL::INT as QUARTER_ID,
    NULL::NUMERIC as AMOUNT_USD,
    NULL::INT as ORDER_LINE_COUNT
FROM SHIPMENTS_GRAIN;
```

**Why NO physical join in SQL:**
- ✅ Each fact maintains its natural grain
- ✅ Prevents spurious row multiplication
- ✅ Tableau many-to-many relationships handle aggregation correctly
- ⚠️ Requires Tableau Server 2020.2+ and LOD expertise

---

### 5.2 Slowly Changing Dimension (SCD) Type 2

**Scenario:** Extract Customer dimension with SCD Type 2 (valid_from / valid_to).

```sql
-- Template: SCD Type 2 dimension as of watermark date

SELECT
    c.CUSTOMER_ID,
    c.CUSTOMER_NAME,
    c.SEGMENT,
    c.COUNTRY,
    c.SCD_VERSION,
    c.VALID_FROM,
    c.VALID_TO
    
FROM DIM_CUSTOMER c

WHERE 
    -- Get version active as of watermark
    c.VALID_FROM <= TIMESTAMP '2026-08-17 14:00:00'
    AND (c.VALID_TO IS NULL OR c.VALID_TO > TIMESTAMP '2026-08-17 14:00:00')

ORDER BY c.CUSTOMER_ID, c.SCD_VERSION;

-- Note: If customer changed multiple times, extract ALL versions
-- Tableau can use EXCLUDE LOD to ignore dimension changes
-- Example: SUM([Amount]) EXCLUDE [Customer.Country] aggregates across all versions
```

---

## Part 6: Extraction Grain Validation Checklist

**Before running extraction SQL, verify:**

```python
def validate_extraction_grain(
    metric_plan: MetricCompilationPlan,
    extraction_grain: ExtractionGrain,
    fact_table_schema: Dict[str, str]  # column_name → sql_type
) -> GrainValidationResult:
    """
    ADR-022: Mandatory blocker if extraction grain is insufficient.
    """
    
    # Checklist 1: All grain keys exist in fact table
    for grain_key in extraction_grain.grain_keys:
        if grain_key not in fact_table_schema:
            return GrainValidationResult(
                valid=False,
                blocker=True,
                message=f"Grain key {grain_key} not found in fact table schema"
            )
    
    # Checklist 2: All LOD dimension FKs are in grain or joinable
    for lod_dim in metric_plan.lod_dimensions:
        dim_fk = infer_fk_for_dimension(lod_dim)
        if dim_fk not in extraction_grain.grain_keys and dim_fk not in fact_table_schema:
            return GrainValidationResult(
                valid=False,
                blocker=True,
                message=f"LOD dimension {lod_dim} requires FK {dim_fk} not in grain"
            )
    
    # Checklist 3: No redundant grain keys (e.g., both ORDER_ID and ORDER_LINE_ID if order is never sliced)
    # (Warning only; not a blocker)
    
    return GrainValidationResult(
        valid=True,
        blocker=False,
        message="Extraction grain is sufficient for all LOD calculations"
    )
```

---

## Part 7: Query Performance Optimization

### 7.1 Predicate Pushdown Pattern

```sql
-- ❌ INEFFICIENT: Large join before filter
SELECT f.*, d.REGION_NAME
FROM FACT_ORDERS f
JOIN DIM_REGION d ON f.REGION_ID = d.REGION_ID
WHERE d.REGION_NAME = 'United States'

-- ✅ EFFICIENT: Filter before join
SELECT f.*, d.REGION_NAME
FROM FACT_ORDERS f
JOIN DIM_REGION d ON f.REGION_ID = d.REGION_ID AND d.REGION_NAME = 'United States'
-- or
WHERE f.REGION_ID = (SELECT REGION_ID FROM DIM_REGION WHERE REGION_NAME = 'United States')
```

### 7.2 Partition Pruning Pattern

```sql
-- Always include partition key in WHERE clause early
SELECT * FROM fact_orders f
WHERE 
    -- Partition pruning FIRST (reduces scanned bytes)
    DATE(_PARTITIONTIME) >= '2026-07-01'
    
    -- Then other filters
    AND f.REGION_ID IN (1, 2)
    AND f.AMOUNT_USD > 1000
```

### 7.3 Aggregation Spillover Prevention

```sql
-- If fact table is large, aggregate WITHIN warehouse before export to Hyper
-- (Hyper handles raw rows fine; but massive pre-agg helps export speed)

-- Option 1: Raw grain (Tableau LODs)
SELECT ORDER_ID, LINE_ITEM_ID, AMOUNT_USD FROM fact_orders  -- 100M rows

-- Option 2: Pre-aggregated daily (if interactive latency is concern)
SELECT 
    DATE(ORDER_DATE),
    REGION_ID,
    SUM(AMOUNT_USD) as AMOUNT_USD,
    COUNT(*) as ORDER_COUNT
FROM fact_orders
GROUP BY DATE(ORDER_DATE), REGION_ID  -- 10k rows
```

---

## Part 8: Testing & Validation

### 8.1 Row Count Parity Test

```sql
-- Verify extraction produces expected row counts

WITH EXTRACTED_ROWS AS (
    SELECT COUNT(*) as extracted_count FROM fact_orders
    WHERE LOAD_TIMESTAMP <= TIMESTAMP '2026-08-17 14:00:00'
),

EXPECTED_ROWS AS (
    SELECT 1234567 as expected_count  -- From MSTR golden dataset
)

SELECT
    e.extracted_count,
    x.expected_count,
    CASE 
        WHEN e.extracted_count = x.expected_count THEN 'PASS'
        ELSE 'FAIL'
    END as status,
    ABS(e.extracted_count - x.expected_count) as variance
    
FROM EXTRACTED_ROWS e
CROSS JOIN EXPECTED_ROWS x
```

### 8.2 Null Value Audit

```sql
-- Verify VLDB null_propagation setting is respected

SELECT
    COUNT(*) as total_rows,
    COUNT(CASE WHEN AMOUNT_USD IS NULL THEN 1 END) as null_amount_count,
    ROUND(100.0 * COUNT(CASE WHEN AMOUNT_USD IS NULL THEN 1 END) / COUNT(*), 2) as null_pct
    
FROM fact_orders

WHERE LOAD_TIMESTAMP <= TIMESTAMP '2026-08-17 14:00:00'

-- Expected: If VLDB says "ignore nulls", count should be 0 or < 0.1%
-- Blocker if: Null count is unexpectedly high
```

---

**Appendix: SQL Template Quick Reference**

| Warehouse | Watermark Pattern | Grain Isolation | Partition Pruning |
|-----------|-------------------|-----------------|-------------------|
| **Snowflake** | `TIMESTAMP ≤` or `AT()` | Separate CTEs | Automatic clustering |
| **BigQuery** | `_PARTITIONTIME ≤` or CDC version | Separate `SELECT * UNION` | `DATE(_PARTITIONTIME)` |
| **PostgreSQL** | `FOR SYSTEM_TIME` or `valid_from/to` | Separate queries | Manual indexes |
| **Redshift** | `Spectrum` or `LOAD_TIMESTAMP ≤` | Separate queries | S3 partition keys |
| **Append-only** | `LOAD_TIMESTAMP ≤` with `ROW_NUMBER()` | Separate queries | Index on `LOAD_TIMESTAMP` |

