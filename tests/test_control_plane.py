from __future__ import annotations

import http.client
import io
import json
import threading
from contextlib import redirect_stdout
from pathlib import Path

from agent_architect_lab.cli import (
    cmd_approve_release,
    cmd_open_incident,
    cmd_run_evals,
    cmd_run_release_shadow,
)
from agent_architect_lab.config import load_settings
from agent_architect_lab.control_plane.server import ControlPlaneApp, ControlPlaneAuth, create_control_plane_server


def _configure_env(monkeypatch, tmp_path: Path, *, mutation_token: str | None = "writer-token") -> None:
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_ARTIFACTS", str(tmp_path / "artifacts"))
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_PRODUCTION_SOAK_MINUTES", "0")
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_PRODUCTION_REQUIRED_APPROVER_ROLES", "qa-owner,release-manager")
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_INCIDENT_STALE_MINUTES", "0")
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_CONTROL_PLANE_READ_TOKEN", "reader-token")
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


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _mutation_headers(token: str, idempotency_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Idempotency-Key": idempotency_key,
    }


def test_control_plane_app_requires_read_token_for_governance_routes(monkeypatch, tmp_path: Path) -> None:
    _configure_env(monkeypatch, tmp_path)
    settings = load_settings()
    app = ControlPlaneApp(
        settings=settings,
        auth=ControlPlaneAuth(
            read_token=settings.control_plane_read_token,
            mutation_token=settings.control_plane_mutation_token,
        ),
    )

    unauthorized = app.handle_request("GET", "/governance-summary", {}, b"")
    authorized = app.handle_request("GET", "/health", {}, b"")

    assert unauthorized.status_code == 401
    assert unauthorized.payload["error"]["code"] == "unauthorized"
    assert authorized.status_code == 200
    assert authorized.payload["status"] == "ok"


def test_control_plane_app_disables_mutation_routes_without_mutation_token(monkeypatch, tmp_path: Path) -> None:
    _configure_env(monkeypatch, tmp_path, mutation_token=None)
    settings = load_settings()
    app = ControlPlaneApp(
        settings=settings,
        auth=ControlPlaneAuth(
            read_token=settings.control_plane_read_token,
            mutation_token=settings.control_plane_mutation_token,
        ),
    )

    response = app.handle_request(
        "POST",
        "/incidents/open",
        _mutation_headers("reader-token", "open-incident-1"),
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


def test_control_plane_app_requires_idempotency_key_for_mutations(monkeypatch, tmp_path: Path) -> None:
    _configure_env(monkeypatch, tmp_path)
    settings = load_settings()
    app = ControlPlaneApp(
        settings=settings,
        auth=ControlPlaneAuth(
            read_token=settings.control_plane_read_token,
            mutation_token=settings.control_plane_mutation_token,
        ),
    )

    response = app.handle_request(
        "POST",
        "/incidents/open",
        _auth_header("writer-token"),
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
    app = ControlPlaneApp(
        settings=settings,
        auth=ControlPlaneAuth(
            read_token=settings.control_plane_read_token,
            mutation_token=settings.control_plane_mutation_token,
        ),
    )

    opened = app.handle_request(
        "POST",
        "/incidents/open",
        _mutation_headers("writer-token", "open-incident-1"),
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
        _mutation_headers("writer-token", "open-incident-1"),
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
        _mutation_headers("writer-token", "transition-incident-1"),
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


def test_control_plane_app_rejects_conflicting_idempotency_reuse(monkeypatch, tmp_path: Path) -> None:
    _configure_env(monkeypatch, tmp_path)
    settings = load_settings()
    app = ControlPlaneApp(
        settings=settings,
        auth=ControlPlaneAuth(
            read_token=settings.control_plane_read_token,
            mutation_token=settings.control_plane_mutation_token,
        ),
    )

    first = app.handle_request(
        "POST",
        "/incidents/open",
        _mutation_headers("writer-token", "open-incident-1"),
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
        _mutation_headers("writer-token", "open-incident-1"),
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

        connection.request("GET", "/release-risk-board?limit=5", headers=_auth_header("reader-token"))
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
                **_mutation_headers("writer-token", "smoke-open-incident-1"),
            },
        )
        incident_response = connection.getresponse()
        incident_payload = json.loads(incident_response.read().decode("utf-8"))
        connection.close()

        assert health_response.status == 200
        assert health_payload["status"] == "ok"
        assert risk_response.status == 200
        assert risk_payload["rows"]
        assert risk_payload["rows"][0]["release_name"] == "release-a"
        assert incident_response.status == 201
        assert incident_payload["status"] == "open"
        assert incident_payload["_control_plane"]["replayed"] is False
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
