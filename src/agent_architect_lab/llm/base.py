from __future__ import annotations

from abc import ABC, abstractmethod

from agent_architect_lab.models import PlannerDecision, RunTrace, Task, ToolSpec


class PlannerError(RuntimeError):
    def __init__(self, message: str, error_code: str = "planner_provider_error") -> None:
        super().__init__(message)
        self.error_code = error_code


class PlannerProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def decide(
        self,
        task: Task,
        trace: RunTrace,
        tools: list[ToolSpec],
        memory_summary: str,
        selected_skills: list[str],
    ) -> PlannerDecision:
        raise NotImplementedError
