from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from agent_architect_lab.harness.reporting import HarnessReport


@dataclass(slots=True)
class ReportComparison:
    baseline_suite: str
    candidate_suite: str
    success_rate_delta: float
    average_score_delta: float
    average_steps_delta: float
    failure_type_deltas: dict[str, int]
    track_success_rate_deltas: dict[str, float]
    regressions: list[str]

    def to_dict(self) -> dict:
        return {
            "baseline_suite": self.baseline_suite,
            "candidate_suite": self.candidate_suite,
            "success_rate_delta": self.success_rate_delta,
            "average_score_delta": self.average_score_delta,
            "average_steps_delta": self.average_steps_delta,
            "failure_type_deltas": self.failure_type_deltas,
            "track_success_rate_deltas": self.track_success_rate_deltas,
            "regressions": self.regressions,
        }


def compare_reports(baseline: HarnessReport, candidate: HarnessReport) -> ReportComparison:
    baseline_failures = Counter(baseline.failures_by_type)
    candidate_failures = Counter(candidate.failures_by_type)
    failure_type_deltas = {
        failure_type: candidate_failures.get(failure_type, 0) - baseline_failures.get(failure_type, 0)
        for failure_type in sorted(set(baseline_failures) | set(candidate_failures))
    }
    regressions = []
    track_success_rate_deltas: dict[str, float] = {}
    if baseline.suite_name == candidate.suite_name:
        baseline_tracks = baseline.results_by_track
        candidate_tracks = candidate.results_by_track
        track_success_rate_deltas = {
            track: candidate_tracks.get(track, {}).get("success_rate", 0.0) - baseline_tracks.get(track, {}).get("success_rate", 0.0)
            for track in sorted(set(baseline_tracks) | set(candidate_tracks))
        }
    else:
        regressions.append("suite_mismatch")
    if candidate.success_rate < baseline.success_rate:
        regressions.append("success_rate_decreased")
    if candidate.average_score < baseline.average_score:
        regressions.append("average_score_decreased")
    if candidate.average_steps > baseline.average_steps:
        regressions.append("average_steps_increased")
    regressions.extend(
        f"failure_type_increased:{failure_type}"
        for failure_type, delta in failure_type_deltas.items()
        if delta > 0
    )
    regressions.extend(
        f"track_regressed:{track}"
        for track, delta in track_success_rate_deltas.items()
        if delta < 0
    )
    return ReportComparison(
        baseline_suite=baseline.suite_name,
        candidate_suite=candidate.suite_name,
        success_rate_delta=candidate.success_rate - baseline.success_rate,
        average_score_delta=candidate.average_score - baseline.average_score,
        average_steps_delta=candidate.average_steps - baseline.average_steps,
        failure_type_deltas=failure_type_deltas,
        track_success_rate_deltas=track_success_rate_deltas,
        regressions=regressions,
    )
