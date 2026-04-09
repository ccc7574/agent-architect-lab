from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_architect_lab.models import ToolSpec
from agent_architect_lab.tools.base import Tool


IGNORED_SEARCH_PARTS = {
    ".agent_lab_artifacts",
    ".pytest_cache",
    "__pycache__",
    "artifacts",
}

IGNORED_SEARCH_FILENAMES = {
    ".DS_Store",
}


class _WorkspaceTool(Tool):
    def _resolve_path(self, raw_path: str) -> Path:
        candidate = (self.workspace_root / raw_path).resolve()
        if self.workspace_root not in candidate.parents and candidate != self.workspace_root:
            raise ValueError(f"Path '{raw_path}' resolves outside the workspace root.")
        return candidate

    def _is_searchable_path(self, path: Path) -> bool:
        if path.name in IGNORED_SEARCH_FILENAMES:
            return False
        return not any(part in IGNORED_SEARCH_PARTS for part in path.relative_to(self.workspace_root).parts)


class ReadFileTool(_WorkspaceTool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="read_file",
            description="Read a UTF-8 text file from the workspace.",
            input_schema={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        )

    def invoke(self, arguments: dict[str, Any]) -> dict[str, Any]:
        path = self._resolve_path(arguments["path"])
        content = path.read_text(encoding="utf-8")
        return {"path": str(path.relative_to(self.workspace_root)), "content": content}


class WriteFileTool(_WorkspaceTool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="write_file",
            description="Write UTF-8 text to a workspace file.",
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                "required": ["path", "content"],
            },
        )

    def invoke(self, arguments: dict[str, Any]) -> dict[str, Any]:
        path = self._resolve_path(arguments["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(arguments["content"], encoding="utf-8")
        return {"path": str(path.relative_to(self.workspace_root)), "bytes_written": len(arguments["content"].encode("utf-8"))}


class SearchFilesTool(_WorkspaceTool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="search_files",
            description="Search workspace file names and paths for a pattern.",
            input_schema={"type": "object", "properties": {"pattern": {"type": "string"}}, "required": ["pattern"]},
        )

    def invoke(self, arguments: dict[str, Any]) -> dict[str, Any]:
        pattern = arguments["pattern"].lower()
        matches = []
        for path in sorted(self.workspace_root.rglob("*")):
            if not path.is_file():
                continue
            if not self._is_searchable_path(path):
                continue
            rel = str(path.relative_to(self.workspace_root))
            if pattern in rel.lower():
                matches.append({"path": rel})
            if len(matches) >= 20:
                break
        return {"pattern": arguments["pattern"], "matches": matches}
