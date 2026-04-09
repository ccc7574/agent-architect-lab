from __future__ import annotations

import json
import os
from pathlib import Path

from agent_architect_lab.harness.compare import compare_reports
from agent_architect_lab.harness.gates import GateConfig, check_report_gates
from agent_architect_lab.harness.ledger import (
    ReleaseManifest,
    check_deploy_readiness,
    get_deploy_policy,
    get_environment_history,
    get_release_readiness_digest,
    get_release_risk_board,
    get_rollout_matrix,
    ReleaseLedger,
    build_release_manifest,
    deploy_release,
    grant_release_override,
    get_environment_status,
    list_active_overrides,
    list_releases,
    record_release_candidate,
    rollback_release,
    transition_release,
)
from agent_architect_lab.harness.policies import summarize_policy_findings
from agent_architect_lab.harness.promotion import default_gate_config_for_suite, evaluate_promotion
from agent_architect_lab.harness.release import ReleaseShadowReview, run_release_shadow_review
from agent_architect_lab.harness.reporting import HarnessReport, save_report_and_record
from agent_architect_lab.harness.rollout import build_rollout_review
from agent_architect_lab.harness.shadow import run_shadow_suite
from agent_architect_lab.models import EvalResult


def _report(path: Path, *, success: bool, score: float, failure_type: str | None = None) -> HarnessReport:
    report = HarnessReport(
        suite_name="demo",
        results=[
            EvalResult(
                task_id="task-1",
                success=success,
                score=score,
                steps=2,
                status="completed" if success else "failed",
                failure_type=failure_type,
                final_answer="answer",
                run_id="run-1",
                metadata={"track": "demo"},
            )
        ],
    )
    report.save(path)
    return report


def test_compare_reports_detects_regressions(tmp_path: Path) -> None:
    baseline = _report(tmp_path / "baseline.json", success=True, score=1.0)
    candidate = _report(tmp_path / "candidate.json", success=False, score=0.5, failure_type="answer_missing_content")

    comparison = compare_reports(baseline, candidate)

    assert "success_rate_decreased" in comparison.regressions
    assert comparison.failure_type_deltas["answer_missing_content"] == 1


def test_compare_reports_flags_suite_mismatch(tmp_path: Path) -> None:
    baseline = _report(tmp_path / "baseline.json", success=True, score=1.0)
    candidate = _report(tmp_path / "candidate.json", success=True, score=1.0)
    candidate.suite_name = "different-suite"

    comparison = compare_reports(baseline, candidate)

    assert "suite_mismatch" in comparison.regressions
    assert comparison.track_success_rate_deltas == {}


def test_check_report_gates_uses_unsuccessful_failures_only(tmp_path: Path) -> None:
    report = _report(tmp_path / "report.json", success=True, score=1.0, failure_type="safety_violation")

    result = check_report_gates(report, GateConfig())

    assert result.passed is True
    assert result.failures == []


def test_check_report_gates_blocks_low_quality_reports(tmp_path: Path) -> None:
    report = _report(tmp_path / "bad.json", success=False, score=0.25, failure_type="answer_missing_content")

    result = check_report_gates(report, GateConfig(min_success_rate=1.0, min_average_score=0.9))

    assert result.passed is False
    assert any("success_rate_below_threshold" in failure for failure in result.failures)


def test_default_gate_config_for_suite_is_stricter_for_safety() -> None:
    config = default_gate_config_for_suite("safety")

    assert config.min_success_rate == 1.0
    assert config.min_average_score == 1.0
    assert config.max_average_steps == 1.5


def test_evaluate_promotion_blocks_suite_mismatch_by_default(tmp_path: Path) -> None:
    baseline = _report(tmp_path / "baseline.json", success=True, score=1.0)
    candidate = _report(tmp_path / "candidate.json", success=True, score=1.0)
    candidate.suite_name = "safety"

    result = evaluate_promotion(baseline, candidate, suite_aware_defaults=True)

    assert result.passed is False
    assert "suite_mismatch" in result.blockers
    assert result.recommended_action == "hold"


def test_evaluate_promotion_passes_candidate_when_gates_and_regressions_are_clean(tmp_path: Path) -> None:
    baseline = _report(tmp_path / "baseline.json", success=True, score=1.0)
    candidate = _report(tmp_path / "candidate.json", success=True, score=1.0)

    result = evaluate_promotion(baseline, candidate, suite_aware_defaults=True)

    assert result.passed is True
    assert result.recommended_action == "promote"


def test_rollout_review_explains_blockers_and_suggests_backfill(tmp_path: Path) -> None:
    baseline = _report(tmp_path / "baseline.json", success=True, score=1.0)
    candidate = _report(tmp_path / "candidate.json", success=False, score=0.5, failure_type="planner_timeout")
    candidate.results[0].metadata["goal"] = "demo planner timeout"

    review = build_rollout_review(baseline, candidate, suite_aware_defaults=True)

    assert review.promotion.passed is False
    assert any("passes fewer tasks" in explanation for explanation in review.blocker_explanations)
    assert review.candidate_incident_suggestions
    assert review.policy_findings
    assert review.summary == "Candidate should be held pending blocker resolution."


def test_policy_findings_capture_failure_and_track_risk(tmp_path: Path) -> None:
    baseline = _report(tmp_path / "baseline.json", success=True, score=1.0)
    candidate = _report(tmp_path / "candidate.json", success=False, score=0.5, failure_type="planner_timeout")
    comparison = compare_reports(baseline, candidate)

    findings = summarize_policy_findings(candidate, comparison)

    assert findings
    assert findings[0].policy in {"planner_reliability", "runtime_efficiency"}


def test_release_shadow_review_dataclass_serializes() -> None:
    review = ReleaseShadowReview(
        passed=False,
        suites=["safety"],
        suite_results=[],
        missing_baselines=["safety"],
        blockers=["missing_baseline:safety"],
        warnings=[],
        policy_findings=[],
        recommended_action="hold",
    )

    payload = review.to_dict()

    assert payload["passed"] is False
    assert payload["missing_baselines"] == ["safety"]


def test_run_shadow_suite_rejects_baseline_candidate_path_collision(monkeypatch, tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts"
    reports_dir = artifacts_dir / "reports"
    reports_dir.mkdir(parents=True)
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_ARTIFACTS", str(artifacts_dir))

    baseline_path = reports_dir / "shadow-report.json"
    HarnessReport(suite_name="safety", results=[]).save(baseline_path)

    try:
        run_shadow_suite(baseline_path, "safety", "shadow-report.json")
    except ValueError as exc:
        assert "must be different" in str(exc)
    else:
        raise AssertionError("Expected same-path shadow run to raise a ValueError.")


def test_run_release_shadow_review_ignores_reserved_candidate_report_names(
    monkeypatch,
    tmp_path: Path,
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    reports_dir = artifacts_dir / "reports"
    reports_dir.mkdir(parents=True)
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_ARTIFACTS", str(artifacts_dir))

    safety_baseline = _report(reports_dir / "baseline-safety.json", success=True, score=1.0)
    safety_baseline.suite_name = "safety"
    safety_baseline.save(reports_dir / "baseline-safety.json")
    retrieval_baseline = _report(reports_dir / "baseline-retrieval.json", success=True, score=1.0)
    retrieval_baseline.suite_name = "retrieval"
    retrieval_baseline.save(reports_dir / "baseline-retrieval.json")

    reserved_safety = _report(reports_dir / "release-candidate-safety.json", success=True, score=1.0)
    reserved_safety.suite_name = "safety"
    reserved_safety.save(reports_dir / "release-candidate-safety.json")
    reserved_retrieval = _report(reports_dir / "release-candidate-retrieval.json", success=True, score=1.0)
    reserved_retrieval.suite_name = "retrieval"
    reserved_retrieval.save(reports_dir / "release-candidate-retrieval.json")

    os.utime(reports_dir / "baseline-safety.json", (1, 1))
    os.utime(reports_dir / "baseline-retrieval.json", (1, 1))
    os.utime(reports_dir / "release-candidate-safety.json", (2, 2))
    os.utime(reports_dir / "release-candidate-retrieval.json", (2, 2))

    review = run_release_shadow_review(
        ["safety", "retrieval"],
        report_prefix="release-candidate",
        suite_aware_defaults=True,
    )

    result_by_suite = {result.suite_name: result for result in review.suite_results}
    assert result_by_suite["safety"].baseline_report_path.name == "baseline-safety.json"
    assert result_by_suite["retrieval"].baseline_report_path.name == "baseline-retrieval.json"
    assert result_by_suite["safety"].baseline_report_path != result_by_suite["safety"].candidate_report_path
    assert result_by_suite["retrieval"].baseline_report_path != result_by_suite["retrieval"].candidate_report_path
    assert review.summary
    assert review.suite_recommendations["safety"] in {"hold", "promote", "promote_with_review"}


def test_run_release_shadow_review_prefers_registered_baseline_over_newer_discovery(
    monkeypatch,
    tmp_path: Path,
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    reports_dir = artifacts_dir / "reports"
    reports_dir.mkdir(parents=True)
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_ARTIFACTS", str(artifacts_dir))

    approved_baseline = _report(reports_dir / "approved-safety.json", success=True, score=1.0)
    approved_baseline.suite_name = "safety"
    save_report_and_record(
        approved_baseline,
        reports_dir / "approved-safety.json",
        report_kind="baseline",
        label="approved",
        source="test",
    )

    newer_unapproved = _report(reports_dir / "newer-safety.json", success=True, score=1.0)
    newer_unapproved.suite_name = "safety"
    newer_unapproved.save(reports_dir / "newer-safety.json")
    os.utime(reports_dir / "approved-safety.json", (1, 1))
    os.utime(reports_dir / "newer-safety.json", (10, 10))

    review = run_release_shadow_review(["safety"], report_prefix="registry-release", suite_aware_defaults=True)

    assert review.baseline_sources["safety"] == "registry"
    assert review.suite_results[0].baseline_report_path.name == "approved-safety.json"


def test_run_release_shadow_review_supports_explicit_baseline_manifest(
    monkeypatch,
    tmp_path: Path,
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    reports_dir = artifacts_dir / "reports"
    reports_dir.mkdir(parents=True)
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_ARTIFACTS", str(artifacts_dir))

    manifest_baseline = _report(reports_dir / "manifest-retrieval.json", success=True, score=1.0)
    manifest_baseline.suite_name = "retrieval"
    manifest_baseline.save(reports_dir / "manifest-retrieval.json")

    registered_baseline = _report(reports_dir / "registered-retrieval.json", success=True, score=1.0)
    registered_baseline.suite_name = "retrieval"
    save_report_and_record(
        registered_baseline,
        reports_dir / "registered-retrieval.json",
        report_kind="baseline",
        label="registered",
        source="test",
    )

    manifest_path = tmp_path / "baseline-manifest.json"
    manifest_path.write_text(
        json.dumps({"retrieval": {"report_path": str(reports_dir / "manifest-retrieval.json")}}, indent=2),
        encoding="utf-8",
    )

    review = run_release_shadow_review(
        ["retrieval"],
        report_prefix="manifest-release",
        suite_aware_defaults=True,
        baseline_manifest=manifest_path,
    )

    assert review.baseline_sources["retrieval"] == "manifest"
    assert review.suite_results[0].baseline_report_path.name == "manifest-retrieval.json"


def test_build_release_manifest_captures_suite_snapshots() -> None:
    review = ReleaseShadowReview(
        passed=True,
        suites=["safety"],
        suite_results=[],
        blockers=[],
        warnings=[],
        policy_findings=[],
        recommended_action="promote",
        summary="ready",
        baseline_sources={"safety": "registry"},
    )

    manifest = build_release_manifest(review, "release-001", "candidate")

    assert manifest.release_name == "release-001"
    assert manifest.baseline_sources["safety"] == "registry"
    assert manifest.suite_snapshots == []


def test_record_release_candidate_creates_immutable_manifest_and_pending_record(tmp_path: Path) -> None:
    releases_dir = tmp_path / "releases"
    review = ReleaseShadowReview(
        passed=True,
        suites=["safety"],
        suite_results=[],
        blockers=[],
        warnings=[],
        policy_findings=[],
        recommended_action="promote",
        summary="ready",
        baseline_sources={"safety": "registry"},
    )

    record = record_release_candidate(
        review,
        release_name="release-001",
        report_prefix="candidate",
        releases_dir=releases_dir,
    )

    manifest_path = releases_dir / "manifests" / "release-001.json"
    manifest = ReleaseManifest.load(manifest_path)
    ledger = ReleaseLedger.load(releases_dir / "release-ledger.json")

    assert manifest.release_name == "release-001"
    assert record.state == "pending_approval"
    assert ledger.get("release-001").state == "pending_approval"


def test_record_release_candidate_marks_blocked_release_when_review_has_blockers(tmp_path: Path) -> None:
    releases_dir = tmp_path / "releases"
    review = ReleaseShadowReview(
        passed=False,
        suites=["safety"],
        suite_results=[],
        blockers=["safety:success_rate_decreased"],
        warnings=[],
        policy_findings=[],
        recommended_action="hold",
        summary="hold",
        baseline_sources={"safety": "registry"},
    )

    record = record_release_candidate(
        review,
        release_name="release-002",
        report_prefix="candidate",
        releases_dir=releases_dir,
    )

    assert record.state == "blocked"


def test_release_ledger_allows_approve_then_promote(tmp_path: Path) -> None:
    releases_dir = tmp_path / "releases"
    review = ReleaseShadowReview(
        passed=True,
        suites=["retrieval"],
        suite_results=[],
        blockers=[],
        warnings=[],
        policy_findings=[],
        recommended_action="promote",
        summary="ready",
        baseline_sources={"retrieval": "manifest"},
    )
    record_release_candidate(
        review,
        release_name="release-003",
        report_prefix="candidate",
        releases_dir=releases_dir,
    )

    approved = transition_release(
        "release-003",
        action="approve",
        actor="qa-owner",
        note="approved for rollout",
        ledger_path=releases_dir / "release-ledger.json",
    )
    promoted = transition_release(
        "release-003",
        action="promote",
        actor="release-manager",
        note="promoted to prod",
        ledger_path=releases_dir / "release-ledger.json",
    )

    assert approved.state == "approved"
    assert promoted.state == "promoted"
    assert promoted.events[-1].action == "promote"


def test_release_ledger_rejects_invalid_transition(tmp_path: Path) -> None:
    releases_dir = tmp_path / "releases"
    review = ReleaseShadowReview(
        passed=False,
        suites=["safety"],
        suite_results=[],
        blockers=["missing_baseline:safety"],
        warnings=[],
        policy_findings=[],
        recommended_action="hold",
        summary="blocked",
        baseline_sources={},
    )
    record_release_candidate(
        review,
        release_name="release-004",
        report_prefix="candidate",
        releases_dir=releases_dir,
    )

    try:
        transition_release(
            "release-004",
            action="approve",
            actor="qa-owner",
            note="force approve",
            ledger_path=releases_dir / "release-ledger.json",
        )
    except ValueError as exc:
        assert "Cannot approve release" in str(exc)
    else:
        raise AssertionError("Expected invalid transition to raise ValueError.")


def test_release_ledger_requires_approval_before_deploy(tmp_path: Path) -> None:
    releases_dir = tmp_path / "releases"
    review = ReleaseShadowReview(
        passed=True,
        suites=["safety"],
        suite_results=[],
        blockers=[],
        warnings=[],
        policy_findings=[],
        recommended_action="promote",
        summary="ready",
        baseline_sources={"safety": "registry"},
    )
    record_release_candidate(
        review,
        release_name="release-005",
        report_prefix="candidate",
        releases_dir=releases_dir,
    )

    try:
        deploy_release(
            "release-005",
            environment="staging",
            actor="release-manager",
            note="try deploy too early",
            ledger_path=releases_dir / "release-ledger.json",
        )
    except ValueError as exc:
        assert "release_not_approved" in str(exc)
    else:
        raise AssertionError("Expected deployment without approval to raise ValueError.")


def test_release_ledger_requires_staging_before_production(tmp_path: Path) -> None:
    releases_dir = tmp_path / "releases"
    review = ReleaseShadowReview(
        passed=True,
        suites=["retrieval"],
        suite_results=[],
        blockers=[],
        warnings=[],
        policy_findings=[],
        recommended_action="promote",
        summary="ready",
        baseline_sources={"retrieval": "registry"},
    )
    record_release_candidate(
        review,
        release_name="release-006",
        report_prefix="candidate",
        releases_dir=releases_dir,
    )
    transition_release(
        "release-006",
        action="approve",
        actor="qa-owner",
        note="approved",
        ledger_path=releases_dir / "release-ledger.json",
    )

    try:
        deploy_release(
            "release-006",
            environment="production",
            actor="release-manager",
            note="skip staging",
            ledger_path=releases_dir / "release-ledger.json",
        )
    except ValueError as exc:
        assert "staging" in str(exc)
    else:
        raise AssertionError("Expected production deployment without staging to raise ValueError.")


def test_check_deploy_readiness_blocks_production_without_staging(tmp_path: Path) -> None:
    releases_dir = tmp_path / "releases"
    review = ReleaseShadowReview(
        passed=True,
        suites=["retrieval"],
        suite_results=[],
        blockers=[],
        warnings=[],
        policy_findings=[],
        recommended_action="promote",
        summary="ready",
        baseline_sources={"retrieval": "registry"},
    )
    record_release_candidate(
        review,
        release_name="release-006b",
        report_prefix="candidate",
        releases_dir=releases_dir,
    )
    ledger_path = releases_dir / "release-ledger.json"
    transition_release("release-006b", action="approve", actor="qa-owner", note="approved", ledger_path=ledger_path)

    readiness = check_deploy_readiness(
        "release-006b",
        environment="production",
        ledger_path=ledger_path,
        production_soak_minutes=30,
    )

    assert readiness.passed is False
    assert "missing_active_staging_deployment" in readiness.blockers


def test_check_deploy_readiness_blocks_production_when_staging_soak_is_short(tmp_path: Path) -> None:
    releases_dir = tmp_path / "releases"
    review = ReleaseShadowReview(
        passed=True,
        suites=["safety"],
        suite_results=[],
        blockers=[],
        warnings=[],
        policy_findings=[],
        recommended_action="promote",
        summary="ready",
        baseline_sources={"safety": "registry"},
    )
    record_release_candidate(
        review,
        release_name="release-soak",
        report_prefix="candidate",
        releases_dir=releases_dir,
    )
    ledger_path = releases_dir / "release-ledger.json"
    transition_release("release-soak", action="approve", actor="qa-owner", note="approved", ledger_path=ledger_path)
    deploy_release(
        "release-soak",
        environment="staging",
        actor="release-manager",
        note="deploy staging",
        ledger_path=ledger_path,
        production_soak_minutes=30,
    )

    readiness = check_deploy_readiness(
        "release-soak",
        environment="production",
        ledger_path=ledger_path,
        production_soak_minutes=30,
        required_approver_roles=[],
    )

    assert readiness.passed is False
    assert "staging_soak_incomplete" in readiness.blockers
    assert readiness.soak_minutes_required == 30


def test_check_deploy_readiness_passes_when_staging_soak_requirement_is_met(tmp_path: Path) -> None:
    releases_dir = tmp_path / "releases"
    review = ReleaseShadowReview(
        passed=True,
        suites=["safety"],
        suite_results=[],
        blockers=[],
        warnings=[],
        policy_findings=[],
        recommended_action="promote",
        summary="ready",
        baseline_sources={"safety": "registry"},
    )
    record_release_candidate(
        review,
        release_name="release-ready",
        report_prefix="candidate",
        releases_dir=releases_dir,
    )
    ledger_path = releases_dir / "release-ledger.json"
    transition_release("release-ready", action="approve", actor="qa-owner", note="approved", ledger_path=ledger_path)
    transition_release(
        "release-ready",
        action="approve",
        actor="release-manager",
        role="release-manager",
        note="ops approved",
        ledger_path=ledger_path,
    )
    deploy_release(
        "release-ready",
        environment="staging",
        actor="release-manager",
        note="deploy staging",
        ledger_path=ledger_path,
        production_soak_minutes=0,
        required_approver_roles=[],
    )

    readiness = check_deploy_readiness(
        "release-ready",
        environment="production",
        ledger_path=ledger_path,
        production_soak_minutes=0,
        required_approver_roles=["qa-owner", "release-manager"],
    )

    assert readiness.passed is True
    assert readiness.blockers == []


def test_check_deploy_readiness_blocks_when_environment_is_frozen(tmp_path: Path) -> None:
    releases_dir = tmp_path / "releases"
    review = ReleaseShadowReview(
        passed=True,
        suites=["safety"],
        suite_results=[],
        blockers=[],
        warnings=[],
        policy_findings=[],
        recommended_action="promote",
        summary="ready",
        baseline_sources={"safety": "registry"},
    )
    record_release_candidate(
        review,
        release_name="release-frozen",
        report_prefix="candidate",
        releases_dir=releases_dir,
    )
    ledger_path = releases_dir / "release-ledger.json"
    transition_release("release-frozen", action="approve", actor="qa-owner", note="approved", ledger_path=ledger_path)

    readiness = check_deploy_readiness(
        "release-frozen",
        environment="staging",
        ledger_path=ledger_path,
        production_soak_minutes=0,
        required_approver_roles=[],
        environment_freeze_windows={"staging": ["00:00-23:59"]},
    )

    assert readiness.passed is False
    assert "environment_frozen" in readiness.blockers
    assert readiness.active_freeze_window == "00:00-23:59"


def test_get_deploy_policy_reports_environment_requirements_and_head(tmp_path: Path) -> None:
    releases_dir = tmp_path / "releases"
    review = ReleaseShadowReview(
        passed=True,
        suites=["safety"],
        suite_results=[],
        blockers=[],
        warnings=[],
        policy_findings=[],
        recommended_action="promote",
        summary="ready",
        baseline_sources={"safety": "registry"},
    )
    record_release_candidate(
        review,
        release_name="release-policy",
        report_prefix="candidate",
        releases_dir=releases_dir,
    )
    ledger_path = releases_dir / "release-ledger.json"
    transition_release("release-policy", action="approve", actor="qa-owner", note="approved", ledger_path=ledger_path)
    transition_release(
        "release-policy",
        action="approve",
        actor="release-manager",
        role="release-manager",
        note="ops approved",
        ledger_path=ledger_path,
    )
    deploy_release(
        "release-policy",
        environment="staging",
        actor="release-manager",
        note="deploy staging",
        ledger_path=ledger_path,
        production_soak_minutes=0,
        required_approver_roles=[],
    )
    deploy_release(
        "release-policy",
        environment="production",
        actor="release-manager",
        note="deploy production",
        ledger_path=ledger_path,
        production_soak_minutes=0,
        required_approver_roles=[],
    )

    policy = get_deploy_policy(
        "production",
        ledger_path=ledger_path,
        production_soak_minutes=45,
        required_approver_roles=["qa-owner", "release-manager"],
        environment_freeze_windows={"production": ["00:00-23:59"]},
    )

    assert policy.environment == "production"
    assert policy.required_predecessor_environment == "staging"
    assert policy.required_approver_roles == ["qa-owner", "release-manager"]
    assert policy.soak_minutes_required == 45
    assert policy.freeze_windows == ["00:00-23:59"]
    assert policy.active_freeze_window == "00:00-23:59"
    assert policy.environment_status == "active"
    assert policy.active_release == "release-policy"


def test_release_ledger_can_roll_back_and_reactivate_prior_release(tmp_path: Path) -> None:
    releases_dir = tmp_path / "releases"
    review = ReleaseShadowReview(
        passed=True,
        suites=["safety"],
        suite_results=[],
        blockers=[],
        warnings=[],
        policy_findings=[],
        recommended_action="promote",
        summary="ready",
        baseline_sources={"safety": "registry"},
    )
    record_release_candidate(
        review,
        release_name="release-007-a",
        report_prefix="candidate-a",
        releases_dir=releases_dir,
    )
    record_release_candidate(
        review,
        release_name="release-007-b",
        report_prefix="candidate-b",
        releases_dir=releases_dir,
    )
    ledger_path = releases_dir / "release-ledger.json"
    transition_release("release-007-a", action="approve", actor="qa-owner", note="approved", ledger_path=ledger_path)
    transition_release("release-007-b", action="approve", actor="qa-owner", note="approved", ledger_path=ledger_path)

    first = deploy_release(
        "release-007-a",
        environment="staging",
        actor="release-manager",
        note="deploy A",
        ledger_path=ledger_path,
    )
    second = deploy_release(
        "release-007-b",
        environment="staging",
        actor="release-manager",
        note="deploy B",
        ledger_path=ledger_path,
    )
    rolled_back = rollback_release(
        "release-007-b",
        environment="staging",
        actor="release-manager",
        note="rollback B",
        ledger_path=ledger_path,
    )
    ledger = ReleaseLedger.load(ledger_path)
    restored = ledger.get("release-007-a")
    rolled_back_record = ledger.get("release-007-b")

    assert first.deployments[-1].status in {"active", "superseded"}
    assert second.deployments[-1].status in {"active", "rolled_back"}
    assert rolled_back.deployments[-1].rolled_back_by == "release-manager"
    assert rolled_back_record.deployments[-1].status == "rolled_back"
    assert restored.deployments[-1].status == "active"
    assert restored.deployments[-1].reactivated_by == "release-manager"


def test_list_releases_returns_newest_first(tmp_path: Path) -> None:
    releases_dir = tmp_path / "releases"
    review = ReleaseShadowReview(
        passed=True,
        suites=["safety"],
        suite_results=[],
        blockers=[],
        warnings=[],
        policy_findings=[],
        recommended_action="promote",
        summary="ready",
        baseline_sources={"safety": "registry"},
    )
    record_release_candidate(review, release_name="release-old", report_prefix="old", releases_dir=releases_dir)
    record_release_candidate(review, release_name="release-new", report_prefix="new", releases_dir=releases_dir)

    records = list_releases(ledger_path=releases_dir / "release-ledger.json")

    assert [record.release_name for record in records] == ["release-new", "release-old"]


def test_environment_status_tracks_active_release(tmp_path: Path) -> None:
    releases_dir = tmp_path / "releases"
    review = ReleaseShadowReview(
        passed=True,
        suites=["safety"],
        suite_results=[],
        blockers=[],
        warnings=[],
        policy_findings=[],
        recommended_action="promote",
        summary="ready",
        baseline_sources={"safety": "registry"},
    )
    record_release_candidate(review, release_name="release-env-a", report_prefix="a", releases_dir=releases_dir)
    record_release_candidate(review, release_name="release-env-b", report_prefix="b", releases_dir=releases_dir)
    ledger_path = releases_dir / "release-ledger.json"
    transition_release("release-env-a", action="approve", actor="qa-owner", note="approved", ledger_path=ledger_path)
    transition_release("release-env-b", action="approve", actor="qa-owner", note="approved", ledger_path=ledger_path)
    deploy_release("release-env-a", environment="staging", actor="release-manager", note="deploy A", ledger_path=ledger_path)
    deploy_release("release-env-b", environment="staging", actor="release-manager", note="deploy B", ledger_path=ledger_path)

    before_rollback = get_environment_status("staging", ledger_path=ledger_path)
    rollback_release("release-env-b", environment="staging", actor="release-manager", note="rollback B", ledger_path=ledger_path)
    after_rollback = get_environment_status("staging", ledger_path=ledger_path)
    empty = get_environment_status("production", ledger_path=ledger_path)

    assert before_rollback.active_release == "release-env-b"
    assert after_rollback.active_release == "release-env-a"
    assert empty.status == "empty"


def test_environment_history_tracks_supersede_and_rollback_lineage(tmp_path: Path) -> None:
    releases_dir = tmp_path / "releases"
    review = ReleaseShadowReview(
        passed=True,
        suites=["safety"],
        suite_results=[],
        blockers=[],
        warnings=[],
        policy_findings=[],
        recommended_action="promote",
        summary="ready",
        baseline_sources={"safety": "registry"},
    )
    record_release_candidate(review, release_name="release-env-a", report_prefix="a", releases_dir=releases_dir)
    record_release_candidate(review, release_name="release-env-b", report_prefix="b", releases_dir=releases_dir)
    ledger_path = releases_dir / "release-ledger.json"
    transition_release("release-env-a", action="approve", actor="qa-owner", note="approved", ledger_path=ledger_path)
    transition_release("release-env-b", action="approve", actor="qa-owner", note="approved", ledger_path=ledger_path)
    deploy_release("release-env-a", environment="staging", actor="release-manager", note="deploy A", ledger_path=ledger_path)
    deploy_release("release-env-b", environment="staging", actor="release-manager", note="deploy B", ledger_path=ledger_path)
    rollback_release("release-env-b", environment="staging", actor="release-manager", note="rollback B", ledger_path=ledger_path)

    history = get_environment_history("staging", ledger_path=ledger_path)

    assert [entry.release_name for entry in history[:2]] == ["release-env-a", "release-env-b"]
    assert history[0].status == "active"
    assert history[0].reactivated_by == "release-manager"
    assert history[1].status == "rolled_back"
    assert history[1].rolled_back_by == "release-manager"


def test_get_rollout_matrix_reports_policy_and_release_readiness(tmp_path: Path) -> None:
    releases_dir = tmp_path / "releases"
    review = ReleaseShadowReview(
        passed=True,
        suites=["safety"],
        suite_results=[],
        blockers=[],
        warnings=[],
        policy_findings=[],
        recommended_action="promote",
        summary="ready",
        baseline_sources={"safety": "registry"},
    )
    record_release_candidate(review, release_name="release-matrix", report_prefix="matrix", releases_dir=releases_dir)
    ledger_path = releases_dir / "release-ledger.json"
    transition_release("release-matrix", action="approve", actor="qa-owner", note="approved", ledger_path=ledger_path)
    deploy_release(
        "release-matrix",
        environment="staging",
        actor="release-manager",
        note="deploy staging",
        ledger_path=ledger_path,
        production_soak_minutes=0,
        required_approver_roles=[],
    )

    matrix = get_rollout_matrix(
        ["staging", "production"],
        ledger_path=ledger_path,
        release_name="release-matrix",
        production_soak_minutes=30,
        required_approver_roles=["qa-owner", "release-manager"],
        environment_freeze_windows={"production": ["00:00-23:59"]},
    )

    assert matrix.release_name == "release-matrix"
    assert matrix.all_ready is False
    assert [row.environment for row in matrix.rows] == ["staging", "production"]
    assert matrix.rows[0].readiness is not None
    assert matrix.rows[0].readiness.passed is False
    assert "already_active_in_environment" in matrix.rows[0].readiness.blockers
    assert matrix.rows[0].recommended_action == "no_action_already_active"
    assert matrix.rows[1].policy.required_predecessor_environment == "staging"
    assert matrix.rows[1].readiness is not None
    assert "environment_frozen" in matrix.rows[1].readiness.blockers
    assert matrix.rows[1].recommended_action == "collect_required_approvals"


def test_get_rollout_matrix_without_release_only_reports_environment_views(tmp_path: Path) -> None:
    releases_dir = tmp_path / "releases"
    review = ReleaseShadowReview(
        passed=True,
        suites=["safety"],
        suite_results=[],
        blockers=[],
        warnings=[],
        policy_findings=[],
        recommended_action="promote",
        summary="ready",
        baseline_sources={"safety": "registry"},
    )
    record_release_candidate(review, release_name="release-head", report_prefix="head", releases_dir=releases_dir)
    ledger_path = releases_dir / "release-ledger.json"
    transition_release("release-head", action="approve", actor="qa-owner", note="approved", ledger_path=ledger_path)
    deploy_release("release-head", environment="staging", actor="release-manager", note="deploy", ledger_path=ledger_path)

    matrix = get_rollout_matrix(
        ["staging", "production"],
        ledger_path=ledger_path,
        environment_freeze_windows={"production": ["23:00-23:59"]},
    )

    assert matrix.release_name is None
    assert matrix.all_ready is None
    assert matrix.rows[0].policy.active_release == "release-head"
    assert matrix.rows[0].readiness is None
    assert matrix.rows[0].recommended_action == "observe_environment"
    assert matrix.rows[1].policy.freeze_windows == ["23:00-23:59"]


def test_environment_specific_policies_extend_readiness_chain(tmp_path: Path) -> None:
    releases_dir = tmp_path / "releases"
    review = ReleaseShadowReview(
        passed=True,
        suites=["safety"],
        suite_results=[],
        blockers=[],
        warnings=[],
        policy_findings=[],
        recommended_action="promote",
        summary="ready",
        baseline_sources={"safety": "registry"},
    )
    record_release_candidate(review, release_name="release-chain", report_prefix="chain", releases_dir=releases_dir)
    ledger_path = releases_dir / "release-ledger.json"
    environment_policies = {
        "canary": {
            "required_predecessor_environment": "staging",
            "required_approver_roles": ["qa-owner"],
            "soak_minutes_required": 0,
        },
        "production": {
            "required_predecessor_environment": "canary",
            "required_approver_roles": ["ops-oncall"],
            "soak_minutes_required": 10,
            "freeze_windows": ["00:00-23:59"],
        },
    }

    transition_release("release-chain", action="approve", actor="qa-owner", note="approved", ledger_path=ledger_path)
    deploy_release("release-chain", environment="staging", actor="release-manager", note="deploy staging", ledger_path=ledger_path)

    canary_readiness = check_deploy_readiness(
        "release-chain",
        environment="canary",
        ledger_path=ledger_path,
        environment_policies=environment_policies,
    )
    assert canary_readiness.passed is True

    deploy_release(
        "release-chain",
        environment="canary",
        actor="release-manager",
        note="deploy canary",
        ledger_path=ledger_path,
        environment_policies=environment_policies,
    )

    production_policy = get_deploy_policy(
        "production",
        ledger_path=ledger_path,
        environment_policies=environment_policies,
    )
    production_readiness = check_deploy_readiness(
        "release-chain",
        environment="production",
        ledger_path=ledger_path,
        environment_policies=environment_policies,
    )

    assert production_policy.required_predecessor_environment == "canary"
    assert production_policy.required_approver_roles == ["ops-oncall"]
    assert production_policy.soak_minutes_required == 10
    assert production_policy.freeze_windows == ["00:00-23:59"]
    assert production_readiness.passed is False
    assert "missing_required_approvals:ops-oncall" in production_readiness.blockers
    assert "environment_frozen" in production_readiness.blockers
    assert "predecessor_soak_incomplete:canary" in production_readiness.blockers


def test_release_override_can_waive_specific_blocker(tmp_path: Path) -> None:
    releases_dir = tmp_path / "releases"
    review = ReleaseShadowReview(
        passed=True,
        suites=["safety"],
        suite_results=[],
        blockers=[],
        warnings=[],
        policy_findings=[],
        recommended_action="promote",
        summary="ready",
        baseline_sources={"safety": "registry"},
    )
    record_release_candidate(review, release_name="release-override", report_prefix="override", releases_dir=releases_dir)
    ledger_path = releases_dir / "release-ledger.json"
    transition_release("release-override", action="approve", actor="qa-owner", note="approved", ledger_path=ledger_path)

    blocked = check_deploy_readiness(
        "release-override",
        environment="staging",
        ledger_path=ledger_path,
        environment_freeze_windows={"staging": ["00:00-23:59"]},
    )
    assert blocked.passed is False
    assert blocked.blockers == ["environment_frozen"]

    grant_release_override(
        "release-override",
        environment="staging",
        blocker="environment_frozen",
        actor="incident-commander",
        note="hotfix waiver",
        ledger_path=ledger_path,
    )

    waived = check_deploy_readiness(
        "release-override",
        environment="staging",
        ledger_path=ledger_path,
        environment_freeze_windows={"staging": ["00:00-23:59"]},
    )

    assert waived.passed is True
    assert waived.blockers == []
    assert "override_applied:environment_frozen:incident-commander" in waived.evidence


def test_release_override_rejects_non_overridable_blocker(tmp_path: Path) -> None:
    releases_dir = tmp_path / "releases"
    review = ReleaseShadowReview(
        passed=True,
        suites=["safety"],
        suite_results=[],
        blockers=[],
        warnings=[],
        policy_findings=[],
        recommended_action="promote",
        summary="ready",
        baseline_sources={"safety": "registry"},
    )
    record_release_candidate(review, release_name="release-no-override", report_prefix="override", releases_dir=releases_dir)
    ledger_path = releases_dir / "release-ledger.json"

    try:
        grant_release_override(
            "release-no-override",
            environment="staging",
            blocker="release_not_approved",
            actor="incident-commander",
            note="should fail",
            ledger_path=ledger_path,
        )
    except ValueError as exc:
        assert "cannot be overridden" in str(exc)
    else:
        raise AssertionError("Expected non-overridable blocker to raise ValueError.")


def test_list_active_overrides_filters_and_skips_expired_entries(tmp_path: Path) -> None:
    releases_dir = tmp_path / "releases"
    review = ReleaseShadowReview(
        passed=True,
        suites=["safety"],
        suite_results=[],
        blockers=[],
        warnings=[],
        policy_findings=[],
        recommended_action="promote",
        summary="ready",
        baseline_sources={"safety": "registry"},
    )
    record_release_candidate(review, release_name="release-a", report_prefix="a", releases_dir=releases_dir)
    record_release_candidate(review, release_name="release-b", report_prefix="b", releases_dir=releases_dir)
    ledger_path = releases_dir / "release-ledger.json"
    transition_release("release-a", action="approve", actor="qa-owner", note="approved", ledger_path=ledger_path)
    transition_release("release-b", action="approve", actor="qa-owner", note="approved", ledger_path=ledger_path)

    grant_release_override(
        "release-a",
        environment="staging",
        blocker="environment_frozen",
        actor="incident-commander",
        note="active",
        ledger_path=ledger_path,
    )
    grant_release_override(
        "release-b",
        environment="production",
        blocker="missing_required_approvals:ops-oncall",
        actor="release-director",
        note="expired",
        expires_at="2000-01-01T00:00:00+00:00",
        ledger_path=ledger_path,
    )

    all_entries = list_active_overrides(ledger_path=ledger_path)
    staging_entries = list_active_overrides(ledger_path=ledger_path, environment="staging")
    release_entries = list_active_overrides(ledger_path=ledger_path, release_name="release-a")

    assert len(all_entries) == 1
    assert all_entries[0].release_name == "release-a"
    assert all_entries[0].environment == "staging"
    assert len(staging_entries) == 1
    assert staging_entries[0].blocker == "environment_frozen"
    assert len(release_entries) == 1
    assert release_entries[0].actor == "incident-commander"


def test_release_readiness_digest_summarizes_blockers_and_expiring_overrides(tmp_path: Path) -> None:
    releases_dir = tmp_path / "releases"
    review = ReleaseShadowReview(
        passed=True,
        suites=["safety"],
        suite_results=[],
        blockers=[],
        warnings=[],
        policy_findings=[],
        recommended_action="promote",
        summary="ready",
        baseline_sources={"safety": "registry"},
    )
    record_release_candidate(review, release_name="release-digest", report_prefix="digest", releases_dir=releases_dir)
    ledger_path = releases_dir / "release-ledger.json"
    transition_release("release-digest", action="approve", actor="qa-owner", note="approved", ledger_path=ledger_path)
    deploy_release(
        "release-digest",
        environment="staging",
        actor="release-manager",
        note="deploy staging",
        ledger_path=ledger_path,
        production_soak_minutes=0,
        required_approver_roles=[],
    )
    grant_release_override(
        "release-digest",
        environment="production",
        blocker="environment_frozen",
        actor="incident-commander",
        note="expires soon",
        expires_at="2099-01-01T00:30:00+00:00",
        ledger_path=ledger_path,
    )

    digest = get_release_readiness_digest(
        "release-digest",
        environments=["staging", "production"],
        ledger_path=ledger_path,
        production_soak_minutes=0,
        required_approver_roles=["qa-owner", "release-manager"],
        environment_freeze_windows={"production": ["00:00-23:59"]},
        override_expiring_soon_minutes=999999999,
    )

    assert digest.release_name == "release-digest"
    assert digest.all_ready is False
    assert digest.blocking_environments == ["staging", "production"]
    assert digest.ready_environments == []
    assert digest.recommended_actions["staging"] == "no_action_already_active"
    assert digest.recommended_actions["production"] == "collect_required_approvals"
    assert len(digest.active_overrides) == 1
    assert len(digest.expiring_overrides) == 1
    assert "expire soon" in digest.summary


def test_release_risk_board_ranks_releases_by_operator_risk(tmp_path: Path) -> None:
    releases_dir = tmp_path / "releases"
    review = ReleaseShadowReview(
        passed=True,
        suites=["safety"],
        suite_results=[],
        blockers=[],
        warnings=[],
        policy_findings=[],
        recommended_action="promote",
        summary="ready",
        baseline_sources={"safety": "registry"},
    )
    record_release_candidate(review, release_name="release-low", report_prefix="low", releases_dir=releases_dir)
    record_release_candidate(review, release_name="release-high", report_prefix="high", releases_dir=releases_dir)
    ledger_path = releases_dir / "release-ledger.json"
    transition_release("release-low", action="approve", actor="qa-owner", note="approved", ledger_path=ledger_path)
    transition_release("release-low", action="approve", actor="release-manager", role="release-manager", note="approved", ledger_path=ledger_path)
    transition_release("release-high", action="approve", actor="qa-owner", note="approved", ledger_path=ledger_path)
    deploy_release(
        "release-low",
        environment="staging",
        actor="release-manager",
        note="deploy staging",
        ledger_path=ledger_path,
        production_soak_minutes=0,
        required_approver_roles=[],
    )
    grant_release_override(
        "release-high",
        environment="production",
        blocker="environment_frozen",
        actor="incident-commander",
        note="expiring",
        expires_at="2999-01-01T00:30:00+00:00",
        ledger_path=ledger_path,
    )

    board = get_release_risk_board(
        environments=["staging", "production"],
        ledger_path=ledger_path,
        production_soak_minutes=0,
        required_approver_roles=["qa-owner", "release-manager"],
        override_expiring_soon_minutes=999999999,
        limit=10,
    )

    assert [row.release_name for row in board.rows[:2]] == ["release-high", "release-low"]
    assert board.rows[0].risk_level == "high"
    assert board.rows[0].next_action == "collect_required_approvals"
    assert board.rows[0].expiring_override_count == 1
    assert board.rows[1].risk_level == "low"
    assert board.rows[1].next_action == "observe_release"
