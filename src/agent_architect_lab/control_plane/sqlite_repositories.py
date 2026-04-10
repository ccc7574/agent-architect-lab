from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

from agent_architect_lab.control_plane.jobs import ControlPlaneJob, ControlPlaneJobRepository
from agent_architect_lab.control_plane.storage import AuditEvent, IdempotencyRecord
from agent_architect_lab.models import utc_now_iso


class SQLiteRepositoryMixin:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection


class SQLiteIdempotencyRepository(SQLiteRepositoryMixin):
    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self._initialize()

    def _initialize(self) -> None:
        with self._lock:
            with self._connect() as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS idempotency_records (
                        idempotency_key TEXT PRIMARY KEY,
                        method TEXT NOT NULL,
                        path TEXT NOT NULL,
                        request_fingerprint TEXT NOT NULL,
                        operation_id TEXT NOT NULL,
                        committed_at TEXT NOT NULL,
                        status_code INTEGER NOT NULL,
                        response_payload TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_idempotency_committed_at ON idempotency_records (committed_at DESC, idempotency_key DESC)"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_idempotency_operation_id ON idempotency_records (operation_id)"
                )

    def get(self, idempotency_key: str) -> IdempotencyRecord | None:
        with self._lock:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT * FROM idempotency_records WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
        return _idempotency_from_row(row) if row is not None else None

    def save(self, record: IdempotencyRecord) -> None:
        with self._lock:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT OR REPLACE INTO idempotency_records (
                        idempotency_key,
                        method,
                        path,
                        request_fingerprint,
                        operation_id,
                        committed_at,
                        status_code,
                        response_payload
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.idempotency_key,
                        record.method,
                        record.path,
                        record.request_fingerprint,
                        record.operation_id,
                        record.committed_at,
                        record.status_code,
                        json.dumps(record.response_payload, sort_keys=True),
                    ),
                )

    def list_records(
        self,
        *,
        limit: int = 100,
        method: str | None = None,
        path: str | None = None,
        operation_id: str | None = None,
        status_code: int | None = None,
    ) -> list[IdempotencyRecord]:
        clauses: list[str] = []
        parameters: list[Any] = []
        if method is not None:
            clauses.append("method = ?")
            parameters.append(method)
        if path is not None:
            clauses.append("path = ?")
            parameters.append(path)
        if operation_id is not None:
            clauses.append("operation_id = ?")
            parameters.append(operation_id)
        if status_code is not None:
            clauses.append("status_code = ?")
            parameters.append(status_code)
        sql = "SELECT * FROM idempotency_records"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY committed_at DESC, idempotency_key DESC LIMIT ?"
        parameters.append(limit)
        with self._lock:
            with self._connect() as connection:
                rows = connection.execute(sql, parameters).fetchall()
        return [_idempotency_from_row(row) for row in rows]


class SQLiteAuditLogRepository(SQLiteRepositoryMixin):
    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self._initialize()

    def _initialize(self) -> None:
        with self._lock:
            with self._connect() as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS audit_events (
                        audit_event_id TEXT PRIMARY KEY,
                        occurred_at TEXT NOT NULL,
                        request_id TEXT,
                        operation_id TEXT,
                        event_type TEXT,
                        error_code TEXT,
                        actor TEXT,
                        role TEXT,
                        method TEXT,
                        path TEXT,
                        status_code INTEGER,
                        replayed INTEGER NOT NULL DEFAULT 0,
                        conflict INTEGER NOT NULL DEFAULT 0,
                        payload TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_audit_occurred_at ON audit_events (occurred_at DESC, audit_event_id DESC)"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_audit_request_id ON audit_events (request_id)"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_audit_operation_id ON audit_events (operation_id)"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_audit_event_type ON audit_events (event_type, error_code)"
                )

    def append(self, payload: dict[str, Any]) -> None:
        event = dict(payload)
        audit_event_id = str(event.get("audit_event_id") or f"audit-{uuid4().hex[:12]}")
        with self._lock:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT OR REPLACE INTO audit_events (
                        audit_event_id,
                        occurred_at,
                        request_id,
                        operation_id,
                        event_type,
                        error_code,
                        actor,
                        role,
                        method,
                        path,
                        status_code,
                        replayed,
                        conflict,
                        payload
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        audit_event_id,
                        str(event.get("occurred_at", "")),
                        _optional_text(event.get("request_id")),
                        _optional_text(event.get("operation_id")),
                        _optional_text(event.get("event_type")),
                        _optional_text(event.get("error_code")),
                        _optional_text(event.get("actor")),
                        _optional_text(event.get("role")),
                        _optional_text(event.get("method")),
                        _optional_text(event.get("path")),
                        _optional_int(event.get("status_code")),
                        1 if bool(event.get("replayed")) else 0,
                        1 if bool(event.get("conflict")) else 0,
                        json.dumps(event, sort_keys=True),
                    ),
                )

    def list_events(
        self,
        *,
        request_id: str | None = None,
        operation_id: str | None = None,
        event_type: str | None = None,
        error_code: str | None = None,
        actor: str | None = None,
        role: str | None = None,
        path: str | None = None,
        method: str | None = None,
        status_code: int | None = None,
        replayed: bool | None = None,
        conflict: bool | None = None,
        limit: int = 100,
    ) -> list[AuditEvent]:
        clauses: list[str] = []
        parameters: list[Any] = []
        for column, value in (
            ("request_id", request_id),
            ("operation_id", operation_id),
            ("event_type", event_type),
            ("error_code", error_code),
            ("actor", actor),
            ("role", role),
            ("path", path),
            ("method", method),
            ("status_code", status_code),
        ):
            if value is None:
                continue
            clauses.append(f"{column} = ?")
            parameters.append(value)
        if replayed is not None:
            clauses.append("replayed = ?")
            parameters.append(1 if replayed else 0)
        if conflict is not None:
            clauses.append("conflict = ?")
            parameters.append(1 if conflict else 0)
        sql = "SELECT payload FROM audit_events"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY occurred_at DESC, audit_event_id DESC LIMIT ?"
        parameters.append(limit)
        with self._lock:
            with self._connect() as connection:
                rows = connection.execute(sql, parameters).fetchall()
        return [AuditEvent.from_dict(json.loads(str(row["payload"]))) for row in rows]


class SQLiteControlPlaneJobStore(SQLiteRepositoryMixin, ControlPlaneJobRepository):
    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self._initialize()

    def _initialize(self) -> None:
        with self._lock:
            with self._connect() as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS control_plane_jobs (
                        job_id TEXT PRIMARY KEY,
                        job_type TEXT NOT NULL,
                        status TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        requested_by_actor TEXT,
                        requested_by_role TEXT,
                        request_id TEXT,
                        operation_id TEXT,
                        attempts INTEGER NOT NULL,
                        max_attempts INTEGER NOT NULL,
                        queue_reason TEXT NOT NULL,
                        input_payload TEXT NOT NULL,
                        result_payload TEXT,
                        error TEXT,
                        last_error TEXT,
                        started_at TEXT,
                        completed_at TEXT
                    )
                    """
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_jobs_status_created_at ON control_plane_jobs (status, created_at ASC, job_id ASC)"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_jobs_request_id ON control_plane_jobs (request_id)"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_jobs_operation_id ON control_plane_jobs (operation_id)"
                )

    def create_job(
        self,
        *,
        job_type: str,
        payload: dict[str, Any],
        requested_by_actor: str | None,
        requested_by_role: str | None,
        request_id: str | None,
        operation_id: str | None,
        max_attempts: int = 1,
    ) -> ControlPlaneJob:
        now = utc_now_iso()
        job = ControlPlaneJob(
            job_id=f"job-{uuid4().hex[:12]}",
            job_type=job_type,
            status="queued",
            created_at=now,
            updated_at=now,
            requested_by_actor=requested_by_actor,
            requested_by_role=requested_by_role,
            request_id=request_id,
            operation_id=operation_id,
            attempts=0,
            max_attempts=max_attempts,
            queue_reason="initial_enqueue",
            input_payload=dict(payload),
        )
        with self._lock:
            with self._connect() as connection:
                _insert_job(connection, job)
        return job

    def list_jobs(
        self,
        *,
        status: str | None = None,
        limit: int = 50,
        job_type: str | None = None,
        request_id: str | None = None,
        operation_id: str | None = None,
    ) -> list[ControlPlaneJob]:
        clauses: list[str] = []
        parameters: list[Any] = []
        for column, value in (
            ("status", status),
            ("job_type", job_type),
            ("request_id", request_id),
            ("operation_id", operation_id),
        ):
            if value is None:
                continue
            clauses.append(f"{column} = ?")
            parameters.append(value)
        sql = "SELECT * FROM control_plane_jobs"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC, job_id DESC LIMIT ?"
        parameters.append(limit)
        with self._lock:
            with self._connect() as connection:
                rows = connection.execute(sql, parameters).fetchall()
        return [_job_from_row(row) for row in rows]

    def get_job(self, job_id: str) -> ControlPlaneJob:
        with self._lock:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT * FROM control_plane_jobs WHERE job_id = ?",
                    (job_id,),
                ).fetchone()
        if row is None:
            raise KeyError(f"Unknown job '{job_id}'.")
        return _job_from_row(row)

    def claim_next_job(self) -> ControlPlaneJob | None:
        with self._lock:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    """
                    SELECT * FROM control_plane_jobs
                    WHERE status = 'queued'
                    ORDER BY created_at ASC, job_id ASC
                    LIMIT 1
                    """
                ).fetchone()
                if row is None:
                    connection.commit()
                    return None
                now = utc_now_iso()
                connection.execute(
                    """
                    UPDATE control_plane_jobs
                    SET status = 'running',
                        attempts = attempts + 1,
                        started_at = ?,
                        updated_at = ?
                    WHERE job_id = ?
                    """,
                    (now, now, str(row["job_id"])),
                )
                updated = connection.execute(
                    "SELECT * FROM control_plane_jobs WHERE job_id = ?",
                    (str(row["job_id"]),),
                ).fetchone()
                connection.commit()
        return _job_from_row(updated) if updated is not None else None

    def complete_job(self, job_id: str, result_payload: dict[str, Any]) -> ControlPlaneJob:
        with self._lock:
            with self._connect() as connection:
                _assert_job_exists(connection, job_id)
                now = utc_now_iso()
                connection.execute(
                    """
                    UPDATE control_plane_jobs
                    SET status = 'succeeded',
                        result_payload = ?,
                        error = NULL,
                        completed_at = ?,
                        updated_at = ?,
                        queue_reason = 'completed'
                    WHERE job_id = ?
                    """,
                    (json.dumps(result_payload, sort_keys=True), now, now, job_id),
                )
                row = connection.execute(
                    "SELECT * FROM control_plane_jobs WHERE job_id = ?",
                    (job_id,),
                ).fetchone()
        return _job_from_row(row)

    def fail_job(self, job_id: str, error_payload: dict[str, Any]) -> ControlPlaneJob:
        with self._lock:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT * FROM control_plane_jobs WHERE job_id = ?",
                    (job_id,),
                ).fetchone()
                if row is None:
                    raise KeyError(f"Unknown job '{job_id}'.")
                now = utc_now_iso()
                latest_error = json.dumps(error_payload, sort_keys=True)
                attempts = int(row["attempts"])
                max_attempts = int(row["max_attempts"])
                if attempts < max_attempts:
                    connection.execute(
                        """
                        UPDATE control_plane_jobs
                        SET status = 'queued',
                            error = NULL,
                            last_error = ?,
                            completed_at = NULL,
                            updated_at = ?,
                            queue_reason = 'automatic_retry'
                        WHERE job_id = ?
                        """,
                        (latest_error, now, job_id),
                    )
                else:
                    connection.execute(
                        """
                        UPDATE control_plane_jobs
                        SET status = 'failed',
                            error = ?,
                            last_error = ?,
                            completed_at = ?,
                            updated_at = ?,
                            queue_reason = 'failed'
                        WHERE job_id = ?
                        """,
                        (latest_error, latest_error, now, now, job_id),
                    )
                updated = connection.execute(
                    "SELECT * FROM control_plane_jobs WHERE job_id = ?",
                    (job_id,),
                ).fetchone()
        return _job_from_row(updated)

    def requeue_job(self, job_id: str, *, max_attempts: int | None = None) -> ControlPlaneJob:
        with self._lock:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT * FROM control_plane_jobs WHERE job_id = ?",
                    (job_id,),
                ).fetchone()
                if row is None:
                    raise KeyError(f"Unknown job '{job_id}'.")
                if str(row["status"]) != "failed":
                    raise ValueError(f"Only failed jobs can be retried. Job '{job_id}' is currently '{row['status']}'.")
                used_attempts = int(row["attempts"])
                if max_attempts is not None and max_attempts <= used_attempts:
                    raise ValueError("Field 'max_attempts' must be greater than the number of attempts already used.")
                next_max_attempts = max_attempts or max(int(row["max_attempts"]), used_attempts + 1)
                now = utc_now_iso()
                connection.execute(
                    """
                    UPDATE control_plane_jobs
                    SET status = 'queued',
                        max_attempts = ?,
                        error = NULL,
                        completed_at = NULL,
                        updated_at = ?,
                        queue_reason = 'manual_retry'
                    WHERE job_id = ?
                    """,
                    (next_max_attempts, now, job_id),
                )
                updated = connection.execute(
                    "SELECT * FROM control_plane_jobs WHERE job_id = ?",
                    (job_id,),
                ).fetchone()
        return _job_from_row(updated)


def _insert_job(connection: sqlite3.Connection, job: ControlPlaneJob) -> None:
    connection.execute(
        """
        INSERT INTO control_plane_jobs (
            job_id,
            job_type,
            status,
            created_at,
            updated_at,
            requested_by_actor,
            requested_by_role,
            request_id,
            operation_id,
            attempts,
            max_attempts,
            queue_reason,
            input_payload,
            result_payload,
            error,
            last_error,
            started_at,
            completed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job.job_id,
            job.job_type,
            job.status,
            job.created_at,
            job.updated_at,
            job.requested_by_actor,
            job.requested_by_role,
            job.request_id,
            job.operation_id,
            job.attempts,
            job.max_attempts,
            job.queue_reason,
            json.dumps(job.input_payload, sort_keys=True),
            json.dumps(job.result_payload, sort_keys=True) if job.result_payload is not None else None,
            json.dumps(job.error, sort_keys=True) if job.error is not None else None,
            json.dumps(job.last_error, sort_keys=True) if job.last_error is not None else None,
            job.started_at,
            job.completed_at,
        ),
    )


def _assert_job_exists(connection: sqlite3.Connection, job_id: str) -> None:
    row = connection.execute(
        "SELECT job_id FROM control_plane_jobs WHERE job_id = ?",
        (job_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"Unknown job '{job_id}'.")


def _job_from_row(row: sqlite3.Row) -> ControlPlaneJob:
    return ControlPlaneJob(
        job_id=str(row["job_id"]),
        job_type=str(row["job_type"]),
        status=str(row["status"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        requested_by_actor=_optional_text(row["requested_by_actor"]),
        requested_by_role=_optional_text(row["requested_by_role"]),
        request_id=_optional_text(row["request_id"]),
        operation_id=_optional_text(row["operation_id"]),
        attempts=int(row["attempts"]),
        max_attempts=int(row["max_attempts"]),
        queue_reason=str(row["queue_reason"]),
        input_payload=_json_dict(row["input_payload"]) or {},
        result_payload=_json_dict(row["result_payload"]),
        error=_json_dict(row["error"]),
        last_error=_json_dict(row["last_error"]),
        started_at=_optional_text(row["started_at"]),
        completed_at=_optional_text(row["completed_at"]),
    )


def _idempotency_from_row(row: sqlite3.Row) -> IdempotencyRecord:
    return IdempotencyRecord(
        idempotency_key=str(row["idempotency_key"]),
        method=str(row["method"]),
        path=str(row["path"]),
        request_fingerprint=str(row["request_fingerprint"]),
        operation_id=str(row["operation_id"]),
        committed_at=str(row["committed_at"]),
        status_code=int(row["status_code"]),
        response_payload=_json_dict(row["response_payload"]) or {},
    )


def _json_dict(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    payload = json.loads(str(value))
    if not isinstance(payload, dict):
        return None
    return {str(key): item for key, item in payload.items()}


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)
