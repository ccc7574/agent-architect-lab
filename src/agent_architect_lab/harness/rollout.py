from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_architect_lab.harness.feedback import build_related_feedback
from agent_architect_lab.harness.incidents import IncidentEvalSuggestion, suggest_incident_evals
from agent_architect_lab.harness.policies import PolicyFinding, summarize_policy_findings
from agent_architect_lab.harness.promotion import PromotionResult, evaluate_promotion
from agent_architect_lab.harness.reporting import HarnessReport


EXPLANATIONS = {
    "suite_mismatch": "Baseline and candidate reports are from different suites, so the promotion comparison is not directly valid.",
    "success_rate_decreased": "The candidate passes fewer tasks than the baseline.",
    "average_score_decreased": "The candidate quality score dropped against the baseline.",
    "average_steps_increased": "The candidate needs more steps on average, which may indicate less efficient planning.",
}


def _explain_issue(issue: str) -> str:
    if issue in EXPLANATIONS:
        return EXPLANATIONS[issue]
    if issue.startswith("failure_type_increased:"):
        failure_type = issue.split(":", 1)[1]
        return f"The candidate increased failures of type '{failure_type}'."
    if issue.startswith("track_regressed:"):
        track = issue.split(":", 1)[1]
        return f"The candidate regressed on the '{track}' capability track."
    if issue.startswith("success_rate_below_threshold:"):
        return "The candidate is below the required success-rate gate."
    if issue.startswith("average_score_below_threshold:"):
        return "The candidate is below the required average-score gate."
    if issue.startswith("average_steps_above_threshold:"):
        return "The candidate exceeds the allowed step budget."
    if issue.startswith("blocked_failure_type_present:"):
        return "The candidate contains a blocked failure type that is not allowed for promotion."
    return issue


def _summarize_related_feedback(rows: list[dict[str, Any]]) -> dict[str, Any]:
    sentiment_counts = Counter(str(row.get("sentiment", "")) for row in rows if row.get("sentiment"))
    actionability_counts = Counter(str(row.get("actionability", "")) for row in rows if row.get("actionability"))
    label_counts = Counter(
        str(label)
        for row in rows
        for label in row.get("labels", [])
        if isinstance(label, str) and label
    )
    return {
        "matched_feedback_count": len(rows),
        "negative_feedback_count": sentiment_counts.get("negative", 0),
        "positive_feedback_count": sentiment_counts.get("positive", 0),
        "urgent_feedback_count": actionability_counts.get("urgent_followup", 0),
        "followup_feedback_count": actionability_counts.get("followup_required", 0),
        "top_labels": [
            {"label": label, "count": count}
            for label, count in sorted(label_counts.items(), key=lambda item: (-item[1], item[0]))[:5]
        ],
    }


@dataclass(slots=True)
class RolloutReview:
    promotion: PromotionResult
    candidate_incident_suggestions: list[IncidentEvalSuggestion]
    policy_findings: list[PolicyFinding]
    related_feedback: list[dict[str, Any]] = field(default_factory=list)
    feedback_summary: dict[str, Any] = field(default_factory=dict)
    blocker_explanations: list[str] = field(default_factory=list)
    warning_explanations: list[str] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict:
        return {
            "summary": self.summary,
            "promotion": self.promotion.to_dict(),
            "blocker_explanations": self.blocker_explanations,
            "warning_explanations": self.warning_explanations,
            "policy_findings": [finding.to_dict() for finding in self.policy_findings],
            "feedback_summary": self.feedback_summary,
            "related_feedback": self.related_feedback,
            "candidate_incident_suggestions": [suggestion.to_dict() for suggestion in self.candidate_incident_suggestions],
        }


def build_rollout_review(
    baseline: HarnessReport,
    candidate: HarnessReport,
    *,
    allow_suite_mismatch: bool = False,
    suite_aware_defaults: bool = False,
    feedback_ledger_path: Path | None = None,
    candidate_report_path: Path | None = None,
    release_name: str | None = None,
    incident_id: str | None = None,
) -> RolloutReview:
    promotion = evaluate_promotion(
        baseline,
        candidate,
        allow_suite_mismatch=allow_suite_mismatch,
        suite_aware_defaults=suite_aware_defaults,
    )
    blocker_explanations = [_explain_issue(issue) for issue in promotion.blockers]
    warning_explanations = [_explain_issue(issue) for issue in promotion.warnings]
    normalized_report_path = str(candidate_report_path.resolve()) if candidate_report_path is not None else None
    related_feedback: list[dict[str, Any]] = []
    if feedback_ledger_path is not None:
        related_feedback = build_related_feedback(
            ledger_path=feedback_ledger_path,
            release_name=release_name,
            incident_ids=[incident_id] if incident_id else None,
            run_ids=[result.run_id for result in candidate.results if result.run_id],
            report_paths=[normalized_report_path] if normalized_report_path else None,
            limit=20,
        )
    feedback_summary = _summarize_related_feedback(related_feedback)
    candidate_incident_suggestions = suggest_incident_evals(
        candidate,
        feedback_ledger_path=feedback_ledger_path,
        release_name=release_name,
        incident_id=incident_id,
        report_path=normalized_report_path,
    )
    policy_findings = summarize_policy_findings(candidate, promotion.comparison)
    if promotion.passed:
        summary = "Candidate is promotable."
        if promotion.warnings:
            summary = "Candidate is promotable with review."
    else:
        summary = "Candidate should be held pending blocker resolution."
    return RolloutReview(
        promotion=promotion,
        candidate_incident_suggestions=candidate_incident_suggestions,
        policy_findings=policy_findings,
        related_feedback=related_feedback,
        feedback_summary=feedback_summary,
        blocker_explanations=blocker_explanations,
        warning_explanations=warning_explanations,
        summary=summary,
    )
