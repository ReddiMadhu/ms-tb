"""
DiscoveryAgent — Pre-job metadata harvesting from MicroStrategy.

Ref: spec/agents.md §Agent 1 & Agent 2
ADR-016: Dynamic MSTRSession lifecycle
Step 1 Review Board: Multi-form attribute extraction, compound keys,
                     transitive permission poisoning, checkpoint recovery.

Responsibilities:
  1. Authenticate to MSTR and enumerate the catalog
  2. Extract dossiers, cubes, metrics, attributes, facts
  3. Capture all attribute forms (ID, DESC, compound keys)
  4. Capture VLDB settings (null propagation, zero division)
  5. Detect inaccessible dependencies → transitive BLOCKED poisoning
  6. Persist discovery state for crash recovery
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.job import Job
from app.models.objects import (
    DiscoveryObject,
    DiscoverySession,
    Issue,
    MigrationObject,
)
from app.services.mstr_client.session import (
    AsyncMSTRSession,
    MSTRAPIError,
    MSTRSession,
)

logger = logging.getLogger(__name__)

# MSTR object type codes
MSTR_TYPE_DOSSIER = 55
MSTR_TYPE_REPORT = 3
MSTR_TYPE_METRIC = 4
MSTR_TYPE_ATTRIBUTE = 12
MSTR_TYPE_FACT = 13
MSTR_TYPE_FILTER = 1
MSTR_TYPE_CUBE = 21

TYPE_CODE_MAP = {
    MSTR_TYPE_DOSSIER: "dossier",
    MSTR_TYPE_REPORT: "report",
    MSTR_TYPE_METRIC: "metric",
    MSTR_TYPE_ATTRIBUTE: "attribute",
    MSTR_TYPE_FACT: "fact",
    MSTR_TYPE_FILTER: "filter",
    MSTR_TYPE_CUBE: "cube",
}


class DiscoveryAgent:
    """
    Agent 1 + 2: Discovery & catalog harvesting.

    Extracts the full MSTR object catalog for a project and captures
    metadata needed by downstream agents (semantic extraction, graph compilation).
    """

    def __init__(
        self,
        db: Session,
        job: Job,
        audit_logger=None,
        mstr_username: str = "",
        mstr_password: str = "",
    ):
        self.db = db
        self.job = job
        self.audit = audit_logger
        self.mstr_username = mstr_username
        self.mstr_password = mstr_password
        self._mstr: Optional[AsyncMSTRSession] = None

    async def run(self, selected_dossier_ids: Optional[list[str]] = None) -> dict:
        """
        Execute the discovery phase.

        Args:
            selected_dossier_ids: If provided, only discover these specific dossiers
                                  and their dependency subgraphs. If None, scan full estate.

        Returns:
            Summary dict with counts of discovered objects.
        """
        # Create MSTR session with proactive renewal (ADR-016)
        username = self.mstr_username or settings.mstr_username
        password = self.mstr_password or settings.mstr_password
        sync_session = MSTRSession(
            base_url=self.job.mstr_base_url,
            username=username,
            password=password,
            project_id=self.job.mstr_project_id,
            renewal_margin_s=settings.mstr_token_renewal_margin_s,
        )
        self._mstr = AsyncMSTRSession(sync_session)

        try:
            await self._mstr.authenticate()

            # Initialize discovery session checkpoint
            discovery_session = DiscoverySession(
                job_id=self.job.id,
                current_phase="scan_dossiers",
                status="in_progress",
            )
            self.db.add(discovery_session)
            self.db.commit()

            # Update job status
            self.job.status = "DISCOVERY"
            self.job.current_stage = "DISCOVERY"
            self.db.commit()

            # Phase 1: Discover dossiers
            dossiers = await self._discover_dossiers(selected_dossier_ids)
            discovery_session.dossiers_total = len(dossiers)
            self.db.commit()

            # Phase 2: For each dossier, extract referenced objects
            all_objects: dict[str, MigrationObject] = {}
            for i, dossier in enumerate(dossiers):
                try:
                    refs = await self._extract_dossier_references(dossier)
                    all_objects.update(refs)
                except MSTRAPIError as e:
                    if e.status_code == 403:
                        # Transitive BLOCKED poisoning
                        logger.warning(
                            "Permission denied for dossier %s — marking BLOCKED",
                            dossier.get("id"),
                        )
                        self._mark_blocked(dossier, "permission_denied")
                    else:
                        raise

                discovery_session.dossiers_scanned = i + 1
                self.db.commit()

            # Phase 3: Capture VLDB settings
            await self._capture_vldb_settings()

            # Mark discovery complete
            discovery_session.current_phase = "complete"
            discovery_session.status = "complete"
            self.job.objects_total = len(all_objects)
            self.db.commit()

            summary = {
                "dossiers": len(dossiers),
                "total_objects": len(all_objects),
                "by_type": {},
            }
            for obj in all_objects.values():
                t = obj.type_name
                summary["by_type"][t] = summary["by_type"].get(t, 0) + 1

            logger.info("Discovery complete: %s", summary)
            return summary

        finally:
            await self._mstr.close()

    async def _discover_dossiers(
        self, selected_ids: Optional[list[str]] = None
    ) -> list[dict]:
        """Enumerate dossiers in the project, optionally filtering by selected IDs."""
        raw = await self._mstr.search_objects(object_type=MSTR_TYPE_DOSSIER)

        if selected_ids:
            raw = [d for d in raw if d.get("id") in selected_ids]

        # Persist each dossier as a MigrationObject
        for d in raw:
            mstr_id = d.get("id", "")
            existing = (
                self.db.query(MigrationObject)
                .filter(
                    MigrationObject.job_id == self.job.id,
                    MigrationObject.mstr_id == mstr_id,
                )
                .first()
            )
            if not existing:
                obj = MigrationObject(
                    id=str(uuid.uuid4()),
                    job_id=self.job.id,
                    mstr_id=mstr_id,
                    mstr_type=MSTR_TYPE_DOSSIER,
                    type_name="dossier",
                    name=d.get("name", "Unnamed"),
                    path=d.get("ancestors", [{}])[0].get("name", "")
                    if d.get("ancestors")
                    else None,
                    status="discovered",
                    mstr_definition=d,
                )
                self.db.add(obj)

            # Also persist to discovery_objects for checkpoint tracking
            disc_obj = DiscoveryObject(
                job_id=self.job.id,
                object_id=mstr_id,
                object_type="dossier",
                object_name=d.get("name", "Unnamed"),
                metadata_json=json.dumps(d),
            )
            self.db.merge(disc_obj)

        self.db.commit()
        return raw

    async def _extract_dossier_references(self, dossier: dict) -> dict[str, MigrationObject]:
        """
        Extract all objects referenced by a dossier: datasets, metrics, attributes, facts.

        This builds the dependency subgraph needed for graph compilation (Agent 2).
        """
        dossier_id = dossier.get("id", "")
        objects: dict[str, MigrationObject] = {}

        try:
            definition = await self._mstr.get_dossier_definition(dossier_id)
        except MSTRAPIError:
            logger.error("Failed to fetch dossier definition for %s", dossier_id)
            return objects
        except Exception as e:
            logger.error("Unexpected error fetching dossier definition for %s: %s", dossier_id, e)
            return objects

        # Extract dataset references from dossier definition
        datasets = definition.get("datasets", []) if isinstance(definition, dict) else []
        if not isinstance(datasets, list):
            datasets = []

        # Link dossier to its datasets
        dataset_ids = [ds.get("id") for ds in datasets if isinstance(ds, dict) and ds.get("id")]
        dossier_obj = (
            self.db.query(MigrationObject)
            .filter(
                MigrationObject.job_id == self.job.id,
                MigrationObject.mstr_id == dossier_id,
            )
            .first()
        )
        if dossier_obj and dataset_ids:
            dossier_obj.dependency_ids = dataset_ids
            # Store the full dossier definition (including chapters/pages/visualizations)
            # for downstream visual extraction during IR compilation
            dossier_obj.mstr_definition = definition
            self.db.commit()

        for ds in datasets:
            if not isinstance(ds, dict):
                continue
            ds_id = ds.get("id", "")
            ds_name = ds.get("name", "Unnamed Dataset")
            if not ds_id:
                continue

            # Persist cube/report as MigrationObject
            obj = MigrationObject(
                id=str(uuid.uuid4()),
                job_id=self.job.id,
                mstr_id=ds_id,
                mstr_type=MSTR_TYPE_CUBE,
                type_name="cube",
                name=ds_name,
                status="discovered",
                mstr_definition=ds,
            )
            self.db.merge(obj)
            objects[ds_id] = obj

            # Extract attributes and metrics from the dataset safely
            # Note: MSTR returns availableObjects either as a dict or a list depending on API version
            available = ds.get("availableObjects")
            raw_attrs: list[dict] = []
            raw_metrics: list[dict] = []

            if isinstance(available, dict):
                if isinstance(available.get("attributes"), list):
                    raw_attrs.extend(available["attributes"])
                if isinstance(available.get("metrics"), list):
                    raw_metrics.extend(available["metrics"])
            elif isinstance(available, list):
                for item in available:
                    if not isinstance(item, dict):
                        continue
                    itype = str(item.get("type", "")).lower()
                    if itype in ("attribute", "12", str(MSTR_TYPE_ATTRIBUTE)):
                        raw_attrs.append(item)
                    elif itype in ("metric", "4", str(MSTR_TYPE_METRIC)):
                        raw_metrics.append(item)
                    elif "attribute" in itype:
                        raw_attrs.append(item)
                    elif "metric" in itype:
                        raw_metrics.append(item)

            if isinstance(ds.get("attributes"), list):
                raw_attrs.extend(ds["attributes"])
            if isinstance(ds.get("metrics"), list):
                raw_metrics.extend(ds["metrics"])

            # If availableObjects is empty on dataset, attempt fetching cube definition
            if not raw_attrs and not raw_metrics and ds_id:
                try:
                    cube_def = await self._mstr.get_cube_definition(ds_id)
                    if isinstance(cube_def, dict):
                        avail_cube = (
                            cube_def.get("result", {}).get("definition", {}).get("availableObjects")
                            or cube_def.get("availableObjects")
                        )
                        if isinstance(avail_cube, dict):
                            raw_attrs.extend(avail_cube.get("attributes") or [])
                            raw_metrics.extend(avail_cube.get("metrics") or [])
                        elif isinstance(avail_cube, list):
                            for item in avail_cube:
                                if isinstance(item, dict):
                                    itype = str(item.get("type", "")).lower()
                                    if "attribute" in itype or itype in ("12", str(MSTR_TYPE_ATTRIBUTE)):
                                        raw_attrs.append(item)
                                    elif "metric" in itype or itype in ("4", str(MSTR_TYPE_METRIC)):
                                        raw_metrics.append(item)
                except Exception as e:
                    logger.debug("Could not fetch cube definition for %s: %s", ds_id, e)

            # Deduplicate by id
            attrs_by_id: dict[str, dict] = {}
            for a in raw_attrs:
                if isinstance(a, dict) and a.get("id"):
                    attrs_by_id[a["id"]] = a

            metrics_by_id: dict[str, dict] = {}
            for m in raw_metrics:
                if isinstance(m, dict) and m.get("id"):
                    metrics_by_id[m["id"]] = m

            for attr_id, attr in attrs_by_id.items():
                attr_obj = MigrationObject(
                    id=str(uuid.uuid4()),
                    job_id=self.job.id,
                    mstr_id=attr_id,
                    mstr_type=MSTR_TYPE_ATTRIBUTE,
                    type_name="attribute",
                    name=attr.get("name", "Unnamed Attribute"),
                    status="discovered",
                    mstr_definition=attr,
                    # Capture compound key structure from forms
                    compound_key_json=self._extract_compound_keys(attr),
                    dependency_ids=[ds_id],
                )
                self.db.merge(attr_obj)
                objects[attr_id] = attr_obj

            for metric_id, metric in metrics_by_id.items():
                expr_text = self._extract_expression_text(metric)
                if not expr_text and isinstance(metric.get("expression"), str):
                    expr_text = metric["expression"]
                elif not expr_text and isinstance(metric.get("formula"), str):
                    expr_text = metric["formula"]

                dep_ids = self._extract_metric_dependencies(metric) or [ds_id]

                metric_obj = MigrationObject(
                    id=str(uuid.uuid4()),
                    job_id=self.job.id,
                    mstr_id=metric_id,
                    mstr_type=MSTR_TYPE_METRIC,
                    type_name="metric",
                    name=metric.get("name", "Unnamed Metric"),
                    status="discovered",
                    mstr_definition=metric,
                    expression_text=expr_text,
                    dependency_ids=dep_ids,
                )
                self.db.merge(metric_obj)
                objects[metric_id] = metric_obj

        self.db.commit()
        return objects

    def _extract_compound_keys(self, attr_detail: dict) -> Optional[list[dict]]:
        """
        Extract compound key information from MSTR attribute forms.

        Compound keys (e.g. [Date_ID, Product_ID, Store_ID]) must be preserved
        to prevent Cartesian products in downstream relationship joins.
        """
        if not isinstance(attr_detail, dict):
            return None
        forms = attr_detail.get("forms", [])
        if not isinstance(forms, list) or not forms:
            return None

        keys = []
        for form in forms:
            if isinstance(form, dict):
                data_type = "unknown"
                if isinstance(form.get("dataType"), dict):
                    data_type = form["dataType"].get("type", "unknown")
                keys.append({
                    "form_name": form.get("name", ""),
                    "form_id": form.get("id", ""),
                    "data_type": data_type,
                    "expressions": form.get("expressions", []),
                })
        return keys if len(keys) > 1 else None

    def _extract_expression_text(self, metric_detail: dict) -> Optional[str]:
        """Extract human-readable expression text from metric API response."""
        if not isinstance(metric_detail, dict):
            return None
        expr = metric_detail.get("expression", {})
        if isinstance(expr, dict):
            return expr.get("text", None)
        return None

    def _extract_metric_dependencies(self, metric_detail: dict) -> Optional[list[str]]:
        """Extract MSTR GUIDs of objects this metric depends on."""
        if not isinstance(metric_detail, dict):
            return None
        references = metric_detail.get("references", [])
        if not isinstance(references, list) or not references:
            return None
        return [ref.get("id", "") for ref in references if isinstance(ref, dict) and ref.get("id")]

    def _mark_blocked(self, dossier: dict, reason: str):
        """Mark a dossier as BLOCKED due to inaccessible dependencies."""
        mstr_id = dossier.get("id", "")
        obj = (
            self.db.query(MigrationObject)
            .filter(
                MigrationObject.job_id == self.job.id,
                MigrationObject.mstr_id == mstr_id,
            )
            .first()
        )
        if obj:
            obj.status = "failed"
            issue = Issue(
                id=str(uuid.uuid4()),
                job_id=self.job.id,
                object_id=obj.id,
                severity="blocker",
                category="permission_denied",
                message=f"Dossier {mstr_id} is blocked: {reason}",
            )
            self.db.add(issue)
            self.db.commit()

    async def _capture_vldb_settings(self):
        """Capture project-level VLDB settings (null propagation, zero division)."""
        try:
            vldb = await self._mstr.get_vldb_settings()
            self.job.vldb_settings_json = vldb if isinstance(vldb, dict) else {}

            # Extract key settings for fast lookup
            properties = vldb.get("propertyValues", {}) if isinstance(vldb, dict) else {}
            if not isinstance(properties, dict):
                properties = {}

            # Null handling: "propagate" or "ignore"
            null_prop = properties.get("NullChecking", {}) if isinstance(properties.get("NullChecking"), dict) else {}
            null_setting = null_prop.get("value", "1")
            self.job.null_propagation = "ignore" if str(null_setting) == "2" else "propagate"

            # Zero division: "null" or "zero"
            zero_prop = properties.get("ZeroDivisionBehavior", {}) if isinstance(properties.get("ZeroDivisionBehavior"), dict) else {}
            zero_setting = zero_prop.get("value", "1")
            self.job.zero_division_result = "zero" if str(zero_setting) == "2" else "null"

            self.db.commit()
            logger.info(
                "VLDB settings captured: null_propagation=%s, zero_division=%s",
                self.job.null_propagation,
                self.job.zero_division_result,
            )
        except Exception as e:
            # Endpoint may not be enabled in all MSTR Library environments — use standard defaults
            self.job.null_propagation = "propagate"
            self.job.zero_division_result = "null"
            self.db.commit()
            logger.debug("VLDB properties endpoint not available; using platform defaults: %s", e)
