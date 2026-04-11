from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from agent_architect_lab.config import Settings
from agent_architect_lab.harness.ledger import ReleaseManifest, get_release_record
from agent_architect_lab.harness.reporting import HarnessReport
from agent_architect_lab.models import utc_now_iso


def artifact_entry(
    kind: str,
    path: str | Path | None,
    *,
    run_id: str | None = None,
    release_name: str | None = None,
    incident_id: str | None = None,
    suite_name: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if path is None:
        return None
    path_text = str(path).strip()
    if not path_text:
        return None
    resolved = Path(path_text).expanduser().resolve()
    payload: dict[str, Any] = {
        "kind": kind,
        "path": str(resolved),
        "file_name": resolved.name,
        "exists": resolved.exists(),
    }
    if run_id:
        payload["run_id"] = run_id
    if release_name:
        payload["release_name"] = release_name
    if incident_id:
        payload["incident_id"] = incident_id
    if suite_name:
        payload["suite_name"] = suite_name
    if metadata:
        payload["metadata"] = dict(metadata)
    return payload


def build_lineage_bundle(
    entries: Iterable[dict[str, Any] | None],
    *,
    label: str,
) -> dict[str, Any]:
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    counts_by_kind: dict[str, int] = {}
    run_ids: set[str] = set()
    for entry in entries:
        if not entry:
            continue
        key = (
            str(entry.get("kind", "")),
            str(entry.get("path", "")),
            str(entry.get("run_id", "")),
            str(entry.get("release_name", "")),
            str(entry.get("incident_id", "")),
        )
        if key in seen:
            continue
        seen.add(key)
        normalized.append(entry)
        kind = str(entry.get("kind", "unknown"))
        counts_by_kind[kind] = counts_by_kind.get(kind, 0) + 1
        run_id = str(entry.get("run_id", "")).strip()
        if run_id:
            run_ids.add(run_id)
    normalized.sort(key=lambda item: (str(item.get("kind", "")), str(item.get("path", ""))))
    return {
        "label": label,
        "generated_at": utc_now_iso(),
        "artifacts": normalized,
        "run_ids": sorted(run_ids),
        "counts": {
            "artifacts": len(normalized),
            "existing_artifacts": sum(1 for item in normalized if item.get("exists")),
            "run_ids": len(run_ids),
            "by_kind": counts_by_kind,
        },
    }


def extend_lineage(
    lineage: dict[str, Any] | None,
    *,
    label: str,
    entries: Iterable[dict[str, Any] | None],
) -> dict[str, Any]:
    existing_entries = []
    if isinstance(lineage, dict):
        existing_entries = list(lineage.get("artifacts", []))
    return build_lineage_bundle([*existing_entries, *entries], label=label)


def build_operator_handoff_lineage(settings: Settings) -> dict[str, Any]:
    return build_lineage_bundle(
        [
            artifact_entry("release_ledger", settings.release_ledger_path),
            artifact_entry("incident_ledger", settings.incident_ledger_path),
            artifact_entry("feedback_ledger", settings.feedback_ledger_path),
        ],
        label="operator_handoff",
    )


def build_governance_summary_lineage(
    settings: Settings,
    *,
    runtime_realism: dict[str, Any] | None = None,
) -> dict[str, Any]:
    entries: list[dict[str, Any] | None] = [
        artifact_entry("release_ledger", settings.release_ledger_path),
        artifact_entry("incident_ledger", settings.incident_ledger_path),
        artifact_entry("feedback_ledger", settings.feedback_ledger_path),
    ]
    runtime_payload = runtime_realism or {}
    latest_planner_shadow = runtime_payload.get("latest_planner_shadow") or {}
    latest_release_command_brief = runtime_payload.get("latest_release_command_brief") or {}
    entries.extend(
        [
            artifact_entry("planner_shadow_report", latest_planner_shadow.get("path")),
            artifact_entry(
                "release_command_brief_json",
                latest_release_command_brief.get("path"),
                release_name=latest_release_command_brief.get("release_name"),
            ),
        ]
    )
    entries.extend(
        _markdown_sibling_entries(
            "planner_shadow_markdown",
            latest_planner_shadow.get("path"),
        )
    )
    entries.extend(
        _markdown_sibling_entries(
            "release_command_brief_markdown",
            latest_release_command_brief.get("path"),
            release_name=latest_release_command_brief.get("release_name"),
        )
    )
    return build_lineage_bundle(entries, label="governance_summary")


def build_weekly_status_lineage(
    settings: Settings,
    *,
    current_governance: dict[str, Any],
    snapshot_paths: list[Path],
) -> dict[str, Any]:
    entries: list[dict[str, Any] | None] = list((current_governance.get("lineage") or {}).get("artifacts", []))
    for snapshot_path in snapshot_paths:
        entries.append(artifact_entry("handoff_snapshot", snapshot_path))
    entries.append(artifact_entry("handoffs_directory", settings.handoffs_dir))
    return build_lineage_bundle(entries, label="weekly_status")


def build_release_lineage(
    settings: Settings,
    *,
    release_name: str,
    include_latest_planner_shadow: bool = False,
    include_latest_release_command_brief: bool = False,
) -> dict[str, Any]:
    entries: list[dict[str, Any] | None] = [
        artifact_entry("release_ledger", settings.release_ledger_path, release_name=release_name),
        artifact_entry("feedback_ledger", settings.feedback_ledger_path, release_name=release_name),
    ]
    try:
        record = get_release_record(release_name, ledger_path=settings.release_ledger_path)
    except KeyError:
        return build_lineage_bundle(entries, label=f"release:{release_name}")

    manifest_path = Path(record.manifest_path)
    entries.append(
        artifact_entry(
            "release_manifest",
            manifest_path,
            release_name=release_name,
        )
    )
    if manifest_path.exists():
        manifest = ReleaseManifest.load(manifest_path)
        for snapshot in manifest.suite_snapshots:
            _append_harness_report_lineage(
                entries,
                settings,
                snapshot.candidate_report_path,
                kind="candidate_report",
                release_name=release_name,
                suite_name=snapshot.suite_name,
                metadata={
                    "baseline_source": snapshot.baseline_source,
                    "recommended_action": snapshot.recommended_action,
                },
            )
            _append_harness_report_lineage(
                entries,
                settings,
                snapshot.baseline_report_path,
                kind="baseline_report",
                release_name=release_name,
                suite_name=snapshot.suite_name,
                metadata={"baseline_source": snapshot.baseline_source},
            )
    if include_latest_planner_shadow:
        _append_latest_planner_shadow_lineage(entries, settings)
    if include_latest_release_command_brief:
        _append_latest_release_command_brief_lineage(entries, settings, release_name=release_name)
    return build_lineage_bundle(entries, label=f"release:{release_name}")


def build_release_runbook_lineage(
    settings: Settings,
    *,
    release_name: str,
    active_incidents: list[dict[str, Any]],
) -> dict[str, Any]:
    entries: list[dict[str, Any] | None] = list(
        build_release_lineage(
            settings,
            release_name=release_name,
            include_latest_planner_shadow=True,
            include_latest_release_command_brief=True,
        ).get("artifacts", [])
    )
    for incident in active_incidents:
        incident_id = incident.get("incident_id")
        entries.append(
            artifact_entry(
                "incident_source_report",
                incident.get("source_report_path"),
                release_name=release_name,
                incident_id=incident_id,
            )
        )
        entries.append(
            artifact_entry(
                "followup_eval_artifact",
                incident.get("followup_eval_path"),
                release_name=release_name,
                incident_id=incident_id,
            )
        )
    return build_lineage_bundle(entries, label=f"release_runbook:{release_name}")


def build_planner_shadow_lineage(
    settings: Settings,
    *,
    suite_name: str,
    report_path: str | Path,
    markdown_path: str | Path | None = None,
) -> dict[str, Any]:
    dataset_path = settings.project_root / "src" / "agent_architect_lab" / "evals" / "datasets" / f"{suite_name}_tasks.jsonl"
    entries = [
        artifact_entry("planner_shadow_report", report_path, suite_name=suite_name),
        artifact_entry("planner_shadow_markdown", markdown_path, suite_name=suite_name),
        artifact_entry("planner_shadow_dataset", dataset_path, suite_name=suite_name),
    ]
    return build_lineage_bundle(entries, label=f"planner_shadow:{suite_name}")


def build_incident_bundle_lineage(
    settings: Settings,
    *,
    incident_record: dict[str, Any],
    bundle_manifest_path: str | Path | None = None,
    incident_report_path: str | Path | None = None,
    handoff_snapshot_path: str | Path | None = None,
    handoff_report_path: str | Path | None = None,
    followup_eval_bundle_path: str | Path | None = None,
) -> dict[str, Any]:
    incident_id = str(incident_record.get("incident_id", "") or "")
    release_name = incident_record.get("release_name")
    entries: list[dict[str, Any] | None] = [
        artifact_entry("incident_ledger", settings.incident_ledger_path, incident_id=incident_id),
        artifact_entry("feedback_ledger", settings.feedback_ledger_path, incident_id=incident_id),
        artifact_entry("incident_bundle_manifest", bundle_manifest_path, incident_id=incident_id),
        artifact_entry("incident_report", incident_report_path, incident_id=incident_id),
        artifact_entry(
            "incident_source_report",
            incident_record.get("source_report_path"),
            incident_id=incident_id,
            release_name=release_name,
        ),
        artifact_entry(
            "followup_eval_artifact",
            incident_record.get("followup_eval_path"),
            incident_id=incident_id,
            release_name=release_name,
        ),
        artifact_entry(
            "followup_eval_bundle",
            followup_eval_bundle_path,
            incident_id=incident_id,
            release_name=release_name,
        ),
        artifact_entry(
            "handoff_snapshot",
            handoff_snapshot_path,
            incident_id=incident_id,
            release_name=release_name,
        ),
        artifact_entry(
            "handoff_report",
            handoff_report_path,
            incident_id=incident_id,
            release_name=release_name,
        ),
    ]
    _append_harness_report_lineage(
        entries,
        settings,
        incident_record.get("source_report_path"),
        kind="incident_source_report",
        release_name=release_name,
        incident_id=incident_id,
    )
    if release_name:
        entries.extend(
            build_release_lineage(
                settings,
                release_name=release_name,
                include_latest_planner_shadow=True,
                include_latest_release_command_brief=True,
            ).get("artifacts", [])
        )
    return build_lineage_bundle(entries, label=f"incident_bundle:{incident_id}")


def artifact_lineage_rows(lineage: dict[str, Any], *, limit: int = 12) -> list[list[object]]:
    rows: list[list[object]] = []
    for entry in list(lineage.get("artifacts", []))[: max(0, limit)]:
        notes: list[str] = []
        if entry.get("run_id"):
            notes.append(f"run={entry['run_id']}")
        if entry.get("release_name"):
            notes.append(f"release={entry['release_name']}")
        if entry.get("incident_id"):
            notes.append(f"incident={entry['incident_id']}")
        if entry.get("suite_name"):
            notes.append(f"suite={entry['suite_name']}")
        metadata = entry.get("metadata") or {}
        for key in sorted(metadata):
            notes.append(f"{key}={metadata[key]}")
        rows.append(
            [
                entry.get("kind"),
                entry.get("file_name"),
                entry.get("exists"),
                ", ".join(notes) if notes else "-",
            ]
        )
    return rows


def _append_harness_report_lineage(
    entries: list[dict[str, Any] | None],
    settings: Settings,
    report_path: str | Path | None,
    *,
    kind: str,
    release_name: str | None = None,
    incident_id: str | None = None,
    suite_name: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    base_entry = artifact_entry(
        kind,
        report_path,
        release_name=release_name,
        incident_id=incident_id,
        suite_name=suite_name,
        metadata=metadata,
    )
    entries.append(base_entry)
    if not base_entry or not base_entry.get("exists"):
        return
    try:
        report = HarnessReport.load(Path(base_entry["path"]))
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return
    for result in report.results:
        run_metadata = {
            "task_id": result.task_id,
            "status": result.status,
        }
        if result.failure_type:
            run_metadata["failure_type"] = result.failure_type
        entries.append(
            artifact_entry(
                "trace",
                settings.traces_dir / f"{result.run_id}.json",
                run_id=result.run_id,
                release_name=release_name,
                incident_id=incident_id,
                suite_name=suite_name or report.suite_name,
                metadata=run_metadata,
            )
        )
        entries.append(
            artifact_entry(
                "checkpoint",
                settings.checkpoints_dir / f"{result.run_id}.checkpoint.json",
                run_id=result.run_id,
                release_name=release_name,
                incident_id=incident_id,
                suite_name=suite_name or report.suite_name,
                metadata=run_metadata,
            )
        )


def _append_latest_planner_shadow_lineage(
    entries: list[dict[str, Any] | None],
    settings: Settings,
) -> None:
    artifact = _find_latest_json_artifact(
        settings.reports_dir.glob("*planner-shadow*.json"),
        required_keys={"suite_name", "candidate_provider", "policy_pass_rate"},
    )
    if artifact is None:
        return
    path, payload = artifact
    entries.append(
        artifact_entry(
            "planner_shadow_report",
            path,
            suite_name=payload.get("suite_name"),
        )
    )
    entries.extend(
        _markdown_sibling_entries(
            "planner_shadow_markdown",
            path,
            suite_name=payload.get("suite_name"),
        )
    )


def _append_latest_release_command_brief_lineage(
    entries: list[dict[str, Any] | None],
    settings: Settings,
    *,
    release_name: str | None = None,
) -> None:
    artifact = _find_latest_json_artifact(
        settings.reports_dir.glob("release-command-*.json"),
        required_keys={"release_name", "pattern", "recommended_action"},
        release_name=release_name,
    )
    if artifact is None:
        return
    path, payload = artifact
    entries.append(
        artifact_entry(
            "release_command_brief_json",
            path,
            release_name=payload.get("release_name"),
        )
    )
    entries.extend(
        _markdown_sibling_entries(
            "release_command_brief_markdown",
            path,
            release_name=payload.get("release_name"),
        )
    )


def _find_latest_json_artifact(
    paths,
    *,
    required_keys: set[str],
    release_name: str | None = None,
) -> tuple[Path, dict[str, Any]] | None:
    candidates: list[tuple[str, Path, dict[str, Any]]] = []
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not required_keys.issubset(set(payload)):
            continue
        if release_name and payload.get("release_name") != release_name:
            continue
        sort_key = str(payload.get("generated_at") or payload.get("created_at") or path.name)
        candidates.append((sort_key, path, payload))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1].name), reverse=True)
    _, path, payload = candidates[0]
    return path, payload


def _markdown_sibling_entries(
    kind: str,
    json_path: str | Path | None,
    *,
    release_name: str | None = None,
    suite_name: str | None = None,
) -> list[dict[str, Any] | None]:
    if json_path is None:
        return []
    markdown_path = Path(str(json_path)).with_suffix(".md")
    return [
        artifact_entry(
            kind,
            markdown_path,
            release_name=release_name,
            suite_name=suite_name,
        )
    ]
