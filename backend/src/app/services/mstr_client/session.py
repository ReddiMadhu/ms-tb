"""
MicroStrategy REST API session manager with proactive token renewal.

Ref: spec/agents.md §Agent 1 (DiscoveryAgent), Step 1 Review Board
ADR-016: Dynamic MSTRSession lifecycle — proactive token re-auth with margin,
         404 instance recreation, no fixed TTL assumptions.

Key behaviors:
  - Proactive renewal: re-authenticates `renewal_margin_s` seconds before TTL expiry.
  - 401 auto-retry: on token rejection, re-auth and replay the request once.
  - 404 cube instance re-creation: cube instances expire after ~10 min idle.
  - All I/O wrapped for asyncio.to_thread() compatibility (ADR-019).
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


class MSTRAuthError(Exception):
    """Raised when MSTR authentication fails."""
    pass


class MSTRInstanceExpiredError(Exception):
    """Raised when a cube/report instance has expired (404)."""
    pass


class MSTRProjectIdleError(Exception):
    """Raised when the MSTR project is idle/unloaded on the Intelligence Server (iServerCode -2147209151)."""

    def __init__(self, project_id: str, message: str = ""):
        self.project_id = project_id
        super().__init__(
            message or f"MSTR project {project_id} is idle or not loaded on the Intelligence Server"
        )


class MSTRAPIError(Exception):
    """Raised for non-recoverable MSTR API errors."""

    def __init__(self, status_code: int, message: str, url: str):
        self.status_code = status_code
        self.url = url
        super().__init__(f"MSTR API {status_code} at {url}: {message}")


class MSTRSession:
    """
    Manages authenticated sessions against MicroStrategy REST API.

    This class handles:
    1. Initial authentication via POST /api/auth/login
    2. Proactive token renewal before TTL expiry
    3. Transparent 401 retry with re-authentication
    4. Cube instance lifecycle (creation, pagination, 404 re-creation)
    5. Project selection via X-MSTR-ProjectID header
    """

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        project_id: str,
        renewal_margin_s: int = 60,
        timeout_s: int = 120,
    ):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.project_id = project_id
        self.renewal_margin_s = renewal_margin_s

        self._token: Optional[str] = None
        self._token_acquired_at: float = 0
        self._token_ttl_s: float = 1800  # default; updated from server response
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout_s,
            follow_redirects=True,
        )

    # ── Authentication ──────────────────────────────────────────

    def authenticate(self) -> str:
        """Authenticate and obtain a session token."""
        resp = self._client.post(
            "/api/auth/login",
            json={"username": self.username, "password": self.password},
        )
        if resp.status_code != 204:
            raise MSTRAuthError(
                f"Authentication failed: {resp.status_code} {resp.text}"
            )

        self._token = resp.headers.get("X-MSTR-AuthToken")
        if not self._token:
            raise MSTRAuthError("No X-MSTR-AuthToken in login response")

        self._token_acquired_at = time.monotonic()

        # Try to parse TTL from response headers or body
        # MSTR typically returns a timeout header
        timeout_header = resp.headers.get("X-MSTR-SessionTimeout")
        if timeout_header:
            try:
                self._token_ttl_s = float(timeout_header)
            except ValueError:
                pass

        logger.info(
            "MSTR authenticated (TTL=%ds, renewal_margin=%ds)",
            self._token_ttl_s,
            self.renewal_margin_s,
        )
        return self._token

    def _ensure_authenticated(self):
        """Proactively renew token if within renewal margin of TTL expiry."""
        if not self._token:
            self.authenticate()
            return

        elapsed = time.monotonic() - self._token_acquired_at
        remaining = self._token_ttl_s - elapsed

        if remaining <= self.renewal_margin_s:
            logger.info(
                "Proactive token renewal (remaining=%ds, margin=%ds)",
                remaining,
                self.renewal_margin_s,
            )
            self.authenticate()

    @property
    def _headers(self) -> dict[str, str]:
        """Standard headers for all MSTR API calls."""
        return {
            "X-MSTR-AuthToken": self._token or "",
            "X-MSTR-ProjectID": self.project_id,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # ── Core HTTP methods ───────────────────────────────────────

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: Optional[dict] = None,
        retry_on_401: bool = True,
    ) -> httpx.Response:
        """
        Execute an authenticated MSTR API request.

        Handles:
        - Proactive token renewal before TTL expiry
        - 401 → re-authenticate → retry once
        - 404 on instance endpoints → raise MSTRInstanceExpiredError
        """
        self._ensure_authenticated()

        start = time.monotonic()
        resp = self._client.request(
            method,
            path,
            headers=self._headers,
            json=json,
            params=params,
        )
        duration_ms = int((time.monotonic() - start) * 1000)

        # 401 — token rejected, re-auth and retry once
        if resp.status_code == 401 and retry_on_401:
            logger.warning("MSTR 401 on %s %s — re-authenticating", method, path)
            self.authenticate()
            return self._request(method, path, json=json, params=params, retry_on_401=False)

        # 404 on cube/report instance — instance expired
        if resp.status_code == 404 and "/instances" in path:
            raise MSTRInstanceExpiredError(f"Instance expired at {path}")

        # 404 with iServerCode -2147209151 — project idle/not loaded
        if resp.status_code == 404:
            try:
                body = resp.json()
                if body.get("iServerCode") == -2147209151:
                    raise MSTRProjectIdleError(
                        project_id=self.project_id,
                        message=body.get("message", "Project is idle or not loaded"),
                    )
            except (json.JSONDecodeError, KeyError):
                pass  # not the idle-project pattern, fall through

        # 403 — permission denied (used for transitive BLOCKED poisoning)
        if resp.status_code == 403:
            raise MSTRAPIError(403, "Forbidden — insufficient permissions", path)

        if resp.status_code >= 400:
            raise MSTRAPIError(resp.status_code, resp.text[:500], path)

        return resp

    def get(self, path: str, **kwargs) -> httpx.Response:
        return self._request("GET", path, **kwargs)

    def post(self, path: str, **kwargs) -> httpx.Response:
        return self._request("POST", path, **kwargs)

    def put(self, path: str, **kwargs) -> httpx.Response:
        return self._request("PUT", path, **kwargs)

    def delete(self, path: str, **kwargs) -> httpx.Response:
        return self._request("DELETE", path, **kwargs)

    # ── High-Level MSTR Object Access ───────────────────────────

    def get_server_status(self) -> dict:
        """GET /api/status — check server availability and version."""
        resp = self.get("/api/status")
        return resp.json()

    def list_projects(self) -> list[dict]:
        """GET /api/projects — list accessible projects."""
        resp = self.get("/api/projects")
        return resp.json()

    def search_objects(
        self,
        object_type: Optional[int] = None,
        name: Optional[str] = None,
        root_folder_id: Optional[str] = None,
        offset: int = 0,
        limit: int = 1000,
    ) -> list[dict]:
        """
        GET /api/searches/results — search for MSTR objects.

        Args:
            object_type: MSTR type code (55=dossier, 3=report, 4=metric, etc.)
            name: Name filter
            root_folder_id: Restrict to folder
            offset: Pagination offset
            limit: Page size
        """
        params: dict[str, Any] = {"offset": offset, "limit": limit}
        if object_type is not None:
            params["type"] = object_type
        if name:
            params["name"] = name
        if root_folder_id:
            params["root"] = root_folder_id

        resp = self.get("/api/searches/results", params=params)
        return resp.json().get("result", [])

    def search_objects_with_retry(
        self,
        retry_delay_s: float = 3.0,
        **kwargs,
    ) -> list[dict]:
        """
        search_objects with a single retry on MSTRProjectIdleError.

        When a project is idle, the first search call returns 404.
        This method waits `retry_delay_s` seconds and retries once,
        giving the Intelligence Server time to load the project.
        """
        try:
            return self.search_objects(**kwargs)
        except MSTRProjectIdleError:
            logger.warning(
                "Project %s is idle — retrying search in %ds",
                self.project_id,
                retry_delay_s,
            )
            time.sleep(retry_delay_s)
            return self.search_objects(**kwargs)

    def get_dossier_definition(self, dossier_id: str) -> dict:
        """GET /api/v2/dossiers/{id}/definition — full dossier structure."""
        resp = self.get(f"/api/v2/dossiers/{dossier_id}/definition")
        return resp.json()

    def get_attribute(self, attribute_id: str) -> dict:
        """GET /api/model/attributes/{id} — attribute with all forms."""
        resp = self.get(f"/api/model/attributes/{attribute_id}")
        return resp.json()

    def get_fact(self, fact_id: str) -> dict:
        """GET /api/model/facts/{id} — fact definition."""
        resp = self.get(f"/api/model/facts/{fact_id}")
        return resp.json()

    def get_metric(self, metric_id: str) -> dict:
        """GET /api/model/metrics/{id}?showExpressionAs=tree — metric with expression tree."""
        resp = self.get(
            f"/api/model/metrics/{metric_id}",
            params={"showExpressionAs": "tree"},
        )
        return resp.json()

    def get_filter(self, filter_id: str) -> dict:
        """GET /api/model/filters/{id} — filter definition."""
        resp = self.get(f"/api/model/filters/{filter_id}")
        return resp.json()

    # ── Cube / Report Instance Management ───────────────────────

    def create_cube_instance(self, cube_id: str) -> dict:
        """
        POST /api/v2/cubes/{id}/instances — create a new instance for paginated data access.

        Returns the instance definition including instanceId.
        """
        resp = self.post(f"/api/v2/cubes/{cube_id}/instances", json={})
        return resp.json()

    def get_cube_data(
        self,
        cube_id: str,
        instance_id: str,
        offset: int = 0,
        limit: int = 10000,
    ) -> dict:
        """
        GET /api/v2/cubes/{id}/instances/{instanceId} — paginated data extraction.

        Returns raw grid data including headers and rows.
        """
        resp = self.get(
            f"/api/v2/cubes/{cube_id}/instances/{instance_id}",
            params={"offset": offset, "limit": limit},
        )
        return resp.json()

    def create_report_instance(self, report_id: str) -> dict:
        """POST /api/v2/reports/{id}/instances — create report instance."""
        resp = self.post(f"/api/v2/reports/{report_id}/instances", json={})
        return resp.json()

    def get_report_data(
        self,
        report_id: str,
        instance_id: str,
        offset: int = 0,
        limit: int = 10000,
    ) -> dict:
        """GET /api/v2/reports/{id}/instances/{instanceId} — paginated report data."""
        resp = self.get(
            f"/api/v2/reports/{report_id}/instances/{instance_id}",
            params={"offset": offset, "limit": limit},
        )
        return resp.json()

    # ── VLDB Settings ───────────────────────────────────────────

    def get_vldb_settings(self, project_id: Optional[str] = None) -> dict:
        """GET /api/model/vldbProperties — project-level VLDB configuration."""
        resp = self.get("/api/model/vldbProperties")
        return resp.json()

    # ── Cleanup ─────────────────────────────────────────────────

    def logout(self):
        """POST /api/auth/logout — terminate the MSTR session."""
        try:
            self._client.post(
                "/api/auth/logout",
                headers=self._headers,
            )
        except Exception:
            pass  # best-effort logout
        finally:
            self._token = None

    def close(self):
        """Close the HTTP client and logout."""
        self.logout()
        self._client.close()

    def __enter__(self):
        self.authenticate()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Async wrapper for use from FastAPI event loop (ADR-019)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class AsyncMSTRSession:
    """
    Async facade around the synchronous MSTRSession.

    All blocking MSTR REST calls are offloaded via asyncio.to_thread()
    to keep the FastAPI event loop responsive (ADR-019).
    """

    def __init__(self, session: MSTRSession):
        self._session = session

    async def authenticate(self) -> str:
        return await asyncio.to_thread(self._session.authenticate)

    async def get_server_status(self) -> dict:
        return await asyncio.to_thread(self._session.get_server_status)

    async def list_projects(self) -> list[dict]:
        return await asyncio.to_thread(self._session.list_projects)

    async def search_objects(self, **kwargs) -> list[dict]:
        return await asyncio.to_thread(self._session.search_objects, **kwargs)

    async def get_dossier_definition(self, dossier_id: str) -> dict:
        return await asyncio.to_thread(self._session.get_dossier_definition, dossier_id)

    async def get_attribute(self, attribute_id: str) -> dict:
        return await asyncio.to_thread(self._session.get_attribute, attribute_id)

    async def get_fact(self, fact_id: str) -> dict:
        return await asyncio.to_thread(self._session.get_fact, fact_id)

    async def get_metric(self, metric_id: str) -> dict:
        return await asyncio.to_thread(self._session.get_metric, metric_id)

    async def get_filter(self, filter_id: str) -> dict:
        return await asyncio.to_thread(self._session.get_filter, filter_id)

    async def create_cube_instance(self, cube_id: str) -> dict:
        return await asyncio.to_thread(self._session.create_cube_instance, cube_id)

    async def get_cube_data(self, cube_id: str, instance_id: str, **kwargs) -> dict:
        return await asyncio.to_thread(
            self._session.get_cube_data, cube_id, instance_id, **kwargs
        )

    async def create_report_instance(self, report_id: str) -> dict:
        return await asyncio.to_thread(self._session.create_report_instance, report_id)

    async def get_report_data(self, report_id: str, instance_id: str, **kwargs) -> dict:
        return await asyncio.to_thread(
            self._session.get_report_data, report_id, instance_id, **kwargs
        )

    async def get_vldb_settings(self) -> dict:
        return await asyncio.to_thread(self._session.get_vldb_settings)

    async def close(self):
        await asyncio.to_thread(self._session.close)
