from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any, Mapping, Protocol, runtime_checkable


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
class AuditEvent:
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return dict(self.payload)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "AuditEvent":
        return cls(payload=dict(payload))


@dataclass(slots=True)
class IdempotencyRegistry:
    records: dict[str, IdempotencyRecord] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "records": {
                key: record.to_dict()
                for key, record in sorted(self.records.items())
            }
        }

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

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")


@runtime_checkable
class IdempotencyRepository(Protocol):
    def get(self, idempotency_key: str) -> IdempotencyRecord | None: ...

    def save(self, record: IdempotencyRecord) -> None: ...

    def list_records(self, *, limit: int = 100) -> list[IdempotencyRecord]: ...


@runtime_checkable
class AuditLogRepository(Protocol):
    def append(self, payload: Mapping[str, Any]) -> None: ...

    def list_events(
        self,
        *,
        request_id: str | None = None,
        operation_id: str | None = None,
        limit: int = 100,
    ) -> list[AuditEvent]: ...


class JsonIdempotencyRepository:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = Lock()

    def get(self, idempotency_key: str) -> IdempotencyRecord | None:
        with self._lock:
            registry = IdempotencyRegistry.load(self.path)
        return registry.records.get(idempotency_key)

    def save(self, record: IdempotencyRecord) -> None:
        with self._lock:
            registry = IdempotencyRegistry.load(self.path)
            registry.records[record.idempotency_key] = record
            registry.save(self.path)

    def list_records(self, *, limit: int = 100) -> list[IdempotencyRecord]:
        with self._lock:
            registry = IdempotencyRegistry.load(self.path)
        records = sorted(
            registry.records.values(),
            key=lambda item: (item.committed_at, item.idempotency_key),
            reverse=True,
        )
        return records[:limit]


class JsonAuditLogRepository:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = Lock()

    def append(self, payload: Mapping[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(dict(payload), sort_keys=True) + "\n")

    def list_events(
        self,
        *,
        request_id: str | None = None,
        operation_id: str | None = None,
        limit: int = 100,
    ) -> list[AuditEvent]:
        if not self.path.exists():
            return []
        with self._lock:
            rows = [
                AuditEvent.from_dict(json.loads(line))
                for line in self.path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        if request_id is not None:
            rows = [row for row in rows if row.payload.get("request_id") == request_id]
        if operation_id is not None:
            rows = [row for row in rows if row.payload.get("operation_id") == operation_id]
        rows.sort(
            key=lambda item: (
                str(item.payload.get("occurred_at", "")),
                str(item.payload.get("audit_event_id", "")),
            ),
            reverse=True,
        )
        return rows[:limit]
