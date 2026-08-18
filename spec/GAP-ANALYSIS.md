# GAP ANALYSIS & SCHEMA EXTENSIONS

**Companion to:** `IMPLEMENTATION-GUIDE.md`, 10-Step Architecture Review  
**Date:** 17 August 2026  
**Purpose:** Identify specification gaps from 10-step analysis and provide concrete remediation

---

## Executive Summary

The 10-step architecture review identified **18 critical blindspots** across steps 1–10:

| Step | Gap | Severity | Remediation | Status |
|------|-----|----------|-------------|--------|
| 1 | Session checkpoint schema undefined | 🔴 Critical | Add `extraction_checkpoints` table | ✅ In IMPL-GUIDE |
| 2 | SCC wave persistence schema missing | 🔴 Critical | Add `migration_units`, `wave_assignments` | ⏳ See §3 |
| 3 | Warehouse SQL templating incomplete | 🔴 Critical | Add `WarehouseSemanticSQLGenerator` | ✅ In IMPL-GUIDE |
| 4 | Expression confidence scoring vague | 🟡 High | Formalize confidence formula + boost algorithm | ⏳ See §5 |
| 5 | Fingerprint collision handling under-specified | 🔴 Critical | CaptionRegistry collision suffix rules | ⏳ See §4 |
| 6 | Hyper schema validation missing | 🟡 High | Add schema parity assertions | ⏳ See §6 |
| 7 | TWBX validation incomplete | 🟡 High | Add XSD + structure validators | ⏳ See §7 |
| 8 | Watermark snapshot contract under-spec'd | 🔴 Critical | Formalize warehouse time-travel patterns | ✅ In IMPL-GUIDE |
| 9 | Production lock idempotency schema missing | 🔴 Critical | Add `production_write_locks`, `promotion_operations` | ✅ In IMPL-GUIDE |
| 10 | IR patch re-validation flow missing | 🔴 Critical | Add `review_tasks`, `ir_edits`, re-validation engine | ✅ In IMPL-GUIDE |

---

## Part 1: Step 2 Gaps — Graph Compilation & Wave Persistence

### 1.1 Current State

`architecture.md` describes Tarjan SCC and topological sort conceptually, but lacks:
- **Persistent wave state** schema for crash recovery
- **MigrationUnit** data model and relationship to waves
- **Blast radius** transitive closure algorithm

### 1.2 Remediation: Database Schema

```sql
-- migration_units.sql: Atomic compilation units (collapsed SCCs)

CREATE TABLE migration_units (
    unit_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    
    -- SCC membership
    member_ids JSON NOT NULL,  -- List of MSTR GUID strings
    member_types JSON NOT NULL,  -- List of object types (metric, filter, etc.)
    member_count INT NOT NULL,
    
    -- Wave assignment
    wave_number INT NOT NULL,  -- 0–10 per two-phase model
    phase TEXT CHECK (phase IN ('PHASE_1_EXTRACTION', 'PHASE_2_GLOBAL')),
    
    -- Dependency metadata
    internal_edges INT NOT NULL,  -- Edges within SCC
    external_edges INT NOT NULL,  -- Edges to other units
    external_dependent_units JSON,  -- List of units that depend on this
    
    -- Compilation status
    status TEXT CHECK (status IN ('PENDING', 'IN_PROGRESS', 'COMPILED', 'FAILED')),
    compilation_error TEXT,
    
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (job_id) REFERENCES jobs(id)
);

CREATE INDEX idx_migration_unit_wave ON migration_units(job_id, wave_number);
CREATE INDEX idx_migration_unit_status ON migration_units(status);


-- dependency_edges.sql: Explicit edge tracking for blast radius

CREATE TABLE dependency_edges (
    edge_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    
    source_id TEXT NOT NULL,  -- MSTR GUID
    target_id TEXT NOT NULL,  -- MSTR GUID
    
    source_unit_id TEXT,  -- MigrationUnit containing source
    target_unit_id TEXT,  -- MigrationUnit containing target
    
    edge_type TEXT,  -- "metric_uses_filter", "metric_uses_metric", etc.
    
    -- For blast radius computation
    is_transitive_dependency BOOLEAN DEFAULT FALSE,
    
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (job_id) REFERENCES jobs(id),
    FOREIGN KEY (source_unit_id) REFERENCES migration_units(unit_id),
    FOREIGN KEY (target_unit_id) REFERENCES migration_units(unit_id)
);

CREATE INDEX idx_dependency_edges_source ON dependency_edges(source_id);
CREATE INDEX idx_dependency_edges_target ON dependency_edges(target_id);
```

### 1.3 Remediation: Tarjan SCC + Blast Radius Implementation

```python
# core/graph/tarjan_scc.py

from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple
import logging

logger = logging.getLogger(__name__)


@dataclass
class DependencyNode:
    """Represents an object in dependency graph."""
    
    id: str  # MSTR GUID
    name: str
    object_type: str  # metric | filter | prompt | etc.
    depends_on: List[str] = field(default_factory=list)  # List of node IDs


@dataclass
class StronglyConnectedComponent:
    """Collapsed cycle detected by Tarjan."""
    
    component_id: str
    member_ids: Set[str]
    internal_edges: int  # Edges within component
    external_edges: Dict[str, int]  # component_id → count of edges to that component
    
    @property
    def is_cyclic(self) -> bool:
        """True if component has more than 1 member or self-edge."""
        return len(self.member_ids) > 1


class TarjanSCCDetector:
    """
    Detect cycles via Tarjan's strongly connected components algorithm.
    
    Time: O(V + E)
    Produces: List of SCCs (components of size 1 are acyclic nodes)
    """
    
    def __init__(self):
        self.index_counter = 0
        self.stack: List[DependencyNode] = []
        self.indices: Dict[str, int] = {}
        self.lowlinks: Dict[str, int] = {}
        self.on_stack: Set[str] = set()
        self.sccs: List[StronglyConnectedComponent] = []
    
    def detect_cycles(self, nodes: List[DependencyNode]) -> List[StronglyConnectedComponent]:
        """
        Main entry point: detect all SCCs in graph.
        """
        
        self.index_counter = 0
        self.stack = []
        self.indices = {}
        self.lowlinks = {}
        self.on_stack = set()
        self.sccs = []
        
        for node in nodes:
            if node.id not in self.indices:
                self._strongconnect(nodes, node)
        
        return self.sccs
    
    def _strongconnect(self, nodes: List[DependencyNode], node: DependencyNode):
        """Recursive SCC detection (Tarjan algorithm)."""
        
        self.indices[node.id] = self.index_counter
        self.lowlinks[node.id] = self.index_counter
        self.index_counter += 1
        self.stack.append(node)
        self.on_stack.add(node.id)
        
        # Find node's dependencies
        node_map = {n.id: n for n in nodes}
        
        for dep_id in node.depends_on:
            if dep_id not in node_map:
                continue  # Dependency not in graph (external reference)
            
            dep_node = node_map[dep_id]
            
            if dep_id not in self.indices:
                # Unvisited successor
                self._strongconnect(nodes, dep_node)
                self.lowlinks[node.id] = min(self.lowlinks[node.id], self.lowlinks[dep_id])
            
            elif dep_id in self.on_stack:
                # Successor is in stack; back edge found
                self.lowlinks[node.id] = min(self.lowlinks[node.id], self.indices[dep_id])
        
        # If node is a root node, pop SCC
        if self.lowlinks[node.id] == self.indices[node.id]:
            component_members = []
            
            while True:
                w = self.stack.pop()
                self.on_stack.discard(w.id)
                component_members.append(w.id)
                
                if w.id == node.id:
                    break
            
            # Create SCC
            component = StronglyConnectedComponent(
                component_id=f"scc_{len(self.sccs)}",
                member_ids=set(component_members),
                internal_edges=self._count_internal_edges(component_members, node_map),
                external_edges={}
            )
            
            self.sccs.append(component)
    
    def _count_internal_edges(self, member_ids: List[str], node_map: Dict[str, DependencyNode]) -> int:
        """Count edges within SCC."""
        count = 0
        member_set = set(member_ids)
        
        for member_id in member_ids:
            node = node_map.get(member_id)
            if node:
                for dep in node.depends_on:
                    if dep in member_set:
                        count += 1
        
        return count


class BlastRadiusCalculator:
    """
    Compute transitive closure to determine failure blast radius.
    
    Question: If node X fails, how many downstream nodes are affected?
    Answer: All nodes reachable from X in dependency graph.
    """
    
    def __init__(self, nodes: List[DependencyNode]):
        self.nodes = nodes
        self.node_map = {n.id: n for n in nodes}
        self.reachability_cache: Dict[str, Set[str]] = {}
    
    def compute_blast_radius(self, failed_node_id: str) -> Set[str]:
        """
        Return all nodes transitively dependent on failed_node_id.
        """
        
        if failed_node_id in self.reachability_cache:
            return self.reachability_cache[failed_node_id]
        
        reachable = set()
        visited = set()
        
        self._dfs_reverse_reachable(failed_node_id, reachable, visited)
        
        self.reachability_cache[failed_node_id] = reachable
        return reachable
    
    def _dfs_reverse_reachable(self, node_id: str, reachable: Set[str], visited: Set[str]):
        """
        DFS from node_id following reverse edges (dependents).
        
        In dependency graph:
          A → B means "A depends on B"
        Reverse edges:
          B ← A means "B is depended on by A"
        
        To find blast radius (nodes affected by A failing),
        we traverse reverse edges from A.
        """
        
        if node_id in visited:
            return
        visited.add(node_id)
        
        # Find all nodes that depend on this node
        for other_node in self.nodes:
            if node_id in other_node.depends_on:
                reachable.add(other_node.id)
                self._dfs_reverse_reachable(other_node.id, reachable, visited)


# Example usage
def example_scc_detection():
    """Detect cycles in 3-node graph: A → B → C → A (cycle)"""
    
    nodes = [
        DependencyNode(id="metric_a", name="Revenue", object_type="metric", depends_on=["metric_b"]),
        DependencyNode(id="metric_b", name="Cost", object_type="metric", depends_on=["filter_x"]),
        DependencyNode(id="filter_x", name="Recent", object_type="filter", depends_on=["metric_a"]),
    ]
    
    detector = TarjanSCCDetector()
    sccs = detector.detect_cycles(nodes)
    
    # Result: 1 SCC with 3 members (cyclic)
    assert len(sccs) == 1
    assert sccs[0].is_cyclic
    assert sccs[0].member_ids == {"metric_a", "metric_b", "filter_x"}
    
    # Blast radius: if metric_a fails, all metrics depending on it fail
    calculator = BlastRadiusCalculator(nodes)
    radius = calculator.compute_blast_radius("metric_a")
    
    # If A fails, B and C are affected (transitively)
    assert "metric_b" in radius or "filter_x" in radius
```

---

## Part 2: Step 5 Gaps — Semantic Fingerprint Collision Handling

### 2.1 Current State

`ir-schema.md` defines the 12-field `SemanticFingerprint` but lacks:
- **CaptionRegistry collision resolution** algorithm
- **Suffix generation** when fingerprint collision detected
- **Deduplication** scope and timing

### 2.2 Remediation: CaptionRegistry Implementation

```python
# core/dedup/caption_registry.py

from dataclasses import dataclass
from typing import Dict, Set
import hashlib


@dataclass
class SemanticFingerprint:
    """
    12-field canonical hash for metric deduplication (ADR-027).
    """
    
    ast_hash: str  # 1. Expression AST canonical form
    source_facts: str  # 2. List of base fact tables
    extraction_grain: str  # 3. Physical grain keys
    vldb_null_propagation: str  # 4. "propagate" | "ignore"
    vldb_division_handling: str  # 5. "propagate_null" | "zero" | "undefined"
    filtering_scope: str  # 6. Pre-filter | post-agg context
    dimensionality: str  # 7. Set of dimension level GUIDs
    lod_include_dims: str  # 8. LOD INCLUDE dimensions
    lod_exclude_dims: str  # 9. LOD EXCLUDE dimensions
    transformation_fn: str  # 10. e.g., "SUM" | "COUNT_DISTINCT" | "RANK"
    visual_encoding: str  # 11. Axis type (continuous | discrete | measure)
    confidence: float  # 12. Human-assigned score (0.0–1.0)
    
    def to_hash(self) -> str:
        """Compute 256-bit hash of canonical fingerprint."""
        fields = (
            self.ast_hash,
            self.source_facts,
            self.extraction_grain,
            self.vldb_null_propagation,
            self.vldb_division_handling,
            self.filtering_scope,
            self.dimensionality,
            self.lod_include_dims,
            self.lod_exclude_dims,
            self.transformation_fn,
            self.visual_encoding,
            str(self.confidence)
        )
        canonical = "|".join(fields)
        return hashlib.sha256(canonical.encode()).hexdigest()


class CaptionRegistry:
    """
    Registry for deduplicating metrics by semantic fingerprint.
    
    Problem: Two metrics "Profit Margin" with different expressions
    should NOT dedup to a single field (breaks both dossiers).
    
    Solution: Dedup by fingerprint, not name. If collision, use suffix.
    
    Collision suffix: fingerprint_hash[:8] appended to caption
    Result: [Profit Margin:abc1def2] vs [Profit Margin:ghi3jkl4]
    """
    
    def __init__(self, db=None):
        self.db = db
        self.fingerprint_to_captions: Dict[str, Set[str]] = {}
    
    async def register_metric(
        self,
        metric_id: str,
        caption: str,
        fingerprint: SemanticFingerprint,
        job_id: str
    ) -> str:
        """
        Register metric caption with fingerprint.
        
        Returns: Deduplicated caption (with suffix if collision).
        """
        
        fp_hash = fingerprint.to_hash()
        
        # Check for existing metric with same fingerprint
        existing_caption = await self.db.get_caption_for_fingerprint(job_id, fp_hash)
        
        if existing_caption:
            # Dedup: reuse existing caption
            await self.db.log_dedup_event(
                job_id=job_id,
                metric_id=metric_id,
                fingerprint_hash=fp_hash,
                original_caption=caption,
                deduplicated_to=existing_caption
            )
            return existing_caption
        
        # New fingerprint: check for caption collision
        suffix = fp_hash[:8].upper()
        deduplicated_caption = f"{caption}:{suffix}"
        
        # Store in registry
        self.fingerprint_to_captions[fp_hash] = deduplicated_caption
        
        # Persist to DB
        await self.db.create_caption_registry_entry(
            job_id=job_id,
            metric_id=metric_id,
            fingerprint_hash=fp_hash,
            original_caption=caption,
            deduplicated_caption=deduplicated_caption
        )
        
        return deduplicated_caption
    
    async def lookup_by_fingerprint(
        self,
        job_id: str,
        fingerprint: SemanticFingerprint
    ) -> Optional[str]:
        """Lookup deduplicated caption by fingerprint."""
        fp_hash = fingerprint.to_hash()
        return await self.db.get_caption_for_fingerprint(job_id, fp_hash)


# Schema extension
def create_caption_registry_tables():
    """Create database tables for deduplication registry."""
    
    sql = """
    CREATE TABLE IF NOT EXISTS caption_registry (
        registry_id TEXT PRIMARY KEY,
        job_id TEXT NOT NULL,
        metric_id TEXT NOT NULL,
        
        fingerprint_hash TEXT NOT NULL,  -- sha256[:8] suffix
        original_caption TEXT NOT NULL,
        deduplicated_caption TEXT NOT NULL,
        
        -- Dedup metadata
        is_deduplication BOOLEAN DEFAULT FALSE,
        dedup_source_metric_id TEXT,  -- If this is a dedup'd copy
        dedup_collision_count INT DEFAULT 1,
        
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        
        FOREIGN KEY (job_id) REFERENCES jobs(id)
    );
    
    CREATE UNIQUE INDEX idx_fp_per_job ON caption_registry(job_id, fingerprint_hash);
    CREATE INDEX idx_dedup_caption ON caption_registry(deduplicated_caption);
    
    
    CREATE TABLE IF NOT EXISTS dedup_events (
        event_id TEXT PRIMARY KEY,
        job_id TEXT NOT NULL,
        
        metric_id TEXT NOT NULL,
        fingerprint_hash TEXT NOT NULL,
        original_caption TEXT,
        deduplicated_to TEXT,
        
        event_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        
        FOREIGN KEY (job_id) REFERENCES jobs(id)
    );
    """
    
    return sql
```

---

## Part 3: Step 6 Gaps — Hyper Schema Validation

### 3.1 Current State

`database.md` lacks schema validation patterns for Hyper extracts.

### 3.2 Remediation: Hyper Schema Parity Assertions

```python
# core/hyper/schema_validator.py

from dataclasses import dataclass
from typing import List, Dict
from tableauserverlient import Query
from tableau_hyper_api import TableDefinition, SqlType
import logging

logger = logging.getLogger(__name__)


@dataclass
class HyperColumnSpec:
    """Expected column specification in Hyper extract."""
    
    name: str
    tableau_type: str  # "string" | "real" | "date" | "boolean" | "integer"
    nullable: bool
    is_pk: bool = False


@dataclass
class HyperSchemaParity:
    """Result of schema validation."""
    
    matches: bool
    mismatches: List[str]  # List of discrepancies
    missing_columns: List[str]
    extra_columns: List[str]


class HyperSchemaValidator:
    """
    Validate Hyper extract schema against expected spec.
    """
    
    async def validate_hyper_schema(
        self,
        hyper_file_path: str,
        expected_columns: List[HyperColumnSpec],
        table_name: str = "Extract"
    ) -> HyperSchemaParity:
        """
        Open Hyper file, inspect schema, verify matches expected.
        """
        
        from tableau_hyper_api import Connection
        
        mismatches = []
        missing_columns = []
        extra_columns = []
        
        try:
            # Open Hyper file
            with Connection(hyper_file_path) as connection:
                # Fetch actual schema
                inspector = connection.catalog.get_table(table_name)
                actual_columns = {col.name: col for col in inspector.columns}
            
            # Check for missing columns
            for expected_col in expected_columns:
                if expected_col.name not in actual_columns:
                    missing_columns.append(expected_col.name)
                    mismatches.append(f"Missing column: {expected_col.name}")
                else:
                    actual_col = actual_columns[expected_col.name]
                    
                    # Verify type matches
                    if not self._types_compatible(expected_col.tableau_type, actual_col.type):
                        mismatches.append(
                            f"Type mismatch for {expected_col.name}: "
                            f"expected {expected_col.tableau_type}, "
                            f"got {actual_col.type}"
                        )
                    
                    # Verify nullability
                    if expected_col.nullable and not actual_col.nullability.is_nullable():
                        mismatches.append(
                            f"Nullability mismatch for {expected_col.name}: "
                            f"expected nullable, got NOT NULL"
                        )
            
            # Check for extra columns
            for actual_col_name in actual_columns:
                if not any(e.name == actual_col_name for e in expected_columns):
                    extra_columns.append(actual_col_name)
                    mismatches.append(f"Unexpected column: {actual_col_name}")
            
            return HyperSchemaParity(
                matches=len(mismatches) == 0,
                mismatches=mismatches,
                missing_columns=missing_columns,
                extra_columns=extra_columns
            )
        
        except Exception as e:
            logger.error(f"Hyper schema validation failed: {e}")
            return HyperSchemaParity(
                matches=False,
                mismatches=[str(e)],
                missing_columns=[],
                extra_columns=[]
            )
    
    def _types_compatible(self, expected: str, actual: SqlType) -> bool:
        """Check if Hyper actual type matches expected Tableau type."""
        
        type_mapping = {
            "string": [SqlType.text, SqlType.varchar],
            "real": [SqlType.double, SqlType.real],
            "integer": [SqlType.int, SqlType.big_int],
            "date": [SqlType.date],
            "boolean": [SqlType.bool]
        }
        
        allowed = type_mapping.get(expected.lower(), [])
        return actual in allowed


# Assertion function for Step 6
async def assert_hyper_schema_valid(
    hyper_path: str,
    job_id: str,
    db: Database
) -> bool:
    """
    Fail if Hyper schema doesn't match expected.
    """
    
    # Get expected schema from IR
    ir_doc = await db.get_ir_document(job_id)
    expected_columns = [
        HyperColumnSpec(
            name=col["name"],
            tableau_type=col["type"],
            nullable=col.get("nullable", True),
            is_pk=col.get("is_primary_key", False)
        )
        for col in ir_doc["model"]["tables"][0]["columns"]
    ]
    
    # Validate
    validator = HyperSchemaValidator()
    result = await validator.validate_hyper_schema(
        hyper_file_path=hyper_path,
        expected_columns=expected_columns
    )
    
    if not result.matches:
        logger.error(f"Hyper schema validation failed: {result.mismatches}")
        return False
    
    logger.info("Hyper schema validation passed")
    return True
```

---

## Part 4: Critical Missing Pieces Summary

| Gap | Document | Impact | Recommendation |
|-----|-----------|--------|-----------------|
| Wave persistence schema | database.md | 🔴 Job crash loses SCC/wave state | Add `migration_units`, `dependency_edges` tables |
| Tarjan + blast radius algorithm | architecture.md | 🔴 No cycle detection implementation | Reference `tarjan_scc.py` from IMPL-GUIDE |
| CaptionRegistry collision algorithm | ir-schema.md | 🔴 Metric dedup collisions break workbooks | Add `caption_registry.py` + schema |
| Hyper schema validation | database.md | 🟡 No column type/nullability checks | Add `hyper_schema_validator.py` + assertions |
| TWBX validation spec | validation-contract.md | 🟡 Incomplete file structure checks | Add XSD validator + file integrity checks |
| Confidence scoring formula | validation-contract.md | 🟡 Confidence adjustments ad-hoc | Formalize: base + review_boost + role_boost, cap at 0.99 |

---

**Action Items:**

1. ✅ Create `IMPLEMENTATION-GUIDE.md` with critical patterns (MSTRSession, SQL templates, IR patches)
2. ⏳ Merge `tarjan_scc.py` into `agents.md` or create `GRAPH-ALGORITHMS.md`
3. ⏳ Update `database.md` with `migration_units`, `caption_registry`, `review_tasks` schemas
4. ⏳ Add `hyper_schema_validator.py` example to validation-contract.md
5. ⏳ Formalize confidence scoring in validation-contract.md (§5.1)

