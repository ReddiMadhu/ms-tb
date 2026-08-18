"""
Dependency Graph Engine — Tarjan's SCC collapse & wave partitioning.

Ref: spec/agents.md §Agent 2 (GraphAgent)
ADR-003: Dependency graph wave partitioning with Tarjan's SCC cycle collapse
ADR-007: Failure isolation & dependency propagation (blast radius)
ADR-014: Skip unused/orphan objects with explicit inventory logging

Step 2 Review Board:
  - Tarjan's SCC condensation of circular dependencies into atomic MigrationUnit nodes
  - 11-Wave Normative Pipeline (Waves 0 to 10)
  - Topological invariant: ∀(u→v), wave(u) ≥ wave(v)
  - Blast radius calculation: FAILED(v) ⟹ all transitive dependents → BLOCKED
  - Orphan inventory with reason codes
"""

import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

import networkx as nx
from sqlalchemy.orm import Session

from app.models.job import Job
from app.models.objects import MigrationObject, WaveExecution, Issue

logger = logging.getLogger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Data Structures
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@dataclass
class MigrationUnit:
    """
    An atomic migration unit — either a single object or a condensed SCC group.

    After Tarjan's SCC collapse, cyclic dependency groups become a single MigrationUnit
    containing multiple objects that must be processed together.
    """
    unit_id: int
    objects: list[str] = field(default_factory=list)  # MSTR GUIDs
    internal_edges: list[tuple[str, str]] = field(default_factory=list)
    external_dependencies: dict[int, list[str]] = field(default_factory=dict)  # scc_id → [edge objects]
    wave: int = -1
    status: str = "PENDING"


@dataclass
class TopologyViolation:
    """A violation of the topological invariant."""
    source_wave: int
    source_unit: int
    target_wave: int


@dataclass
class OrphanRecord:
    """An object skipped as orphan/unused."""
    mstr_id: str
    name: str
    object_type: str
    reason: str  # "unused_per_stats", "unused_per_dependency", "inaccessible", "unsupported"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  11-Wave Normative Pipeline (Step 2 Review Board)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

WAVE_NAMES = {
    0: "Physical Table Resolution",
    1: "Attribute & Fact Extraction",
    2: "Metric Semantic Extraction",
    3: "Metric Expression Compilation (IR)",
    4: "Semantic Fingerprinting & Deduplication",
    5: "AI Translation (Low-Confidence)",
    6: "Visualization Planning",
    7: "Datasource & Workbook XML Emission",
    8: "Staging Publication & Multi-Gate Validation",
    9: "Promotion Precheck",
    10: "Production Promotion",
}


class DependencyGraph:
    """
    Builds, condenses, and partitions the MSTR object dependency graph.

    Processing pipeline:
    1. Build directed graph from object dependency_ids
    2. Run Tarjan's SCC algorithm to detect cycles
    3. Condense cycles into atomic MigrationUnit nodes
    4. Topologically sort the condensed DAG
    5. Assign wave numbers per the 11-Wave Normative Pipeline
    6. Calculate blast radius for failure propagation
    7. Identify orphan objects with no transitive dependents
    """

    def __init__(self, db: Session, job: Job):
        self.db = db
        self.job = job
        self._graph: Optional[nx.DiGraph] = None
        self._condensed: Optional[nx.DiGraph] = None
        self._units: dict[int, MigrationUnit] = {}
        self._object_to_scc: dict[str, int] = {}
        self._orphans: list[OrphanRecord] = []

    def build(self) -> dict:
        """
        Execute the full graph compilation pipeline.

        Returns summary dict with wave assignments and orphan counts.
        """
        # Step 1: Build raw dependency graph
        self._build_raw_graph()

        # Step 2: Tarjan's SCC collapse
        self._collapse_sccs()

        # Step 3: Topological sort & wave assignment
        self._assign_waves()

        # Step 4: Verify topological invariant
        violations = self._verify_topological_invariant()
        if violations:
            logger.error(
                "TOPOLOGICAL INVARIANT VIOLATED: %d violations detected",
                len(violations),
            )
            raise RuntimeError(
                f"Topological invariant violated: {len(violations)} violations"
            )

        # Step 5: Identify orphans
        self._identify_orphans()

        # Step 6: Persist wave assignments
        self._persist_wave_assignments()

        summary = {
            "total_objects": self._graph.number_of_nodes() if self._graph else 0,
            "total_edges": self._graph.number_of_edges() if self._graph else 0,
            "scc_count": len(self._units),
            "multi_object_sccs": sum(1 for u in self._units.values() if len(u.objects) > 1),
            "wave_count": max((u.wave for u in self._units.values()), default=0) + 1,
            "orphan_count": len(self._orphans),
        }
        logger.info("Graph compilation complete: %s", summary)
        return summary

    # ── Step 1: Build raw dependency graph ──────────────────────

    def _build_raw_graph(self):
        """Build a directed graph from object dependency_ids."""
        self._graph = nx.DiGraph()

        objects = (
            self.db.query(MigrationObject)
            .filter(MigrationObject.job_id == self.job.id)
            .all()
        )

        for obj in objects:
            self._graph.add_node(obj.mstr_id, type_name=obj.type_name, name=obj.name)

            if obj.dependency_ids:
                for dep_id in obj.dependency_ids:
                    if dep_id:  # skip empty strings
                        self._graph.add_edge(obj.mstr_id, dep_id)

        logger.info(
            "Built dependency graph: %d nodes, %d edges",
            self._graph.number_of_nodes(),
            self._graph.number_of_edges(),
        )

    # ── Step 2: Tarjan's SCC collapse ───────────────────────────

    def _collapse_sccs(self):
        """
        Run Tarjan's SCC algorithm and condense cycles into MigrationUnit nodes.

        Circular dependencies (Metric ↔ Filter ↔ Prompt) are collapsed into
        atomic units that must be processed together.
        """
        sccs = list(nx.strongly_connected_components(self._graph))

        for scc_id, scc in enumerate(sccs):
            scc_list = sorted(scc)

            # Map each object to its SCC
            for obj_id in scc_list:
                self._object_to_scc[obj_id] = scc_id

            # Build internal edges (within SCC)
            internal_edges = [
                (u, v)
                for u, v in self._graph.edges()
                if u in scc and v in scc
            ]

            unit = MigrationUnit(
                unit_id=scc_id,
                objects=scc_list,
                internal_edges=internal_edges,
            )
            self._units[scc_id] = unit

        # Build external dependencies between SCCs
        for scc_id, unit in self._units.items():
            for obj_id in unit.objects:
                for successor in self._graph.successors(obj_id):
                    dep_scc = self._object_to_scc.get(successor)
                    if dep_scc is not None and dep_scc != scc_id:
                        if dep_scc not in unit.external_dependencies:
                            unit.external_dependencies[dep_scc] = []
                        unit.external_dependencies[dep_scc].append(successor)

        # Build condensed DAG
        self._condensed = nx.DiGraph()
        for scc_id in self._units:
            self._condensed.add_node(scc_id)
        for scc_id, unit in self._units.items():
            for dep_scc in unit.external_dependencies:
                self._condensed.add_edge(scc_id, dep_scc)

        multi_count = sum(1 for u in self._units.values() if len(u.objects) > 1)
        if multi_count:
            logger.warning(
                "Detected %d multi-object SCCs (circular dependencies)", multi_count
            )

    # ── Step 3: Topological sort & wave assignment ──────────────

    def _assign_waves(self):
        """
        Assign wave numbers using reverse topological order.

        Leaf nodes (no dependencies) get wave 0.
        Each subsequent layer gets wave = max(dependency waves) + 1.
        """
        if not self._condensed:
            return

        # Reverse topological order — process leaves first
        try:
            topo_order = list(nx.topological_sort(self._condensed))
        except nx.NetworkXUnfeasible:
            raise RuntimeError("Condensed graph still contains cycles — SCC collapse failed")

        # Reverse so leaves are processed first
        topo_order.reverse()

        for scc_id in topo_order:
            unit = self._units[scc_id]
            if not unit.external_dependencies:
                unit.wave = 0
            else:
                max_dep_wave = max(
                    self._units[dep_scc].wave
                    for dep_scc in unit.external_dependencies
                )
                unit.wave = max_dep_wave + 1

        # Update job with total wave count
        max_wave = max((u.wave for u in self._units.values()), default=0)
        self.job.total_waves = max_wave + 1
        self.db.commit()

    # ── Step 4: Verify topological invariant ────────────────────

    def _verify_topological_invariant(self) -> list[TopologyViolation]:
        """
        Verify: ∀(u→v), wave(u) ≥ wave(v).

        This ensures that every dependency is processed before or in the same wave
        as its dependent.
        """
        violations = []
        for scc_id, unit in self._units.items():
            for dep_scc in unit.external_dependencies:
                dep_unit = self._units[dep_scc]
                if unit.wave < dep_unit.wave:
                    violations.append(
                        TopologyViolation(unit.wave, scc_id, dep_unit.wave)
                    )
        return violations

    # ── Step 5: Identify orphans ────────────────────────────────

    def _identify_orphans(self):
        """
        Identify objects with no transitive dependents (ADR-014).

        These are skipped with an explicit audit inventory.
        """
        if not self._graph or not self.job.skip_unused:
            return

        # Objects with no predecessors (nothing depends on them)
        # AND no dossier container (not referenced by any dossier)
        dossier_nodes = {
            n for n in self._graph.nodes()
            if self._graph.nodes[n].get("type_name") == "dossier"
        }

        # Find all objects reachable from dossiers (the useful subgraph)
        reachable = set()
        for dossier in dossier_nodes:
            reachable.update(nx.descendants(self._graph, dossier))
            reachable.add(dossier)

        # Anything not reachable is orphan
        for node in self._graph.nodes():
            if node not in reachable:
                node_data = self._graph.nodes[node]
                self._orphans.append(
                    OrphanRecord(
                        mstr_id=node,
                        name=node_data.get("name", ""),
                        object_type=node_data.get("type_name", ""),
                        reason="unused_per_dependency",
                    )
                )
                # Mark in DB
                obj = (
                    self.db.query(MigrationObject)
                    .filter(
                        MigrationObject.job_id == self.job.id,
                        MigrationObject.mstr_id == node,
                    )
                    .first()
                )
                if obj:
                    obj.status = "skipped"
                    self.job.objects_skipped = (self.job.objects_skipped or 0) + 1

        if self._orphans:
            logger.info("Identified %d orphan objects", len(self._orphans))
        self.db.commit()

    # ── Step 6: Persist wave assignments ────────────────────────

    def _persist_wave_assignments(self):
        """Persist wave execution state to SQLite for crash recovery (ADR-003)."""
        import hashlib

        for scc_id, unit in self._units.items():
            dep_hash = hashlib.sha256(
                str(sorted(unit.external_dependencies.keys())).encode()
            ).hexdigest()

            for obj_id in unit.objects:
                wave_exec = WaveExecution(
                    job_id=self.job.id,
                    wave_id=unit.wave,
                    scc_id=scc_id,
                    object_id=obj_id,
                    dependency_hash=dep_hash,
                    status="PENDING",
                )
                self.db.merge(wave_exec)

        self.db.commit()

    # ── Blast Radius Calculation (ADR-007) ──────────────────────

    def calculate_blast_radius(self, failed_object_id: str) -> set[str]:
        """
        Compute transitive closure of all objects that become BLOCKED
        when `failed_object_id` fails (ADR-007).

        FAILED(v) ⟹ ∀u transitively depending on v: status(u) ∈ {BLOCKED, REVIEW_REQUIRED}
        """
        if not self._graph:
            return set()

        # Find all predecessors (objects that depend on the failed object)
        visited: set[str] = set()
        queue = [failed_object_id]

        while queue:
            curr = queue.pop(0)
            if curr in visited:
                continue
            visited.add(curr)

            # Find all objects that depend on curr (predecessors in the dependency graph)
            for predecessor in self._graph.predecessors(curr):
                if predecessor not in visited:
                    queue.append(predecessor)

        visited.discard(failed_object_id)  # don't include the failed object itself
        return visited

    def propagate_failure(self, failed_object_id: str):
        """
        Propagate a failure: mark all transitively dependent objects as BLOCKED.
        """
        blocked = self.calculate_blast_radius(failed_object_id)

        for mstr_id in blocked:
            obj = (
                self.db.query(MigrationObject)
                .filter(
                    MigrationObject.job_id == self.job.id,
                    MigrationObject.mstr_id == mstr_id,
                )
                .first()
            )
            if obj and obj.status not in ("failed", "skipped"):
                obj.status = "failed"
                obj.blocker_count = (obj.blocker_count or 0) + 1

                issue = Issue(
                    id=str(uuid.uuid4()),
                    job_id=self.job.id,
                    object_id=obj.id,
                    severity="blocker",
                    category="blocked_dependency",
                    message=f"Blocked by failed dependency: {failed_object_id}",
                    affected_objects=[failed_object_id],
                )
                self.db.add(issue)

        self.db.commit()

        logger.info(
            "Failure propagated from %s → %d objects blocked",
            failed_object_id,
            len(blocked),
        )

    # ── Accessors ───────────────────────────────────────────────

    @property
    def units(self) -> dict[int, MigrationUnit]:
        return self._units

    @property
    def orphans(self) -> list[OrphanRecord]:
        return self._orphans

    def get_wave_units(self, wave: int) -> list[MigrationUnit]:
        """Get all MigrationUnits assigned to a specific wave."""
        return [u for u in self._units.values() if u.wave == wave]
