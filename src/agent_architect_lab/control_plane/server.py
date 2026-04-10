from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

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
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class AuthorizationContext:
    token_scope: str
    actor: str | None = None
    role: str | None = None


@dataclass(slots=True)
class IdempotencyRecord:
    idempotency_key: str
    method: str
    path: str
    request_fingerprint: str
    operation_id: str
    committed_at: str
    status_code: int
    response_payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "idempotency_key": self.idempotency_key,
            "method": self.method,
            "path": self.path,
            "request_fingerprint": self.request_fingerprint,
            "operation_id": self.operation_id,
            "committed_at": self.committed_at,
            "status_code": self.status_code,
            "response_payload": self.response_payload,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "IdempotencyRecord":
        return cls(
            idempotency_key=str(payload["idempotency_key"]),
            method=str(payload["method"]),
            path=str(payload["path"]),
            request_fingerprint=str(payload["request_fingerprint"]),
            operation_id=str(payload["operation_id"]),
            committed_at=str(payload["committed_at"]),
            status_code=int(payload["status_code"]),
            response_payload=dict(payload["response_payload"]),
        )


@dataclass(slots=True)
class IdempotencyRegistry:
    records: dict[str, IdempotencyRecord] = field(default_factory=dict)

    def get(self, idempotency_key: str) -> IdempotencyRecord | None:
        return self.records.get(idempotency_key)

    def set(self, record: IdempotencyRecord) -> None:
        self.records[record.idempotency_key] = record

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "records": {
                key: record.to_dict()
                for key, record in sorted(self.records.items())
            }
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "IdempotencyRegistry":
        if not path.exists():
            return cls()
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            records={
                key: IdempotencyRecord.from_dict(record)
                for key, record in payload.get("records", {}).items()
            }
        )


@dataclass(slots=True)
class ControlPlaneAuth:
    read_token: str | None = None
    mutation_token: str | None = None

    def authenticate(
        self,
        scope: str,
        headers: Mapping[str, str],
    ) -> tuple[str | None, ControlPlaneResponse | None]:
        if scope == "public":
            return "public", None
        header_value = _header_value(headers, "Authorization") or ""
        token = _extract_bearer_token(header_value)
        if scope == "read":
            valid_tokens = {candidate for candidate in (self.read_token, self.mutation_token) if candidate}
            if not valid_tokens:
                return "anonymous", None
            if token in valid_tokens:
                return ("mutation" if token == self.mutation_token else "read"), None
            return None, _error_response(401, "unauthorized", "A valid bearer token is required for read access.")
        if scope == "write":
            if not self.mutation_token:
                return None, _error_response(
                    503,
                    "mutation_token_not_configured",
                    "Mutation routes are disabled until AGENT_ARCHITECT_LAB_CONTROL_PLANE_MUTATION_TOKEN is configured.",
                )
            if token == self.mutation_token:
                return "mutation", None
            return None, _error_response(401, "unauthorized", "A valid mutation bearer token is required.")
        return None, _error_response(500, "invalid_scope", f"Unknown auth scope '{scope}'.")


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
                authorization, auth_error = self._authorize_route(
                    scope="read",
                    route_policy_key="read_governance",
                    headers=headers,
                )
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
                authorization, auth_error = self._authorize_route(
                    scope="read",
                    route_policy_key="read_governance",
                    headers=headers,
                )
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
                authorization, auth_error = self._authorize_route(
                    scope="read",
                    route_policy_key="read_governance",
                    headers=headers,
                )
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
                authorization, auth_error = self._authorize_route(
                    scope="read",
                    route_policy_key="read_governance",
                    headers=headers,
                )
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
                authorization, auth_error = self._authorize_route(
                    scope="write",
                    route_policy_key="open_incident",
                    headers=headers,
                )
                if auth_error is not None:
                    return auth_error
                return self._execute_mutation(
                    authorization=authorization,
                    method=method,
                    path=path,
                    headers=headers,
                    body=body,
                    handler=lambda payload: open_incident(
                        severity=_required_string(payload, "severity"),
                        summary=_required_string(payload, "summary"),
                        owner=_required_string(payload, "owner"),
                        environment=_optional_string(payload, "environment"),
                        release_name=_optional_string(payload, "release_name"),
                        source_report_path=_optional_string(payload, "source_report_path"),
                        note=_optional_string(payload, "note") or "",
                        ledger_path=self.settings.incident_ledger_path,
                    ).to_dict(),
                    success_status_code=201,
                )
            transition_match = re.fullmatch(r"/incidents/([^/]+)/transition", path)
            if method == "POST" and transition_match is not None:
                authorization, auth_error = self._authorize_route(
                    scope="write",
                    route_policy_key="transition_incident",
                    headers=headers,
                )
                if auth_error is not None:
                    return auth_error
                return self._execute_mutation(
                    authorization=authorization,
                    method=method,
                    path=path,
                    headers=headers,
                    body=body,
                    handler=lambda payload: transition_incident(
                        transition_match.group(1),
                        status=_required_string(payload, "status"),
                        actor=_required_string(payload, "by"),
                        note=_optional_string(payload, "note") or "",
                        owner=_optional_string(payload, "owner"),
                        followup_eval_path=_optional_string(payload, "followup_eval_path"),
                        ledger_path=self.settings.incident_ledger_path,
                    ).to_dict(),
                    success_status_code=200,
                )
            return _error_response(404, "not_found", f"Route '{path}' is not defined.")
        except json.JSONDecodeError:
            return _error_response(400, "invalid_json", "Request body must be valid JSON.")
        except KeyError as exc:
            return _error_response(404, "not_found", str(exc))
        except ValueError as exc:
            return _error_response(400, "invalid_request", str(exc))

    def _authorize_route(
        self,
        *,
        scope: str,
        route_policy_key: str,
        headers: Mapping[str, str],
    ) -> tuple[AuthorizationContext | None, ControlPlaneResponse | None]:
        token_scope, auth_error = self.auth.authenticate(scope, headers)
        if auth_error is not None:
            return None, auth_error
        allowed_roles = self.settings.control_plane_role_policies.get(route_policy_key, [])
        identity = _identity_context(headers)
        if allowed_roles:
            if identity is None:
                return None, _error_response(
                    400,
                    "missing_identity",
                    "Headers 'X-Control-Plane-Actor' and 'X-Control-Plane-Role' are required for this route.",
                )
            if identity.role not in allowed_roles:
                return None, _error_response(
                    403,
                    "forbidden_role",
                    f"Role '{identity.role}' is not permitted for route policy '{route_policy_key}'.",
                )
            return AuthorizationContext(token_scope=token_scope or scope, actor=identity.actor, role=identity.role), None
        if identity is not None:
            return AuthorizationContext(token_scope=token_scope or scope, actor=identity.actor, role=identity.role), None
        return AuthorizationContext(token_scope=token_scope or scope), None

    def _execute_mutation(
        self,
        *,
        authorization: AuthorizationContext | None,
        method: str,
        path: str,
        headers: Mapping[str, str],
        body: bytes,
        handler: Any,
        success_status_code: int,
    ) -> ControlPlaneResponse:
        idempotency_key = _required_idempotency_key(headers)
        request_fingerprint = _request_fingerprint(method, path, body)
        registry = IdempotencyRegistry.load(self.settings.control_plane_idempotency_path)
        existing = registry.get(idempotency_key)
        if existing is not None:
            if existing.request_fingerprint != request_fingerprint:
                response = _error_response(
                    409,
                    "idempotency_conflict",
                    "Idempotency-Key has already been used for a different request payload.",
                )
                self._append_mutation_audit(
                    method=method,
                    path=path,
                    headers=headers,
                body=body,
                idempotency_key=idempotency_key,
                request_fingerprint=request_fingerprint,
                response=response,
                operation_id=existing.operation_id,
                authorization=authorization,
                replayed=False,
                conflict=True,
            )
                return response
            response = self._build_mutation_response(
                status_code=existing.status_code,
                payload=existing.response_payload,
                operation_id=existing.operation_id,
                idempotency_key=idempotency_key,
                replayed=True,
                committed_at=existing.committed_at,
            )
            self._append_mutation_audit(
                method=method,
                path=path,
                headers=headers,
                body=body,
                idempotency_key=idempotency_key,
                request_fingerprint=request_fingerprint,
                response=response,
                operation_id=existing.operation_id,
                authorization=authorization,
                replayed=True,
                conflict=False,
            )
            return response

        payload = _load_json_body(body)
        result_payload = handler(payload)
        operation_id = f"op-{uuid4().hex[:12]}"
        committed_at = utc_now_iso()
        response = self._build_mutation_response(
            status_code=success_status_code,
            payload=result_payload,
            operation_id=operation_id,
            idempotency_key=idempotency_key,
            replayed=False,
            committed_at=committed_at,
        )
        registry.set(
            IdempotencyRecord(
                idempotency_key=idempotency_key,
                method=method,
                path=path,
                request_fingerprint=request_fingerprint,
                operation_id=operation_id,
                committed_at=committed_at,
                status_code=response.status_code,
                response_payload=response.payload,
            )
        )
        registry.save(self.settings.control_plane_idempotency_path)
        self._append_mutation_audit(
            method=method,
            path=path,
            headers=headers,
            body=body,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            response=response,
            operation_id=operation_id,
            authorization=authorization,
            replayed=False,
            conflict=False,
        )
        return response

    def _build_mutation_response(
        self,
        *,
        status_code: int,
        payload: dict[str, Any],
        operation_id: str,
        idempotency_key: str,
        replayed: bool,
        committed_at: str,
    ) -> ControlPlaneResponse:
        response_payload = dict(payload)
        response_payload["_control_plane"] = {
            "operation_id": operation_id,
            "idempotency_key": idempotency_key,
            "replayed": replayed,
            "committed_at": committed_at,
        }
        return ControlPlaneResponse(
            status_code=status_code,
            payload=response_payload,
            headers={
                "X-Control-Plane-Operation-Id": operation_id,
                "X-Idempotent-Replay": "true" if replayed else "false",
            },
        )

    def _append_mutation_audit(
        self,
        *,
        method: str,
        path: str,
        headers: Mapping[str, str],
        body: bytes,
        idempotency_key: str,
        request_fingerprint: str,
        response: ControlPlaneResponse,
        operation_id: str,
        authorization: AuthorizationContext | None,
        replayed: bool,
        conflict: bool,
    ) -> None:
        self.settings.control_plane_request_log_path.parent.mkdir(parents=True, exist_ok=True)
        audit_entry = {
            "audit_event_id": f"audit-{uuid4().hex[:12]}",
            "occurred_at": utc_now_iso(),
            "operation_id": operation_id,
            "method": method,
            "path": path,
            "idempotency_key": idempotency_key,
            "request_fingerprint": request_fingerprint,
            "token_scope": authorization.token_scope if authorization is not None else None,
            "token_fingerprint": _token_fingerprint(_header_value(headers, "Authorization") or ""),
            "actor": authorization.actor if authorization is not None else None,
            "role": authorization.role if authorization is not None else None,
            "request_body": _audit_request_body(body),
            "status_code": response.status_code,
            "response_payload": response.payload,
            "replayed": replayed,
            "conflict": conflict,
        }
        with self.settings.control_plane_request_log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(audit_entry, sort_keys=True) + "\n")


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
            for key, value in response.headers.items():
                self.send_header(key, value)
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


def _header_value(headers: Mapping[str, str], name: str) -> str | None:
    target = name.lower()
    for key, value in headers.items():
        if key.lower() == target:
            return value
    return None


def _extract_bearer_token(header_value: str) -> str | None:
    parts = header_value.strip().split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None


@dataclass(slots=True)
class IdentityContext:
    actor: str
    role: str


def _identity_context(headers: Mapping[str, str]) -> IdentityContext | None:
    actor = (_header_value(headers, "X-Control-Plane-Actor") or "").strip()
    role = (_header_value(headers, "X-Control-Plane-Role") or "").strip()
    if not actor and not role:
        return None
    if not actor or not role:
        raise ValueError(
            "Headers 'X-Control-Plane-Actor' and 'X-Control-Plane-Role' must be supplied together."
        )
    return IdentityContext(actor=actor, role=role)


def _required_idempotency_key(headers: Mapping[str, str]) -> str:
    candidate = (_header_value(headers, "Idempotency-Key") or "").strip()
    if candidate:
        return candidate
    raise ValueError("Header 'Idempotency-Key' is required for mutation routes.")


def _load_json_body(body: bytes) -> dict[str, Any]:
    if not body:
        return {}
    payload = json.loads(body.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Request body must be a JSON object.")
    return payload


def _audit_request_body(body: bytes) -> dict[str, Any] | dict[str, str]:
    if not body:
        return {}
    try:
        return _load_json_body(body)
    except (json.JSONDecodeError, ValueError):
        return {"raw": body.decode("utf-8", errors="replace")}


def _request_fingerprint(method: str, path: str, body: bytes) -> str:
    digest = hashlib.sha256()
    digest.update(method.encode("utf-8"))
    digest.update(b"\0")
    digest.update(path.encode("utf-8"))
    digest.update(b"\0")
    digest.update(body)
    return digest.hexdigest()


def _token_fingerprint(header_value: str) -> str | None:
    token = _extract_bearer_token(header_value)
    if not token:
        return None
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


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
