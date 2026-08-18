"""
Audit log ORM model and batched audit logger.

Ref: spec/database.md §2.7, §5
ADR-010: Full append-only audit trail
ADR-020: Batched writes to prevent lock convoys
"""

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.types import JSON

from app.db.base import Base


def _utcnow():
    return datetime.now(timezone.utc)


class AuditLog(Base):
    """Append-only audit log entry. One per API call, extraction step, or AI invocation."""

    __tablename__ = "audit_log"
    __table_args__ = (
        Index("idx_audit_job", "job_id"),
        Index("idx_audit_type", "event_type"),
        Index("idx_audit_timestamp", "timestamp"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String, ForeignKey("jobs.id"))
    event_type = Column(String, nullable=False)
    timestamp = Column(DateTime, nullable=False, default=_utcnow)
    details = Column(JSON, nullable=False)
    prompt_hash = Column(String)
    api_method = Column(String)
    api_url = Column(String)
    api_status_code = Column(Integer)
    api_duration_ms = Column(Integer)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Batched Audit Logger (ADR-020)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class BatchedAuditLogger:
    """
    Asynchronous batched audit logger.

    Accumulates audit entries in memory and flushes them to SQLite in batches
    of `batch_size` entries or every `flush_interval` seconds, whichever comes first.
    This prevents write-lock convoys under concurrent background extraction (ADR-020).
    """

    def __init__(
        self,
        session_factory,
        batch_size: int = 100,
        flush_interval: float = 5.0,
    ):
        self._session_factory = session_factory
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._buffer: list[dict] = []
        self._lock = asyncio.Lock()
        self._flush_task: Optional[asyncio.Task] = None

    async def start(self):
        """Start the periodic flush background task."""
        self._flush_task = asyncio.create_task(self._periodic_flush())

    async def stop(self):
        """Flush remaining entries and stop the background task."""
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        await self._flush()

    async def log(
        self,
        job_id: str,
        event_type: str,
        details: dict,
        prompt_hash: Optional[str] = None,
        api_method: Optional[str] = None,
        api_url: Optional[str] = None,
        api_status_code: Optional[int] = None,
        api_duration_ms: Optional[int] = None,
    ):
        """Add an audit entry to the in-memory buffer. Flushes automatically."""
        entry = {
            "job_id": job_id,
            "event_type": event_type,
            "timestamp": _utcnow(),
            "details": details,
            "prompt_hash": prompt_hash,
            "api_method": api_method,
            "api_url": api_url,
            "api_status_code": api_status_code,
            "api_duration_ms": api_duration_ms,
        }
        async with self._lock:
            self._buffer.append(entry)
            if len(self._buffer) >= self._batch_size:
                await self._flush_unlocked()

    # ── Convenience methods ──────────────────────────────────────

    async def log_mstr_api_call(
        self, job_id: str, method: str, url: str, status_code: int, duration_ms: int
    ):
        await self.log(
            job_id=job_id,
            event_type="mstr_api_call",
            details={"method": method, "url": url},
            api_method=method,
            api_url=url,
            api_status_code=status_code,
            api_duration_ms=duration_ms,
        )

    async def log_object_extracted(self, job_id: str, mstr_id: str, name: str, obj_type: str):
        await self.log(
            job_id=job_id,
            event_type="object_extracted",
            details={"mstr_id": mstr_id, "name": name, "type": obj_type},
        )

    async def log_ai_invocation(
        self, job_id: str, prompt_hash: str, expression: str, result: str, confidence: float
    ):
        await self.log(
            job_id=job_id,
            event_type="ai_invocation",
            details={"expression": expression, "result": result, "confidence": confidence},
            prompt_hash=prompt_hash,
        )

    async def log_job_state_change(self, job_id: str, old_status: str, new_status: str):
        await self.log(
            job_id=job_id,
            event_type="job_state_change",
            details={"old_status": old_status, "new_status": new_status},
        )

    async def log_error(self, job_id: str, message: str, details: Optional[dict] = None):
        await self.log(
            job_id=job_id,
            event_type="error",
            details={"message": message, **(details or {})},
        )

    # ── Internal flush mechanics ─────────────────────────────────

    async def _periodic_flush(self):
        """Background loop that flushes every `flush_interval` seconds."""
        while True:
            await asyncio.sleep(self._flush_interval)
            async with self._lock:
                await self._flush_unlocked()

    async def _flush(self):
        async with self._lock:
            await self._flush_unlocked()

    async def _flush_unlocked(self):
        """Write buffered entries to the database. Caller must hold self._lock."""
        if not self._buffer:
            return

        entries = self._buffer.copy()
        self._buffer.clear()

        # Offload blocking DB writes to a thread (ADR-019)
        await asyncio.to_thread(self._write_batch, entries)

    def _write_batch(self, entries: list[dict]):
        """Synchronous batch insert into SQLite."""
        db = self._session_factory()
        try:
            for entry_data in entries:
                entry = AuditLog(**entry_data)
                db.add(entry)
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
