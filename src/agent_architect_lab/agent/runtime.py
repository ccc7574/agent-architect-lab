from __future__ import annotations

from pathlib import Path

from agent_architect_lab.agent.memory import MemoryManager
from agent_architect_lab.agent.planner import AgentPlanner
from agent_architect_lab.config import load_settings
from agent_architect_lab.llm.base import PlannerError
from agent_architect_lab.llm.factory import create_planner_provider
from agent_architect_lab.mcp.tool_adapter import MCPToolAdapter
from agent_architect_lab.models import RunTrace, StepTrace, Task
from agent_architect_lab.skills.router import SkillRouter
from agent_architect_lab.storage.checkpoints import CheckpointStore
from agent_architect_lab.tools.registry import ToolRegistry
from agent_architect_lab.traces.store import TraceStore


class AgentRuntime:
    def __init__(
        self,
        workspace_root: Path | None = None,
        planner: AgentPlanner | None = None,
        registry: ToolRegistry | None = None,
        trace_store: TraceStore | None = None,
        checkpoint_store: CheckpointStore | None = None,
        skill_router: SkillRouter | None = None,
        max_steps: int = 6,
    ) -> None:
        settings = load_settings()
        self.workspace_root = workspace_root or settings.project_root
        self.memory = MemoryManager()
        if planner is None:
            provider = create_planner_provider(settings)
            self.planner = AgentPlanner(provider)
            self.planner_provider_name = provider.name
        else:
            self.planner = planner
            self.planner_provider_name = planner.provider.name
        self.registry = registry or ToolRegistry.local_defaults(self.workspace_root)
        self.skill_router = skill_router or SkillRouter(settings.skills_dir)
        server_script = settings.project_root / "scripts" / "run_mcp_server.py"
        if server_script.exists():
            if "search_notes" not in self.registry.tools:
                self.registry.register(
                    MCPToolAdapter(
                        workspace_root=self.workspace_root,
                        server_script=server_script,
                        name="search_notes",
                        description="Search internal architecture notes over MCP.",
                        input_schema={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
                    )
                )
            if "get_note" not in self.registry.tools:
                self.registry.register(
                    MCPToolAdapter(
                        workspace_root=self.workspace_root,
                        server_script=server_script,
                        name="get_note",
                        description="Read a note by note id over MCP.",
                        input_schema={"type": "object", "properties": {"note_id": {"type": "string"}}, "required": ["note_id"]},
                    )
                )
        self.trace_store = trace_store or TraceStore(settings.traces_dir)
        self.checkpoint_store = checkpoint_store or CheckpointStore(settings.checkpoints_dir)
        self.max_steps = max_steps

    def run(self, task: Task) -> RunTrace:
        selected_skills = self.skill_router.select(task.goal)
        trace = RunTrace.start(task, selected_skills=selected_skills, planner_provider=self.planner_provider_name)
        for step_index in range(self.max_steps):
            memory_summary = self.memory.summarize(trace)
            try:
                decision = self.planner.decide(task, trace, self.registry.specs(), memory_summary, selected_skills)
            except PlannerError as exc:
                step = StepTrace(
                    index=step_index,
                    rationale="Planner provider failed before an action could be taken.",
                    action_type="planner_error",
                    tool_call=None,
                    observation=str(exc),
                    failure_type=exc.error_code,
                )
                trace.steps.append(step)
                trace.close(status="failed", final_answer=f"Task failed: {exc}", failure_type=exc.error_code)
                self.trace_store.save(trace)
                self.checkpoint_store.save(trace)
                return trace

            if decision.action_type == "answer":
                step = StepTrace(
                    index=step_index,
                    rationale=decision.rationale,
                    action_type="answer",
                    tool_call=None,
                    observation=decision.final_answer or "",
                )
                trace.steps.append(step)
                trace.close(status="completed", final_answer=decision.final_answer or "")
                self.trace_store.save(trace)
                self.checkpoint_store.save(trace)
                return trace

            tool_call = self.registry.invoke(decision.tool_name or "", decision.tool_arguments)
            observation = tool_call.error or str(tool_call.result)[:400]
            step = StepTrace(
                index=step_index,
                rationale=decision.rationale,
                action_type="tool",
                tool_call=tool_call,
                observation=observation,
                failure_type=tool_call.error_code,
            )
            trace.steps.append(step)
            self.trace_store.save(trace)
            self.checkpoint_store.save(trace)
            if tool_call.error:
                trace.close(
                    status="failed",
                    final_answer=f"Task failed: {tool_call.error}",
                    failure_type=tool_call.error_code or "tool_execution_error",
                )
                self.trace_store.save(trace)
                self.checkpoint_store.save(trace)
                return trace

        final_answer = "Agent stopped after reaching max steps."
        trace.close(status="incomplete", final_answer=final_answer, failure_type="step_budget_exceeded")
        self.trace_store.save(trace)
        self.checkpoint_store.save(trace)
        return trace

    def close(self) -> None:
        self.registry.close()
