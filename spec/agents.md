# Pipeline Agents Specification — mstr-tableau-migrator

**Companion to:** `architecture.md`  
**Date:** 17 August 2026  

---

## Pipeline Overview

```
Orchestrator
   ├─ 1. DiscoveryAgent        → ObjectCatalog
   ├─ 2. GraphAgent            → DAG + migration waves
   ├─ 3. SemanticAgent         → typed defs + expression ASTs
   ├─ 4. IRCompilerAgent       → BI-IR JSON
   ├─ 5. AITranslationAgent    → patched IR (low-confidence only)
   ├─ 6. VisualizationAgent    → worksheet/dashboard specs
   ├─ 7. HyperAgent            → .hyper extract files
   ├─ 8. TableauEmitterAgent   → .twb + .twbx
   ├─ 9. ValidationAgent       → Scorecard
   ├─ 10. PublishAgent         → Tableau Server workbook/DS IDs
   └─ 11. ReviewQueueAgent     → human tasks for failures
```

---

## Agent 0: Orchestrator

**File:** `backend/src/app/services/pipeline/orchestrator.py`

| Field | Value |
|-------|-------|
| **Trigger** | `POST /api/v1/jobs` with project scope |
| **Input** | `MigrationJobSpec` (MSTR URL, credentials, project ID, target Tableau site/project, template version) |
| **Output** | Job status, artifact URIs, aggregate scores |
| **Responsibilities** | Sequence agents, manage job state in SQLite, handle retries, emit audit log entries |

### Pseudocode

```python
class MigrationOrchestrator:
    def __init__(self, job_spec: MigrationJobSpec, job_id: str):
        self.spec = job_spec
        self.job_id = job_id
        self.audit = AuditLogger(job_id)

    async def run(self):
        self.update_status("DISCOVERY")
        catalog = await DiscoveryAgent(self.spec).run()
        
        self.update_status("GRAPH")
        graph = GraphAgent(catalog).run()
        
        # -------------------------------------------------------------
        # PHASE 1: Wave-by-Wave Semantic Extraction & Object Compilation
        # -------------------------------------------------------------
        compiled_wave_irs = []
        all_hyper_paths = {}
        
        for wave in graph.waves():
            self.update_status(f"SEMANTIC_WAVE_{wave.index}")
            semantic_bundle = await SemanticAgent(self.spec, wave).run()
            
            self.update_status(f"PHYSICAL_MODEL_PLAN_WAVE_{wave.index}")
            physical_plan = PhysicalModelPlanner(semantic_bundle, self.spec.warehouse_connection).plan()
            
            self.update_status(f"IR_COMPILE_WAVE_{wave.index}")
            wave_ir = IRCompilerAgent(semantic_bundle, physical_plan).run()
            compiled_wave_irs.append(wave_ir)
            
            self.update_status(f"HYPER_BUILD_WAVE_{wave.index}")
            wave_hypers = await HyperAgent(physical_plan, self.spec).run()
            all_hyper_paths.update(wave_hypers)
        
        # -------------------------------------------------------------
        # PHASE 2: Global Assembly, Staging, Validation & Promotion
        # -------------------------------------------------------------
        self.update_status("METRIC_DEDUPLICATION")
        merged_ir = MetricDeduplicator().deduplicate_all(compiled_wave_irs)
        
        self.update_status("AI_TRANSLATE")
        ir = AITranslationAgent(merged_ir).run()  # only low confidence / unmapped patterns
        
        self.update_status("VIZ")
        viz_specs = VisualizationAgent(ir).run()
        
        self.update_status("DATASOURCE_EMIT")
        ds_plan = DatasourcePlanner(ir, self.spec).plan()
        ds_artifacts = TableauEmitterAgent(ir, viz_specs, all_hyper_paths, ds_plan).emit_datasources()
        
        self.update_status("DATASOURCE_PUBLISH_STAGING")
        staging_ds_map = await PublishAgent(ds_artifacts, target_env="staging").publish_datasources()
        
        self.update_status("WORKBOOK_EMIT_STAGING")
        staging_twbx = TableauEmitterAgent(ir, viz_specs, all_hyper_paths, ds_plan).emit_workbooks(target_env="staging", ds_map=staging_ds_map)
        
        self.update_status("STATIC_VALIDATE")
        static_score = StaticValidator(staging_twbx).validate()
        if not static_score.passed:
            ReviewQueueAgent(ir, staging_twbx, static_score).enqueue()
            return
        
        self.update_status("STAGING_PUBLISH")
        staged_wb_ids = await PublishAgent(staging_twbx, target_env="staging").publish_workbooks()
        
        self.update_status("SERVER_RENDER_VALIDATE")
        render_score = await ValidationAgent(ir, staged_wb_ids, self.spec).validate_server_rendering()
        
        self.update_status("SECURITY_VALIDATE")
        sec_score = await ValidationAgent(ir, staged_wb_ids, self.spec).validate_security()
        
        self.update_status("NUMERIC_VALIDATE")
        num_score = await ValidationAgent(ir, staged_wb_ids, self.spec).validate_numeric()
        
        overall_score = ValidationScorecard.aggregate(static_score, render_score, sec_score, num_score)
        
        if overall_score.auto_publish_ok:
            self.update_status("DATASOURCE_PUBLISH_PRODUCTION")
            prod_ds_map = await PublishAgent(ds_artifacts, target_env="production").publish_datasources()
            
            self.update_status("WORKBOOK_EMIT_PRODUCTION")
            prod_twbx = TableauEmitterAgent(ir, viz_specs, all_hyper_paths, ds_plan).emit_workbooks(target_env="production", ds_map=prod_ds_map)
            
            self.update_status("PROMOTE")
            await PublishAgent(prod_twbx, target_env="production").promote(staged_wb_ids)
            
            self.update_status("RECONCILE")
            await ReconciliationAgent(job_id=self.job_id).reconcile()
        else:
            ReviewQueueAgent(ir, staging_twbx, overall_score).enqueue()
            await PublishAgent(staging_twbx, target_env="staging").rollback_staging(staged_wb_ids)
        
        self.update_status("REPORT")
        ReportGenerator(self.job_id).generate()
        self.update_status("COMPLETE")
```

### Job State Machine (Audit v4 — Canonical)

```
[PHASE 1: EXTRACTION & COMPILATION WAVES]
PENDING → DISCOVERY → GRAPH 
  → [FOR EACH WAVE: SEMANTIC_EXTRACT → PHYSICAL_MODEL_PLAN → IR_COMPILE → HYPER_BUILD]

[PHASE 2: GLOBAL DEDUPLICATION, STAGING, VALIDATION & ATOMIC PROMOTION]
  → METRIC_DEDUPLICATION (global cross-wave pass)
  → AI_TRANSLATE → VIZ → DATASOURCE_EMIT → DATASOURCE_PUBLISH_STAGING
  → WORKBOOK_EMIT_STAGING → STATIC_VALIDATE → STAGING_PUBLISH → SERVER_RENDER_VALIDATE
  → SECURITY_VALIDATE → NUMERIC_VALIDATE 
  → [IF auto_publish_ok:
       DATASOURCE_PUBLISH_PRODUCTION → WORKBOOK_EMIT_PRODUCTION → PROMOTE → RECONCILE → REPORT → COMPLETE]
  → [ELSE:
       ENQUEUE_REVIEW → ROLLBACK_STAGING (production untouched)]
```

---

## Agent 1: DiscoveryAgent

**File:** `backend/src/app/agents/discovery.py`

| Field | Value |
|-------|-------|
| **Input** | MSTR project ID, auth credentials |
| **Output** | `ObjectCatalog` — list of all objects with GUIDs, types, paths, versionIds |
| **APIs** | `POST /api/auth/login`, `GET /api/folders/{id}`, object search API with type/date filters |
| **Strategy** | Use search API with type filters for targeted discovery. Walk folders only for organizational structure. |
| **Error handling** | Retry with exponential backoff on 429/5xx. Re-authenticate on 401 (ADR-016). Re-create instance on 404. Skip inaccessible folders, log warning. |
| **Session** | Uses `MSTRSession` wrapper (ADR-016) with proactive token renewal and instance re-creation. |

### Session Lifecycle & Discovery Schemas

```python
class MSTRSession:
    """Manages dynamic MSTR token lifecycle with proactive renewal (ADR-016)."""
    def __init__(self, username: str, password: str, proactive_renewal_margin_s: int = 60):
        self.username = username
        self.password = password
        self.token: Optional[str] = None
        self.token_issued_at: Optional[datetime] = None
        self.renewal_margin = proactive_renewal_margin_s
        self.cube_instances: dict[str, Any] = {}
        
    def token_expired(self) -> bool:
        if not self.token_issued_at:
            return True
        elapsed = (datetime.utcnow() - self.token_issued_at).total_seconds()
        return elapsed > (1800 - self.renewal_margin)
    
    async def ensure_valid_session(self):
        if self.token_expired():
            self.token = await self._login()
            self.token_issued_at = datetime.utcnow()

@dataclass
class FormSpec:
    form_id: str
    form_name: str
    form_type: str  # "ID" | "DESC" | "HIERARCHY" | "BUSINESS_KEY"
    is_primary_key: bool
    data_type: str

@dataclass
class AttributeFormMetadata:
    attribute_id: str
    attribute_name: str
    forms: list[FormSpec]

@dataclass
class CubeFactMetadata:
    cube_id: str
    fact_table_name: str
    grain_keys: list[str]        # Physical PK columns
    grain_attributes: list[str]  # Referenced MSTR attributes
    
    def validate_dimension_join_safety(self, dim_attrs: list[str]) -> bool:
        """Prevents Cartesian product by checking compound key completeness."""
        return set(self.grain_attributes).issubset(set(dim_attrs))

class DiscoveryValidator:
    """Validates object catalog integrity before advancing to Graph stage."""
    def validate_discovery(self, catalog: ObjectCatalog) -> list[ValidationIssue]:
        issues = []
        for obj in catalog.objects:
            if obj.type_name == "fact" and not obj.compound_key:
                issues.append(ValidationIssue(blocker=True, message=f"Fact {obj.id} missing grain keys"))
            if obj.type_name == "attribute" and "ID" not in obj.attribute_forms:
                issues.append(ValidationIssue(blocker=True, message=f"Attribute {obj.id} missing ID form"))
        return issues
```

### Discovery Sequence

1. `POST /api/auth/login` → obtain `X-MSTR-AuthToken` & probe capabilities (`CapabilityDiscovery`)
2. `GET /api/sessions` → capture MSTR version info
3. Search by object type: attributes (12), facts (13), metrics (4), filters (1), reports (3), cubes (776/779), dossiers (55)
3.5. **[AUDIT]** For each attribute, call `/api/model/attributes/{id}` to pre-extract compound key structure (multiple forms via `AttributeFormMetadata`). Persist to `objects.compound_key_json`. This prevents Cartesian join defects in HyperAgent.
3.6. **[AUDIT]** Detect and distinguish **MSTR Selectors** (type 60) from **Prompts**. Selectors are in-dossier dimension selectors that map to Tableau Quick Filters. Tag them as `type_name: "selector"` in the catalog — NOT as prompts (which are deferred per ADR-013).
4. For each dossier: `GET /api/v2/dossiers/{id}/definition` → extract dataset object IDs AND selector definitions
4.5. **[Inaccessible Dependency Contract]:** If a selected dossier references a cube/report with `accessibility: "INACCESSIBLE"` (HTTP 403 / permission denied), mark the Dossier as `extraction_status: "BLOCKED"`, `poison_reason: "INACCESSIBLE_DEPENDENCY"`. The dossier must **never** be reported as successfully discovered.
5. Walk folder structure for organizational hierarchy
6. Optionally call object lineage endpoints to pre-seed dependency edges
7. **[AUDIT]** Extract project-level VLDB settings (`GET /api/model/vldbSettings`): `null_propagation`, join type defaults, subtotal behavior. Persist to `jobs.vldb_settings_json`.
8. **[AUDIT]** Extract transformation table definitions if any (`GET /api/model/tables?type=transformation`). These are needed by HyperAgent to replicate shifted-key joins for prior-period metrics.
9. Persist catalog to SQLite

### Unused Content Detection (ADR-014)

- Query MSTR audit/usage tables if accessible (`GET /api/stats/usage`).
- Classify unused objects under explicit reason codes:
  - `UNUSED_PER_STATS`: 0 accesses in last 90 days.
  - `UNUSED_PER_DEPENDENCY`: 0 transitive dependents.
  - `INACCESSIBLE`: Permission denied during discovery.
  - `UNSUPPORTED`: Non-migrable object types (ADR-013 prompts, legacy RSD documents).
- Skip unused objects with complete inventory logging in the audit report.

---

## Agent 2: GraphAgent

**File:** `backend/src/app/agents/graph.py`

| Field | Value |
|-------|-------|
| **Input** | `ObjectCatalog` + dependency edges |
| **Output** | Condensed DAG, MigrationUnits, 11-wave partition, blast radius mapping |
| **Tech** | `networkx.DiGraph`, Tarjan's SCC algorithm |

### Edge Types

| Edge | Meaning |
|------|---------|
| `USES` | Object A uses object B in its definition |
| `CONTAINS` | Dossier contains dataset/viz |
| `FILTERS` | Filter applied to report/viz |
| `SECURED_BY` | Object secured by security filter |
| `MATERIALIZES` | Cube materializes metrics/attributes |

### Tarjan's SCC Collapse & MigrationUnit Contract (ADR-003)

```python
@dataclass
class MigrationUnit:
    """Atomic compilation unit (may contain 1+ objects if participating in an SCC)."""
    unit_id: str
    scc_id: int
    member_object_ids: list[str]
    member_types: list[str]
    internal_edges: list[tuple[str, str, str]]
    external_dependencies: dict[int, list[tuple[str, str]]]  # {scc_id: [(from_obj, edge_type)]}
    external_dependents: dict[int, list[tuple[str, str]]]    # {scc_id: [(to_obj, edge_type)]}
    wave_assignment: Optional[int] = None
    compile_status: str = "PENDING"  # "PENDING" | "COMPILING" | "SUCCESS" | "FAILED" | "BLOCKED"
    failure_reason: Optional[str] = None
    blocker_issues: list[str] = field(default_factory=list)

class DependencyGraph:
    def __init__(self):
        self.objects: dict[str, CatalogObject] = {}
        self.edges: dict[str, list[str]] = {}
        self.edge_types: dict[tuple[str, str], str] = {}
        
    def find_sccs(self) -> list[list[str]]:
        """Tarjan's algorithm for strongly connected component detection."""
        index_counter = [0]
        stack, lowlinks, index, on_stack, sccs = [], {}, {}, {}, []
        
        def strongconnect(node):
            index[node] = lowlinks[node] = index_counter[0]
            index_counter[0] += 1
            stack.append(node)
            on_stack[node] = True
            
            for successor in self.edges.get(node, []):
                if successor not in index:
                    strongconnect(successor)
                    lowlinks[node] = min(lowlinks[node], lowlinks[successor])
                elif on_stack.get(successor, False):
                    lowlinks[node] = min(lowlinks[node], index[successor])
                    
            if lowlinks[node] == index[node]:
                scc = []
                while True:
                    w = stack.pop()
                    on_stack[w] = False
                    scc.append(w)
                    if w == node:
                        break
                sccs.append(scc)
                
        for node in self.edges:
            if node not in index:
                strongconnect(node)
        return sccs
```

### The 11-Wave Normative Pipeline Sequence (Waves 0 to 10)

```
[PHASE 1: EXTRACTION & COMPILATION]
  Wave 0: Physical Schema (Warehouse exploration, Hyper schema plan, extraction grain derivation)
  Wave 1: Base Metrics & Filters (Simple aggregations, RLS filters, element qualifications)
  Wave 2: Derived Metrics & Cubes (Divisions, conditionals, level metrics with LOD analysis)
  Wave 3: Dossier Datasets & Chapters (Chapter composition, dataset bindings, selectors)

[PHASE 2: DEDUPLICATION, VALIDATION & CONTROLLED PROMOTION]
  Wave 4: Global Metric Deduplication (Canonical SemanticFingerprint matching & CaptionRegistry)
  Wave 5: AI Translation & Confidence (LLM fallback for unmapped expressions, review triage)
  Wave 6: Visualization & Layout Planning (Viz type mapping, tiled auto-layout planning)
  Wave 7: Datasource & Workbook XML Emission (TDS/TWB generation, streaming Hyper build)
  Wave 8: Staging Publication & Multi-Gate Validation (Crosstab render check, RLS impersonation, numeric parity)
  Wave 9: Promotion Precheck (Scorecard auto_publish_ok evaluation, min-confidence check)
  Wave 10: Production Promotion (Production TDS/TWB publish, permissions, staging cleanup)
```

### Topological Invariant & Blast Radius Verification

$$\text{Topological Invariant: } \forall (u \to v), \quad \text{wave}(u) \ge \text{wave}(v)$$

```python
def verify_topological_invariant(waves: list[MigrationWave], dag: DAGGraph) -> list[TopologyViolation]:
    violations = []
    for wave_idx, wave in enumerate(waves):
        for unit in wave.scc_units:
            for dep_scc_id in unit.external_dependencies.keys():
                dep_wave_idx = dag.get_wave_of_scc(dep_scc_id)
                if wave_idx < dep_wave_idx:
                    violations.append(TopologyViolation(wave_idx, unit.unit_id, dep_wave_idx))
    return violations

def calculate_blast_radius(failed_object_id: str, dag: DAGGraph) -> set[str]:
    """Computes transitive closure of all dependent objects that become BLOCKED (ADR-007)."""
    visited, queue = set(), [failed_object_id]
    while queue:
        curr = queue.pop(0)
        if curr in visited:
            continue
        visited.add(curr)
        for obj_id, deps in dag.edges.items():
            if curr in deps and obj_id not in visited:
                queue.append(obj_id)
    return visited
```

---

## Agent 3: SemanticAgent

**File:** `backend/src/app/agents/semantic.py`

| Field | Value |
|-------|-------|
| **Input** | Wave object GUIDs |
| **Output** | Typed definitions + expression ASTs + dimty + security predicates |
| **APIs** | `/api/model/attributes/{id}`, `/api/model/facts/{id}`, `/api/model/metrics/{id}?showExpressionAs=tree`, `/api/model/filters/{id}`, security filter APIs |

### Per-Object-Type Extraction

#### Attributes
```python
# GET /api/model/attributes/{id}
# Extract: name, forms (ID, DESC, etc.), expressions, relationships
# Output: DimensionDef with field list
```

#### Facts
```python
# GET /api/model/facts/{id}
# Extract: name, expressions, data type
# Output: FactDef with column mapping
```

#### Metrics
```python
# GET /api/model/metrics/{id}?showExpressionAs=tree
# Extract: expression tree, dimty (dimensionality), conditionality, format, thresholds
# Output: MeasureDef with AST + grain hints + confidence score
```

**Blocked & Special Metric Types (Audit v4):**
- Flag `training`, `extreme`, `relationship` metrics as `Issue(severity=BLOCKER, category="unsupported_metric_type")`.
- **Trap B (Derived Elements):** If metric or report template contains derived elements (custom ad-hoc grouping or element sums), emit `Issue(severity=BLOCKER, category="derived_elements_present")`.
- **Trap C (Prompt in Condition):** If metric conditionality or filter tree references an MSTR prompt, emit `Issue(severity=BLOCKER, category="prompt_in_condition")`. Baking default prompt answers into static Tableau calcs is prohibited.
- **Trap E (Semi-Additive Facts):** If fact/metric has VLDB subtotal function set to anything other than `SUM` (e.g. `LAST`, `FIRST` for balance-sheet or inventory metrics), set `grainContract.semiAdditive = True` and emit `Issue(severity=WARNING, category="semi_additive_measure")`.

#### Filters
```python
# GET /api/model/filters/{id}
# Extract: expression tree, qualification type
# Output: FilterDef with predicate AST
```

#### Security Filters
```python
# Security filter modeling APIs
# Extract: predicate expression, user/group bindings
# Output: SecurityPolicyDef with predicate + membership list (keyed on USERNAME per ADR-031)
```

#### Dossier Structure
```python
# GET /api/v2/dossiers/{id}/definition
# Extract: chapters, pages, visualizations, datasets, chapter filters, selectors
# Output: DossierDef with structural tree
```

**Trap D (Multi-Dataset Blending):** If a dossier chapter or visualization references multiple independent datasets/cubes at differing grains, construct a `blendSpec` on the `WorksheetSpec` or emit `Issue(severity=BLOCKER, category="dossier_multi_dataset_blend")`. Single-datasource assumption (ADR-012) does not apply to multi-cube blended sheets.

### Confidence Scoring

Each extracted object gets a confidence score:

| Score | Meaning |
|-------|---------|
| 0.95–1.0 | Fully extractable, simple expression |
| 0.80–0.94 | Extractable but has dimty/conditionality complexity |
| 0.50–0.79 | Partially extractable, needs AI assistance |
| 0.0–0.49 | Blocked or unknown, must go to review |

---

## Agent 3.5: PhysicalModelPlanner (Audit v3 Addition)

**File:** `backend/src/app/agents/physical_model_planner.py`

| Field | Value |
|-------|-------|
| **Input** | MSTR Semantic Bundle (Agent 3), Warehouse Schema Metadata, VLDB Configuration |
| **Output** | `PhysicalModelPlan` with SQL ASTs and extraction specifications |
| **Rules** | **Deterministic semantic SQL compiler — no LLM** |

### Responsibilities

The PhysicalModelPlanner is the semantic-to-physical compiler that turns abstract MSTR metadata into executable warehouse extraction plans:

1. **Physical Table Resolution:** Maps MSTR logical tables to physical warehouse tables, resolving schema names, database catalogs, and physical table aliases.
2. **Attribute Form Resolution:** Reconstructs all attribute forms (ID, DESC, custom expressions, compound keys). For compound forms (e.g. `[STORE_ID] + [DEPT_ID]`), compiles multi-column keys.
3. **Fact Expression Resolution:** Compiles MSTR fact expressions (e.g. `CASE WHEN txn_status = 'POSTED' THEN net_amount END`) into physical SQL dialect ASTs.
4. **Join Path Planning:** Selects optimal relationship paths and constructs warehouse join trees respecting VLDB settings (`JOIN_TYPE`, `PRESERVE_LOOKUP_TABLES`, `CROSS_JOIN_BEHAVIOR`).
5. **Grain & Key Derivation:** Computes exact `ExtractionGrain` (physical grain, semantic grain, primary/foreign keys) for every target Hyper table.
6. **SQL AST Generation:** Generates ANSI/Warehouse-dialect SQL ASTs (`PhysicalExtractQuery`) executed by the HyperAgent during extraction.
7. **Security Predicate Pushdown:** Determines which security filters can be compiled as warehouse WHERE clauses vs. evaluated in Tableau entitlement tables.

### PhysicalModelPlan Schema

```python
@dataclass
class PhysicalModelPlan:
    job_id: str
    datasource_domain: str
    table_plans: list[PhysicalTablePlan]
    join_graph: list[PhysicalJoinEdge]
    grain_contract: ExtractionGrain
    vldb_overrides: dict[str, Any]

@dataclass
class PhysicalTablePlan:
    table_id: str
    physical_name: str
    schema: str
    columns: list[PhysicalColumnDef]
    fact_expressions: list[CompiledFactExpr]
    attribute_forms: list[CompiledFormExpr]
    sql_ast: dict[str, Any]              # Dialect-agnostic SQL AST
    extract_sql: str                     # Rendered warehouse SQL query
    expected_grain: list[str]
```

---

## Agent 4: IRCompilerAgent

**File:** `backend/src/app/agents/ir_compiler.py`

| Field | Value |
|-------|-------|
| **Input** | Semantic bundle (Agent 3), PhysicalModelPlan (Agent 3.5) |
| **Output** | BI-IR JSON conforming to schema (see `ir-schema.md`) |
| **Rules** | **Deterministic only — no LLM in this agent** |

### Compilation Steps

0. **[Audit v3 — ADR-027] MetricDeduplication via SemanticFingerprint:** Cross-wave pass after extraction. Groups all `Measure` entities across all content objects using `SemanticFingerprint` (combining normalized AST, source fact dependencies, datasource domain, physical/semantic grain, aggregation, filtering mode, condition phase, transformation, null policy, zero-division policy, and security scope). Measures with identical fingerprints appearing across multiple content objects receive `scope: "shared"`. Measures with distinct fingerprints or unique to one object receive `scope: "local"`. **String-based formula matching is strictly prohibited.**
1. **Tables:** Map MSTR logical tables to IR `Table` entities, embedding `extractionGrain` and physical schema mappings from the `PhysicalModelPlan`.
2. **Relationships:** Map MSTR attribute relationships to IR `Relationship` entities with verified join cardinalities and compound foreign keys.
3. **Dimensions:** Compile attributes + forms into IR `Dimension` entities.
4. **Measures:** Construct `EvaluationPlan` intermediate models and compile into IR `Measure` entities with Tableau calc expressions. Inject `null_propagation` and `zero_division_result` from `CompilationContext`.
5. **Filters:** Compile filter predicates into IR `Filter` entities.
6. **Security policies:** Compile security filters into IR `SecurityPolicy` entities.
7. **Visuals:** Compile dossier viz definitions into IR `Visual` entities.
8. **Layouts:** Compile dossier chapter/page structure into IR `Layout` entities.
9. **Issues:** Collect all compilation warnings/errors into IR `Issue` entities.
10. **Grain validation:** For every `Measure` with an LOD expression, verify extraction grain sufficiency against `Table.extractionGrain` (Validation Rule 13, ADR-022). Emit `Issue(blocker, insufficient_extraction_grain)` if check fails.

### Expression Compilation

The core of this agent is the **expression compiler** that transforms MSTR metric expression trees into multi-phase `EvaluationPlan` models and then renders Tableau calculated field syntax.

See `expression-compiler.md` for the full pattern catalog and evaluation plan architecture.

---

## Agent 5: AITranslationAgent

**File:** `backend/src/app/agents/ai_translation.py`

| Field | Value |
|-------|-------|
| **Input** | IR nodes with `confidence < 0.85` or unresolved patterns |
| **Output** | Proposed IR patches with rationale |
| **Gate** | Schema validate every patch. Must not touch security without human approval. |

### 3-Tier Fallback Sequence

```python
class AITranslationAgent:
    def translate(self, ir_node: IRMeasure) -> IRPatch:
        # Tier 1: Hash lookup — canonical expression hash → known translation
        cached = self.hash_lookup(ir_node.expression_hash)
        if cached:
            return cached
        
        # Tier 2: Pattern match — dimty→LOD template catalog
        pattern = self.pattern_match(ir_node.expression_ast, ir_node.grain_hints)
        if pattern:
            return pattern.apply(ir_node)
        
        # Tier 3: Semantic search — embed expression, find nearest neighbor
        similar = self.semantic_search(ir_node.expression_text, threshold=0.85)
        if similar:
            return similar.adapt(ir_node)
        
        # Tier 4: LLM — last resort
        return self.llm_translate(ir_node)
```

### LLM Translation (Tier 4)

Reuses the db-tb project pattern:

- Direct OpenAI/Azure API calls (no LangChain)
- SHA-256 hash-based JSON file cache
- Pydantic structured output for parsed results
- Retry with error context injection on failure (max 3 attempts)
- `sqlglot` syntax validation of generated Tableau calc syntax

### LLM Contract

```python
@dataclass
class LLMTranslationResult:
    tableau_calc: str          # Generated Tableau calculated field expression
    explanation: str           # How the translation was derived
    confidence: float          # 0.0–1.0
    requires_human_review: bool
```

### AI Policy (What AI May NOT Do)

- Generate object IDs or lineage edges
- Compile security filter predicates without human sign-off
- Write Hyper schema definitions
- Generate final TWB XML bytes directly
- Decide pass/fail on numeric validation gates
- Set publish ACL/permissions

---

## Agent 6: VisualizationAgent

**File:** `backend/src/app/agents/visualization.py`

| Field | Value |
|-------|-------|
| **Input** | IR visuals + dossier structure |
| **Output** | Worksheet/dashboard specs (mark type, shelf assignments, filter configs) |

### Viz Type Mapping

**Primary:** LLM-assisted recommendation based on viz metadata + data sample.  
**Fallback:** Static mapping table.

| MSTR Viz Type | Tableau Mark Type |
|---------------|-------------------|
| Grid / Crosstab | Text Table |
| Vertical Bar | Bar |
| Horizontal Bar | Bar (swap rows/cols) |
| Line | Line |
| Area | Area |
| Pie | Pie |
| KPI / Metric Value | Text (big number) |
| Scatter | Circle |
| Map | Map |
| Heat Map | Square (color encoding) |
| Unknown | Text Table (safe fallback) |

### Worksheet Spec Output

```python
@dataclass
class WorksheetSpec:
    name: str
    datasource_ref: str
    mark_type: str                    # "bar", "line", "text", etc.
    rows: list[FieldRef]             # shelf assignments
    columns: list[FieldRef]
    color: Optional[FieldRef]
    size: Optional[FieldRef]
    label: Optional[FieldRef]
    detail: list[FieldRef]
    filters: list[FilterSpec]
    sort: list[SortSpec]
    tooltip_fields: list[FieldRef]
```

### Dashboard Spec Output

```python
@dataclass
class DashboardSpec:
    name: str                         # MSTR chapter/page name
    worksheets: list[str]            # worksheet names to include
    layout: str                       # "auto-tiled" (ADR-008)
    filters: list[DashboardFilterSpec]
```

---

## Agent 7: HyperAgent

**File:** `backend/src/app/agents/hyper_builder.py`

| Field | Value |
|-------|-------|
| **Input** | IR physical model + MSTR data (via JSON Data API) |
| **Output** | `.hyper` file(s) with tables + assumed FKs |
| **API (source)** | MSTR JSON Data API (`/api/v2/cubes/{id}/instances`, `/api/v2/reports/{id}/instances`) |
| **API (target)** | `tableauhyperapi` |

### Data Extraction Strategy

Always extract via MSTR JSON Data API (ADR: ensures data matches what MSTR users see, including server-side calcs).

```python
async def extract_cube_data(self, cube_id: str) -> pd.DataFrame:
    """Paginated extraction from MSTR cube instance.
    
    [AUDIT FIX - Flaw 1] Uses MSTRSession wrapper for:
    - Proactive token re-auth before TTL expiry
    - Cube instance re-creation on 404 (instance expiry)
    - Page-level checkpoint persistence for crash recovery
    All blocking IO is wrapped in asyncio.to_thread() (ADR / Audit Flaw 4).
    """
    # Resume from checkpoint if crashed previously
    checkpoint = await self.checkpoint_manager.resume(cube_id)
    offset = checkpoint.page_offset if checkpoint else 0
    all_rows = checkpoint.accumulated_rows if checkpoint else []
    
    instance = await asyncio.to_thread(
        self.mstr_session.create_cube_instance, cube_id
    )
    
    while True:
        try:
            page = await asyncio.to_thread(
                self.mstr_session.get_cube_data,
                instance, offset=offset, limit=10000
            )
        except InstanceExpiredError:
            # MSTR cube instance TTL expired (typically 10 min idle)
            instance = await asyncio.to_thread(
                self.mstr_session.create_cube_instance, cube_id
            )
            continue  # retry same offset with new instance
        
        all_rows.extend(page.rows)
        offset += 10000
        
        # Persist checkpoint after each successful page
        await self.checkpoint_manager.save(cube_id, offset, len(all_rows))
        
        if len(page.rows) < 10000:
            break
    
    await self.checkpoint_manager.mark_complete(cube_id)
    return pd.DataFrame(all_rows, columns=page.column_names)
```

> **Audit Fix (Flaw 1 + Flaw 4):** The original pseudocode had no session management, no checkpoint recovery, and blocked the asyncio event loop. This version wraps all MSTR API calls in `asyncio.to_thread()` to keep FastAPI's poll endpoints responsive, handles instance expiry (404) separately from token expiry (401, handled by `MSTRSession` transparently), and persists page offsets to the `extraction_checkpoints` SQLite table.

### Hyper Schema Generation & Atomic Build (Audit v4)

```python
def build_hyper(self, ir: BIIR, data_iterators: dict[str, Iterator]) -> Path:
    """Build multi-table .hyper with streaming chunked inserts and atomic file swap.
    
    [AUDIT FIX - F4 & v4 Edge 13] Never accumulates full DataFrame in memory.
    Builds to a temporary file (`.hyper.tmp`) and executes atomic filesystem swap
    upon full batch completion, ensuring partial inserts never corrupt checkpoints.
    """
    tmp_path = hyper_path.with_suffix(".hyper.tmp")
    with HyperProcess(Telemetry.DO_NOT_SEND_USAGE_DATA) as hyper:
        with Connection(hyper.endpoint, tmp_path, CreateMode.CREATE_AND_REPLACE) as conn:
            for table in ir.model.tables:
                schema = self._ir_table_to_hyper_schema(table)
                conn.catalog.create_table(schema)
                # Streaming chunked insert — never full in-memory DataFrame
                with Inserter(conn, schema) as inserter:
                    for chunk in data_iterators[table.id]:
                        inserter.add_rows(chunk)  # chunk = list[list], ~10k rows
                    inserter.execute()
    
    # Atomic filesystem swap
    if tmp_path.exists():
        tmp_path.replace(hyper_path)
    return hyper_path
```

> **Hyper Identifier Escaping Parity (Gotcha 5):** Identifier normalization (case-folding, special character replacement) must be identical between Hyper DDL column creation and Tableau TDS XML `<column remote-name='...'>`.

### Live Connection Generation

For content marked as "live connection" (not Hyper extract), generate a `.tds` datasource definition with connection XML pointing to the existing warehouse.

```python
def emit_live_datasource(self, ir: BIIR, warehouse_config: dict) -> str:
    """Generate TDS XML for live connection to warehouse."""
    # Connection type determined by warehouse (sqlserver, oracle, postgresql, etc.)
    # Include Custom SQL if FFSQL, otherwise use native table references
```

---

## Agent 8: TableauEmitterAgent

**File:** `backend/src/app/agents/tableau_emitter.py`

| Field | Value |
|-------|-------|
| **Input** | IR, viz specs, Hyper path, template version |
| **Process** | Copy blank template → inject DS/calcs/sheets/zones → XSD validate → ZIP .twbx |
| **Output** | `.twbx` artifact |

### Emission Sequence (Audit v4 Canonical)

1. **Copy** blank golden template `.twb` for target Tableau version (must be saved with **logical table connections** per ADR-004)
2. **Initialize/load caption registry** — global per published datasource. `{ir_field_id → (local_name, remote_name, caption)}`. Persisted in `caption_registry`.
3. **Topo-sort columns** — topologically sort all `Measure` entities in dependency order using `USES` edges.
4. **Inject datasource columns** — `<column caption=... local-name=... remote-name=...>` elements with XML entity-encoded formulas.
5. **Inject datasource XML fixture** — Use appropriate template fixture (logical Hyper, live TDS, or published DS proxy).
6. **Inject relationship XML** — `<logical-tables>` and `<relationships>` in the logical layer.
7. **Inject worksheets** — one `<worksheet>` per WorksheetSpec. Context filters promoted via `<filter class='categorical' context='true'>` at datasource/dashboard scope (Gotcha 4).
8. **Inject entitlement wiring (Audit v4 — ADR-031):**
   - Wire entitlement table to logical model.
   - Emit delimiter-wrapped predicate: `CONTAINS("|" + [ALLOWED_VALUES] + "|", "|" + [Region] + "|")`.
   - Key match strictly on `USERNAME() = [EntitlementUser]`.
   - Mark entitlement fields `hidden='true'`.
9. **Inject dashboards** — auto-tiled zones with valid `<zones>` tree. Failed worksheets are hidden by omitting them from all dashboard `<zone>` references and omitting them from the `<window>` placement list (Gotcha 3).
10. **Inject parameters** — if any.
11. **Apply basic formatting** — font sizes, colors, number formats.
12. **XSD validate** against `tableau-document-schemas`.
13. **Rewrite datasource paths** — inject **staging** datasource path (`_migration_staging/Datasources/{ds_name}`) or **production** path (`{target_project}/Datasources/{ds_name}`) based on `target_environment` parameter.
14. **Rewrite extract paths** — replace absolute artifact paths with relative package paths (`Data/Extracts/...`).
15. **Package** `.twb` + `.hyper` + images → `.twbx` ZIP.

---

## Agent 9: ValidationAgent

**File:** `backend/src/app/agents/validation.py`

| Field | Value |
|-------|-------|
| **Input** | MSTR golden dataset (pinned at watermark) + generated Tableau staging artifacts |
| **Output** | `ValidationScorecard` with multi-gate results |

### Validation Checks (Audit v4 Multi-Gate)

| Check | Method | Threshold | Category Gate |
|-------|--------|-----------|---------------|
| Row counts | MSTR cube rows vs Hyper table rows at watermark | Exact match | Structural (0.99) |
| Critical KPI values | Pairwise comparison under identical filters & watermark | ≤ 0.1% relative | Financial KPI (0.98) |
| Semi-additive rollup | Recompute at rolled-up time grains vs MSTR | Exact / ≤ 0.1% | Financial KPI (0.98) |
| Filter member sets | Enumeration comparison | Exact set match | Structural (0.99) |
| TWB structure | XSD validation & server view load test | Must pass (200) | Structural (0.99) |
| **Security Impersonation** | **[Audit v4]** Call `Export Crosstab` via Connected App JWT impersonation for 3 test identities; diff visible member sets vs MSTR security filters | 100% member match | Security (Hard 1.0) |
| Context-filter/LOD conflict | Assert no conflicting include filter on FIXED grain | Must pass | Structural (0.99) |

### Scorecard Schema (Audit v4)

```python
@dataclass
class ValidationScorecard:
    job_id: str
    security_confidence: float      # Must be 1.0 for auto-publish
    financial_kpi_confidence: float  # Must be >= 0.98 for auto-publish
    structural_confidence: float    # Must be >= 0.99 for auto-publish
    visual_confidence: float        # Must be >= 0.80 (soft warning)
    security_parity: bool           # Verified via impersonation testing
    blocker_issues: int             # Must be 0
    warning_issues: int
    mandatory_review_flags: int     # Must be 0 for auto-publish
    checks: list[ValidationCheck]
    
    @property
    def auto_publish_ok(self) -> bool:
        return (
            self.security_confidence >= 1.0
            and self.financial_kpi_confidence >= 0.98
            and self.structural_confidence >= 0.99
            and self.visual_confidence >= 0.80
            and self.security_parity
            and self.blocker_issues == 0
            and self.mandatory_review_flags == 0
        )
    
@dataclass
class ValidationCheck:
    check_type: str               # "row_count", "kpi_value", "filter_set", "xsd", "security_member_set", "semi_additive_rollup", "data_drift"
    object_id: str
    expected: Any
    actual: Any
    passed: bool
    tolerance: Optional[float]
    message: str
```

---

## Agent 10: PublishAgent

**File:** `backend/src/app/agents/publisher.py`

| Field | Value |
|-------|-------|
| **Input** | `.twbx` / `.tdsx`, target site/project, ACL map |
| **Output** | Remote entity IDs on Tableau Server, `publish_operations` audit records |
| **API** | `tableauserverclient` (TSC) with chunked upload |

### Publishing Sequence (Audit v4 — Strict Write-Lock Model)

1. **Authenticate & Gate:** Authenticate to Tableau Server. Validate `server_version >= 2020.2` (ADR-024) and `template_version <= server_version` (Validation Rule 17).
2. **Project Resolution:** Resolve or create target project in staging (`_migration_staging/...`).
3. **Publish Staging Datasource:** Publish shared datasource artifact to `_migration_staging/Datasources/...`. Mandate `TSC.FileUpload` chunked upload for files > 64MB.
4. **Publish Staging Workbooks:** Publish workbooks emitted with `target_environment: "staging"` to `_migration_staging`. Log operation in `publish_operations`.
5. **Validation Phase:** Trigger `ValidationAgent` (server-render, security impersonation, numeric checks).
6. **Promotion Phase (`promote()`):**
   - Executed **only** if `scorecard.auto_publish_ok == True`.
   - **Publish Production Datasource:** Publish shared datasource to `{target_project}/Datasources/...`.
   - **Publish Production Workbooks:** Publish workbooks emitted with `target_environment: "production"`.
   - **Preserve Existing Server Metadata:** Query and preserve pre-existing refresh schedules, custom user subscriptions, and group permissions on overwrite re-runs.
   - **Apply Permissions:** Map MSTR ACLs to Tableau Server group permissions.
   - **Record Cross-References:** `mstr_guid → tableau_workbook_id`.
7. **Cleanup & Rollback:**
   - On success: Clean up staging artifacts from `_migration_staging`.
   - On failure: Clean up staging artifacts; production project was never touched. Log rollback in `publish_operations` and `reconciliation_events`.
8. **Reconcile:** Verify production publish via REST API hash comparison.

### Folder → Project Mapping

Replicate MSTR folder paths as Tableau project hierarchy:
- `/Public Objects/Sales/` → Tableau Project `Public Objects > Sales`
- Create projects as needed via TSC API

---

## Agent 11: ReviewQueueAgent

**File:** `backend/src/app/agents/review_queue.py`

| Field | Value |
|-------|-------|
| **Input** | Failed/low-confidence jobs |
| **Output** | Review tasks stored in SQLite, served to Next.js UI |

### Review Task Schema

```python
@dataclass
class ReviewTask:
    id: str
    job_id: str
    object_id: str                    # MSTR GUID
    object_name: str
    object_type: str
    severity: str                     # "blocker", "warning", "info"
    reason: str                       # why this needs review
    mstr_expression: Optional[str]    # original MSTR expression
    generated_calc: Optional[str]     # what the compiler produced
    confidence: float
    ir_snapshot: dict                 # IR JSON for this object
    status: str                       # "pending", "approved", "rejected", "redesign", "assigned"
    assigned_to: Optional[str]
    resolution_notes: Optional[str]
    created_at: datetime
    resolved_at: Optional[datetime]
    blast_radius: list[str]           # GUIDs of affected downstream objects
```

### Review Actions & Re-Validation Cascade (ADR-033)

```python
async def apply_ir_patch_and_revalidate(
    task_id: str,
    expression_id: str,
    new_tableau_calc: str,
    db: Database,
    compiler: ExpressionCompiler
) -> UpdatedValidationResult:
    """Applies human IR patch, validates syntax/fingerprint, cascades to dependents, and re-aggregates scorecard."""
    # 1. Syntax check & semantic fingerprint computation
    ast = compiler.parse_tableau_expression(new_tableau_calc)
    new_fp = compiler.compute_semantic_fingerprint(ast)
    
    # 2. Apply patch & re-validate single expression
    await db.apply_ir_patch(task_id, expression_id, new_tableau_calc)
    
    # 3. Cascade re-validation to transitive dependent metrics
    dependents = await db.get_dependent_expressions(expression_id)
    new_scorecard = await recompute_scorecard_for_subset(expression_id, dependents)
    
    return UpdatedValidationResult(
        status="NOW_AUTO_PUBLISHABLE" if new_scorecard.auto_publish_ok else "STILL_REQUIRES_REVIEW",
        scorecard=new_scorecard
    )
```

### Human Review Confidence Model (ADR-034)

$$\text{Confidence}_{\text{post\_review}} = \min(\text{Confidence}_{\text{orig}} + 0.10 + \text{CommentBoost} + \text{RoleBoost}, \quad 0.99)$$

- **Base boost:** $+0.10$ upon human review.
- **Comment boost:** $+0.05$ for detailed justification ($\ge 100$ characters).
- **Role boost:** $+0.05$ if reviewer role is `BI_ARCHITECT`.
- **Ceiling:** Strictly capped at $0.99$.
- **Post-Promotion 7-Day Audit:** If actual error rate over 7 days exceeds predicted $2 \times (1 - \text{Confidence}_{\text{post\_review}})$, expression is flagged for re-review.

| Action | Effect |
|--------|--------|
| **Approve as-is** | Mark resolved, allow publish |
| **Edit calc & re-validate** | Update IR, re-run validation cascade (ADR-033); if `auto_publish_ok` $\to$ eligible for promotion |
| **Flag for redesign** | Mark as manual work, exclude from auto pipeline |
| **Assign to developer** | Set `assigned_to`, track SLA |

---

## Report Generator

**File:** `backend/src/app/services/pipeline/report_generator.py`

Generates a comprehensive Excel/PDF migration report per project:

| Section | Content |
|---------|---------|
| Executive Summary | Total objects, conversion rate, score distribution |
| Object Inventory | All MSTR objects with type, path, status, confidence |
| Conversion Details | Per-object: MSTR expression → Tableau calc, issues |
| Validation Results | Scorecard per dossier/report |
| Review Queue | Pending items with reasons |
| Recommendations | Prompt re-implementation, theme adjustments |
| Cross-Reference | MSTR GUID → Tableau workbook/DS/field mapping |
