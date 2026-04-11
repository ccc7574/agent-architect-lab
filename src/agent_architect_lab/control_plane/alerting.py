from __future__ import annotations

from typing import Any

from agent_architect_lab.config import Settings
from agent_architect_lab.control_plane.metrics import build_control_plane_metrics_snapshot
from agent_architect_lab.control_plane.reporting import build_governance_summary_payload
from agent_architect_lab.models import utc_now_iso


_SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def build_operator_alert_board_payload(
    *,
    settings: Settings,
    job_store: Any,
    worker_store: Any,
    worker_alive: bool,
    worker_id: str,
    managed_by_server: bool,
    environments: list[str] | None = None,
    release_limit: int = 20,
    incident_limit: int = 20,
    override_limit: int = 50,
    alert_limit: int = 20,
    now: str | None = None,
) -> dict[str, Any]:
    generated_at = now or utc_now_iso()
    governance = build_governance_summary_payload(
        settings,
        environments=environments or settings.environment_names,
        release_limit=release_limit,
        incident_limit=incident_limit,
        override_limit=override_limit,
    )
    control_plane_metrics = build_control_plane_metrics_snapshot(
        settings=settings,
        job_store=job_store,
        worker_store=worker_store,
        worker_alive=worker_alive,
        worker_id=worker_id,
        managed_by_server=managed_by_server,
        now=generated_at,
    )
    failed_jobs = [job.to_dict() for job in job_store.list_jobs(status="failed", limit=max(alert_limit, 20))]
    stale_workers = [
        worker
        for worker in worker_store.summarize_workers(
            now=generated_at,
            minimum_stale_after_s=settings.control_plane_worker_stale_after_s,
        ).get("workers", [])
        if worker.get("health_status") == "stale"
    ]
    alerts = _build_alerts(
        settings=settings,
        governance=governance,
        control_plane_metrics=control_plane_metrics,
        failed_jobs=failed_jobs,
        stale_workers=stale_workers,
    )
    alerts = sorted(
        alerts,
        key=lambda item: (
            _SEVERITY_RANK.get(str(item.get("severity")), 99),
            str(item.get("category") or ""),
            str(item.get("title") or ""),
        ),
    )[: max(1, alert_limit)]
    counts_by_severity: dict[str, int] = {}
    for alert in alerts:
        severity = str(alert.get("severity") or "low")
        counts_by_severity[severity] = counts_by_severity.get(severity, 0) + 1
    return {
        "generated_at": generated_at,
        "summary": _render_alert_summary(alerts),
        "metrics": {
            "total_alerts": len(alerts),
            "counts_by_severity": dict(sorted(counts_by_severity.items(), key=lambda item: _SEVERITY_RANK.get(item[0], 99))),
        },
        "alerts": alerts,
        "source_views": {
            "control_plane_metrics": control_plane_metrics,
            "release_risk_board": {
                "rows": governance.get("release_risk_board", {}).get("rows", [])[: min(release_limit, 10)],
                "total": len(governance.get("release_risk_board", {}).get("rows", [])),
            },
            "approval_review_board": {
                "rows": governance.get("approval_review_board", {}).get("rows", [])[: min(release_limit, 10)],
                "total": len(governance.get("approval_review_board", {}).get("rows", [])),
            },
            "incident_review_board": {
                "rows": governance.get("incident_review_board", {}).get("rows", [])[: min(incident_limit, 10)],
                "total": len(governance.get("incident_review_board", {}).get("rows", [])),
            },
            "override_review_board": {
                "rows": governance.get("override_review_board", {}).get("rows", [])[: min(override_limit, 10)],
                "total": len(governance.get("override_review_board", {}).get("rows", [])),
            },
            "failed_jobs": failed_jobs[: min(alert_limit, 10)],
            "stale_workers": stale_workers[: min(alert_limit, 10)],
        },
    }


def _build_alerts(
    *,
    settings: Settings,
    governance: dict[str, Any],
    control_plane_metrics: dict[str, Any],
    failed_jobs: list[dict[str, Any]],
    stale_workers: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    critical_incidents = [
        row for row in governance.get("active_incidents", []) if row.get("severity") == "critical"
    ]
    if critical_incidents:
        alerts.append(
            _alert(
                "critical",
                "incidents",
                "Critical incidents require commander attention",
                f"{len(critical_incidents)} critical incident(s) remain active: "
                + ", ".join(str(row.get("incident_id")) for row in critical_incidents[:5]),
                "incident_review_board",
                "review_critical_incidents",
                "PYTHONPATH=src python3 -m agent_architect_lab.cli incident-review-board --limit 20",
            )
        )

    high_risk_releases = [
        row for row in governance.get("release_risk_board", {}).get("rows", []) if row.get("risk_level") == "high"
    ]
    if high_risk_releases:
        alerts.append(
            _alert(
                "high",
                "releases",
                "High-risk releases need explicit operator review",
                f"{len(high_risk_releases)} high-risk release(s): "
                + ", ".join(str(row.get("release_name")) for row in high_risk_releases[:5]),
                "release_risk_board",
                "review_high_risk_releases",
                "PYTHONPATH=src python3 -m agent_architect_lab.cli release-risk-board --limit 20",
            )
        )

    stale_approvals = [
        row for row in governance.get("approval_review_board", {}).get("rows", []) if row.get("is_stale")
    ]
    if stale_approvals:
        alerts.append(
            _alert(
                "high",
                "approvals",
                "Approval backlog contains stale release gates",
                f"{len(stale_approvals)} stale approval queue(s): "
                + ", ".join(str(row.get("release_name")) for row in stale_approvals[:5]),
                "approval_review_board",
                "escalate_release_approvals",
                "PYTHONPATH=src python3 -m agent_architect_lab.cli approval-review-board --limit 20",
            )
        )

    urgent_overrides = [
        row
        for row in governance.get("override_review_board", {}).get("rows", [])
        if row.get("status") in {"expired", "expiring_soon"}
    ]
    if urgent_overrides:
        alerts.append(
            _alert(
                "high",
                "overrides",
                "Overrides are expired or expiring soon",
                f"{len(urgent_overrides)} override(s) require renewal or removal.",
                "override_review_board",
                "review_override_expiry",
                "PYTHONPATH=src python3 -m agent_architect_lab.cli override-review-board --limit 20",
            )
        )

    if failed_jobs:
        alerts.append(
            _alert(
                "high",
                "control_plane",
                "Dead-letter jobs are waiting for operator retry or cleanup",
                f"{len(failed_jobs)} failed job(s) are currently parked in the dead-letter view.",
                "dead_letter_jobs",
                "review_failed_jobs",
                "PYTHONPATH=src python3 -m agent_architect_lab.cli control-plane-dead-letter-jobs",
            )
        )

    if stale_workers:
        alerts.append(
            _alert(
                "high",
                "workers",
                "Worker heartbeats are stale",
                f"{len(stale_workers)} worker(s) have stale heartbeats: "
                + ", ".join(str(row.get("worker_id")) for row in stale_workers[:5]),
                "workers",
                "restart_or_replace_workers",
                "PYTHONPATH=src python3 -m agent_architect_lab.cli control-plane-workers",
            )
        )

    queued_jobs = int(control_plane_metrics.get("jobs", {}).get("totals", {}).get("queued_jobs", 0) or 0)
    oldest_queued_age_s = control_plane_metrics.get("jobs", {}).get("oldest_queued_age_s")
    if (
        isinstance(oldest_queued_age_s, (int, float))
        and queued_jobs > 0
        and float(oldest_queued_age_s) >= max(settings.control_plane_job_poll_interval_s * 20.0, 60.0)
    ):
        alerts.append(
            _alert(
                "medium",
                "queue",
                "Queued jobs are aging beyond the expected processing window",
                f"{queued_jobs} queued job(s); oldest queued age is {round(float(oldest_queued_age_s), 1)}s.",
                "job_queue_status",
                "inspect_queue_backlog",
                "PYTHONPATH=src python3 -m agent_architect_lab.cli control-plane-job-queue-status",
            )
        )

    if queued_jobs > 0 and not bool(control_plane_metrics.get("worker_process", {}).get("alive")):
        alerts.append(
            _alert(
                "high",
                "workers",
                "Queued jobs exist but the embedded worker is not alive",
                f"{queued_jobs} queued job(s) are waiting while worker '{control_plane_metrics.get('worker_process', {}).get('worker_id')}' is not alive.",
                "control_plane_metrics",
                "start_or_attach_worker",
                "PYTHONPATH=src python3 -m agent_architect_lab.cli run-control-plane-worker",
            )
        )

    urgent_feedback_count = int(governance.get("feedback_summary", {}).get("metrics", {}).get("urgent_feedback_count", 0) or 0)
    if urgent_feedback_count > 0:
        alerts.append(
            _alert(
                "medium",
                "feedback",
                "Urgent human feedback requires follow-up",
                f"{urgent_feedback_count} urgent feedback signal(s) are active in the governance summary.",
                "feedback_summary",
                "triage_feedback_followups",
                "PYTHONPATH=src python3 -m agent_architect_lab.cli feedback-summary --limit 20",
            )
        )
    return alerts


def _render_alert_summary(alerts: list[dict[str, Any]]) -> str:
    if not alerts:
        return "No active operator alerts."
    counts_by_severity: dict[str, int] = {}
    for alert in alerts:
        severity = str(alert.get("severity") or "low")
        counts_by_severity[severity] = counts_by_severity.get(severity, 0) + 1
    severity_text = ", ".join(
        f"{counts_by_severity[level]} {level}"
        for level in ("critical", "high", "medium", "low")
        if counts_by_severity.get(level)
    )
    top_titles = "; ".join(str(alert.get("title")) for alert in alerts[:3])
    return f"{severity_text} alert(s). Top items: {top_titles}."


def _alert(
    severity: str,
    category: str,
    title: str,
    summary: str,
    source_view: str,
    recommended_action: str,
    command: str,
) -> dict[str, Any]:
    return {
        "severity": severity,
        "category": category,
        "title": title,
        "summary": summary,
        "source_view": source_view,
        "recommended_action": recommended_action,
        "command": command,
    }
