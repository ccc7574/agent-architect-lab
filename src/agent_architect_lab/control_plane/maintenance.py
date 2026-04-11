from __future__ import annotations

import json
import os
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
                settings.control_plane_worker_registry_path,
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


def verify_control_plane_backup(backup_path: str, *, expected_sha256: str = "") -> dict[str, Any]:
    path = Path(backup_path)
    if not path.exists():
        raise ValueError(f"Backup archive not found: {path}")
    archive_sha256 = _file_sha256(path)
    if expected_sha256 and archive_sha256 != expected_sha256:
        raise ValueError("Backup archive SHA256 does not match the expected value.")
    with zipfile.ZipFile(path) as archive:
        names = sorted(archive.namelist())
        if "manifest.json" not in names:
            raise ValueError("Backup archive is missing manifest.json.")
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        backend = str(manifest.get("backend", "") or "")
        if backend not in {"json", "sqlite"}:
            raise ValueError("Backup manifest declares an unsupported backend.")
        entries = list(manifest.get("entries", []))
        if backend == "sqlite":
            payload = _verify_sqlite_backup_archive(archive, names, entries)
        else:
            payload = _verify_json_backup_archive(archive, names, entries)
    return {
        "backup_path": str(path),
        "archive_sha256": archive_sha256,
        "backend": backend,
        "manifest": manifest,
        **payload,
    }


def restore_control_plane_backup(
    settings: Settings,
    *,
    backup_path: str,
    output_dir: str = "",
    label: str = "",
) -> dict[str, Any]:
    verification = verify_control_plane_backup(backup_path)
    source_path = Path(backup_path)
    restore_root = settings.control_plane_dir / "restore-drills"
    restore_root.mkdir(parents=True, exist_ok=True)
    timestamp = utc_now_iso().replace(":", "").replace("+", "_")
    safe_label = sub(r"[^a-zA-Z0-9._-]+", "-", label.strip()).strip("-")
    destination = Path(output_dir) if output_dir else restore_root / (
        f"restore-{timestamp}" + (f"-{safe_label}" if safe_label else "")
    )
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(source_path) as archive:
        archive.extractall(destination)
    restored_files = sorted(
        str(path.relative_to(destination))
        for path in destination.rglob("*")
        if path.is_file()
    )
    validation = _validate_restored_backup(destination, backend=verification["backend"])
    return {
        "backup_path": str(source_path),
        "restored_to": str(destination),
        "backend": verification["backend"],
        "archive_sha256": verification["archive_sha256"],
        "restored_files": restored_files,
        "validation": validation,
    }


def _build_json_status(settings: Settings) -> dict[str, Any]:
    files = [
        _file_status("mutation_audit_log", settings.control_plane_request_log_path, line_count=_count_non_empty_lines(settings.control_plane_request_log_path)),
        _file_status("idempotency_registry", settings.control_plane_idempotency_path, record_count=_json_mapping_count(settings.control_plane_idempotency_path, "records")),
        _file_status("job_registry", settings.control_plane_job_registry_path, record_count=_json_list_count(settings.control_plane_job_registry_path, "jobs")),
        _file_status("worker_registry", settings.control_plane_worker_registry_path, record_count=_json_list_count(settings.control_plane_worker_registry_path, "workers")),
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
            "workers": files[3]["record_count"],
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
                "workers": 0,
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
                "workers": _table_count(connection, "control_plane_workers"),
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


def _verify_sqlite_backup_archive(
    archive: zipfile.ZipFile,
    names: list[str],
    entries: list[dict[str, Any]],
) -> dict[str, Any]:
    sqlite_names = [name for name in names if name.startswith("sqlite/") and name.endswith(".sqlite3")]
    if not sqlite_names:
        raise ValueError("SQLite backup archive is missing the database payload.")
    sqlite_name = sqlite_names[0]
    with tempfile.TemporaryDirectory(prefix="agent-lab-control-plane-verify-") as tmp_dir:
        extracted_path = Path(tmp_dir) / Path(sqlite_name).name
        with extracted_path.open("wb") as handle:
            handle.write(archive.read(sqlite_name))
        connection = sqlite3.connect(extracted_path)
        try:
            connection.row_factory = sqlite3.Row
            integrity_check = str(connection.execute("PRAGMA quick_check").fetchone()[0])
            audit_events = _table_count(connection, "audit_events")
            idempotency_records = _table_count(connection, "idempotency_records")
            jobs = _table_count(connection, "control_plane_jobs")
        finally:
            connection.close()
    if integrity_check != "ok":
        raise ValueError(f"SQLite backup integrity check failed: {integrity_check}")
    return {
        "validated": True,
        "entries": entries,
        "sqlite_database": sqlite_name,
        "counts": {
            "audit_events": audit_events,
            "idempotency_records": idempotency_records,
            "jobs": jobs,
        },
        "integrity_check": integrity_check,
    }


def _verify_json_backup_archive(
    archive: zipfile.ZipFile,
    names: list[str],
    entries: list[dict[str, Any]],
) -> dict[str, Any]:
    required_names = {
        "json/mutation-requests.jsonl",
        "json/idempotency-registry.json",
        "json/job-registry.json",
        "json/worker-registry.json",
    }
    missing = sorted(name for name in required_names if name not in names)
    if missing:
        raise ValueError(f"JSON backup archive is missing required entries: {', '.join(missing)}")
    audit_events = sum(
        1
        for line in archive.read("json/mutation-requests.jsonl").decode("utf-8").splitlines()
        if line.strip()
    )
    idempotency_payload = json.loads(archive.read("json/idempotency-registry.json").decode("utf-8"))
    jobs_payload = json.loads(archive.read("json/job-registry.json").decode("utf-8"))
    workers_payload = json.loads(archive.read("json/worker-registry.json").decode("utf-8"))
    return {
        "validated": True,
        "entries": entries,
        "counts": {
            "audit_events": audit_events,
            "idempotency_records": len(idempotency_payload.get("records", {})),
            "jobs": len(jobs_payload.get("jobs", [])),
            "workers": len(workers_payload.get("workers", [])),
        },
    }


def _validate_restored_backup(destination: Path, *, backend: str) -> dict[str, Any]:
    manifest_path = destination / "manifest.json"
    if not manifest_path.exists():
        raise ValueError("Restored backup is missing manifest.json.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if backend == "sqlite":
        sqlite_files = list((destination / "sqlite").glob("*.sqlite3"))
        if not sqlite_files:
            raise ValueError("Restored SQLite backup is missing the SQLite database file.")
        sqlite_path = sqlite_files[0]
        connection = sqlite3.connect(sqlite_path)
        try:
            connection.row_factory = sqlite3.Row
            integrity_check = str(connection.execute("PRAGMA quick_check").fetchone()[0])
            counts = {
                "audit_events": _table_count(connection, "audit_events"),
                "idempotency_records": _table_count(connection, "idempotency_records"),
                "jobs": _table_count(connection, "control_plane_jobs"),
                "workers": _table_count(connection, "control_plane_workers"),
            }
        finally:
            connection.close()
        if integrity_check != "ok":
            raise ValueError(f"Restored SQLite backup integrity check failed: {integrity_check}")
        return {
            "validated": True,
            "backend": backend,
            "manifest_backend": manifest.get("backend"),
            "integrity_check": integrity_check,
            "counts": counts,
        }
    json_dir = destination / "json"
    if not json_dir.exists():
        raise ValueError("Restored JSON backup is missing the json/ directory.")
    audit_events = _count_non_empty_lines(json_dir / "mutation-requests.jsonl")
    idempotency_records = _json_mapping_count(json_dir / "idempotency-registry.json", "records")
    jobs = _json_list_count(json_dir / "job-registry.json", "jobs")
    workers = _json_list_count(json_dir / "worker-registry.json", "workers")
    return {
        "validated": True,
        "backend": backend,
        "manifest_backend": manifest.get("backend"),
        "counts": {
            "audit_events": audit_events,
            "idempotency_records": idempotency_records,
            "jobs": jobs,
            "workers": workers,
        },
    }
