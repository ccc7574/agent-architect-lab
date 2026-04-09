from __future__ import annotations

from pathlib import Path

from agent_architect_lab.agent.planner import AgentPlanner
from agent_architect_lab.agent.runtime import AgentRuntime
from agent_architect_lab.evals.tasks import load_default_suite
from agent_architect_lab.harness.runner import run_suite
from agent_architect_lab.llm.base import PlannerProvider
from agent_architect_lab.models import PlannerDecision, Task


def test_runtime_can_summarize_file() -> None:
    runtime = AgentRuntime()
    try:
        trace = runtime.run(
            task=type("TaskObj", (), {"id": "task-1", "goal": "summarize 'pyproject.toml'"})()
        )
    finally:
        runtime.close()
    assert trace.status == "completed"
    assert "agent-architect-lab" in (trace.final_answer or "")


def test_default_eval_suite_runs_successfully() -> None:
    project_root = Path(__file__).resolve().parents[1]
    runtime = AgentRuntime()
    try:
        suite = load_default_suite(project_root)
        report = run_suite(runtime, suite)
    finally:
        runtime.close()
    assert len(report.results) == 4
    assert report.success_rate == 1.0
    assert report.average_score == 1.0
    assert report.failures_by_type == {}


def test_runtime_marks_missing_files_as_failed() -> None:
    runtime = AgentRuntime()
    try:
        trace = runtime.run(Task.create(goal="summarize 'missing.txt'"))
    finally:
        runtime.close()
    assert trace.status == "failed"
    assert trace.failure_type == "tool_execution_error"
    assert "No such file or directory" in (trace.final_answer or "")


class _InvalidToolPlanner(PlannerProvider):
    @property
    def name(self) -> str:
        return "invalid_tool_test"

    def decide(self, task: Task, trace, tools, memory_summary: str, selected_skills: list[str]) -> PlannerDecision:
        return PlannerDecision(
            action_type="tool",
            rationale="exercise invalid tool handling",
            tool_name="missing_tool",
            tool_arguments={},
        )


def test_runtime_handles_unknown_tools_without_crashing() -> None:
    runtime = AgentRuntime(planner=AgentPlanner(_InvalidToolPlanner()))
    try:
        trace = runtime.run(Task.create(goal="trigger invalid tool"))
    finally:
        runtime.close()
    assert trace.status == "failed"
    assert trace.failure_type == "planner_invalid_tool"
    assert "Unknown tool" in (trace.final_answer or "")


class _PlannerErrorPlanner(PlannerProvider):
    @property
    def name(self) -> str:
        return "planner_error_test"

    def decide(self, task: Task, trace, tools, memory_summary: str, selected_skills: list[str]) -> PlannerDecision:
        from agent_architect_lab.llm.base import PlannerError

        raise PlannerError("provider timeout", "planner_timeout")


def test_runtime_handles_planner_provider_failures() -> None:
    runtime = AgentRuntime(planner=AgentPlanner(_PlannerErrorPlanner()))
    try:
        trace = runtime.run(Task.create(goal="trigger planner error"))
    finally:
        runtime.close()
    assert trace.status == "failed"
    assert trace.failure_type == "planner_timeout"
    assert trace.steps[0].action_type == "planner_error"
