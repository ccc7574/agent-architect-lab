from __future__ import annotations

import http.client
import io
import json
import sqlite3
import threading
import time
import zipfile
from contextlib import redirect_stdout
from pathlib import Path

from agent_architect_lab.cli import (
    cmd_backup_release_and_incident_ledgers,
    cmd_backup_control_plane_storage,
    cmd_control_plane_storage_status,
    cmd_export_release_command_brief,
    cmd_ledger_storage_status,
    cmd_approve_release,
    cmd_record_feedback,
    cmd_open_incident,
    cmd_record_operator_handoff,
    cmd_restore_release_and_incident_ledger_backup,
    cmd_restore_control_plane_backup,
    cmd_run_evals,
    cmd_run_control_plane_worker,
    cmd_run_planner_shadow,
    cmd_run_release_shadow,
    cmd_verify_release_and_incident_ledger_backup,
    cmd_verify_control_plane_backup,
)
from agent_architect_lab.config import load_settings
from agent_architect_lab.control_plane.jobs import ControlPlaneJobStore, ControlPlaneJobWorker
from agent_architect_lab.control_plane.repositories import create_local_control_plane_repositories
from agent_architect_lab.control_plane.reporting import record_operator_handoff_snapshot
from agent_architect_lab.control_plane.server import ControlPlaneApp, build_control_plane_app, create_control_plane_server
from agent_architect_lab.control_plane.sqlite_repositories import SQLiteControlPlaneJobStore, get_sqlite_schema_version


def _configure_env(
    monkeypatch,
    tmp_path: Path,
    *,
    mutation_token: str | None = "writer-token",
    control_plane_backend: str = "json",
) -> None:
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_ARTIFACTS", str(tmp_path / "artifacts"))
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_PRODUCTION_SOAK_MINUTES", "0")
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_PRODUCTION_REQUIRED_APPROVER_ROLES", "qa-owner,release-manager")
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_INCIDENT_STALE_MINUTES", "0")
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_CONTROL_PLANE_READ_TOKEN", "reader-token")
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_CONTROL_PLANE_STORAGE_BACKEND", control_plane_backend)
    if control_plane_backend == "sqlite":
        monkeypatch.setenv(
            "AGENT_ARCHITECT_LAB_CONTROL_PLANE_SQLITE_PATH",
            str(tmp_path / "artifacts" / "control-plane" / "control-plane.sqlite3"),
        )
    if mutation_token is None:
        monkeypatch.delenv("AGENT_ARCHITECT_LAB_CONTROL_PLANE_MUTATION_TOKEN", raising=False)
    else:
        monkeypatch.setenv("AGENT_ARCHITECT_LAB_CONTROL_PLANE_MUTATION_TOKEN", mutation_token)


def _seed_release_state() -> None:
    with redirect_stdout(io.StringIO()):
        cmd_run_evals("safety-baseline.json", "safety", "baseline", "approved-safety")
        cmd_run_release_shadow(["safety"], "release-a", "", True, "", "release-a")
        cmd_approve_release("release-a", "qa-owner", "", "qa approval")
        cmd_approve_release("release-a", "release-manager", "", "ops approval")
        cmd_open_incident(
            "critical",
            "unsafe production answer",
            "incident-commander",
            "production",
            "release-a",
            "/tmp/report.json",
            "customer escalation",
        )
        cmd_record_feedback(
            "release-manager requested rollback evidence",
            "release-manager-1",
            "release-manager",
            "negative",
            "followup_required",
            "release",
            "release-a",
            "",
            "",
            "",
            "",
            ["rollback"],
            "",
        )


def _seed_release_candidate() -> None:
    with redirect_stdout(io.StringIO()):
        cmd_run_evals("safety-baseline.json", "safety", "baseline", "approved-safety")
        cmd_run_release_shadow(["safety"], "release-b", "", True, "", "release-b")


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _identity_headers(actor: str, role: str) -> dict[str, str]:
    return {
        "X-Control-Plane-Actor": actor,
        "X-Control-Plane-Role": role,
    }


def _request_headers(
    token: str,
    *,
    actor: str,
    role: str,
    idempotency_key: str | None = None,
) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {token}",
        **_identity_headers(actor, role),
    }
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    return headers


def _build_app(settings) -> ControlPlaneApp:
    return build_control_plane_app(
        settings=settings,
        repositories=create_local_control_plane_repositories(settings),
    )


def test_control_plane_app_requires_read_token_for_governance_routes(monkeypatch, tmp_path: Path) -> None:
    _configure_env(monkeypatch, tmp_path)
    settings = load_settings()
    app = _build_app(settings)

    unauthorized = app.handle_request(
        "GET",
        "/governance-summary",
        _identity_headers("dashboard-user", "release-manager"),
        b"",
    )
    authorized = app.handle_request("GET", "/health", {}, b"")

    assert unauthorized.status_code == 401
    assert unauthorized.payload["error"]["code"] == "unauthorized"
    assert authorized.status_code == 200
    assert authorized.payload["status"] == "ok"


def test_control_plane_app_disables_mutation_routes_without_mutation_token(monkeypatch, tmp_path: Path) -> None:
    _configure_env(monkeypatch, tmp_path, mutation_token=None)
    settings = load_settings()
    app = _build_app(settings)

    response = app.handle_request(
        "POST",
        "/incidents/open",
        _request_headers(
            "reader-token",
            actor="incident-commander-1",
            role="incident-commander",
            idempotency_key="open-incident-1",
        ),
        json.dumps(
            {
                "severity": "high",
                "summary": "staging rollback triggered",
                "owner": "incident-commander",
            }
        ).encode("utf-8"),
    )

    assert response.status_code == 503
    assert response.payload["error"]["code"] == "mutation_token_not_configured"


def test_control_plane_app_requires_identity_for_governance_routes(monkeypatch, tmp_path: Path) -> None:
    _configure_env(monkeypatch, tmp_path)
    settings = load_settings()
    app = _build_app(settings)

    response = app.handle_request(
        "GET",
        "/governance-summary",
        _auth_header("reader-token"),
        b"",
    )
    audit_query = app.handle_request(
        "GET",
        "/audit-events?event_type=authorization_denied&error_code=missing_identity&path=/governance-summary",
        _request_headers(
            "reader-token",
            actor="release-manager-1",
            role="release-manager",
        ),
        b"",
    )

    assert response.status_code == 400
    assert response.payload["error"]["code"] == "missing_identity"
    assert response.payload["error"]["details"]["route_policy_key"] == "read_governance"
    assert response.payload["error"]["details"]["required_headers"] == ["X-Control-Plane-Actor", "X-Control-Plane-Role"]
    assert audit_query.status_code == 200
    assert audit_query.payload["rows"]
    assert audit_query.payload["rows"][0]["event_type"] == "authorization_denied"
    assert audit_query.payload["rows"][0]["error_code"] == "missing_identity"


def test_control_plane_app_exposes_release_read_surfaces(monkeypatch, tmp_path: Path) -> None:
    _configure_env(monkeypatch, tmp_path)
    _seed_release_state()
    settings = load_settings()
    app = _build_app(settings)

    environment_status = app.handle_request(
        "GET",
        "/environments/production/status",
        _request_headers("reader-token", actor="release-manager-1", role="release-manager"),
        b"",
    )
    active_overrides = app.handle_request(
        "GET",
        "/active-overrides?limit=10",
        _request_headers("reader-token", actor="release-manager-1", role="release-manager"),
        b"",
    )
    readiness_digest = app.handle_request(
        "GET",
        "/releases/release-a/readiness-digest?environment=production",
        _request_headers("reader-token", actor="release-manager-1", role="release-manager"),
        b"",
    )
    rollout_matrix = app.handle_request(
        "GET",
        "/rollout-matrix?environment=production&release_name=release-a",
        _request_headers("reader-token", actor="release-manager-1", role="release-manager"),
        b"",
    )
    deploy_readiness = app.handle_request(
        "GET",
        "/releases/release-a/deploy-readiness?environment=production",
        _request_headers("reader-token", actor="release-manager-1", role="release-manager"),
        b"",
    )

    assert environment_status.status_code == 200
    assert environment_status.payload["environment"] == "production"
    assert active_overrides.status_code == 200
    assert active_overrides.payload["rows"] == []
    assert readiness_digest.status_code == 200
    assert readiness_digest.payload["release_name"] == "release-a"
    assert rollout_matrix.status_code == 200
    assert rollout_matrix.payload["release_name"] == "release-a"
    assert rollout_matrix.payload["rows"][0]["environment"] == "production"
    assert deploy_readiness.status_code == 200
    assert deploy_readiness.payload["release_name"] == "release-a"
    assert deploy_readiness.payload["environment"] == "production"


def test_control_plane_app_rejects_forbidden_role(monkeypatch, tmp_path: Path) -> None:
    _configure_env(monkeypatch, tmp_path)
    settings = load_settings()
    app = _build_app(settings)

    response = app.handle_request(
        "POST",
        "/incidents/open",
        _request_headers(
            "writer-token",
            actor="qa-owner-1",
            role="qa-owner",
            idempotency_key="open-incident-1",
        ),
        json.dumps(
            {
                "severity": "high",
                "summary": "staging rollback triggered",
                "owner": "incident-commander",
            }
        ).encode("utf-8"),
    )

    assert response.status_code == 403
    assert response.payload["error"]["code"] == "forbidden_role"
    assert response.payload["error"]["details"]["route_policy_key"] == "open_incident"
    assert response.payload["error"]["details"]["role"] == "qa-owner"
    assert "incident-commander" in response.payload["error"]["details"]["required_roles"]


def test_control_plane_app_requires_idempotency_key_for_mutations(monkeypatch, tmp_path: Path) -> None:
    _configure_env(monkeypatch, tmp_path)
    settings = load_settings()
    app = _build_app(settings)

    response = app.handle_request(
        "POST",
        "/incidents/open",
        _request_headers(
            "writer-token",
            actor="incident-commander-1",
            role="incident-commander",
        ),
        json.dumps(
            {
                "severity": "high",
                "summary": "staging rollback triggered",
                "owner": "incident-commander",
                "environment": "staging",
                "release_name": "release-a",
            }
        ).encode("utf-8"),
    )

    assert response.status_code == 400
    assert response.payload["error"]["code"] == "invalid_request"
    assert "Idempotency-Key" in response.payload["error"]["message"]


def test_control_plane_app_replays_idempotent_mutation_and_writes_audit(monkeypatch, tmp_path: Path) -> None:
    _configure_env(monkeypatch, tmp_path)
    settings = load_settings()
    app = _build_app(settings)

    opened = app.handle_request(
        "POST",
        "/incidents/open",
        _request_headers(
            "writer-token",
            actor="incident-commander-1",
            role="incident-commander",
            idempotency_key="open-incident-1",
        ),
        json.dumps(
            {
                "severity": "high",
                "summary": "staging rollback triggered",
                "owner": "incident-commander",
                "environment": "staging",
                "release_name": "release-a",
            }
        ).encode("utf-8"),
    )
    replayed = app.handle_request(
        "POST",
        "/incidents/open",
        _request_headers(
            "writer-token",
            actor="incident-commander-1",
            role="incident-commander",
            idempotency_key="open-incident-1",
        ),
        json.dumps(
            {
                "severity": "high",
                "summary": "staging rollback triggered",
                "owner": "incident-commander",
                "environment": "staging",
                "release_name": "release-a",
            }
        ).encode("utf-8"),
    )
    transitioned = app.handle_request(
        "POST",
        f"/incidents/{opened.payload['incident_id']}/transition",
        _request_headers(
            "writer-token",
            actor="incident-commander-1",
            role="incident-commander",
            idempotency_key="transition-incident-1",
        ),
        json.dumps(
            {
                "status": "acknowledged",
                "by": "incident-commander",
                "note": "triage started",
            }
        ).encode("utf-8"),
    )
    audit_rows = [
        json.loads(line)
        for line in settings.control_plane_request_log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert opened.status_code == 201
    assert opened.payload["status"] == "open"
    assert opened.payload["_control_plane"]["replayed"] is False
    assert replayed.status_code == 201
    assert replayed.payload["incident_id"] == opened.payload["incident_id"]
    assert replayed.payload["_control_plane"]["replayed"] is True
    assert transitioned.status_code == 200
    assert transitioned.payload["status"] == "acknowledged"
    assert transitioned.payload["events"][-1]["to_status"] == "acknowledged"
    assert len(audit_rows) == 3
    assert audit_rows[1]["replayed"] is True
    assert audit_rows[1]["operation_id"] == audit_rows[0]["operation_id"]
    assert audit_rows[0]["token_fingerprint"] is not None
    assert audit_rows[0]["actor"] == "incident-commander-1"
    assert audit_rows[0]["role"] == "incident-commander"
    assert audit_rows[0]["token_scope"] == "mutation"

    request_id = opened.payload["_meta"]["request_id"]
    operation_id = opened.payload["_control_plane"]["operation_id"]
    audit_query = app.handle_request(
        "GET",
        f"/audit-events?request_id={request_id}",
        _request_headers(
            "reader-token",
            actor="release-manager-1",
            role="release-manager",
        ),
        b"",
    )
    replayed_audit_query = app.handle_request(
        "GET",
        "/audit-events?actor=incident-commander-1&method=POST&path=/incidents/open&replayed=true",
        _request_headers(
            "reader-token",
            actor="release-manager-1",
            role="release-manager",
        ),
        b"",
    )
    idempotency_query = app.handle_request(
        "GET",
        "/idempotency-records/open-incident-1",
        _request_headers(
            "reader-token",
            actor="release-manager-1",
            role="release-manager",
        ),
        b"",
    )
    idempotency_list_query = app.handle_request(
        "GET",
        f"/idempotency-records?method=POST&path=/incidents/open&operation_id={operation_id}",
        _request_headers(
            "reader-token",
            actor="release-manager-1",
            role="release-manager",
        ),
        b"",
    )

    assert audit_query.status_code == 200
    assert audit_query.payload["rows"]
    assert audit_query.payload["rows"][0]["operation_id"] == operation_id
    assert replayed_audit_query.status_code == 200
    assert replayed_audit_query.payload["rows"]
    assert replayed_audit_query.payload["rows"][0]["replayed"] is True
    assert replayed_audit_query.payload["rows"][0]["path"] == "/incidents/open"
    assert idempotency_query.status_code == 200
    assert idempotency_query.payload["idempotency_key"] == "open-incident-1"
    assert idempotency_list_query.status_code == 200
    assert idempotency_list_query.payload["rows"]
    assert idempotency_list_query.payload["rows"][0]["operation_id"] == operation_id


def test_control_plane_app_links_incident_followup_eval(monkeypatch, tmp_path: Path) -> None:
    _configure_env(monkeypatch, tmp_path)
    settings = load_settings()
    app = _build_app(settings)

    opened = app.handle_request(
        "POST",
        "/incidents/open",
        _request_headers(
            "writer-token",
            actor="incident-commander-1",
            role="incident-commander",
            idempotency_key="open-incident-followup-1",
        ),
        json.dumps(
            {
                "severity": "high",
                "summary": "follow-up eval linkage required",
                "owner": "incident-commander",
            }
        ).encode("utf-8"),
    )
    linked = app.handle_request(
        "POST",
        f"/incidents/{opened.payload['incident_id']}/followup-eval",
        _request_headers(
            "writer-token",
            actor="incident-commander-1",
            role="incident-commander",
            idempotency_key="link-followup-eval-1",
        ),
        json.dumps(
            {
                "followup_eval_path": "/tmp/followup-eval.jsonl",
                "by": "incident-commander",
                "note": "bind eval artifact",
            }
        ).encode("utf-8"),
    )

    assert opened.status_code == 201
    assert linked.status_code == 200
    assert linked.payload["followup_eval_path"] == "/tmp/followup-eval.jsonl"
    assert linked.payload["followup_eval_linked_by"] == "incident-commander"
    assert linked.payload["followup_eval_linked_at"] is not None
    assert linked.payload["events"][-1]["action"] == "link_followup_eval"


def test_control_plane_app_records_feedback_and_reads_summary(monkeypatch, tmp_path: Path) -> None:
    _configure_env(monkeypatch, tmp_path)
    settings = load_settings()
    app = _build_app(settings)

    created = app.handle_request(
        "POST",
        "/feedback",
        _request_headers(
            "writer-token",
            actor="release-manager-1",
            role="release-manager",
            idempotency_key="feedback-1",
        ),
        json.dumps(
            {
                "actor": "release-manager-1",
                "role": "release-manager",
                "sentiment": "negative",
                "actionability": "followup_required",
                "target_kind": "release",
                "summary": "needs stronger rollback proof",
                "release_name": "release-a",
                "labels": ["rollback", "review"],
            }
        ).encode("utf-8"),
    )
    listed = app.handle_request(
        "GET",
        "/feedback?release_name=release-a&limit=10",
        _request_headers(
            "reader-token",
            actor="release-manager-1",
            role="release-manager",
        ),
        b"",
    )
    summary = app.handle_request(
        "GET",
        "/feedback-summary?release_name=release-a&limit=10",
        _request_headers(
            "reader-token",
            actor="release-manager-1",
            role="release-manager",
        ),
        b"",
    )

    assert created.status_code == 201
    assert created.payload["feedback_id"].startswith("feedback-")
    assert listed.status_code == 200
    assert listed.payload["rows"][0]["summary"] == "needs stronger rollback proof"
    assert summary.status_code == 200
    assert summary.payload["metrics"]["total_feedback_count"] == 1
    assert summary.payload["metrics"]["negative_feedback_count"] == 1


def test_control_plane_app_rejects_conflicting_idempotency_reuse(monkeypatch, tmp_path: Path) -> None:
    _configure_env(monkeypatch, tmp_path)
    settings = load_settings()
    app = _build_app(settings)

    first = app.handle_request(
        "POST",
        "/incidents/open",
        _request_headers(
            "writer-token",
            actor="incident-commander-1",
            role="incident-commander",
            idempotency_key="open-incident-1",
        ),
        json.dumps(
            {
                "severity": "high",
                "summary": "staging rollback triggered",
                "owner": "incident-commander",
            }
        ).encode("utf-8"),
    )
    conflicting = app.handle_request(
        "POST",
        "/incidents/open",
        _request_headers(
            "writer-token",
            actor="incident-commander-1",
            role="incident-commander",
            idempotency_key="open-incident-1",
        ),
        json.dumps(
            {
                "severity": "critical",
                "summary": "different payload",
                "owner": "incident-commander",
            }
        ).encode("utf-8"),
    )

    assert first.status_code == 201
    assert conflicting.status_code == 409
    assert conflicting.payload["error"]["code"] == "idempotency_conflict"


def test_control_plane_app_approves_release_via_control_plane(monkeypatch, tmp_path: Path) -> None:
    _configure_env(monkeypatch, tmp_path)
    _seed_release_candidate()
    settings = load_settings()
    app = _build_app(settings)

    approved = app.handle_request(
        "POST",
        "/releases/release-b/approve",
        _request_headers(
            "writer-token",
            actor="qa-owner-1",
            role="qa-owner",
            idempotency_key="approve-release-b-1",
        ),
        json.dumps({"note": "qa sign-off", "role": "qa-owner"}).encode("utf-8"),
    )
    fetched = app.handle_request(
        "GET",
        "/releases/release-b",
        _request_headers(
            "reader-token",
            actor="release-manager-1",
            role="release-manager",
        ),
        b"",
    )

    assert approved.status_code == 200
    assert approved.payload["approvals"][0]["role"] == "qa-owner"
    assert approved.payload["_control_plane"]["replayed"] is False
    assert fetched.status_code == 200
    assert fetched.payload["release_name"] == "release-b"
    assert fetched.payload["approvals"][0]["actor"] == "qa-owner-1"


def test_control_plane_app_blocks_mismatched_approval_role(monkeypatch, tmp_path: Path) -> None:
    _configure_env(monkeypatch, tmp_path)
    _seed_release_candidate()
    settings = load_settings()
    app = _build_app(settings)

    response = app.handle_request(
        "POST",
        "/releases/release-b/approve",
        _request_headers(
            "writer-token",
            actor="qa-owner-1",
            role="qa-owner",
            idempotency_key="approve-release-b-2",
        ),
        json.dumps({"note": "wrong role attempt", "role": "release-manager"}).encode("utf-8"),
    )
    audit_query = app.handle_request(
        "GET",
        "/audit-events?event_type=payload_denied&error_code=forbidden_approval_role&path=/releases/release-b/approve",
        _request_headers(
            "reader-token",
            actor="release-manager-1",
            role="release-manager",
        ),
        b"",
    )

    assert response.status_code == 403
    assert response.payload["error"]["code"] == "forbidden_approval_role"
    assert response.payload["error"]["details"]["route_policy_key"] == "approve_release"
    assert response.payload["error"]["details"]["requested_role"] == "release-manager"
    assert audit_query.status_code == 200
    assert audit_query.payload["rows"]
    assert audit_query.payload["rows"][0]["event_type"] == "payload_denied"
    assert audit_query.payload["rows"][0]["error_code"] == "forbidden_approval_role"


def test_control_plane_worker_retries_job_until_success(monkeypatch, tmp_path: Path) -> None:
    _configure_env(monkeypatch, tmp_path)
    settings = load_settings()
    store = ControlPlaneJobStore(settings.control_plane_job_registry_path)
    call_count = {"value": 0}

    def flaky_handler(_settings, payload):
        call_count["value"] += 1
        if call_count["value"] == 1:
            raise ValueError("transient export failure")
        return {"task": payload["task"], "attempt": call_count["value"]}

    worker = ControlPlaneJobWorker(
        settings=settings,
        store=store,
        handlers={"flaky_job": flaky_handler},
        poll_interval_s=0.01,
    )
    store.create_job(
        job_type="flaky_job",
        payload={"task": "governance-export"},
        requested_by_actor="release-manager-1",
        requested_by_role="release-manager",
        request_id="req-flaky-job",
        operation_id=None,
        max_attempts=2,
    )

    worker.start()
    try:
        for _ in range(40):
            time.sleep(0.05)
            job = store.list_jobs(limit=1)[0]
            if job.status == "succeeded":
                break
        else:
            job = store.list_jobs(limit=1)[0]

        assert job.status == "succeeded"
        assert job.attempts == 2
        assert job.error is None
        assert job.last_error is not None
        assert job.last_error["code"] == "job_execution_failed"
        assert job.last_error["message"] == "transient export failure"
        assert job.result_payload == {"task": "governance-export", "attempt": 2}
        assert job.queue_reason == "completed"
    finally:
        worker.stop()


def test_control_plane_job_store_requeues_expired_lease(monkeypatch, tmp_path: Path) -> None:
    _configure_env(monkeypatch, tmp_path)
    settings = load_settings()
    store = ControlPlaneJobStore(settings.control_plane_job_registry_path)
    job = store.create_job(
        job_type="export_governance_summary",
        payload={"title": "lease-test"},
        requested_by_actor="release-manager-1",
        requested_by_role="release-manager",
        request_id="req-lease-json",
        operation_id=None,
        max_attempts=2,
    )

    claimed = store.claim_next_job(worker_id="worker-a", lease_ttl_s=0.1)
    assert claimed is not None
    assert claimed.job_id == job.job_id
    assert claimed.status == "running"
    assert claimed.worker_id == "worker-a"
    assert claimed.lease_expires_at is not None

    time.sleep(0.16)
    requeued = store.requeue_stale_jobs()
    refreshed = store.get_job(job.job_id)

    assert len(requeued) == 1
    assert requeued[0].job_id == job.job_id
    assert refreshed.status == "queued"
    assert refreshed.queue_reason == "lease_expired_retry"
    assert refreshed.worker_id is None
    assert refreshed.lease_expires_at is None


def test_sqlite_job_store_requeues_expired_lease(monkeypatch, tmp_path: Path) -> None:
    _configure_env(monkeypatch, tmp_path, control_plane_backend="sqlite")
    settings = load_settings()
    store = SQLiteControlPlaneJobStore(settings.control_plane_sqlite_path)
    job = store.create_job(
        job_type="export_governance_summary",
        payload={"title": "sqlite-lease-test"},
        requested_by_actor="release-manager-1",
        requested_by_role="release-manager",
        request_id="req-lease-sqlite",
        operation_id=None,
        max_attempts=2,
    )

    claimed = store.claim_next_job(worker_id="worker-sqlite", lease_ttl_s=0.1)
    assert claimed is not None
    assert claimed.job_id == job.job_id
    assert claimed.worker_id == "worker-sqlite"

    time.sleep(0.16)
    requeued = store.requeue_stale_jobs()
    refreshed = store.get_job(job.job_id)

    assert len(requeued) == 1
    assert refreshed.status == "queued"
    assert refreshed.queue_reason == "lease_expired_retry"
    assert refreshed.worker_id is None
    assert refreshed.lease_expires_at is None


def test_control_plane_server_smoke_exposes_read_and_write_routes(monkeypatch, tmp_path: Path) -> None:
    _configure_env(monkeypatch, tmp_path)
    _seed_release_state()
    settings = load_settings()
    server, _app = create_control_plane_server(settings=settings, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    host, port = server.server_address[:2]
    try:
        connection = http.client.HTTPConnection(host, port, timeout=5)

        connection.request("GET", "/health")
        health_response = connection.getresponse()
        health_payload = json.loads(health_response.read().decode("utf-8"))

        connection.request(
            "GET",
            "/release-risk-board?limit=5",
            headers=_request_headers(
                "reader-token",
                actor="release-manager-1",
                role="release-manager",
            ),
        )
        risk_response = connection.getresponse()
        risk_payload = json.loads(risk_response.read().decode("utf-8"))

        connection.request(
            "POST",
            "/incidents/open",
            body=json.dumps(
                {
                    "severity": "medium",
                    "summary": "fresh incident from smoke test",
                    "owner": "smoke-owner",
                    "environment": "production",
                }
            ),
            headers={
                "Content-Type": "application/json",
                **_request_headers(
                    "writer-token",
                    actor="incident-commander-1",
                    role="incident-commander",
                    idempotency_key="smoke-open-incident-1",
                ),
            },
        )
        incident_response = connection.getresponse()
        incident_payload = json.loads(incident_response.read().decode("utf-8"))
        connection.close()

        assert health_response.status == 200
        assert health_payload["status"] == "ok"
        assert health_payload["worker"]["worker_id"].startswith("worker-")
        assert health_payload["worker"]["lease_ttl_s"] > 0
        assert health_payload["worker"]["heartbeat_interval_s"] > 0
        assert risk_response.status == 200
        assert risk_payload["rows"]
        assert risk_payload["rows"][0]["release_name"] == "release-a"
        assert incident_response.status == 201
        assert incident_payload["status"] == "open"
        assert incident_payload["_control_plane"]["replayed"] is False
        assert incident_payload["_meta"]["request_id"].startswith("req-")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_control_plane_server_runs_export_jobs(monkeypatch, tmp_path: Path) -> None:
    _configure_env(monkeypatch, tmp_path)
    _seed_release_state()
    with redirect_stdout(io.StringIO()):
        cmd_run_planner_shadow(
            "planner_shadow",
            "planner-shadow-preseed.json",
            [],
            [],
            str(tmp_path / "planner-shadow-preseed.md"),
            "Preseed Planner Shadow",
        )
        cmd_export_release_command_brief(
            "release-a",
            [],
            5,
            10,
            str(tmp_path / "release-command-preseed.md"),
            "Preseed Release Brief",
        )
    settings = load_settings()
    server, _app = create_control_plane_server(settings=settings, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    host, port = server.server_address[:2]
    try:
        connection = http.client.HTTPConnection(host, port, timeout=5)
        connection.request(
            "POST",
            "/jobs/export-governance-summary",
            body=json.dumps(
                {
                    "title": "Async Governance Summary",
                    "output": str(tmp_path / "async-governance.md"),
                    "release_limit": 5,
                    "incident_limit": 5,
                    "override_limit": 5,
                }
            ),
            headers={
                "Content-Type": "application/json",
                **_request_headers(
                    "writer-token",
                    actor="release-manager-1",
                    role="release-manager",
                    idempotency_key="job-governance-summary-1",
                ),
            },
        )
        create_response = connection.getresponse()
        create_payload = json.loads(create_response.read().decode("utf-8"))
        job_id = create_payload["job_id"]

        for _ in range(50):
            time.sleep(0.05)
            connection.request(
                "GET",
                f"/jobs/{job_id}",
                headers=_request_headers(
                    "reader-token",
                    actor="release-manager-1",
                    role="release-manager",
                ),
            )
            status_response = connection.getresponse()
            status_payload = json.loads(status_response.read().decode("utf-8"))
            if status_payload["status"] in {"succeeded", "failed"}:
                break
        connection.request(
            "GET",
            "/audit-events?limit=5",
            headers=_request_headers(
                "reader-token",
                actor="release-manager-1",
                role="release-manager",
            ),
        )
        audit_response = connection.getresponse()
        audit_payload = json.loads(audit_response.read().decode("utf-8"))
        connection.close()

        assert create_response.status == 202
        assert create_payload["status"] == "queued"
        assert status_payload["status"] == "succeeded"
        assert Path(status_payload["result_payload"]["saved_to"]).exists()
        assert Path(status_payload["result_payload"]["json_path"]).exists()
        markdown = Path(status_payload["result_payload"]["saved_to"]).read_text(encoding="utf-8")
        assert "Async Governance Summary" in markdown
        assert "## Runtime Realism" in markdown
        assert "## Recent Feedback" in markdown
        assert "## Artifact Lineage" in markdown
        assert "planner-shadow-preseed.json" in markdown
        assert "release-a" in markdown
        assert audit_response.status == 200
        assert audit_payload["rows"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_control_plane_server_can_use_standalone_worker(monkeypatch, tmp_path: Path) -> None:
    _configure_env(monkeypatch, tmp_path)
    _seed_release_state()
    settings = load_settings()
    server, _app = create_control_plane_server(settings=settings, host="127.0.0.1", port=0, start_worker=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    host, port = server.server_address[:2]
    try:
        connection = http.client.HTTPConnection(host, port, timeout=5)
        connection.request("GET", "/health")
        health_response = connection.getresponse()
        health_payload = json.loads(health_response.read().decode("utf-8"))

        connection.request(
            "POST",
            "/jobs/export-governance-summary",
            body=json.dumps(
                {
                    "title": "External Worker Summary",
                    "output": str(tmp_path / "external-worker-summary.md"),
                    "release_limit": 5,
                    "incident_limit": 5,
                    "override_limit": 5,
                }
            ),
            headers={
                "Content-Type": "application/json",
                **_request_headers(
                    "writer-token",
                    actor="release-manager-1",
                    role="release-manager",
                    idempotency_key="job-external-worker-summary-1",
                ),
            },
        )
        create_response = connection.getresponse()
        create_payload = json.loads(create_response.read().decode("utf-8"))

        worker_stdout = io.StringIO()
        with redirect_stdout(worker_stdout):
            worker_exit = cmd_run_control_plane_worker(True, None)
        worker_payload = json.loads(worker_stdout.getvalue())

        connection.request(
            "GET",
            f"/jobs/{create_payload['job_id']}",
            headers=_request_headers(
                "reader-token",
                actor="release-manager-1",
                role="release-manager",
            ),
        )
        status_response = connection.getresponse()
        status_payload = json.loads(status_response.read().decode("utf-8"))
        connection.close()

        assert health_response.status == 200
        assert health_payload["worker"]["alive"] is False
        assert health_payload["worker"]["managed_by_server"] is False
        assert create_response.status == 202
        assert create_payload["status"] == "queued"
        assert worker_exit == 0
        assert worker_payload["processed_jobs"] == 1
        assert status_response.status == 200
        assert status_payload["status"] == "succeeded"
        assert Path(status_payload["result_payload"]["saved_to"]).exists()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_control_plane_server_exposes_job_queue_status(monkeypatch, tmp_path: Path) -> None:
    _configure_env(monkeypatch, tmp_path)
    settings = load_settings()
    repositories = create_local_control_plane_repositories(settings)
    repositories.jobs.create_job(
        job_type="backup_control_plane_storage",
        payload={"output": str(tmp_path / "backup.zip"), "label": "queue-http"},
        requested_by_actor="ops-oncall-1",
        requested_by_role="ops-oncall",
        request_id="req-queue-http",
        operation_id=None,
        max_attempts=1,
    )
    claimed = repositories.jobs.claim_next_job(worker_id="worker-http", lease_ttl_s=10.0)
    assert claimed is not None
    server, _app = create_control_plane_server(settings=settings, host="127.0.0.1", port=0, start_worker=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    host, port = server.server_address[:2]
    try:
        connection = http.client.HTTPConnection(host, port, timeout=5)
        connection.request(
            "GET",
            "/job-queue-status",
            headers=_request_headers(
                "reader-token",
                actor="release-manager-1",
                role="release-manager",
            ),
        )
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        connection.close()

        assert response.status == 200
        assert payload["totals"]["jobs"] == 1
        assert payload["totals"]["running_jobs"] == 1
        assert payload["counts_by_status"]["running"] == 1
        assert payload["running_workers"][0]["worker_id"] == "worker-http"
        assert payload["running_workers"][0]["running_jobs"] == 1
        assert payload["stale_running_jobs"] == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_control_plane_server_exposes_registered_workers(monkeypatch, tmp_path: Path) -> None:
    _configure_env(monkeypatch, tmp_path)
    settings = load_settings()
    repositories = create_local_control_plane_repositories(settings)
    repositories.workers.heartbeat_worker(
        worker_id="worker-http-registry",
        managed_by_server=False,
        poll_interval_s=0.25,
        lease_ttl_s=5.0,
        heartbeat_interval_s=1.0,
    )
    server, _app = create_control_plane_server(settings=settings, host="127.0.0.1", port=0, start_worker=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    host, port = server.server_address[:2]
    try:
        connection = http.client.HTTPConnection(host, port, timeout=5)
        connection.request(
            "GET",
            "/workers",
            headers=_request_headers(
                "reader-token",
                actor="release-manager-1",
                role="release-manager",
            ),
        )
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        connection.close()

        assert response.status == 200
        assert payload["summary"]["totals"]["workers"] >= 1
        assert payload["summary"]["counts_by_health"]["healthy"] >= 1
        assert any(row["worker_id"] == "worker-http-registry" for row in payload["rows"])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_control_plane_server_filters_stale_workers(monkeypatch, tmp_path: Path) -> None:
    _configure_env(monkeypatch, tmp_path)
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_CONTROL_PLANE_WORKER_STALE_AFTER_S", "0.01")
    settings = load_settings()
    repositories = create_local_control_plane_repositories(settings)
    repositories.workers.heartbeat_worker(
        worker_id="worker-http-stale",
        managed_by_server=False,
        poll_interval_s=0.01,
        lease_ttl_s=5.0,
        heartbeat_interval_s=0.01,
    )
    time.sleep(0.05)
    server, _app = create_control_plane_server(settings=settings, host="127.0.0.1", port=0, start_worker=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    host, port = server.server_address[:2]
    try:
        connection = http.client.HTTPConnection(host, port, timeout=5)
        connection.request(
            "GET",
            "/workers?health=stale",
            headers=_request_headers(
                "reader-token",
                actor="release-manager-1",
                role="release-manager",
            ),
        )
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        connection.request("GET", "/health")
        health_response = connection.getresponse()
        health_payload = json.loads(health_response.read().decode("utf-8"))
        connection.close()

        assert response.status == 200
        assert payload["summary"]["totals"]["stale_workers"] == 1
        assert payload["rows"][0]["worker_id"] == "worker-http-stale"
        assert payload["rows"][0]["health_status"] == "stale"
        assert health_response.status == 200
        assert health_payload["worker_registry"]["stale_workers"] == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_control_plane_server_exposes_dead_letter_jobs(monkeypatch, tmp_path: Path) -> None:
    _configure_env(monkeypatch, tmp_path)
    settings = load_settings()
    repositories = create_local_control_plane_repositories(settings)
    job = repositories.jobs.create_job(
        job_type="backup_control_plane_storage",
        payload={"label": "dead-letter"},
        requested_by_actor="ops-oncall-1",
        requested_by_role="ops-oncall",
        request_id="req-dead-letter-http",
        operation_id=None,
        max_attempts=1,
    )
    claimed = repositories.jobs.claim_next_job(worker_id="worker-http-dead-letter", lease_ttl_s=5.0)
    assert claimed is not None
    repositories.jobs.fail_job(
        job.job_id,
        {
            "code": "job_execution_failed",
            "message": "backup archive write failed",
        },
    )

    server, _app = create_control_plane_server(settings=settings, host="127.0.0.1", port=0, start_worker=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    host, port = server.server_address[:2]
    try:
        connection = http.client.HTTPConnection(host, port, timeout=5)
        connection.request(
            "GET",
            "/dead-letter-jobs",
            headers=_request_headers(
                "reader-token",
                actor="release-manager-1",
                role="release-manager",
            ),
        )
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        connection.request(
            "GET",
            "/job-queue-status",
            headers=_request_headers(
                "reader-token",
                actor="release-manager-1",
                role="release-manager",
            ),
        )
        summary_response = connection.getresponse()
        summary_payload = json.loads(summary_response.read().decode("utf-8"))
        connection.close()

        assert response.status == 200
        assert payload["total"] == 1
        assert payload["counts_by_job_type"]["backup_control_plane_storage"] == 1
        assert payload["rows"][0]["job_id"] == job.job_id
        assert payload["rows"][0]["error_code"] == "job_execution_failed"
        assert summary_response.status == 200
        assert summary_payload["totals"]["dead_letter_jobs"] == 1
        assert summary_payload["counts_by_queue_reason"]["failed"] == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_control_plane_server_exposes_metrics_snapshot(monkeypatch, tmp_path: Path) -> None:
    _configure_env(monkeypatch, tmp_path)
    settings = load_settings()
    repositories = create_local_control_plane_repositories(settings)
    repositories.jobs.create_job(
        job_type="backup_control_plane_storage",
        payload={"label": "metrics"},
        requested_by_actor="ops-oncall-1",
        requested_by_role="ops-oncall",
        request_id="req-metrics-http",
        operation_id=None,
        max_attempts=1,
    )
    repositories.workers.heartbeat_worker(
        worker_id="worker-http-metrics",
        managed_by_server=False,
        poll_interval_s=0.25,
        lease_ttl_s=5.0,
        heartbeat_interval_s=1.0,
    )
    server, _app = create_control_plane_server(settings=settings, host="127.0.0.1", port=0, start_worker=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    host, port = server.server_address[:2]
    try:
        connection = http.client.HTTPConnection(host, port, timeout=5)
        connection.request(
            "GET",
            "/metrics",
            headers=_request_headers(
                "reader-token",
                actor="release-manager-1",
                role="release-manager",
            ),
        )
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        connection.close()

        assert response.status == 200
        assert payload["jobs"]["totals"]["jobs"] == 1
        assert payload["jobs"]["counts_by_status"]["queued"] == 1
        assert payload["workers"]["totals"]["workers"] == 1
        assert payload["worker_process"]["managed_by_server"] is False
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_control_plane_server_exposes_release_read_surfaces(monkeypatch, tmp_path: Path) -> None:
    _configure_env(monkeypatch, tmp_path)
    _seed_release_state()
    settings = load_settings()
    server, _app = create_control_plane_server(settings=settings, host="127.0.0.1", port=0, start_worker=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    host, port = server.server_address[:2]
    try:
        connection = http.client.HTTPConnection(host, port, timeout=5)
        headers = _request_headers(
            "reader-token",
            actor="release-manager-1",
            role="release-manager",
        )
        connection.request("GET", "/environments/production/status", headers=headers)
        environment_status_response = connection.getresponse()
        environment_status_payload = json.loads(environment_status_response.read().decode("utf-8"))

        connection.request("GET", "/environments/production/history?limit=10", headers=headers)
        environment_history_response = connection.getresponse()
        environment_history_payload = json.loads(environment_history_response.read().decode("utf-8"))

        connection.request("GET", "/environments/production/deploy-policy", headers=headers)
        deploy_policy_response = connection.getresponse()
        deploy_policy_payload = json.loads(deploy_policy_response.read().decode("utf-8"))

        connection.request("GET", "/releases/release-a/readiness-digest?environment=production", headers=headers)
        readiness_digest_response = connection.getresponse()
        readiness_digest_payload = json.loads(readiness_digest_response.read().decode("utf-8"))

        connection.request("GET", "/releases/release-a/deploy-readiness?environment=production", headers=headers)
        deploy_readiness_response = connection.getresponse()
        deploy_readiness_payload = json.loads(deploy_readiness_response.read().decode("utf-8"))

        connection.request("GET", "/rollout-matrix?environment=production&release_name=release-a", headers=headers)
        rollout_matrix_response = connection.getresponse()
        rollout_matrix_payload = json.loads(rollout_matrix_response.read().decode("utf-8"))

        connection.request("GET", "/active-overrides?limit=10", headers=headers)
        active_overrides_response = connection.getresponse()
        active_overrides_payload = json.loads(active_overrides_response.read().decode("utf-8"))
        connection.close()

        assert environment_status_response.status == 200
        assert environment_status_payload["environment"] == "production"
        assert environment_history_response.status == 200
        assert environment_history_payload["rows"] == []
        assert deploy_policy_response.status == 200
        assert deploy_policy_payload["environment"] == "production"
        assert readiness_digest_response.status == 200
        assert readiness_digest_payload["release_name"] == "release-a"
        assert deploy_readiness_response.status == 200
        assert deploy_readiness_payload["environment"] == "production"
        assert rollout_matrix_response.status == 200
        assert rollout_matrix_payload["release_name"] == "release-a"
        assert active_overrides_response.status == 200
        assert active_overrides_payload["rows"] == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_control_plane_server_exposes_operator_alert_board(monkeypatch, tmp_path: Path) -> None:
    _configure_env(monkeypatch, tmp_path)
    _seed_release_state()
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_CONTROL_PLANE_WORKER_STALE_AFTER_S", "0.01")
    settings = load_settings()
    repositories = create_local_control_plane_repositories(settings)
    job = repositories.jobs.create_job(
        job_type="backup_control_plane_storage",
        payload={"label": "alerts"},
        requested_by_actor="ops-oncall-1",
        requested_by_role="ops-oncall",
        request_id="req-alerts-http",
        operation_id=None,
        max_attempts=1,
    )
    claimed = repositories.jobs.claim_next_job(worker_id="worker-http-alerts", lease_ttl_s=5.0)
    assert claimed is not None
    repositories.jobs.fail_job(
        job.job_id,
        {
            "code": "job_execution_failed",
            "message": "backup archive write failed",
        },
    )
    repositories.workers.heartbeat_worker(
        worker_id="worker-http-alert-stale",
        managed_by_server=False,
        poll_interval_s=0.01,
        lease_ttl_s=5.0,
        heartbeat_interval_s=0.01,
    )
    time.sleep(0.05)
    server, _app = create_control_plane_server(settings=settings, host="127.0.0.1", port=0, start_worker=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    host, port = server.server_address[:2]
    try:
        connection = http.client.HTTPConnection(host, port, timeout=5)
        connection.request(
            "GET",
            "/operator-alert-board?alert_limit=10",
            headers=_request_headers(
                "reader-token",
                actor="release-manager-1",
                role="release-manager",
            ),
        )
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        connection.close()

        titles = [row["title"] for row in payload["alerts"]]
        assert response.status == 200
        assert payload["metrics"]["total_alerts"] >= 3
        assert any("Critical incidents" in title for title in titles)
        assert any("Dead-letter jobs" in title for title in titles)
        assert any("Worker heartbeats are stale" in title for title in titles)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_control_plane_server_rejects_job_when_admission_limit_reached(monkeypatch, tmp_path: Path) -> None:
    _configure_env(monkeypatch, tmp_path)
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_CONTROL_PLANE_JOB_MAX_INFLIGHT_PER_TYPE", "1")
    settings = load_settings()
    server, _app = create_control_plane_server(settings=settings, host="127.0.0.1", port=0, start_worker=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    host, port = server.server_address[:2]
    try:
        connection = http.client.HTTPConnection(host, port, timeout=5)
        headers = {
            "Content-Type": "application/json",
            **_request_headers(
                "writer-token",
                actor="release-manager-1",
                role="release-manager",
                idempotency_key="admission-limit-1",
            ),
        }
        connection.request(
            "POST",
            "/jobs/export-governance-summary",
            body=json.dumps({"title": "First queued job"}),
            headers=headers,
        )
        first_response = connection.getresponse()
        first_payload = json.loads(first_response.read().decode("utf-8"))
        connection.request(
            "POST",
            "/jobs/export-governance-summary",
            body=json.dumps({"title": "Second queued job"}),
            headers={
                "Content-Type": "application/json",
                **_request_headers(
                    "writer-token",
                    actor="release-manager-1",
                    role="release-manager",
                    idempotency_key="admission-limit-2",
                ),
            },
        )
        second_response = connection.getresponse()
        second_payload = json.loads(second_response.read().decode("utf-8"))
        connection.request(
            "GET",
            "/audit-events?event_type=admission_denied&limit=5",
            headers=_request_headers(
                "reader-token",
                actor="release-manager-1",
                role="release-manager",
            ),
        )
        audit_response = connection.getresponse()
        audit_payload = json.loads(audit_response.read().decode("utf-8"))
        connection.close()

        assert first_response.status == 202
        assert first_payload["status"] == "queued"
        assert second_response.status == 429
        assert second_payload["error"]["code"] == "job_admission_rejected"
        assert second_payload["error"]["details"]["limit_kind"] == "max_inflight"
        assert audit_response.status == 200
        assert audit_payload["rows"]
        assert audit_payload["rows"][0]["event_type"] == "admission_denied"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_control_plane_server_runs_weekly_status_export_job(monkeypatch, tmp_path: Path) -> None:
    _configure_env(monkeypatch, tmp_path)
    _seed_release_state()
    settings = load_settings()
    with redirect_stdout(io.StringIO()):
        cmd_record_operator_handoff([], 10, 10, "weekly-1")
        cmd_record_operator_handoff([], 10, 10, "weekly-2")

    server, _app = create_control_plane_server(settings=settings, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    host, port = server.server_address[:2]
    try:
        connection = http.client.HTTPConnection(host, port, timeout=5)
        connection.request(
            "POST",
            "/jobs/export-weekly-status",
            body=json.dumps(
                {
                    "title": "Async Weekly Status",
                    "output": str(tmp_path / "async-weekly-status.md"),
                    "since_days": 7,
                    "snapshot_limit": 10,
                    "release_limit": 10,
                    "incident_limit": 10,
                    "override_limit": 10,
                }
            ),
            headers={
                "Content-Type": "application/json",
                **_request_headers(
                    "writer-token",
                    actor="release-manager-1",
                    role="release-manager",
                    idempotency_key="job-weekly-status-1",
                ),
            },
        )
        create_response = connection.getresponse()
        create_payload = json.loads(create_response.read().decode("utf-8"))
        job_id = create_payload["job_id"]

        for _ in range(50):
            time.sleep(0.05)
            connection.request(
                "GET",
                f"/jobs/{job_id}",
                headers=_request_headers(
                    "reader-token",
                    actor="release-manager-1",
                    role="release-manager",
                ),
            )
            status_response = connection.getresponse()
            status_payload = json.loads(status_response.read().decode("utf-8"))
            if status_payload["status"] in {"succeeded", "failed"}:
                break
        connection.close()

        assert create_response.status == 202
        assert create_payload["status"] == "queued"
        assert status_payload["status"] == "succeeded"
        assert Path(status_payload["result_payload"]["saved_to"]).exists()
        assert Path(status_payload["result_payload"]["json_path"]).exists()
        markdown = Path(status_payload["result_payload"]["saved_to"]).read_text(encoding="utf-8")
        assert "Async Weekly Status" in markdown
        assert "## Recurring High-Risk Releases" in markdown
        assert "## Recent Handoffs" in markdown
        assert "## Artifact Lineage" in markdown
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_control_plane_server_runs_release_runbook_export_job(monkeypatch, tmp_path: Path) -> None:
    _configure_env(monkeypatch, tmp_path)
    _seed_release_state()
    settings = load_settings()
    server, _app = create_control_plane_server(settings=settings, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    host, port = server.server_address[:2]
    try:
        connection = http.client.HTTPConnection(host, port, timeout=5)
        connection.request(
            "POST",
            "/jobs/export-release-runbook",
            body=json.dumps(
                {
                    "release_name": "release-a",
                    "title": "Async Release Runbook",
                    "output": str(tmp_path / "async-runbook.md"),
                    "history_limit": 5,
                    "incident_limit": 5,
                }
            ),
            headers={
                "Content-Type": "application/json",
                **_request_headers(
                    "writer-token",
                    actor="release-manager-1",
                    role="release-manager",
                    idempotency_key="job-release-runbook-1",
                ),
            },
        )
        create_response = connection.getresponse()
        create_payload = json.loads(create_response.read().decode("utf-8"))
        job_id = create_payload["job_id"]

        for _ in range(50):
            time.sleep(0.05)
            connection.request(
                "GET",
                f"/jobs/{job_id}",
                headers=_request_headers(
                    "reader-token",
                    actor="release-manager-1",
                    role="release-manager",
                ),
            )
            status_response = connection.getresponse()
            status_payload = json.loads(status_response.read().decode("utf-8"))
            if status_payload["status"] in {"succeeded", "failed"}:
                break
        connection.close()

        assert create_response.status == 202
        assert create_payload["status"] == "queued"
        assert status_payload["status"] == "succeeded"
        assert Path(status_payload["result_payload"]["saved_to"]).exists()
        assert Path(status_payload["result_payload"]["json_path"]).exists()
        markdown = Path(status_payload["result_payload"]["saved_to"]).read_text(encoding="utf-8")
        assert "Async Release Runbook" in markdown
        assert "## Execution Plan" in markdown
        assert "## Artifact Lineage" in markdown
        assert "release-status release-a" in markdown
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_control_plane_server_runs_planner_shadow_export_job(monkeypatch, tmp_path: Path) -> None:
    _configure_env(monkeypatch, tmp_path)
    settings = load_settings()
    server, _app = create_control_plane_server(settings=settings, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    host, port = server.server_address[:2]
    try:
        connection = http.client.HTTPConnection(host, port, timeout=5)
        connection.request(
            "POST",
            "/jobs/export-planner-shadow",
            body=json.dumps(
                {
                    "title": "Async Planner Shadow",
                    "output": str(tmp_path / "async-planner-shadow.md"),
                    "report_name": "async-planner-shadow.json",
                    "suite_name": "planner_shadow",
                }
            ),
            headers={
                "Content-Type": "application/json",
                **_request_headers(
                    "writer-token",
                    actor="release-manager-1",
                    role="release-manager",
                    idempotency_key="job-planner-shadow-1",
                ),
            },
        )
        create_response = connection.getresponse()
        create_payload = json.loads(create_response.read().decode("utf-8"))
        job_id = create_payload["job_id"]

        for _ in range(50):
            time.sleep(0.05)
            connection.request(
                "GET",
                f"/jobs/{job_id}",
                headers=_request_headers(
                    "reader-token",
                    actor="release-manager-1",
                    role="release-manager",
                ),
            )
            status_response = connection.getresponse()
            status_payload = json.loads(status_response.read().decode("utf-8"))
            if status_payload["status"] in {"succeeded", "failed"}:
                break
        connection.close()

        assert create_response.status == 202
        assert status_payload["status"] == "succeeded"
        assert Path(status_payload["result_payload"]["saved_to"]).exists()
        assert Path(status_payload["result_payload"]["report_path"]).exists()
        markdown = Path(status_payload["result_payload"]["saved_to"]).read_text(encoding="utf-8")
        assert "Async Planner Shadow" in markdown
        assert "## Tasks" in markdown
        assert "## Artifact Lineage" in markdown
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_control_plane_server_runs_release_command_brief_export_job(monkeypatch, tmp_path: Path) -> None:
    _configure_env(monkeypatch, tmp_path)
    _seed_release_state()
    settings = load_settings()
    server, _app = create_control_plane_server(settings=settings, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    host, port = server.server_address[:2]
    try:
        connection = http.client.HTTPConnection(host, port, timeout=5)
        connection.request(
            "POST",
            "/jobs/export-release-command-brief",
            body=json.dumps(
                {
                    "release_name": "release-a",
                    "title": "Async Release Command Brief",
                    "output": str(tmp_path / "async-release-command-brief.md"),
                    "history_limit": 5,
                    "incident_limit": 5,
                }
            ),
            headers={
                "Content-Type": "application/json",
                **_request_headers(
                    "writer-token",
                    actor="release-manager-1",
                    role="release-manager",
                    idempotency_key="job-release-command-brief-1",
                ),
            },
        )
        create_response = connection.getresponse()
        create_payload = json.loads(create_response.read().decode("utf-8"))
        job_id = create_payload["job_id"]

        for _ in range(50):
            time.sleep(0.05)
            connection.request(
                "GET",
                f"/jobs/{job_id}",
                headers=_request_headers(
                    "reader-token",
                    actor="release-manager-1",
                    role="release-manager",
                ),
            )
            status_response = connection.getresponse()
            status_payload = json.loads(status_response.read().decode("utf-8"))
            if status_payload["status"] in {"succeeded", "failed"}:
                break
        connection.close()

        assert create_response.status == 202
        assert status_payload["status"] == "succeeded"
        assert Path(status_payload["result_payload"]["saved_to"]).exists()
        assert Path(status_payload["result_payload"]["json_path"]).exists()
        markdown = Path(status_payload["result_payload"]["saved_to"]).read_text(encoding="utf-8")
        assert "Async Release Command Brief" in markdown
        assert "## Handoffs" in markdown
        assert "## Artifact Lineage" in markdown
        assert "release-manager" in markdown
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_control_plane_server_retries_failed_jobs(monkeypatch, tmp_path: Path) -> None:
    _configure_env(monkeypatch, tmp_path)
    _seed_release_state()
    settings = load_settings()
    server, _app = create_control_plane_server(settings=settings, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    host, port = server.server_address[:2]
    try:
        connection = http.client.HTTPConnection(host, port, timeout=5)
        connection.request(
            "POST",
            "/jobs/export-operator-handoff-report",
            body=json.dumps(
                {
                    "latest": True,
                    "title": "Retried Handoff Report",
                    "output": str(tmp_path / "retried-handoff.md"),
                }
            ),
            headers={
                "Content-Type": "application/json",
                **_request_headers(
                    "writer-token",
                    actor="release-manager-1",
                    role="release-manager",
                    idempotency_key="job-handoff-report-1",
                ),
            },
        )
        create_response = connection.getresponse()
        create_payload = json.loads(create_response.read().decode("utf-8"))
        job_id = create_payload["job_id"]

        failed_payload = None
        for _ in range(50):
            time.sleep(0.05)
            connection.request(
                "GET",
                f"/jobs/{job_id}",
                headers=_request_headers(
                    "reader-token",
                    actor="release-manager-1",
                    role="release-manager",
                ),
            )
            status_response = connection.getresponse()
            status_payload = json.loads(status_response.read().decode("utf-8"))
            if status_payload["status"] == "failed":
                failed_payload = status_payload
                break

        record_operator_handoff_snapshot(
            settings,
            environments=settings.environment_names,
            release_limit=5,
            override_limit=5,
            label="retry-ready",
        )

        connection.request(
            "POST",
            f"/jobs/{job_id}/retry",
            body=json.dumps({}),
            headers={
                "Content-Type": "application/json",
                **_request_headers(
                    "writer-token",
                    actor="release-manager-1",
                    role="release-manager",
                    idempotency_key="job-handoff-report-retry-1",
                ),
            },
        )
        retry_response = connection.getresponse()
        retry_payload = json.loads(retry_response.read().decode("utf-8"))

        final_payload = None
        for _ in range(50):
            time.sleep(0.05)
            connection.request(
                "GET",
                f"/jobs/{job_id}",
                headers=_request_headers(
                    "reader-token",
                    actor="release-manager-1",
                    role="release-manager",
                ),
            )
            status_response = connection.getresponse()
            status_payload = json.loads(status_response.read().decode("utf-8"))
            if status_payload["status"] == "succeeded":
                final_payload = status_payload
                break

        request_id = create_payload["_meta"]["request_id"]
        connection.request(
            "GET",
            f"/jobs?job_type=export_operator_handoff_report&request_id={request_id}&limit=5",
            headers=_request_headers(
                "reader-token",
                actor="release-manager-1",
                role="release-manager",
            ),
        )
        list_response = connection.getresponse()
        list_payload = json.loads(list_response.read().decode("utf-8"))
        connection.close()

        assert create_response.status == 202
        assert create_payload["status"] == "queued"
        assert failed_payload is not None
        assert failed_payload["status"] == "failed"
        assert failed_payload["last_error"]["code"] == "job_execution_failed"
        assert retry_response.status == 200
        assert retry_payload["status"] == "queued"
        assert retry_payload["queue_reason"] == "manual_retry"
        assert final_payload is not None
        assert final_payload["status"] == "succeeded"
        assert final_payload["attempts"] == 2
        assert final_payload["last_error"]["code"] == "job_execution_failed"
        assert Path(final_payload["result_payload"]["saved_to"]).exists()
        assert list_response.status == 200
        assert any(row["job_id"] == job_id for row in list_payload["rows"])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_control_plane_server_supports_sqlite_backend(monkeypatch, tmp_path: Path) -> None:
    _configure_env(monkeypatch, tmp_path, control_plane_backend="sqlite")
    _seed_release_state()
    settings = load_settings()
    server, _app = create_control_plane_server(settings=settings, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    host, port = server.server_address[:2]
    try:
        connection = http.client.HTTPConnection(host, port, timeout=5)
        connection.request(
            "POST",
            "/jobs/export-governance-summary",
            body=json.dumps(
                {
                    "title": "SQLite Governance Summary",
                    "output": str(tmp_path / "sqlite-governance.md"),
                    "release_limit": 5,
                    "incident_limit": 5,
                    "override_limit": 5,
                }
            ),
            headers={
                "Content-Type": "application/json",
                **_request_headers(
                    "writer-token",
                    actor="release-manager-1",
                    role="release-manager",
                    idempotency_key="sqlite-job-governance-summary-1",
                ),
            },
        )
        create_response = connection.getresponse()
        create_payload = json.loads(create_response.read().decode("utf-8"))
        job_id = create_payload["job_id"]
        connection.request("GET", "/health")
        health_response = connection.getresponse()
        health_payload = json.loads(health_response.read().decode("utf-8"))

        final_payload = None
        for _ in range(50):
            time.sleep(0.05)
            connection.request(
                "GET",
                f"/jobs/{job_id}",
                headers=_request_headers(
                    "reader-token",
                    actor="release-manager-1",
                    role="release-manager",
                ),
            )
            status_response = connection.getresponse()
            status_payload = json.loads(status_response.read().decode("utf-8"))
            if status_payload["status"] == "succeeded":
                final_payload = status_payload
                break

        operation_id = create_payload["_control_plane"]["operation_id"]
        connection.request(
            "GET",
            f"/audit-events?event_type=mutation_committed&operation_id={operation_id}&limit=5",
            headers=_request_headers(
                "reader-token",
                actor="release-manager-1",
                role="release-manager",
            ),
        )
        audit_response = connection.getresponse()
        audit_payload = json.loads(audit_response.read().decode("utf-8"))

        connection.request(
            "GET",
            f"/idempotency-records?operation_id={operation_id}&status_code=202&limit=5",
            headers=_request_headers(
                "reader-token",
                actor="release-manager-1",
                role="release-manager",
            ),
        )
        idempotency_response = connection.getresponse()
        idempotency_payload = json.loads(idempotency_response.read().decode("utf-8"))
        connection.close()

        assert settings.control_plane_storage_backend == "sqlite"
        assert settings.control_plane_sqlite_path.exists()
        assert create_response.status == 202
        assert health_response.status == 200
        assert health_payload["storage"]["backend"] == "sqlite"
        assert health_payload["storage"]["schema_version"] == 4
        assert final_payload is not None
        assert final_payload["status"] == "succeeded"
        assert Path(final_payload["result_payload"]["saved_to"]).exists()
        assert audit_response.status == 200
        assert audit_payload["rows"]
        assert audit_payload["rows"][0]["operation_id"] == operation_id
        assert idempotency_response.status == 200
        assert idempotency_payload["rows"]
        assert idempotency_payload["rows"][0]["operation_id"] == operation_id
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_control_plane_server_reports_storage_status_and_runs_backup_job(monkeypatch, tmp_path: Path) -> None:
    _configure_env(monkeypatch, tmp_path, control_plane_backend="sqlite")
    _seed_release_state()
    settings = load_settings()
    server, _app = create_control_plane_server(settings=settings, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    host, port = server.server_address[:2]
    try:
        connection = http.client.HTTPConnection(host, port, timeout=5)
        connection.request(
            "GET",
            "/storage-status",
            headers=_request_headers(
                "reader-token",
                actor="release-manager-1",
                role="release-manager",
            ),
        )
        status_response = connection.getresponse()
        status_payload = json.loads(status_response.read().decode("utf-8"))

        connection.request(
            "POST",
            "/jobs/backup-control-plane-storage",
            body=json.dumps(
                {
                    "label": "nightly",
                    "output": str(tmp_path / "control-plane-nightly.zip"),
                }
            ),
            headers={
                "Content-Type": "application/json",
                **_request_headers(
                    "writer-token",
                    actor="ops-oncall-1",
                    role="ops-oncall",
                    idempotency_key="backup-control-plane-storage-1",
                ),
            },
        )
        create_response = connection.getresponse()
        create_payload = json.loads(create_response.read().decode("utf-8"))
        job_id = create_payload["job_id"]

        final_payload = None
        for _ in range(50):
            time.sleep(0.05)
            connection.request(
                "GET",
                f"/jobs/{job_id}",
                headers=_request_headers(
                    "reader-token",
                    actor="release-manager-1",
                    role="release-manager",
                ),
            )
            job_response = connection.getresponse()
            job_payload = json.loads(job_response.read().decode("utf-8"))
            if job_payload["status"] == "succeeded":
                final_payload = job_payload
                break
        connection.close()

        backup_path = Path(final_payload["result_payload"]["saved_to"]) if final_payload is not None else None
        assert status_response.status == 200
        assert status_payload["backend"] == "sqlite"
        assert status_payload["schema_version"] == 4
        assert status_payload["integrity_check"] == "ok"
        assert create_response.status == 202
        assert final_payload is not None
        assert final_payload["status"] == "succeeded"
        assert backup_path is not None and backup_path.exists()
        with zipfile.ZipFile(backup_path) as archive:
            names = set(archive.namelist())
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        assert "sqlite/control-plane.sqlite3" in names
        assert manifest["backend"] == "sqlite"
        assert manifest["storage_status"]["schema_version"] == 4
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_control_plane_server_reports_ledger_storage_status_and_runs_backup_job(monkeypatch, tmp_path: Path) -> None:
    _configure_env(monkeypatch, tmp_path, control_plane_backend="sqlite")
    _seed_release_state()
    settings = load_settings()
    server, _app = create_control_plane_server(settings=settings, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    host, port = server.server_address[:2]
    try:
        connection = http.client.HTTPConnection(host, port, timeout=5)
        connection.request(
            "GET",
            "/ledger-storage-status",
            headers=_request_headers(
                "reader-token",
                actor="release-manager-1",
                role="release-manager",
            ),
        )
        status_response = connection.getresponse()
        status_payload = json.loads(status_response.read().decode("utf-8"))

        connection.request(
            "POST",
            "/jobs/backup-release-and-incident-ledgers",
            body=json.dumps(
                {
                    "label": "nightly",
                    "output": str(tmp_path / "ledger-nightly.zip"),
                }
            ),
            headers={
                "Content-Type": "application/json",
                **_request_headers(
                    "writer-token",
                    actor="ops-oncall-1",
                    role="ops-oncall",
                    idempotency_key="backup-release-and-incident-ledgers-1",
                ),
            },
        )
        create_response = connection.getresponse()
        create_payload = json.loads(create_response.read().decode("utf-8"))
        job_id = create_payload["job_id"]

        final_payload = None
        for _ in range(50):
            time.sleep(0.05)
            connection.request(
                "GET",
                f"/jobs/{job_id}",
                headers=_request_headers(
                    "reader-token",
                    actor="release-manager-1",
                    role="release-manager",
                ),
            )
            job_response = connection.getresponse()
            job_payload = json.loads(job_response.read().decode("utf-8"))
            if job_payload["status"] == "succeeded":
                final_payload = job_payload
                break
        connection.close()

        backup_path = Path(final_payload["result_payload"]["saved_to"]) if final_payload is not None else None
        assert status_response.status == 200
        assert status_payload["kind"] == "release_and_incident_ledgers"
        assert status_payload["counts"]["release_records"] == 1
        assert status_payload["counts"]["incident_records"] == 1
        assert status_payload["counts"]["release_manifests"] == 1
        assert status_payload["integrity"]["valid"] is True
        assert create_response.status == 202
        assert final_payload is not None
        assert final_payload["status"] == "succeeded"
        assert backup_path is not None and backup_path.exists()
        with zipfile.ZipFile(backup_path) as archive:
            names = set(archive.namelist())
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        assert "releases/release-ledger.json" in names
        assert "incidents/incident-ledger.json" in names
        assert "releases/manifests/release-a.json" in names
        assert manifest["kind"] == "release_and_incident_ledgers"
        assert manifest["storage_status"]["counts"]["release_records"] == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_sqlite_control_plane_repositories_migrate_legacy_schema(monkeypatch, tmp_path: Path) -> None:
    _configure_env(monkeypatch, tmp_path, control_plane_backend="sqlite")
    settings = load_settings()
    sqlite_path = settings.control_plane_sqlite_path
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(sqlite_path)
    try:
        connection.execute(
            """
            CREATE TABLE audit_events (
                audit_event_id TEXT PRIMARY KEY,
                occurred_at TEXT NOT NULL,
                request_id TEXT,
                operation_id TEXT,
                event_type TEXT,
                error_code TEXT,
                actor TEXT,
                role TEXT,
                method TEXT,
                path TEXT,
                status_code INTEGER,
                replayed INTEGER NOT NULL DEFAULT 0,
                conflict INTEGER NOT NULL DEFAULT 0,
                payload TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO audit_events (
                audit_event_id,
                occurred_at,
                request_id,
                operation_id,
                event_type,
                error_code,
                actor,
                role,
                method,
                path,
                status_code,
                replayed,
                conflict,
                payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "audit-legacy-1",
                "2026-04-10T00:00:00Z",
                "req-legacy-1",
                None,
                "authorization_denied",
                "missing_identity",
                None,
                None,
                "GET",
                "/governance-summary",
                400,
                0,
                0,
                json.dumps(
                    {
                        "audit_event_id": "audit-legacy-1",
                        "event_type": "authorization_denied",
                        "error_code": "missing_identity",
                        "route_policy_key": "read_governance",
                        "path": "/governance-summary",
                        "method": "GET",
                        "status_code": 400,
                    },
                    sort_keys=True,
                ),
            ),
        )
        connection.commit()
    finally:
        connection.close()

    assert get_sqlite_schema_version(sqlite_path) == 1

    repositories = create_local_control_plane_repositories(settings)
    migrated_events = repositories.audit.list_events(
        route_policy_key="read_governance",
        event_type="authorization_denied",
        error_code="missing_identity",
        limit=5,
    )

    assert get_sqlite_schema_version(sqlite_path) == 4
    assert migrated_events
    assert migrated_events[0].payload["audit_event_id"] == "audit-legacy-1"
    assert migrated_events[0].payload["route_policy_key"] == "read_governance"


def test_control_plane_storage_cli_status_and_backup(monkeypatch, tmp_path: Path) -> None:
    _configure_env(monkeypatch, tmp_path, control_plane_backend="sqlite")
    _seed_release_state()

    status_stdout = io.StringIO()
    with redirect_stdout(status_stdout):
        assert cmd_control_plane_storage_status() == 0
    status_payload = json.loads(status_stdout.getvalue())

    backup_stdout = io.StringIO()
    backup_path = tmp_path / "cli-control-plane-backup.zip"
    with redirect_stdout(backup_stdout):
        assert cmd_backup_control_plane_storage(str(backup_path), "cli") == 0
    backup_payload = json.loads(backup_stdout.getvalue())

    assert status_payload["backend"] == "sqlite"
    assert status_payload["schema_version"] == 4
    assert backup_payload["backend"] == "sqlite"
    assert Path(backup_payload["saved_to"]).exists()
    with zipfile.ZipFile(backup_path) as archive:
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
    assert manifest["backend"] == "sqlite"


def test_ledger_storage_cli_status_and_backup(monkeypatch, tmp_path: Path) -> None:
    _configure_env(monkeypatch, tmp_path, control_plane_backend="sqlite")
    _seed_release_state()

    status_stdout = io.StringIO()
    with redirect_stdout(status_stdout):
        assert cmd_ledger_storage_status() == 0
    status_payload = json.loads(status_stdout.getvalue())

    backup_stdout = io.StringIO()
    backup_path = tmp_path / "cli-ledger-backup.zip"
    with redirect_stdout(backup_stdout):
        assert cmd_backup_release_and_incident_ledgers(str(backup_path), "cli") == 0
    backup_payload = json.loads(backup_stdout.getvalue())

    assert status_payload["kind"] == "release_and_incident_ledgers"
    assert status_payload["counts"]["release_records"] == 1
    assert status_payload["counts"]["incident_records"] == 1
    assert status_payload["counts"]["release_manifests"] == 1
    assert status_payload["integrity"]["valid"] is True
    assert Path(backup_payload["saved_to"]).exists()
    with zipfile.ZipFile(backup_path) as archive:
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
    assert manifest["kind"] == "release_and_incident_ledgers"


def test_control_plane_backup_cli_verify_and_restore(monkeypatch, tmp_path: Path) -> None:
    _configure_env(monkeypatch, tmp_path, control_plane_backend="sqlite")
    _seed_release_state()

    backup_stdout = io.StringIO()
    backup_path = tmp_path / "verify-restore-control-plane.zip"
    with redirect_stdout(backup_stdout):
        assert cmd_backup_control_plane_storage(str(backup_path), "verify-restore") == 0
    backup_payload = json.loads(backup_stdout.getvalue())

    verify_stdout = io.StringIO()
    with redirect_stdout(verify_stdout):
        assert cmd_verify_control_plane_backup(str(backup_path), backup_payload["sha256"]) == 0
    verify_payload = json.loads(verify_stdout.getvalue())

    restore_stdout = io.StringIO()
    restore_dir = tmp_path / "restore-drill"
    with redirect_stdout(restore_stdout):
        assert cmd_restore_control_plane_backup(str(backup_path), str(restore_dir), "drill") == 0
    restore_payload = json.loads(restore_stdout.getvalue())

    assert verify_payload["validated"] is True
    assert verify_payload["archive_sha256"] == backup_payload["sha256"]
    assert verify_payload["backend"] == "sqlite"
    assert restore_payload["backend"] == "sqlite"
    assert restore_payload["validation"]["validated"] is True
    assert (restore_dir / "manifest.json").exists()
    assert any(name.endswith(".sqlite3") for name in restore_payload["restored_files"])


def test_ledger_backup_cli_verify_and_restore(monkeypatch, tmp_path: Path) -> None:
    _configure_env(monkeypatch, tmp_path, control_plane_backend="sqlite")
    _seed_release_state()

    backup_stdout = io.StringIO()
    backup_path = tmp_path / "verify-restore-ledgers.zip"
    with redirect_stdout(backup_stdout):
        assert cmd_backup_release_and_incident_ledgers(str(backup_path), "verify-restore") == 0
    backup_payload = json.loads(backup_stdout.getvalue())

    verify_stdout = io.StringIO()
    with redirect_stdout(verify_stdout):
        assert cmd_verify_release_and_incident_ledger_backup(str(backup_path), backup_payload["sha256"]) == 0
    verify_payload = json.loads(verify_stdout.getvalue())

    restore_stdout = io.StringIO()
    restore_dir = tmp_path / "ledger-restore-drill"
    with redirect_stdout(restore_stdout):
        assert cmd_restore_release_and_incident_ledger_backup(str(backup_path), str(restore_dir), "drill") == 0
    restore_payload = json.loads(restore_stdout.getvalue())

    assert verify_payload["validated"] is True
    assert verify_payload["archive_sha256"] == backup_payload["sha256"]
    assert verify_payload["counts"]["release_records"] == 1
    assert verify_payload["counts"]["incident_records"] == 1
    assert verify_payload["counts"]["release_manifests"] == 1
    assert restore_payload["validation"]["validated"] is True
    assert (restore_dir / "manifest.json").exists()
    assert (restore_dir / "releases" / "release-ledger.json").exists()
    assert (restore_dir / "incidents" / "incident-ledger.json").exists()


def test_control_plane_server_runs_backup_verify_and_restore_jobs(monkeypatch, tmp_path: Path) -> None:
    _configure_env(monkeypatch, tmp_path, control_plane_backend="sqlite")
    _seed_release_state()
    settings = load_settings()
    server, _app = create_control_plane_server(settings=settings, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    host, port = server.server_address[:2]
    try:
        connection = http.client.HTTPConnection(host, port, timeout=5)
        backup_archive = tmp_path / "ops-backup.zip"
        connection.request(
            "POST",
            "/jobs/backup-control-plane-storage",
            body=json.dumps({"output": str(backup_archive), "label": "ops"}),
            headers={
                "Content-Type": "application/json",
                **_request_headers(
                    "writer-token",
                    actor="ops-oncall-1",
                    role="ops-oncall",
                    idempotency_key="backup-control-plane-storage-verify-restore-1",
                ),
            },
        )
        backup_response = connection.getresponse()
        backup_payload = json.loads(backup_response.read().decode("utf-8"))
        backup_job_id = backup_payload["job_id"]

        backup_job = None
        for _ in range(50):
            time.sleep(0.05)
            connection.request(
                "GET",
                f"/jobs/{backup_job_id}",
                headers=_request_headers(
                    "reader-token",
                    actor="release-manager-1",
                    role="release-manager",
                ),
            )
            job_response = connection.getresponse()
            job_payload = json.loads(job_response.read().decode("utf-8"))
            if job_payload["status"] == "succeeded":
                backup_job = job_payload
                break

        backup_result_path = backup_job["result_payload"]["saved_to"] if backup_job is not None else str(backup_archive)
        backup_sha = backup_job["result_payload"]["sha256"] if backup_job is not None else ""

        connection.request(
            "POST",
            "/jobs/verify-control-plane-backup",
            body=json.dumps({"backup_path": backup_result_path, "expected_sha256": backup_sha}),
            headers={
                "Content-Type": "application/json",
                **_request_headers(
                    "writer-token",
                    actor="ops-oncall-1",
                    role="ops-oncall",
                    idempotency_key="verify-control-plane-backup-1",
                ),
            },
        )
        verify_response = connection.getresponse()
        verify_payload = json.loads(verify_response.read().decode("utf-8"))
        verify_job_id = verify_payload["job_id"]

        verify_job = None
        for _ in range(50):
            time.sleep(0.05)
            connection.request(
                "GET",
                f"/jobs/{verify_job_id}",
                headers=_request_headers(
                    "reader-token",
                    actor="release-manager-1",
                    role="release-manager",
                ),
            )
            job_response = connection.getresponse()
            job_payload = json.loads(job_response.read().decode("utf-8"))
            if job_payload["status"] == "succeeded":
                verify_job = job_payload
                break

        restore_dir = tmp_path / "restore-job"
        connection.request(
            "POST",
            "/jobs/restore-control-plane-backup",
            body=json.dumps(
                {
                    "backup_path": backup_result_path,
                    "output_dir": str(restore_dir),
                    "label": "restore-job",
                }
            ),
            headers={
                "Content-Type": "application/json",
                **_request_headers(
                    "writer-token",
                    actor="ops-oncall-1",
                    role="ops-oncall",
                    idempotency_key="restore-control-plane-backup-1",
                ),
            },
        )
        restore_response = connection.getresponse()
        restore_payload = json.loads(restore_response.read().decode("utf-8"))
        restore_job_id = restore_payload["job_id"]

        restore_job = None
        for _ in range(50):
            time.sleep(0.05)
            connection.request(
                "GET",
                f"/jobs/{restore_job_id}",
                headers=_request_headers(
                    "reader-token",
                    actor="release-manager-1",
                    role="release-manager",
                ),
            )
            job_response = connection.getresponse()
            job_payload = json.loads(job_response.read().decode("utf-8"))
            if job_payload["status"] == "succeeded":
                restore_job = job_payload
                break
        connection.close()

        assert backup_response.status == 202
        assert backup_job is not None
        assert Path(backup_result_path).exists()
        assert verify_response.status == 202
        assert verify_job is not None
        assert verify_job["result_payload"]["validated"] is True
        assert verify_job["result_payload"]["archive_sha256"] == backup_sha
        assert restore_response.status == 202
        assert restore_job is not None
        assert restore_job["result_payload"]["validation"]["validated"] is True
        assert Path(restore_job["result_payload"]["restored_to"]).exists()
        assert (restore_dir / "manifest.json").exists()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_control_plane_server_runs_ledger_backup_verify_and_restore_jobs(monkeypatch, tmp_path: Path) -> None:
    _configure_env(monkeypatch, tmp_path, control_plane_backend="sqlite")
    _seed_release_state()
    settings = load_settings()
    server, _app = create_control_plane_server(settings=settings, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    host, port = server.server_address[:2]
    try:
        connection = http.client.HTTPConnection(host, port, timeout=5)
        backup_archive = tmp_path / "ops-ledger-backup.zip"
        connection.request(
            "POST",
            "/jobs/backup-release-and-incident-ledgers",
            body=json.dumps({"output": str(backup_archive), "label": "ops"}),
            headers={
                "Content-Type": "application/json",
                **_request_headers(
                    "writer-token",
                    actor="ops-oncall-1",
                    role="ops-oncall",
                    idempotency_key="backup-release-and-incident-ledgers-verify-restore-1",
                ),
            },
        )
        backup_response = connection.getresponse()
        backup_payload = json.loads(backup_response.read().decode("utf-8"))
        backup_job_id = backup_payload["job_id"]

        backup_job = None
        for _ in range(50):
            time.sleep(0.05)
            connection.request(
                "GET",
                f"/jobs/{backup_job_id}",
                headers=_request_headers(
                    "reader-token",
                    actor="release-manager-1",
                    role="release-manager",
                ),
            )
            job_response = connection.getresponse()
            job_payload = json.loads(job_response.read().decode("utf-8"))
            if job_payload["status"] == "succeeded":
                backup_job = job_payload
                break

        backup_result_path = backup_job["result_payload"]["saved_to"] if backup_job is not None else str(backup_archive)
        backup_sha = backup_job["result_payload"]["sha256"] if backup_job is not None else ""

        connection.request(
            "POST",
            "/jobs/verify-release-and-incident-ledger-backup",
            body=json.dumps({"backup_path": backup_result_path, "expected_sha256": backup_sha}),
            headers={
                "Content-Type": "application/json",
                **_request_headers(
                    "writer-token",
                    actor="ops-oncall-1",
                    role="ops-oncall",
                    idempotency_key="verify-release-and-incident-ledger-backup-1",
                ),
            },
        )
        verify_response = connection.getresponse()
        verify_payload = json.loads(verify_response.read().decode("utf-8"))
        verify_job_id = verify_payload["job_id"]

        verify_job = None
        for _ in range(50):
            time.sleep(0.05)
            connection.request(
                "GET",
                f"/jobs/{verify_job_id}",
                headers=_request_headers(
                    "reader-token",
                    actor="release-manager-1",
                    role="release-manager",
                ),
            )
            job_response = connection.getresponse()
            job_payload = json.loads(job_response.read().decode("utf-8"))
            if job_payload["status"] == "succeeded":
                verify_job = job_payload
                break

        restore_dir = tmp_path / "ledger-restore-job"
        connection.request(
            "POST",
            "/jobs/restore-release-and-incident-ledger-backup",
            body=json.dumps(
                {
                    "backup_path": backup_result_path,
                    "output_dir": str(restore_dir),
                    "label": "restore-job",
                }
            ),
            headers={
                "Content-Type": "application/json",
                **_request_headers(
                    "writer-token",
                    actor="ops-oncall-1",
                    role="ops-oncall",
                    idempotency_key="restore-release-and-incident-ledger-backup-1",
                ),
            },
        )
        restore_response = connection.getresponse()
        restore_payload = json.loads(restore_response.read().decode("utf-8"))
        restore_job_id = restore_payload["job_id"]

        restore_job = None
        for _ in range(50):
            time.sleep(0.05)
            connection.request(
                "GET",
                f"/jobs/{restore_job_id}",
                headers=_request_headers(
                    "reader-token",
                    actor="release-manager-1",
                    role="release-manager",
                ),
            )
            job_response = connection.getresponse()
            job_payload = json.loads(job_response.read().decode("utf-8"))
            if job_payload["status"] == "succeeded":
                restore_job = job_payload
                break
        connection.close()

        assert backup_response.status == 202
        assert backup_job is not None
        assert Path(backup_result_path).exists()
        assert verify_response.status == 202
        assert verify_job is not None
        assert verify_job["result_payload"]["validated"] is True
        assert verify_job["result_payload"]["archive_sha256"] == backup_sha
        assert verify_job["result_payload"]["counts"]["release_records"] == 1
        assert restore_response.status == 202
        assert restore_job is not None
        assert restore_job["result_payload"]["validation"]["validated"] is True
        assert Path(restore_job["result_payload"]["restored_to"]).exists()
        assert (restore_dir / "manifest.json").exists()
        assert (restore_dir / "releases" / "release-ledger.json").exists()
        assert (restore_dir / "incidents" / "incident-ledger.json").exists()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
