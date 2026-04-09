from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path

from agent_architect_lab.cli import (
    cmd_approve_release,
    cmd_check_deploy_readiness,
    cmd_deploy_release,
    cmd_environment_status,
    cmd_explain_patterns,
    cmd_list_skills,
    cmd_list_releases,
    cmd_promote_release,
    cmd_register_report,
    cmd_rollback_release,
    cmd_release_status,
    cmd_run_evals,
    cmd_run_release_shadow,
)


def test_cmd_explain_patterns_outputs_serializable_patterns() -> None:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        exit_code = cmd_explain_patterns("")
    payload = json.loads(buffer.getvalue())
    assert exit_code == 0
    assert "single_agent" in payload
    assert payload["single_agent"]["name"] == "single_agent"


def test_cmd_list_skills_matches_memory_retrieval_goal() -> None:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        exit_code = cmd_list_skills("agent skills and memory retrieval")
    payload = json.loads(buffer.getvalue())
    ids = {item["id"] for item in payload}
    assert exit_code == 0
    assert "skill_router" in ids
    assert "memory_retrieval_designer" in ids


def test_cmd_run_evals_registers_report(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_ARTIFACTS", str(tmp_path / "artifacts"))
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        exit_code = cmd_run_evals("baseline-safety.json", "safety", "baseline", "approved")
    output = buffer.getvalue()
    registry_path = tmp_path / "artifacts" / "reports" / "report-registry.json"
    payload = json.loads(registry_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert "report_registered=report-" in output
    assert payload["records"][0]["report_kind"] == "baseline"
    assert payload["records"][0]["label"] == "approved"


def test_cmd_register_report_registers_existing_report(monkeypatch, tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts"
    reports_dir = artifacts_dir / "reports"
    reports_dir.mkdir(parents=True)
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_ARTIFACTS", str(artifacts_dir))

    report_path = reports_dir / "manual.json"
    report_path.write_text(
        json.dumps(
            {
                "suite_name": "safety",
                "success_rate": 1.0,
                "average_score": 1.0,
                "average_steps": 1.0,
                "status_counts": {"failed": 1},
                "failures_by_type": {},
                "results_by_track": {},
                "results": [],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        exit_code = cmd_register_report(str(report_path), "baseline", "manual-approved")
    payload = json.loads(buffer.getvalue())

    assert exit_code == 0
    assert payload["report_kind"] == "baseline"
    assert payload["label"] == "manual-approved"


def test_cmd_run_release_shadow_can_record_release_and_transition(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_ARTIFACTS", str(tmp_path / "artifacts"))

    with redirect_stdout(io.StringIO()):
        cmd_run_evals("safety-baseline.json", "safety", "baseline", "approved-safety")

    shadow_buffer = io.StringIO()
    with redirect_stdout(shadow_buffer):
        exit_code = cmd_run_release_shadow(
            ["safety"],
            "release-candidate",
            "",
            True,
            "",
            "release-qa-001",
        )
    shadow_payload = json.loads(shadow_buffer.getvalue())

    approve_buffer = io.StringIO()
    with redirect_stdout(approve_buffer):
        approve_exit = cmd_approve_release("release-qa-001", "qa-owner", "", "looks good")
    approve_payload = json.loads(approve_buffer.getvalue())

    promote_buffer = io.StringIO()
    with redirect_stdout(promote_buffer):
        promote_exit = cmd_promote_release("release-qa-001", "release-manager", "deploy now")
    promote_payload = json.loads(promote_buffer.getvalue())

    status_buffer = io.StringIO()
    with redirect_stdout(status_buffer):
        status_exit = cmd_release_status("release-qa-001")
    status_payload = json.loads(status_buffer.getvalue())

    assert exit_code == 0
    assert shadow_payload["release_record"]["state"] == "pending_approval"
    assert shadow_payload["baseline_sources"]["safety"] == "registry"
    assert approve_exit == 0
    assert approve_payload["state"] == "approved"
    assert promote_exit == 0
    assert promote_payload["state"] == "promoted"
    assert status_exit == 0
    assert status_payload["state"] == "promoted"


def test_cmd_deploy_and_rollback_release(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_ARTIFACTS", str(tmp_path / "artifacts"))

    with redirect_stdout(io.StringIO()):
        cmd_run_evals("safety-baseline.json", "safety", "baseline", "approved-safety")
        cmd_run_release_shadow(["safety"], "release-a", "", True, "", "release-a")
        cmd_approve_release("release-a", "qa-owner", "", "approved")
        cmd_deploy_release("release-a", "staging", "release-manager", "deploy A")

        cmd_run_release_shadow(["safety"], "release-b", "", True, "", "release-b")
        cmd_approve_release("release-b", "qa-owner", "", "approved")

    deploy_buffer = io.StringIO()
    with redirect_stdout(deploy_buffer):
        deploy_exit = cmd_deploy_release("release-b", "staging", "release-manager", "deploy B")
    deploy_payload = json.loads(deploy_buffer.getvalue())

    rollback_buffer = io.StringIO()
    with redirect_stdout(rollback_buffer):
        rollback_exit = cmd_rollback_release("release-b", "staging", "release-manager", "rollback B")
    rollback_payload = json.loads(rollback_buffer.getvalue())

    status_buffer = io.StringIO()
    with redirect_stdout(status_buffer):
        status_exit = cmd_release_status("release-a")
    status_payload = json.loads(status_buffer.getvalue())

    assert deploy_exit == 0
    assert deploy_payload["deployments"][-1]["environment"] == "staging"
    assert deploy_payload["deployments"][-1]["status"] == "active"
    assert rollback_exit == 0
    assert rollback_payload["deployments"][-1]["status"] == "rolled_back"
    assert status_exit == 0
    assert status_payload["deployments"][-1]["status"] == "active"


def test_cmd_list_releases_and_environment_status(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_ARTIFACTS", str(tmp_path / "artifacts"))

    with redirect_stdout(io.StringIO()):
        cmd_run_evals("safety-baseline.json", "safety", "baseline", "approved-safety")
        cmd_run_release_shadow(["safety"], "release-a", "", True, "", "release-a")
        cmd_approve_release("release-a", "qa-owner", "", "approved")
        cmd_deploy_release("release-a", "staging", "release-manager", "deploy A")
        cmd_run_release_shadow(["safety"], "release-b", "", True, "", "release-b")
        cmd_approve_release("release-b", "qa-owner", "", "approved")
        cmd_deploy_release("release-b", "staging", "release-manager", "deploy B")

    releases_buffer = io.StringIO()
    with redirect_stdout(releases_buffer):
        releases_exit = cmd_list_releases()
    releases_payload = json.loads(releases_buffer.getvalue())

    env_buffer = io.StringIO()
    with redirect_stdout(env_buffer):
        env_exit = cmd_environment_status("staging")
    env_payload = json.loads(env_buffer.getvalue())

    assert releases_exit == 0
    assert releases_payload[0]["release_name"] == "release-b"
    assert env_exit == 0
    assert env_payload["active_release"] == "release-b"


def test_cmd_check_deploy_readiness_reports_blockers(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_ARTIFACTS", str(tmp_path / "artifacts"))
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_PRODUCTION_SOAK_MINUTES", "30")
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_PRODUCTION_REQUIRED_APPROVER_ROLES", "qa-owner,release-manager")

    with redirect_stdout(io.StringIO()):
        cmd_run_evals("safety-baseline.json", "safety", "baseline", "approved-safety")
        cmd_run_release_shadow(["safety"], "release-a", "", True, "", "release-a")
        cmd_approve_release("release-a", "qa-owner", "", "approved")
        cmd_deploy_release("release-a", "staging", "release-manager", "deploy A")

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        exit_code = cmd_check_deploy_readiness("release-a", "production")
    payload = json.loads(buffer.getvalue())

    assert exit_code == 1
    assert "staging_soak_incomplete" in payload["blockers"]


def test_cmd_check_deploy_readiness_reports_freeze_window(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_ARTIFACTS", str(tmp_path / "artifacts"))
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_ENVIRONMENT_FREEZE_WINDOWS", '{"staging":["00:00-23:59"]}')
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_PRODUCTION_REQUIRED_APPROVER_ROLES", "")

    with redirect_stdout(io.StringIO()):
        cmd_run_evals("safety-baseline.json", "safety", "baseline", "approved-safety")
        cmd_run_release_shadow(["safety"], "release-a", "", True, "", "release-a")
        cmd_approve_release("release-a", "qa-owner", "", "approved")

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        exit_code = cmd_check_deploy_readiness("release-a", "staging")
    payload = json.loads(buffer.getvalue())

    assert exit_code == 1
    assert "environment_frozen" in payload["blockers"]
    assert payload["active_freeze_window"] == "00:00-23:59"
