from __future__ import annotations

from typing import Any

from agent_architect_lab.config import Settings
from agent_architect_lab.control_plane.jobs import ControlPlaneJobRepository
from agent_architect_lab.control_plane.workers import ControlPlaneWorkerRepository
from agent_architect_lab.models import utc_now_iso


def build_control_plane_metrics_snapshot(
    *,
    settings: Settings,
    job_store: ControlPlaneJobRepository,
    worker_store: ControlPlaneWorkerRepository,
    worker_alive: bool,
    worker_id: str,
    managed_by_server: bool,
    now: str | None = None,
) -> dict[str, Any]:
    generated_at = now or utc_now_iso()
    job_summary = job_store.summarize_jobs(now=generated_at)
    worker_summary = worker_store.summarize_workers(
        now=generated_at,
        minimum_stale_after_s=settings.control_plane_worker_stale_after_s,
    )
    return {
        "generated_at": generated_at,
        "service": "agent-architect-lab-control-plane",
        "storage_backend": settings.control_plane_storage_backend,
        "jobs": {
            "totals": dict(job_summary.get("totals", {})),
            "counts_by_status": dict(job_summary.get("counts_by_status", {})),
            "counts_by_queue_reason": dict(job_summary.get("counts_by_queue_reason", {})),
            "oldest_queued_at": job_summary.get("oldest_queued_at"),
            "oldest_queued_age_s": job_summary.get("oldest_queued_age_s"),
        },
        "workers": {
            "totals": dict(worker_summary.get("totals", {})),
            "counts_by_status": dict(worker_summary.get("counts_by_status", {})),
            "counts_by_health": dict(worker_summary.get("counts_by_health", {})),
        },
        "worker_process": {
            "alive": worker_alive,
            "worker_id": worker_id,
            "managed_by_server": managed_by_server,
        },
        "admission": {
            "default_max_queued_per_type": settings.control_plane_job_max_queued_per_type,
            "default_max_inflight_per_type": settings.control_plane_job_max_inflight_per_type,
            "overrides": settings.control_plane_job_admission_overrides,
        },
    }
