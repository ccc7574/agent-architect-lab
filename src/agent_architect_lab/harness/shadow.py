from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent_architect_lab.agent.runtime import AgentRuntime
from agent_architect_lab.config import load_settings
from agent_architect_lab.evals.tasks import load_suite
from agent_architect_lab.harness.incidents import save_incident_suggestions
from agent_architect_lab.harness.reporting import HarnessReport, save_report_and_record
from agent_architect_lab.harness.rollout import RolloutReview, build_rollout_review
from agent_architect_lab.harness.runner import run_suite


@dataclass(slots=True)
class ShadowRunResult:
    suite_name: str
    baseline_report_path: Path
    candidate_report_path: Path
    rollout_review: RolloutReview
    backfill_path: Path | None = None

    def to_dict(self) -> dict:
        payload = {
            "suite_name": self.suite_name,
            "baseline_report_path": str(self.baseline_report_path),
            "candidate_report_path": str(self.candidate_report_path),
            "rollout_review": self.rollout_review.to_dict(),
        }
        if self.backfill_path is not None:
            payload["backfill_path"] = str(self.backfill_path)
        return payload


def run_shadow_suite(
    baseline_report_path: Path,
    suite_name: str,
    report_name: str,
    *,
    output_backfill: Path | None = None,
    allow_suite_mismatch: bool = False,
    suite_aware_defaults: bool = True,
    report_kind: str = "shadow_candidate",
    report_label: str = "",
    report_source: str = "run-shadow",
) -> ShadowRunResult:
    settings = load_settings()
    candidate_report_path = settings.reports_dir / report_name
    if baseline_report_path.resolve() == candidate_report_path.resolve():
        raise ValueError("Baseline and candidate report paths must be different for a shadow run.")
    baseline_report = HarnessReport.load(baseline_report_path)
    runtime = AgentRuntime()
    try:
        suite = load_suite(settings.project_root, suite_name)
        candidate_report = run_suite(runtime, suite)
    finally:
        runtime.close()

    save_report_and_record(
        candidate_report,
        candidate_report_path,
        report_kind=report_kind,
        label=report_label,
        source=report_source,
        metadata={"baseline_report_path": str(baseline_report_path.resolve())},
    )
    rollout_review = build_rollout_review(
        baseline_report,
        candidate_report,
        allow_suite_mismatch=allow_suite_mismatch,
        suite_aware_defaults=suite_aware_defaults,
    )
    backfill_path: Path | None = None
    if output_backfill is not None:
        backfill_path = save_incident_suggestions(rollout_review.candidate_incident_suggestions, output_backfill)
    return ShadowRunResult(
        suite_name=suite.name,
        baseline_report_path=baseline_report_path,
        candidate_report_path=candidate_report_path,
        rollout_review=rollout_review,
        backfill_path=backfill_path,
    )
