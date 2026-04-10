from __future__ import annotations

import json
import re
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Mapping
from urllib.parse import parse_qs, urlparse

from agent_architect_lab.config import Settings, load_settings
from agent_architect_lab.harness.incidents import (
    get_incident_review_board,
    list_incidents,
    open_incident,
    transition_incident,
)
from agent_architect_lab.harness.ledger import (
    get_approval_review_board,
    get_override_review_board,
    get_release_risk_board,
    list_active_overrides,
    list_releases,
)
from agent_architect_lab.models import utc_now_iso


def build_governance_summary_payload(
    settings: Settings,
    *,
    environments: list[str] | None = None,
    release_limit: int = 20,
    incident_limit: int = 20,
    override_limit: int = 50,
) -> dict[str, Any]:
    selected_environments = environments or settings.environment_names
    release_risk_board = get_release_risk_board(
        environments=selected_environments,
        ledger_path=settings.release_ledger_path,
        production_soak_minutes=settings.production_soak_minutes,
        required_approver_roles=settings.production_required_approver_roles,
        environment_policies=settings.environment_policies,
        environment_freeze_windows=settings.environment_freeze_windows,
        override_expiring_soon_minutes=settings.override_expiring_soon_minutes,
        release_stale_minutes=settings.release_stale_minutes,
        limit=release_limit,
    ).to_dict()
    approval_review_board = get_approval_review_board(
        environments=selected_environments,
        ledger_path=settings.release_ledger_path,
        production_soak_minutes=settings.production_soak_minutes,
        required_approver_roles=settings.production_required_approver_roles,
        environment_policies=settings.environment_policies,
        environment_freeze_windows=settings.environment_freeze_windows,
        approval_stale_minutes=settings.approval_stale_minutes,
        limit=release_limit,
    ).to_dict()
    override_review_board = get_override_review_board(
        ledger_path=settings.release_ledger_path,
        override_expiring_soon_minutes=settings.override_expiring_soon_minutes,
        limit=override_limit,
    ).to_dict()
    active_overrides = [
        row.to_dict()
        for row in list_active_overrides(
            ledger_path=settings.release_ledger_path,
            release_name=None,
            environment=None,
            limit=override_limit,
        )
    ]
    incident_review_board = get_incident_review_board(
        ledger_path=settings.incident_ledger_path,
        stale_minutes=settings.incident_stale_minutes,
        status=None,
        limit=incident_limit,
    ).to_dict()
    active_incidents = [
        row.to_dict()
        for row in list_incidents(
            ledger_path=settings.incident_ledger_path,
            status=None,
            severity=None,
            limit=incident_limit,
        )
        if row.status not in {"resolved", "closed"}
    ]
    releases = [row.to_dict() for row in list_releases(ledger_path=settings.release_ledger_path)]
    return {
        "generated_at": utc_now_iso(),
        "environments": selected_environments,
        "release_risk_board": release_risk_board,
        "approval_review_board": approval_review_board,
        "incident_review_board": incident_review_board,
        "override_review_board": override_review_board,
        "active_incidents": active_incidents,
        "active_overrides": active_overrides,
        "releases": releases,
        "metrics": {
            "recorded_release_count": len(releases),
            "high_risk_release_count": len(
                [row for row in release_risk_board.get("rows", []) if row.get("risk_level") == "high"]
            ),
            "stale_release_count": len([row for row in release_risk_board.get("rows", []) if row.get("is_stale")]),
            "approval_backlog_count": len(approval_review_board.get("rows", [])),
            "stale_approval_count": len(
                [row for row in approval_review_board.get("rows", []) if row.get("is_stale")]
            ),
            "active_incident_count": len(active_incidents),
            "critical_incident_count": len(
                [row for row in active_incidents if row.get("severity") == "critical"]
            ),
            "active_override_count": len(active_overrides),
            "urgent_override_count": len(
                [
                    row
                    for row in override_review_board.get("rows", [])
                    if row.get("status") in {"expired", "expiring_soon"}
                ]
            ),
        },
    }


@dataclass(slots=True)
class ControlPlaneResponse:
    status_code: int
    payload: dict[str, Any]


@dataclass(slots=True)
class ControlPlaneAuth:
    read_token: str | None = None
    mutation_token: str | None = None

    def authorize(self, scope: str, headers: Mapping[str, str]) -> ControlPlaneResponse | None:
        if scope == "public":
            return None
        header_value = headers.get("Authorization", "")
        token = _extract_bearer_token(header_value)
        if scope == "read":
            valid_tokens = {candidate for candidate in (self.read_token, self.mutation_token) if candidate}
            if not valid_tokens:
                return None
            if token in valid_tokens:
                return None
            return _error_response(401, "unauthorized", "A valid bearer token is required for read access.")
        if scope == "write":
            if not self.mutation_token:
                return _error_response(
                    503,
                    "mutation_token_not_configured",
                    "Mutation routes are disabled until AGENT_ARCHITECT_LAB_CONTROL_PLANE_MUTATION_TOKEN is configured.",
                )
            if token == self.mutation_token:
                return None
            return _error_response(401, "unauthorized", "A valid mutation bearer token is required.")
        return _error_response(500, "invalid_scope", f"Unknown auth scope '{scope}'.")


@dataclass(slots=True)
class ControlPlaneApp:
    settings: Settings
    auth: ControlPlaneAuth

    def handle_request(
        self,
        method: str,
        raw_path: str,
        headers: Mapping[str, str],
        body: bytes,
    ) -> ControlPlaneResponse:
        parsed = urlparse(raw_path)
        path = _normalize_path(parsed.path)
        query = parse_qs(parsed.query, keep_blank_values=False)

        try:
            if method == "GET" and path == "/health":
                return ControlPlaneResponse(
                    200,
                    {
                        "status": "ok",
                        "service": "agent-architect-lab-control-plane",
                        "generated_at": utc_now_iso(),
                        "auth": {
                            "read_token_configured": bool(self.auth.read_token),
                            "mutation_token_configured": bool(self.auth.mutation_token),
                        },
                    },
                )
            if method == "GET" and path == "/release-risk-board":
                auth_error = self.auth.authorize("read", headers)
                if auth_error is not None:
                    return auth_error
                environments = _query_environments(query, self.settings)
                limit = _query_int(query, "limit", default=20, minimum=1)
                payload = get_release_risk_board(
                    environments=environments,
                    ledger_path=self.settings.release_ledger_path,
                    production_soak_minutes=self.settings.production_soak_minutes,
                    required_approver_roles=self.settings.production_required_approver_roles,
                    environment_policies=self.settings.environment_policies,
                    environment_freeze_windows=self.settings.environment_freeze_windows,
                    override_expiring_soon_minutes=self.settings.override_expiring_soon_minutes,
                    release_stale_minutes=self.settings.release_stale_minutes,
                    limit=limit,
                ).to_dict()
                return ControlPlaneResponse(200, payload)
            if method == "GET" and path == "/approval-review-board":
                auth_error = self.auth.authorize("read", headers)
                if auth_error is not None:
                    return auth_error
                environments = _query_environments(query, self.settings)
                limit = _query_int(query, "limit", default=20, minimum=1)
                payload = get_approval_review_board(
                    environments=environments,
                    ledger_path=self.settings.release_ledger_path,
                    production_soak_minutes=self.settings.production_soak_minutes,
                    required_approver_roles=self.settings.production_required_approver_roles,
                    environment_policies=self.settings.environment_policies,
                    environment_freeze_windows=self.settings.environment_freeze_windows,
                    approval_stale_minutes=self.settings.approval_stale_minutes,
                    limit=limit,
                ).to_dict()
                return ControlPlaneResponse(200, payload)
            if method == "GET" and path == "/incident-review-board":
                auth_error = self.auth.authorize("read", headers)
                if auth_error is not None:
                    return auth_error
                status = _query_optional_string(
                    query,
                    "status",
                    allowed={"open", "acknowledged", "contained", "resolved", "closed"},
                )
                limit = _query_int(query, "limit", default=20, minimum=1)
                payload = get_incident_review_board(
                    ledger_path=self.settings.incident_ledger_path,
                    stale_minutes=self.settings.incident_stale_minutes,
                    status=status,
                    limit=limit,
                ).to_dict()
                return ControlPlaneResponse(200, payload)
            if method == "GET" and path == "/governance-summary":
                auth_error = self.auth.authorize("read", headers)
                if auth_error is not None:
                    return auth_error
                payload = build_governance_summary_payload(
                    self.settings,
                    environments=_query_environments(query, self.settings),
                    release_limit=_query_int(query, "release_limit", default=20, minimum=1),
                    incident_limit=_query_int(query, "incident_limit", default=20, minimum=1),
                    override_limit=_query_int(query, "override_limit", default=50, minimum=1),
                )
                return ControlPlaneResponse(200, payload)
            if method == "POST" and path == "/incidents/open":
                auth_error = self.auth.authorize("write", headers)
                if auth_error is not None:
                    return auth_error
                payload = _load_json_body(body)
                record = open_incident(
                    severity=_required_string(payload, "severity"),
                    summary=_required_string(payload, "summary"),
                    owner=_required_string(payload, "owner"),
                    environment=_optional_string(payload, "environment"),
                    release_name=_optional_string(payload, "release_name"),
                    source_report_path=_optional_string(payload, "source_report_path"),
                    note=_optional_string(payload, "note") or "",
                    ledger_path=self.settings.incident_ledger_path,
                )
                return ControlPlaneResponse(201, record.to_dict())
            transition_match = re.fullmatch(r"/incidents/([^/]+)/transition", path)
            if method == "POST" and transition_match is not None:
                auth_error = self.auth.authorize("write", headers)
                if auth_error is not None:
                    return auth_error
                payload = _load_json_body(body)
                record = transition_incident(
                    transition_match.group(1),
                    status=_required_string(payload, "status"),
                    actor=_required_string(payload, "by"),
                    note=_optional_string(payload, "note") or "",
                    owner=_optional_string(payload, "owner"),
                    followup_eval_path=_optional_string(payload, "followup_eval_path"),
                    ledger_path=self.settings.incident_ledger_path,
                )
                return ControlPlaneResponse(200, record.to_dict())
            return _error_response(404, "not_found", f"Route '{path}' is not defined.")
        except json.JSONDecodeError:
            return _error_response(400, "invalid_json", "Request body must be valid JSON.")
        except KeyError as exc:
            return _error_response(404, "not_found", str(exc))
        except ValueError as exc:
            return _error_response(400, "invalid_request", str(exc))


class ControlPlaneHTTPServer(ThreadingHTTPServer):
    daemon_threads = True


def create_control_plane_server(
    *,
    settings: Settings | None = None,
    host: str | None = None,
    port: int | None = None,
) -> tuple[ControlPlaneHTTPServer, ControlPlaneApp]:
    resolved_settings = settings or load_settings()
    app = ControlPlaneApp(
        settings=resolved_settings,
        auth=ControlPlaneAuth(
            read_token=resolved_settings.control_plane_read_token,
            mutation_token=resolved_settings.control_plane_mutation_token,
        ),
    )
    server = ControlPlaneHTTPServer(
        (host or resolved_settings.control_plane_host, port if port is not None else resolved_settings.control_plane_port),
        _build_handler(app),
    )
    return server, app


def _build_handler(app: ControlPlaneApp) -> type[BaseHTTPRequestHandler]:
    class ControlPlaneHandler(BaseHTTPRequestHandler):
        server_version = "AgentArchitectLabControlPlane/0.1"

        def do_GET(self) -> None:
            self._dispatch()

        def do_POST(self) -> None:
            self._dispatch()

        def _dispatch(self) -> None:
            content_length = int(self.headers.get("Content-Length", "0") or "0")
            body = self.rfile.read(content_length) if content_length > 0 else b""
            response = app.handle_request(
                self.command,
                self.path,
                {key: value for key, value in self.headers.items()},
                body,
            )
            payload = json.dumps(response.payload, indent=2).encode("utf-8") + b"\n"
            self.send_response(response.status_code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: object) -> None:
            return

    return ControlPlaneHandler


def _error_response(status_code: int, code: str, message: str) -> ControlPlaneResponse:
    return ControlPlaneResponse(
        status_code,
        {
            "error": {
                "code": code,
                "message": message,
            }
        },
    )


def _extract_bearer_token(header_value: str) -> str | None:
    parts = header_value.strip().split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None


def _load_json_body(body: bytes) -> dict[str, Any]:
    if not body:
        return {}
    payload = json.loads(body.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Request body must be a JSON object.")
    return payload


def _required_string(payload: Mapping[str, Any], key: str) -> str:
    value = _optional_string(payload, key)
    if not value:
        raise ValueError(f"Field '{key}' is required.")
    return value


def _optional_string(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"Field '{key}' must be a string.")
    stripped = value.strip()
    return stripped or None


def _normalize_path(path: str) -> str:
    if not path or path == "/":
        return "/"
    return path.rstrip("/")


def _query_int(
    query: Mapping[str, list[str]],
    key: str,
    *,
    default: int,
    minimum: int,
) -> int:
    raw_values = query.get(key)
    if not raw_values:
        return default
    try:
        value = int(raw_values[-1])
    except ValueError as exc:
        raise ValueError(f"Query parameter '{key}' must be an integer.") from exc
    if value < minimum:
        raise ValueError(f"Query parameter '{key}' must be >= {minimum}.")
    return value


def _query_optional_string(
    query: Mapping[str, list[str]],
    key: str,
    *,
    allowed: set[str] | None = None,
) -> str | None:
    raw_values = query.get(key)
    if not raw_values:
        return None
    value = raw_values[-1].strip()
    if not value:
        return None
    if allowed is not None and value not in allowed:
        raise ValueError(
            f"Query parameter '{key}' must be one of: {', '.join(sorted(allowed))}."
        )
    return value


def _query_environments(query: Mapping[str, list[str]], settings: Settings) -> list[str]:
    raw_values = [value.strip() for value in query.get("environment", []) if value.strip()]
    return raw_values or settings.environment_names
