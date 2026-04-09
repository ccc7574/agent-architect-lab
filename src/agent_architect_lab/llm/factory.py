from __future__ import annotations

from agent_architect_lab.config import Settings
from agent_architect_lab.llm.base import PlannerProvider
from agent_architect_lab.llm.heuristic_provider import HeuristicPlanner
from agent_architect_lab.llm.openai_compatible_provider import OpenAICompatiblePlanner


def create_planner_provider(settings: Settings) -> PlannerProvider:
    if settings.planner_provider == "heuristic":
        return HeuristicPlanner()
    if settings.planner_provider == "openai_compatible":
        if not settings.planner_api_base:
            raise ValueError("AGENT_ARCHITECT_LAB_PLANNER_API_BASE is required for openai_compatible planner.")
        if not settings.planner_api_key:
            raise ValueError("AGENT_ARCHITECT_LAB_PLANNER_API_KEY is required for openai_compatible planner.")
        return OpenAICompatiblePlanner(
            api_base=settings.planner_api_base,
            api_key=settings.planner_api_key,
            model=settings.planner_model,
            timeout_s=settings.planner_timeout_s,
            max_retries=settings.planner_max_retries,
        )
    raise ValueError(f"Unknown planner provider '{settings.planner_provider}'.")
