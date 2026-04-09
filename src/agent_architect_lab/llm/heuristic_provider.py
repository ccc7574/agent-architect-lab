from __future__ import annotations

import re

from agent_architect_lab.llm.base import PlannerProvider
from agent_architect_lab.models import PlannerDecision, RunTrace, Task, ToolSpec


def _extract_backticked_command(goal: str) -> str | None:
    match = re.search(r"`([^`]+)`", goal)
    return match.group(1) if match else None


def _extract_quoted_path(goal: str) -> str | None:
    for pattern in (r"'([^']+\.[a-zA-Z0-9]+)'", r'"([^"]+\.[a-zA-Z0-9]+)"'):
        match = re.search(pattern, goal)
        if match:
            return match.group(1)
    return None


class HeuristicPlanner(PlannerProvider):
    """A deterministic planner so the project runs before any API keys exist."""

    NOTE_BACKED_SKILLS = {
        "agent_infra_architect",
        "evals_engineer",
        "harness_engineer",
        "memory_retrieval_designer",
        "observability_owner",
        "operator_workflow_designer",
        "product_architect",
        "safeguards_architect",
        "safety_policy_designer",
    }

    @property
    def name(self) -> str:
        return "heuristic"

    def _requires_approval(self, goal: str) -> bool:
        dangerous_verbs = ("delete", "remove", "deploy", "rotate", "revoke", "shutdown")
        sensitive_targets = ("production", "credential", "secret", "token", "release", "customer", "database")
        return any(verb in goal for verb in dangerous_verbs) and any(target in goal for target in sensitive_targets)

    def decide(
        self,
        task: Task,
        trace: RunTrace,
        tools: list[ToolSpec],
        memory_summary: str,
        selected_skills: list[str],
    ) -> PlannerDecision:
        goal = task.goal.lower()
        last_step = trace.steps[-1] if trace.steps else None

        if last_step and last_step.tool_call:
            tool_name = last_step.tool_call.name
            result = last_step.tool_call.result
            if tool_name == "search_files":
                matches = result.get("matches", [])
                if matches:
                    first_path = matches[0]["path"]
                    if any(term in goal for term in ("summarize", "what", "explain", "read")):
                        return PlannerDecision(
                            action_type="tool",
                            rationale=f"Search found a candidate file; read {first_path} to answer precisely.",
                            tool_name="read_file",
                            tool_arguments={"path": first_path},
                        )
                    return PlannerDecision(
                        action_type="answer",
                        rationale="Search already produced the relevant path list.",
                        final_answer="Found matches: " + ", ".join(match["path"] for match in matches[:5]),
                    )
                return PlannerDecision(
                    action_type="answer",
                    rationale="Search returned no matches, so report the miss explicitly.",
                    final_answer="No matching files were found.",
                )

            if tool_name == "read_file":
                content = result.get("content", "")
                preview = content[:400].strip()
                return PlannerDecision(
                    action_type="answer",
                    rationale="The file content is available, so respond with a concise synthesis.",
                    final_answer=f"Summary based on {result.get('path')}: {preview}",
                )

            if tool_name == "run_shell":
                stdout = result.get("stdout", "").strip()
                stderr = result.get("stderr", "").strip()
                answer = stdout or stderr or "Command completed without output."
                return PlannerDecision(
                    action_type="answer",
                    rationale="A shell command already executed; report its output.",
                    final_answer=answer,
                )

            if tool_name == "search_notes":
                matches = result.get("matches", [])
                if matches:
                    top_match = matches[0]
                    if any(skill in self.NOTE_BACKED_SKILLS for skill in selected_skills):
                        return PlannerDecision(
                            action_type="tool",
                            rationale=f"Read the full note for richer grounded context on {top_match['title']}.",
                            tool_name="get_note",
                            tool_arguments={"note_id": top_match["title"]},
                        )
                    return PlannerDecision(
                        action_type="answer",
                        rationale="The note search found a relevant passage.",
                        final_answer=f"{top_match['title']}: {top_match['snippet']}",
                    )
                return PlannerDecision(
                    action_type="answer",
                    rationale="No note matched the query.",
                    final_answer="No note matched the requested query.",
                )

            if tool_name == "get_note":
                content = result.get("content", "")
                preview = " ".join(content.split())[:400]
                return PlannerDecision(
                    action_type="answer",
                    rationale="The full note is available, so respond with a grounded synthesis.",
                    final_answer=f"{result.get('title')}: {preview}",
                )

        if any(term in goal for term in ("run ", "execute ", "shell", "command")):
            command = _extract_backticked_command(task.goal)
            if command:
                return PlannerDecision(
                    action_type="tool",
                    rationale="The task explicitly requests a shell command.",
                    tool_name="run_shell",
                    tool_arguments={"command": command},
                )

        if self._requires_approval(goal):
            return PlannerDecision(
                action_type="answer",
                rationale="The request targets a high-risk production action, so require explicit human approval before execution.",
                final_answer="Approval required before executing this action. Escalate to a human operator and record the justification in the trace.",
            )

        if any(term in goal for term in ("note", "principle", "memory", "retrieval")):
            return PlannerDecision(
                action_type="tool",
                rationale="The task sounds knowledge-oriented, so search the note MCP server.",
                tool_name="search_notes",
                tool_arguments={"query": task.goal},
            )

        if any(term in goal for term in ("find", "search", "locate", "where is")):
            path_hint = _extract_quoted_path(task.goal)
            pattern = path_hint or next((token for token in task.goal.split() if "." in token), task.goal)
            return PlannerDecision(
                action_type="tool",
                rationale="Use file search before reading anything else.",
                tool_name="search_files",
                tool_arguments={"pattern": pattern},
            )

        if any(term in goal for term in ("read", "open", "summarize")):
            path_hint = _extract_quoted_path(task.goal)
            if path_hint:
                return PlannerDecision(
                    action_type="tool",
                    rationale="The task references a concrete file path.",
                    tool_name="read_file",
                    tool_arguments={"path": path_hint},
                )

        if selected_skills and any(skill in self.NOTE_BACKED_SKILLS for skill in selected_skills):
            return PlannerDecision(
                action_type="tool",
                rationale="Matched skills indicate a note-backed architecture answer is more useful than a generic reply.",
                tool_name="search_notes",
                tool_arguments={"query": task.goal},
            )

        return PlannerDecision(
            action_type="answer",
            rationale="No specific tool is required, so respond directly.",
            final_answer=f"Goal captured. Memory summary: {memory_summary or 'none yet'}",
        )
