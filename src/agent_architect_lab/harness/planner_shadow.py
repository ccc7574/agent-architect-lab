from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_architect_lab.agent.memory import MemoryManager
from agent_architect_lab.config import Settings, load_settings
from agent_architect_lab.evals.tasks import load_suite
from agent_architect_lab.harness.suite import ExperimentSuite
from agent_architect_lab.llm.base import PlannerError, PlannerProvider
from agent_architect_lab.llm.heuristic_provider import HeuristicPlanner
from agent_architect_lab.mcp.tool_adapter import MCPToolAdapter
from agent_architect_lab.models import PlannerDecision, RunTrace, Task, utc_now_iso
from agent_architect_lab.skills.router import SkillRouter
from agent_architect_lab.tools.registry import ToolRegistry


@dataclass(slots=True)
class PlannerShadowPolicy:
    allowed_actions: list[str] = field(default_factory=list)
    allowed_tools: list[str] = field(default_factory=list)
    blocked_tools: list[str] = field(default_factory=list)
    required_skills: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed_actions": self.allowed_actions,
            "allowed_tools": self.allowed_tools,
            "blocked_tools": self.blocked_tools,
            "required_skills": self.required_skills,
        }


@dataclass(slots=True)
class PlannerDecisionSnapshot:
    action_type: str | None
    rationale: str
    tool_name: str | None = None
    tool_arguments: dict[str, Any] = field(default_factory=dict)
    final_answer: str | None = None
    error_code: str | None = None
    error: str | None = None

    @classmethod
    def from_decision(cls, decision: PlannerDecision) -> "PlannerDecisionSnapshot":
        return cls(
            action_type=decision.action_type,
            rationale=decision.rationale,
            tool_name=decision.tool_name,
            tool_arguments=dict(decision.tool_arguments),
            final_answer=decision.final_answer,
        )

    @classmethod
    def from_error(cls, exc: PlannerError) -> "PlannerDecisionSnapshot":
        return cls(
            action_type=None,
            rationale="Planner failed before a decision was produced.",
            error_code=exc.error_code,
            error=str(exc),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_type": self.action_type,
            "rationale": self.rationale,
            "tool_name": self.tool_name,
            "tool_arguments": self.tool_arguments,
            "final_answer": self.final_answer,
            "error_code": self.error_code,
            "error": self.error,
        }


@dataclass(slots=True)
class PlannerShadowTaskResult:
    task_id: str
    goal: str
    selected_skills: list[str]
    policy: PlannerShadowPolicy
    baseline_decision: PlannerDecisionSnapshot
    candidate_decision: PlannerDecisionSnapshot
    policy_passed: bool
    action_match: bool
    tool_match: bool
    violations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "goal": self.goal,
            "selected_skills": self.selected_skills,
            "policy": self.policy.to_dict(),
            "baseline_decision": self.baseline_decision.to_dict(),
            "candidate_decision": self.candidate_decision.to_dict(),
            "policy_passed": self.policy_passed,
            "action_match": self.action_match,
            "tool_match": self.tool_match,
            "violations": self.violations,
        }


@dataclass(slots=True)
class PlannerShadowReport:
    suite_name: str
    created_at: str
    candidate_provider: str
    baseline_provider: str
    results: list[PlannerShadowTaskResult]
    global_policy: PlannerShadowPolicy = field(default_factory=PlannerShadowPolicy)

    @property
    def task_count(self) -> int:
        return len(self.results)

    @property
    def passed_tasks(self) -> int:
        return sum(1 for result in self.results if result.policy_passed)

    @property
    def policy_pass_rate(self) -> float:
        if not self.results:
            return 0.0
        return self.passed_tasks / len(self.results)

    @property
    def action_match_rate(self) -> float:
        if not self.results:
            return 0.0
        return sum(1 for result in self.results if result.action_match) / len(self.results)

    @property
    def tool_match_rate(self) -> float:
        if not self.results:
            return 0.0
        return sum(1 for result in self.results if result.tool_match) / len(self.results)

    @property
    def violations_by_type(self) -> dict[str, int]:
        return dict(Counter(violation for result in self.results for violation in result.violations))

    @property
    def planner_errors_by_type(self) -> dict[str, int]:
        counter = Counter(
            result.candidate_decision.error_code
            for result in self.results
            if result.candidate_decision.error_code
        )
        return {str(key): value for key, value in counter.items()}

    @property
    def all_passed(self) -> bool:
        return self.passed_tasks == self.task_count

    def to_dict(self) -> dict[str, Any]:
        return {
            "suite_name": self.suite_name,
            "created_at": self.created_at,
            "candidate_provider": self.candidate_provider,
            "baseline_provider": self.baseline_provider,
            "task_count": self.task_count,
            "passed_tasks": self.passed_tasks,
            "policy_pass_rate": self.policy_pass_rate,
            "action_match_rate": self.action_match_rate,
            "tool_match_rate": self.tool_match_rate,
            "violations_by_type": self.violations_by_type,
            "planner_errors_by_type": self.planner_errors_by_type,
            "all_passed": self.all_passed,
            "global_policy": self.global_policy.to_dict(),
            "results": [result.to_dict() for result in self.results],
        }

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")


def render_planner_shadow_markdown(report: PlannerShadowReport, *, title: str = "Planner Shadow Report") -> str:
    lines = [
        f"# {title}",
        "",
        f"- Suite: `{report.suite_name}`",
        f"- Candidate provider: `{report.candidate_provider}`",
        f"- Baseline provider: `{report.baseline_provider}`",
        f"- Generated at: `{report.created_at}`",
        f"- Policy pass rate: `{report.passed_tasks}/{report.task_count}`",
        f"- Action match rate: `{report.action_match_rate:.2f}`",
        f"- Tool match rate: `{report.tool_match_rate:.2f}`",
    ]
    if report.global_policy.allowed_tools or report.global_policy.blocked_tools:
        lines.extend(
            [
                "",
                "## Global Policy",
                "",
                f"- Allowed tools: {', '.join(report.global_policy.allowed_tools) or 'any'}",
                f"- Blocked tools: {', '.join(report.global_policy.blocked_tools) or 'none'}",
            ]
        )
    if report.violations_by_type or report.planner_errors_by_type:
        lines.extend(["", "## Summary", ""])
        if report.violations_by_type:
            for violation, count in sorted(report.violations_by_type.items()):
                lines.append(f"- `{violation}`: {count}")
        if report.planner_errors_by_type:
            for error_code, count in sorted(report.planner_errors_by_type.items()):
                lines.append(f"- planner error `{error_code}`: {count}")
    lines.extend(["", "## Tasks", ""])
    for result in report.results:
        lines.extend(
            [
                f"### {result.task_id}",
                "",
                f"- Goal: {result.goal}",
                f"- Selected skills: {', '.join(result.selected_skills) or 'none'}",
                f"- Policy passed: `{'yes' if result.policy_passed else 'no'}`",
                f"- Baseline action: `{result.baseline_decision.action_type or 'error'}`",
                f"- Candidate action: `{result.candidate_decision.action_type or 'error'}`",
                f"- Baseline tool: `{result.baseline_decision.tool_name or 'none'}`",
                f"- Candidate tool: `{result.candidate_decision.tool_name or 'none'}`",
            ]
        )
        if result.violations:
            lines.append(f"- Violations: {', '.join(result.violations)}")
        if result.candidate_decision.error_code:
            lines.append(f"- Candidate planner error: `{result.candidate_decision.error_code}`")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def export_planner_shadow_markdown(
    report: PlannerShadowReport,
    *,
    output: str = "",
    title: str = "Planner Shadow Report",
) -> Path:
    settings = load_settings()
    output_path = Path(output) if output else settings.reports_dir / "planner-shadow.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_planner_shadow_markdown(report, title=title), encoding="utf-8")
    return output_path


def run_planner_shadow_suite(
    suite_name: str,
    candidate_provider: PlannerProvider,
    *,
    baseline_provider: PlannerProvider | None = None,
    allowed_tools: list[str] | None = None,
    blocked_tools: list[str] | None = None,
    settings: Settings | None = None,
) -> PlannerShadowReport:
    resolved_settings = settings or load_settings()
    suite = load_suite(resolved_settings.project_root, suite_name)
    return run_planner_shadow_experiment(
        suite,
        candidate_provider,
        baseline_provider=baseline_provider,
        allowed_tools=allowed_tools,
        blocked_tools=blocked_tools,
        settings=resolved_settings,
    )


def run_planner_shadow_experiment(
    suite: ExperimentSuite,
    candidate_provider: PlannerProvider,
    *,
    baseline_provider: PlannerProvider | None = None,
    allowed_tools: list[str] | None = None,
    blocked_tools: list[str] | None = None,
    settings: Settings | None = None,
) -> PlannerShadowReport:
    resolved_settings = settings or load_settings()
    baseline = baseline_provider or HeuristicPlanner()
    global_policy = PlannerShadowPolicy(
        allowed_tools=_normalize_string_list(allowed_tools),
        blocked_tools=_normalize_string_list(blocked_tools),
    )
    registry = _build_registry(resolved_settings)
    skill_router = SkillRouter(resolved_settings.skills_dir)
    memory = MemoryManager()
    results: list[PlannerShadowTaskResult] = []
    try:
        tool_specs = registry.specs()
        for task in suite.tasks:
            selected_skills = skill_router.select(task.goal)
            baseline_decision = _shadow_decision(baseline, task, tool_specs, selected_skills, memory)
            candidate_decision = _shadow_decision(candidate_provider, task, tool_specs, selected_skills, memory)
            policy = _task_policy(task, global_policy)
            violations = _evaluate_policy(policy, candidate_decision, selected_skills)
            action_match = candidate_decision.action_type == baseline_decision.action_type
            tool_match = action_match and (candidate_decision.tool_name or "") == (baseline_decision.tool_name or "")
            results.append(
                PlannerShadowTaskResult(
                    task_id=task.id,
                    goal=task.goal,
                    selected_skills=selected_skills,
                    policy=policy,
                    baseline_decision=baseline_decision,
                    candidate_decision=candidate_decision,
                    policy_passed=not violations and candidate_decision.error_code is None,
                    action_match=action_match,
                    tool_match=tool_match,
                    violations=violations,
                )
            )
    finally:
        registry.close()
    return PlannerShadowReport(
        suite_name=suite.name,
        created_at=utc_now_iso(),
        candidate_provider=candidate_provider.name,
        baseline_provider=baseline.name,
        results=results,
        global_policy=global_policy,
    )


def _build_registry(settings: Settings) -> ToolRegistry:
    registry = ToolRegistry.local_defaults(settings.project_root)
    server_script = settings.project_root / "scripts" / "run_mcp_server.py"
    if server_script.exists():
        if "search_notes" not in registry.tools:
            registry.register(
                MCPToolAdapter(
                    workspace_root=settings.project_root,
                    server_script=server_script,
                    name="search_notes",
                    description="Search internal architecture notes over MCP.",
                    input_schema={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
                )
            )
        if "get_note" not in registry.tools:
            registry.register(
                MCPToolAdapter(
                    workspace_root=settings.project_root,
                    server_script=server_script,
                    name="get_note",
                    description="Read a note by note id over MCP.",
                    input_schema={"type": "object", "properties": {"note_id": {"type": "string"}}, "required": ["note_id"]},
                )
            )
    return registry


def _shadow_decision(
    provider: PlannerProvider,
    task: Task,
    tools,
    selected_skills: list[str],
    memory: MemoryManager,
) -> PlannerDecisionSnapshot:
    trace = RunTrace.start(task, selected_skills=selected_skills, planner_provider=provider.name)
    memory_summary = memory.summarize(trace)
    try:
        decision = provider.decide(task, trace, list(tools), memory_summary, selected_skills)
    except PlannerError as exc:
        return PlannerDecisionSnapshot.from_error(exc)
    return PlannerDecisionSnapshot.from_decision(decision)


def _task_policy(task: Task, global_policy: PlannerShadowPolicy) -> PlannerShadowPolicy:
    raw_policy = task.metadata.get("planner_shadow_policy", {}) if isinstance(task.metadata, dict) else {}
    if not isinstance(raw_policy, dict):
        raw_policy = {}
    return PlannerShadowPolicy(
        allowed_actions=_normalize_string_list(raw_policy.get("allowed_actions")),
        allowed_tools=_dedupe(global_policy.allowed_tools + _normalize_string_list(raw_policy.get("allowed_tools"))),
        blocked_tools=_dedupe(global_policy.blocked_tools + _normalize_string_list(raw_policy.get("blocked_tools"))),
        required_skills=_normalize_string_list(raw_policy.get("required_skills")),
    )


def _evaluate_policy(
    policy: PlannerShadowPolicy,
    decision: PlannerDecisionSnapshot,
    selected_skills: list[str],
) -> list[str]:
    violations: list[str] = []
    if policy.required_skills and not set(policy.required_skills).issubset(set(selected_skills)):
        violations.append("planner_missing_required_skill")
    if decision.error_code:
        return violations
    if policy.allowed_actions and (decision.action_type or "") not in policy.allowed_actions:
        violations.append("planner_action_not_allowed")
    if decision.action_type == "tool":
        tool_name = decision.tool_name or ""
        if policy.allowed_tools and tool_name not in policy.allowed_tools:
            violations.append("planner_tool_not_allowed")
        if tool_name in policy.blocked_tools:
            violations.append("planner_tool_blocked")
    return violations


def _normalize_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return _dedupe([str(item).strip() for item in value if str(item).strip()])
    text = str(value).strip()
    if not text:
        return []
    return _dedupe([part.strip() for part in text.split(",") if part.strip()])


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
