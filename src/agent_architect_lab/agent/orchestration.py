from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_architect_lab.config import Settings, load_settings
from agent_architect_lab.harness.incidents import list_incidents
from agent_architect_lab.harness.ledger import (
    get_approval_review_board,
    get_environment_history,
    get_override_review_board,
    get_release_readiness_digest,
    get_release_record,
    get_rollout_matrix,
    list_active_overrides,
)
from agent_architect_lab.models import utc_now_iso


@dataclass(slots=True)
class RoleBrief:
    role: str
    objective: str
    ownership: str
    findings: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "objective": self.objective,
            "ownership": self.ownership,
            "findings": self.findings,
            "blockers": self.blockers,
            "recommendations": self.recommendations,
        }


@dataclass(slots=True)
class RoleHandoff:
    from_role: str
    to_role: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {
            "from_role": self.from_role,
            "to_role": self.to_role,
            "reason": self.reason,
        }


@dataclass(slots=True)
class ReleaseCommandBrief:
    release_name: str
    generated_at: str
    environments: list[str]
    pattern: str
    summary: str
    recommended_action: str
    roles: list[RoleBrief]
    handoffs: list[RoleHandoff]

    def to_dict(self) -> dict[str, Any]:
        return {
            "release_name": self.release_name,
            "generated_at": self.generated_at,
            "environments": self.environments,
            "pattern": self.pattern,
            "summary": self.summary,
            "recommended_action": self.recommended_action,
            "roles": [role.to_dict() for role in self.roles],
            "handoffs": [handoff.to_dict() for handoff in self.handoffs],
        }

    def save_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")


def build_release_command_brief(
    release_name: str,
    *,
    environments: list[str] | None = None,
    history_limit: int = 5,
    incident_limit: int = 10,
    settings: Settings | None = None,
) -> ReleaseCommandBrief:
    resolved_settings = settings or load_settings()
    selected_environments = list(environments or resolved_settings.environment_names)
    record = get_release_record(release_name, ledger_path=resolved_settings.release_ledger_path)
    digest = get_release_readiness_digest(
        release_name,
        environments=selected_environments,
        ledger_path=resolved_settings.release_ledger_path,
        production_soak_minutes=resolved_settings.production_soak_minutes,
        required_approver_roles=resolved_settings.production_required_approver_roles,
        environment_policies=resolved_settings.environment_policies,
        environment_freeze_windows=resolved_settings.environment_freeze_windows,
        override_expiring_soon_minutes=resolved_settings.override_expiring_soon_minutes,
    )
    approval_board = get_approval_review_board(
        environments=selected_environments,
        ledger_path=resolved_settings.release_ledger_path,
        production_soak_minutes=resolved_settings.production_soak_minutes,
        required_approver_roles=resolved_settings.production_required_approver_roles,
        environment_policies=resolved_settings.environment_policies,
        environment_freeze_windows=resolved_settings.environment_freeze_windows,
        approval_stale_minutes=resolved_settings.approval_stale_minutes,
        limit=max(incident_limit, 20),
    )
    approval_row = next((row for row in approval_board.rows if row.release_name == release_name), None)
    override_board = get_override_review_board(
        ledger_path=resolved_settings.release_ledger_path,
        release_name=release_name,
        override_expiring_soon_minutes=resolved_settings.override_expiring_soon_minutes,
        limit=max(incident_limit, 20),
    )
    active_overrides = list_active_overrides(
        ledger_path=resolved_settings.release_ledger_path,
        release_name=release_name,
        limit=max(incident_limit, 20),
    )
    rollout_matrix = get_rollout_matrix(
        selected_environments,
        ledger_path=resolved_settings.release_ledger_path,
        release_name=release_name,
        production_soak_minutes=resolved_settings.production_soak_minutes,
        required_approver_roles=resolved_settings.production_required_approver_roles,
        environment_policies=resolved_settings.environment_policies,
        environment_freeze_windows=resolved_settings.environment_freeze_windows,
    )
    incidents = [
        incident
        for incident in list_incidents(ledger_path=resolved_settings.incident_ledger_path, limit=max(incident_limit * 4, 50))
        if incident.release_name == release_name or (incident.environment in selected_environments and incident.status != "closed")
    ][:incident_limit]
    history = {
        environment: get_environment_history(
            environment,
            ledger_path=resolved_settings.release_ledger_path,
            limit=history_limit,
        )
        for environment in selected_environments
    }

    qa_findings = [
        f"Release state is `{record.state}` with recommended action `{record.recommended_action}`.",
        f"Shadow suites: {', '.join(record.suites) or 'none recorded'}.",
    ]
    qa_blockers = list(record.blockers)
    qa_recommendations = []
    if approval_row is not None:
        if approval_row.approved_roles:
            qa_findings.append(f"Approved roles: {', '.join(approval_row.approved_roles)}.")
        if approval_row.missing_roles:
            qa_blockers.append(f"Missing approver roles: {', '.join(approval_row.missing_roles)}.")
        qa_recommendations.append(approval_row.recommended_action)
    if record.warnings:
        qa_findings.append(f"Release warnings: {', '.join(record.warnings)}.")

    ops_findings = [
        digest.summary,
        f"Ready environments: {', '.join(digest.ready_environments) or 'none'}.",
    ]
    ops_blockers = [f"Blocked environment: {environment}" for environment in digest.blocking_environments]
    if active_overrides:
        ops_findings.append(
            "Active overrides: "
            + ", ".join(f"{item.environment}:{item.blocker}" for item in active_overrides)
            + "."
        )
    if override_board.rows:
        ops_findings.append(
            "Override review: "
            + ", ".join(f"{row.environment}:{row.blocker}:{row.status}" for row in override_board.rows[:5])
            + "."
        )
    for environment, rows in history.items():
        if rows:
            head = rows[0]
            ops_findings.append(
                f"Latest {environment} history: {head.release_name} is `{head.status}` from {head.last_transition_at}."
            )
    ops_recommendations = [row.recommended_action for row in rollout_matrix.rows if row.recommended_action]

    incident_findings = []
    incident_blockers = []
    incident_recommendations = []
    if incidents:
        incident_findings.append(f"Active incident load: {len(incidents)} relevant incident(s).")
    else:
        incident_findings.append("No active incidents are currently linked to this release or its target environments.")
    for incident in incidents:
        incident_findings.append(
            f"{incident.incident_id}: {incident.severity}/{incident.status} owned by {incident.owner}."
        )
        if incident.status in {"open", "acknowledged", "contained"}:
            incident_blockers.append(f"Unresolved incident: {incident.incident_id}.")
        if incident.status == "resolved" and not incident.followup_eval_path:
            incident_blockers.append(f"Resolved incident missing follow-up eval: {incident.incident_id}.")
        incident_recommendations.append(
            "close_incident_loop" if incident.followup_eval_path else "link_followup_eval"
        )

    release_manager_blockers = _dedupe(qa_blockers + ops_blockers + incident_blockers)
    if incident_blockers:
        recommended_action = "hold_release"
    elif ops_blockers:
        recommended_action = "stabilize_operational_blockers"
    elif qa_blockers:
        recommended_action = "collect_quality_signoff"
    elif record.warnings or active_overrides:
        recommended_action = "promote_with_review"
    else:
        recommended_action = "promote"
    manager_findings = [
        f"Release summary: {record.summary or 'no summary recorded'}.",
        f"Readiness summary: {digest.summary}",
        f"Final recommended action: `{recommended_action}`.",
    ]
    manager_recommendations = _dedupe(
        qa_recommendations + ops_recommendations + incident_recommendations + [recommended_action]
    )
    roles = [
        RoleBrief(
            role="qa-owner",
            objective="Validate shadow evidence, release blockers, and approval posture.",
            ownership="Eval quality, release blockers, and missing sign-off.",
            findings=qa_findings,
            blockers=_dedupe(qa_blockers),
            recommendations=_dedupe(qa_recommendations or ["review_shadow_findings"]),
        ),
        RoleBrief(
            role="ops-oncall",
            objective="Check rollout readiness, override debt, and environment exposure.",
            ownership="Operational safety, deploy blockers, and rollback context.",
            findings=ops_findings,
            blockers=_dedupe(ops_blockers),
            recommendations=_dedupe(ops_recommendations or ["review_rollout_readiness"]),
        ),
        RoleBrief(
            role="incident-commander",
            objective="Contain active incidents and confirm follow-up eval closure risk.",
            ownership="Incident severity, ownership, and follow-up eval linkage.",
            findings=incident_findings,
            blockers=_dedupe(incident_blockers),
            recommendations=_dedupe(incident_recommendations or ["observe_incident_load"]),
        ),
        RoleBrief(
            role="release-manager",
            objective="Make the bounded promotion decision using upstream role packets.",
            ownership="Final release call and explicit hold/promote outcome.",
            findings=manager_findings,
            blockers=release_manager_blockers,
            recommendations=manager_recommendations,
        ),
    ]
    handoffs = [
        RoleHandoff("qa-owner", "ops-oncall", "Quality posture feeds deployment risk review."),
        RoleHandoff("ops-oncall", "incident-commander", "Operational blockers and rollback context feed incident command."),
        RoleHandoff("incident-commander", "release-manager", "Incident exposure and closure debt inform the final release call."),
    ]
    summary = (
        f"Hold {release_name} until blockers clear."
        if release_manager_blockers
        else f"{release_name} is ready to promote within the bounded role handoff."
    )
    return ReleaseCommandBrief(
        release_name=release_name,
        generated_at=utc_now_iso(),
        environments=selected_environments,
        pattern="bounded_role_handoff",
        summary=summary,
        recommended_action=recommended_action,
        roles=roles,
        handoffs=handoffs,
    )


def render_release_command_brief_markdown(
    brief: ReleaseCommandBrief,
    *,
    title: str = "Release Command Brief",
) -> str:
    lines = [
        f"# {title}",
        "",
        f"- Release: `{brief.release_name}`",
        f"- Pattern: `{brief.pattern}`",
        f"- Environments: {', '.join(brief.environments)}",
        f"- Generated at: `{brief.generated_at}`",
        f"- Recommended action: `{brief.recommended_action}`",
        "",
        "## Summary",
        "",
        brief.summary,
        "",
        "## Handoffs",
        "",
    ]
    for handoff in brief.handoffs:
        lines.append(f"- `{handoff.from_role}` -> `{handoff.to_role}`: {handoff.reason}")
    for role in brief.roles:
        lines.extend(["", f"## {role.role}", ""])
        lines.append(f"- Objective: {role.objective}")
        lines.append(f"- Ownership: {role.ownership}")
        if role.findings:
            for finding in role.findings:
                lines.append(f"- Finding: {finding}")
        if role.blockers:
            for blocker in role.blockers:
                lines.append(f"- Blocker: {blocker}")
        if role.recommendations:
            for recommendation in role.recommendations:
                lines.append(f"- Recommendation: {recommendation}")
    return "\n".join(lines).rstrip() + "\n"


def export_release_command_brief(
    release_name: str,
    *,
    environments: list[str] | None = None,
    history_limit: int = 5,
    incident_limit: int = 10,
    output: str = "",
    title: str = "Release Command Brief",
    settings: Settings | None = None,
) -> tuple[ReleaseCommandBrief, Path]:
    resolved_settings = settings or load_settings()
    brief = build_release_command_brief(
        release_name,
        environments=environments,
        history_limit=history_limit,
        incident_limit=incident_limit,
        settings=resolved_settings,
    )
    output_path = Path(output) if output else resolved_settings.reports_dir / f"release-command-{release_name}.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_release_command_brief_markdown(brief, title=title), encoding="utf-8")
    return brief, output_path


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
