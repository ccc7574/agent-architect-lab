from __future__ import annotations

from dataclasses import dataclass

from agent_architect_lab.models import Task


@dataclass(frozen=True, slots=True)
class AgentPattern:
    name: str
    when_to_use: str
    strengths: str
    risks: str


PATTERNS = {
    "single_agent": AgentPattern(
        name="single_agent",
        when_to_use="Short tasks, low coordination overhead, fast iteration.",
        strengths="Simple control flow, easier tracing, lowest operating complexity.",
        risks="Planner overload and weaker decomposition on broad tasks.",
    ),
    "planner_executor": AgentPattern(
        name="planner_executor",
        when_to_use="Tasks need decomposition, checkpoints, or different execution policies.",
        strengths="Separates strategy from action; better for long-horizon work.",
        risks="Plan drift and coordination latency if plan updates are weak.",
    ),
    "evaluator_optimizer": AgentPattern(
        name="evaluator_optimizer",
        when_to_use="Quality matters more than speed and outputs can be graded.",
        strengths="Fits enterprise review loops and regression protection.",
        risks="Higher cost and slow feedback cycles.",
    ),
    "multi_agent": AgentPattern(
        name="multi_agent",
        when_to_use="Distinct roles have disjoint context or ownership boundaries.",
        strengths="Parallelism and specialization for bounded subproblems.",
        risks="Coordination bugs, duplicated work, and higher infra complexity.",
    ),
}


def recommend_pattern(task: Task) -> AgentPattern:
    goal = task.goal.lower()
    if any(term in goal for term in ("review", "grade", "evaluate", "compare")):
        return PATTERNS["evaluator_optimizer"]
    if any(term in goal for term in ("parallel", "multiple", "cluster", "several")):
        return PATTERNS["multi_agent"]
    if any(term in goal for term in ("plan", "roadmap", "long", "multi-step", "workflow")):
        return PATTERNS["planner_executor"]
    return PATTERNS["single_agent"]

