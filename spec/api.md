# API Specification — mstr-tableau-migrator

**Companion to:** `architecture.md`, `agents.md`  
**Date:** 17 August 2026  
**Base URL:** `http://localhost:8000/api/v1`  

---

## Authentication

MVP uses a simple API key header for backend access. Tableau Server and MSTR credentials are stored in `.env` / environment variables.

```
X-API-Key: {configured_api_key}
```

---

## 1. Connection Management

### 1.1 Test MSTR Connection

```
POST /connections/mstr/test
```

**Request Body:**
```json
{
  "base_url": "https://env-xxxxx.customer.cloud.microstrategy.com/MicroStrategyLibrary",
  "username": "mstr_service_account",
  "password": "********"
}
```

**Response (200):**
```json
{
  "status": "connected",
  "server_version": "2024.0402.0200",
  "project_count": 3,
  "projects": [
    {"id": "B7CA92F04B9FAE8D941C3E9B7E0CD754", "name": "MicroStrategy Tutorial"},
    {"id": "AF08BF5A11D3E48E1000E787EC6DE8A4", "name": "Sales Analytics"}
  ],
  "capabilities": {
    "dossier_definition_api": true,
    "modeling_attribute_forms": true,
    "vldb_settings_api": true,
    "transformation_tables_api": true,
    "lineage_graph_api": true,
    "json_data_api_v2": true,
    "migration_ready": true
  }
}
```

**Response (401):**
```json
{
  "status": "error",
  "message": "Authentication failed: invalid credentials"
}
```

---

### 1.2 Test Tableau Server Connection

```
POST /connections/tableau/test
```

**Request Body:**
```json
{
  "server_url": "https://tableau.company.com",
  "site_id": "default",
  "token_name": "migration-tool",
  "token_value": "********"
}
```

**Response (200):**
```json
{
  "status": "connected",
  "server_version": "2024.2.5",
  "site_name": "Default",
  "project_count": 12,
  "version_compatible": true,
  "auth_type": "active_directory",
  "min_required_version": "2020.2",
  "max_supported_template_version": "2024.2"
}
```

> **Audit v2 (ADR-024):** The connection test **must** validate `server_version >= 2020.2`. Logical relationship models (ADR-004/021) are required for the migration pipeline and are not supported on older servers. If the version check fails, the response includes `"version_compatible": false` and job creation is blocked.

> **Audit v4 (Validation Rule 17):** The connection test returns `max_supported_template_version`. `POST /jobs` enforces `template_version <= server_version`. Attempting to use a newer template version (e.g. `2025.1` template targeting `2024.2` server) is rejected with a 400 error.

> **Audit v2/v4 (ADR-031 — Auth Type):** `auth_type` is captured for auditing, but RLS predicates key strictly on `USERNAME()` with delimiter wrapping.

**Response (400 — Version Incompatible):**
```json
{
  "status": "error",
  "message": "Tableau Server version 2019.4.3 is below minimum required 2020.2. Logical relationship models are not supported.",
  "server_version": "2019.4.3",
  "version_compatible": false
}
```

### 1.3 Test Warehouse Connection (Audit v3 Addition)

```
POST /connections/warehouse/test
```

**Request Body:**
```json
{
  "connection_ref": "warehouse-prod-01",
  "warehouse_type": "sqlserver",
  "host": "dw-sql01.internal.company.com",
  "database": "SALES_DW",
  "schema": "dbo"
}
```

**Response (200):**
```json
{
  "status": "connected",
  "database_type": "Microsoft SQL Server 2022",
  "table_count": 48,
  "accessible": true
}
```

### 1.4 Pre-Job Dossier Discovery Scan

```
POST /discovery/dossiers
```

**Purpose:** Lightweight scan endpoint for the interactive UI wizard. Returns all dossiers within an MSTR project with basic structural metadata without initiating a migration job.

**Request Body:**
```json
{
  "base_url": "https://env-xxxxx.customer.cloud.microstrategy.com/MicroStrategyLibrary",
  "username": "mstr_service_account",
  "password": "********",
  "project_id": "B7CA92F04B9FAE8D941C3E9B7E0CD754",
  "folder_filter": null
}
```

**Response (200):**
```json
{
  "project_id": "B7CA92F04B9FAE8D941C3E9B7E0CD754",
  "project_name": "Sales Analytics",
  "dossier_count": 3,
  "dossiers": [
    {
      "id": "D0551E8045F075DFE0540003BA123456",
      "name": "Executive Sales Overview",
      "path": "/Shared Reports/Executive",
      "chapter_count": 4,
      "page_count": 8,
      "visualization_count": 14,
      "dataset_count": 2,
      "dataset_names": ["Sales Performance Cube", "Regional Targets"],
      "modified_at": "2026-08-10T09:15:00Z"
    },
    {
      "id": "E1662F9146G186EGF1651114CB234567",
      "name": "Regional KPI Dashboard",
      "path": "/Shared Reports/Regional",
      "chapter_count": 3,
      "page_count": 5,
      "visualization_count": 9,
      "dataset_count": 1,
      "dataset_names": ["Regional Performance Cube"],
      "modified_at": "2026-08-12T14:30:00Z"
    },
    {
      "id": "F2773A0257H297FHA2762225DC345678",
      "name": "Marketing Campaign ROI",
      "path": "/Shared Reports/Marketing",
      "chapter_count": 6,
      "page_count": 12,
      "visualization_count": 18,
      "dataset_count": 3,
      "dataset_names": ["Marketing Leads", "Spend by Channel", "Conversions"],
      "modified_at": "2026-08-15T11:00:00Z"
    }
  ]
}
```

---

## 2. Migration Jobs

### 2.1 Create Migration Job

```
POST /jobs
```

**Request Body:**
```json
{
  "name": "Q3 2026 Sales Migration",
  "mstr": {
    "base_url": "https://env-xxxxx.customer.cloud.microstrategy.com/MicroStrategyLibrary",
    "username": "mstr_service_account",
    "password": "********",
    "project_id": "B7CA92F04B9FAE8D941C3E9B7E0CD754"
  },
  "tableau": {
    "server_url": "https://tableau.company.com",
    "site_id": "default",
    "token_name": "migration-tool",
    "token_value": "********",
    "target_project": "Migrated from MSTR"
  },
  "warehouse": {
    "connection_ref": "warehouse-prod-01",
    "default_schema": "dbo"
  },
  "validation_watermark": "2026-08-17T14:00:00Z",
  "security_test_identities": [
    {"username": "mgr_east", "expected_regions": ["East"]},
    {"username": "mgr_west", "expected_regions": ["West"]},
    {"username": "admin_user", "expected_regions": ["*"]}
  ],
  "entitlement_datasource_mode": "locked_separate_datasource",
  "options": {
    "template_version": "2024.2",
    "datasource_scope": "project",
    "skip_unused_objects": true,
    "extract_data": true,
    "auto_publish": true,
    "publish_mode": "partial",
    "numeric_threshold": 0.98,
    "scope": {
      "object_types": ["dossier", "report", "metric", "attribute", "fact", "cube"],
      "folder_filter": null,
      "specific_object_ids": null
    }
  }
}
```

**Response (202):**
```json
{
  "job_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "PENDING",
  "created_at": "2026-08-17T14:30:00Z",
  "message": "Migration job queued"
}
```

---

### 2.2 Get Job Status

```
GET /jobs/{job_id}
```

**Response (200):**
```json
{
  "job_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "name": "Q3 2026 Sales Migration",
  "status": "PROMOTING",
  "progress": {
    "current_stage": "PROMOTE",
    "current_wave": 4,
    "total_waves": 4,
    "stages_completed": ["DISCOVERY", "GRAPH", "SEMANTIC_WAVES", "HYPER_BUILD", "STAGING_VALIDATE"],
    "objects_processed": 187,
    "objects_total": 187,
    "objects_succeeded": 170,
    "objects_failed": 2,
    "objects_blocked": 5,
    "objects_skipped": 10
  },
  "validation": {
    "security_confidence": 1.0,
    "security_parity": true,
    "financial_kpi_confidence": 0.995,
    "structural_confidence": 1.0,
    "visual_confidence": 0.91,
    "blocker_issues": 0,
    "mandatory_review_flags": 0,
    "auto_publish_ok": true
  },
  "review_queue_count": 5,
  "created_at": "2026-08-17T14:30:00Z",
  "started_at": "2026-08-17T14:30:05Z",
  "completed_at": null,
  "duration_seconds": 342
}
```

---

### 2.3 List All Jobs

```
GET /jobs?status={status}&limit={limit}&offset={offset}
```

**Query Parameters:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `status` | string | (all) | Filter: PENDING, RUNNING, COMPLETE, FAILED |
| `limit` | int | 20 | Page size |
| `offset` | int | 0 | Page offset |

**Response (200):**
```json
{
  "jobs": [...],
  "total": 5,
  "limit": 20,
  "offset": 0
}
```

---

### 2.4 Cancel Job

```
POST /jobs/{job_id}/cancel
```

**Response (200):**
```json
{
  "job_id": "...",
  "status": "CANCELLED",
  "message": "Job cancelled. Artifacts from completed stages are preserved."
}
```

---

### 2.5 Resume Job from Checkpoint (Audit Addition)

```
POST /jobs/{job_id}/resume
```

Resumes a failed or cancelled migration job from the last recorded stage/wave checkpoint (ADR-016), reusing completed extraction and IR compilation artifacts.

**Request Body (Optional):**
```json
{
  "force_stage": null    // string | null - e.g. "HYPER_WAVE_2" to force re-run from a specific stage
}
```

**Response (200):**
```json
{
  "job_id": "a1b2c3d4...",
  "status": "RESUMED",
  "resumed_from_stage": "HYPER_WAVE_2",
  "checkpoint_info": {
    "waves_completed": [1],
    "cubes_extracted": 3,
    "last_checkpoint_at": "2026-08-17T15:20:10Z"
  }
}
```

---

### 2.6 Get Extraction & Wave Checkpoints (Audit Addition)

```
GET /jobs/{job_id}/checkpoints
```

**Response (200):**
```json
{
  "job_id": "a1b2c3d4...",
  "current_stage": "HYPER_WAVE_2",
  "checkpoints": [
    {
      "object_id": "28B7F04A4F89C3E45721F...",
      "object_name": "Sales Cube",
      "page_offset": 50000,
      "rows_written": 50000,
      "completed": true,
      "updated_at": "2026-08-17T15:15:30Z"
    },
    {
      "object_id": "39C8F15B5F90D4F56832G...",
      "object_name": "Inventory Cube",
      "page_offset": 20000,
      "rows_written": 20000,
      "completed": false,
      "updated_at": "2026-08-17T15:18:45Z"
    }
  ]
}
```

---

## 3. Object Catalog

### 3.1 List Discovered Objects

```
GET /jobs/{job_id}/objects?type={type}&status={status}&search={search}
```

**Query Parameters:**
| Param | Type | Description |
|-------|------|-------------|
| `type` | string | Filter by MSTR type: metric, attribute, dossier, report, cube, fact, filter |
| `status` | string | Filter: extracted, compiled, published, failed, skipped, review |
| `search` | string | Search by name |
| `limit` | int | Page size (default 50) |
| `offset` | int | Page offset |

**Response (200):**
```json
{
  "objects": [
    {
      "mstr_id": "28B7F04A4F89C3E45721F...",
      "name": "Revenue",
      "type": "metric",
      "path": "/Public Objects/Metrics/Sales/",
      "status": "compiled",
      "confidence": 0.95,
      "issues": [],
      "tableau_id": null,
      "tableau_field": "Revenue"
    }
  ],
  "total": 187,
  "by_status": {
    "extracted": 187,
    "compiled": 175,
    "published": 140,
    "failed": 8,
    "skipped": 12,
    "review": 15
  }
}
```

---

### 3.2 Get Object Detail

```
GET /jobs/{job_id}/objects/{mstr_id}
```

**Response (200):**
```json
{
  "mstr_id": "28B7F04A4F89C3E45721F...",
  "name": "Profit Margin",
  "type": "metric",
  "path": "/Public Objects/Metrics/Financial/",
  "status": "compiled",
  "confidence": 0.92,
  "mstr_definition": {
    "expression_text": "Sum(Profit) / Sum(Revenue)",
    "expression_tree": { "...MSTR expression tree JSON..." },
    "dimty": { "...dimensionality..." },
    "format": { "category": "percent", "decimal_places": 2 }
  },
  "ir_node": { "...BI-IR measure JSON..." },
  "tableau_calc": "SUM([Profit]) / SUM([Revenue])",
  "issues": [],
  "dependencies": ["fact:revenue", "fact:profit"],
  "dependents": ["dossier:sales_performance", "report:quarterly_review"],
  "cross_reference": {
    "tableau_workbook_id": "abc-123",
    "tableau_datasource_id": "ds-456",
    "tableau_field_name": "[Profit Margin]"
  }
}
```

---

## 4. Review Queue

### 4.1 List Review Tasks

```
GET /review?job_id={job_id}&status={status}&severity={severity}
```

**Query Parameters:**
| Param | Type | Description |
|-------|------|-------------|
| `job_id` | string | Filter by job |
| `status` | string | pending, approved, rejected, redesign, assigned |
| `severity` | string | blocker, warning, info |

**Response (200):**
```json
{
  "tasks": [
    {
      "id": "rv-001",
      "job_id": "a1b2c3d4...",
      "object_id": "5A8F3B...",
      "object_name": "Revenue YoY Growth",
      "object_type": "metric",
      "severity": "warning",
      "reason": "Level metric with dimty at Year grain — LOD translation confidence 0.72",
      "mstr_expression": "Sum(Revenue) / Sum(Revenue){~+, Year-1}",
      "generated_calc": "SUM([Revenue]) / LOOKUP(SUM([Revenue]), -1)",
      "confidence": 0.72,
      "status": "pending",
      "blast_radius": ["dossier:sales_overview", "report:annual_summary"],
      "created_at": "2026-08-17T15:00:00Z"
    }
  ],
  "total": 15,
  "by_severity": { "blocker": 3, "warning": 10, "info": 2 }
}
```

---

### 4.2 Get Review Task Detail

```
GET /review/{task_id}
```

Returns full detail including IR snapshot, MSTR raw definition, generated Tableau calc, confidence breakdown, and blast radius.

---

### 4.3 Resolve Review Task

```
POST /review/{task_id}/resolve
```

**Request Body:**
```json
{
  "action": "approve",
  "notes": "Verified YoY calc manually, expression is correct",
  "edited_calc": null
}
```

**Actions:**
| Action | Description |
|--------|-------------|
| `approve` | Accept as-is, allow publish |
| `edit` | Provide `edited_calc`, system re-validates and re-publishes if passing |
| `redesign` | Flag for manual Tableau development |
| `assign` | Set `assigned_to` field |

**Response (200):**
```json
{
  "id": "rv-001",
  "status": "approved",
  "resolved_at": "2026-08-17T16:30:00Z",
  "revalidation_triggered": false
}
```

---

### 4.4 Edit IR and Re-compile

```
POST /review/{task_id}/edit-ir
```

> **Audit note:** Editing the IR triggers the full validation pipeline (re-compile expression AST, re-emit affected worksheets, run golden tests, execute staged-publish validation if needed, and update scorecard).

**Request Body:**
```json
{
  "ir_patch": {
    "transformation": {
      "strategy": "precomputed_column",
      "precomputedColumnName": "Revenue_Prior_Year",
      "offset": {"year": -1}
    },
    "expression": {
      "compiledTableau": "SUM([Revenue]) / [Revenue_Prior_Year]"
    }
  }
}
```

**Response (200):**
```json
{
  "id": "rv-001",
  "recompiled_calc": "SUM([Revenue]) / [Revenue_Prior_Year]",
  "validation_result": {
    "xsd_valid": true,
    "golden_test_passed": true,
    "staged_publish_valid": true,
    "new_confidence": 0.95,
    "numeric_score": 0.998
  },
  "status": "approved",
  "auto_publish_eligible": true
}
```

---

### 4.5 Get Expression Blast Radius

```
GET /review/{task_id}/blast-radius
```

Returns the transitive dependency graph and affected downstream worksheets for an expression under review.

**Response (200):**
```json
{
  "task_id": "rv-001",
  "expression_id": "meas:revenue_growth",
  "direct_dependents": 3,
  "high_confidence_dependents": 2,
  "low_confidence_dependents": 1,
  "affected_worksheets": ["Revenue by Region", "Executive Summary", "YoY Trends"],
  "summary": "Edit affects 3 metrics across 3 worksheets"
}
```

---

### 4.6 Approve & Promote Review Task

```
POST /review/{task_id}/approve
```

Approves the reviewed task, re-acquires the production write-lock, applies all registered IR edits, re-emits production artifacts, and executes atomic promotion to Tableau Server.

**Request Body:**
```json
{
  "approved_by_user": "architect@company.com",
  "reason": "Verified YoY LOD formula against warehouse ground truth"
}
```

**Response (200):**
```json
{
  "task_id": "rv-001",
  "status": "PROMOTED",
  "message": "Job a1b2c3d4 approved and promoted to production",
  "promoted_at": "2026-08-17T17:15:00Z"
}
```

---

## 5. Validation

### 5.1 Get Validation Scorecard

```
GET /jobs/{job_id}/validation
```

**Response (200):**
```json
{
  "job_id": "a1b2c3d4...",
  "overall_numeric_score": 0.97,
  "overall_structural_score": 0.99,
  "security_parity": true,
  "auto_publishable_count": 35,
  "review_count": 12,
  "checks": [
    {
      "check_type": "kpi_value",
      "object_name": "Revenue",
      "filter_scenario": "Region=East, Year=2025",
      "expected": 1234567.89,
      "actual": 1234567.89,
      "passed": true,
      "tolerance": 0.001
    }
  ]
}
```

---

## 6. Cross-Reference

### 6.1 Query Cross-Reference

```
GET /cross-reference?mstr_id={mstr_id}&tableau_id={tableau_id}
```

**Response (200):**
```json
{
  "mappings": [
    {
      "mstr_id": "28B7F04A...",
      "mstr_name": "Revenue",
      "mstr_type": "metric",
      "mstr_path": "/Public Objects/Metrics/Sales/",
      "tableau_workbook_id": "abc-123",
      "tableau_workbook_name": "Sales Performance",
      "tableau_datasource_id": "ds-456",
      "tableau_field_name": "[Revenue]",
      "tableau_field_type": "measure",
      "job_id": "a1b2c3d4...",
      "migrated_at": "2026-08-17T16:00:00Z"
    }
  ]
}
```

---

## 7. Audit Trail

### 7.1 Query Audit Log

```
GET /audit?job_id={job_id}&event_type={type}&from={datetime}&to={datetime}
```

**Event Types:**
- `mstr_api_call` — every REST call to MSTR
- `object_extracted` — object definition captured
- `object_compiled` — IR compiled
- `ai_invocation` — LLM called (includes prompt hash + response)
- `validation_check` — individual validation check result
- `publish_action` — workbook/datasource published
- `review_action` — human review decision
- `error` — any error

**Response (200):**
```json
{
  "events": [
    {
      "id": 1,
      "job_id": "a1b2c3d4...",
      "event_type": "mstr_api_call",
      "timestamp": "2026-08-17T14:30:05Z",
      "details": {
        "method": "GET",
        "url": "/api/model/metrics/28B7F04A...",
        "status_code": 200,
        "duration_ms": 234
      }
    }
  ],
  "total": 5432
}
```

---

## 8. Reports

### 8.1 Generate Migration Report

```
POST /jobs/{job_id}/report
```

**Request Body:**
```json
{
  "format": "excel"
}
```

**Response (200):**
```json
{
  "report_url": "/artifacts/jobs/a1b2c3d4.../migration_report.xlsx",
  "generated_at": "2026-08-17T17:00:00Z"
}
```

Supported formats: `excel`, `pdf`, `json`.

---

## 9. Artifacts

### 9.1 List Job Artifacts

```
GET /jobs/{job_id}/artifacts
```

**Response (200):**
```json
{
  "artifacts": [
    {"name": "catalog.json", "type": "catalog", "size_bytes": 234567, "path": "/artifacts/jobs/.../catalog.json"},
    {"name": "ir.json", "type": "ir", "size_bytes": 456789, "path": "/artifacts/jobs/.../ir.json"},
    {"name": "sales_performance.twbx", "type": "twbx", "size_bytes": 1234567, "path": "/artifacts/jobs/.../sales_performance.twbx"},
    {"name": "shared_datasource.hyper", "type": "hyper", "size_bytes": 8765432, "path": "/artifacts/jobs/.../shared_datasource.hyper"},
    {"name": "migration_report.xlsx", "type": "report", "size_bytes": 345678, "path": "/artifacts/jobs/.../migration_report.xlsx"},
    {"name": "audit.jsonl", "type": "audit", "size_bytes": 123456, "path": "/artifacts/jobs/.../audit.jsonl"}
  ]
}
```

### 9.2 Download Artifact

```
GET /artifacts/{path}
```

Returns the file with appropriate `Content-Type` and `Content-Disposition` headers.

### 9.3 Get Publish Status (Audit v3 Addition)

```
GET /jobs/{job_id}/publish-status
```

**Response (200):**
```json
{
  "job_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "staging": {
    "project_path": "_migration_staging/Sales",
    "datasources_published": 1,
    "workbooks_published": 3,
    "server_validation_passed": true
  },
  "production": {
    "project_path": "Public Objects/Sales",
    "datasources_published": 1,
    "workbooks_published": 3,
    "permissions_applied": true
  },
  "operations": [
    {
      "id": "pub_op_001",
      "artifact_id": "art_ds_01",
      "environment": "staging",
      "status": "COMPLETED",
      "remote_id": "ds-uuid-111",
      "idempotency_key": "sha256:88fa...",
      "completed_at": "2026-08-17T15:45:00Z"
    }
  ]
}
```

### 9.4 Get Reconciliation Report (Audit v3 Addition)

```
GET /jobs/{job_id}/reconciliation
```

**Response (200):**
```json
{
  "job_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "reconciliation_status": "VERIFIED",
  "staging_cleanup_completed": true,
  "remote_workbooks_verified": 3,
  "remote_datasources_verified": 1,
  "hash_matches": true,
  "events": [
    {
      "event_id": "rec_001",
      "event_type": "PROMOTION_VERIFIED",
      "target_id": "wb-uuid-333",
      "timestamp": "2026-08-17T16:00:00Z"
    }
  ]
}
```

### 9.5 Get Validation Matrix (Audit v3 Addition)

```
GET /jobs/{job_id}/validation-matrix
```

**Response (200):**
```json
{
  "job_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "auto_publish_eligible": true,
  "category_scores": {
    "security_confidence": 1.0,
    "financial_kpi_confidence": 0.995,
    "structural_confidence": 0.992,
    "visual_confidence": 0.880
  },
  "gates": {
    "security_gate_passed": true,
    "financial_kpi_gate_passed": true,
    "structural_gate_passed": true,
    "visual_gate_passed": true,
    "blocker_count": 0,
    "warning_count": 2
  }
}
```

---

## Error Response Format

All error responses use a consistent format:

```json
{
  "error": {
    "code": "MSTR_AUTH_FAILED",
    "message": "Failed to authenticate with MicroStrategy: invalid credentials",
    "details": { "status_code": 401, "mstr_error": "..." }
  }
}
```

**Standard Error Codes:**

| Code | HTTP Status | Description |
|------|-------------|-------------|
| `MSTR_AUTH_FAILED` | 401 | MSTR authentication failed |
| `MSTR_API_ERROR` | 502 | MSTR API returned unexpected error |
| `TABLEAU_AUTH_FAILED` | 401 | Tableau Server authentication failed |
| `TABLEAU_PUBLISH_FAILED` | 502 | Tableau publish operation failed |
| `JOB_NOT_FOUND` | 404 | Job ID not found |
| `OBJECT_NOT_FOUND` | 404 | Object not found in catalog |
| `VALIDATION_FAILED` | 422 | Request validation failed |
| `IR_SCHEMA_ERROR` | 500 | IR schema validation failed |
| `TEMPLATE_NOT_FOUND` | 404 | Tableau template version not found |
