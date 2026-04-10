from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import zipfile
from hashlib import sha256
from pathlib import Path
from re import sub
from typing import Any

from agent_architect_lab.config import Settings
from agent_architect_lab.models import utc_now_iso


def build_control_plane_storage_status(settings: Settings) -> dict[str, Any]:
    if settings.control_plane_storage_backend == "sqlite":
        return _build_sqlite_status(settings)
    return _build_json_status(settings)


def backup_control_plane_storage(
    settings: Settings,
    *,
    output: str = "",
    label: str = "",
) -> dict[str, Any]:
    backups_dir = settings.control_plane_dir / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    timestamp = utc_now_iso().replace(":", "").replace("+", "_")
    safe_label = sub(r"[^a-zA-Z0-9._-]+", "-", label.strip()).strip("-")
    file_name = f"control-plane-backup-{timestamp}"
    if safe_label:
        file_name += f"-{safe_label}"
    destination = Path(output) if output else backups_dir / f"{file_name}.zip"
    destination.parent.mkdir(parents=True, exist_ok=True)

    entries: list[dict[str, Any]] = []
    manifest = {
        "generated_at": utc_now_iso(),
        "backend": settings.control_plane_storage_backend,
        "storage_status": build_control_plane_storage_status(settings),
        "entries": entries,
    }
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        if settings.control_plane_storage_backend == "sqlite":
            sqlite_entry = _backup_sqlite_database(settings.control_plane_sqlite_path, archive)
            if sqlite_entry is not None:
                entries.append(sqlite_entry)
        else:
            for source_path in (
                settings.control_plane_request_log_path,
                settings.control_plane_idempotency_path,
                settings.control_plane_job_registry_path,
            ):
                entry = _add_file_to_archive(
                    archive,
                    source_path,
                    arcname=f"json/{source_path.name}",
                )
                if entry is not None:
                    entries.append(entry)
        archive.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True))

    return {
        "saved_to": str(destination),
        "backend": settings.control_plane_storage_backend,
        "generated_at": manifest["generated_at"],
        "entries": entries,
        "sha256": _file_sha256(destination),
    }


def _build_json_status(settings: Settings) -> dict[str, Any]:
    files = [
        _file_status("mutation_audit_log", settings.control_plane_request_log_path, line_count=_count_non_empty_lines(settings.control_plane_request_log_path)),
        _file_status("idempotency_registry", settings.control_plane_idempotency_path, record_count=_json_mapping_count(settings.control_plane_idempotency_path, "records")),
        _file_status("job_registry", settings.control_plane_job_registry_path, record_count=_json_list_count(settings.control_plane_job_registry_path, "jobs")),
    ]
    return {
        "backend": "json",
        "control_plane_dir": str(settings.control_plane_dir),
        "backups_dir": str(settings.control_plane_dir / "backups"),
        "files": files,
        "counts": {
            "audit_events": files[0]["line_count"],
            "idempotency_records": files[1]["record_count"],
            "jobs": files[2]["record_count"],
        },
    }


def _build_sqlite_status(settings: Settings) -> dict[str, Any]:
    from agent_architect_lab.control_plane.sqlite_repositories import get_sqlite_schema_version

    db_path = settings.control_plane_sqlite_path
    file_size_bytes = db_path.stat().st_size if db_path.exists() else 0
    if not db_path.exists():
        return {
            "backend": "sqlite",
            "path": str(db_path),
            "exists": False,
            "schema_version": 0,
            "file_size_bytes": file_size_bytes,
            "integrity_check": "missing",
            "counts": {
                "audit_events": 0,
                "idempotency_records": 0,
                "jobs": 0,
            },
        }
    connection = sqlite3.connect(db_path)
    try:
        connection.row_factory = sqlite3.Row
        integrity_check = str(connection.execute("PRAGMA quick_check").fetchone()[0])
        page_count = int(connection.execute("PRAGMA page_count").fetchone()[0])
        page_size = int(connection.execute("PRAGMA page_size").fetchone()[0])
        return {
            "backend": "sqlite",
            "path": str(db_path),
            "exists": True,
            "schema_version": get_sqlite_schema_version(db_path),
            "file_size_bytes": file_size_bytes,
            "integrity_check": integrity_check,
            "page_count": page_count,
            "page_size": page_size,
            "counts": {
                "audit_events": _table_count(connection, "audit_events"),
                "idempotency_records": _table_count(connection, "idempotency_records"),
                "jobs": _table_count(connection, "control_plane_jobs"),
            },
        }
    finally:
        connection.close()


def _backup_sqlite_database(path: Path, archive: zipfile.ZipFile) -> dict[str, Any] | None:
    if not path.exists():
        return None
    with tempfile.TemporaryDirectory(prefix="agent-lab-control-plane-backup-") as tmp_dir:
        snapshot_path = Path(tmp_dir) / path.name
        source = sqlite3.connect(path)
        destination = sqlite3.connect(snapshot_path)
        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()
        archive.write(snapshot_path, arcname=f"sqlite/{path.name}")
        return {
            "kind": "sqlite_database",
            "source_path": str(path),
            "archived_as": f"sqlite/{path.name}",
            "size_bytes": snapshot_path.stat().st_size,
        }


def _add_file_to_archive(
    archive: zipfile.ZipFile,
    source_path: Path,
    *,
    arcname: str,
) -> dict[str, Any] | None:
    if not source_path.exists():
        return None
    archive.write(source_path, arcname=arcname)
    return {
        "kind": "artifact_file",
        "source_path": str(source_path),
        "archived_as": arcname,
        "size_bytes": source_path.stat().st_size,
    }


def _file_status(name: str, path: Path, **extra: Any) -> dict[str, Any]:
    payload = {
        "name": name,
        "path": str(path),
        "exists": path.exists(),
        "size_bytes": path.stat().st_size if path.exists() else 0,
    }
    payload.update(extra)
    return payload


def _count_non_empty_lines(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def _json_mapping_count(path: Path, key: str) -> int:
    if not path.exists():
        return 0
    payload = json.loads(path.read_text(encoding="utf-8"))
    value = payload.get(key, {})
    return len(value) if isinstance(value, dict) else 0


def _json_list_count(path: Path, key: str) -> int:
    if not path.exists():
        return 0
    payload = json.loads(path.read_text(encoding="utf-8"))
    value = payload.get(key, [])
    return len(value) if isinstance(value, list) else 0


def _table_count(connection: sqlite3.Connection, table_name: str) -> int:
    row = connection.execute(f"SELECT COUNT(*) AS count FROM {table_name}").fetchone()
    return int(row["count"]) if row is not None else 0


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        shutil.copyfileobj(handle, _HashWriter(digest))
    return digest.hexdigest()


class _HashWriter:
    def __init__(self, digest) -> None:
        self.digest = digest

    def write(self, data: bytes) -> int:
        self.digest.update(data)
        return len(data)
