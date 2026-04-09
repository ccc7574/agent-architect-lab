from __future__ import annotations

from pathlib import Path

from agent_architect_lab.agent.runtime import AgentRuntime
from agent_architect_lab.models import Task
from agent_architect_lab.safety.policies import SafetyViolation, validate_shell_command
from agent_architect_lab.tools.file_tools import SearchFilesTool


def test_validate_shell_command_blocks_metacharacters() -> None:
    try:
        validate_shell_command("echo hi && pwd")
    except SafetyViolation as exc:
        assert "metacharacters" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("Expected a SafetyViolation for metacharacters.")


def test_runtime_fails_dangerous_shell_tasks() -> None:
    runtime = AgentRuntime()
    try:
        trace = runtime.run(Task.create(goal="run `echo hi; pwd`"))
    finally:
        runtime.close()
    assert trace.status == "failed"
    assert trace.failure_type == "safety_violation"


def test_search_files_ignores_artifact_directories(tmp_path: Path) -> None:
    (tmp_path / "artifacts").mkdir()
    (tmp_path / "artifacts" / "ignored.txt").write_text("ignore me", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "kept.txt").write_text("keep me", encoding="utf-8")

    tool = SearchFilesTool(tmp_path)
    result = tool.invoke({"pattern": "txt"})
    assert result["matches"] == [{"path": "src/kept.txt"}]
