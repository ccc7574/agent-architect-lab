from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

from agent_architect_lab.control_plane.jobs import (
    ControlPlaneJob,
    ControlPlaneJobRepository,
    _job_summary,
    _lease_deadline,
    normalize_job_types,
)
from agent_architect_lab.control_plane.storage import AuditEvent, IdempotencyRecord
from agent_architect_lab.control_plane.workers import (
    ControlPlaneWorkerRecord,
    ControlPlaneWorkerRepository,
    summarize_worker_records,
)
from agent_architect_lab.models import utc_now_iso


CONTROL_PLANE_SQLITE_SCHEMA_VERSION = 5
_SCHEMA_NAME = "control_plane"


class SQLiteRepositoryMixin:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection


def get_sqlite_schema_version(path: Path) -> int:
    if not path.exists():
        return 0
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        _ensure_schema_meta_table(connection)
        row = connection.execute(
            "SELECT schema_version FROM control_plane_schema_meta WHERE schema_name = ?",
            (_SCHEMA_NAME,),
        ).fetchone()
        return int(row["schema_version"]) if row is not None else _infer_legacy_schema_version(connection)
    finally:
        connection.close()


def ensure_sqlite_control_plane_schema(path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        return _ensure_sqlite_control_plane_schema(connection)
    finally:
        connection.close()


class SQLiteIdempotencyRepository(SQLiteRepositoryMixin):
    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self._initialize()

    def _initialize(self) -> None:
        with self._lock:
            with self._connect() as connection:
                _ensure_sqlite_control_plane_schema(connection)

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
                _ensure_sqlite_control_plane_schema(connection)

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
                        route_policy_key,
                        actor,
                        role,
                        method,
                        path,
                        status_code,
                        replayed,
                        conflict,
                        payload
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        audit_event_id,
                        str(event.get("occurred_at", "")),
                        _optional_text(event.get("request_id")),
                        _optional_text(event.get("operation_id")),
                        _optional_text(event.get("event_type")),
                        _optional_text(event.get("error_code")),
                        _optional_text(event.get("route_policy_key")),
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
        route_policy_key: str | None = None,
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
            ("route_policy_key", route_policy_key),
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
                _ensure_sqlite_control_plane_schema(connection)

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

    def summarize_jobs(self, *, now: str | None = None) -> dict[str, Any]:
        with self._lock:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT * FROM control_plane_jobs ORDER BY created_at DESC, job_id DESC"
                ).fetchall()
        return _job_summary([_job_from_row(row) for row in rows], now=now or utc_now_iso())

    def claim_next_job(
        self,
        *,
        worker_id: str,
        lease_ttl_s: float,
        allowed_job_types: list[str] | None = None,
    ) -> ControlPlaneJob | None:
        allowed = normalize_job_types(allowed_job_types)
        parameters: list[Any] = []
        sql = """
            SELECT * FROM control_plane_jobs
            WHERE status = 'queued'
        """
        if allowed:
            sql += " AND job_type IN ({})".format(",".join("?" for _ in allowed))
            parameters.extend(allowed)
        sql += """
            ORDER BY created_at ASC, job_id ASC
            LIMIT 1
        """
        with self._lock:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                _requeue_stale_jobs_sql(connection, now=utc_now_iso())
                row = connection.execute(sql, parameters).fetchone()
                if row is None:
                    connection.commit()
                    return None
                now = utc_now_iso()
                lease_expires_at = _lease_deadline(now, lease_ttl_s)
                connection.execute(
                    """
                    UPDATE control_plane_jobs
                    SET status = 'running',
                        attempts = attempts + 1,
                        started_at = ?,
                        updated_at = ?,
                        worker_id = ?,
                        heartbeat_at = ?,
                        lease_expires_at = ?
                    WHERE job_id = ?
                    """,
                    (now, now, worker_id, now, lease_expires_at, str(row["job_id"])),
                )
                updated = connection.execute(
                    "SELECT * FROM control_plane_jobs WHERE job_id = ?",
                    (str(row["job_id"]),),
                ).fetchone()
                connection.commit()
        return _job_from_row(updated) if updated is not None else None

    def heartbeat_job(self, job_id: str, *, worker_id: str, lease_ttl_s: float) -> ControlPlaneJob:
        with self._lock:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT * FROM control_plane_jobs WHERE job_id = ?",
                    (job_id,),
                ).fetchone()
                if row is None:
                    raise KeyError(f"Unknown job '{job_id}'.")
                if str(row["status"]) != "running":
                    raise ValueError(f"Only running jobs can be heartbeated. Job '{job_id}' is currently '{row['status']}'.")
                if _optional_text(row["worker_id"]) != worker_id:
                    raise ValueError(f"Job '{job_id}' is currently leased by '{row['worker_id']}', not '{worker_id}'.")
                now = utc_now_iso()
                connection.execute(
                    """
                    UPDATE control_plane_jobs
                    SET heartbeat_at = ?,
                        lease_expires_at = ?,
                        updated_at = ?
                    WHERE job_id = ?
                    """,
                    (now, _lease_deadline(now, lease_ttl_s), now, job_id),
                )
                updated = connection.execute(
                    "SELECT * FROM control_plane_jobs WHERE job_id = ?",
                    (job_id,),
                ).fetchone()
        return _job_from_row(updated)

    def requeue_stale_jobs(self, *, now: str | None = None) -> list[ControlPlaneJob]:
        with self._lock:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                rows = _requeue_stale_jobs_sql(connection, now=now or utc_now_iso())
                connection.commit()
        return rows

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
                        queue_reason = 'completed',
                        worker_id = NULL,
                        lease_expires_at = NULL,
                        heartbeat_at = ?
                    WHERE job_id = ?
                    """,
                    (json.dumps(result_payload, sort_keys=True), now, now, now, job_id),
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
                            queue_reason = 'automatic_retry',
                            worker_id = NULL,
                            lease_expires_at = NULL,
                            heartbeat_at = ?
                        WHERE job_id = ?
                        """,
                        (latest_error, now, now, job_id),
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
                            queue_reason = 'failed',
                            worker_id = NULL,
                            lease_expires_at = NULL,
                            heartbeat_at = ?
                        WHERE job_id = ?
                        """,
                        (latest_error, latest_error, now, now, now, job_id),
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
                        queue_reason = 'manual_retry',
                        worker_id = NULL,
                        lease_expires_at = NULL
                    WHERE job_id = ?
                    """,
                    (next_max_attempts, now, job_id),
                )
                updated = connection.execute(
                    "SELECT * FROM control_plane_jobs WHERE job_id = ?",
                    (job_id,),
                ).fetchone()
        return _job_from_row(updated)


class SQLiteControlPlaneWorkerStore(SQLiteRepositoryMixin, ControlPlaneWorkerRepository):
    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self._initialize()

    def _initialize(self) -> None:
        with self._lock:
            with self._connect() as connection:
                _ensure_sqlite_control_plane_schema(connection)

    def heartbeat_worker(
        self,
        *,
        worker_id: str,
        managed_by_server: bool,
        poll_interval_s: float,
        lease_ttl_s: float,
        heartbeat_interval_s: float,
        allowed_job_types: list[str] | None = None,
        status: str = "running",
    ) -> ControlPlaneWorkerRecord:
        now = utc_now_iso()
        normalized_job_types = json.dumps(normalize_job_types(allowed_job_types), sort_keys=True)
        with self._lock:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO control_plane_workers (
                        worker_id,
                        status,
                        started_at,
                        updated_at,
                        last_heartbeat_at,
                        managed_by_server,
                        poll_interval_s,
                        lease_ttl_s,
                        heartbeat_interval_s,
                        allowed_job_types
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(worker_id) DO UPDATE SET
                        status = excluded.status,
                        updated_at = excluded.updated_at,
                        last_heartbeat_at = excluded.last_heartbeat_at,
                        managed_by_server = excluded.managed_by_server,
                        poll_interval_s = excluded.poll_interval_s,
                        lease_ttl_s = excluded.lease_ttl_s,
                        heartbeat_interval_s = excluded.heartbeat_interval_s,
                        allowed_job_types = excluded.allowed_job_types
                    """,
                    (
                        worker_id,
                        status,
                        now,
                        now,
                        now,
                        1 if managed_by_server else 0,
                        poll_interval_s,
                        lease_ttl_s,
                        heartbeat_interval_s,
                        normalized_job_types,
                    ),
                )
                row = connection.execute(
                    "SELECT * FROM control_plane_workers WHERE worker_id = ?",
                    (worker_id,),
                ).fetchone()
        return _worker_from_row(row)

    def stop_worker(self, worker_id: str) -> ControlPlaneWorkerRecord | None:
        now = utc_now_iso()
        with self._lock:
            with self._connect() as connection:
                connection.execute(
                    """
                    UPDATE control_plane_workers
                    SET status = 'stopped',
                        updated_at = ?,
                        last_heartbeat_at = ?
                    WHERE worker_id = ?
                    """,
                    (now, now, worker_id),
                )
                row = connection.execute(
                    "SELECT * FROM control_plane_workers WHERE worker_id = ?",
                    (worker_id,),
                ).fetchone()
        return _worker_from_row(row) if row is not None else None

    def list_workers(self, *, status: str | None = None, limit: int = 50) -> list[ControlPlaneWorkerRecord]:
        parameters: list[Any] = []
        sql = "SELECT * FROM control_plane_workers"
        if status is not None:
            sql += " WHERE status = ?"
            parameters.append(status)
        sql += " ORDER BY updated_at DESC, worker_id DESC LIMIT ?"
        parameters.append(limit)
        with self._lock:
            with self._connect() as connection:
                rows = connection.execute(sql, parameters).fetchall()
        return [_worker_from_row(row) for row in rows]

    def summarize_workers(self, *, now: str | None = None, minimum_stale_after_s: float = 15.0) -> dict[str, Any]:
        return summarize_worker_records(
            self.list_workers(limit=1000),
            now=now or utc_now_iso(),
            minimum_stale_after_s=minimum_stale_after_s,
        )


def _ensure_sqlite_control_plane_schema(connection: sqlite3.Connection) -> int:
    _ensure_schema_meta_table(connection)
    current_version = _current_schema_version(connection)
    if current_version == 0 and _has_legacy_tables(connection):
        current_version = _infer_legacy_schema_version(connection)
        _write_schema_version(connection, current_version)
    while current_version < CONTROL_PLANE_SQLITE_SCHEMA_VERSION:
        next_version = current_version + 1
        if next_version == 1:
            _apply_schema_v1(connection)
        elif next_version == 2:
            _apply_schema_v2(connection)
        elif next_version == 3:
            _apply_schema_v3(connection)
        elif next_version == 4:
            _apply_schema_v4(connection)
        elif next_version == 5:
            _apply_schema_v5(connection)
        else:  # pragma: no cover - defensive future guard
            raise ValueError(f"Unsupported SQLite schema migration target: {next_version}")
        _write_schema_version(connection, next_version)
        current_version = next_version
    return current_version


def _ensure_schema_meta_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS control_plane_schema_meta (
            schema_name TEXT PRIMARY KEY,
            schema_version INTEGER NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )


def _current_schema_version(connection: sqlite3.Connection) -> int:
    row = connection.execute(
        "SELECT schema_version FROM control_plane_schema_meta WHERE schema_name = ?",
        (_SCHEMA_NAME,),
    ).fetchone()
    return int(row["schema_version"]) if row is not None else 0


def _write_schema_version(connection: sqlite3.Connection, version: int) -> None:
    connection.execute(
        """
        INSERT OR REPLACE INTO control_plane_schema_meta (
            schema_name,
            schema_version,
            updated_at
        ) VALUES (?, ?, ?)
        """,
        (_SCHEMA_NAME, version, utc_now_iso()),
    )


def _has_legacy_tables(connection: sqlite3.Connection) -> bool:
    return any(
        _has_table(connection, table_name)
        for table_name in ("idempotency_records", "audit_events", "control_plane_jobs", "control_plane_workers")
    )


def _infer_legacy_schema_version(connection: sqlite3.Connection) -> int:
    if _has_table(connection, "control_plane_workers"):
        if _has_column(connection, "control_plane_workers", "allowed_job_types"):
            return 5
        return 4
    if _has_column(connection, "audit_events", "route_policy_key"):
        if _has_column(connection, "control_plane_jobs", "worker_id"):
            return 3
        return 2
    if _has_legacy_tables(connection):
        return 1
    return 0


def _apply_schema_v1(connection: sqlite3.Connection) -> None:
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
    _ensure_v1_indexes(connection)


def _apply_schema_v2(connection: sqlite3.Connection) -> None:
    _apply_schema_v1(connection)
    if not _has_column(connection, "audit_events", "route_policy_key"):
        connection.execute("ALTER TABLE audit_events ADD COLUMN route_policy_key TEXT")
        rows = connection.execute(
            "SELECT audit_event_id, payload FROM audit_events WHERE route_policy_key IS NULL"
        ).fetchall()
        for row in rows:
            payload = _json_dict(row["payload"]) or {}
            connection.execute(
                "UPDATE audit_events SET route_policy_key = ? WHERE audit_event_id = ?",
                (_optional_text(payload.get("route_policy_key")), str(row["audit_event_id"])),
            )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_route_policy_key ON audit_events (route_policy_key, event_type, error_code)"
    )
    _ensure_v1_indexes(connection)


def _apply_schema_v3(connection: sqlite3.Connection) -> None:
    _apply_schema_v2(connection)
    if not _has_column(connection, "control_plane_jobs", "worker_id"):
        connection.execute("ALTER TABLE control_plane_jobs ADD COLUMN worker_id TEXT")
    if not _has_column(connection, "control_plane_jobs", "lease_expires_at"):
        connection.execute("ALTER TABLE control_plane_jobs ADD COLUMN lease_expires_at TEXT")
    if not _has_column(connection, "control_plane_jobs", "heartbeat_at"):
        connection.execute("ALTER TABLE control_plane_jobs ADD COLUMN heartbeat_at TEXT")
    _ensure_v1_indexes(connection)


def _apply_schema_v4(connection: sqlite3.Connection) -> None:
    _apply_schema_v3(connection)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS control_plane_workers (
            worker_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_heartbeat_at TEXT NOT NULL,
            managed_by_server INTEGER NOT NULL DEFAULT 0,
            poll_interval_s REAL NOT NULL,
            lease_ttl_s REAL NOT NULL,
            heartbeat_interval_s REAL NOT NULL
        )
        """
    )
    _ensure_v1_indexes(connection)


def _apply_schema_v5(connection: sqlite3.Connection) -> None:
    _apply_schema_v4(connection)
    if not _has_column(connection, "control_plane_workers", "allowed_job_types"):
        connection.execute(
            "ALTER TABLE control_plane_workers ADD COLUMN allowed_job_types TEXT NOT NULL DEFAULT '[]'"
        )
    _ensure_v1_indexes(connection)


def _ensure_v1_indexes(connection: sqlite3.Connection) -> None:
    if _has_table(connection, "idempotency_records"):
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_idempotency_committed_at ON idempotency_records (committed_at DESC, idempotency_key DESC)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_idempotency_operation_id ON idempotency_records (operation_id)"
        )
    if _has_table(connection, "audit_events"):
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
    if _has_table(connection, "control_plane_jobs"):
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_jobs_status_created_at ON control_plane_jobs (status, created_at ASC, job_id ASC)"
        )
        if _has_column(connection, "control_plane_jobs", "lease_expires_at"):
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_jobs_status_lease_expires_at ON control_plane_jobs (status, lease_expires_at ASC, created_at ASC, job_id ASC)"
            )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_jobs_request_id ON control_plane_jobs (request_id)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_jobs_operation_id ON control_plane_jobs (operation_id)"
        )
    if _has_table(connection, "control_plane_workers"):
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_workers_status_updated_at ON control_plane_workers (status, updated_at DESC, worker_id DESC)"
        )


def _has_table(connection: sqlite3.Connection, table_name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _has_column(connection: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    if not _has_table(connection, table_name):
        return False
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(str(row["name"]) == column_name for row in rows)


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
            completed_at,
            worker_id,
            lease_expires_at,
            heartbeat_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            job.worker_id,
            job.lease_expires_at,
            job.heartbeat_at,
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
        worker_id=_optional_text(row["worker_id"]) if "worker_id" in row.keys() else None,
        lease_expires_at=_optional_text(row["lease_expires_at"]) if "lease_expires_at" in row.keys() else None,
        heartbeat_at=_optional_text(row["heartbeat_at"]) if "heartbeat_at" in row.keys() else None,
    )


def _worker_from_row(row: sqlite3.Row) -> ControlPlaneWorkerRecord:
    return ControlPlaneWorkerRecord(
        worker_id=str(row["worker_id"]),
        status=str(row["status"]),
        started_at=str(row["started_at"]),
        updated_at=str(row["updated_at"]),
        last_heartbeat_at=str(row["last_heartbeat_at"]),
        managed_by_server=bool(int(row["managed_by_server"])),
        poll_interval_s=float(row["poll_interval_s"]),
        lease_ttl_s=float(row["lease_ttl_s"]),
        heartbeat_interval_s=float(row["heartbeat_interval_s"]),
        allowed_job_types=_json_list(row["allowed_job_types"]) if "allowed_job_types" in row.keys() else [],
    )


def _requeue_stale_jobs_sql(connection: sqlite3.Connection, *, now: str) -> list[ControlPlaneJob]:
    if not _has_column(connection, "control_plane_jobs", "lease_expires_at"):
        return []
    rows = connection.execute(
        """
        SELECT * FROM control_plane_jobs
        WHERE status = 'running'
          AND lease_expires_at IS NOT NULL
          AND lease_expires_at <= ?
        ORDER BY lease_expires_at ASC, created_at ASC, job_id ASC
        """,
        (now,),
    ).fetchall()
    if not rows:
        return []
    connection.execute(
        """
        UPDATE control_plane_jobs
        SET status = 'queued',
            updated_at = ?,
            completed_at = NULL,
            queue_reason = 'lease_expired_retry',
            worker_id = NULL,
            lease_expires_at = NULL,
            heartbeat_at = ?
        WHERE status = 'running'
          AND lease_expires_at IS NOT NULL
          AND lease_expires_at <= ?
        """,
        (now, now, now),
    )
    updated = connection.execute(
        """
        SELECT * FROM control_plane_jobs
        WHERE job_id IN ({})
        ORDER BY updated_at DESC, job_id DESC
        """.format(",".join("?" for _ in rows)),
        tuple(str(row["job_id"]) for row in rows),
    ).fetchall()
    return [_job_from_row(row) for row in updated]


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


def _json_list(value: Any) -> list[str]:
    if value is None:
        return []
    try:
        payload = json.loads(str(value))
    except json.JSONDecodeError:
        return normalize_job_types(value)
    if not isinstance(payload, list):
        return normalize_job_types(payload)
    return normalize_job_types(payload)


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)
