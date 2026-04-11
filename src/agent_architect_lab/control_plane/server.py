from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Mapping
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from agent_architect_lab.config import Settings, load_settings
from agent_architect_lab.control_plane.jobs import ControlPlaneJobRepository, ControlPlaneJobWorker
from agent_architect_lab.control_plane.maintenance import build_control_plane_storage_status
from agent_architect_lab.control_plane.policies import (
    AuthorizationContext,
    ControlPlanePolicyEngine,
    IdentityContext,
)
from agent_architect_lab.control_plane.repositories import (
    ControlPlaneRepositories,
    create_local_control_plane_repositories,
)
from agent_architect_lab.control_plane.reporting import build_governance_summary_payload
from agent_architect_lab.control_plane.sqlite_repositories import get_sqlite_schema_version
from agent_architect_lab.control_plane.storage import (
    AuditLogRepository,
    IdempotencyRecord,
    IdempotencyRepository,
)
from agent_architect_lab.harness.incidents import (
    get_incident_review_board,
    link_incident_followup_eval,
    open_incident,
    transition_incident,
)
from agent_architect_lab.harness.ledger_maintenance import build_ledger_storage_status
from agent_architect_lab.harness.ledger import (
    deploy_release,
    get_release_record,
    get_approval_review_board,
    get_release_risk_board,
    grant_release_override,
    list_releases,
    revoke_release_override,
    rollback_release,
    transition_release,
)
from agent_architect_lab.models import utc_now_iso


@dataclass(slots=True)
class ControlPlaneResponse:
    status_code: int
    payload: dict[str, Any]
    headers: dict[str, str] = field(default_factory=dict)


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
    job_store: ControlPlaneJobRepository
    job_worker: ControlPlaneJobWorker
    idempotency_repository: IdempotencyRepository
    audit_repository: AuditLogRepository
    policy_engine: ControlPlanePolicyEngine

    def handle_request(
        self,
        method: str,
        raw_path: str,
        headers: Mapping[str, str],
        body: bytes,
    ) -> ControlPlaneResponse:
        request_id = f"req-{uuid4().hex[:12]}"
        parsed = urlparse(raw_path)
        path = _normalize_path(parsed.path)
        query = parse_qs(parsed.query, keep_blank_values=False)
        respond = lambda response: self._attach_response_envelope(response, request_id=request_id)
        authorize = lambda scope, route_policy_key: self._authorize_route(
            request_id=request_id,
            method=method,
            path=path,
            scope=scope,
            route_policy_key=route_policy_key,
            headers=headers,
        )

        try:
            if method == "GET" and path == "/health":
                return respond(ControlPlaneResponse(
                    200,
                    {
                        "status": "ok",
                        "service": "agent-architect-lab-control-plane",
                        "generated_at": utc_now_iso(),
                        "worker": {
                            "alive": self.job_worker.is_alive(),
                            "poll_interval_s": self.job_worker.poll_interval_s,
                        },
                        "auth": {
                            "read_token_configured": bool(self.auth.read_token),
                            "mutation_token_configured": bool(self.auth.mutation_token),
                        },
                        "storage": {
                            "backend": self.settings.control_plane_storage_backend,
                            "sqlite_path": (
                                str(self.settings.control_plane_sqlite_path)
                                if self.settings.control_plane_storage_backend == "sqlite"
                                else None
                            ),
                            "schema_version": (
                                get_sqlite_schema_version(self.settings.control_plane_sqlite_path)
                                if self.settings.control_plane_storage_backend == "sqlite"
                                else None
                            ),
                        },
                    },
                ))
            if method == "GET" and path == "/storage-status":
                _authorization, auth_error = authorize("read", "read_storage")
                if auth_error is not None:
                    return respond(auth_error)
                return respond(ControlPlaneResponse(200, build_control_plane_storage_status(self.settings)))
            if method == "GET" and path == "/ledger-storage-status":
                _authorization, auth_error = authorize("read", "read_storage")
                if auth_error is not None:
                    return respond(auth_error)
                return respond(ControlPlaneResponse(200, build_ledger_storage_status(self.settings)))
            if method == "GET" and path == "/release-risk-board":
                _authorization, auth_error = authorize("read", "read_governance")
                if auth_error is not None:
                    return respond(auth_error)
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
                return respond(ControlPlaneResponse(200, payload))
            if method == "GET" and path == "/approval-review-board":
                _authorization, auth_error = authorize("read", "read_governance")
                if auth_error is not None:
                    return respond(auth_error)
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
                return respond(ControlPlaneResponse(200, payload))
            if method == "GET" and path == "/incident-review-board":
                _authorization, auth_error = authorize("read", "read_governance")
                if auth_error is not None:
                    return respond(auth_error)
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
                return respond(ControlPlaneResponse(200, payload))
            if method == "GET" and path == "/governance-summary":
                _authorization, auth_error = authorize("read", "read_governance")
                if auth_error is not None:
                    return respond(auth_error)
                payload = build_governance_summary_payload(
                    self.settings,
                    environments=_query_environments(query, self.settings),
                    release_limit=_query_int(query, "release_limit", default=20, minimum=1),
                    incident_limit=_query_int(query, "incident_limit", default=20, minimum=1),
                    override_limit=_query_int(query, "override_limit", default=50, minimum=1),
                )
                return respond(ControlPlaneResponse(200, payload))
            if method == "GET" and path == "/releases":
                _authorization, auth_error = authorize("read", "read_governance")
                if auth_error is not None:
                    return respond(auth_error)
                limit = _query_int(query, "limit", default=50, minimum=1)
                payload = {"rows": [row.to_dict() for row in list_releases(ledger_path=self.settings.release_ledger_path)[:limit]]}
                return respond(ControlPlaneResponse(200, payload))
            release_match = re.fullmatch(r"/releases/([^/]+)", path)
            if method == "GET" and release_match is not None:
                _authorization, auth_error = authorize("read", "read_governance")
                if auth_error is not None:
                    return respond(auth_error)
                payload = get_release_record(release_match.group(1), ledger_path=self.settings.release_ledger_path).to_dict()
                return respond(ControlPlaneResponse(200, payload))
            if method == "GET" and path == "/jobs":
                _authorization, auth_error = authorize("read", "read_jobs")
                if auth_error is not None:
                    return respond(auth_error)
                status = _query_optional_string(
                    query,
                    "status",
                    allowed={"queued", "running", "succeeded", "failed"},
                )
                limit = _query_int(query, "limit", default=50, minimum=1)
                jobs = [
                    job.to_dict()
                    for job in self.job_store.list_jobs(
                        status=status,
                        limit=limit,
                        job_type=_query_optional_string(query, "job_type"),
                        request_id=_query_optional_string(query, "request_id"),
                        operation_id=_query_optional_string(query, "operation_id"),
                    )
                ]
                return respond(ControlPlaneResponse(200, {"rows": jobs, "total": len(jobs)}))
            job_match = re.fullmatch(r"/jobs/([^/]+)", path)
            if method == "GET" and job_match is not None:
                _authorization, auth_error = authorize("read", "read_jobs")
                if auth_error is not None:
                    return respond(auth_error)
                job = self.job_store.get_job(job_match.group(1))
                return respond(ControlPlaneResponse(200, job.to_dict()))
            job_retry_match = re.fullmatch(r"/jobs/([^/]+)/retry", path)
            if method == "POST" and job_retry_match is not None:
                authorization, auth_error = authorize("write", "retry_job")
                if auth_error is not None:
                    return respond(auth_error)
                return respond(
                    self._execute_mutation(
                        request_id=request_id,
                        authorization=authorization,
                        method=method,
                        path=path,
                        headers=headers,
                        body=body,
                        handler=lambda payload: self._retry_job(job_retry_match.group(1), payload=payload),
                        success_status_code=200,
                    )
                )
            if method == "GET" and path == "/audit-events":
                _authorization, auth_error = authorize("read", "read_jobs")
                if auth_error is not None:
                    return respond(auth_error)
                limit = _query_int(query, "limit", default=100, minimum=1)
                request_id_filter = _query_optional_string(query, "request_id")
                operation_id_filter = _query_optional_string(query, "operation_id")
                events = [
                    event.to_dict()
                    for event in self.audit_repository.list_events(
                        request_id=request_id_filter,
                        operation_id=operation_id_filter,
                        event_type=_query_optional_string(query, "event_type"),
                        error_code=_query_optional_string(query, "error_code"),
                        route_policy_key=_query_optional_string(query, "route_policy_key"),
                        actor=_query_optional_string(query, "actor"),
                        role=_query_optional_string(query, "role"),
                        path=_query_optional_string(query, "path"),
                        method=_query_optional_string(query, "method"),
                        status_code=_query_optional_int(query, "status_code"),
                        replayed=_query_optional_bool(query, "replayed"),
                        conflict=_query_optional_bool(query, "conflict"),
                        limit=limit,
                    )
                ]
                return respond(ControlPlaneResponse(200, {"rows": events, "total": len(events)}))
            if method == "GET" and path == "/idempotency-records":
                _authorization, auth_error = authorize("read", "read_jobs")
                if auth_error is not None:
                    return respond(auth_error)
                limit = _query_int(query, "limit", default=100, minimum=1)
                rows = [
                    record.to_dict()
                    for record in self.idempotency_repository.list_records(
                        limit=limit,
                        method=_query_optional_string(query, "method"),
                        path=_query_optional_string(query, "path"),
                        operation_id=_query_optional_string(query, "operation_id"),
                        status_code=_query_optional_int(query, "status_code"),
                    )
                ]
                return respond(ControlPlaneResponse(200, {"rows": rows, "total": len(rows)}))
            idempotency_match = re.fullmatch(r"/idempotency-records/([^/]+)", path)
            if method == "GET" and idempotency_match is not None:
                _authorization, auth_error = authorize("read", "read_jobs")
                if auth_error is not None:
                    return respond(auth_error)
                record = self.idempotency_repository.get(idempotency_match.group(1))
                if record is None:
                    return respond(_error_response(404, "not_found", f"Unknown idempotency key '{idempotency_match.group(1)}'."))
                return respond(ControlPlaneResponse(200, record.to_dict()))
            if method == "POST" and path == "/jobs/export-governance-summary":
                authorization, auth_error = authorize("write", "create_export_job")
                if auth_error is not None:
                    return respond(auth_error)
                return respond(
                    self._execute_mutation(
                        request_id=request_id,
                        authorization=authorization,
                        method=method,
                        path=path,
                        headers=headers,
                        body=body,
                        handler=lambda payload: self._enqueue_job(
                            job_type="export_governance_summary",
                            payload={
                                "environments": _optional_string_list(payload, "environments"),
                                "release_limit": _optional_int(payload, "release_limit", default=20),
                                "incident_limit": _optional_int(payload, "incident_limit", default=20),
                                "override_limit": _optional_int(payload, "override_limit", default=50),
                                "output": _optional_string(payload, "output") or "",
                                "title": _optional_string(payload, "title") or "",
                            },
                            authorization=authorization,
                            request_id=request_id,
                        ),
                        success_status_code=202,
                    )
                )
            if method == "POST" and path == "/jobs/record-operator-handoff":
                authorization, auth_error = authorize("write", "create_export_job")
                if auth_error is not None:
                    return respond(auth_error)
                return respond(
                    self._execute_mutation(
                        request_id=request_id,
                        authorization=authorization,
                        method=method,
                        path=path,
                        headers=headers,
                        body=body,
                        handler=lambda payload: self._enqueue_job(
                            job_type="record_operator_handoff",
                            payload={
                                "environments": _optional_string_list(payload, "environments"),
                                "release_limit": _optional_int(payload, "release_limit", default=20),
                                "override_limit": _optional_int(payload, "override_limit", default=50),
                                "label": _optional_string(payload, "label") or "",
                                "output_path": _optional_string(payload, "output_path") or "",
                            },
                            authorization=authorization,
                            request_id=request_id,
                        ),
                        success_status_code=202,
                    )
                )
            if method == "POST" and path == "/jobs/export-operator-handoff-report":
                authorization, auth_error = authorize("write", "create_export_job")
                if auth_error is not None:
                    return respond(auth_error)
                return respond(
                    self._execute_mutation(
                        request_id=request_id,
                        authorization=authorization,
                        method=method,
                        path=path,
                        headers=headers,
                        body=body,
                        handler=lambda payload: self._enqueue_job(
                            job_type="export_operator_handoff_report",
                            payload={
                                "snapshot": _optional_string(payload, "snapshot") or "",
                                "latest": _optional_bool(payload, "latest", default=False),
                                "output": _optional_string(payload, "output") or "",
                                "title": _optional_string(payload, "title") or "",
                            },
                            authorization=authorization,
                            request_id=request_id,
                        ),
                        success_status_code=202,
                    )
                )
            if method == "POST" and path == "/jobs/export-release-runbook":
                authorization, auth_error = authorize("write", "create_export_job")
                if auth_error is not None:
                    return respond(auth_error)
                return respond(
                    self._execute_mutation(
                        request_id=request_id,
                        authorization=authorization,
                        method=method,
                        path=path,
                        headers=headers,
                        body=body,
                        handler=lambda payload: self._enqueue_job(
                            job_type="export_release_runbook",
                            payload={
                                "release_name": _required_string(payload, "release_name"),
                                "environments": _optional_string_list(payload, "environments"),
                                "history_limit": max(1, _optional_int(payload, "history_limit", default=10) or 10),
                                "incident_limit": max(1, _optional_int(payload, "incident_limit", default=20) or 20),
                                "output": _optional_string(payload, "output") or "",
                                "title": _optional_string(payload, "title") or "",
                            },
                            authorization=authorization,
                            request_id=request_id,
                        ),
                        success_status_code=202,
                    )
                )
            if method == "POST" and path == "/jobs/backup-control-plane-storage":
                authorization, auth_error = authorize("write", "manage_storage")
                if auth_error is not None:
                    return respond(auth_error)
                return respond(
                    self._execute_mutation(
                        request_id=request_id,
                        authorization=authorization,
                        method=method,
                        path=path,
                        headers=headers,
                        body=body,
                        handler=lambda payload: self._enqueue_job(
                            job_type="backup_control_plane_storage",
                            payload={
                                "output": _optional_string(payload, "output") or "",
                                "label": _optional_string(payload, "label") or "",
                            },
                            authorization=authorization,
                            request_id=request_id,
                        ),
                        success_status_code=202,
                    )
                )
            if method == "POST" and path == "/jobs/verify-control-plane-backup":
                authorization, auth_error = authorize("write", "manage_storage")
                if auth_error is not None:
                    return respond(auth_error)
                return respond(
                    self._execute_mutation(
                        request_id=request_id,
                        authorization=authorization,
                        method=method,
                        path=path,
                        headers=headers,
                        body=body,
                        handler=lambda payload: self._enqueue_job(
                            job_type="verify_control_plane_backup",
                            payload={
                                "backup_path": _required_string(payload, "backup_path"),
                                "expected_sha256": _optional_string(payload, "expected_sha256") or "",
                            },
                            authorization=authorization,
                            request_id=request_id,
                        ),
                        success_status_code=202,
                    )
                )
            if method == "POST" and path == "/jobs/restore-control-plane-backup":
                authorization, auth_error = authorize("write", "restore_storage")
                if auth_error is not None:
                    return respond(auth_error)
                return respond(
                    self._execute_mutation(
                        request_id=request_id,
                        authorization=authorization,
                        method=method,
                        path=path,
                        headers=headers,
                        body=body,
                        handler=lambda payload: self._enqueue_job(
                            job_type="restore_control_plane_backup",
                            payload={
                                "backup_path": _required_string(payload, "backup_path"),
                                "output_dir": _optional_string(payload, "output_dir") or "",
                                "label": _optional_string(payload, "label") or "",
                            },
                            authorization=authorization,
                            request_id=request_id,
                        ),
                        success_status_code=202,
                    )
                )
            if method == "POST" and path == "/jobs/backup-release-and-incident-ledgers":
                authorization, auth_error = authorize("write", "manage_storage")
                if auth_error is not None:
                    return respond(auth_error)
                return respond(
                    self._execute_mutation(
                        request_id=request_id,
                        authorization=authorization,
                        method=method,
                        path=path,
                        headers=headers,
                        body=body,
                        handler=lambda payload: self._enqueue_job(
                            job_type="backup_release_and_incident_ledgers",
                            payload={
                                "output": _optional_string(payload, "output") or "",
                                "label": _optional_string(payload, "label") or "",
                            },
                            authorization=authorization,
                            request_id=request_id,
                        ),
                        success_status_code=202,
                    )
                )
            if method == "POST" and path == "/jobs/verify-release-and-incident-ledger-backup":
                authorization, auth_error = authorize("write", "manage_storage")
                if auth_error is not None:
                    return respond(auth_error)
                return respond(
                    self._execute_mutation(
                        request_id=request_id,
                        authorization=authorization,
                        method=method,
                        path=path,
                        headers=headers,
                        body=body,
                        handler=lambda payload: self._enqueue_job(
                            job_type="verify_release_and_incident_ledger_backup",
                            payload={
                                "backup_path": _required_string(payload, "backup_path"),
                                "expected_sha256": _optional_string(payload, "expected_sha256") or "",
                            },
                            authorization=authorization,
                            request_id=request_id,
                        ),
                        success_status_code=202,
                    )
                )
            if method == "POST" and path == "/jobs/restore-release-and-incident-ledger-backup":
                authorization, auth_error = authorize("write", "restore_storage")
                if auth_error is not None:
                    return respond(auth_error)
                return respond(
                    self._execute_mutation(
                        request_id=request_id,
                        authorization=authorization,
                        method=method,
                        path=path,
                        headers=headers,
                        body=body,
                        handler=lambda payload: self._enqueue_job(
                            job_type="restore_release_and_incident_ledger_backup",
                            payload={
                                "backup_path": _required_string(payload, "backup_path"),
                                "output_dir": _optional_string(payload, "output_dir") or "",
                                "label": _optional_string(payload, "label") or "",
                            },
                            authorization=authorization,
                            request_id=request_id,
                        ),
                        success_status_code=202,
                    )
                )
            release_approve_match = re.fullmatch(r"/releases/([^/]+)/approve", path)
            if method == "POST" and release_approve_match is not None:
                authorization, auth_error = authorize("write", "approve_release")
                if auth_error is not None:
                    return respond(auth_error)
                return respond(self._execute_mutation(
                    request_id=request_id,
                    authorization=authorization,
                    method=method,
                    path=path,
                    headers=headers,
                    body=body,
                    handler=lambda payload: transition_release(
                        release_approve_match.group(1),
                        action="approve",
                        actor=authorization.actor or _required_string(payload, "actor"),
                        note=_optional_string(payload, "note") or "",
                        ledger_path=self.settings.release_ledger_path,
                        role=_optional_string(payload, "role") or authorization.role or authorization.actor or "",
                    ).to_dict(),
                    success_status_code=200,
                ))
            release_reject_match = re.fullmatch(r"/releases/([^/]+)/reject", path)
            if method == "POST" and release_reject_match is not None:
                authorization, auth_error = authorize("write", "reject_release")
                if auth_error is not None:
                    return respond(auth_error)
                return respond(self._execute_mutation(
                    request_id=request_id,
                    authorization=authorization,
                    method=method,
                    path=path,
                    headers=headers,
                    body=body,
                    handler=lambda payload: transition_release(
                        release_reject_match.group(1),
                        action="reject",
                        actor=authorization.actor or _required_string(payload, "actor"),
                        note=_optional_string(payload, "note") or "",
                        ledger_path=self.settings.release_ledger_path,
                    ).to_dict(),
                    success_status_code=200,
                ))
            release_promote_match = re.fullmatch(r"/releases/([^/]+)/promote", path)
            if method == "POST" and release_promote_match is not None:
                authorization, auth_error = authorize("write", "promote_release")
                if auth_error is not None:
                    return respond(auth_error)
                return respond(self._execute_mutation(
                    request_id=request_id,
                    authorization=authorization,
                    method=method,
                    path=path,
                    headers=headers,
                    body=body,
                    handler=lambda payload: transition_release(
                        release_promote_match.group(1),
                        action="promote",
                        actor=authorization.actor or _required_string(payload, "actor"),
                        note=_optional_string(payload, "note") or "",
                        ledger_path=self.settings.release_ledger_path,
                    ).to_dict(),
                    success_status_code=200,
                ))
            release_deploy_match = re.fullmatch(r"/releases/([^/]+)/deploy", path)
            if method == "POST" and release_deploy_match is not None:
                authorization, auth_error = authorize("write", "deploy_release")
                if auth_error is not None:
                    return respond(auth_error)
                return respond(self._execute_mutation(
                    request_id=request_id,
                    authorization=authorization,
                    method=method,
                    path=path,
                    headers=headers,
                    body=body,
                    handler=lambda payload: deploy_release(
                        release_deploy_match.group(1),
                        environment=_required_string(payload, "environment"),
                        actor=authorization.actor or _required_string(payload, "actor"),
                        note=_optional_string(payload, "note") or "",
                        ledger_path=self.settings.release_ledger_path,
                        production_soak_minutes=self.settings.production_soak_minutes,
                        required_approver_roles=self.settings.production_required_approver_roles,
                        environment_policies=self.settings.environment_policies,
                        environment_freeze_windows=self.settings.environment_freeze_windows,
                    ).to_dict(),
                    success_status_code=200,
                ))
            release_rollback_match = re.fullmatch(r"/releases/([^/]+)/rollback", path)
            if method == "POST" and release_rollback_match is not None:
                authorization, auth_error = authorize("write", "deploy_release")
                if auth_error is not None:
                    return respond(auth_error)
                return respond(self._execute_mutation(
                    request_id=request_id,
                    authorization=authorization,
                    method=method,
                    path=path,
                    headers=headers,
                    body=body,
                    handler=lambda payload: rollback_release(
                        release_rollback_match.group(1),
                        environment=_required_string(payload, "environment"),
                        actor=authorization.actor or _required_string(payload, "actor"),
                        note=_optional_string(payload, "note") or "",
                        ledger_path=self.settings.release_ledger_path,
                    ).to_dict(),
                    success_status_code=200,
                ))
            release_override_grant_match = re.fullmatch(r"/releases/([^/]+)/overrides/grant", path)
            if method == "POST" and release_override_grant_match is not None:
                authorization, auth_error = authorize("write", "manage_release_override")
                if auth_error is not None:
                    return respond(auth_error)
                return respond(self._execute_mutation(
                    request_id=request_id,
                    authorization=authorization,
                    method=method,
                    path=path,
                    headers=headers,
                    body=body,
                    handler=lambda payload: grant_release_override(
                        release_override_grant_match.group(1),
                        environment=_required_string(payload, "environment"),
                        blocker=_required_string(payload, "blocker"),
                        actor=authorization.actor or _required_string(payload, "actor"),
                        note=_optional_string(payload, "note") or "",
                        expires_at=_optional_string(payload, "expires_at"),
                        ledger_path=self.settings.release_ledger_path,
                    ).to_dict(),
                    success_status_code=200,
                ))
            release_override_revoke_match = re.fullmatch(r"/releases/([^/]+)/overrides/revoke", path)
            if method == "POST" and release_override_revoke_match is not None:
                authorization, auth_error = authorize("write", "manage_release_override")
                if auth_error is not None:
                    return respond(auth_error)
                return respond(self._execute_mutation(
                    request_id=request_id,
                    authorization=authorization,
                    method=method,
                    path=path,
                    headers=headers,
                    body=body,
                    handler=lambda payload: revoke_release_override(
                        release_override_revoke_match.group(1),
                        environment=_required_string(payload, "environment"),
                        blocker=_required_string(payload, "blocker"),
                        actor=authorization.actor or _required_string(payload, "actor"),
                        note=_optional_string(payload, "note") or "",
                        ledger_path=self.settings.release_ledger_path,
                    ).to_dict(),
                    success_status_code=200,
                ))
            if method == "POST" and path == "/incidents/open":
                authorization, auth_error = authorize("write", "open_incident")
                if auth_error is not None:
                    return respond(auth_error)
                return respond(self._execute_mutation(
                    request_id=request_id,
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
                ))
            transition_match = re.fullmatch(r"/incidents/([^/]+)/transition", path)
            if method == "POST" and transition_match is not None:
                authorization, auth_error = authorize("write", "transition_incident")
                if auth_error is not None:
                    return respond(auth_error)
                return respond(self._execute_mutation(
                    request_id=request_id,
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
                ))
            followup_link_match = re.fullmatch(r"/incidents/([^/]+)/followup-eval", path)
            if method == "POST" and followup_link_match is not None:
                authorization, auth_error = authorize("write", "transition_incident")
                if auth_error is not None:
                    return respond(auth_error)
                return respond(self._execute_mutation(
                    request_id=request_id,
                    authorization=authorization,
                    method=method,
                    path=path,
                    headers=headers,
                    body=body,
                    handler=lambda payload: link_incident_followup_eval(
                        followup_link_match.group(1),
                        followup_eval_path=_required_string(payload, "followup_eval_path"),
                        actor=_required_string(payload, "by"),
                        note=_optional_string(payload, "note") or "",
                        ledger_path=self.settings.incident_ledger_path,
                    ).to_dict(),
                    success_status_code=200,
                ))
            return respond(_error_response(404, "not_found", f"Route '{path}' is not defined."))
        except json.JSONDecodeError:
            return respond(_error_response(400, "invalid_json", "Request body must be valid JSON."))
        except KeyError as exc:
            return respond(_error_response(404, "not_found", str(exc)))
        except ValueError as exc:
            return respond(_error_response(400, "invalid_request", str(exc)))

    def _authorize_route(
        self,
        *,
        request_id: str,
        method: str,
        path: str,
        scope: str,
        route_policy_key: str,
        headers: Mapping[str, str],
    ) -> tuple[AuthorizationContext | None, ControlPlaneResponse | None]:
        token_scope, auth_error = self.auth.authenticate(scope, headers)
        if auth_error is not None:
            self._append_denied_request_audit(
                event_type="authentication_denied",
                request_id=request_id,
                method=method,
                path=path,
                route_policy_key=route_policy_key,
                headers=headers,
                response=auth_error,
                decision_details={"scope": scope},
                actor=None,
                role=None,
                token_scope=None,
            )
            return None, auth_error
        try:
            identity = _identity_context(headers)
        except ValueError as exc:
            response = _error_response(
                400,
                "invalid_request",
                str(exc),
                details={
                    "route_policy_key": route_policy_key,
                    "required_headers": ["X-Control-Plane-Actor", "X-Control-Plane-Role"],
                },
            )
            self._append_denied_request_audit(
                event_type="identity_invalid",
                request_id=request_id,
                method=method,
                path=path,
                route_policy_key=route_policy_key,
                headers=headers,
                response=response,
                decision_details=response.payload["error"].get("details", {}),
                actor=None,
                role=None,
                token_scope=token_scope,
            )
            return None, response
        authorization, decision = self.policy_engine.authorize_route(
            route_policy_key=route_policy_key,
            identity=identity,
            token_scope=token_scope or scope,
        )
        if decision.allowed:
            return authorization, None
        response = _error_response(
            400 if decision.code == "missing_identity" else 403,
            decision.code,
            decision.message,
            details=decision.details,
        )
        self._append_denied_request_audit(
            event_type="authorization_denied",
            request_id=request_id,
            method=method,
            path=path,
            route_policy_key=route_policy_key,
            headers=headers,
            response=response,
            decision_details=decision.details,
            actor=identity.actor if identity is not None else None,
            role=identity.role if identity is not None else None,
            token_scope=token_scope,
        )
        return None, response

    def _execute_mutation(
        self,
        *,
        request_id: str,
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
        existing = self.idempotency_repository.get(idempotency_key)
        if existing is not None:
            if existing.request_fingerprint != request_fingerprint:
                response = _error_response(
                    409,
                    "idempotency_conflict",
                    "Idempotency-Key has already been used for a different request payload.",
                )
                self._append_mutation_audit(
                    request_id=request_id,
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
                request_id=request_id,
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
        payload_decision = self.policy_engine.validate_payload(
            route_policy_key=_route_policy_key_for_path(method, path),
            authorization=authorization,
            payload=payload,
        )
        if not payload_decision.allowed:
            response = _error_response(
                403,
                payload_decision.code,
                payload_decision.message,
                details=payload_decision.details,
            )
            self._append_denied_request_audit(
                event_type="payload_denied",
                request_id=request_id,
                method=method,
                path=path,
                route_policy_key=_route_policy_key_for_path(method, path),
                headers=headers,
                response=response,
                decision_details=payload_decision.details,
                actor=authorization.actor if authorization is not None else None,
                role=authorization.role if authorization is not None else None,
                token_scope=authorization.token_scope if authorization is not None else None,
                body=body,
                idempotency_key=idempotency_key,
                request_fingerprint=request_fingerprint,
            )
            return response
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
        self.idempotency_repository.save(
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
        self._append_mutation_audit(
            request_id=request_id,
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

    def _retry_job(self, job_id: str, *, payload: Mapping[str, Any]) -> dict[str, Any]:
        job = self.job_store.requeue_job(
            job_id,
            max_attempts=_optional_int(payload, "max_attempts"),
        )
        return job.to_dict()

    def _enqueue_job(
        self,
        *,
        job_type: str,
        payload: dict[str, Any],
        authorization: AuthorizationContext | None,
        request_id: str,
    ) -> dict[str, Any]:
        job = self.job_store.create_job(
            job_type=job_type,
            payload=payload,
            requested_by_actor=authorization.actor if authorization is not None else None,
            requested_by_role=authorization.role if authorization is not None else None,
            request_id=request_id,
            operation_id=None,
        )
        return job.to_dict()

    def _attach_response_envelope(self, response: ControlPlaneResponse, *, request_id: str) -> ControlPlaneResponse:
        payload = dict(response.payload)
        payload["_meta"] = {
            "request_id": request_id,
            "generated_at": utc_now_iso(),
            "service": "agent-architect-lab-control-plane",
        }
        headers = dict(response.headers)
        headers["X-Request-Id"] = request_id
        return ControlPlaneResponse(status_code=response.status_code, payload=payload, headers=headers)

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
        request_id: str,
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
        audit_entry = {
            "audit_event_id": f"audit-{uuid4().hex[:12]}",
            "event_type": (
                "mutation_conflict"
                if conflict
                else ("mutation_replayed" if replayed else "mutation_committed")
            ),
            "request_id": request_id,
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
            "error_code": _response_error_code(response),
            "replayed": replayed,
            "conflict": conflict,
        }
        self.audit_repository.append(audit_entry)

    def _append_denied_request_audit(
        self,
        *,
        event_type: str,
        request_id: str,
        method: str,
        path: str,
        route_policy_key: str,
        headers: Mapping[str, str],
        response: ControlPlaneResponse,
        decision_details: Mapping[str, Any],
        actor: str | None,
        role: str | None,
        token_scope: str | None,
        body: bytes = b"",
        idempotency_key: str | None = None,
        request_fingerprint: str | None = None,
    ) -> None:
        self.audit_repository.append(
            {
                "audit_event_id": f"audit-{uuid4().hex[:12]}",
                "event_type": event_type,
                "request_id": request_id,
                "occurred_at": utc_now_iso(),
                "operation_id": None,
                "method": method,
                "path": path,
                "route_policy_key": route_policy_key,
                "idempotency_key": idempotency_key,
                "request_fingerprint": request_fingerprint,
                "token_scope": token_scope,
                "token_fingerprint": _token_fingerprint(_header_value(headers, "Authorization") or ""),
                "actor": actor,
                "role": role,
                "request_body": _audit_request_body(body),
                "status_code": response.status_code,
                "response_payload": response.payload,
                "error_code": _response_error_code(response),
                "replayed": False,
                "conflict": False,
                "policy_details": dict(decision_details),
            }
        )


class ControlPlaneHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, server_address, RequestHandlerClass, *, job_worker: ControlPlaneJobWorker):
        super().__init__(server_address, RequestHandlerClass)
        self.job_worker = job_worker

    def server_close(self) -> None:
        self.job_worker.stop()
        super().server_close()


def create_control_plane_server(
    *,
    settings: Settings | None = None,
    host: str | None = None,
    port: int | None = None,
) -> tuple[ControlPlaneHTTPServer, ControlPlaneApp]:
    resolved_settings = settings or load_settings()
    repositories = create_local_control_plane_repositories(resolved_settings)
    app = build_control_plane_app(
        settings=resolved_settings,
        repositories=repositories,
    )
    server = ControlPlaneHTTPServer(
        (host or resolved_settings.control_plane_host, port if port is not None else resolved_settings.control_plane_port),
        _build_handler(app),
        job_worker=app.job_worker,
    )
    app.job_worker.start()
    return server, app


def build_control_plane_app(
    *,
    settings: Settings | None = None,
    repositories: ControlPlaneRepositories | None = None,
) -> ControlPlaneApp:
    resolved_settings = settings or load_settings()
    resolved_repositories = repositories or create_local_control_plane_repositories(resolved_settings)
    job_worker = ControlPlaneJobWorker(settings=resolved_settings, store=resolved_repositories.jobs)
    return ControlPlaneApp(
        settings=resolved_settings,
        auth=ControlPlaneAuth(
            read_token=resolved_settings.control_plane_read_token,
            mutation_token=resolved_settings.control_plane_mutation_token,
        ),
        job_store=resolved_repositories.jobs,
        job_worker=job_worker,
        idempotency_repository=resolved_repositories.idempotency,
        audit_repository=resolved_repositories.audit,
        policy_engine=ControlPlanePolicyEngine(resolved_settings.control_plane_role_policies),
    )


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


def _error_response(
    status_code: int,
    code: str,
    message: str,
    *,
    details: Mapping[str, Any] | None = None,
) -> ControlPlaneResponse:
    error = {
        "code": code,
        "message": message,
    }
    if details:
        error["details"] = dict(details)
    return ControlPlaneResponse(
        status_code,
        {
            "error": error
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


def _response_error_code(response: ControlPlaneResponse) -> str | None:
    error = response.payload.get("error")
    if not isinstance(error, Mapping):
        return None
    code = error.get("code")
    if not isinstance(code, str):
        return None
    return code


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


def _optional_int(payload: Mapping[str, Any], key: str, *, default: int | None = None) -> int | None:
    value = payload.get(key)
    if value is None:
        return default
    if isinstance(value, bool):
        raise ValueError(f"Field '{key}' must be an integer.")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Field '{key}' must be an integer.") from exc


def _optional_bool(payload: Mapping[str, Any], key: str, *, default: bool) -> bool:
    value = payload.get(key)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    raise ValueError(f"Field '{key}' must be a boolean.")


def _optional_string_list(payload: Mapping[str, Any], key: str) -> list[str]:
    value = payload.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"Field '{key}' must be a list of strings.")
    items: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"Field '{key}' must be a list of strings.")
        stripped = item.strip()
        if stripped:
            items.append(stripped)
    return items


def _route_policy_key_for_path(method: str, path: str) -> str:
    if method == "POST":
        if path == "/jobs/export-governance-summary":
            return "create_export_job"
        if path == "/jobs/record-operator-handoff":
            return "create_export_job"
        if path == "/jobs/export-operator-handoff-report":
            return "create_export_job"
        if path == "/jobs/backup-control-plane-storage":
            return "manage_storage"
        if path == "/jobs/verify-control-plane-backup":
            return "manage_storage"
        if path == "/jobs/restore-control-plane-backup":
            return "restore_storage"
        if re.fullmatch(r"/jobs/[^/]+/retry", path):
            return "retry_job"
        if path == "/incidents/open":
            return "open_incident"
        if re.fullmatch(r"/incidents/[^/]+/transition", path):
            return "transition_incident"
        if re.fullmatch(r"/releases/[^/]+/approve", path):
            return "approve_release"
        if re.fullmatch(r"/releases/[^/]+/reject", path):
            return "reject_release"
        if re.fullmatch(r"/releases/[^/]+/promote", path):
            return "promote_release"
        if re.fullmatch(r"/releases/[^/]+/deploy", path):
            return "deploy_release"
        if re.fullmatch(r"/releases/[^/]+/rollback", path):
            return "deploy_release"
        if re.fullmatch(r"/releases/[^/]+/overrides/grant", path):
            return "manage_release_override"
        if re.fullmatch(r"/releases/[^/]+/overrides/revoke", path):
            return "manage_release_override"
    return ""


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


def _query_optional_int(query: Mapping[str, list[str]], key: str) -> int | None:
    raw_values = query.get(key)
    if not raw_values:
        return None
    try:
        return int(raw_values[-1])
    except ValueError as exc:
        raise ValueError(f"Query parameter '{key}' must be an integer.") from exc


def _query_optional_bool(query: Mapping[str, list[str]], key: str) -> bool | None:
    raw_values = query.get(key)
    if not raw_values:
        return None
    value = raw_values[-1].strip().lower()
    if not value:
        return None
    if value in {"true", "1", "yes"}:
        return True
    if value in {"false", "0", "no"}:
        return False
    raise ValueError(f"Query parameter '{key}' must be a boolean.")


def _query_environments(query: Mapping[str, list[str]], settings: Settings) -> list[str]:
    raw_values = [value.strip() for value in query.get("environment", []) if value.strip()]
    return raw_values or settings.environment_names
