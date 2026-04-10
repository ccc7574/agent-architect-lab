from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path

from agent_architect_lab.cli import (
    cmd_approval_review_board,
    cmd_approve_release,
    cmd_check_deploy_readiness,
    cmd_environment_history,
    cmd_deploy_policy,
    cmd_deploy_release,
    cmd_environment_status,
    cmd_explain_patterns,
    cmd_incident_review_board,
    cmd_incident_status,
    cmd_export_incident_report,
    cmd_export_incident_bundle,
    cmd_grant_release_override,
    cmd_list_incidents,
    cmd_list_active_overrides,
    cmd_list_operator_handoffs,
    cmd_list_skills,
    cmd_list_releases,
    cmd_open_incident,
    cmd_operator_handoff,
    cmd_override_review_board,
    cmd_promote_release,
    cmd_record_operator_handoff,
    cmd_register_report,
    cmd_revoke_release_override,
    cmd_export_operator_handoff_report,
    cmd_release_readiness_digest,
    cmd_release_risk_board,
    cmd_rollout_matrix,
    cmd_rollback_release,
    cmd_release_status,
    cmd_run_evals,
    cmd_run_release_shadow,
    cmd_show_operator_handoff,
    cmd_transition_incident,
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


def test_cmd_incident_workflow_and_review_board(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_ARTIFACTS", str(tmp_path / "artifacts"))
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_INCIDENT_STALE_MINUTES", "0")

    open_buffer = io.StringIO()
    with redirect_stdout(open_buffer):
        open_exit = cmd_open_incident(
            "critical",
            "production rollout is returning unsafe answers",
            "ic-owner",
            "production",
            "release-unsafe",
            "/tmp/report.json",
            "customer escalation",
        )
    open_payload = json.loads(open_buffer.getvalue())

    list_buffer = io.StringIO()
    with redirect_stdout(list_buffer):
        list_exit = cmd_list_incidents("", "", 10)
    list_payload = json.loads(list_buffer.getvalue())

    board_buffer = io.StringIO()
    with redirect_stdout(board_buffer):
        board_exit = cmd_incident_review_board("", 10)
    board_payload = json.loads(board_buffer.getvalue())

    transition_buffer = io.StringIO()
    with redirect_stdout(transition_buffer):
        transition_exit = cmd_transition_incident(
            open_payload["incident_id"],
            "contained",
            "incident-commander",
            "rollback complete",
            "ops-owner",
            "/tmp/followup.jsonl",
        )
    transition_payload = json.loads(transition_buffer.getvalue())

    status_buffer = io.StringIO()
    with redirect_stdout(status_buffer):
        status_exit = cmd_incident_status(open_payload["incident_id"])
    status_payload = json.loads(status_buffer.getvalue())

    assert open_exit == 0
    assert open_payload["status"] == "open"
    assert list_exit == 0
    assert list_payload[0]["incident_id"] == open_payload["incident_id"]
    assert board_exit == 0
    assert board_payload["rows"][0]["incident_id"] == open_payload["incident_id"]
    assert board_payload["rows"][0]["recommended_action"] == "escalate_incident_owner"
    assert transition_exit == 0
    assert transition_payload["status"] == "contained"
    assert transition_payload["owner"] == "ops-owner"
    assert transition_payload["followup_eval_path"] == "/tmp/followup.jsonl"
    assert status_exit == 0
    assert status_payload["events"][-1]["to_status"] == "contained"


def test_cmd_export_incident_report_writes_markdown(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_ARTIFACTS", str(tmp_path / "artifacts"))

    open_buffer = io.StringIO()
    with redirect_stdout(open_buffer):
        open_exit = cmd_open_incident(
            "high",
            "staging rollback triggered",
            "incident-commander",
            "staging",
            "release-a",
            "/tmp/report.json",
            "triage started",
        )
    open_payload = json.loads(open_buffer.getvalue())

    export_buffer = io.StringIO()
    with redirect_stdout(export_buffer):
        export_exit = cmd_export_incident_report(open_payload["incident_id"], "", "Incident Rollback Report")
    export_payload = json.loads(export_buffer.getvalue())
    markdown = Path(export_payload["saved_to"]).read_text(encoding="utf-8")

    assert open_exit == 0
    assert export_exit == 0
    assert "# Incident Rollback Report" in markdown
    assert "## Timeline" in markdown
    assert "staging rollback triggered" in markdown


def test_cmd_export_incident_bundle_writes_release_and_handoff_context(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_ARTIFACTS", str(tmp_path / "artifacts"))

    with redirect_stdout(io.StringIO()):
        cmd_run_evals("safety-baseline.json", "safety", "baseline", "approved-safety")
        cmd_run_release_shadow(["safety"], "release-a", "", True, "", "release-a")
        cmd_approve_release("release-a", "qa-owner", "", "approved")

    open_buffer = io.StringIO()
    with redirect_stdout(open_buffer):
        open_exit = cmd_open_incident(
            "high",
            "staging rollback triggered",
            "incident-commander",
            "staging",
            "release-a",
            "/tmp/report.json",
            "triage started",
        )
    open_payload = json.loads(open_buffer.getvalue())

    with redirect_stdout(io.StringIO()):
        cmd_record_operator_handoff([], 10, 10, "incident-shift")

    bundle_buffer = io.StringIO()
    with redirect_stdout(bundle_buffer):
        bundle_exit = cmd_export_incident_bundle(open_payload["incident_id"], "")
    bundle_payload = json.loads(bundle_buffer.getvalue())
    bundle_dir = Path(bundle_payload["saved_to"])
    manifest = json.loads((bundle_dir / "bundle-manifest.json").read_text(encoding="utf-8"))

    assert open_exit == 0
    assert bundle_exit == 0
    assert (bundle_dir / "incident-report.md").exists()
    assert manifest["incident"]["incident_id"] == open_payload["incident_id"]
    assert manifest["release_record"]["release_name"] == "release-a"
    assert manifest["related_handoff_snapshot_path"] is not None
    assert manifest["related_handoff_report_path"] is not None


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
        cmd_deploy_release("release-a", "staging", "release-manager", "deploy staging")

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


def test_cmd_revoke_release_override_restores_blocker(monkeypatch, tmp_path: Path) -> None:
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

    revoke_buffer = io.StringIO()
    with redirect_stdout(revoke_buffer):
        revoke_exit = cmd_revoke_release_override(
            "release-a",
            "staging",
            "environment_frozen",
            "release-manager",
            "window closed",
        )
    revoke_payload = json.loads(revoke_buffer.getvalue())

    blocked_buffer = io.StringIO()
    with redirect_stdout(blocked_buffer):
        blocked_exit = cmd_check_deploy_readiness("release-a", "staging")
    blocked_payload = json.loads(blocked_buffer.getvalue())

    assert revoke_exit == 0
    assert revoke_payload["overrides"][0]["revoked_by"] == "release-manager"
    assert blocked_exit == 1
    assert blocked_payload["blockers"] == ["environment_frozen"]


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


def test_cmd_approval_review_board_reports_backlog_and_staleness(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_ARTIFACTS", str(tmp_path / "artifacts"))
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_PRODUCTION_REQUIRED_APPROVER_ROLES", "qa-owner,release-manager")
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_PRODUCTION_SOAK_MINUTES", "0")
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_APPROVAL_STALE_MINUTES", "0")

    with redirect_stdout(io.StringIO()):
        cmd_run_evals("safety-baseline.json", "safety", "baseline", "approved-safety")
        cmd_run_release_shadow(["safety"], "release-awaiting-first", "", True, "", "release-awaiting-first")
        cmd_run_release_shadow(["safety"], "release-awaiting-role", "", True, "", "release-awaiting-role")
        cmd_approve_release("release-awaiting-role", "qa-owner", "", "approved")

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        exit_code = cmd_approval_review_board([], 10)
    payload = json.loads(buffer.getvalue())
    rows = {row["release_name"]: row for row in payload["rows"]}

    assert exit_code == 0
    assert payload["environments"] == ["staging", "production"]
    assert rows["release-awaiting-first"]["status"] == "awaiting_first_approval"
    assert rows["release-awaiting-first"]["risk_level"] == "high"
    assert rows["release-awaiting-first"]["recommended_action"] == "escalate_release_review"
    assert rows["release-awaiting-role"]["status"] == "awaiting_required_roles"
    assert rows["release-awaiting-role"]["missing_roles"] == ["release-manager"]
    assert rows["release-awaiting-role"]["blocking_environments"] == ["production"]
    assert rows["release-awaiting-role"]["approved_roles"] == ["qa-owner"]


def test_cmd_release_risk_board_flags_stale_release(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_ARTIFACTS", str(tmp_path / "artifacts"))
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_ENVIRONMENTS", "staging")
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_PRODUCTION_REQUIRED_APPROVER_ROLES", "")
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_PRODUCTION_SOAK_MINUTES", "0")
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_RELEASE_STALE_MINUTES", "0")

    with redirect_stdout(io.StringIO()):
        cmd_run_evals("safety-baseline.json", "safety", "baseline", "approved-safety")
        cmd_run_release_shadow(["safety"], "release-a", "", True, "", "release-a")
        cmd_approve_release("release-a", "qa-owner", "", "approved")

    risk_buffer = io.StringIO()
    with redirect_stdout(risk_buffer):
        risk_exit = cmd_release_risk_board([], 10)
    risk_payload = json.loads(risk_buffer.getvalue())

    handoff_buffer = io.StringIO()
    with redirect_stdout(handoff_buffer):
        handoff_exit = cmd_operator_handoff([], 10, 10)
    handoff_payload = json.loads(handoff_buffer.getvalue())

    assert risk_exit == 0
    assert risk_payload["rows"][0]["release_name"] == "release-a"
    assert risk_payload["rows"][0]["risk_level"] == "high"
    assert risk_payload["rows"][0]["is_stale"] is True
    assert risk_payload["rows"][0]["minutes_since_update"] >= 0
    assert risk_payload["rows"][0]["next_action"] == "review_stale_release"
    assert handoff_exit == 0
    assert "Stale releases: release-a." in handoff_payload["summary"]


def test_cmd_override_review_board_reports_remediation_priority(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_ARTIFACTS", str(tmp_path / "artifacts"))
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_OVERRIDE_EXPIRING_SOON_MINUTES", "999999999")

    with redirect_stdout(io.StringIO()):
        cmd_run_evals("safety-baseline.json", "safety", "baseline", "approved-safety")
        cmd_run_release_shadow(["safety"], "release-a", "", True, "", "release-a")
        cmd_approve_release("release-a", "qa-owner", "", "approved")
        cmd_grant_release_override(
            "release-a",
            "production",
            "environment_frozen",
            "incident-commander",
            "expired",
            "2000-01-01T00:00:00+00:00",
        )
        cmd_run_release_shadow(["safety"], "release-b", "", True, "", "release-b")
        cmd_approve_release("release-b", "qa-owner", "", "approved")
        cmd_grant_release_override(
            "release-b",
            "staging",
            "environment_frozen",
            "incident-commander",
            "no expiry",
            "",
        )

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        exit_code = cmd_override_review_board("", "", 10)
    payload = json.loads(buffer.getvalue())

    assert exit_code == 0
    assert payload["rows"][0]["status"] == "expired"
    assert payload["rows"][0]["recommended_action"] == "remove_or_renew_override"
    assert payload["rows"][1]["status"] == "active_no_expiry"
    assert payload["rows"][1]["recommended_action"] == "add_override_expiry"


def test_cmd_operator_handoff_reports_combined_shift_payload(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_ARTIFACTS", str(tmp_path / "artifacts"))
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_PRODUCTION_SOAK_MINUTES", "0")
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_PRODUCTION_REQUIRED_APPROVER_ROLES", "qa-owner,release-manager")
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
        exit_code = cmd_operator_handoff([], 10, 10)
    payload = json.loads(buffer.getvalue())

    assert exit_code == 0
    assert payload["release_risk_board"]["rows"][0]["release_name"] == "release-high"
    assert payload["approval_review_board"]["rows"][0]["release_name"] == "release-high"
    assert payload["override_review_board"]["rows"][0]["status"] == "expiring_soon"
    assert payload["incident_review_board"]["rows"] == []
    assert payload["active_incidents"] == []
    assert len(payload["active_overrides"]) == 1
    assert "High-risk releases: release-high." in payload["summary"]


def test_cmd_record_operator_handoff_saves_snapshot(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_ARTIFACTS", str(tmp_path / "artifacts"))

    with redirect_stdout(io.StringIO()):
        cmd_run_evals("safety-baseline.json", "safety", "baseline", "approved-safety")
        cmd_run_release_shadow(["safety"], "release-a", "", True, "", "release-a")
        cmd_approve_release("release-a", "qa-owner", "", "approved")

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        exit_code = cmd_record_operator_handoff([], 10, 10, "night-shift")
    payload = json.loads(buffer.getvalue())
    saved_path = Path(payload["saved_to"])

    assert exit_code == 0
    assert saved_path.exists()
    assert "night-shift" in saved_path.name
    assert payload["handoff"]["release_risk_board"]["rows"][0]["release_name"] == "release-a"


def test_cmd_list_operator_handoffs_reports_latest_first(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_ARTIFACTS", str(tmp_path / "artifacts"))
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_PRODUCTION_SOAK_MINUTES", "0")
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_PRODUCTION_REQUIRED_APPROVER_ROLES", "qa-owner,release-manager")
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_OVERRIDE_EXPIRING_SOON_MINUTES", "999999999")

    with redirect_stdout(io.StringIO()):
        cmd_run_evals("safety-baseline.json", "safety", "baseline", "approved-safety")
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

    first_buffer = io.StringIO()
    with redirect_stdout(first_buffer):
        first_exit = cmd_record_operator_handoff([], 10, 10, "day-shift")
    first_payload = json.loads(first_buffer.getvalue())

    second_buffer = io.StringIO()
    with redirect_stdout(second_buffer):
        second_exit = cmd_record_operator_handoff([], 10, 10, "night-shift")
    second_payload = json.loads(second_buffer.getvalue())

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        exit_code = cmd_list_operator_handoffs(10)
    payload = json.loads(buffer.getvalue())

    assert first_exit == 0
    assert second_exit == 0
    assert exit_code == 0
    assert payload["total"] == 2
    assert payload["rows"][0]["file_name"] == Path(second_payload["saved_to"]).name
    assert payload["rows"][1]["file_name"] == Path(first_payload["saved_to"]).name
    assert payload["rows"][0]["high_risk_releases"] == ["release-high"]
    assert payload["rows"][0]["approval_review_count"] == 1
    assert payload["rows"][0]["active_override_count"] == 1


def test_cmd_show_operator_handoff_loads_latest_snapshot(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_ARTIFACTS", str(tmp_path / "artifacts"))

    with redirect_stdout(io.StringIO()):
        cmd_run_evals("safety-baseline.json", "safety", "baseline", "approved-safety")
        cmd_run_release_shadow(["safety"], "release-a", "", True, "", "release-a")
        cmd_approve_release("release-a", "qa-owner", "", "approved")

    record_buffer = io.StringIO()
    with redirect_stdout(record_buffer):
        record_exit = cmd_record_operator_handoff([], 10, 10, "night-shift")
    record_payload = json.loads(record_buffer.getvalue())

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        exit_code = cmd_show_operator_handoff("", True)
    payload = json.loads(buffer.getvalue())

    assert record_exit == 0
    assert exit_code == 0
    assert payload["saved_to"] == record_payload["saved_to"]
    assert payload["handoff"]["release_risk_board"]["rows"][0]["release_name"] == "release-a"


def test_cmd_export_operator_handoff_report_writes_markdown(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_ARTIFACTS", str(tmp_path / "artifacts"))
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_PRODUCTION_SOAK_MINUTES", "0")
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_PRODUCTION_REQUIRED_APPROVER_ROLES", "qa-owner,release-manager")
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_OVERRIDE_EXPIRING_SOON_MINUTES", "999999999")

    with redirect_stdout(io.StringIO()):
        cmd_run_evals("safety-baseline.json", "safety", "baseline", "approved-safety")
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

    record_buffer = io.StringIO()
    with redirect_stdout(record_buffer):
        record_exit = cmd_record_operator_handoff([], 10, 10, "night-shift")
    record_payload = json.loads(record_buffer.getvalue())
    snapshot_path = Path(record_payload["saved_to"])

    export_buffer = io.StringIO()
    with redirect_stdout(export_buffer):
        export_exit = cmd_export_operator_handoff_report("", True, "", "Night Shift Release Report")
    export_payload = json.loads(export_buffer.getvalue())
    markdown_path = Path(export_payload["saved_to"])
    markdown = markdown_path.read_text(encoding="utf-8")

    assert record_exit == 0
    assert export_exit == 0
    assert export_payload["source_snapshot"] == str(snapshot_path)
    assert markdown_path.exists()
    assert markdown_path.suffix == ".md"
    assert "# Night Shift Release Report" in markdown
    assert "## Incident Review Board" in markdown
    assert "## Approval Review Board" in markdown
    assert "## Override Review Board" in markdown
    assert "release-high" in markdown


def test_cmd_operator_handoff_includes_active_incidents(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_ARTIFACTS", str(tmp_path / "artifacts"))
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_INCIDENT_STALE_MINUTES", "0")

    with redirect_stdout(io.StringIO()):
        cmd_open_incident(
            "high",
            "staging rollback in progress",
            "incident-commander",
            "staging",
            "release-a",
            "",
            "triage started",
        )

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        exit_code = cmd_operator_handoff([], 10, 10)
    payload = json.loads(buffer.getvalue())

    assert exit_code == 0
    assert payload["incident_review_board"]["rows"][0]["release_name"] == "release-a"
    assert payload["active_incidents"][0]["status"] == "open"
    assert "Active incidents:" in payload["summary"]
