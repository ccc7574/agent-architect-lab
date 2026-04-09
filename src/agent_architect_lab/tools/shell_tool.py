from __future__ import annotations

import subprocess
import time
from typing import Any

from agent_architect_lab.models import ToolSpec
from agent_architect_lab.safety.policies import SafetyViolation, validate_shell_command
from agent_architect_lab.tools.base import Tool


class RunShellTool(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="run_shell",
            description="Run a low-risk shell command inside the workspace.",
            input_schema={"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]},
        )

    def invoke(self, arguments: dict[str, Any]) -> dict[str, Any]:
        command = arguments["command"]
        argv = validate_shell_command(command)
        start = time.perf_counter()
        completed = subprocess.run(
            argv,
            cwd=self.workspace_root,
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )
        latency_ms = int((time.perf_counter() - start) * 1000)
        return {
            "command": command,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "latency_ms": latency_ms,
        }

    def error_code_for_exception(self, exc: Exception) -> str:
        if isinstance(exc, SafetyViolation):
            return "safety_violation"
        if isinstance(exc, subprocess.TimeoutExpired):
            return "tool_timeout"
        return super().error_code_for_exception(exc)
