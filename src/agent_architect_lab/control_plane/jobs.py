from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any, Callable, Protocol, runtime_checkable
from uuid import uuid4

from agent_architect_lab.config import Settings
from agent_architect_lab.control_plane.maintenance import backup_control_plane_storage
from agent_architect_lab.control_plane.reporting import (
    export_governance_summary_report,
    export_operator_handoff_report,
    record_operator_handoff_snapshot,
)
from agent_architect_lab.models import utc_now_iso


JobPayload = dict[str, Any]
JobHandler = Callable[[Settings, JobPayload], dict[str, Any]]


@dataclass(slots=True)
class ControlPlaneJob:
    job_id: str
    job_type: str
    status: str
    created_at: str
    updated_at: str
    requested_by_actor: str | None = None
    requested_by_role: str | None = None
    request_id: str | None = None
    operation_id: str | None = None
    attempts: int = 0
    max_attempts: int = 1
    queue_reason: str = "initial_enqueue"
    input_payload: JobPayload = field(default_factory=dict)
    result_payload: JobPayload | None = None
    error: JobPayload | None = None
    last_error: JobPayload | None = None
    started_at: str | None = None
    completed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "job_type": self.job_type,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "requested_by_actor": self.requested_by_actor,
            "requested_by_role": self.requested_by_role,
            "request_id": self.request_id,
            "operation_id": self.operation_id,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "queue_reason": self.queue_reason,
            "input_payload": self.input_payload,
            "result_payload": self.result_payload,
            "error": self.error,
            "last_error": self.last_error,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ControlPlaneJob":
        return cls(
            job_id=str(payload["job_id"]),
            job_type=str(payload["job_type"]),
            status=str(payload["status"]),
            created_at=str(payload["created_at"]),
            updated_at=str(payload["updated_at"]),
            requested_by_actor=payload.get("requested_by_actor"),
            requested_by_role=payload.get("requested_by_role"),
            request_id=payload.get("request_id"),
            operation_id=payload.get("operation_id"),
            attempts=int(payload.get("attempts", 0)),
            max_attempts=int(payload.get("max_attempts", 1)),
            queue_reason=str(payload.get("queue_reason", "initial_enqueue") or "initial_enqueue"),
            input_payload=dict(payload.get("input_payload", {})),
            result_payload=dict(payload["result_payload"]) if isinstance(payload.get("result_payload"), dict) else payload.get("result_payload"),
            error=dict(payload["error"]) if isinstance(payload.get("error"), dict) else payload.get("error"),
            last_error=dict(payload["last_error"]) if isinstance(payload.get("last_error"), dict) else payload.get("last_error"),
            started_at=payload.get("started_at"),
            completed_at=payload.get("completed_at"),
        )


@dataclass(slots=True)
class ControlPlaneJobRegistry:
    jobs: list[ControlPlaneJob] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"jobs": [job.to_dict() for job in self.jobs]}

    @classmethod
    def load(cls, path: Path) -> "ControlPlaneJobRegistry":
        if not path.exists():
            return cls()
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(jobs=[ControlPlaneJob.from_dict(item) for item in payload.get("jobs", [])])

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")


@runtime_checkable
class ControlPlaneJobRepository(Protocol):
    def create_job(
        self,
        *,
        job_type: str,
        payload: JobPayload,
        requested_by_actor: str | None,
        requested_by_role: str | None,
        request_id: str | None,
        operation_id: str | None,
        max_attempts: int = 1,
    ) -> ControlPlaneJob: ...

    def list_jobs(
        self,
        *,
        status: str | None = None,
        limit: int = 50,
        job_type: str | None = None,
        request_id: str | None = None,
        operation_id: str | None = None,
    ) -> list[ControlPlaneJob]: ...

    def get_job(self, job_id: str) -> ControlPlaneJob: ...

    def claim_next_job(self) -> ControlPlaneJob | None: ...

    def complete_job(self, job_id: str, result_payload: JobPayload) -> ControlPlaneJob: ...

    def fail_job(self, job_id: str, error_payload: JobPayload) -> ControlPlaneJob: ...

    def requeue_job(self, job_id: str, *, max_attempts: int | None = None) -> ControlPlaneJob: ...


class ControlPlaneJobStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = Lock()

    def create_job(
        self,
        *,
        job_type: str,
        payload: JobPayload,
        requested_by_actor: str | None,
        requested_by_role: str | None,
        request_id: str | None,
        operation_id: str | None,
        max_attempts: int = 1,
    ) -> ControlPlaneJob:
        now = utc_now_iso()
        job = ControlPlaneJob(
            job_id=f"job-{uuid4().hex[:12]}",
            job_type=job_type,
            status="queued",
            created_at=now,
            updated_at=now,
            requested_by_actor=requested_by_actor,
            requested_by_role=requested_by_role,
            request_id=request_id,
            operation_id=operation_id,
            max_attempts=max_attempts,
            queue_reason="initial_enqueue",
            input_payload=dict(payload),
        )
        with self._lock:
            registry = ControlPlaneJobRegistry.load(self.path)
            registry.jobs.append(job)
            registry.save(self.path)
        return job

    def list_jobs(
        self,
        *,
        status: str | None = None,
        limit: int = 50,
        job_type: str | None = None,
        request_id: str | None = None,
        operation_id: str | None = None,
    ) -> list[ControlPlaneJob]:
        with self._lock:
            registry = ControlPlaneJobRegistry.load(self.path)
        jobs = registry.jobs
        if status is not None:
            jobs = [job for job in jobs if job.status == status]
        if job_type is not None:
            jobs = [job for job in jobs if job.job_type == job_type]
        if request_id is not None:
            jobs = [job for job in jobs if job.request_id == request_id]
        if operation_id is not None:
            jobs = [job for job in jobs if job.operation_id == operation_id]
        jobs = sorted(jobs, key=lambda item: (item.created_at, item.job_id), reverse=True)
        return jobs[:limit]

    def get_job(self, job_id: str) -> ControlPlaneJob:
        with self._lock:
            registry = ControlPlaneJobRegistry.load(self.path)
        for job in registry.jobs:
            if job.job_id == job_id:
                return job
        raise KeyError(f"Unknown job '{job_id}'.")

    def claim_next_job(self) -> ControlPlaneJob | None:
        with self._lock:
            registry = ControlPlaneJobRegistry.load(self.path)
            queued_jobs = [job for job in registry.jobs if job.status == "queued"]
            if not queued_jobs:
                return None
            queued_jobs.sort(key=lambda item: (item.created_at, item.job_id))
            job = queued_jobs[0]
            now = utc_now_iso()
            for stored in registry.jobs:
                if stored.job_id != job.job_id:
                    continue
                stored.status = "running"
                stored.attempts += 1
                stored.started_at = now
                stored.updated_at = now
                job = stored
                break
            registry.save(self.path)
        return job

    def complete_job(self, job_id: str, result_payload: JobPayload) -> ControlPlaneJob:
        with self._lock:
            registry = ControlPlaneJobRegistry.load(self.path)
            job = _find_job(registry, job_id)
            now = utc_now_iso()
            job.status = "succeeded"
            job.result_payload = dict(result_payload)
            job.error = None
            job.completed_at = now
            job.updated_at = now
            job.queue_reason = "completed"
            registry.save(self.path)
            return job

    def fail_job(self, job_id: str, error_payload: JobPayload) -> ControlPlaneJob:
        with self._lock:
            registry = ControlPlaneJobRegistry.load(self.path)
            job = _find_job(registry, job_id)
            now = utc_now_iso()
            latest_error = dict(error_payload)
            job.last_error = latest_error
            if job.attempts < job.max_attempts:
                job.status = "queued"
                job.error = None
                job.completed_at = None
                job.queue_reason = "automatic_retry"
            else:
                job.status = "failed"
                job.error = latest_error
                job.completed_at = now
                job.queue_reason = "failed"
            job.updated_at = now
            registry.save(self.path)
            return job

    def requeue_job(self, job_id: str, *, max_attempts: int | None = None) -> ControlPlaneJob:
        with self._lock:
            registry = ControlPlaneJobRegistry.load(self.path)
            job = _find_job(registry, job_id)
            if job.status != "failed":
                raise ValueError(f"Only failed jobs can be retried. Job '{job_id}' is currently '{job.status}'.")
            if max_attempts is not None and max_attempts <= job.attempts:
                raise ValueError("Field 'max_attempts' must be greater than the number of attempts already used.")
            job.status = "queued"
            job.max_attempts = max_attempts or max(job.max_attempts, job.attempts + 1)
            job.error = None
            job.completed_at = None
            job.updated_at = utc_now_iso()
            job.queue_reason = "manual_retry"
            registry.save(self.path)
            return job


class ControlPlaneJobWorker:
    def __init__(
        self,
        *,
        settings: Settings,
        store: ControlPlaneJobRepository,
        handlers: dict[str, JobHandler] | None = None,
        poll_interval_s: float | None = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.handlers = handlers or default_job_handlers()
        self.poll_interval_s = poll_interval_s if poll_interval_s is not None else settings.control_plane_job_poll_interval_s
        self._stop_event = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = Thread(target=self._run, name="control-plane-job-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            job = self.store.claim_next_job()
            if job is None:
                self._stop_event.wait(self.poll_interval_s)
                continue
            handler = self.handlers.get(job.job_type)
            if handler is None:
                self.store.fail_job(
                    job.job_id,
                    {
                        "code": "unknown_job_type",
                        "message": f"No worker handler registered for job type '{job.job_type}'.",
                    },
                )
                continue
            try:
                result_payload = handler(self.settings, dict(job.input_payload))
            except Exception as exc:  # pragma: no cover - defensive worker boundary
                self.store.fail_job(
                    job.job_id,
                    {
                        "code": "job_execution_failed",
                        "message": str(exc),
                    },
                )
                continue
            self.store.complete_job(job.job_id, result_payload)


def default_job_handlers() -> dict[str, JobHandler]:
    return {
        "export_governance_summary": _handle_export_governance_summary,
        "record_operator_handoff": _handle_record_operator_handoff,
        "export_operator_handoff_report": _handle_export_operator_handoff_report,
        "backup_control_plane_storage": _handle_backup_control_plane_storage,
    }


def _handle_export_governance_summary(settings: Settings, payload: JobPayload) -> dict[str, Any]:
    return export_governance_summary_report(
        settings,
        environments=list(payload.get("environments", [])),
        release_limit=int(payload.get("release_limit", 20)),
        incident_limit=int(payload.get("incident_limit", 20)),
        override_limit=int(payload.get("override_limit", 50)),
        output=str(payload.get("output", "")),
        title=str(payload.get("title", "")),
    )


def _handle_record_operator_handoff(settings: Settings, payload: JobPayload) -> dict[str, Any]:
    return record_operator_handoff_snapshot(
        settings,
        environments=list(payload.get("environments", [])),
        release_limit=int(payload.get("release_limit", 20)),
        override_limit=int(payload.get("override_limit", 50)),
        label=str(payload.get("label", "")),
        output_path=str(payload.get("output_path", "")),
    )


def _handle_export_operator_handoff_report(settings: Settings, payload: JobPayload) -> dict[str, Any]:
    return export_operator_handoff_report(
        settings,
        snapshot=str(payload.get("snapshot", "")),
        latest=bool(payload.get("latest", False)),
        output=str(payload.get("output", "")),
        title=str(payload.get("title", "")),
    )


def _handle_backup_control_plane_storage(settings: Settings, payload: JobPayload) -> dict[str, Any]:
    return backup_control_plane_storage(
        settings,
        output=str(payload.get("output", "")),
        label=str(payload.get("label", "")),
    )


def _find_job(registry: ControlPlaneJobRegistry, job_id: str) -> ControlPlaneJob:
    for job in registry.jobs:
        if job.job_id == job_id:
            return job
    raise KeyError(f"Unknown job '{job_id}'.")
