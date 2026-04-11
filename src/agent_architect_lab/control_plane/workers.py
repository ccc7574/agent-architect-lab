from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any, Protocol, runtime_checkable

from agent_architect_lab.models import utc_now_iso


@dataclass(slots=True)
class ControlPlaneWorkerRecord:
    worker_id: str
    status: str
    started_at: str
    updated_at: str
    last_heartbeat_at: str
    managed_by_server: bool
    poll_interval_s: float
    lease_ttl_s: float
    heartbeat_interval_s: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "worker_id": self.worker_id,
            "status": self.status,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "last_heartbeat_at": self.last_heartbeat_at,
            "managed_by_server": self.managed_by_server,
            "poll_interval_s": self.poll_interval_s,
            "lease_ttl_s": self.lease_ttl_s,
            "heartbeat_interval_s": self.heartbeat_interval_s,
        }

    def stale_after_s(self, *, minimum_stale_after_s: float = 15.0) -> float:
        return max(
            float(minimum_stale_after_s),
            max(self.poll_interval_s, self.heartbeat_interval_s) * 3.0,
        )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ControlPlaneWorkerRecord":
        return cls(
            worker_id=str(payload["worker_id"]),
            status=str(payload["status"]),
            started_at=str(payload["started_at"]),
            updated_at=str(payload["updated_at"]),
            last_heartbeat_at=str(payload["last_heartbeat_at"]),
            managed_by_server=bool(payload.get("managed_by_server", False)),
            poll_interval_s=float(payload.get("poll_interval_s", 0.0)),
            lease_ttl_s=float(payload.get("lease_ttl_s", 0.0)),
            heartbeat_interval_s=float(payload.get("heartbeat_interval_s", 0.0)),
        )


@dataclass(slots=True)
class ControlPlaneWorkerRegistry:
    workers: list[ControlPlaneWorkerRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"workers": [worker.to_dict() for worker in self.workers]}

    @classmethod
    def load(cls, path: Path) -> "ControlPlaneWorkerRegistry":
        if not path.exists():
            return cls()
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(workers=[ControlPlaneWorkerRecord.from_dict(item) for item in payload.get("workers", [])])

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")


@runtime_checkable
class ControlPlaneWorkerRepository(Protocol):
    def heartbeat_worker(
        self,
        *,
        worker_id: str,
        managed_by_server: bool,
        poll_interval_s: float,
        lease_ttl_s: float,
        heartbeat_interval_s: float,
        status: str = "running",
    ) -> ControlPlaneWorkerRecord: ...

    def stop_worker(self, worker_id: str) -> ControlPlaneWorkerRecord | None: ...

    def list_workers(self, *, status: str | None = None, limit: int = 50) -> list[ControlPlaneWorkerRecord]: ...

    def summarize_workers(self, *, now: str | None = None, minimum_stale_after_s: float = 15.0) -> dict[str, Any]: ...


class JsonControlPlaneWorkerStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = Lock()
        if not self.path.exists():
            ControlPlaneWorkerRegistry().save(self.path)

    def heartbeat_worker(
        self,
        *,
        worker_id: str,
        managed_by_server: bool,
        poll_interval_s: float,
        lease_ttl_s: float,
        heartbeat_interval_s: float,
        status: str = "running",
    ) -> ControlPlaneWorkerRecord:
        with self._lock:
            registry = ControlPlaneWorkerRegistry.load(self.path)
            now = utc_now_iso()
            for worker in registry.workers:
                if worker.worker_id != worker_id:
                    continue
                worker.status = status
                worker.updated_at = now
                worker.last_heartbeat_at = now
                worker.managed_by_server = managed_by_server
                worker.poll_interval_s = poll_interval_s
                worker.lease_ttl_s = lease_ttl_s
                worker.heartbeat_interval_s = heartbeat_interval_s
                registry.save(self.path)
                return worker
            worker = ControlPlaneWorkerRecord(
                worker_id=worker_id,
                status=status,
                started_at=now,
                updated_at=now,
                last_heartbeat_at=now,
                managed_by_server=managed_by_server,
                poll_interval_s=poll_interval_s,
                lease_ttl_s=lease_ttl_s,
                heartbeat_interval_s=heartbeat_interval_s,
            )
            registry.workers.append(worker)
            registry.workers.sort(key=lambda item: (item.updated_at, item.worker_id), reverse=True)
            registry.save(self.path)
            return worker

    def stop_worker(self, worker_id: str) -> ControlPlaneWorkerRecord | None:
        with self._lock:
            registry = ControlPlaneWorkerRegistry.load(self.path)
            for worker in registry.workers:
                if worker.worker_id != worker_id:
                    continue
                now = utc_now_iso()
                worker.status = "stopped"
                worker.updated_at = now
                worker.last_heartbeat_at = now
                registry.save(self.path)
                return worker
        return None

    def list_workers(self, *, status: str | None = None, limit: int = 50) -> list[ControlPlaneWorkerRecord]:
        with self._lock:
            registry = ControlPlaneWorkerRegistry.load(self.path)
        workers = sorted(registry.workers, key=lambda item: (item.updated_at, item.worker_id), reverse=True)
        if status is not None:
            workers = [worker for worker in workers if worker.status == status]
        return workers[:limit]

    def summarize_workers(self, *, now: str | None = None, minimum_stale_after_s: float = 15.0) -> dict[str, Any]:
        return summarize_worker_records(
            self.list_workers(limit=1000),
            now=now or utc_now_iso(),
            minimum_stale_after_s=minimum_stale_after_s,
        )


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


def build_worker_view(
    worker: ControlPlaneWorkerRecord,
    *,
    now: str,
    minimum_stale_after_s: float = 15.0,
) -> dict[str, Any]:
    payload = worker.to_dict()
    stale_after_s = worker.stale_after_s(minimum_stale_after_s=minimum_stale_after_s)
    now_ts = _parse_timestamp(now)
    heartbeat_ts = _parse_timestamp(worker.last_heartbeat_at)
    heartbeat_age_s: float | None = None
    if now_ts is not None and heartbeat_ts is not None:
        heartbeat_age_s = max(0.0, round((now_ts - heartbeat_ts).total_seconds(), 3))
    if worker.status != "running":
        health_status = "stopped"
    elif heartbeat_age_s is not None and heartbeat_age_s > stale_after_s:
        health_status = "stale"
    else:
        health_status = "healthy"
    payload.update(
        {
            "health_status": health_status,
            "heartbeat_age_s": heartbeat_age_s,
            "stale_after_s": round(stale_after_s, 3),
            "is_stale": health_status == "stale",
        }
    )
    return payload


def summarize_worker_records(
    workers: list[ControlPlaneWorkerRecord],
    *,
    now: str,
    minimum_stale_after_s: float = 15.0,
) -> dict[str, Any]:
    counts_by_status: dict[str, int] = {}
    counts_by_health: dict[str, int] = {}
    rows = [
        build_worker_view(worker, now=now, minimum_stale_after_s=minimum_stale_after_s)
        for worker in workers
    ]
    for worker in workers:
        counts_by_status[worker.status] = counts_by_status.get(worker.status, 0) + 1
    for row in rows:
        counts_by_health[row["health_status"]] = counts_by_health.get(row["health_status"], 0) + 1
    return {
        "generated_at": now,
        "totals": {
            "workers": len(workers),
            "running_workers": counts_by_status.get("running", 0),
            "stopped_workers": counts_by_status.get("stopped", 0),
            "healthy_workers": counts_by_health.get("healthy", 0),
            "stale_workers": counts_by_health.get("stale", 0),
        },
        "counts_by_status": dict(sorted(counts_by_status.items())),
        "counts_by_health": dict(sorted(counts_by_health.items())),
        "workers": rows[:50],
    }
