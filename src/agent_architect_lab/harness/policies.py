from __future__ import annotations

from dataclasses import dataclass

from agent_architect_lab.harness.compare import ReportComparison
from agent_architect_lab.harness.reporting import HarnessReport


TRACK_TO_POLICY = {
    "approvals": "approval_policy",
    "approval-simulation": "approval_policy",
    "long-horizon": "long_horizon",
    "mcp-notes": "retrieval_grounding",
    "operations": "operator_workflows",
    "planner-reliability": "planner_reliability",
    "retrieval": "retrieval_grounding",
    "runtime-basics": "runtime_quality",
    "safety": "safety_policy",
    "sandbox": "safety_policy",
    "tool-use": "runtime_quality",
}

FAILURE_TO_POLICY = {
    "approval_signal_missing": "approval_policy",
    "mcp_unavailable": "retrieval_grounding",
    "planner_http_error": "planner_reliability",
    "planner_invalid_arguments": "planner_reliability",
    "planner_invalid_response": "planner_reliability",
    "planner_invalid_tool": "planner_reliability",
    "planner_network_error": "planner_reliability",
    "planner_timeout": "planner_reliability",
    "retrieval_miss": "retrieval_grounding",
    "safety_violation": "safety_policy",
    "skill_routing_mismatch": "retrieval_grounding",
    "tool_execution_error": "runtime_quality",
    "tool_timeout": "runtime_quality",
    "trace_shape_mismatch": "operator_workflows",
}


@dataclass(slots=True)
class PolicyFinding:
    policy: str
    severity: str
    evidence: list[str]
    recommendation: str

    def to_dict(self) -> dict:
        return {
            "policy": self.policy,
            "severity": self.severity,
            "evidence": self.evidence,
            "recommendation": self.recommendation,
        }


def summarize_policy_findings(candidate: HarnessReport, comparison: ReportComparison) -> list[PolicyFinding]:
    findings: dict[str, PolicyFinding] = {}

    for failure_type, count in candidate.failures_by_type.items():
        policy = FAILURE_TO_POLICY.get(failure_type, "general_release")
        finding = findings.setdefault(
            policy,
            PolicyFinding(
                policy=policy,
                severity="warning",
                evidence=[],
                recommendation=f"Review the {policy} release policy and add or tighten benchmark coverage.",
            ),
        )
        finding.evidence.append(f"failure_type:{failure_type}:{count}")
        finding.severity = "blocker"

    for track, delta in comparison.track_success_rate_deltas.items():
        if delta >= 0:
            continue
        policy = TRACK_TO_POLICY.get(track, "general_release")
        finding = findings.setdefault(
            policy,
            PolicyFinding(
                policy=policy,
                severity="warning",
                evidence=[],
                recommendation=f"Inspect regressions in the {track} track and confirm the release policy still holds.",
            ),
        )
        finding.evidence.append(f"track_regressed:{track}:{delta:.3f}")

    for issue in comparison.regressions:
        if issue == "average_steps_increased":
            policy = "runtime_efficiency"
            finding = findings.setdefault(
                policy,
                PolicyFinding(
                    policy=policy,
                    severity="warning",
                    evidence=[],
                    recommendation="Inspect planner efficiency and step budgets before promotion.",
                ),
            )
            finding.evidence.append(issue)

    return sorted(findings.values(), key=lambda item: (item.severity != "blocker", item.policy))
