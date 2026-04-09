from __future__ import annotations

from dataclasses import dataclass, field

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


@dataclass(slots=True)
class RolloutReview:
    promotion: PromotionResult
    candidate_incident_suggestions: list[IncidentEvalSuggestion]
    policy_findings: list[PolicyFinding]
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
            "candidate_incident_suggestions": [
                {
                    "task_id": suggestion.task_id,
                    "goal": suggestion.goal,
                    "grader": suggestion.grader,
                    "metadata": suggestion.metadata,
                    "source_run_id": suggestion.source_run_id,
                    "suggested_dataset": suggestion.suggested_dataset,
                    "template_notes": suggestion.template_notes,
                }
                for suggestion in self.candidate_incident_suggestions
            ],
        }


def build_rollout_review(
    baseline: HarnessReport,
    candidate: HarnessReport,
    *,
    allow_suite_mismatch: bool = False,
    suite_aware_defaults: bool = False,
) -> RolloutReview:
    promotion = evaluate_promotion(
        baseline,
        candidate,
        allow_suite_mismatch=allow_suite_mismatch,
        suite_aware_defaults=suite_aware_defaults,
    )
    blocker_explanations = [_explain_issue(issue) for issue in promotion.blockers]
    warning_explanations = [_explain_issue(issue) for issue in promotion.warnings]
    candidate_incident_suggestions = suggest_incident_evals(candidate)
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
        blocker_explanations=blocker_explanations,
        warning_explanations=warning_explanations,
        summary=summary,
    )
