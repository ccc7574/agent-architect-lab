from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_architect_lab.models import ToolCall, ToolSpec
from agent_architect_lab.tools.base import Tool
from agent_architect_lab.tools.file_tools import ReadFileTool, SearchFilesTool, WriteFileTool
from agent_architect_lab.tools.shell_tool import RunShellTool


@dataclass(slots=True)
class ToolRegistry:
    tools: dict[str, Tool]

    @classmethod
    def local_defaults(cls, workspace_root: Path) -> "ToolRegistry":
        tool_list = [
            ReadFileTool(workspace_root),
            WriteFileTool(workspace_root),
            SearchFilesTool(workspace_root),
            RunShellTool(workspace_root),
        ]
        return cls({tool.spec.name: tool for tool in tool_list})

    def register(self, tool: Tool) -> None:
        self.tools[tool.spec.name] = tool

    def specs(self) -> list[ToolSpec]:
        return [tool.spec for tool in self.tools.values()]

    def invoke(self, name: str, arguments: dict[str, Any]) -> ToolCall:
        if name not in self.tools:
            return ToolCall(
                name=name,
                arguments=arguments,
                result={"error": f"Unknown tool '{name}'."},
                latency_ms=0,
                error=f"Unknown tool '{name}'.",
                error_code="planner_invalid_tool",
            )
        tool = self.tools[name]
        start = time.perf_counter()
        error = None
        error_code = None
        try:
            result = tool.invoke(arguments)
        except Exception as exc:  # pragma: no cover - exercised by runtime error path
            error = str(exc)
            error_code = tool.error_code_for_exception(exc)
            result = {"error": str(exc)}
        latency_ms = int((time.perf_counter() - start) * 1000)
        return ToolCall(
            name=name,
            arguments=arguments,
            result=result,
            latency_ms=latency_ms,
            error=error,
            error_code=error_code,
        )

    def close(self) -> None:
        for tool in self.tools.values():
            close = getattr(tool, "close", None)
            if callable(close):
                close()
