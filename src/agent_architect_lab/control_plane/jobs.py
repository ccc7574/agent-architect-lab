from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any, Callable, Protocol, runtime_checkable
from uuid import uuid4

from agent_architect_lab.config import Settings
from agent_architect_lab.control_plane.maintenance import (
    backup_control_plane_storage,
    restore_control_plane_backup,
    verify_control_plane_backup,
)
from agent_architect_lab.control_plane.reporting import (
    export_governance_summary_report,
    export_operator_handoff_report,
    export_planner_shadow_report,
    export_release_command_brief_report,
    export_release_runbook_report,
    export_weekly_status_report,
    record_operator_handoff_snapshot,
)
from agent_architect_lab.harness.ledger_maintenance import (
    backup_release_and_incident_ledgers,
    restore_release_and_incident_ledger_backup,
    verify_release_and_incident_ledger_backup,
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
    worker_id: str | None = None
    lease_expires_at: str | None = None
    heartbeat_at: str | None = None

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
            "worker_id": self.worker_id,
            "lease_expires_at": self.lease_expires_at,
            "heartbeat_at": self.heartbeat_at,
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
            worker_id=payload.get("worker_id"),
            lease_expires_at=payload.get("lease_expires_at"),
            heartbeat_at=payload.get("heartbeat_at"),
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

    def summarize_jobs(self, *, now: str | None = None) -> dict[str, Any]: ...

    def claim_next_job(self, *, worker_id: str, lease_ttl_s: float) -> ControlPlaneJob | None: ...

    def heartbeat_job(self, job_id: str, *, worker_id: str, lease_ttl_s: float) -> ControlPlaneJob: ...

    def requeue_stale_jobs(self, *, now: str | None = None) -> list[ControlPlaneJob]: ...

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

    def summarize_jobs(self, *, now: str | None = None) -> dict[str, Any]:
        with self._lock:
            registry = ControlPlaneJobRegistry.load(self.path)
        return _job_summary(registry.jobs, now=now or utc_now_iso())

    def claim_next_job(self, *, worker_id: str, lease_ttl_s: float) -> ControlPlaneJob | None:
        with self._lock:
            registry = ControlPlaneJobRegistry.load(self.path)
            requeued = _requeue_stale_jobs(registry, now=utc_now_iso())
            queued_jobs = [job for job in registry.jobs if job.status == "queued"]
            if not queued_jobs:
                if requeued:
                    registry.save(self.path)
                return None
            queued_jobs.sort(key=lambda item: (item.created_at, item.job_id))
            job = queued_jobs[0]
            now = utc_now_iso()
            lease_expires_at = _lease_deadline(now, lease_ttl_s)
            for stored in registry.jobs:
                if stored.job_id != job.job_id:
                    continue
                stored.status = "running"
                stored.attempts += 1
                stored.started_at = now
                stored.updated_at = now
                stored.worker_id = worker_id
                stored.heartbeat_at = now
                stored.lease_expires_at = lease_expires_at
                job = stored
                break
            registry.save(self.path)
        return job

    def heartbeat_job(self, job_id: str, *, worker_id: str, lease_ttl_s: float) -> ControlPlaneJob:
        with self._lock:
            registry = ControlPlaneJobRegistry.load(self.path)
            job = _find_job(registry, job_id)
            if job.status != "running":
                raise ValueError(f"Only running jobs can be heartbeated. Job '{job_id}' is currently '{job.status}'.")
            if job.worker_id != worker_id:
                raise ValueError(f"Job '{job_id}' is currently leased by '{job.worker_id}', not '{worker_id}'.")
            now = utc_now_iso()
            job.heartbeat_at = now
            job.lease_expires_at = _lease_deadline(now, lease_ttl_s)
            job.updated_at = now
            registry.save(self.path)
            return job

    def requeue_stale_jobs(self, *, now: str | None = None) -> list[ControlPlaneJob]:
        with self._lock:
            registry = ControlPlaneJobRegistry.load(self.path)
            rows = _requeue_stale_jobs(registry, now=now or utc_now_iso())
            if rows:
                registry.save(self.path)
            return rows

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
            job.worker_id = None
            job.lease_expires_at = None
            job.heartbeat_at = now
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
            job.worker_id = None
            job.lease_expires_at = None
            job.heartbeat_at = now
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
            job.worker_id = None
            job.lease_expires_at = None
            job.heartbeat_at = job.updated_at
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
        managed_by_server: bool = True,
    ) -> None:
        self.settings = settings
        self.store = store
        self.handlers = handlers or default_job_handlers()
        self.poll_interval_s = poll_interval_s if poll_interval_s is not None else settings.control_plane_job_poll_interval_s
        self.lease_ttl_s = settings.control_plane_job_lease_ttl_s
        self.heartbeat_interval_s = settings.control_plane_job_heartbeat_interval_s
        self.worker_id = f"worker-{uuid4().hex[:10]}"
        self.managed_by_server = managed_by_server
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
            if not self.run_once():
                self._stop_event.wait(self.poll_interval_s)

    def run_once(self) -> bool:
        self.store.requeue_stale_jobs()
        job = self.store.claim_next_job(worker_id=self.worker_id, lease_ttl_s=self.lease_ttl_s)
        if job is None:
            return False
        self._process_job(job)
        return True

    def run_until_idle(self, idle_timeout_s: float) -> int:
        idle_started_at = time.monotonic()
        processed_jobs = 0
        while not self._stop_event.is_set():
            processed = self.run_once()
            if processed:
                processed_jobs += 1
                idle_started_at = time.monotonic()
                continue
            if time.monotonic() - idle_started_at >= idle_timeout_s:
                break
            time.sleep(self.poll_interval_s)
        return processed_jobs

    def _process_job(self, job: ControlPlaneJob) -> None:
        handler = self.handlers.get(job.job_type)
        if handler is None:
            self.store.fail_job(
                job.job_id,
                {
                    "code": "unknown_job_type",
                    "message": f"No worker handler registered for job type '{job.job_type}'.",
                },
            )
            return
        heartbeat_stop = Event()
        heartbeat_thread = Thread(
            target=self._heartbeat_loop,
            args=(job.job_id, heartbeat_stop),
            name=f"control-plane-job-heartbeat-{job.job_id}",
            daemon=True,
        )
        heartbeat_thread.start()
        try:
            result_payload = handler(self.settings, dict(job.input_payload))
        except Exception as exc:  # pragma: no cover - defensive worker boundary
            heartbeat_stop.set()
            heartbeat_thread.join(timeout=5)
            self.store.fail_job(
                job.job_id,
                {
                    "code": "job_execution_failed",
                    "message": str(exc),
                },
            )
            return
        heartbeat_stop.set()
        heartbeat_thread.join(timeout=5)
        self.store.complete_job(job.job_id, result_payload)

    def _heartbeat_loop(self, job_id: str, stop_event: Event) -> None:
        while not stop_event.wait(self.heartbeat_interval_s):
            try:
                self.store.heartbeat_job(
                    job_id,
                    worker_id=self.worker_id,
                    lease_ttl_s=self.lease_ttl_s,
                )
            except Exception:  # pragma: no cover - defensive background boundary
                return


def default_job_handlers() -> dict[str, JobHandler]:
    return {
        "export_governance_summary": _handle_export_governance_summary,
        "export_weekly_status": _handle_export_weekly_status,
        "record_operator_handoff": _handle_record_operator_handoff,
        "export_operator_handoff_report": _handle_export_operator_handoff_report,
        "export_planner_shadow": _handle_export_planner_shadow,
        "export_release_command_brief": _handle_export_release_command_brief,
        "export_release_runbook": _handle_export_release_runbook,
        "backup_control_plane_storage": _handle_backup_control_plane_storage,
        "verify_control_plane_backup": _handle_verify_control_plane_backup,
        "restore_control_plane_backup": _handle_restore_control_plane_backup,
        "backup_release_and_incident_ledgers": _handle_backup_release_and_incident_ledgers,
        "verify_release_and_incident_ledger_backup": _handle_verify_release_and_incident_ledger_backup,
        "restore_release_and_incident_ledger_backup": _handle_restore_release_and_incident_ledger_backup,
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


def _handle_export_weekly_status(settings: Settings, payload: JobPayload) -> dict[str, Any]:
    return export_weekly_status_report(
        settings,
        environments=list(payload.get("environments", [])),
        since_days=int(payload.get("since_days", 7)),
        snapshot_limit=int(payload.get("snapshot_limit", 20)),
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


def _handle_export_planner_shadow(settings: Settings, payload: JobPayload) -> dict[str, Any]:
    return export_planner_shadow_report(
        settings,
        suite_name=str(payload.get("suite_name", "planner_shadow") or "planner_shadow"),
        report_name=str(payload.get("report_name", "planner-shadow-report.json") or "planner-shadow-report.json"),
        allowed_tools=list(payload.get("allowed_tools", [])),
        blocked_tools=list(payload.get("blocked_tools", [])),
        markdown_output=str(payload.get("output", "")),
        title=str(payload.get("title", "")),
    )


def _handle_export_release_command_brief(settings: Settings, payload: JobPayload) -> dict[str, Any]:
    return export_release_command_brief_report(
        settings,
        release_name=str(payload.get("release_name", "")),
        environments=list(payload.get("environments", [])),
        history_limit=int(payload.get("history_limit", 5)),
        incident_limit=int(payload.get("incident_limit", 10)),
        output=str(payload.get("output", "")),
        title=str(payload.get("title", "")),
    )


def _handle_export_release_runbook(settings: Settings, payload: JobPayload) -> dict[str, Any]:
    return export_release_runbook_report(
        settings,
        release_name=str(payload.get("release_name", "")),
        environments=list(payload.get("environments", [])),
        history_limit=int(payload.get("history_limit", 10)),
        incident_limit=int(payload.get("incident_limit", 20)),
        output=str(payload.get("output", "")),
        title=str(payload.get("title", "")),
    )


def _handle_backup_control_plane_storage(settings: Settings, payload: JobPayload) -> dict[str, Any]:
    return backup_control_plane_storage(
        settings,
        output=str(payload.get("output", "")),
        label=str(payload.get("label", "")),
    )


def _handle_verify_control_plane_backup(settings: Settings, payload: JobPayload) -> dict[str, Any]:
    return verify_control_plane_backup(
        str(payload.get("backup_path", "")),
        expected_sha256=str(payload.get("expected_sha256", "")),
    )


def _handle_restore_control_plane_backup(settings: Settings, payload: JobPayload) -> dict[str, Any]:
    return restore_control_plane_backup(
        settings,
        backup_path=str(payload.get("backup_path", "")),
        output_dir=str(payload.get("output_dir", "")),
        label=str(payload.get("label", "")),
    )


def _handle_backup_release_and_incident_ledgers(settings: Settings, payload: JobPayload) -> dict[str, Any]:
    return backup_release_and_incident_ledgers(
        settings,
        output=str(payload.get("output", "")),
        label=str(payload.get("label", "")),
    )


def _handle_verify_release_and_incident_ledger_backup(settings: Settings, payload: JobPayload) -> dict[str, Any]:
    return verify_release_and_incident_ledger_backup(
        str(payload.get("backup_path", "")),
        expected_sha256=str(payload.get("expected_sha256", "")),
    )


def _handle_restore_release_and_incident_ledger_backup(settings: Settings, payload: JobPayload) -> dict[str, Any]:
    return restore_release_and_incident_ledger_backup(
        settings,
        backup_path=str(payload.get("backup_path", "")),
        output_dir=str(payload.get("output_dir", "")),
        label=str(payload.get("label", "")),
    )


def _find_job(registry: ControlPlaneJobRegistry, job_id: str) -> ControlPlaneJob:
    for job in registry.jobs:
        if job.job_id == job_id:
            return job
    raise KeyError(f"Unknown job '{job_id}'.")


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        timestamp = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(UTC)


def _lease_deadline(started_at: str, lease_ttl_s: float) -> str:
    started = _parse_timestamp(started_at) or datetime.now(UTC)
    return (started + timedelta(seconds=max(lease_ttl_s, 0.1))).isoformat()


def _requeue_stale_jobs(registry: ControlPlaneJobRegistry, *, now: str) -> list[ControlPlaneJob]:
    rows: list[ControlPlaneJob] = []
    now_ts = _parse_timestamp(now)
    if now_ts is None:
        return rows
    for job in registry.jobs:
        if job.status != "running":
            continue
        deadline = _parse_timestamp(job.lease_expires_at)
        if deadline is None or deadline > now_ts:
            continue
        job.status = "queued"
        job.updated_at = now
        job.completed_at = None
        job.queue_reason = "lease_expired_retry"
        job.worker_id = None
        job.heartbeat_at = now
        job.lease_expires_at = None
        rows.append(job)
    return rows


def _job_summary(jobs: list[ControlPlaneJob], *, now: str) -> dict[str, Any]:
    now_ts = _parse_timestamp(now)
    counts_by_status: dict[str, int] = {}
    running_by_worker: dict[str, dict[str, Any]] = {}
    oldest_queued_at: str | None = None
    stale_running_jobs: list[dict[str, Any]] = []
    queued_jobs = 0
    running_jobs = 0
    for job in jobs:
        counts_by_status[job.status] = counts_by_status.get(job.status, 0) + 1
        if job.status == "queued":
            queued_jobs += 1
            if oldest_queued_at is None or (job.created_at, job.job_id) < (oldest_queued_at, job.job_id):
                oldest_queued_at = job.created_at
        if job.status == "running":
            running_jobs += 1
            worker_key = job.worker_id or "unassigned"
            entry = running_by_worker.setdefault(
                worker_key,
                {"worker_id": worker_key, "running_jobs": 0, "job_ids": [], "lease_expires_at": None},
            )
            entry["running_jobs"] += 1
            entry["job_ids"].append(job.job_id)
            lease_expires_at = job.lease_expires_at
            if lease_expires_at and (
                entry["lease_expires_at"] is None or str(lease_expires_at) < str(entry["lease_expires_at"])
            ):
                entry["lease_expires_at"] = lease_expires_at
            lease_deadline = _parse_timestamp(job.lease_expires_at)
            if now_ts is not None and lease_deadline is not None and lease_deadline <= now_ts:
                stale_running_jobs.append(
                    {
                        "job_id": job.job_id,
                        "worker_id": job.worker_id,
                        "lease_expires_at": job.lease_expires_at,
                        "job_type": job.job_type,
                    }
                )
    queued_age_s: float | None = None
    if oldest_queued_at and now_ts is not None:
        oldest_ts = _parse_timestamp(oldest_queued_at)
        if oldest_ts is not None:
            queued_age_s = max(0.0, round((now_ts - oldest_ts).total_seconds(), 3))
    return {
        "generated_at": now,
        "totals": {
            "jobs": len(jobs),
            "queued_jobs": queued_jobs,
            "running_jobs": running_jobs,
            "stale_running_jobs": len(stale_running_jobs),
        },
        "counts_by_status": dict(sorted(counts_by_status.items())),
        "oldest_queued_at": oldest_queued_at,
        "oldest_queued_age_s": queued_age_s,
        "running_workers": sorted(
            running_by_worker.values(),
            key=lambda item: (-int(item["running_jobs"]), str(item["worker_id"])),
        ),
        "stale_running_jobs": sorted(
            stale_running_jobs,
            key=lambda item: (str(item.get("lease_expires_at") or ""), str(item["job_id"])),
        ),
    }
