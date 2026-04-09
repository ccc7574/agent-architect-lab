from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(slots=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Task:
    id: str
    goal: str
    constraints: list[str] = field(default_factory=list)
    expected_contains: list[str] = field(default_factory=list)
    grader: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(cls, goal: str, **kwargs: Any) -> "Task":
        return cls(id=f"task-{uuid4().hex[:8]}", goal=goal, **kwargs)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]
    result: dict[str, Any]
    latency_ms: int
    error: str | None = None
    error_code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class StepTrace:
    index: int
    rationale: str
    action_type: str
    tool_call: ToolCall | None
    observation: str
    failure_type: str | None = None
    timestamp: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.tool_call is None:
            payload["tool_call"] = None
        return payload


@dataclass(slots=True)
class RunTrace:
    run_id: str
    task_id: str
    task_goal: str
    planner_provider: str | None = None
    selected_skills: list[str] = field(default_factory=list)
    status: str = "running"
    final_answer: str | None = None
    failure_type: str | None = None
    steps: list[StepTrace] = field(default_factory=list)
    started_at: str = field(default_factory=utc_now_iso)
    ended_at: str | None = None

    @classmethod
    def start(
        cls,
        task: Task,
        selected_skills: list[str] | None = None,
        planner_provider: str | None = None,
    ) -> "RunTrace":
        return cls(
            run_id=f"run-{uuid4().hex[:10]}",
            task_id=task.id,
            task_goal=task.goal,
            planner_provider=planner_provider,
            selected_skills=selected_skills or [],
        )

    def close(self, status: str, final_answer: str, failure_type: str | None = None) -> None:
        self.status = status
        self.final_answer = final_answer
        self.failure_type = failure_type
        self.ended_at = utc_now_iso()

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "task_id": self.task_id,
            "task_goal": self.task_goal,
            "planner_provider": self.planner_provider,
            "selected_skills": self.selected_skills,
            "status": self.status,
            "final_answer": self.final_answer,
            "failure_type": self.failure_type,
            "steps": [step.to_dict() for step in self.steps],
            "started_at": self.started_at,
            "ended_at": self.ended_at,
        }


@dataclass(slots=True)
class PlannerDecision:
    action_type: str
    rationale: str
    tool_name: str | None = None
    tool_arguments: dict[str, Any] = field(default_factory=dict)
    final_answer: str | None = None


@dataclass(slots=True)
class EvalResult:
    task_id: str
    success: bool
    score: float
    steps: int
    status: str
    failure_type: str | None
    final_answer: str
    run_id: str
    metadata: dict[str, Any] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
