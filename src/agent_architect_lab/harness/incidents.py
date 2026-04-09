from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from agent_architect_lab.harness.reporting import HarnessReport


FAILURE_TO_TRACK = {
    "planner_invalid_tool": "planner-reliability",
    "planner_invalid_response": "planner-reliability",
    "planner_http_error": "planner-reliability",
    "planner_network_error": "planner-reliability",
    "planner_timeout": "planner-reliability",
    "tool_execution_error": "tool-use",
    "tool_timeout": "tool-use",
    "safety_violation": "safety",
    "mcp_unavailable": "retrieval",
    "retrieval_miss": "retrieval",
    "trace_shape_mismatch": "workflow-shape",
    "approval_signal_missing": "approvals",
    "skill_routing_mismatch": "skills",
}

TRACK_TO_DATASET = {
    "approvals": "approval_tasks.jsonl",
    "incident-followup": "incident_backfill_tasks.jsonl",
    "planner-reliability": "planner_reliability_tasks.jsonl",
    "retrieval": "retrieval_tasks.jsonl",
    "safety": "safety_tasks.jsonl",
    "skills": "incident_backfill_tasks.jsonl",
    "tool-use": "incident_backfill_tasks.jsonl",
    "workflow-shape": "incident_backfill_tasks.jsonl",
}


@dataclass(slots=True)
class IncidentEvalSuggestion:
    task_id: str
    goal: str
    grader: dict
    metadata: dict
    source_run_id: str
    suggested_dataset: str
    template_notes: list[str]

    def to_jsonl_line(self) -> str:
        payload = {
            "id": self.task_id,
            "goal": self.goal,
            "grader": self.grader,
            "metadata": self.metadata,
        }
        return json.dumps(payload, ensure_ascii=True)


def _goal_for_failure(result) -> str:
    goal = result.metadata.get("task_goal") or result.metadata.get("goal")
    if goal:
        return str(goal)
    return f"follow up on failure type {result.failure_type or 'unknown'} from run {result.run_id}"


def _template_notes_for_failure(failure_type: str) -> list[str]:
    notes = [
        "Review the source trace before promoting this generated task into a permanent benchmark.",
        "Tighten the grader if the incident requires more than status and failure-type checks.",
    ]
    if failure_type.startswith("planner_"):
        notes.append("Prefer adding trace-shape or tool-argument validation checks for planner failures.")
    if failure_type == "safety_violation":
        notes.append("Consider whether this incident belongs in the safety suite or the approval simulation suite.")
    if failure_type in {"mcp_unavailable", "retrieval_miss"}:
        notes.append("Capture the expected retrieval path or note/tool usage in the grader.")
    return notes


def suggest_incident_evals(report: HarnessReport) -> list[IncidentEvalSuggestion]:
    suggestions: list[IncidentEvalSuggestion] = []
    for result in report.results:
        if result.success:
            continue
        failure_type = result.failure_type or "unspecified_failure"
        task_id = f"incident-{failure_type}-{result.task_id}"
        track = FAILURE_TO_TRACK.get(failure_type, "incident-followup")
        suggested_dataset = TRACK_TO_DATASET.get(track, "incident_backfill_tasks.jsonl")
        grader = {"type": "all", "checks": [{"type": "status", "equals": result.status}]}
        if result.failure_type:
            grader["checks"].append({"type": "failure_type", "equals": result.failure_type})
        suggestions.append(
            IncidentEvalSuggestion(
                task_id=task_id,
                goal=_goal_for_failure(result),
                grader=grader,
                metadata={
                    "track": track,
                    "source_task_id": result.task_id,
                    "source_run_id": result.run_id,
                    "incident_failure_type": failure_type,
                    "difficulty": result.metadata.get("difficulty", "unknown"),
                },
                source_run_id=result.run_id,
                suggested_dataset=suggested_dataset,
                template_notes=_template_notes_for_failure(failure_type),
            )
        )
    return suggestions


def save_incident_suggestions(suggestions: list[IncidentEvalSuggestion], path: Path) -> Path:
    lines = [suggestion.to_jsonl_line() for suggestion in suggestions]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return path
