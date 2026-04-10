from __future__ import annotations

from dataclasses import dataclass

from agent_architect_lab.config import Settings
from agent_architect_lab.control_plane.jobs import ControlPlaneJobRepository, ControlPlaneJobStore
from agent_architect_lab.control_plane.sqlite_repositories import (
    SQLiteAuditLogRepository,
    SQLiteControlPlaneJobStore,
    SQLiteIdempotencyRepository,
)
from agent_architect_lab.control_plane.storage import (
    AuditLogRepository,
    IdempotencyRepository,
    JsonAuditLogRepository,
    JsonIdempotencyRepository,
)


@dataclass(slots=True)
class ControlPlaneRepositories:
    jobs: ControlPlaneJobRepository
    idempotency: IdempotencyRepository
    audit: AuditLogRepository


def create_local_control_plane_repositories(settings: Settings) -> ControlPlaneRepositories:
    if settings.control_plane_storage_backend == "sqlite":
        return ControlPlaneRepositories(
            jobs=SQLiteControlPlaneJobStore(settings.control_plane_sqlite_path),
            idempotency=SQLiteIdempotencyRepository(settings.control_plane_sqlite_path),
            audit=SQLiteAuditLogRepository(settings.control_plane_sqlite_path),
        )
    return ControlPlaneRepositories(
        jobs=ControlPlaneJobStore(settings.control_plane_job_registry_path),
        idempotency=JsonIdempotencyRepository(settings.control_plane_idempotency_path),
        audit=JsonAuditLogRepository(settings.control_plane_request_log_path),
    )
