"""Database-backed job queue.

Jobs are rows in `jobs`; a worker claims queued jobs whose run_after has passed, runs the handler,
and records logs/result/error. Failures retry with exponential backoff up to max_retries. The unique
idempotency_key prevents duplicate operational actions. Cloud Scheduler calls POST /api/v1/jobs/tick
(authenticated with SCHEDULER_TOKEN / OIDC) to enqueue scheduled work and drain the queue.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.core.db import session_scope
from app.core.logging import log
from app.models import Job

Handler = Callable[[Job], Awaitable[dict[str, Any] | None]]
HANDLERS: dict[str, Handler] = {}


def handler(kind: str) -> Callable[[Handler], Handler]:
    def deco(fn: Handler) -> Handler:
        HANDLERS[kind] = fn
        return fn

    return deco


async def enqueue(kind: str, *, payload: dict[str, Any], idempotency_key: str, organization_id: str | None = None,
                  client_id: str | None = None, workflow_id: str = "manual", run_after: datetime | None = None) -> Job:
    async with session_scope() as s:
        existing = (await s.execute(select(Job).where(Job.idempotency_key == idempotency_key))).scalar_one_or_none()
        if existing:
            return existing
        job = Job(kind=kind, payload=payload, idempotency_key=idempotency_key, organization_id=organization_id,
                  client_id=client_id, workflow_id=workflow_id, run_after=run_after or datetime.now(UTC))
        s.add(job)
        try:
            await s.flush()
        except IntegrityError:
            await s.rollback()
            return (await s.execute(select(Job).where(Job.idempotency_key == idempotency_key))).scalar_one()
    return job


async def run_pending(limit: int = 50) -> dict[str, int]:
    counts = {"succeeded": 0, "failed": 0, "retrying": 0}
    async with session_scope() as s:
        ids = [j.id for j in (await s.execute(
            select(Job).where(Job.status == "queued", Job.run_after <= datetime.now(UTC)).order_by(Job.created_at).limit(limit)
        )).scalars()]
    for jid in ids:
        async with session_scope() as s:
            # Atomic claim: only one worker transitions queued -> running.
            claimed = await s.execute(update(Job).where(Job.id == jid, Job.status == "queued").values(status="running"))
            if claimed.rowcount != 1:
                continue
        async with session_scope() as s:
            job = await s.get(Job, jid)
            fn = HANDLERS.get(job.kind)
            try:
                if fn is None:
                    raise RuntimeError(f"no handler for {job.kind}")
                result = await fn(job)
                job.status, job.result = "succeeded", result or {}
                job.completed_at = datetime.now(UTC)
                job.logs = [*job.logs, f"{datetime.now(UTC).isoformat()} succeeded"]
                counts["succeeded"] += 1
            except Exception as exc:
                job.error = f"{type(exc).__name__}: {exc}"[:2000]
                job.logs = [*job.logs, f"{datetime.now(UTC).isoformat()} attempt {job.retry_count + 1} failed: {exc}"[:500]]
                if job.retry_count < job.max_retries:
                    job.retry_count += 1
                    job.status = "queued"
                    job.run_after = datetime.now(UTC) + timedelta(seconds=30 * 2 ** job.retry_count)
                    counts["retrying"] += 1
                else:
                    job.status, job.completed_at = "failed", datetime.now(UTC)
                    counts["failed"] += 1
                    log.error("job failed", extra={"ctx": {"job_id": job.id, "kind": job.kind}})
    return counts
