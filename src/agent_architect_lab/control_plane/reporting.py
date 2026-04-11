from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from re import sub
from typing import Any

from agent_architect_lab.artifact_lineage import (
    artifact_entry,
    artifact_lineage_rows,
    build_governance_summary_lineage,
    build_operator_handoff_lineage,
    build_planner_shadow_lineage,
    build_release_runbook_lineage,
    build_weekly_status_lineage,
)
from agent_architect_lab.agent.orchestration import export_release_command_brief
from agent_architect_lab.config import Settings
from agent_architect_lab.harness.incidents import get_incident_review_board, list_incidents
from agent_architect_lab.harness.ledger import (
    get_environment_history,
    get_environment_status,
    get_approval_review_board,
    get_operator_handoff,
    get_override_review_board,
    get_release_readiness_digest,
    get_release_record,
    get_release_risk_board,
    get_rollout_matrix,
    list_active_overrides,
    list_releases,
)
from agent_architect_lab.harness.planner_shadow import (
    export_planner_shadow_markdown,
    run_planner_shadow_suite,
)
from agent_architect_lab.llm.factory import create_planner_provider
from agent_architect_lab.models import utc_now_iso


def build_runtime_realism_payload(settings: Settings) -> dict[str, Any]:
    planner_shadow_reports = _load_runtime_json_artifacts(
        settings.reports_dir.glob("*planner-shadow*.json"),
        required_keys={"suite_name", "candidate_provider", "policy_pass_rate"},
    )
    release_command_briefs = _load_runtime_json_artifacts(
        settings.reports_dir.glob("release-command-*.json"),
        required_keys={"release_name", "pattern", "recommended_action"},
    )
    latest_planner_shadow = planner_shadow_reports[0] if planner_shadow_reports else None
    latest_release_command_brief = release_command_briefs[0] if release_command_briefs else None
    return {
        "latest_planner_shadow": latest_planner_shadow,
        "latest_release_command_brief": latest_release_command_brief,
        "planner_shadow_reports": planner_shadow_reports[:10],
        "release_command_briefs": release_command_briefs[:10],
        "metrics": {
            "planner_shadow_report_count": len(planner_shadow_reports),
            "release_command_brief_count": len(release_command_briefs),
            "latest_planner_shadow_passed": (
                latest_planner_shadow.get("all_passed") if isinstance(latest_planner_shadow, dict) else None
            ),
            "latest_release_command_action": (
                latest_release_command_brief.get("recommended_action")
                if isinstance(latest_release_command_brief, dict)
                else None
            ),
        },
    }


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
    runtime_realism = build_runtime_realism_payload(settings)
    payload = {
        "generated_at": utc_now_iso(),
        "environments": selected_environments,
        "release_risk_board": release_risk_board,
        "approval_review_board": approval_review_board,
        "incident_review_board": incident_review_board,
        "override_review_board": override_review_board,
        "active_incidents": active_incidents,
        "active_overrides": active_overrides,
        "releases": releases,
        "runtime_realism": runtime_realism,
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
            "planner_shadow_report_count": runtime_realism["metrics"]["planner_shadow_report_count"],
            "release_command_brief_count": runtime_realism["metrics"]["release_command_brief_count"],
        },
    }
    payload["lineage"] = build_governance_summary_lineage(settings, runtime_realism=runtime_realism)
    return payload


def build_operator_handoff_payload(
    settings: Settings,
    *,
    environments: list[str],
    release_limit: int,
    override_limit: int,
) -> dict[str, Any]:
    handoff = get_operator_handoff(
        environments=environments or settings.environment_names,
        ledger_path=settings.release_ledger_path,
        production_soak_minutes=settings.production_soak_minutes,
        required_approver_roles=settings.production_required_approver_roles,
        environment_policies=settings.environment_policies,
        environment_freeze_windows=settings.environment_freeze_windows,
        override_expiring_soon_minutes=settings.override_expiring_soon_minutes,
        release_stale_minutes=settings.release_stale_minutes,
        approval_stale_minutes=settings.approval_stale_minutes,
        release_limit=release_limit,
        override_limit=override_limit,
    )
    incident_review_board = get_incident_review_board(
        ledger_path=settings.incident_ledger_path,
        stale_minutes=settings.incident_stale_minutes,
        status=None,
        limit=override_limit,
    )
    active_incidents = [
        row.to_dict()
        for row in list_incidents(
            ledger_path=settings.incident_ledger_path,
            status=None,
            severity=None,
            limit=override_limit,
        )
        if row.status not in {"resolved", "closed"}
    ]
    payload = handoff.to_dict()
    payload["incident_review_board"] = incident_review_board.to_dict()
    payload["active_incidents"] = active_incidents
    if incident_review_board.rows:
        active_names = [row.incident_id for row in incident_review_board.rows if row.status not in {"resolved", "closed"}]
        if active_names:
            payload["summary"] += " Active incidents: " + ", ".join(active_names[:5]) + "."
    payload["lineage"] = build_operator_handoff_lineage(settings)
    return payload


def record_operator_handoff_snapshot(
    settings: Settings,
    *,
    environments: list[str],
    release_limit: int,
    override_limit: int,
    label: str,
    output_path: str = "",
) -> dict[str, Any]:
    payload = build_operator_handoff_payload(
        settings,
        environments=environments,
        release_limit=release_limit,
        override_limit=override_limit,
    )
    if output_path:
        path = Path(output_path)
    else:
        safe_label = sub(r"[^a-zA-Z0-9._-]+", "-", label.strip()).strip("-")
        generated_at = str(payload.get("generated_at", "unknown"))
        file_name = f"operator-handoff-{generated_at.replace(':', '').replace('+', '_')}"
        if safe_label:
            file_name += f"-{safe_label}"
        path = settings.handoffs_dir / f"{file_name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {"saved_to": str(path), "handoff": payload}


def load_operator_handoff_snapshots(handoffs_dir: Path) -> list[tuple[Path, dict[str, Any]]]:
    snapshots: list[tuple[Path, dict[str, Any]]] = []
    for path in handoffs_dir.glob("operator-handoff-*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        snapshots.append((path, payload))
    snapshots.sort(key=lambda item: (str(item[1].get("generated_at", "")), item[0].name), reverse=True)
    return snapshots


def resolve_operator_handoff_snapshot(
    settings: Settings,
    snapshot: str,
    latest: bool,
) -> tuple[Path | None, dict[str, Any] | None, str | None]:
    if latest:
        snapshots = load_operator_handoff_snapshots(settings.handoffs_dir)
        if not snapshots:
            return None, None, "No saved operator handoff snapshots found."
        path, payload = snapshots[0]
        return path, payload, None
    if not snapshot:
        return None, None, "snapshot is required unless --latest is provided."
    path = Path(snapshot)
    if not path.is_absolute():
        path = settings.handoffs_dir / snapshot
    if not path.exists():
        return None, None, f"Operator handoff snapshot not found: {path}"
    return path, json.loads(path.read_text(encoding="utf-8")), None


def export_operator_handoff_report(
    settings: Settings,
    *,
    snapshot: str,
    latest: bool,
    output: str,
    title: str,
) -> dict[str, Any]:
    source_path, payload, error = resolve_operator_handoff_snapshot(settings, snapshot, latest)
    if error is not None or source_path is None or payload is None:
        raise ValueError(error or "Unknown snapshot resolution error.")
    output_path = Path(output) if output else source_path.with_suffix(".md")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report_title = title.strip() or "Operator Handoff Report"
    output_path.write_text(
        render_operator_handoff_markdown(payload, title=report_title),
        encoding="utf-8",
    )
    return {
        "saved_to": str(output_path),
        "source_snapshot": str(source_path),
        "title": report_title,
    }


def export_governance_summary_report(
    settings: Settings,
    *,
    environments: list[str],
    release_limit: int,
    incident_limit: int,
    override_limit: int,
    output: str,
    title: str,
) -> dict[str, Any]:
    payload = build_governance_summary_payload(
        settings,
        environments=environments or settings.environment_names,
        release_limit=release_limit,
        incident_limit=incident_limit,
        override_limit=override_limit,
    )
    output_path = Path(output) if output else settings.reports_dir / "governance-summary.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report_title = title.strip() or "Release Governance Summary"
    output_path.write_text(
        render_governance_summary_markdown(payload, title=report_title),
        encoding="utf-8",
    )
    json_path = output_path.with_suffix(".json")
    json_path.write_text(json.dumps({"title": report_title, **payload}, indent=2), encoding="utf-8")
    return {
        "saved_to": str(output_path),
        "json_path": str(json_path),
        "title": report_title,
        "metrics": payload["metrics"],
        "lineage": payload["lineage"],
    }


def build_release_runbook_payload(
    settings: Settings,
    *,
    release_name: str,
    environments: list[str] | None = None,
    history_limit: int = 10,
    incident_limit: int = 20,
) -> dict[str, Any]:
    selected_environments = environments or settings.environment_names
    release_record = get_release_record(release_name, ledger_path=settings.release_ledger_path).to_dict()
    readiness_digest = get_release_readiness_digest(
        release_name,
        environments=selected_environments,
        ledger_path=settings.release_ledger_path,
        production_soak_minutes=settings.production_soak_minutes,
        required_approver_roles=settings.production_required_approver_roles,
        environment_policies=settings.environment_policies,
        environment_freeze_windows=settings.environment_freeze_windows,
        override_expiring_soon_minutes=settings.override_expiring_soon_minutes,
    ).to_dict()
    rollout_matrix = get_rollout_matrix(
        selected_environments,
        ledger_path=settings.release_ledger_path,
        release_name=release_name,
        production_soak_minutes=settings.production_soak_minutes,
        required_approver_roles=settings.production_required_approver_roles,
        environment_policies=settings.environment_policies,
        environment_freeze_windows=settings.environment_freeze_windows,
    ).to_dict()
    active_overrides = [
        row.to_dict()
        for row in list_active_overrides(
            ledger_path=settings.release_ledger_path,
            release_name=release_name,
            environment=None,
            limit=max(incident_limit, 50),
        )
    ]
    active_incidents = [
        row.to_dict()
        for row in list_incidents(
            ledger_path=settings.incident_ledger_path,
            status=None,
            severity=None,
            limit=incident_limit,
        )
        if row.release_name == release_name and row.status not in {"resolved", "closed"}
    ]
    environment_statuses = {
        environment: get_environment_status(environment, ledger_path=settings.release_ledger_path).to_dict()
        for environment in selected_environments
    }
    environment_histories = {
        environment: [
            entry.to_dict()
            for entry in get_environment_history(
                environment,
                ledger_path=settings.release_ledger_path,
                limit=history_limit,
            )
        ]
        for environment in selected_environments
    }
    execution_plan = _build_release_runbook_steps(
        release_name,
        release_record=release_record,
        readiness_digest=readiness_digest,
        rollout_matrix=rollout_matrix,
        active_incidents=active_incidents,
        active_overrides=active_overrides,
    )
    verification_commands = _build_release_runbook_verification_commands(release_name, selected_environments)
    payload = {
        "generated_at": utc_now_iso(),
        "release_name": release_name,
        "environments": selected_environments,
        "release_record": release_record,
        "readiness_digest": readiness_digest,
        "rollout_matrix": rollout_matrix,
        "active_incidents": active_incidents,
        "active_overrides": active_overrides,
        "environment_statuses": environment_statuses,
        "environment_histories": environment_histories,
        "execution_plan": execution_plan,
        "verification_commands": verification_commands,
    }
    payload["lineage"] = build_release_runbook_lineage(
        settings,
        release_name=release_name,
        active_incidents=active_incidents,
    )
    return payload


def export_release_runbook_report(
    settings: Settings,
    *,
    release_name: str,
    environments: list[str],
    history_limit: int,
    incident_limit: int,
    output: str,
    title: str,
) -> dict[str, Any]:
    payload = build_release_runbook_payload(
        settings,
        release_name=release_name,
        environments=environments or settings.environment_names,
        history_limit=history_limit,
        incident_limit=incident_limit,
    )
    safe_release_name = release_name.replace("/", "-")
    output_path = Path(output) if output else settings.reports_dir / f"release-runbook-{safe_release_name}.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report_title = title.strip() or f"Release Runbook: {release_name}"
    output_path.write_text(
        render_release_runbook_markdown(payload, title=report_title),
        encoding="utf-8",
    )
    json_path = output_path.with_suffix(".json")
    json_path.write_text(json.dumps({"title": report_title, **payload}, indent=2), encoding="utf-8")
    return {
        "saved_to": str(output_path),
        "json_path": str(json_path),
        "title": report_title,
        "release_name": release_name,
        "environments": payload["environments"],
        "step_count": len(payload["execution_plan"]),
        "lineage": payload["lineage"],
    }


def export_planner_shadow_report(
    settings: Settings,
    *,
    suite_name: str,
    report_name: str,
    allowed_tools: list[str],
    blocked_tools: list[str],
    markdown_output: str,
    title: str,
) -> dict[str, Any]:
    provider = create_planner_provider(settings)
    markdown_path_hint = Path(markdown_output) if markdown_output else settings.reports_dir / "planner-shadow.md"
    report = run_planner_shadow_suite(
        suite_name,
        provider,
        allowed_tools=allowed_tools,
        blocked_tools=blocked_tools,
        settings=settings,
    )
    report_path = settings.reports_dir / report_name
    report.lineage = build_planner_shadow_lineage(
        settings,
        suite_name=suite_name,
        report_path=report_path,
        markdown_path=markdown_path_hint,
    )
    report.save(report_path)
    markdown_path = export_planner_shadow_markdown(
        report,
        output=markdown_output,
        title=title or "Planner Shadow Report",
    )
    return {
        "saved_to": str(markdown_path),
        "report_path": str(report_path),
        "title": title.strip() or "Planner Shadow Report",
        "suite_name": report.suite_name,
        "candidate_provider": report.candidate_provider,
        "policy_pass_rate": report.policy_pass_rate,
        "all_passed": report.all_passed,
        "lineage": report.lineage,
    }


def export_release_command_brief_report(
    settings: Settings,
    *,
    release_name: str,
    environments: list[str],
    history_limit: int,
    incident_limit: int,
    output: str,
    title: str,
) -> dict[str, Any]:
    brief, output_path, json_path = export_release_command_brief(
        release_name,
        environments=environments or settings.environment_names,
        history_limit=history_limit,
        incident_limit=incident_limit,
        output=output,
        title=title or "Release Command Brief",
        settings=settings,
    )
    return {
        "saved_to": str(output_path),
        "json_path": str(json_path),
        "title": title.strip() or "Release Command Brief",
        "release_name": brief.release_name,
        "pattern": brief.pattern,
        "recommended_action": brief.recommended_action,
        "lineage": brief.lineage,
    }


def build_weekly_status_payload(
    settings: Settings,
    *,
    environments: list[str] | None = None,
    since_days: int = 7,
    snapshot_limit: int = 20,
    release_limit: int = 20,
    incident_limit: int = 20,
    override_limit: int = 50,
) -> dict[str, Any]:
    selected_environments = environments or settings.environment_names
    governance_summary = build_governance_summary_payload(
        settings,
        environments=selected_environments,
        release_limit=release_limit,
        incident_limit=incident_limit,
        override_limit=override_limit,
    )
    cutoff = datetime.now(UTC) - timedelta(days=max(1, since_days))
    all_snapshots = load_operator_handoff_snapshots(settings.handoffs_dir)
    filtered_snapshots: list[tuple[Path, dict[str, Any]]] = []
    for path, payload in all_snapshots:
        generated_at = _parse_iso_timestamp(str(payload.get("generated_at", "")))
        if generated_at is None or generated_at < cutoff:
            continue
        filtered_snapshots.append((path, payload))
    selected_snapshots = filtered_snapshots[: max(1, snapshot_limit)]

    high_risk_release_frequency = _count_rows(
        selected_snapshots,
        lambda payload: [
            row.get("release_name")
            for row in payload.get("release_risk_board", {}).get("rows", [])
            if row.get("risk_level") == "high" and row.get("release_name")
        ],
    )
    override_blocker_frequency = _count_rows(
        selected_snapshots,
        lambda payload: [
            f"{row.get('environment') or '-'}:{row.get('blocker')}"
            for row in payload.get("override_review_board", {}).get("rows", [])
            if row.get("blocker")
        ],
    )
    incident_release_frequency = _count_rows(
        selected_snapshots,
        lambda payload: [
            row.get("release_name") or row.get("environment") or row.get("incident_id")
            for row in payload.get("active_incidents", [])
            if row.get("release_name") or row.get("environment") or row.get("incident_id")
        ],
    )
    stale_release_frequency = _count_rows(
        selected_snapshots,
        lambda payload: [
            row.get("release_name")
            for row in payload.get("release_risk_board", {}).get("rows", [])
            if row.get("is_stale") and row.get("release_name")
        ],
    )
    recent_handoffs = [
        {
            "file_name": path.name,
            "generated_at": payload.get("generated_at"),
            "summary": payload.get("summary"),
            "high_risk_releases": [
                row.get("release_name")
                for row in payload.get("release_risk_board", {}).get("rows", [])
                if row.get("risk_level") == "high"
            ],
            "active_incident_count": len(payload.get("active_incidents", [])),
            "active_override_count": len(payload.get("active_overrides", [])),
        }
        for path, payload in selected_snapshots
    ]
    recurring_release_rows = _top_frequency_rows(high_risk_release_frequency, key_name="release_name")
    recurring_override_rows = _top_frequency_rows(override_blocker_frequency, key_name="blocker_key")
    recurring_incident_rows = _top_frequency_rows(incident_release_frequency, key_name="release_or_environment")
    recurring_stale_rows = _top_frequency_rows(stale_release_frequency, key_name="release_name")

    payload = {
        "generated_at": utc_now_iso(),
        "window": {
            "since_days": max(1, since_days),
            "cutoff": cutoff.isoformat(),
            "snapshots_analyzed": len(selected_snapshots),
        },
        "environments": selected_environments,
        "current_governance": governance_summary,
        "historical_patterns": {
            "recurring_high_risk_releases": recurring_release_rows,
            "recurring_override_blockers": recurring_override_rows,
            "recurring_incident_hotspots": recurring_incident_rows,
            "recurring_stale_releases": recurring_stale_rows,
        },
        "recent_handoffs": recent_handoffs,
    }
    payload["lineage"] = build_weekly_status_lineage(
        settings,
        current_governance=governance_summary,
        snapshot_paths=[path for path, _payload in selected_snapshots],
    )
    return payload


def export_weekly_status_report(
    settings: Settings,
    *,
    environments: list[str],
    since_days: int,
    snapshot_limit: int,
    release_limit: int,
    incident_limit: int,
    override_limit: int,
    output: str,
    title: str,
) -> dict[str, Any]:
    payload = build_weekly_status_payload(
        settings,
        environments=environments or settings.environment_names,
        since_days=since_days,
        snapshot_limit=snapshot_limit,
        release_limit=release_limit,
        incident_limit=incident_limit,
        override_limit=override_limit,
    )
    output_path = Path(output) if output else settings.reports_dir / "weekly-status.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report_title = title.strip() or "Weekly Release Status"
    output_path.write_text(
        render_weekly_status_markdown(payload, title=report_title),
        encoding="utf-8",
    )
    json_path = output_path.with_suffix(".json")
    json_path.write_text(json.dumps({"title": report_title, **payload}, indent=2), encoding="utf-8")
    return {
        "saved_to": str(output_path),
        "json_path": str(json_path),
        "title": report_title,
        "window": payload["window"],
        "top_recurring_high_risk_release": (
            payload["historical_patterns"]["recurring_high_risk_releases"][0]["release_name"]
            if payload["historical_patterns"]["recurring_high_risk_releases"]
            else None
        ),
        "lineage": payload["lineage"],
    }


def markdown_cell(value: object) -> str:
    if value is None:
        return "-"
    if isinstance(value, list):
        text = ", ".join(str(item) for item in value) if value else "-"
    elif isinstance(value, bool):
        text = "yes" if value else "no"
    else:
        text = str(value)
    return text.replace("|", "\\|").replace("\n", "<br>")


def render_markdown_table(headers: list[str], rows: list[list[object]]) -> list[str]:
    if not rows:
        return ["No items."]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(markdown_cell(item) for item in row) + " |")
    return lines


def render_operator_handoff_markdown(payload: dict[str, Any], *, title: str) -> str:
    release_rows = payload.get("release_risk_board", {}).get("rows", [])
    approval_rows = payload.get("approval_review_board", {}).get("rows", [])
    override_rows = payload.get("override_review_board", {}).get("rows", [])
    active_overrides = payload.get("active_overrides", [])
    incident_rows = payload.get("incident_review_board", {}).get("rows", [])
    active_incidents = payload.get("active_incidents", [])
    lines = [
        f"# {title}",
        "",
        f"- Generated at: {markdown_cell(payload.get('generated_at'))}",
        f"- Environments: {markdown_cell(payload.get('environments', []))}",
        "",
        "## Executive Summary",
        "",
        payload.get("summary", "No summary available."),
        "",
        "## Release Risk Board",
        "",
    ]
    lines.extend(
        render_markdown_table(
            ["Release", "State", "Risk", "Blocking Environments", "Stale", "Next Action"],
            [
                [
                    row.get("release_name"),
                    row.get("release_state"),
                    row.get("risk_level"),
                    row.get("blocking_environments", []),
                    row.get("is_stale"),
                    row.get("next_action"),
                ]
                for row in release_rows
            ],
        )
    )
    lines.extend(["", "## Incident Review Board", ""])
    lines.extend(
        render_markdown_table(
            ["Incident", "Severity", "Status", "Owner", "Release", "Recommended Action"],
            [
                [
                    row.get("incident_id"),
                    row.get("severity"),
                    row.get("status"),
                    row.get("owner"),
                    row.get("release_name"),
                    row.get("recommended_action"),
                ]
                for row in incident_rows
            ],
        )
    )
    lines.extend(["", "## Active Incidents", ""])
    lines.extend(
        render_markdown_table(
            ["Incident", "Severity", "Status", "Owner", "Environment", "Release"],
            [
                [
                    row.get("incident_id"),
                    row.get("severity"),
                    row.get("status"),
                    row.get("owner"),
                    row.get("environment"),
                    row.get("release_name"),
                ]
                for row in active_incidents
            ],
        )
    )
    lines.extend(["", "## Approval Review Board", ""])
    lines.extend(
        render_markdown_table(
            ["Release", "Status", "Risk", "Missing Roles", "Blocking Environments", "Recommended Action"],
            [
                [
                    row.get("release_name"),
                    row.get("status"),
                    row.get("risk_level"),
                    row.get("missing_roles", []),
                    row.get("blocking_environments", []),
                    row.get("recommended_action"),
                ]
                for row in approval_rows
            ],
        )
    )
    lines.extend(["", "## Override Review Board", ""])
    lines.extend(
        render_markdown_table(
            ["Release", "Environment", "Blocker", "Status", "Risk", "Recommended Action"],
            [
                [
                    row.get("release_name"),
                    row.get("environment"),
                    row.get("blocker"),
                    row.get("status"),
                    row.get("risk_level"),
                    row.get("recommended_action"),
                ]
                for row in override_rows
            ],
        )
    )
    lines.extend(["", "## Active Overrides", ""])
    lines.extend(
        render_markdown_table(
            ["Release", "Environment", "Blocker", "Actor", "Expires At"],
            [
                [
                    row.get("release_name"),
                    row.get("environment"),
                    row.get("blocker"),
                    row.get("actor"),
                    row.get("expires_at"),
                ]
                for row in active_overrides
            ],
        )
    )
    lines.append("")
    return "\n".join(lines)


def render_governance_summary_markdown(payload: dict[str, Any], *, title: str) -> str:
    release_rows = payload.get("release_risk_board", {}).get("rows", [])
    approval_rows = payload.get("approval_review_board", {}).get("rows", [])
    incident_rows = payload.get("incident_review_board", {}).get("rows", [])
    override_rows = payload.get("override_review_board", {}).get("rows", [])
    active_overrides = payload.get("active_overrides", [])
    active_incidents = payload.get("active_incidents", [])
    releases = payload.get("releases", [])
    metrics = payload.get("metrics", {})
    runtime_realism = payload.get("runtime_realism", {})
    latest_planner_shadow = runtime_realism.get("latest_planner_shadow") or {}
    latest_release_command_brief = runtime_realism.get("latest_release_command_brief") or {}
    lines = [
        f"# {title}",
        "",
        f"- Generated at: {markdown_cell(payload.get('generated_at'))}",
        f"- Environments: {markdown_cell(payload.get('environments', []))}",
        "",
        "## Summary Metrics",
        "",
    ]
    lines.extend(
        render_markdown_table(
            ["Metric", "Value"],
            [
                ["Recorded releases", metrics.get("recorded_release_count")],
                ["High-risk releases", metrics.get("high_risk_release_count")],
                ["Stale releases", metrics.get("stale_release_count")],
                ["Approval backlog", metrics.get("approval_backlog_count")],
                ["Stale approval queues", metrics.get("stale_approval_count")],
                ["Active incidents", metrics.get("active_incident_count")],
                ["Critical incidents", metrics.get("critical_incident_count")],
                ["Active overrides", metrics.get("active_override_count")],
                ["Expired or expiring overrides", metrics.get("urgent_override_count")],
                ["Planner shadow reports", metrics.get("planner_shadow_report_count")],
                ["Release command briefs", metrics.get("release_command_brief_count")],
            ],
        )
    )
    lines.extend(["", "## Runtime Realism", ""])
    lines.extend(
        render_markdown_table(
            ["Artifact", "Key Fields"],
            [
                [
                    "Latest planner shadow",
                    [
                        latest_planner_shadow.get("file_name"),
                        latest_planner_shadow.get("candidate_provider"),
                        latest_planner_shadow.get("policy_pass_rate"),
                        latest_planner_shadow.get("all_passed"),
                    ],
                ],
                [
                    "Latest release command brief",
                    [
                        latest_release_command_brief.get("file_name"),
                        latest_release_command_brief.get("release_name"),
                        latest_release_command_brief.get("recommended_action"),
                        latest_release_command_brief.get("pattern"),
                    ],
                ],
            ],
        )
    )
    lines.extend(["", "## Top Release Risks", ""])
    lines.extend(
        render_markdown_table(
            ["Release", "Risk", "State", "Blocking Environments", "Next Action"],
            [
                [
                    row.get("release_name"),
                    row.get("risk_level"),
                    row.get("release_state"),
                    row.get("blocking_environments", []),
                    row.get("next_action"),
                ]
                for row in release_rows[:10]
            ],
        )
    )
    lines.extend(["", "## Approval Backlog", ""])
    lines.extend(
        render_markdown_table(
            ["Release", "Status", "Risk", "Missing Roles", "Blocking Environments", "Action"],
            [
                [
                    row.get("release_name"),
                    row.get("status"),
                    row.get("risk_level"),
                    row.get("missing_roles", []),
                    row.get("blocking_environments", []),
                    row.get("recommended_action"),
                ]
                for row in approval_rows[:10]
            ],
        )
    )
    lines.extend(["", "## Incident Queue", ""])
    lines.extend(
        render_markdown_table(
            ["Incident", "Severity", "Status", "Owner", "Release", "Summary", "Action"],
            [
                [
                    row.get("incident_id"),
                    row.get("severity"),
                    row.get("status"),
                    row.get("owner"),
                    row.get("release_name"),
                    row.get("summary"),
                    row.get("recommended_action"),
                ]
                for row in incident_rows[:10]
            ],
        )
    )
    lines.extend(["", "## Override Pressure", ""])
    lines.extend(
        render_markdown_table(
            ["Release", "Environment", "Blocker", "Status", "Risk", "Action"],
            [
                [
                    row.get("release_name"),
                    row.get("environment"),
                    row.get("blocker"),
                    row.get("status"),
                    row.get("risk_level"),
                    row.get("recommended_action"),
                ]
                for row in override_rows[:10]
            ],
        )
    )
    lines.extend(["", "## Active Incidents", ""])
    lines.extend(
        render_markdown_table(
            ["Incident", "Severity", "Status", "Owner", "Environment", "Release"],
            [
                [
                    row.get("incident_id"),
                    row.get("severity"),
                    row.get("status"),
                    row.get("owner"),
                    row.get("environment"),
                    row.get("release_name"),
                ]
                for row in active_incidents[:10]
            ],
        )
    )
    lines.extend(["", "## Active Overrides", ""])
    lines.extend(
        render_markdown_table(
            ["Release", "Environment", "Blocker", "Actor", "Expires At"],
            [
                [
                    row.get("release_name"),
                    row.get("environment"),
                    row.get("blocker"),
                    row.get("actor"),
                    row.get("expires_at"),
                ]
                for row in active_overrides[:10]
            ],
        )
    )
    lines.extend(["", "## Recent Releases", ""])
    lines.extend(
        render_markdown_table(
            ["Release", "State", "Created At", "Last Updated", "Summary"],
            [
                [
                    row.get("release_name"),
                    row.get("state"),
                    row.get("created_at"),
                    row.get("last_updated_at"),
                    row.get("summary"),
                ]
                for row in releases[:10]
            ],
        )
    )
    lineage_rows = artifact_lineage_rows(payload.get("lineage") or {}, limit=12)
    if lineage_rows:
        lines.extend(["", "## Artifact Lineage", ""])
        lines.extend(render_markdown_table(["Kind", "File", "Exists", "Notes"], lineage_rows))
    lines.append("")
    return "\n".join(lines)


def render_release_runbook_markdown(payload: dict[str, Any], *, title: str) -> str:
    release_record = payload.get("release_record", {})
    readiness_digest = payload.get("readiness_digest", {})
    rollout_rows = payload.get("rollout_matrix", {}).get("rows", [])
    active_incidents = payload.get("active_incidents", [])
    active_overrides = payload.get("active_overrides", [])
    execution_plan = payload.get("execution_plan", [])
    verification_commands = payload.get("verification_commands", [])
    environment_statuses = payload.get("environment_statuses", {})
    environment_histories = payload.get("environment_histories", {})

    lines = [
        f"# {title}",
        "",
        f"- Generated at: {markdown_cell(payload.get('generated_at'))}",
        f"- Release: {markdown_cell(payload.get('release_name'))}",
        f"- Environments: {markdown_cell(payload.get('environments', []))}",
        "",
        "## Release Overview",
        "",
    ]
    lines.extend(
        render_markdown_table(
            ["Field", "Value"],
            [
                ["State", release_record.get("state")],
                ["Recommended action", release_record.get("recommended_action")],
                ["Summary", release_record.get("summary")],
                ["Suites", release_record.get("suites", [])],
                ["Blockers", release_record.get("blockers", [])],
                ["Warnings", release_record.get("warnings", [])],
                ["Approvals", [approval.get("role") for approval in release_record.get("approvals", [])]],
                ["Deployments", [deployment.get("environment") for deployment in release_record.get("deployments", [])]],
            ],
        )
    )
    lines.extend(["", "## Readiness Digest", ""])
    lines.extend(
        render_markdown_table(
            ["Field", "Value"],
            [
                ["Release state", readiness_digest.get("release_state")],
                ["All ready", readiness_digest.get("all_ready")],
                ["Ready environments", readiness_digest.get("ready_environments", [])],
                ["Blocking environments", readiness_digest.get("blocking_environments", [])],
                ["Summary", readiness_digest.get("summary")],
            ],
        )
    )
    lines.extend(["", "## Rollout Matrix", ""])
    lines.extend(
        render_markdown_table(
            ["Environment", "Policy State", "Readiness", "Blockers", "Recommended Action"],
            [
                [
                    row.get("environment"),
                    row.get("policy", {}).get("required_state"),
                    (row.get("readiness") or {}).get("passed"),
                    (row.get("readiness") or {}).get("blockers", []),
                    row.get("recommended_action"),
                ]
                for row in rollout_rows
            ],
        )
    )
    lines.extend(["", "## Active Incidents", ""])
    lines.extend(
        render_markdown_table(
            ["Incident", "Severity", "Status", "Owner", "Environment", "Summary"],
            [
                [
                    row.get("incident_id"),
                    row.get("severity"),
                    row.get("status"),
                    row.get("owner"),
                    row.get("environment"),
                    row.get("summary"),
                ]
                for row in active_incidents
            ],
        )
    )
    lines.extend(["", "## Active Overrides", ""])
    lines.extend(
        render_markdown_table(
            ["Environment", "Blocker", "Actor", "Expires At", "Note"],
            [
                [
                    row.get("environment"),
                    row.get("blocker"),
                    row.get("actor"),
                    row.get("expires_at"),
                    row.get("note"),
                ]
                for row in active_overrides
            ],
        )
    )
    lines.extend(["", "## Execution Plan", ""])
    lines.extend(
        render_markdown_table(
            ["Phase", "Status", "Environment", "Action", "Command"],
            [
                [
                    row.get("phase"),
                    row.get("status"),
                    row.get("environment"),
                    row.get("action"),
                    row.get("command"),
                ]
                for row in execution_plan
            ],
        )
    )
    lines.extend(["", "## Verification Commands", ""])
    lines.extend(
        render_markdown_table(
            ["Command", "Purpose"],
            [
                [row.get("command"), row.get("purpose")]
                for row in verification_commands
            ],
        )
    )
    lines.extend(["", "## Environment Status", ""])
    lines.extend(
        render_markdown_table(
            ["Environment", "Active Release", "Deployed At", "Status"],
            [
                [
                    environment,
                    status.get("active_release"),
                    status.get("deployed_at"),
                    status.get("status"),
                ]
                for environment, status in environment_statuses.items()
            ],
        )
    )
    for environment, history_rows in environment_histories.items():
        lines.extend(["", f"## Environment History: {environment}", ""])
        lines.extend(
            render_markdown_table(
                ["Release", "Status", "Deployed At", "Deployed By", "Replaces"],
                [
                    [
                        row.get("release_name"),
                        row.get("status"),
                        row.get("deployed_at"),
                        row.get("deployed_by"),
                        row.get("replaces_release"),
                    ]
                    for row in history_rows
                ],
            )
        )
    lineage_rows = artifact_lineage_rows(payload.get("lineage") or {}, limit=12)
    if lineage_rows:
        lines.extend(["", "## Artifact Lineage", ""])
        lines.extend(render_markdown_table(["Kind", "File", "Exists", "Notes"], lineage_rows))
    lines.append("")
    return "\n".join(lines)


def render_weekly_status_markdown(payload: dict[str, Any], *, title: str) -> str:
    window = payload.get("window", {})
    current_governance = payload.get("current_governance", {})
    metrics = current_governance.get("metrics", {})
    runtime_realism = current_governance.get("runtime_realism", {})
    latest_planner_shadow = runtime_realism.get("latest_planner_shadow") or {}
    latest_release_command_brief = runtime_realism.get("latest_release_command_brief") or {}
    patterns = payload.get("historical_patterns", {})
    recent_handoffs = payload.get("recent_handoffs", [])

    lines = [
        f"# {title}",
        "",
        f"- Generated at: {markdown_cell(payload.get('generated_at'))}",
        f"- Environments: {markdown_cell(payload.get('environments', []))}",
        f"- Window: last {markdown_cell(window.get('since_days'))} days",
        f"- Snapshots analyzed: {markdown_cell(window.get('snapshots_analyzed'))}",
        "",
        "## Current Metrics",
        "",
    ]
    lines.extend(
        render_markdown_table(
            ["Metric", "Value"],
            [
                ["Recorded releases", metrics.get("recorded_release_count")],
                ["High-risk releases", metrics.get("high_risk_release_count")],
                ["Stale releases", metrics.get("stale_release_count")],
                ["Approval backlog", metrics.get("approval_backlog_count")],
                ["Active incidents", metrics.get("active_incident_count")],
                ["Critical incidents", metrics.get("critical_incident_count")],
                ["Active overrides", metrics.get("active_override_count")],
                ["Urgent overrides", metrics.get("urgent_override_count")],
                ["Planner shadow reports", metrics.get("planner_shadow_report_count")],
                ["Release command briefs", metrics.get("release_command_brief_count")],
            ],
        )
    )
    lines.extend(["", "## Latest Runtime Realism", ""])
    lines.extend(
        render_markdown_table(
            ["Artifact", "Key Fields"],
            [
                [
                    "Planner shadow",
                    [
                        latest_planner_shadow.get("file_name"),
                        latest_planner_shadow.get("candidate_provider"),
                        latest_planner_shadow.get("policy_pass_rate"),
                        latest_planner_shadow.get("all_passed"),
                    ],
                ],
                [
                    "Release command brief",
                    [
                        latest_release_command_brief.get("file_name"),
                        latest_release_command_brief.get("release_name"),
                        latest_release_command_brief.get("recommended_action"),
                        latest_release_command_brief.get("pattern"),
                    ],
                ],
            ],
        )
    )
    lines.extend(["", "## Recurring High-Risk Releases", ""])
    lines.extend(
        render_markdown_table(
            ["Release", "Occurrences"],
            [
                [row.get("release_name"), row.get("occurrences")]
                for row in patterns.get("recurring_high_risk_releases", [])
            ],
        )
    )
    lines.extend(["", "## Recurring Override Blockers", ""])
    lines.extend(
        render_markdown_table(
            ["Blocker Key", "Occurrences"],
            [
                [row.get("blocker_key"), row.get("occurrences")]
                for row in patterns.get("recurring_override_blockers", [])
            ],
        )
    )
    lines.extend(["", "## Recurring Incident Hotspots", ""])
    lines.extend(
        render_markdown_table(
            ["Release Or Environment", "Occurrences"],
            [
                [row.get("release_or_environment"), row.get("occurrences")]
                for row in patterns.get("recurring_incident_hotspots", [])
            ],
        )
    )
    lines.extend(["", "## Recurring Stale Releases", ""])
    lines.extend(
        render_markdown_table(
            ["Release", "Occurrences"],
            [
                [row.get("release_name"), row.get("occurrences")]
                for row in patterns.get("recurring_stale_releases", [])
            ],
        )
    )
    lines.extend(["", "## Recent Handoffs", ""])
    lines.extend(
        render_markdown_table(
            ["Generated At", "File", "High-Risk Releases", "Incidents", "Overrides", "Summary"],
            [
                [
                    row.get("generated_at"),
                    row.get("file_name"),
                    row.get("high_risk_releases", []),
                    row.get("active_incident_count"),
                    row.get("active_override_count"),
                    row.get("summary"),
                ]
                for row in recent_handoffs
            ],
        )
    )
    lineage_rows = artifact_lineage_rows(payload.get("lineage") or {}, limit=12)
    if lineage_rows:
        lines.extend(["", "## Artifact Lineage", ""])
        lines.extend(render_markdown_table(["Kind", "File", "Exists", "Notes"], lineage_rows))
    lines.append("")
    return "\n".join(lines)


def _load_runtime_json_artifacts(paths, *, required_keys: set[str]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not required_keys.issubset(set(payload)):
            continue
        generated_at = str(payload.get("generated_at") or payload.get("created_at") or "")
        payload = dict(payload)
        payload["file_name"] = path.name
        payload["path"] = str(path)
        payload["_sort_key"] = generated_at or path.name
        records.append(payload)
    records.sort(key=lambda item: str(item.get("_sort_key", "")), reverse=True)
    for record in records:
        record.pop("_sort_key", None)
    return records


def _build_release_runbook_steps(
    release_name: str,
    *,
    release_record: dict[str, Any],
    readiness_digest: dict[str, Any],
    rollout_matrix: dict[str, Any],
    active_incidents: list[dict[str, Any]],
    active_overrides: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    rows.append(
        {
            "phase": "preflight",
            "status": "required",
            "environment": "-",
            "action": f"Verify release state '{release_record.get('state')}' and review remaining blockers before rollout.",
            "command": f"PYTHONPATH=src python3 -m agent_architect_lab.cli release-status {release_name}",
        }
    )
    if active_incidents:
        rows.append(
            {
                "phase": "preflight",
                "status": "blocked",
                "environment": "-",
                "action": "Resolve or explicitly accept active incidents linked to this release before rollout.",
                "command": f"PYTHONPATH=src python3 -m agent_architect_lab.cli list-incidents --limit {max(len(active_incidents), 10)}",
            }
        )
    if active_overrides:
        rows.append(
            {
                "phase": "preflight",
                "status": "review",
                "environment": "-",
                "action": "Review active overrides, expiry times, and whether they are still justified for this release.",
                "command": f"PYTHONPATH=src python3 -m agent_architect_lab.cli list-active-overrides --release-name {release_name}",
            }
        )
    if not readiness_digest.get("all_ready", False):
        rows.append(
            {
                "phase": "preflight",
                "status": "review",
                "environment": "-",
                "action": "Inspect readiness blockers before attempting rollout.",
                "command": f"PYTHONPATH=src python3 -m agent_architect_lab.cli release-readiness-digest {release_name}",
            }
        )
    for row in rollout_matrix.get("rows", []):
        environment = str(row.get("environment"))
        readiness = row.get("readiness") or {}
        if readiness.get("passed"):
            action = f"Deploy release to {environment}."
            status = "ready"
        else:
            blockers = readiness.get("blockers", [])
            action = (
                f"Clear rollout blockers for {environment}: {', '.join(str(item) for item in blockers) or 'none'}."
            )
            status = "blocked"
        rows.append(
            {
                "phase": "rollout",
                "status": status,
                "environment": environment,
                "action": action,
                "command": f"PYTHONPATH=src python3 -m agent_architect_lab.cli deploy-release {release_name} --environment {environment} --by <operator>",
            }
        )
        rows.append(
            {
                "phase": "verification",
                "status": "required",
                "environment": environment,
                "action": f"Verify environment state and readiness after the {environment} action.",
                "command": f"PYTHONPATH=src python3 -m agent_architect_lab.cli environment-history --environment {environment}",
            }
        )
        rows.append(
            {
                "phase": "rollback",
                "status": "prepared",
                "environment": environment,
                "action": f"Rollback {environment} if rollout triggers incidents or violates policy.",
                "command": f"PYTHONPATH=src python3 -m agent_architect_lab.cli rollback-release {release_name} --environment {environment} --by <operator>",
            }
        )
    return rows


def _build_release_runbook_verification_commands(
    release_name: str,
    environments: list[str],
) -> list[dict[str, str]]:
    rows = [
        {
            "command": f"PYTHONPATH=src python3 -m agent_architect_lab.cli release-status {release_name}",
            "purpose": "Inspect release state, approvals, overrides, deployments, and event history.",
        },
        {
            "command": f"PYTHONPATH=src python3 -m agent_architect_lab.cli release-readiness-digest {release_name}",
            "purpose": "Summarize rollout blockers, ready environments, and override pressure.",
        },
        {
            "command": f"PYTHONPATH=src python3 -m agent_architect_lab.cli rollout-matrix {release_name}",
            "purpose": "Inspect environment-by-environment readiness and next action recommendations.",
        },
    ]
    for environment in environments:
        rows.append(
            {
                "command": f"PYTHONPATH=src python3 -m agent_architect_lab.cli environment-history --environment {environment}",
                "purpose": f"Review recent lineage and rollback context for {environment}.",
            }
        )
    return rows


def _parse_iso_timestamp(value: str) -> datetime | None:
    if not value.strip():
        return None
    observed = datetime.fromisoformat(value)
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=UTC)
    return observed


def _count_rows(
    snapshots: list[tuple[Path, dict[str, Any]]],
    extractor,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for _path, payload in snapshots:
        for key in extractor(payload):
            if not key:
                continue
            counts[str(key)] = counts.get(str(key), 0) + 1
    return counts


def _top_frequency_rows(counts: dict[str, int], *, key_name: str) -> list[dict[str, Any]]:
    return [
        {key_name: key, "occurrences": count}
        for key, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:10]
    ]
