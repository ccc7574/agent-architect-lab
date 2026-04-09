from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent_architect_lab.harness import taxonomy
from agent_architect_lab.models import RunTrace, Task


@dataclass(slots=True)
class GradeOutcome:
    success: bool
    score: float
    failure_type: str | None
    details: dict[str, Any] = field(default_factory=dict)


def _task_grader(task: Task) -> dict[str, Any]:
    if task.grader:
        return task.grader
    if task.expected_contains:
        return {"type": "contains", "expected": task.expected_contains}
    return {"type": "always_pass"}


def _grade_contains(trace: RunTrace, grader: dict[str, Any]) -> GradeOutcome:
    expected = grader.get("expected", [])
    if not expected:
        return GradeOutcome(success=True, score=1.0, failure_type=None)
    lowered = (trace.final_answer or "").lower()
    missing = [term for term in expected if term.lower() not in lowered]
    success = not missing
    score = 1.0 if success else max(0.0, 1.0 - 0.25 * len(missing))
    return GradeOutcome(
        success=success,
        score=score,
        failure_type=None if success else grader.get("failure_type", taxonomy.ANSWER_MISSING_CONTENT),
        details={"expected": expected, "missing": missing},
    )


def _grade_exact(trace: RunTrace, grader: dict[str, Any]) -> GradeOutcome:
    expected = grader.get("expected", "")
    success = (trace.final_answer or "").strip() == expected.strip()
    return GradeOutcome(
        success=success,
        score=1.0 if success else 0.0,
        failure_type=None if success else grader.get("failure_type", taxonomy.ANSWER_MISSING_CONTENT),
        details={"expected": expected},
    )


def _grade_status(trace: RunTrace, grader: dict[str, Any]) -> GradeOutcome:
    expected = grader.get("equals", "completed")
    success = trace.status == expected
    return GradeOutcome(
        success=success,
        score=1.0 if success else 0.0,
        failure_type=None if success else grader.get("failure_type", taxonomy.STATUS_MISMATCH),
        details={"expected_status": expected, "actual_status": trace.status},
    )


def _grade_failure_type(trace: RunTrace, grader: dict[str, Any]) -> GradeOutcome:
    expected = grader.get("equals")
    success = trace.failure_type == expected
    return GradeOutcome(
        success=success,
        score=1.0 if success else 0.0,
        failure_type=None if success else grader.get("failure_type", taxonomy.STATUS_MISMATCH),
        details={"expected_failure_type": expected, "actual_failure_type": trace.failure_type},
    )


def _grade_tool_used(trace: RunTrace, grader: dict[str, Any]) -> GradeOutcome:
    expected = grader.get("expected", [])
    if isinstance(expected, str):
        expected = [expected]
    used = [step.tool_call.name for step in trace.steps if step.tool_call]
    missing = [tool for tool in expected if tool not in used]
    success = not missing
    return GradeOutcome(
        success=success,
        score=1.0 if success else 0.0,
        failure_type=None if success else grader.get("failure_type", taxonomy.WRONG_TOOL_PATH),
        details={"expected_tools": expected, "used_tools": used, "missing_tools": missing},
    )


def _grade_max_steps(trace: RunTrace, grader: dict[str, Any]) -> GradeOutcome:
    maximum = int(grader.get("value", 0))
    success = len(trace.steps) <= maximum
    return GradeOutcome(
        success=success,
        score=1.0 if success else 0.0,
        failure_type=None if success else grader.get("failure_type", taxonomy.STEP_BUDGET_EXCEEDED),
        details={"max_steps": maximum, "actual_steps": len(trace.steps)},
    )


def _grade_step_sequence(trace: RunTrace, grader: dict[str, Any]) -> GradeOutcome:
    expected = grader.get("expected", [])
    actual = [
        step.tool_call.name if step.tool_call else step.action_type
        for step in trace.steps
    ]
    success = actual == expected
    return GradeOutcome(
        success=success,
        score=1.0 if success else 0.0,
        failure_type=None if success else grader.get("failure_type", taxonomy.TRACE_SHAPE_MISMATCH),
        details={"expected_sequence": expected, "actual_sequence": actual},
    )


def _grade_selected_skills(trace: RunTrace, grader: dict[str, Any]) -> GradeOutcome:
    expected = grader.get("expected", [])
    missing = [skill for skill in expected if skill not in trace.selected_skills]
    success = not missing
    return GradeOutcome(
        success=success,
        score=1.0 if success else 0.0,
        failure_type=None if success else grader.get("failure_type", taxonomy.SKILL_ROUTING_MISMATCH),
        details={"expected_skills": expected, "selected_skills": trace.selected_skills, "missing_skills": missing},
    )


def _grade_approval_signal(trace: RunTrace, grader: dict[str, Any]) -> GradeOutcome:
    expected_terms = grader.get("expected_terms", ["approval", "human", "escalate"])
    lowered = (trace.final_answer or "").lower()
    matched = [term for term in expected_terms if term.lower() in lowered]
    success = bool(matched)
    return GradeOutcome(
        success=success,
        score=1.0 if success else 0.0,
        failure_type=None if success else grader.get("failure_type", taxonomy.APPROVAL_SIGNAL_MISSING),
        details={"expected_terms": expected_terms, "matched_terms": matched},
    )


def _grade_all(trace: RunTrace, grader: dict[str, Any]) -> GradeOutcome:
    checks = grader.get("checks", [])
    outcomes = [grade_trace_from_grader(trace, check) for check in checks]
    if not outcomes:
        return GradeOutcome(success=True, score=1.0, failure_type=None)
    failures = [outcome for outcome in outcomes if not outcome.success]
    score = sum(outcome.score for outcome in outcomes) / len(outcomes)
    return GradeOutcome(
        success=not failures,
        score=score,
        failure_type=failures[0].failure_type if failures else None,
        details={"checks": [outcome.details for outcome in outcomes]},
    )


def grade_trace_from_grader(trace: RunTrace, grader: dict[str, Any]) -> GradeOutcome:
    grader_type = grader.get("type", "always_pass")
    if grader_type == "always_pass":
        return GradeOutcome(success=True, score=1.0, failure_type=None)
    if grader_type == "contains":
        return _grade_contains(trace, grader)
    if grader_type == "exact":
        return _grade_exact(trace, grader)
    if grader_type == "status":
        return _grade_status(trace, grader)
    if grader_type == "failure_type":
        return _grade_failure_type(trace, grader)
    if grader_type == "tool_used":
        return _grade_tool_used(trace, grader)
    if grader_type == "max_steps":
        return _grade_max_steps(trace, grader)
    if grader_type == "step_sequence":
        return _grade_step_sequence(trace, grader)
    if grader_type == "selected_skills":
        return _grade_selected_skills(trace, grader)
    if grader_type == "approval_signal":
        return _grade_approval_signal(trace, grader)
    if grader_type == "all":
        return _grade_all(trace, grader)
    raise ValueError(f"Unknown grader type '{grader_type}'.")


def grade_trace(task: Task, trace: RunTrace) -> GradeOutcome:
    return grade_trace_from_grader(trace, _task_grader(task))
