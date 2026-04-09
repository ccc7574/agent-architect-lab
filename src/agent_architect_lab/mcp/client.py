from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from agent_architect_lab.mcp.protocol import read_message, write_message


class MCPClient:
    def __init__(self, server_script: Path) -> None:
        self.server_script = server_script
        self.process: subprocess.Popen | None = None
        self._request_id = 0

    def start(self) -> None:
        self.process = subprocess.Popen(
            [sys.executable, str(self.server_script)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.initialize()

    def stop(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=5)

    def _call(self, method: str, params: dict | None = None) -> dict:
        if not self.process or not self.process.stdin or not self.process.stdout:
            raise RuntimeError("MCP client is not started.")
        self._request_id += 1
        write_message(
            self.process.stdin,
            {"jsonrpc": "2.0", "id": self._request_id, "method": method, "params": params or {}},
        )
        response = read_message(self.process.stdout)
        if response is None:
            raise RuntimeError("MCP server closed the connection.")
        if "error" in response:
            raise RuntimeError(response["error"]["message"])
        return response["result"]

    def initialize(self) -> dict:
        return self._call("initialize", {})

    def list_tools(self) -> list[dict]:
        return self._call("tools/list", {}).get("tools", [])

    def call_tool(self, name: str, arguments: dict) -> dict:
        return self._call("tools/call", {"name": name, "arguments": arguments})

