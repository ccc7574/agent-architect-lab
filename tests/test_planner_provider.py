from __future__ import annotations

from agent_architect_lab.config import load_settings
from agent_architect_lab.harness.grading import grade_trace_from_grader
from agent_architect_lab.llm.base import PlannerError
from agent_architect_lab.llm.factory import create_planner_provider
from agent_architect_lab.llm.openai_compatible_provider import _coerce_decision, _validate_decision, OpenAICompatiblePlanner
from agent_architect_lab.models import PlannerDecision, RunTrace, StepTrace, Task, ToolSpec


def test_factory_defaults_to_heuristic(monkeypatch) -> None:
    monkeypatch.delenv("AGENT_ARCHITECT_LAB_PLANNER_PROVIDER", raising=False)
    settings = load_settings()

    provider = create_planner_provider(settings)

    assert provider.name == "heuristic"


def test_factory_builds_openai_compatible_provider(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_PLANNER_PROVIDER", "openai_compatible")
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_PLANNER_API_BASE", "https://example.invalid/v1")
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_PLANNER_API_KEY", "test-key")
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_PLANNER_MODEL", "test-model")
    settings = load_settings()

    provider = create_planner_provider(settings)

    assert provider.name == "openai_compatible"
    assert provider.model == "test-model"


def test_factory_requires_credentials_for_openai_compatible(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_ARCHITECT_LAB_PLANNER_PROVIDER", "openai_compatible")
    monkeypatch.delenv("AGENT_ARCHITECT_LAB_PLANNER_API_BASE", raising=False)
    monkeypatch.delenv("AGENT_ARCHITECT_LAB_PLANNER_API_KEY", raising=False)

    settings = load_settings()

    try:
        create_planner_provider(settings)
    except ValueError as exc:
        assert "API_BASE" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("Expected missing credential validation.")


def test_openai_compatible_response_is_coerced_to_planner_decision() -> None:
    decision = _coerce_decision(
        {
            "action_type": "tool",
            "rationale": "Need to read the file.",
            "tool_name": "read_file",
            "tool_arguments": {"path": "README.md"},
        }
    )

    assert isinstance(decision, PlannerDecision)
    assert decision.tool_name == "read_file"


def test_openai_compatible_validation_rejects_unknown_tools() -> None:
    decision = PlannerDecision(
        action_type="tool",
        rationale="use unknown tool",
        tool_name="missing_tool",
        tool_arguments={},
    )

    try:
        _validate_decision(decision, [ToolSpec(name="read_file", description="Read", input_schema={})])
    except PlannerError as exc:
        assert exc.error_code == "planner_invalid_tool"
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("Expected planner tool validation to fail.")


def test_openai_compatible_validation_rejects_invalid_tool_arguments() -> None:
    decision = PlannerDecision(
        action_type="tool",
        rationale="bad args",
        tool_name="read_file",
        tool_arguments={"path": 123},
    )

    try:
        _validate_decision(
            decision,
            [
                ToolSpec(
                    name="read_file",
                    description="Read",
                    input_schema={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
                )
            ],
        )
    except PlannerError as exc:
        assert exc.error_code == "planner_invalid_arguments"
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("Expected planner argument validation to fail.")


def test_openai_compatible_planner_retries_transient_failures() -> None:
    planner = OpenAICompatiblePlanner(
        api_base="https://example.invalid/v1",
        api_key="test",
        model="demo",
        max_retries=1,
    )
    calls = {"count": 0}

    def fake_post(_body: bytes) -> dict:
        calls["count"] += 1
        if calls["count"] == 1:
            raise PlannerError("temporary network issue", "planner_network_error")
        return {"choices": [{"message": {"content": '{"action_type":"answer","rationale":"done","final_answer":"ok"}'}}]}

    planner._post = fake_post  # type: ignore[method-assign]

    decision = planner.decide(
        Task.create(goal="demo"),
        RunTrace.start(Task.create(goal="demo")),
        [ToolSpec(name="read_file", description="Read", input_schema={})],
        "",
        [],
    )

    assert decision.final_answer == "ok"
    assert calls["count"] == 2


def test_grader_supports_step_sequence_selected_skills_and_approval_signal() -> None:
    trace = RunTrace.start(
        Task.create(goal="delete production release artifacts"),
        selected_skills=["operator_workflow_designer"],
        planner_provider="heuristic",
    )
    trace.steps.append(
        StepTrace(
            index=0,
            rationale="Require approval",
            action_type="answer",
            tool_call=None,
            observation="Approval required before executing this action. Escalate to a human operator.",
        )
    )
    trace.close(status="completed", final_answer=trace.steps[0].observation)

    outcome = grade_trace_from_grader(
        trace,
        {
            "type": "all",
            "checks": [
                {"type": "step_sequence", "expected": ["answer"]},
                {"type": "selected_skills", "expected": ["operator_workflow_designer"]},
                {"type": "approval_signal"},
            ],
        },
    )

    assert outcome.success is True
