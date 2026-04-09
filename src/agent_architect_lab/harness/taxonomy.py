from __future__ import annotations

PLANNER_INVALID_TOOL = "planner_invalid_tool"
TOOL_EXECUTION_ERROR = "tool_execution_error"
TOOL_TIMEOUT = "tool_timeout"
SAFETY_VIOLATION = "safety_violation"
RETRIEVAL_MISS = "retrieval_miss"
MCP_UNAVAILABLE = "mcp_unavailable"
ANSWER_MISSING_CONTENT = "answer_missing_content"
WRONG_TOOL_PATH = "wrong_tool_path"
STATUS_MISMATCH = "status_mismatch"
STEP_BUDGET_EXCEEDED = "step_budget_exceeded"
TRACE_SHAPE_MISMATCH = "trace_shape_mismatch"
SKILL_ROUTING_MISMATCH = "skill_routing_mismatch"
APPROVAL_SIGNAL_MISSING = "approval_signal_missing"

BLOCKING_FAILURE_TYPES = (
    SAFETY_VIOLATION,
    PLANNER_INVALID_TOOL,
    MCP_UNAVAILABLE,
)
