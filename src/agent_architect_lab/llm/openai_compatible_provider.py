from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib import error, request

from agent_architect_lab.llm.base import PlannerError, PlannerProvider
from agent_architect_lab.models import PlannerDecision, RunTrace, Task, ToolSpec


def _build_prompt(task: Task, trace: RunTrace, tools: list[ToolSpec], memory_summary: str, selected_skills: list[str]) -> str:
    tool_lines = [
        f"- {tool.name}: {tool.description} schema={json.dumps(tool.input_schema, sort_keys=True)}"
        for tool in tools
    ]
    return (
        "You are a planner for a local agent runtime.\n"
        "Return strict JSON with keys action_type, rationale, tool_name, tool_arguments, final_answer.\n"
        "action_type must be 'answer' or 'tool'.\n"
        "Only pick a tool from the provided list.\n"
        f"Task goal: {task.goal}\n"
        f"Selected skills: {selected_skills}\n"
        f"Memory summary: {memory_summary}\n"
        f"Previous steps: {json.dumps([step.to_dict() for step in trace.steps], ensure_ascii=True)}\n"
        "Available tools:\n"
        + "\n".join(tool_lines)
    )


def _coerce_decision(payload: dict[str, Any]) -> PlannerDecision:
    action_type = payload.get("action_type")
    if action_type not in {"answer", "tool"}:
        raise PlannerError("Planner response must use action_type 'answer' or 'tool'.", "planner_invalid_response")
    tool_arguments = payload.get("tool_arguments") or {}
    if not isinstance(tool_arguments, dict):
        raise PlannerError("Planner tool_arguments must be an object.", "planner_invalid_response")
    return PlannerDecision(
        action_type=action_type,
        rationale=str(payload.get("rationale", "")).strip() or "Model-selected plan.",
        tool_name=payload.get("tool_name"),
        tool_arguments=tool_arguments,
        final_answer=payload.get("final_answer"),
    )


def _validate_value_against_schema(value: Any, schema: dict[str, Any], path: str) -> None:
    schema_type = schema.get("type")
    if schema_type == "string":
        if not isinstance(value, str):
            raise PlannerError(f"{path} must be a string.", "planner_invalid_arguments")
        return
    if schema_type == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            raise PlannerError(f"{path} must be an integer.", "planner_invalid_arguments")
        return
    if schema_type == "number":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise PlannerError(f"{path} must be a number.", "planner_invalid_arguments")
        return
    if schema_type == "boolean":
        if not isinstance(value, bool):
            raise PlannerError(f"{path} must be a boolean.", "planner_invalid_arguments")
        return
    if schema_type == "object":
        if not isinstance(value, dict):
            raise PlannerError(f"{path} must be an object.", "planner_invalid_arguments")
        _validate_arguments_against_schema(value, schema, path)
        return


def _validate_arguments_against_schema(arguments: dict[str, Any], schema: dict[str, Any], path: str = "tool_arguments") -> None:
    if schema.get("type") != "object":
        return
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    missing = [name for name in required if name not in arguments]
    if missing:
        raise PlannerError(f"{path} is missing required fields: {', '.join(missing)}.", "planner_invalid_arguments")
    unexpected = sorted(set(arguments) - set(properties))
    if unexpected:
        raise PlannerError(f"{path} includes unexpected fields: {', '.join(unexpected)}.", "planner_invalid_arguments")
    for name, value in arguments.items():
        if name in properties:
            _validate_value_against_schema(value, properties[name], f"{path}.{name}")


def _validate_decision(decision: PlannerDecision, tools: list[ToolSpec]) -> PlannerDecision:
    tools_by_name = {tool.name: tool for tool in tools}
    if decision.action_type == "tool":
        if not decision.tool_name:
            raise PlannerError("Planner chose tool action without tool_name.", "planner_invalid_response")
        if decision.tool_name not in tools_by_name:
            raise PlannerError(
                f"Planner selected unknown tool '{decision.tool_name}'.",
                "planner_invalid_tool",
            )
        _validate_arguments_against_schema(decision.tool_arguments, tools_by_name[decision.tool_name].input_schema)
    if decision.action_type == "answer" and not (decision.final_answer or "").strip():
        raise PlannerError("Planner answer action must include final_answer.", "planner_invalid_response")
    return decision


@dataclass(slots=True)
class OpenAICompatiblePlanner(PlannerProvider):
    api_base: str
    api_key: str
    model: str
    timeout_s: float = 20.0
    max_retries: int = 2

    @property
    def name(self) -> str:
        return "openai_compatible"

    def _request_body(
        self,
        task: Task,
        trace: RunTrace,
        tools: list[ToolSpec],
        memory_summary: str,
        selected_skills: list[str],
    ) -> bytes:
        prompt = _build_prompt(task, trace, tools, memory_summary, selected_skills)
        body = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": "You are a careful planner for a local agent runtime."},
                {"role": "user", "content": prompt},
            ],
        }
        return json.dumps(body).encode("utf-8")

    def _post(self, body: bytes) -> dict[str, Any]:
        req = request.Request(
            url=self.api_base.rstrip("/") + "/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.timeout_s) as response:  # noqa: S310
                return json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="replace")
            raise PlannerError(
                f"Planner HTTP error {exc.code}: {body_text[:240]}",
                "planner_http_error",
            ) from exc
        except error.URLError as exc:
            raise PlannerError(f"Planner network error: {exc.reason}", "planner_network_error") from exc
        except TimeoutError as exc:
            raise PlannerError("Planner request timed out.", "planner_timeout") from exc
        except json.JSONDecodeError as exc:
            raise PlannerError(f"Planner returned non-JSON response: {exc}", "planner_invalid_response") from exc

    def _extract_content(self, response: dict[str, Any]) -> str:
        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise PlannerError("Planner response did not include choices[0].message.content.", "planner_invalid_response") from exc
        if not isinstance(content, str):
            raise PlannerError("Planner response content was not a string.", "planner_invalid_response")
        return content

    def decide(
        self,
        task: Task,
        trace: RunTrace,
        tools: list[ToolSpec],
        memory_summary: str,
        selected_skills: list[str],
    ) -> PlannerDecision:
        body = self._request_body(task, trace, tools, memory_summary, selected_skills)
        last_error: PlannerError | None = None
        for _attempt in range(self.max_retries + 1):
            try:
                response = self._post(body)
                content = self._extract_content(response)
                return _validate_decision(_coerce_decision(json.loads(content)), tools)
            except json.JSONDecodeError as exc:
                last_error = PlannerError(f"Planner returned invalid JSON content: {exc}", "planner_invalid_response")
                break
            except PlannerError as exc:
                last_error = exc
                if exc.error_code in {"planner_invalid_tool", "planner_invalid_response"}:
                    break
        if last_error is None:
            raise PlannerError("Planner failed without surfacing an error.", "planner_provider_error")
        raise last_error
