from __future__ import annotations

import json
import shutil
import tempfile
import zipfile
from hashlib import sha256
from pathlib import Path
from re import sub
from typing import Any

from agent_architect_lab.config import Settings
from agent_architect_lab.harness.incidents import IncidentLedger
from agent_architect_lab.harness.ledger import ReleaseLedger, ReleaseManifest
from agent_architect_lab.models import utc_now_iso


LEDGER_BACKUP_KIND = "release_and_incident_ledgers"


def build_ledger_storage_status(settings: Settings) -> dict[str, Any]:
    release_ledger = ReleaseLedger.load(settings.release_ledger_path)
    incident_ledger = IncidentLedger.load(settings.incident_ledger_path)
    manifest_by_release = _discover_release_manifests(
        release_ledger=release_ledger,
        release_manifests_dir=settings.release_manifests_dir,
    )
    release_names = {record.release_name for record in release_ledger.records}
    missing_release_manifests = sorted(release_names - set(manifest_by_release))
    orphan_release_manifests = sorted(set(manifest_by_release) - release_names)
    incidents_missing_release_records = sorted(
        {
            record.release_name
            for record in incident_ledger.records
            if record.release_name and record.release_name not in release_names
        }
    )

    files = [
        _file_status(
            "release_ledger",
            settings.release_ledger_path,
            record_count=len(release_ledger.records),
        ),
        _file_status(
            "incident_ledger",
            settings.incident_ledger_path,
            record_count=len(incident_ledger.records),
        ),
    ]
    return {
        "kind": LEDGER_BACKUP_KIND,
        "artifacts_dir": str(settings.artifacts_dir),
        "backups_dir": str(settings.artifacts_dir / "ledger-backups"),
        "restore_drills_dir": str(settings.artifacts_dir / "ledger-restore-drills"),
        "files": files,
        "counts": {
            "release_records": len(release_ledger.records),
            "incident_records": len(incident_ledger.records),
            "release_manifests": len(manifest_by_release),
        },
        "integrity": {
            "valid": not missing_release_manifests and not incidents_missing_release_records,
            "missing_release_manifests": missing_release_manifests,
            "orphan_release_manifests": orphan_release_manifests,
            "incidents_missing_release_records": incidents_missing_release_records,
        },
    }


def backup_release_and_incident_ledgers(
    settings: Settings,
    *,
    output: str = "",
    label: str = "",
) -> dict[str, Any]:
    backups_dir = settings.artifacts_dir / "ledger-backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    timestamp = utc_now_iso().replace(":", "").replace("+", "_")
    safe_label = sub(r"[^a-zA-Z0-9._-]+", "-", label.strip()).strip("-")
    file_name = f"release-incident-ledgers-backup-{timestamp}"
    if safe_label:
        file_name += f"-{safe_label}"
    destination = Path(output) if output else backups_dir / f"{file_name}.zip"
    destination.parent.mkdir(parents=True, exist_ok=True)

    release_ledger = ReleaseLedger.load(settings.release_ledger_path)
    manifest_by_release = _discover_release_manifests(
        release_ledger=release_ledger,
        release_manifests_dir=settings.release_manifests_dir,
    )
    entries: list[dict[str, Any]] = []
    manifest = {
        "kind": LEDGER_BACKUP_KIND,
        "generated_at": utc_now_iso(),
        "storage_status": build_ledger_storage_status(settings),
        "entries": entries,
    }

    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        release_entry = _add_file_to_archive(
            archive,
            settings.release_ledger_path,
            arcname="releases/release-ledger.json",
            kind="release_ledger",
            extra={"record_count": len(release_ledger.records)},
        )
        if release_entry is not None:
            entries.append(release_entry)

        incident_ledger = IncidentLedger.load(settings.incident_ledger_path)
        incident_entry = _add_file_to_archive(
            archive,
            settings.incident_ledger_path,
            arcname="incidents/incident-ledger.json",
            kind="incident_ledger",
            extra={"record_count": len(incident_ledger.records)},
        )
        if incident_entry is not None:
            entries.append(incident_entry)

        for release_name, manifest_record in sorted(manifest_by_release.items()):
            entry = _add_file_to_archive(
                archive,
                manifest_record["path"],
                arcname=f"releases/manifests/{release_name}.json",
                kind="release_manifest",
                extra={"release_name": release_name},
            )
            if entry is not None:
                entries.append(entry)

        archive.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True))

    return {
        "saved_to": str(destination),
        "generated_at": manifest["generated_at"],
        "entries": entries,
        "sha256": _file_sha256(destination),
    }


def verify_release_and_incident_ledger_backup(
    backup_path: str,
    *,
    expected_sha256: str = "",
) -> dict[str, Any]:
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
        if manifest.get("kind") != LEDGER_BACKUP_KIND:
            raise ValueError("Backup manifest declares an unsupported ledger backup kind.")
        with tempfile.TemporaryDirectory(prefix="agent-lab-ledger-verify-") as tmp_dir:
            archive.extractall(tmp_dir)
            validation = _validate_extracted_backup(Path(tmp_dir))

    return {
        "backup_path": str(path),
        "archive_sha256": archive_sha256,
        "manifest": manifest,
        **validation,
    }


def restore_release_and_incident_ledger_backup(
    settings: Settings,
    *,
    backup_path: str,
    output_dir: str = "",
    label: str = "",
) -> dict[str, Any]:
    verification = verify_release_and_incident_ledger_backup(backup_path)
    restore_root = settings.artifacts_dir / "ledger-restore-drills"
    restore_root.mkdir(parents=True, exist_ok=True)
    timestamp = utc_now_iso().replace(":", "").replace("+", "_")
    safe_label = sub(r"[^a-zA-Z0-9._-]+", "-", label.strip()).strip("-")
    destination = Path(output_dir) if output_dir else restore_root / (
        f"restore-{timestamp}" + (f"-{safe_label}" if safe_label else "")
    )
    destination.mkdir(parents=True, exist_ok=True)

    source_path = Path(backup_path)
    with zipfile.ZipFile(source_path) as archive:
        archive.extractall(destination)

    restored_files = sorted(
        str(path.relative_to(destination))
        for path in destination.rglob("*")
        if path.is_file()
    )
    validation = _validate_extracted_backup(destination)
    return {
        "backup_path": str(source_path),
        "restored_to": str(destination),
        "archive_sha256": verification["archive_sha256"],
        "restored_files": restored_files,
        "validation": validation,
    }


def _validate_extracted_backup(root: Path) -> dict[str, Any]:
    release_ledger = ReleaseLedger.load(root / "releases" / "release-ledger.json")
    incident_ledger = IncidentLedger.load(root / "incidents" / "incident-ledger.json")
    manifest_dir = root / "releases" / "manifests"
    manifest_by_release = {}
    if manifest_dir.exists():
        for path in sorted(manifest_dir.glob("*.json")):
            manifest = ReleaseManifest.load(path)
            if manifest.release_name in manifest_by_release:
                raise ValueError(f"Duplicate release manifest found for '{manifest.release_name}'.")
            manifest_by_release[manifest.release_name] = str(path)

    release_names = {record.release_name for record in release_ledger.records}
    missing_release_manifests = sorted(release_names - set(manifest_by_release))
    incidents_missing_release_records = sorted(
        {
            record.release_name
            for record in incident_ledger.records
            if record.release_name and record.release_name not in release_names
        }
    )
    if missing_release_manifests:
        raise ValueError(
            "Backup restore drill is missing release manifests for: "
            + ", ".join(missing_release_manifests)
        )
    if incidents_missing_release_records:
        raise ValueError(
            "Incident ledger references unknown releases: "
            + ", ".join(incidents_missing_release_records)
        )

    return {
        "validated": True,
        "counts": {
            "release_records": len(release_ledger.records),
            "incident_records": len(incident_ledger.records),
            "release_manifests": len(manifest_by_release),
        },
        "integrity": {
            "valid": True,
            "missing_release_manifests": [],
            "orphan_release_manifests": sorted(set(manifest_by_release) - release_names),
            "incidents_missing_release_records": [],
        },
    }


def _discover_release_manifests(
    *,
    release_ledger: ReleaseLedger,
    release_manifests_dir: Path,
) -> dict[str, dict[str, Any]]:
    candidates: list[Path] = []
    for record in release_ledger.records:
        manifest_path = Path(record.manifest_path)
        if manifest_path.exists():
            candidates.append(manifest_path)
    if release_manifests_dir.exists():
        candidates.extend(sorted(release_manifests_dir.glob("*.json")))

    manifest_by_release: dict[str, dict[str, Any]] = {}
    for path in candidates:
        resolved = path.resolve()
        manifest = ReleaseManifest.load(resolved)
        existing = manifest_by_release.get(manifest.release_name)
        if existing is not None and Path(existing["path"]) != resolved:
            raise ValueError(f"Duplicate release manifest found for '{manifest.release_name}'.")
        manifest_by_release[manifest.release_name] = {
            "path": resolved,
            "manifest": manifest,
        }
    return manifest_by_release


def _add_file_to_archive(
    archive: zipfile.ZipFile,
    source_path: Path,
    *,
    arcname: str,
    kind: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not source_path.exists():
        return None
    archive.write(source_path, arcname=arcname)
    payload = {
        "kind": kind,
        "source_path": str(source_path.resolve()),
        "archived_as": arcname,
        "size_bytes": source_path.stat().st_size,
    }
    if extra:
        payload.update(extra)
    return payload


def _file_status(name: str, path: Path, **extra: Any) -> dict[str, Any]:
    payload = {
        "name": name,
        "path": str(path),
        "exists": path.exists(),
        "size_bytes": path.stat().st_size if path.exists() else 0,
    }
    payload.update(extra)
    return payload


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
