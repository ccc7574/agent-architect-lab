from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from agent_architect_lab.models import ToolSpec


class Tool(ABC):
    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root

    @property
    @abstractmethod
    def spec(self) -> ToolSpec:
        raise NotImplementedError

    @abstractmethod
    def invoke(self, arguments: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def error_code_for_exception(self, exc: Exception) -> str:
        return "tool_execution_error"
