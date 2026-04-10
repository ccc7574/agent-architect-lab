from __future__ import annotations

import json
from pathlib import Path
from re import sub
from typing import Any

from agent_architect_lab.config import Settings
from agent_architect_lab.harness.incidents import get_incident_review_board, list_incidents
from agent_architect_lab.harness.ledger import (
    get_approval_review_board,
    get_operator_handoff,
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
    return {"saved_to": str(output_path), "title": report_title, "metrics": payload["metrics"]}


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
    lines.append("")
    return "\n".join(lines)
