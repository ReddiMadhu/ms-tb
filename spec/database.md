# Database Schema Specification — mstr-tableau-migrator

**Companion to:** `architecture.md`, `api.md`  
**Date:** 17 August 2026  
**ORM:** SQLAlchemy 2.0  
**Database:** SQLite  

---

## 1. Overview

- Job management and progress tracking (with wave & checkpoint state)
- Object catalog (MSTR objects discovered and their migration status)
- Caption registry (disambiguated Tableau captions mapping)
- Validation scores and check results
- Review queue tasks
- Cross-reference mappings (MSTR → Tableau)
- Full audit trail (batched writes)
- Extraction checkpoints (resumable paginated extraction)

### 1.1 Connection & Concurrency Configuration (ADR-002 / ADR-020)

```python
# SQLite Engine Configuration
engine = create_engine(
    "sqlite:///migrations.db",
    connect_args={"check_same_thread": False, "timeout": 30},
    pool_pre_ping=True
)

@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")        # Write-Ahead Logging for concurrent read/write
    cursor.execute("PRAGMA busy_timeout=5000;")       # 5s retry on lock before raising error
    cursor.execute("PRAGMA synchronous=NORMAL;")      # Balances durability and write speed
    cursor.execute("PRAGMA foreign_keys=ON;")         # Enforce foreign key constraints
    cursor.close()
```

> **Audit note (ADR-020):** SQLite in default rollback journal mode suffers write-lock convoys when auditing every API call during concurrent background extraction. WAL mode enables concurrent readers while a single writer operates. Audit log writes are additionally batched in-memory (up to 100 entries or 5 seconds) before transaction commit.

---

## 2. Tables

### 2.1 `jobs`

```sql
CREATE TABLE jobs (
    id              TEXT PRIMARY KEY,           -- UUID
    name            TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'PENDING',
    -- Status: PENDING, DISCOVERY, GRAPH, SEMANTIC, METRIC_DEDUPLICATION, IR_COMPILE, AI_TRANSLATE,
    --         VIZ, HYPER_BUILD, DATASOURCE_EMIT, DATASOURCE_PUBLISH,
    --         WORKBOOK_EMIT_STAGING, STAGING_PUBLISH, SERVER_RENDER_VALIDATE,
    --         STATIC_VALIDATE, SECURITY_VALIDATE, NUMERIC_VALIDATE,
    --         WORKBOOK_EMIT_PRODUCTION, PROMOTE, RECONCILE, REPORT,
    --         COMPLETE, FAILED, CANCELLED
    
    -- MSTR Connection
    mstr_base_url   TEXT NOT NULL,
    mstr_project_id TEXT NOT NULL,
    mstr_project_name TEXT,
    mstr_version    TEXT,
    
    -- Tableau Target
    tableau_server_url TEXT NOT NULL,
    tableau_site_id    TEXT NOT NULL,
    tableau_target_project TEXT,
    
    -- Options
    template_version    TEXT NOT NULL DEFAULT '2024.2',
    skip_unused         BOOLEAN DEFAULT TRUE,
    extract_data        BOOLEAN DEFAULT TRUE,
    auto_publish        BOOLEAN DEFAULT TRUE,
    publish_mode        TEXT DEFAULT 'partial',    -- 'partial' | 'strict'
    numeric_threshold   REAL DEFAULT 0.98,
    
    -- VLDB & Project Configuration [AUDIT]
    vldb_settings_json  TEXT,                     -- Captured MSTR VLDB settings (null propagation, join defaults)
    null_propagation    TEXT DEFAULT 'propagate',  -- [Audit v2] "propagate" | "ignore" — fast lookup for compiler
    zero_division_result TEXT DEFAULT 'null',      -- [Audit v2] "null" | "zero" — VLDB zero-division setting
    
    -- Warehouse Connection & Watermark (ADR-022 / ADR-030)
    warehouse_connection_json TEXT,               -- [Audit v2] Direct warehouse connection config for Hyper extraction
    datasource_scope    TEXT DEFAULT 'project',   -- [Audit v2] "project" | "compatibility_domain" — ADR-012 config
    validation_watermark DATETIME,                -- [Audit v4 - ADR-030] Shared high-water mark timestamp for extraction & golden generation
    security_test_identities_json JSON,           -- [Audit v4 - Flaw 5] Test identities for impersonation-based security validation
    entitlement_datasource_mode TEXT DEFAULT 'locked_separate_datasource', -- [Audit v4 - ADR-031]
    
    -- Progress & Checkpoint State
    current_stage       TEXT,
    checkpoint_stage    TEXT,                     -- Last completed stage for resume (ADR-016)
    current_wave        INTEGER DEFAULT 0,
    total_waves         INTEGER DEFAULT 0,
    objects_total       INTEGER DEFAULT 0,
    objects_processed   INTEGER DEFAULT 0,
    objects_succeeded   INTEGER DEFAULT 0,
    objects_failed      INTEGER DEFAULT 0,
    objects_skipped     INTEGER DEFAULT 0,
    
    -- Scores (populated after validation)
    numeric_score       REAL,
    structural_score    REAL,
    security_parity     BOOLEAN,
    
    -- Artifacts
    artifacts_dir       TEXT,                     -- local filesystem path
    
    -- Timestamps
    created_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at          DATETIME,
    completed_at        DATETIME,
    error_message       TEXT
);
```

### 2.2 `objects`

```sql
CREATE TABLE objects (
    id              TEXT PRIMARY KEY,           -- Internal ID (auto-generated UUID)
    job_id          TEXT NOT NULL REFERENCES jobs(id),
    
    -- MSTR Identity
    mstr_id         TEXT NOT NULL,              -- MSTR GUID
    mstr_type       INTEGER NOT NULL,           -- MSTR type code
    mstr_sub_type   INTEGER,                    -- MSTR subtype code
    type_name       TEXT NOT NULL,              -- "metric", "attribute", "dossier", etc.
    name            TEXT NOT NULL,
    path            TEXT,                       -- MSTR folder path
    version_id      TEXT,                       -- MSTR version for change detection
    
    -- Migration Status
    status          TEXT NOT NULL DEFAULT 'discovered',
    -- Status: discovered, extracted, compiled, emitted, validated, published, 
    --         failed, skipped, review
    
    -- Extracted Definition
    mstr_definition JSON,                       -- Raw MSTR API response
    expression_text TEXT,                       -- Human-readable expression
    
    -- Compiled IR
    ir_node         JSON,                       -- BI-IR JSON for this object
    
    -- Tableau Output
    tableau_calc    TEXT,                       -- Generated Tableau calculated field
    tableau_field_name TEXT,                    -- Field name in Tableau
    
    -- Quality
    confidence      REAL DEFAULT 0.0,
    translation_method TEXT,                    -- "rule_compiler", "pattern:xxx", "llm", etc.
    
    -- Dependencies
    dependency_ids  JSON,                       -- List of MSTR GUIDs this object depends on
    
    -- [AUDIT] Compound key structure for attributes
    compound_key_json JSON,                     -- Multi-column PK structure from MSTR attribute forms
    
    -- [AUDIT] Scope for measures (shared vs local)
    scope           TEXT,                       -- "shared" (in published datasource) or "local" (workbook-level calc)
    
    -- Issues
    issue_count     INTEGER DEFAULT 0,
    blocker_count   INTEGER DEFAULT 0,
    
    -- Timestamps
    discovered_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
    compiled_at     DATETIME,
    published_at    DATETIME,
    
    UNIQUE(job_id, mstr_id)
);

CREATE INDEX idx_objects_job_id ON objects(job_id);
CREATE INDEX idx_objects_type ON objects(type_name);
CREATE INDEX idx_objects_status ON objects(status);
CREATE INDEX idx_objects_mstr_id ON objects(mstr_id);
```

### 2.3 `issues`

```sql
CREATE TABLE issues (
    id              TEXT PRIMARY KEY,
    job_id          TEXT NOT NULL REFERENCES jobs(id),
    object_id       TEXT REFERENCES objects(id),
    
    severity        TEXT NOT NULL,              -- "blocker", "warning", "info"
    category        TEXT NOT NULL,              -- See issue categories in ir-schema.md
    message         TEXT NOT NULL,
    suggestion      TEXT,
    
    -- Affected downstream objects
    affected_objects JSON,                      -- List of object IDs
    
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_issues_job_id ON issues(job_id);
CREATE INDEX idx_issues_severity ON issues(severity);
```

### 2.4 `validation_checks`

```sql
CREATE TABLE validation_checks (
    id              TEXT PRIMARY KEY,
    job_id          TEXT NOT NULL REFERENCES jobs(id),
    object_id       TEXT REFERENCES objects(id),
    
    check_type      TEXT NOT NULL,             -- "row_count", "kpi_value", "filter_set", "xsd", "open_test", "security_member_set", "semi_additive_rollup", "data_drift"
    check_name      TEXT NOT NULL,             -- Human-readable name
    filter_scenario TEXT,                      -- e.g., "Region=East, Year=2025"
    
    expected_value  TEXT,                      -- JSON-serialized expected
    actual_value    TEXT,                      -- JSON-serialized actual
    tolerance       REAL,
    passed          BOOLEAN NOT NULL,
    message         TEXT,
    
    executed_at     DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_validation_job ON validation_checks(job_id);
CREATE INDEX idx_validation_passed ON validation_checks(passed);
```

### 2.5 `review_tasks`

```sql
CREATE TABLE review_tasks (
    id              TEXT PRIMARY KEY,
    job_id          TEXT NOT NULL REFERENCES jobs(id),
    object_id       TEXT NOT NULL REFERENCES objects(id),
    
    severity        TEXT NOT NULL,              -- "blocker", "warning"
    reason          TEXT NOT NULL,
    
    -- Expression comparison
    mstr_expression TEXT,
    generated_calc  TEXT,
    confidence      REAL,
    
    -- IR snapshot for inline editing
    ir_snapshot     JSON,
    
    -- Status
    status          TEXT NOT NULL DEFAULT 'pending',
    -- Status: pending, approved, rejected, redesign, assigned
    assigned_to     TEXT,
    resolution_notes TEXT,
    edited_calc     TEXT,                       -- If reviewer edited the calc
    
    -- Blast radius
    blast_radius    JSON,                       -- List of affected object GUIDs
    
    -- Timestamps
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    resolved_at     DATETIME
);

CREATE INDEX idx_review_job ON review_tasks(job_id);
CREATE INDEX idx_review_status ON review_tasks(status);
CREATE INDEX idx_review_severity ON review_tasks(severity);
```

### 2.6 `cross_references`

```sql
CREATE TABLE cross_references (
    id              TEXT PRIMARY KEY,
    job_id          TEXT NOT NULL REFERENCES jobs(id),
    
    -- MSTR side
    mstr_id         TEXT NOT NULL,
    mstr_name       TEXT NOT NULL,
    mstr_type       TEXT NOT NULL,
    mstr_path       TEXT,
    
    -- Tableau side
    tableau_workbook_id   TEXT,
    tableau_workbook_name TEXT,
    tableau_datasource_id TEXT,
    tableau_field_name    TEXT,
    published_field_name  TEXT,                 -- [AUDIT] Canonical name from Tableau Server REST API after publish
    tableau_field_type    TEXT,                 -- "dimension", "measure", "calculated"
    tableau_project       TEXT,
    
    migrated_at     DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_xref_mstr ON cross_references(mstr_id);
CREATE INDEX idx_xref_tableau ON cross_references(tableau_workbook_id);
CREATE INDEX idx_xref_job ON cross_references(job_id);
```

### 2.7 `audit_log`

```sql
CREATE TABLE audit_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id          TEXT REFERENCES jobs(id),
    
    event_type      TEXT NOT NULL,
    -- Event types: mstr_api_call, object_extracted, object_compiled, 
    --              ai_invocation, validation_check, publish_action, 
    --              review_action, error, job_state_change
    
    timestamp       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    
    -- Event details (varies by type)
    details         JSON NOT NULL,
    
    -- For AI invocations
    prompt_hash     TEXT,                       -- SHA-256 of the LLM prompt
    
    -- For MSTR API calls
    api_method      TEXT,                       -- GET, POST
    api_url         TEXT,
    api_status_code INTEGER,
    api_duration_ms INTEGER
);

CREATE INDEX idx_audit_job ON audit_log(job_id);
CREATE INDEX idx_audit_type ON audit_log(event_type);
CREATE INDEX idx_audit_timestamp ON audit_log(timestamp);
```

### 2.8 `expression_cache`

    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_used_at    DATETIME,
    golden_suite_version TEXT                  -- [AUDIT] Version of golden suite that validated this entry;
                                              -- cache invalidated when suite version changes
);
```

### 2.9 `caption_registry` (Audit Addition, revised v2)

```sql
-- [AUDIT FIX - Section 3 Gotchas & Edge Case #16]
-- [AUDIT v2 - Flaw A] Now scoped per datasource, not per workbook.
-- Maps IR field IDs to unique, post-disambiguation Tableau captions.
-- MSTR object names are not unique per project; Tableau captions in a datasource must be.
CREATE TABLE caption_registry (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id          TEXT NOT NULL REFERENCES jobs(id),
    datasource_id   TEXT NOT NULL,              -- [Audit v2] Scoped per published datasource, not per workbook
    ir_id           TEXT NOT NULL,              -- e.g. "meas:revenue", "dim:region"
    local_name      TEXT NOT NULL,              -- [Audit v2] Canonical published name (used as local-name AND remote-name in TWB XML)
    remote_name     TEXT NOT NULL,              -- [Audit v2] Server canonical name (= local_name)
    caption         TEXT NOT NULL,              -- [Audit v2] Display disambiguation (e.g., "Revenue Net", NOT "Revenue (2)")
    mstr_name       TEXT NOT NULL,              -- Original MSTR name
    scope           TEXT NOT NULL DEFAULT 'shared', -- 'shared' | 'local'
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(job_id, datasource_id, ir_id),
    UNIQUE(job_id, datasource_id, caption)
);

CREATE INDEX idx_caption_job ON caption_registry(job_id);
CREATE INDEX idx_caption_ds ON caption_registry(datasource_id);
CREATE INDEX idx_caption_ir ON caption_registry(ir_id);
```

### 2.10 `extraction_checkpoints` (Audit Addition)

```sql
-- [AUDIT FIX - Flaw 1 / Edge Case #13] Supports crash-recovery for paginated MSTR data extraction.
-- HyperAgent persists page_offset after each successful page so a crashed
-- extraction resumes from the last committed page, not page 0.
CREATE TABLE extraction_checkpoints (
    id              TEXT PRIMARY KEY,
    job_id          TEXT NOT NULL REFERENCES jobs(id),
    object_id       TEXT NOT NULL,              -- MSTR cube/report GUID
    page_offset     INTEGER NOT NULL DEFAULT 0,
    rows_written    INTEGER NOT NULL DEFAULT 0,
    etag            TEXT,                       -- Instance version / ETag for cache invalidation
    snapshot_identity TEXT,                     -- [Audit v3] Snapshot instance ID & timestamp
    page_checksum   TEXT,                       -- [Audit v3] SHA-256 hash of extracted chunk
    hyper_batch_id  TEXT,                       -- [Audit v3] Batch ID within Hyper extract
    artifact_version TEXT,                      -- [Audit v3] Schema/extract version
    completed       BOOLEAN DEFAULT FALSE,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_checkpoint_job ON extraction_checkpoints(job_id);
CREATE INDEX idx_checkpoint_object ON extraction_checkpoints(object_id);
```

### 2.11 `datasource_path_rewrites` (Audit v2 Addition)

```sql
-- [AUDIT v2 - Flaw B / ADR-023] Stores staging and production datasource paths
-- for TWB path rewriting between staging validation and production publish.
CREATE TABLE datasource_path_rewrites (
    id              TEXT PRIMARY KEY,
    job_id          TEXT NOT NULL REFERENCES jobs(id),
    ir_datasource_id TEXT NOT NULL,             -- IR datasource entity ID
    staging_path    TEXT,                       -- e.g. '_migration_staging/Datasources/shared_sales'
    production_path TEXT,                       -- e.g. 'Migrated from MSTR/Datasources/shared_sales'
    staging_ds_id   TEXT,                       -- Tableau Server datasource ID in staging
    production_ds_id TEXT,                      -- Tableau Server datasource ID in production
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_dsrewrite_job ON datasource_path_rewrites(job_id);
```

### 2.12 `semantic_fingerprints` (Audit v3 Addition — ADR-027)

```sql
-- [AUDIT v3 - Critical #2] Stores multi-attribute semantic fingerprints for measure deduplication.
CREATE TABLE semantic_fingerprints (
    id                  TEXT PRIMARY KEY,
    job_id              TEXT NOT NULL REFERENCES jobs(id),
    fingerprint_hash    TEXT NOT NULL,          -- SHA-256 of canonical fingerprint tuple
    ast_hash            TEXT NOT NULL,
    datasource_domain   TEXT NOT NULL,
    source_dependencies JSON NOT NULL,          -- list of physical fact/table IDs
    physical_grain      JSON NOT NULL,
    semantic_grain      JSON NOT NULL,
    aggregation         TEXT NOT NULL,
    filtering_mode      TEXT NOT NULL,
    condition_phase     TEXT NOT NULL,
    transformation      TEXT,
    null_policy         TEXT NOT NULL,
    zero_division_policy TEXT NOT NULL,
    security_scope      TEXT,
    assigned_scope      TEXT NOT NULL DEFAULT 'local', -- 'shared' | 'local'
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(job_id, fingerprint_hash)
);

CREATE INDEX idx_fingerprint_job ON semantic_fingerprints(job_id);
CREATE INDEX idx_fingerprint_hash ON semantic_fingerprints(fingerprint_hash);
```

### 2.13 `physical_model_plans` (Audit v3 Addition — ADR-026)

```sql
-- [AUDIT v3 - Critical #1] Stores PhysicalModelPlanner compiler output for warehouse extraction.
CREATE TABLE physical_model_plans (
    id                  TEXT PRIMARY KEY,
    job_id              TEXT NOT NULL REFERENCES jobs(id),
    datasource_domain   TEXT NOT NULL,
    table_plans_json    JSON NOT NULL,          -- PhysicalTablePlan definitions with SQL ASTs
    join_graph_json     JSON NOT NULL,          -- Join paths & cardinalities
    grain_contract_json JSON NOT NULL,          -- Derived ExtractionGrain contracts
    vldb_overrides_json JSON,
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_modelplan_job ON physical_model_plans(job_id);
```

### 2.14 `artifacts` (Audit v3 Addition)

```sql
-- [AUDIT v3] Tracks all generated migration artifacts with versioning and environment tagging.
CREATE TABLE artifacts (
    id                  TEXT PRIMARY KEY,
    job_id              TEXT NOT NULL REFERENCES jobs(id),
    artifact_type       TEXT NOT NULL,          -- 'twb', 'twbx', 'hyper', 'tds', 'tdsx', 'report'
    artifact_path       TEXT NOT NULL,
    artifact_hash       TEXT NOT NULL,          -- SHA-256 content hash
    environment         TEXT NOT NULL,          -- 'staging' | 'production' | 'local'
    datasource_id       TEXT,
    workbook_id         TEXT,
    version             INTEGER NOT NULL DEFAULT 1,
    size_bytes          INTEGER NOT NULL,
    status              TEXT NOT NULL DEFAULT 'created', -- 'created', 'validated', 'published', 'deprecated'
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_artifact_job ON artifacts(job_id);
CREATE INDEX idx_artifact_hash ON artifacts(artifact_hash);
```

### 2.15 `publish_operations` (Audit v3 Addition — ADR-029)

```sql
-- [AUDIT v3 - Critical #5] Tracks transactional publish operations with idempotency keys.
CREATE TABLE publish_operations (
    id                  TEXT PRIMARY KEY,
    job_id              TEXT NOT NULL REFERENCES jobs(id),
    artifact_id         TEXT NOT NULL REFERENCES artifacts(id),
    environment         TEXT NOT NULL,          -- 'staging' | 'production'
    remote_id           TEXT,                   -- Tableau Server entity ID
    remote_project_id   TEXT NOT NULL,
    operation           TEXT NOT NULL,          -- 'publish_ds', 'publish_wb', 'promote', 'delete'
    idempotency_key     TEXT NOT NULL UNIQUE,   -- SHA-256(job_id + artifact_id + env + ver)
    status              TEXT NOT NULL,          -- 'PENDING', 'IN_PROGRESS', 'COMPLETED', 'FAILED', 'ROLLED_BACK'
    remote_hash         TEXT,                   -- Hash returned by Tableau Server
    error_message       TEXT,
    started_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    completed_at        DATETIME
);

CREATE INDEX idx_pubop_job ON publish_operations(job_id);
CREATE INDEX idx_pubop_key ON publish_operations(idempotency_key);
```

### 2.16 `reconciliation_events` (Audit v3 Addition)

```sql
-- [AUDIT v3] Logs promotion verification, staging cleanup, and rollback events.
CREATE TABLE reconciliation_events (
    id                  TEXT PRIMARY KEY,
    job_id              TEXT NOT NULL REFERENCES jobs(id),
    event_type          TEXT NOT NULL,          -- 'PROMOTION_VERIFIED', 'STAGING_CLEANED', 'ROLLBACK_TRIGGERED'
    target_entity_id    TEXT NOT NULL,
    environment         TEXT NOT NULL,
    details             JSON NOT NULL,
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_reconciliation_job ON reconciliation_events(job_id);
```

### 2.17 `discovery_sessions` & `discovery_objects` (Step 1 Checkpoint Persistence)

```sql
-- [Step 1 Discovery Checkpointing] Supports resumable pre-job discovery catalog walks.
CREATE TABLE discovery_sessions (
    job_id              TEXT PRIMARY KEY REFERENCES jobs(id),
    started_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_checkpoint_at  DATETIME,
    current_phase       TEXT NOT NULL,          -- 'scan_projects' | 'scan_dossiers' | 'scan_cubes' | 'complete'
    dossiers_scanned    INTEGER DEFAULT 0,
    dossiers_total      INTEGER DEFAULT 0,
    status              TEXT NOT NULL DEFAULT 'in_progress'
);

CREATE TABLE discovery_objects (
    job_id              TEXT NOT NULL REFERENCES jobs(id),
    object_id           TEXT NOT NULL,          -- MSTR GUID
    object_type         TEXT NOT NULL,          -- 'dossier' | 'cube' | 'metric' | 'attribute' | 'fact'
    object_name         TEXT NOT NULL,
    parent_id           TEXT,
    discovered_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
    extraction_status   TEXT NOT NULL DEFAULT 'pending', -- 'pending' | 'extracted' | 'failed' | 'skipped'
    error_reason        TEXT,
    metadata_json       TEXT NOT NULL,          -- Full API response JSON blob
    PRIMARY KEY (job_id, object_id)
);

CREATE INDEX idx_disc_obj_job ON discovery_objects(job_id);
CREATE INDEX idx_disc_obj_type ON discovery_objects(object_type);
```

### 2.18 `wave_executions` (Step 2 SCC & Wave Persistence — ADR-003)

```sql
-- [Step 2 Graph & Waves] Tracks atomic SCC units and wave execution state for crash recovery.
CREATE TABLE wave_executions (
    job_id              TEXT NOT NULL REFERENCES jobs(id),
    wave_id             INTEGER NOT NULL,
    scc_id              INTEGER NOT NULL,
    object_id           TEXT,                   -- MSTR GUID (or NULL for multi-object SCC)
    dependency_hash     TEXT NOT NULL,          -- SHA-256 hash of dependency IDs for change detection
    status              TEXT NOT NULL DEFAULT 'PENDING', -- 'PENDING' | 'COMPILING' | 'SUCCESS' | 'FAILED' | 'BLOCKED'
    attempt             INTEGER NOT NULL DEFAULT 1,
    started_at          DATETIME,
    completed_at        DATETIME,
    failure_reason      TEXT,
    failure_class       TEXT,                   -- 'FAILED_EXTRACT' | 'FAILED_COMPILE' | 'BLOCKED_DEPENDENCY'
    blocker_issues      TEXT,                   -- JSON array of Issue codes/messages
    ir_json_path        TEXT,                   -- Path to intermediate representation artifact
    PRIMARY KEY (job_id, wave_id, scc_id)
);

CREATE INDEX idx_wave_exec_job ON wave_executions(job_id);
CREATE INDEX idx_wave_exec_status ON wave_executions(status);
```

---

## 3. SQLAlchemy Models

```python
# backend/src/app/models/job.py

from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, JSON, Text, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from app.db.base import Base
from datetime import datetime
import uuid


class Job(Base):
    __tablename__ = "jobs"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    status = Column(String, nullable=False, default="PENDING")
    
    # MSTR Connection
    mstr_base_url = Column(String, nullable=False)
    mstr_project_id = Column(String, nullable=False)
    mstr_project_name = Column(String)
    mstr_version = Column(String)
    
    # Tableau Target
    tableau_server_url = Column(String, nullable=False)
    tableau_site_id = Column(String, nullable=False)
    tableau_target_project = Column(String)
    
    # Options & Configuration
    template_version = Column(String, nullable=False, default="2024.2")
    skip_unused = Column(Boolean, default=True)
    extract_data = Column(Boolean, default=True)
    auto_publish = Column(Boolean, default=True)
    publish_mode = Column(String, default="partial")
    numeric_threshold = Column(Float, default=0.98)
    
    # VLDB, Warehouse & Watermark Settings (Audit v2/v3/v4)
    vldb_settings_json = Column(JSON)
    null_propagation = Column(String, default="propagate")
    zero_division_result = Column(String, default="null")
    warehouse_connection_json = Column(JSON)
    datasource_scope = Column(String, default="project")
    validation_watermark = Column(DateTime)
    security_test_identities_json = Column(JSON)
    entitlement_datasource_mode = Column(String, default="locked_separate_datasource")
    
    # Progress
    current_stage = Column(String)
    current_wave = Column(Integer, default=0)
    total_waves = Column(Integer, default=0)
    objects_total = Column(Integer, default=0)
    objects_processed = Column(Integer, default=0)
    objects_succeeded = Column(Integer, default=0)
    objects_failed = Column(Integer, default=0)
    objects_skipped = Column(Integer, default=0)
    
    # Category-Weighted Confidence Scores (Audit v2/v3 ADR-025)
    security_confidence = Column(Float, default=1.0)
    financial_kpi_confidence = Column(Float, default=1.0)
    structural_confidence = Column(Float, default=1.0)
    visual_confidence = Column(Float, default=1.0)
    numeric_score = Column(Float)
    structural_score = Column(Float)
    security_parity = Column(Boolean, default=True)
    
    # Artifacts & Timestamps
    artifacts_dir = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    error_message = Column(Text)
    
    # Relationships
    objects = relationship("MigrationObject", back_populates="job")
    issues = relationship("Issue", back_populates="job")
    review_tasks = relationship("ReviewTask", back_populates="job")
    artifacts = relationship("Artifact", back_populates="job")
    publish_ops = relationship("PublishOperation", back_populates="job")


class CaptionRegistry(Base):
    __tablename__ = "caption_registry"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False)
    datasource_id = Column(String, nullable=False)
    ir_id = Column(String, nullable=False)
    local_name = Column(String, nullable=False)
    remote_name = Column(String, nullable=False)
    caption = Column(String, nullable=False)
    mstr_name = Column(String, nullable=False)
    scope = Column(String, default="shared")
    created_at = Column(DateTime, default=datetime.utcnow)


class ExtractionCheckpoint(Base):
    __tablename__ = "extraction_checkpoints"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False)
    object_id = Column(String, nullable=False)
    page_offset = Column(Integer, default=0)
    rows_written = Column(Integer, default=0)
    etag = Column(String)
    snapshot_identity = Column(String)
    page_checksum = Column(String)
    hyper_batch_id = Column(String)
    artifact_version = Column(String)
    completed = Column(Boolean, default=False)
    updated_at = Column(DateTime, default=datetime.utcnow)


class DatasourcePathRewrite(Base):
    __tablename__ = "datasource_path_rewrites"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False)
    ir_datasource_id = Column(String, nullable=False)
    staging_path = Column(String)
    production_path = Column(String)
    staging_ds_id = Column(String)
    production_ds_id = Column(String)
    updated_at = Column(DateTime, default=datetime.utcnow)


class SemanticFingerprint(Base):
    __tablename__ = "semantic_fingerprints"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False)
    fingerprint_hash = Column(String, nullable=False)
    ast_hash = Column(String, nullable=False)
    datasource_domain = Column(String, nullable=False)
    source_dependencies = Column(JSON, nullable=False)
    physical_grain = Column(JSON, nullable=False)
    semantic_grain = Column(JSON, nullable=False)
    aggregation = Column(String, nullable=False)
    filtering_mode = Column(String, nullable=False)
    condition_phase = Column(String, nullable=False)
    transformation = Column(String)
    null_policy = Column(String, nullable=False)
    zero_division_policy = Column(String, nullable=False)
    security_scope = Column(String)
    assigned_scope = Column(String, default="local")
    created_at = Column(DateTime, default=datetime.utcnow)


class Artifact(Base):
    __tablename__ = "artifacts"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False)
    artifact_type = Column(String, nullable=False)
    artifact_path = Column(String, nullable=False)
    artifact_hash = Column(String, nullable=False)
    environment = Column(String, nullable=False)
    datasource_id = Column(String)
    workbook_id = Column(String)
    version = Column(Integer, default=1)
    size_bytes = Column(Integer, nullable=False)
    status = Column(String, default="created")
    created_at = Column(DateTime, default=datetime.utcnow)
    
    job = relationship("Job", back_populates="artifacts")


class PublishOperation(Base):
    __tablename__ = "publish_operations"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False)
    artifact_id = Column(String, ForeignKey("artifacts.id"), nullable=False)
    environment = Column(String, nullable=False)
    remote_id = Column(String)
    remote_project_id = Column(String, nullable=False)
    operation = Column(String, nullable=False)
    idempotency_key = Column(String, unique=True, nullable=False)
    status = Column(String, nullable=False)
    remote_hash = Column(String)
    error_message = Column(Text)
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)
    
    job = relationship("Job", back_populates="publish_ops")


class MigrationObject(Base):
    __tablename__ = "objects"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False)
    
    mstr_id = Column(String, nullable=False)
    mstr_type = Column(Integer, nullable=False)
    mstr_sub_type = Column(Integer)
    type_name = Column(String, nullable=False)
    name = Column(String, nullable=False)
    path = Column(String)
    version_id = Column(String)
    
    status = Column(String, nullable=False, default="discovered")
    mstr_definition = Column(JSON)
    expression_text = Column(Text)
    ir_node = Column(JSON)
    tableau_calc = Column(Text)
    tableau_field_name = Column(String)
    
    confidence = Column(Float, default=0.0)
    translation_method = Column(String)
    dependency_ids = Column(JSON)
    issue_count = Column(Integer, default=0)
    blocker_count = Column(Integer, default=0)
    
    discovered_at = Column(DateTime, default=datetime.utcnow)
    compiled_at = Column(DateTime)
    published_at = Column(DateTime)
    
    job = relationship("Job", back_populates="objects")


class AuditLog(Base):
    __tablename__ = "audit_log"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String, ForeignKey("jobs.id"))
    event_type = Column(String, nullable=False)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow)
    details = Column(JSON, nullable=False)
    prompt_hash = Column(String)
    api_method = Column(String)
    api_url = Column(String)
    api_status_code = Column(Integer)
    api_duration_ms = Column(Integer)
```

---

## 4. Database Session Management

```python
# backend/src/app/db/session.py

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.core.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False},  # SQLite-specific
    echo=False
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """Dependency for FastAPI routes."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

---

## 5. Audit Logger

```python
# backend/src/app/core/audit.py

from datetime import datetime
from app.db.session import SessionLocal
from app.models.job import AuditLog


class AuditLogger:
    """Append-only audit logger per ADR-010."""
    
    def __init__(self, job_id: str):
        self.job_id = job_id
    
    def log_mstr_api_call(self, method: str, url: str, status_code: int, duration_ms: int):
        self._write(
            event_type="mstr_api_call",
            details={"method": method, "url": url},
            api_method=method,
            api_url=url,
            api_status_code=status_code,
            api_duration_ms=duration_ms
        )
    
    def log_object_extracted(self, mstr_id: str, object_name: str, object_type: str):
        self._write(
            event_type="object_extracted",
            details={"mstr_id": mstr_id, "name": object_name, "type": object_type}
        )
    
    def log_ai_invocation(self, prompt_hash: str, expression: str, result: str, confidence: float):
        self._write(
            event_type="ai_invocation",
            details={
                "expression": expression,
                "result": result,
                "confidence": confidence
            },
            prompt_hash=prompt_hash
        )
    
    def log_publish_action(self, mstr_id: str, tableau_id: str, tableau_type: str):
        self._write(
            event_type="publish_action",
            details={"mstr_id": mstr_id, "tableau_id": tableau_id, "type": tableau_type}
        )
    
    def log_error(self, message: str, details: dict = None):
        self._write(
            event_type="error",
            details={"message": message, **(details or {})}
        )
    
    def _write(self, event_type: str, details: dict, **kwargs):
        db = SessionLocal()
        try:
            entry = AuditLog(
                job_id=self.job_id,
                event_type=event_type,
                timestamp=datetime.utcnow(),
                details=details,
                **kwargs
            )
            db.add(entry)
            db.commit()
        finally:
            db.close()
```
