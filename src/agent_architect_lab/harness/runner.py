from __future__ import annotations

from agent_architect_lab.agent.runtime import AgentRuntime
from agent_architect_lab.harness.grading import grade_trace
from agent_architect_lab.harness.reporting import HarnessReport
from agent_architect_lab.harness.suite import ExperimentSuite
from agent_architect_lab.models import EvalResult


def run_suite(runtime: AgentRuntime, suite: ExperimentSuite) -> HarnessReport:
    results: list[EvalResult] = []
    for task in suite.tasks:
        trace = runtime.run(task)
        grade = grade_trace(task, trace)
        failure = grade.failure_type or trace.failure_type
        results.append(
            EvalResult(
                task_id=task.id,
                success=grade.success,
                score=grade.score,
                steps=len(trace.steps),
                status=trace.status,
                failure_type=failure,
                final_answer=trace.final_answer or "",
                run_id=trace.run_id,
                metadata={**task.metadata, "goal": task.goal},
                details=grade.details,
            )
        )
    return HarnessReport(suite_name=suite.name, results=results)
