from __future__ import annotations

from agent_architect_lab.agent.runtime import AgentRuntime
from agent_architect_lab.models import Task


def test_runtime_uses_skill_routing_for_note_backed_retrieval() -> None:
    runtime = AgentRuntime()
    try:
        trace = runtime.run(Task.create(goal="memory retrieval system design"))
    finally:
        runtime.close()

    tool_names = [step.tool_call.name for step in trace.steps if step.tool_call]

    assert "memory_retrieval_designer" in trace.selected_skills
    assert tool_names == ["search_notes", "get_note"]
    assert trace.status == "completed"


def test_runtime_requires_approval_for_high_risk_production_actions() -> None:
    runtime = AgentRuntime()
    try:
        trace = runtime.run(Task.create(goal="delete production release artifacts for the latest deployment"))
    finally:
        runtime.close()

    assert trace.status == "completed"
    assert trace.selected_skills == ["operator_workflow_designer"]
    assert [step.action_type for step in trace.steps] == ["answer"]
    assert "Approval required" in (trace.final_answer or "")
