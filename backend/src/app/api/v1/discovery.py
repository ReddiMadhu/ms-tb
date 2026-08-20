"""
Discovery and object API routes.

Ref: spec/api.md §2 — Discovery, §3 — Objects
"""

import logging
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.v1.schemas import (
    ConnectionValidationResponse,
    DiscoveredDossier,
    DiscoveryRequest,
    DiscoveryResponse,
    MSTRProjectInfo,
    ObjectListResponse,
    ObjectResponse,
)
from app.core.config import settings
from app.db.session import get_db
from app.models.objects import MigrationObject
from app.services.mstr_client.session import (
    MSTRAPIError,
    MSTRAuthError,
    MSTRProjectIdleError,
    MSTRSession,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["discovery"])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Connection Validation (pre-wizard check)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.post("/discovery/validate-connection", response_model=ConnectionValidationResponse)
async def validate_connection(request: DiscoveryRequest):
    """
    POST /discovery/validate-connection — Lightweight connection test.

    Attempts to authenticate with MSTR server using provided credentials,
    retrieves server version and all accessible projects.
    """
    session = MSTRSession(
        base_url=request.mstr_base_url,
        username=request.mstr_username,
        password=request.mstr_password,
        project_id=request.mstr_project_id,
        renewal_margin_s=settings.mstr_token_renewal_margin_s,
    )

    try:
        session.authenticate()

        server_version = None
        try:
            status_resp = session.get_server_status()
            server_version = status_resp.get("version") or status_resp.get("iServerVersion")
        except Exception:
            pass

        projects: list[MSTRProjectInfo] = []
        matched_project_name = None
        try:
            raw_projects = session.list_projects()
            if isinstance(raw_projects, list):
                for p in raw_projects:
                    p_info = MSTRProjectInfo(
                        id=p.get("id", ""),
                        name=p.get("name", "Unnamed"),
                        description=p.get("description"),
                        status=p.get("status"),
                        alias=p.get("alias"),
                    )
                    projects.append(p_info)
                    if request.mstr_project_id and (
                        p_info.id.lower() == request.mstr_project_id.lower()
                        or p_info.name.lower() == request.mstr_project_id.lower()
                    ):
                        matched_project_name = p_info.name
        except Exception as e:
            logger.warning("Could not list projects during validation: %s", e)

        return ConnectionValidationResponse(
            valid=True,
            project_name=matched_project_name or request.mstr_project_id,
            server_version=server_version,
            projects=projects,
        )
    except Exception as e:
        return ConnectionValidationResponse(
            valid=False,
            error=str(e),
        )
    finally:
        try:
            session.close()
        except Exception:
            pass


@router.post("/discovery/projects", response_model=list[MSTRProjectInfo])
async def list_mstr_projects(request: DiscoveryRequest):
    """
    POST /discovery/projects — List all accessible MicroStrategy projects.

    Connects with the provided credentials and returns all available projects.
    """
    session = MSTRSession(
        base_url=request.mstr_base_url,
        username=request.mstr_username,
        password=request.mstr_password,
        project_id="",
        renewal_margin_s=settings.mstr_token_renewal_margin_s,
    )

    try:
        session.authenticate()
        raw_projects = session.list_projects()
        projects: list[MSTRProjectInfo] = []
        if isinstance(raw_projects, list):
            for p in raw_projects:
                projects.append(
                    MSTRProjectInfo(
                        id=p.get("id", ""),
                        name=p.get("name", "Unnamed"),
                        description=p.get("description"),
                        status=p.get("status"),
                        alias=p.get("alias"),
                    )
                )
        return projects
    except MSTRAuthError as e:
        raise HTTPException(status_code=401, detail=f"Authentication failed: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve projects: {e}")
    finally:
        try:
            session.close()
        except Exception:
            pass


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Discovery Endpoints (api.md §2)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.post("/discovery/dossiers", response_model=DiscoveryResponse)
async def discover_dossiers(request: DiscoveryRequest):
    """
    POST /discovery/dossiers — Pre-job dossier scan.

    Connects to MSTR, enumerates all dossiers in the project,
    and returns metadata for the wizard UI to display.
    """
    start = time.monotonic()

    session = MSTRSession(
        base_url=request.mstr_base_url,
        username=request.mstr_username,
        password=request.mstr_password,
        project_id=request.mstr_project_id,
        renewal_margin_s=settings.mstr_token_renewal_margin_s,
    )

    try:
        session.authenticate()

        # Search for dossiers (type 55 = dossier in MSTR)
        # Uses retry-aware method to handle idle/unloaded projects
        raw_dossiers = session.search_objects_with_retry(object_type=55)

        dossiers = []
        for d in raw_dossiers:
            dossiers.append(
                DiscoveredDossier(
                    mstr_id=d.get("id", ""),
                    name=d.get("name", "Unnamed"),
                    path=d.get("ancestors", [{}])[0].get("name", "") if d.get("ancestors") else None,
                    description=d.get("description"),
                    owner=d.get("owner", {}).get("name") if isinstance(d.get("owner"), dict) else None,
                    date_modified=d.get("dateModified"),
                )
            )

        duration_ms = int((time.monotonic() - start) * 1000)

        return DiscoveryResponse(
            dossiers=dossiers,
            total=len(dossiers),
            scan_duration_ms=duration_ms,
        )
    except MSTRAuthError as e:
        logger.error("MSTR authentication failed: %s", e)
        raise HTTPException(status_code=401, detail=f"Authentication failed: {e}")
    except MSTRProjectIdleError as e:
        logger.warning("MSTR project idle after retry: %s", e)
        raise HTTPException(
            status_code=503,
            detail=(
                "The MicroStrategy project is idle or not loaded on the Intelligence Server. "
                "Please try again in a few moments."
            ),
        )
    except MSTRAPIError as e:
        logger.error("MSTR API error during discovery: %s", e)
        raise HTTPException(status_code=502, detail=f"MicroStrategy API error: {e}")
    except Exception as e:
        logger.exception("Unexpected error during dossier discovery")
        raise HTTPException(status_code=500, detail=f"Discovery failed: {e}")
    finally:
        try:
            session.close()
        except Exception:
            pass


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Object Endpoints (api.md §3)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.get("/jobs/{job_id}/objects", response_model=ObjectListResponse)
async def list_objects(
    job_id: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    type_name: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """GET /jobs/{id}/objects — List objects in a migration job with filtering."""
    query = db.query(MigrationObject).filter(MigrationObject.job_id == job_id)

    if type_name:
        query = query.filter(MigrationObject.type_name == type_name)
    if status:
        query = query.filter(MigrationObject.status == status)

    total = query.count()
    objects = query.offset(offset).limit(limit).all()

    return ObjectListResponse(
        objects=[ObjectResponse.model_validate(o) for o in objects],
        total=total,
    )


from sqlalchemy import or_

@router.get("/jobs/{job_id}/objects/{object_id}", response_model=ObjectResponse)
async def get_object(job_id: str, object_id: str, db: Session = Depends(get_db)):
    """GET /jobs/{id}/objects/{oid} — Get detailed object information by id or mstr_id."""
    obj = (
        db.query(MigrationObject)
        .filter(
            MigrationObject.job_id == job_id,
            or_(MigrationObject.id == object_id, MigrationObject.mstr_id == object_id),
        )
        .first()
    )
    if not obj:
        raise HTTPException(status_code=404, detail="Object not found")
    return ObjectResponse.model_validate(obj)
