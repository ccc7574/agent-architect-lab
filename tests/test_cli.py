from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path

from agent_architect_lab.cli import (
    cmd_approve_release,
    cmd_check_deploy_readiness,
    cmd_environment_history,
    cmd_deploy_policy,
    cmd_deploy_release,
    cmd_environment_status,
    cmd_explain_patterns,
    cmd_grant_release_override,
    cmd_list_active_overrides,
    cmd_list_skills,
    cmd_list_releases,
    cmd_promote_release,
    cmd_register_report,
    cmd_release_readiness_digest,
    cmd_release_risk_board,
    cmd_rollout_matrix,
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


def test_cmd_deploy_policy_reports_environment_policy(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_ARTIFACTS", str(tmp_path / "artifacts"))
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_ENVIRONMENT_FREEZE_WINDOWS", '{"production":["00:00-23:59"]}')
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_PRODUCTION_SOAK_MINUTES", "45")
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_PRODUCTION_REQUIRED_APPROVER_ROLES", "qa-owner,release-manager")

    with redirect_stdout(io.StringIO()):
        cmd_run_evals("safety-baseline.json", "safety", "baseline", "approved-safety")
        cmd_run_release_shadow(["safety"], "release-a", "", True, "", "release-a")
        cmd_approve_release("release-a", "qa-owner", "", "qa approved")
        cmd_approve_release("release-a", "release-manager", "release-manager", "ops approved")
        cmd_deploy_release("release-a", "staging", "release-manager", "deploy staging")

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        exit_code = cmd_deploy_policy("production")
    payload = json.loads(buffer.getvalue())

    assert exit_code == 0
    assert payload["environment"] == "production"
    assert payload["required_predecessor_environment"] == "staging"
    assert payload["required_approver_roles"] == ["qa-owner", "release-manager"]
    assert payload["soak_minutes_required"] == 45
    assert payload["freeze_windows"] == ["00:00-23:59"]
    assert payload["active_freeze_window"] == "00:00-23:59"


def test_cmd_environment_history_reports_recent_lineage(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_ARTIFACTS", str(tmp_path / "artifacts"))

    with redirect_stdout(io.StringIO()):
        cmd_run_evals("safety-baseline.json", "safety", "baseline", "approved-safety")
        cmd_run_release_shadow(["safety"], "release-a", "", True, "", "release-a")
        cmd_approve_release("release-a", "qa-owner", "", "approved")
        cmd_deploy_release("release-a", "staging", "release-manager", "deploy A")
        cmd_run_release_shadow(["safety"], "release-b", "", True, "", "release-b")
        cmd_approve_release("release-b", "qa-owner", "", "approved")
        cmd_deploy_release("release-b", "staging", "release-manager", "deploy B")
        cmd_rollback_release("release-b", "staging", "release-manager", "rollback B")

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        exit_code = cmd_environment_history("staging", 10)
    payload = json.loads(buffer.getvalue())

    assert exit_code == 0
    assert payload[0]["release_name"] == "release-a"
    assert payload[0]["status"] == "active"
    assert payload[1]["release_name"] == "release-b"
    assert payload[1]["status"] == "rolled_back"


def test_cmd_rollout_matrix_reports_release_readiness(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_ARTIFACTS", str(tmp_path / "artifacts"))
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_PRODUCTION_REQUIRED_APPROVER_ROLES", "qa-owner,release-manager")
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_ENVIRONMENT_FREEZE_WINDOWS", '{"production":["00:00-23:59"]}')

    with redirect_stdout(io.StringIO()):
        cmd_run_evals("safety-baseline.json", "safety", "baseline", "approved-safety")
        cmd_run_release_shadow(["safety"], "release-a", "", True, "", "release-a")
        cmd_approve_release("release-a", "qa-owner", "", "approved")
        cmd_deploy_release("release-a", "staging", "release-manager", "deploy staging")

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        exit_code = cmd_rollout_matrix("release-a", [])
    payload = json.loads(buffer.getvalue())

    assert exit_code == 1
    assert payload["release_name"] == "release-a"
    assert payload["all_ready"] is False
    assert payload["rows"][0]["environment"] == "staging"
    assert payload["rows"][0]["readiness"]["blockers"] == ["already_active_in_environment"]
    assert payload["rows"][0]["recommended_action"] == "no_action_already_active"
    assert "environment_frozen" in payload["rows"][1]["readiness"]["blockers"]
    assert payload["rows"][1]["recommended_action"] == "collect_required_approvals"


def test_cmd_rollout_matrix_respects_explicit_environment_override(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_ARTIFACTS", str(tmp_path / "artifacts"))
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_ENVIRONMENTS", "staging,production,canary")

    with redirect_stdout(io.StringIO()):
        cmd_run_evals("safety-baseline.json", "safety", "baseline", "approved-safety")

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        exit_code = cmd_rollout_matrix("", ["canary"])
    payload = json.loads(buffer.getvalue())

    assert exit_code == 0
    assert payload["release_name"] is None
    assert payload["environments"] == ["canary"]
    assert payload["rows"][0]["environment"] == "canary"
    assert payload["rows"][0]["recommended_action"] == "observe_environment"


def test_cmd_rollout_matrix_includes_policy_defined_environments(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_ARTIFACTS", str(tmp_path / "artifacts"))
    monkeypatch.delenv("AGENT_ARCHITECT_LAB_ENVIRONMENTS", raising=False)
    monkeypatch.setenv(
        "AGENT_ARCHITECT_LAB_ENVIRONMENT_POLICIES",
        '{"canary":{"required_predecessor_environment":"staging","required_approver_roles":["qa-owner"],"soak_minutes_required":5}}',
    )

    with redirect_stdout(io.StringIO()):
        cmd_run_evals("safety-baseline.json", "safety", "baseline", "approved-safety")

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        exit_code = cmd_rollout_matrix("", [])
    payload = json.loads(buffer.getvalue())

    assert exit_code == 0
    assert payload["environments"] == ["staging", "production", "canary"]
    assert payload["rows"][2]["environment"] == "canary"
    assert payload["rows"][2]["policy"]["required_predecessor_environment"] == "staging"
    assert payload["rows"][2]["policy"]["required_approver_roles"] == ["qa-owner"]


def test_cmd_grant_release_override_unblocks_readiness(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_ARTIFACTS", str(tmp_path / "artifacts"))
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_ENVIRONMENT_FREEZE_WINDOWS", '{"staging":["00:00-23:59"]}')

    with redirect_stdout(io.StringIO()):
        cmd_run_evals("safety-baseline.json", "safety", "baseline", "approved-safety")
        cmd_run_release_shadow(["safety"], "release-a", "", True, "", "release-a")
        cmd_approve_release("release-a", "qa-owner", "", "approved")

    blocked_buffer = io.StringIO()
    with redirect_stdout(blocked_buffer):
        blocked_exit = cmd_check_deploy_readiness("release-a", "staging")
    blocked_payload = json.loads(blocked_buffer.getvalue())

    override_buffer = io.StringIO()
    with redirect_stdout(override_buffer):
        override_exit = cmd_grant_release_override(
            "release-a",
            "staging",
            "environment_frozen",
            "incident-commander",
            "hotfix waiver",
            "",
        )
    override_payload = json.loads(override_buffer.getvalue())

    waived_buffer = io.StringIO()
    with redirect_stdout(waived_buffer):
        waived_exit = cmd_check_deploy_readiness("release-a", "staging")
    waived_payload = json.loads(waived_buffer.getvalue())

    assert blocked_exit == 1
    assert blocked_payload["blockers"] == ["environment_frozen"]
    assert override_exit == 0
    assert override_payload["overrides"][0]["blocker"] == "environment_frozen"
    assert waived_exit == 0
    assert waived_payload["blockers"] == []
    assert "override_applied:environment_frozen:incident-commander" in waived_payload["evidence"]


def test_cmd_list_active_overrides_reports_current_entries(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_ARTIFACTS", str(tmp_path / "artifacts"))
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_ENVIRONMENT_FREEZE_WINDOWS", '{"staging":["00:00-23:59"]}')

    with redirect_stdout(io.StringIO()):
        cmd_run_evals("safety-baseline.json", "safety", "baseline", "approved-safety")
        cmd_run_release_shadow(["safety"], "release-a", "", True, "", "release-a")
        cmd_approve_release("release-a", "qa-owner", "", "approved")
        cmd_grant_release_override(
            "release-a",
            "staging",
            "environment_frozen",
            "incident-commander",
            "hotfix waiver",
            "",
        )

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        exit_code = cmd_list_active_overrides("", "staging", 10)
    payload = json.loads(buffer.getvalue())

    assert exit_code == 0
    assert len(payload) == 1
    assert payload[0]["release_name"] == "release-a"
    assert payload[0]["environment"] == "staging"
    assert payload[0]["blocker"] == "environment_frozen"


def test_cmd_release_readiness_digest_reports_summary(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_ARTIFACTS", str(tmp_path / "artifacts"))
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_ENVIRONMENT_FREEZE_WINDOWS", '{"production":["00:00-23:59"]}')
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_PRODUCTION_REQUIRED_APPROVER_ROLES", "qa-owner,release-manager")
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_OVERRIDE_EXPIRING_SOON_MINUTES", "999999999")

    with redirect_stdout(io.StringIO()):
        cmd_run_evals("safety-baseline.json", "safety", "baseline", "approved-safety")
        cmd_run_release_shadow(["safety"], "release-a", "", True, "", "release-a")
        cmd_approve_release("release-a", "qa-owner", "", "approved")
        cmd_deploy_release("release-a", "staging", "release-manager", "deploy staging")
        cmd_grant_release_override(
            "release-a",
            "production",
            "environment_frozen",
            "incident-commander",
            "hotfix waiver",
            "2999-01-01T00:30:00+00:00",
        )

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        exit_code = cmd_release_readiness_digest("release-a", [])
    payload = json.loads(buffer.getvalue())

    assert exit_code == 1
    assert payload["release_name"] == "release-a"
    assert payload["all_ready"] is False
    assert payload["blocking_environments"] == ["staging", "production"]
    assert payload["recommended_actions"]["staging"] == "no_action_already_active"
    assert payload["recommended_actions"]["production"] == "collect_required_approvals"
    assert len(payload["active_overrides"]) == 1
    assert len(payload["expiring_overrides"]) == 1


def test_cmd_release_risk_board_reports_ranked_rows(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_ARTIFACTS", str(tmp_path / "artifacts"))
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_PRODUCTION_REQUIRED_APPROVER_ROLES", "qa-owner,release-manager")
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_PRODUCTION_SOAK_MINUTES", "0")
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_OVERRIDE_EXPIRING_SOON_MINUTES", "999999999")

    with redirect_stdout(io.StringIO()):
        cmd_run_evals("safety-baseline.json", "safety", "baseline", "approved-safety")
        cmd_run_release_shadow(["safety"], "release-low", "", True, "", "release-low")
        cmd_approve_release("release-low", "qa-owner", "", "approved")
        cmd_approve_release("release-low", "release-manager", "release-manager", "approved")
        cmd_deploy_release("release-low", "staging", "release-manager", "deploy staging")
        cmd_run_release_shadow(["safety"], "release-high", "", True, "", "release-high")
        cmd_approve_release("release-high", "qa-owner", "", "approved")
        cmd_grant_release_override(
            "release-high",
            "production",
            "environment_frozen",
            "incident-commander",
            "expiring",
            "2999-01-01T00:30:00+00:00",
        )

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        exit_code = cmd_release_risk_board([], 10)
    payload = json.loads(buffer.getvalue())

    assert exit_code == 0
    assert payload["rows"][0]["release_name"] == "release-high"
    assert payload["rows"][0]["risk_level"] == "high"
    assert payload["rows"][0]["expiring_override_count"] == 1
    assert payload["rows"][1]["release_name"] == "release-low"
    assert payload["rows"][1]["risk_level"] == "low"
