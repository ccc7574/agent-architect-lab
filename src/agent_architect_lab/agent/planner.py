from __future__ import annotations

from agent_architect_lab.llm.base import PlannerProvider
from agent_architect_lab.models import PlannerDecision, RunTrace, Task, ToolSpec


class AgentPlanner:
    def __init__(self, provider: PlannerProvider) -> None:
        self.provider = provider

    def decide(
        self,
        task: Task,
        trace: RunTrace,
        tools: list[ToolSpec],
        memory_summary: str,
        selected_skills: list[str],
    ) -> PlannerDecision:
        return self.provider.decide(
            task=task,
            trace=trace,
            tools=tools,
            memory_summary=memory_summary,
            selected_skills=selected_skills,
        )
