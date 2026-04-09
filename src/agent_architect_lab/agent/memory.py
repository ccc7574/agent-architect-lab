from __future__ import annotations

from agent_architect_lab.models import RunTrace


class MemoryManager:
    def summarize(self, trace: RunTrace) -> str:
        if not trace.steps:
            return ""
        recent = trace.steps[-3:]
        summary_parts = []
        for step in recent:
            action = step.tool_call.name if step.tool_call else step.action_type
            observation = step.observation.replace("\n", " ")[:120]
            summary_parts.append(f"step {step.index}: {action} -> {observation}")
        return " | ".join(summary_parts)

