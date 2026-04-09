from __future__ import annotations

import json
import os
from pathlib import Path

from agent_architect_lab.harness.compare import compare_reports
from agent_architect_lab.harness.gates import GateConfig, check_report_gates
from agent_architect_lab.harness.ledger import (
    ReleaseManifest,
    ReleaseLedger,
    build_release_manifest,
    record_release_candidate,
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
        assert "Cannot apply action" in str(exc)
    else:
        raise AssertionError("Expected invalid transition to raise ValueError.")
