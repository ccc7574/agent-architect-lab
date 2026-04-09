from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_architect_lab.mcp.client import MCPClient
from agent_architect_lab.models import ToolSpec
from agent_architect_lab.tools.base import Tool


class MCPToolAdapter(Tool):
    def __init__(self, workspace_root: Path, server_script: Path, name: str, description: str, input_schema: dict[str, Any]) -> None:
        super().__init__(workspace_root)
        self._spec = ToolSpec(name=name, description=description, input_schema=input_schema)
        self.client = MCPClient(server_script)
        self.client.start()

    @property
    def spec(self) -> ToolSpec:
        return self._spec

    def invoke(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.client.call_tool(self._spec.name, arguments)

    def close(self) -> None:
        self.client.stop()

    def error_code_for_exception(self, exc: Exception) -> str:
        return "mcp_unavailable"
