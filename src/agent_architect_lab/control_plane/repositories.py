from __future__ import annotations

from dataclasses import dataclass

from agent_architect_lab.config import Settings
from agent_architect_lab.control_plane.jobs import ControlPlaneJobRepository, ControlPlaneJobStore
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
    return ControlPlaneRepositories(
        jobs=ControlPlaneJobStore(settings.control_plane_job_registry_path),
        idempotency=JsonIdempotencyRepository(settings.control_plane_idempotency_path),
        audit=JsonAuditLogRepository(settings.control_plane_request_log_path),
    )
