from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from re import sub

from agent_architect_lab.agent.patterns import PATTERNS, recommend_pattern
from agent_architect_lab.agent.runtime import AgentRuntime
from agent_architect_lab.config import load_settings
from agent_architect_lab.evals.tasks import list_available_suites, load_default_suite, load_suite
from agent_architect_lab.harness.compare import compare_reports
from agent_architect_lab.harness.gates import GateConfig, check_report_gates
from agent_architect_lab.harness.incidents import (
    get_incident_record,
    get_incident_review_board,
    list_incidents,
    open_incident,
    save_incident_suggestions,
    suggest_incident_evals,
    transition_incident,
)
from agent_architect_lab.harness.ledger import (
    get_approval_review_board,
    check_deploy_readiness,
    deploy_release,
    get_environment_history,
    get_override_review_board,
    get_operator_handoff,
    get_release_readiness_digest,
    get_release_risk_board,
    get_rollout_matrix,
    get_environment_status,
    get_deploy_policy,
    get_release_record,
    grant_release_override,
    list_active_overrides,
    list_releases,
    record_release_candidate,
    revoke_release_override,
    rollback_release,
    transition_release,
)
from agent_architect_lab.harness.promotion import default_gate_config_for_suite, evaluate_promotion
from agent_architect_lab.harness.release import run_release_shadow_review
from agent_architect_lab.harness.reporting import HarnessReport, register_existing_report, save_report_and_record
from agent_architect_lab.harness.rollout import build_rollout_review
from agent_architect_lab.harness.runner import run_suite
from agent_architect_lab.harness.shadow import run_shadow_suite
from agent_architect_lab.mcp.server import serve
from agent_architect_lab.models import Task, utc_now_iso
from agent_architect_lab.skills.catalog import load_skills, select_skills


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-lab", description="Enterprise-focused agent architecture learning lab.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_task = subparsers.add_parser("run-task", help="Run a single task through the local runtime.")
    run_task.add_argument("goal", help="Task goal for the runtime.")

    run_eval = subparsers.add_parser("run-evals", help="Run the default evaluation suite.")
    run_eval.add_argument("--report-name", default="latest-report.json", help="Output report file name.")
    run_eval.add_argument("--suite", default="default", choices=list_available_suites(), help="Named evaluation suite to run.")
    run_eval.add_argument(
        "--report-kind",
        default="adhoc",
        choices=["adhoc", "baseline", "candidate", "shadow_candidate", "release_candidate"],
        help="Registry classification for the saved report.",
    )
    run_eval.add_argument("--report-label", default="", help="Optional label stored in the report registry.")

    run_server = subparsers.add_parser("run-mcp-server", help="Run the example note MCP server.")

    list_skills = subparsers.add_parser("list-skills", help="Show skill manifests and optional matches.")
    list_skills.add_argument("--goal", default="", help="Optional goal to test skill matching.")

    explain_patterns = subparsers.add_parser("explain-patterns", help="Show agent patterns or a recommendation.")
    explain_patterns.add_argument("--goal", default="", help="Optional goal to get a pattern recommendation.")

    compare = subparsers.add_parser("compare-reports", help="Compare two harness reports.")
    compare.add_argument("baseline", help="Baseline report path.")
    compare.add_argument("candidate", help="Candidate report path.")

    gates = subparsers.add_parser("check-gates", help="Check whether a harness report passes release gates.")
    gates.add_argument("report", help="Report path to validate.")
    gates.add_argument("--min-success-rate", type=float, default=1.0, help="Minimum success rate required.")
    gates.add_argument("--min-average-score", type=float, default=0.95, help="Minimum average score required.")
    gates.add_argument("--max-average-steps", type=float, default=None, help="Optional maximum average steps allowed.")
    gates.add_argument("--suite-aware-defaults", action="store_true", help="Use stricter built-in defaults for known suites.")

    incidents = subparsers.add_parser("suggest-incident-evals", help="Generate candidate eval tasks from failed report results.")
    incidents.add_argument("report", help="Report path to inspect.")
    incidents.add_argument("--output", default="", help="Optional JSONL output path for suggested tasks.")

    open_incident_cmd = subparsers.add_parser("open-incident", help="Record a production incident linked to a release, environment, or report.")
    open_incident_cmd.add_argument("--severity", required=True, choices=["critical", "high", "medium", "low"], help="Incident severity.")
    open_incident_cmd.add_argument("--summary", required=True, help="Short operator-facing incident summary.")
    open_incident_cmd.add_argument("--owner", required=True, help="Current incident owner.")
    open_incident_cmd.add_argument("--environment", default="", help="Optional affected environment.")
    open_incident_cmd.add_argument("--release-name", default="", help="Optional linked release.")
    open_incident_cmd.add_argument("--source-report", default="", help="Optional linked harness report path.")
    open_incident_cmd.add_argument("--note", default="", help="Optional opening note.")

    transition_incident_cmd = subparsers.add_parser("transition-incident", help="Advance an incident through acknowledgement, containment, resolution, or closure.")
    transition_incident_cmd.add_argument("incident_id", help="Incident identifier.")
    transition_incident_cmd.add_argument("--status", required=True, choices=["acknowledged", "contained", "resolved", "closed"], help="Target incident status.")
    transition_incident_cmd.add_argument("--by", required=True, help="Operator identity.")
    transition_incident_cmd.add_argument("--note", default="", help="Optional transition note.")
    transition_incident_cmd.add_argument("--owner", default="", help="Optional owner reassignment.")
    transition_incident_cmd.add_argument("--followup-eval-path", default="", help="Optional linked follow-up eval artifact path.")

    list_incidents_cmd = subparsers.add_parser("list-incidents", help="List recorded incidents with optional status or severity filtering.")
    list_incidents_cmd.add_argument("--status", default="", choices=["", "open", "acknowledged", "contained", "resolved", "closed"], help="Optional status filter.")
    list_incidents_cmd.add_argument("--severity", default="", choices=["", "critical", "high", "medium", "low"], help="Optional severity filter.")
    list_incidents_cmd.add_argument("--limit", type=int, default=20, help="Maximum number of incidents to return.")

    incident_status_cmd = subparsers.add_parser("incident-status", help="Show the full state and history for one incident.")
    incident_status_cmd.add_argument("incident_id", help="Incident identifier.")

    export_incident_report_cmd = subparsers.add_parser("export-incident-report", help="Render a recorded incident as a Markdown report.")
    export_incident_report_cmd.add_argument("incident_id", help="Incident identifier.")
    export_incident_report_cmd.add_argument("--output", default="", help="Optional output Markdown path. Defaults to artifacts/incidents/<incident_id>.md.")
    export_incident_report_cmd.add_argument("--title", default="", help="Optional report title override.")

    export_incident_bundle_cmd = subparsers.add_parser("export-incident-bundle", help="Export an incident bundle with incident report, release context, and related handoff artifacts.")
    export_incident_bundle_cmd.add_argument("incident_id", help="Incident identifier.")
    export_incident_bundle_cmd.add_argument("--output-dir", default="", help="Optional output directory. Defaults to artifacts/incidents/bundles/<incident_id>.")

    incident_review_board_cmd = subparsers.add_parser("incident-review-board", help="Show unresolved incident priority and stale incident queues.")
    incident_review_board_cmd.add_argument("--status", default="", choices=["", "open", "acknowledged", "contained", "resolved", "closed"], help="Optional status filter.")
    incident_review_board_cmd.add_argument("--limit", type=int, default=20, help="Maximum number of incidents to return.")

    promote = subparsers.add_parser("evaluate-promotion", help="Evaluate whether a candidate report is promotable against a baseline.")
    promote.add_argument("baseline", help="Baseline report path.")
    promote.add_argument("candidate", help="Candidate report path.")
    promote.add_argument("--allow-suite-mismatch", action="store_true", help="Allow comparing reports from different suites.")
    promote.add_argument("--suite-aware-defaults", action="store_true", help="Use built-in suite gate defaults for the candidate report.")

    rollout = subparsers.add_parser("rollout-review", help="Build an operator-facing rollout review with promotion analysis and eval backfill suggestions.")
    rollout.add_argument("baseline", help="Baseline report path.")
    rollout.add_argument("candidate", help="Candidate report path.")
    rollout.add_argument("--allow-suite-mismatch", action="store_true", help="Allow comparing reports from different suites.")
    rollout.add_argument("--suite-aware-defaults", action="store_true", help="Use built-in suite gate defaults for the candidate report.")
    rollout.add_argument("--output-backfill", default="", help="Optional JSONL path to save candidate incident suggestions.")

    shadow = subparsers.add_parser("run-shadow", help="Run a candidate suite, save the report, and produce a rollout review against a baseline.")
    shadow.add_argument("baseline", help="Baseline report path.")
    shadow.add_argument("--suite", required=True, choices=list_available_suites(), help="Suite to run for the candidate shadow evaluation.")
    shadow.add_argument("--report-name", default="shadow-report.json", help="Candidate report file name.")
    shadow.add_argument("--allow-suite-mismatch", action="store_true", help="Allow comparing reports from different suites.")
    shadow.add_argument("--suite-aware-defaults", action="store_true", help="Use built-in suite gate defaults for the candidate report.")
    shadow.add_argument("--output-backfill", default="", help="Optional JSONL path to save candidate incident suggestions.")

    release = subparsers.add_parser("run-release-shadow", help="Run a multi-suite shadow review using the latest baseline for each suite.")
    release.add_argument("--suites", nargs="+", required=True, choices=list_available_suites(), help="Suites to shadow against their latest baselines.")
    release.add_argument("--report-prefix", default="release-shadow", help="Prefix for generated candidate report files.")
    release.add_argument("--output-backfill-dir", default="", help="Optional directory for per-suite backfill JSONL files.")
    release.add_argument("--suite-aware-defaults", action="store_true", help="Use built-in suite gate defaults for candidate reports.")
    release.add_argument("--baseline-manifest", default="", help="Optional JSON manifest mapping suites to explicit baseline report paths.")
    release.add_argument("--release-name", default="", help="Optional immutable release name to record in the release ledger.")

    register = subparsers.add_parser("register-report", help="Register an existing harness report for baseline selection and audit trails.")
    register.add_argument("report", help="Report path to register.")
    register.add_argument(
        "--report-kind",
        default="adhoc",
        choices=["adhoc", "baseline", "candidate", "shadow_candidate", "release_candidate"],
        help="Registry classification for the report.",
    )
    register.add_argument("--report-label", default="", help="Optional label stored in the report registry.")

    release_status = subparsers.add_parser("release-status", help="Show the current state and history for a recorded release.")
    release_status.add_argument("release_name", help="Immutable release name.")

    approve_release = subparsers.add_parser("approve-release", help="Approve a pending release in the release ledger.")
    approve_release.add_argument("release_name", help="Immutable release name.")
    approve_release.add_argument("--by", required=True, help="Approver identity.")
    approve_release.add_argument("--role", default="", help="Optional approver role for production readiness policy. Defaults to the actor name.")
    approve_release.add_argument("--note", default="", help="Optional approval note.")

    override_release = subparsers.add_parser("grant-release-override", help="Grant a temporary blocker override for a release in a specific environment.")
    override_release.add_argument("release_name", help="Immutable release name.")
    override_release.add_argument("--environment", required=True, help="Deployment environment where the override applies.")
    override_release.add_argument("--blocker", required=True, help="Exact blocker string to override, for example environment_frozen.")
    override_release.add_argument("--by", required=True, help="Operator identity.")
    override_release.add_argument("--note", default="", help="Optional override justification.")
    override_release.add_argument("--expires-at", default="", help="Optional absolute expiry timestamp in ISO-8601 format.")

    revoke_override_release = subparsers.add_parser("revoke-release-override", help="Revoke a previously granted override for a release in a specific environment.")
    revoke_override_release.add_argument("release_name", help="Immutable release name.")
    revoke_override_release.add_argument("--environment", required=True, help="Deployment environment where the override applies.")
    revoke_override_release.add_argument("--blocker", required=True, help="Exact blocker string to revoke.")
    revoke_override_release.add_argument("--by", required=True, help="Operator identity.")
    revoke_override_release.add_argument("--note", default="", help="Optional revoke justification.")

    reject_release = subparsers.add_parser("reject-release", help="Reject a pending or approved release in the release ledger.")
    reject_release.add_argument("release_name", help="Immutable release name.")
    reject_release.add_argument("--by", required=True, help="Reviewer identity.")
    reject_release.add_argument("--note", default="", help="Optional rejection note.")

    promote_release = subparsers.add_parser("promote-release", help="Mark an approved release as promoted.")
    promote_release.add_argument("release_name", help="Immutable release name.")
    promote_release.add_argument("--by", required=True, help="Operator identity.")
    promote_release.add_argument("--note", default="", help="Optional promotion note.")

    deploy_release_cmd = subparsers.add_parser("deploy-release", help="Mark a release as deployed to an environment and record lineage.")
    deploy_release_cmd.add_argument("release_name", help="Immutable release name.")
    deploy_release_cmd.add_argument("--environment", required=True, help="Deployment environment, for example staging or production.")
    deploy_release_cmd.add_argument("--by", required=True, help="Operator identity.")
    deploy_release_cmd.add_argument("--note", default="", help="Optional deployment note.")

    rollback_release_cmd = subparsers.add_parser("rollback-release", help="Roll back an active environment deployment and restore prior lineage when possible.")
    rollback_release_cmd.add_argument("release_name", help="Immutable release name.")
    rollback_release_cmd.add_argument("--environment", required=True, help="Deployment environment to roll back.")
    rollback_release_cmd.add_argument("--by", required=True, help="Operator identity.")
    rollback_release_cmd.add_argument("--note", default="", help="Optional rollback note.")

    readiness_cmd = subparsers.add_parser("check-deploy-readiness", help="Explain whether a release can deploy to an environment under current policy.")
    readiness_cmd.add_argument("release_name", help="Immutable release name.")
    readiness_cmd.add_argument("--environment", required=True, help="Deployment environment to evaluate.")

    deploy_policy_cmd = subparsers.add_parser("deploy-policy", help="Show the current deployment policy and environment head for an environment.")
    deploy_policy_cmd.add_argument("--environment", required=True, help="Deployment environment to inspect.")

    list_releases_cmd = subparsers.add_parser("list-releases", help="List recorded releases in reverse chronological order.")

    environment_status_cmd = subparsers.add_parser("environment-status", help="Show the current active release for an environment.")
    environment_status_cmd.add_argument("--environment", required=True, help="Deployment environment to inspect.")

    environment_history_cmd = subparsers.add_parser("environment-history", help="Show recent deployment lineage for an environment.")
    environment_history_cmd.add_argument("--environment", required=True, help="Deployment environment to inspect.")
    environment_history_cmd.add_argument("--limit", type=int, default=20, help="Maximum number of deployment entries to return.")

    active_overrides_cmd = subparsers.add_parser("list-active-overrides", help="Show currently effective release overrides for audit and incident review.")
    active_overrides_cmd.add_argument("--release-name", default="", help="Optional release filter.")
    active_overrides_cmd.add_argument("--environment", default="", help="Optional environment filter.")
    active_overrides_cmd.add_argument("--limit", type=int, default=50, help="Maximum number of active overrides to return.")

    readiness_digest_cmd = subparsers.add_parser("release-readiness-digest", help="Show an oncall-oriented readiness digest for a release across multiple environments.")
    readiness_digest_cmd.add_argument("release_name", help="Immutable release name to summarize.")
    readiness_digest_cmd.add_argument("--environment", dest="environments", action="append", default=[], help="Environment to include. Repeat to override the configured default environment set.")

    risk_board_cmd = subparsers.add_parser("release-risk-board", help="Show a ranked operator board across recorded releases.")
    risk_board_cmd.add_argument("--environment", dest="environments", action="append", default=[], help="Environment to include. Repeat to override the configured default environment set.")
    risk_board_cmd.add_argument("--limit", type=int, default=20, help="Maximum number of releases to include.")

    approval_review_board_cmd = subparsers.add_parser("approval-review-board", help="Show release approval backlog and stale approval queues across environments.")
    approval_review_board_cmd.add_argument("--environment", dest="environments", action="append", default=[], help="Environment to include. Repeat to override the configured default environment set.")
    approval_review_board_cmd.add_argument("--limit", type=int, default=20, help="Maximum number of releases to include.")

    override_review_board_cmd = subparsers.add_parser("override-review-board", help="Show override remediation priority across recorded releases.")
    override_review_board_cmd.add_argument("--release-name", default="", help="Optional release filter.")
    override_review_board_cmd.add_argument("--environment", default="", help="Optional environment filter.")
    override_review_board_cmd.add_argument("--limit", type=int, default=50, help="Maximum number of override rows to include.")

    operator_handoff_cmd = subparsers.add_parser("operator-handoff", help="Generate a combined handoff payload for release/oncall shifts.")
    operator_handoff_cmd.add_argument("--environment", dest="environments", action="append", default=[], help="Environment to include. Repeat to override the configured default environment set.")
    operator_handoff_cmd.add_argument("--release-limit", type=int, default=20, help="Maximum number of releases to include in the risk board.")
    operator_handoff_cmd.add_argument("--override-limit", type=int, default=50, help="Maximum number of overrides to include in override sections.")

    record_handoff_cmd = subparsers.add_parser("record-operator-handoff", help="Generate and save an operator handoff snapshot under artifacts/handoffs.")
    record_handoff_cmd.add_argument("--environment", dest="environments", action="append", default=[], help="Environment to include. Repeat to override the configured default environment set.")
    record_handoff_cmd.add_argument("--release-limit", type=int, default=20, help="Maximum number of releases to include in the risk board.")
    record_handoff_cmd.add_argument("--override-limit", type=int, default=50, help="Maximum number of overrides to include in override sections.")
    record_handoff_cmd.add_argument("--label", default="", help="Optional label included in the saved file name.")

    list_handoffs_cmd = subparsers.add_parser("list-operator-handoffs", help="List saved operator handoff snapshots for shift history and audits.")
    list_handoffs_cmd.add_argument("--limit", type=int, default=20, help="Maximum number of saved handoff snapshots to return.")

    show_handoff_cmd = subparsers.add_parser("show-operator-handoff", help="Show one saved operator handoff snapshot by file name or the latest snapshot.")
    show_handoff_cmd.add_argument("snapshot", nargs="?", default="", help="Snapshot file name under artifacts/handoffs or an absolute path.")
    show_handoff_cmd.add_argument("--latest", action="store_true", help="Load the most recently generated handoff snapshot.")

    export_handoff_report_cmd = subparsers.add_parser("export-operator-handoff-report", help="Render a saved operator handoff snapshot as a Markdown report.")
    export_handoff_report_cmd.add_argument("snapshot", nargs="?", default="", help="Snapshot file name under artifacts/handoffs or an absolute path.")
    export_handoff_report_cmd.add_argument("--latest", action="store_true", help="Load the most recently generated handoff snapshot.")
    export_handoff_report_cmd.add_argument("--output", default="", help="Optional output Markdown path. Defaults to the snapshot path with a .md suffix.")
    export_handoff_report_cmd.add_argument("--title", default="", help="Optional report title override.")

    export_governance_summary_cmd = subparsers.add_parser("export-governance-summary", help="Render a manager-facing governance summary across releases, approvals, incidents, and overrides.")
    export_governance_summary_cmd.add_argument("--environment", dest="environments", action="append", default=[], help="Environment to include. Repeat to override the configured default environment set.")
    export_governance_summary_cmd.add_argument("--release-limit", type=int, default=20, help="Maximum number of releases to include in release and approval sections.")
    export_governance_summary_cmd.add_argument("--incident-limit", type=int, default=20, help="Maximum number of incidents to include.")
    export_governance_summary_cmd.add_argument("--override-limit", type=int, default=50, help="Maximum number of overrides to include.")
    export_governance_summary_cmd.add_argument("--output", default="", help="Optional output Markdown path. Defaults to artifacts/reports/governance-summary.md.")
    export_governance_summary_cmd.add_argument("--title", default="", help="Optional report title override.")

    rollout_matrix_cmd = subparsers.add_parser("rollout-matrix", help="Show a multi-environment rollout view, optionally with readiness for a specific release.")
    rollout_matrix_cmd.add_argument("release_name", nargs="?", default="", help="Optional immutable release name to evaluate across environments.")
    rollout_matrix_cmd.add_argument("--environment", dest="environments", action="append", default=[], help="Environment to include. Repeat to override the configured default environment set.")
    return parser


def cmd_run_task(goal: str) -> int:
    runtime = AgentRuntime()
    try:
        trace = runtime.run(Task.create(goal=goal))
        print(json.dumps(trace.to_dict(), indent=2))
    finally:
        runtime.close()
    return 0


def cmd_run_evals(report_name: str, suite_name: str, report_kind: str, report_label: str) -> int:
    settings = load_settings()
    runtime = AgentRuntime()
    try:
        suite = load_suite(settings.project_root, suite_name) if suite_name else load_default_suite(settings.project_root)
        report = run_suite(runtime, suite)
        output_path = settings.reports_dir / report_name
        record = save_report_and_record(
            report,
            output_path,
            report_kind=report_kind,
            label=report_label,
            source="run-evals",
            metadata={"planner_provider": runtime.planner_provider_name},
        )
        print(json.dumps(report.to_dict(), indent=2))
        print(f"report_saved={output_path}")
        print(f"report_registered={record.report_id}")
        print(f"planner_provider={runtime.planner_provider_name}")
    finally:
        runtime.close()
    return 0


def cmd_open_incident(
    severity: str,
    summary: str,
    owner: str,
    environment: str,
    release_name: str,
    source_report: str,
    note: str,
) -> int:
    settings = load_settings()
    record = open_incident(
        severity=severity,
        summary=summary,
        owner=owner,
        environment=environment or None,
        release_name=release_name or None,
        source_report_path=source_report or None,
        note=note,
        ledger_path=settings.incident_ledger_path,
    )
    print(json.dumps(record.to_dict(), indent=2))
    return 0


def cmd_transition_incident(
    incident_id: str,
    status: str,
    actor: str,
    note: str,
    owner: str,
    followup_eval_path: str,
) -> int:
    settings = load_settings()
    record = transition_incident(
        incident_id,
        status=status,
        actor=actor,
        note=note,
        owner=owner or None,
        followup_eval_path=followup_eval_path or None,
        ledger_path=settings.incident_ledger_path,
    )
    print(json.dumps(record.to_dict(), indent=2))
    return 0


def cmd_list_incidents(status: str, severity: str, limit: int) -> int:
    settings = load_settings()
    rows = list_incidents(
        ledger_path=settings.incident_ledger_path,
        status=status or None,
        severity=severity or None,
        limit=limit,
    )
    print(json.dumps([row.to_dict() for row in rows], indent=2))
    return 0


def cmd_incident_status(incident_id: str) -> int:
    settings = load_settings()
    record = get_incident_record(incident_id, ledger_path=settings.incident_ledger_path)
    print(json.dumps(record.to_dict(), indent=2))
    return 0


def _render_incident_markdown(record: dict, *, title: str) -> str:
    lines = [
        f"# {title}",
        "",
        f"- Incident ID: {_markdown_cell(record.get('incident_id'))}",
        f"- Severity: {_markdown_cell(record.get('severity'))}",
        f"- Status: {_markdown_cell(record.get('status'))}",
        f"- Owner: {_markdown_cell(record.get('owner'))}",
        f"- Environment: {_markdown_cell(record.get('environment'))}",
        f"- Release: {_markdown_cell(record.get('release_name'))}",
        f"- Source Report: {_markdown_cell(record.get('source_report_path'))}",
        f"- Follow-up Eval: {_markdown_cell(record.get('followup_eval_path'))}",
        f"- Created At: {_markdown_cell(record.get('created_at'))}",
        f"- Last Updated At: {_markdown_cell(record.get('last_updated_at'))}",
        "",
        "## Summary",
        "",
        record.get("summary", ""),
        "",
        "## Timeline",
        "",
    ]
    lines.extend(
        _render_markdown_table(
            ["Timestamp", "Action", "Actor", "From", "To", "Note"],
            [
                [
                    event.get("timestamp"),
                    event.get("action"),
                    event.get("actor"),
                    event.get("from_status"),
                    event.get("to_status"),
                    event.get("note"),
                ]
                for event in record.get("events", [])
            ],
        )
    )
    lines.append("")
    return "\n".join(lines)


def cmd_export_incident_report(incident_id: str, output: str, title: str) -> int:
    settings = load_settings()
    record = get_incident_record(incident_id, ledger_path=settings.incident_ledger_path).to_dict()
    output_path = Path(output) if output else settings.incidents_dir / f"{incident_id}.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report_title = title.strip() or f"Incident Report: {incident_id}"
    output_path.write_text(_render_incident_markdown(record, title=report_title), encoding="utf-8")
    print(json.dumps({"saved_to": str(output_path), "incident_id": incident_id, "title": report_title}, indent=2))
    return 0


def _find_related_handoff_snapshot_for_incident(settings, incident_record: dict) -> tuple[Path, dict] | None:
    release_name = incident_record.get("release_name")
    incident_id = incident_record.get("incident_id")
    for path, payload in _load_operator_handoff_snapshots(settings.handoffs_dir):
        active_incidents = payload.get("active_incidents", [])
        if any(item.get("incident_id") == incident_id for item in active_incidents):
            return path, payload
        if release_name and any(item.get("release_name") == release_name for item in active_incidents):
            return path, payload
        release_rows = payload.get("release_risk_board", {}).get("rows", [])
        if release_name and any(row.get("release_name") == release_name for row in release_rows):
            return path, payload
    return None


def cmd_export_incident_bundle(incident_id: str, output_dir: str) -> int:
    settings = load_settings()
    incident_record = get_incident_record(incident_id, ledger_path=settings.incident_ledger_path).to_dict()
    bundle_dir = Path(output_dir) if output_dir else settings.incidents_dir / "bundles" / incident_id
    bundle_dir.mkdir(parents=True, exist_ok=True)

    incident_report_path = bundle_dir / "incident-report.md"
    incident_report_path.write_text(
        _render_incident_markdown(incident_record, title=f"Incident Report: {incident_id}"),
        encoding="utf-8",
    )

    release_record = None
    if incident_record.get("release_name"):
        try:
            release_record = get_release_record(
                incident_record["release_name"],
                ledger_path=settings.release_ledger_path,
            ).to_dict()
        except KeyError:
            release_record = None

    related_handoff = _find_related_handoff_snapshot_for_incident(settings, incident_record)
    handoff_snapshot_path = None
    handoff_report_path = None
    if related_handoff is not None:
        handoff_snapshot_path, handoff_payload = related_handoff
        handoff_report_path = bundle_dir / "handoff-report.md"
        handoff_report_path.write_text(
            _render_operator_handoff_markdown(
                handoff_payload,
                title=f"Operator Handoff For {incident_id}",
            ),
            encoding="utf-8",
        )

    manifest = {
        "incident": incident_record,
        "incident_report_path": str(incident_report_path),
        "source_report_path": incident_record.get("source_report_path"),
        "followup_eval_path": incident_record.get("followup_eval_path"),
        "release_record": release_record,
        "related_handoff_snapshot_path": str(handoff_snapshot_path) if handoff_snapshot_path else None,
        "related_handoff_report_path": str(handoff_report_path) if handoff_report_path else None,
    }
    manifest_path = bundle_dir / "bundle-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "saved_to": str(bundle_dir),
                "incident_id": incident_id,
                "bundle_manifest": str(manifest_path),
                "incident_report_path": str(incident_report_path),
                "handoff_report_path": str(handoff_report_path) if handoff_report_path else None,
            },
            indent=2,
        )
    )
    return 0


def cmd_incident_review_board(status: str, limit: int) -> int:
    settings = load_settings()
    board = get_incident_review_board(
        ledger_path=settings.incident_ledger_path,
        stale_minutes=settings.incident_stale_minutes,
        status=status or None,
        limit=limit,
    )
    print(json.dumps(board.to_dict(), indent=2))
    return 0


def cmd_run_mcp_server() -> int:
    settings = load_settings()
    serve(settings.notes_dir)
    return 0


def cmd_list_skills(goal: str) -> int:
    settings = load_settings()
    skills_dir = settings.project_root / "data" / "skills"
    skills = load_skills(skills_dir)
    matched = select_skills(goal, skills) if goal else skills
    payload = [
        {
            "id": skill.id,
            "name": skill.name,
            "description": skill.description,
            "tools": skill.tools,
            "operating_notes": skill.operating_notes,
        }
        for skill in matched
    ]
    print(json.dumps(payload, indent=2))
    return 0


def cmd_explain_patterns(goal: str) -> int:
    if goal:
        recommendation = recommend_pattern(Task.create(goal=goal))
        print(json.dumps({"recommended": asdict(recommendation)}, indent=2))
        return 0
    print(json.dumps({name: asdict(pattern) for name, pattern in PATTERNS.items()}, indent=2))
    return 0


def cmd_compare_reports(baseline: str, candidate: str) -> int:
    comparison = compare_reports(HarnessReport.load(Path(baseline)), HarnessReport.load(Path(candidate)))
    print(json.dumps(comparison.to_dict(), indent=2))
    return 0


def cmd_check_gates(
    report: str,
    min_success_rate: float,
    min_average_score: float,
    max_average_steps: float | None,
    suite_aware_defaults: bool,
) -> int:
    harness_report = HarnessReport.load(Path(report))
    gate_config = (
        default_gate_config_for_suite(harness_report.suite_name)
        if suite_aware_defaults
        else GateConfig(
            min_success_rate=min_success_rate,
            min_average_score=min_average_score,
            max_average_steps=max_average_steps,
        )
    )
    gate_result = check_report_gates(
        harness_report,
        gate_config,
    )
    print(json.dumps(gate_result.to_dict(), indent=2))
    return 0 if gate_result.passed else 1


def cmd_suggest_incident_evals(report: str, output: str) -> int:
    harness_report = HarnessReport.load(Path(report))
    suggestions = suggest_incident_evals(harness_report)
    payload = {
        "count": len(suggestions),
        "suggestions": [
            {
                "task_id": suggestion.task_id,
                "goal": suggestion.goal,
                "grader": suggestion.grader,
                "metadata": suggestion.metadata,
                "source_run_id": suggestion.source_run_id,
                "suggested_dataset": suggestion.suggested_dataset,
                "template_notes": suggestion.template_notes,
            }
            for suggestion in suggestions
        ],
    }
    print(json.dumps(payload, indent=2))
    if output:
        output_path = save_incident_suggestions(suggestions, Path(output))
        print(f"suggestions_saved={output_path}")
    return 0


def cmd_evaluate_promotion(
    baseline: str,
    candidate: str,
    allow_suite_mismatch: bool,
    suite_aware_defaults: bool,
) -> int:
    result = evaluate_promotion(
        HarnessReport.load(Path(baseline)),
        HarnessReport.load(Path(candidate)),
        allow_suite_mismatch=allow_suite_mismatch,
        suite_aware_defaults=suite_aware_defaults,
    )
    print(json.dumps(result.to_dict(), indent=2))
    return 0 if result.passed else 1


def cmd_rollout_review(
    baseline: str,
    candidate: str,
    allow_suite_mismatch: bool,
    suite_aware_defaults: bool,
    output_backfill: str,
) -> int:
    baseline_report = HarnessReport.load(Path(baseline))
    candidate_report = HarnessReport.load(Path(candidate))
    review = build_rollout_review(
        baseline_report,
        candidate_report,
        allow_suite_mismatch=allow_suite_mismatch,
        suite_aware_defaults=suite_aware_defaults,
    )
    print(json.dumps(review.to_dict(), indent=2))
    if output_backfill:
        output_path = save_incident_suggestions(review.candidate_incident_suggestions, Path(output_backfill))
        print(f"suggestions_saved={output_path}")
    return 0 if review.promotion.passed else 1


def cmd_run_shadow(
    baseline: str,
    suite: str,
    report_name: str,
    allow_suite_mismatch: bool,
    suite_aware_defaults: bool,
    output_backfill: str,
) -> int:
    result = run_shadow_suite(
        Path(baseline),
        suite,
        report_name,
        output_backfill=Path(output_backfill) if output_backfill else None,
        allow_suite_mismatch=allow_suite_mismatch,
        suite_aware_defaults=suite_aware_defaults,
        report_kind="shadow_candidate",
        report_label=report_name,
        report_source="run-shadow",
    )
    print(json.dumps(result.to_dict(), indent=2))
    return 0 if result.rollout_review.promotion.passed else 1


def cmd_run_release_shadow(
    suites: list[str],
    report_prefix: str,
    output_backfill_dir: str,
    suite_aware_defaults: bool,
    baseline_manifest: str,
    release_name: str,
) -> int:
    result = run_release_shadow_review(
        suites,
        report_prefix=report_prefix,
        output_backfill_dir=Path(output_backfill_dir) if output_backfill_dir else None,
        suite_aware_defaults=suite_aware_defaults,
        baseline_manifest=Path(baseline_manifest) if baseline_manifest else None,
    )
    payload = result.to_dict()
    if release_name:
        settings = load_settings()
        record = record_release_candidate(
            result,
            release_name=release_name,
            report_prefix=report_prefix,
            releases_dir=settings.releases_dir,
            ledger_path=settings.release_ledger_path,
            manifest_path=settings.release_manifests_dir / f"{release_name}.json",
        )
        payload["release_record"] = record.to_dict()
    print(json.dumps(payload, indent=2))
    return 0 if result.passed else 1


def cmd_register_report(report: str, report_kind: str, report_label: str) -> int:
    record = register_existing_report(
        Path(report),
        report_kind=report_kind,
        label=report_label,
    )
    print(json.dumps(record.to_dict(), indent=2))
    return 0


def cmd_release_status(release_name: str) -> int:
    settings = load_settings()
    record = get_release_record(release_name, ledger_path=settings.release_ledger_path)
    print(json.dumps(record.to_dict(), indent=2))
    return 0


def cmd_approve_release(release_name: str, actor: str, role: str, note: str) -> int:
    settings = load_settings()
    record = transition_release(
        release_name,
        action="approve",
        actor=actor,
        note=note,
        ledger_path=settings.release_ledger_path,
        role=role or actor,
    )
    print(json.dumps(record.to_dict(), indent=2))
    return 0


def cmd_grant_release_override(
    release_name: str,
    environment: str,
    blocker: str,
    actor: str,
    note: str,
    expires_at: str,
) -> int:
    settings = load_settings()
    record = grant_release_override(
        release_name,
        environment=environment,
        blocker=blocker,
        actor=actor,
        note=note,
        expires_at=expires_at or None,
        ledger_path=settings.release_ledger_path,
    )
    print(json.dumps(record.to_dict(), indent=2))
    return 0


def cmd_revoke_release_override(
    release_name: str,
    environment: str,
    blocker: str,
    actor: str,
    note: str,
) -> int:
    settings = load_settings()
    record = revoke_release_override(
        release_name,
        environment=environment,
        blocker=blocker,
        actor=actor,
        note=note,
        ledger_path=settings.release_ledger_path,
    )
    print(json.dumps(record.to_dict(), indent=2))
    return 0


def cmd_reject_release(release_name: str, actor: str, note: str) -> int:
    settings = load_settings()
    record = transition_release(
        release_name,
        action="reject",
        actor=actor,
        note=note,
        ledger_path=settings.release_ledger_path,
    )
    print(json.dumps(record.to_dict(), indent=2))
    return 0


def cmd_promote_release(release_name: str, actor: str, note: str) -> int:
    settings = load_settings()
    record = transition_release(
        release_name,
        action="promote",
        actor=actor,
        note=note,
        ledger_path=settings.release_ledger_path,
    )
    print(json.dumps(record.to_dict(), indent=2))
    return 0


def cmd_deploy_release(release_name: str, environment: str, actor: str, note: str) -> int:
    settings = load_settings()
    record = deploy_release(
        release_name,
        environment=environment,
        actor=actor,
        note=note,
        ledger_path=settings.release_ledger_path,
        production_soak_minutes=settings.production_soak_minutes,
        required_approver_roles=settings.production_required_approver_roles,
        environment_policies=settings.environment_policies,
        environment_freeze_windows=settings.environment_freeze_windows,
    )
    print(json.dumps(record.to_dict(), indent=2))
    return 0


def cmd_rollback_release(release_name: str, environment: str, actor: str, note: str) -> int:
    settings = load_settings()
    record = rollback_release(
        release_name,
        environment=environment,
        actor=actor,
        note=note,
        ledger_path=settings.release_ledger_path,
    )
    print(json.dumps(record.to_dict(), indent=2))
    return 0


def cmd_list_releases() -> int:
    settings = load_settings()
    records = list_releases(ledger_path=settings.release_ledger_path)
    print(json.dumps([record.to_dict() for record in records], indent=2))
    return 0


def cmd_environment_status(environment: str) -> int:
    settings = load_settings()
    status = get_environment_status(environment, ledger_path=settings.release_ledger_path)
    print(json.dumps(status.to_dict(), indent=2))
    return 0


def cmd_environment_history(environment: str, limit: int) -> int:
    settings = load_settings()
    history = get_environment_history(environment, ledger_path=settings.release_ledger_path, limit=limit)
    print(json.dumps([entry.to_dict() for entry in history], indent=2))
    return 0


def cmd_list_active_overrides(release_name: str, environment: str, limit: int) -> int:
    settings = load_settings()
    entries = list_active_overrides(
        ledger_path=settings.release_ledger_path,
        release_name=release_name or None,
        environment=environment or None,
        limit=limit,
    )
    print(json.dumps([entry.to_dict() for entry in entries], indent=2))
    return 0


def cmd_release_readiness_digest(release_name: str, environments: list[str]) -> int:
    settings = load_settings()
    digest = get_release_readiness_digest(
        release_name,
        environments=environments or settings.environment_names,
        ledger_path=settings.release_ledger_path,
        production_soak_minutes=settings.production_soak_minutes,
        required_approver_roles=settings.production_required_approver_roles,
        environment_policies=settings.environment_policies,
        environment_freeze_windows=settings.environment_freeze_windows,
        override_expiring_soon_minutes=settings.override_expiring_soon_minutes,
    )
    print(json.dumps(digest.to_dict(), indent=2))
    return 0 if digest.all_ready else 1


def cmd_release_risk_board(environments: list[str], limit: int) -> int:
    settings = load_settings()
    board = get_release_risk_board(
        environments=environments or settings.environment_names,
        ledger_path=settings.release_ledger_path,
        production_soak_minutes=settings.production_soak_minutes,
        required_approver_roles=settings.production_required_approver_roles,
        environment_policies=settings.environment_policies,
        environment_freeze_windows=settings.environment_freeze_windows,
        override_expiring_soon_minutes=settings.override_expiring_soon_minutes,
        release_stale_minutes=settings.release_stale_minutes,
        limit=limit,
    )
    print(json.dumps(board.to_dict(), indent=2))
    return 0


def cmd_approval_review_board(environments: list[str], limit: int) -> int:
    settings = load_settings()
    board = get_approval_review_board(
        environments=environments or settings.environment_names,
        ledger_path=settings.release_ledger_path,
        production_soak_minutes=settings.production_soak_minutes,
        required_approver_roles=settings.production_required_approver_roles,
        environment_policies=settings.environment_policies,
        environment_freeze_windows=settings.environment_freeze_windows,
        approval_stale_minutes=settings.approval_stale_minutes,
        limit=limit,
    )
    print(json.dumps(board.to_dict(), indent=2))
    return 0


def cmd_override_review_board(release_name: str, environment: str, limit: int) -> int:
    settings = load_settings()
    board = get_override_review_board(
        ledger_path=settings.release_ledger_path,
        release_name=release_name or None,
        environment=environment or None,
        override_expiring_soon_minutes=settings.override_expiring_soon_minutes,
        limit=limit,
    )
    print(json.dumps(board.to_dict(), indent=2))
    return 0


def _build_operator_handoff_payload(
    *,
    environments: list[str],
    release_limit: int,
    override_limit: int,
) -> dict:
    settings = load_settings()
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


def cmd_operator_handoff(environments: list[str], release_limit: int, override_limit: int) -> int:
    payload = _build_operator_handoff_payload(
        environments=environments,
        release_limit=release_limit,
        override_limit=override_limit,
    )
    print(json.dumps(payload, indent=2))
    return 0


def cmd_record_operator_handoff(
    environments: list[str],
    release_limit: int,
    override_limit: int,
    label: str,
) -> int:
    settings = load_settings()
    payload = _build_operator_handoff_payload(
        environments=environments,
        release_limit=release_limit,
        override_limit=override_limit,
    )
    safe_label = sub(r"[^a-zA-Z0-9._-]+", "-", label.strip()).strip("-")
    generated_at = str(payload.get("generated_at", "unknown"))
    file_name = f"operator-handoff-{generated_at.replace(':', '').replace('+', '_')}"
    if safe_label:
        file_name += f"-{safe_label}"
    output_path = settings.handoffs_dir / f"{file_name}.json"
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({"saved_to": str(output_path), "handoff": payload}, indent=2))
    return 0


def _load_operator_handoff_snapshots(handoffs_dir: Path) -> list[tuple[Path, dict]]:
    snapshots: list[tuple[Path, dict]] = []
    for path in handoffs_dir.glob("operator-handoff-*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        snapshots.append((path, payload))
    snapshots.sort(key=lambda item: (str(item[1].get("generated_at", "")), item[0].name), reverse=True)
    return snapshots


def _build_operator_handoff_history_row(path: Path, payload: dict) -> dict:
    release_rows = payload.get("release_risk_board", {}).get("rows", [])
    high_risk_releases = [
        str(row.get("release_name"))
        for row in release_rows
        if row.get("risk_level") == "high" and row.get("release_name")
    ]
    return {
        "saved_to": str(path),
        "file_name": path.name,
        "generated_at": payload.get("generated_at"),
        "environments": payload.get("environments", []),
        "release_count": len(release_rows),
        "high_risk_releases": high_risk_releases,
        "approval_review_count": len(payload.get("approval_review_board", {}).get("rows", [])),
        "override_review_count": len(payload.get("override_review_board", {}).get("rows", [])),
        "incident_review_count": len(payload.get("incident_review_board", {}).get("rows", [])),
        "active_incident_count": len(payload.get("active_incidents", [])),
        "active_override_count": len(payload.get("active_overrides", [])),
        "summary": payload.get("summary", ""),
    }


def cmd_list_operator_handoffs(limit: int) -> int:
    settings = load_settings()
    snapshots = _load_operator_handoff_snapshots(settings.handoffs_dir)
    rows = [
        _build_operator_handoff_history_row(path, payload)
        for path, payload in snapshots[: max(limit, 0)]
    ]
    print(json.dumps({"rows": rows, "total": len(snapshots)}, indent=2))
    return 0


def cmd_show_operator_handoff(snapshot: str, latest: bool) -> int:
    settings = load_settings()
    if latest:
        snapshots = _load_operator_handoff_snapshots(settings.handoffs_dir)
        if not snapshots:
            print(json.dumps({"error": "No saved operator handoff snapshots found."}, indent=2))
            return 1
        path, payload = snapshots[0]
    else:
        if not snapshot:
            print(json.dumps({"error": "snapshot is required unless --latest is provided."}, indent=2))
            return 1
        path = Path(snapshot)
        if not path.is_absolute():
            path = settings.handoffs_dir / snapshot
        if not path.exists():
            print(json.dumps({"error": f"Operator handoff snapshot not found: {path}"}, indent=2))
            return 1
        payload = json.loads(path.read_text(encoding="utf-8"))

    print(json.dumps({"saved_to": str(path), "handoff": payload}, indent=2))
    return 0


def _resolve_operator_handoff_snapshot(settings, snapshot: str, latest: bool) -> tuple[Path | None, dict | None, str | None]:
    if latest:
        snapshots = _load_operator_handoff_snapshots(settings.handoffs_dir)
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


def _markdown_cell(value: object) -> str:
    if value is None:
        return "-"
    if isinstance(value, list):
        text = ", ".join(str(item) for item in value) if value else "-"
    elif isinstance(value, bool):
        text = "yes" if value else "no"
    else:
        text = str(value)
    return text.replace("|", "\\|").replace("\n", "<br>")


def _render_markdown_table(headers: list[str], rows: list[list[object]]) -> list[str]:
    if not rows:
        return ["No items."]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(_markdown_cell(item) for item in row) + " |")
    return lines


def _render_operator_handoff_markdown(payload: dict, *, title: str) -> str:
    release_rows = payload.get("release_risk_board", {}).get("rows", [])
    approval_rows = payload.get("approval_review_board", {}).get("rows", [])
    override_rows = payload.get("override_review_board", {}).get("rows", [])
    active_overrides = payload.get("active_overrides", [])
    incident_rows = payload.get("incident_review_board", {}).get("rows", [])
    active_incidents = payload.get("active_incidents", [])
    lines = [
        f"# {title}",
        "",
        f"- Generated at: {_markdown_cell(payload.get('generated_at'))}",
        f"- Environments: {_markdown_cell(payload.get('environments', []))}",
        "",
        "## Executive Summary",
        "",
        payload.get("summary", "No summary available."),
        "",
        "## Release Risk Board",
        "",
    ]
    lines.extend(
        _render_markdown_table(
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
    lines.extend(
        [
            "",
            "## Incident Review Board",
            "",
        ]
    )
    lines.extend(
        _render_markdown_table(
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
    lines.extend(
        [
            "",
            "## Active Incidents",
            "",
        ]
    )
    lines.extend(
        _render_markdown_table(
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
    lines.extend(
        [
            "",
            "## Approval Review Board",
            "",
        ]
    )
    lines.extend(
        _render_markdown_table(
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
    lines.extend(
        [
            "",
            "## Override Review Board",
            "",
        ]
    )
    lines.extend(
        _render_markdown_table(
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
    lines.extend(
        [
            "",
            "## Active Overrides",
            "",
        ]
    )
    lines.extend(
        _render_markdown_table(
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


def cmd_export_operator_handoff_report(snapshot: str, latest: bool, output: str, title: str) -> int:
    settings = load_settings()
    source_path, payload, error = _resolve_operator_handoff_snapshot(settings, snapshot, latest)
    if error is not None or source_path is None or payload is None:
        print(json.dumps({"error": error or "Unknown snapshot resolution error."}, indent=2))
        return 1

    output_path = Path(output) if output else source_path.with_suffix(".md")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    markdown = _render_operator_handoff_markdown(
        payload,
        title=title.strip() or "Operator Handoff Report",
    )
    output_path.write_text(markdown, encoding="utf-8")
    print(
        json.dumps(
            {
                "saved_to": str(output_path),
                "source_snapshot": str(source_path),
                "title": title.strip() or "Operator Handoff Report",
            },
            indent=2,
        )
    )
    return 0


def _render_governance_summary_markdown(payload: dict, *, title: str) -> str:
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
        f"- Generated at: {_markdown_cell(payload.get('generated_at'))}",
        f"- Environments: {_markdown_cell(payload.get('environments', []))}",
        "",
        "## Summary Metrics",
        "",
    ]
    lines.extend(
        _render_markdown_table(
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
        _render_markdown_table(
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
        _render_markdown_table(
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
        _render_markdown_table(
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
        _render_markdown_table(
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
        _render_markdown_table(
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
        _render_markdown_table(
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
        _render_markdown_table(
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


def cmd_export_governance_summary(
    environments: list[str],
    release_limit: int,
    incident_limit: int,
    override_limit: int,
    output: str,
    title: str,
) -> int:
    settings = load_settings()
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
    payload = {
        "generated_at": json.loads(json.dumps({"timestamp": "placeholder"}))["timestamp"],
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
            "high_risk_release_count": len([row for row in release_risk_board.get("rows", []) if row.get("risk_level") == "high"]),
            "stale_release_count": len([row for row in release_risk_board.get("rows", []) if row.get("is_stale")]),
            "approval_backlog_count": len(approval_review_board.get("rows", [])),
            "stale_approval_count": len([row for row in approval_review_board.get("rows", []) if row.get("is_stale")]),
            "active_incident_count": len(active_incidents),
            "critical_incident_count": len([row for row in active_incidents if row.get("severity") == "critical"]),
            "active_override_count": len(active_overrides),
            "urgent_override_count": len([row for row in override_review_board.get("rows", []) if row.get("status") in {"expired", "expiring_soon"}]),
        },
    }
    payload["generated_at"] = utc_now_iso()
    output_path = Path(output) if output else settings.reports_dir / "governance-summary.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report_title = title.strip() or "Release Governance Summary"
    output_path.write_text(
        _render_governance_summary_markdown(payload, title=report_title),
        encoding="utf-8",
    )
    print(json.dumps({"saved_to": str(output_path), "title": report_title, "metrics": payload["metrics"]}, indent=2))
    return 0


def cmd_rollout_matrix(release_name: str, environments: list[str]) -> int:
    settings = load_settings()
    matrix = get_rollout_matrix(
        environments or settings.environment_names,
        ledger_path=settings.release_ledger_path,
        release_name=release_name or None,
        production_soak_minutes=settings.production_soak_minutes,
        required_approver_roles=settings.production_required_approver_roles,
        environment_policies=settings.environment_policies,
        environment_freeze_windows=settings.environment_freeze_windows,
    )
    print(json.dumps(matrix.to_dict(), indent=2))
    if matrix.all_ready is None:
        return 0
    return 0 if matrix.all_ready else 1


def cmd_check_deploy_readiness(release_name: str, environment: str) -> int:
    settings = load_settings()
    readiness = check_deploy_readiness(
        release_name,
        environment=environment,
        ledger_path=settings.release_ledger_path,
        production_soak_minutes=settings.production_soak_minutes,
        required_approver_roles=settings.production_required_approver_roles,
        environment_policies=settings.environment_policies,
        environment_freeze_windows=settings.environment_freeze_windows,
    )
    print(json.dumps(readiness.to_dict(), indent=2))
    return 0 if readiness.passed else 1


def cmd_deploy_policy(environment: str) -> int:
    settings = load_settings()
    policy = get_deploy_policy(
        environment,
        ledger_path=settings.release_ledger_path,
        production_soak_minutes=settings.production_soak_minutes,
        required_approver_roles=settings.production_required_approver_roles,
        environment_policies=settings.environment_policies,
        environment_freeze_windows=settings.environment_freeze_windows,
    )
    print(json.dumps(policy.to_dict(), indent=2))
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "run-task":
        return cmd_run_task(args.goal)
    if args.command == "run-evals":
        return cmd_run_evals(args.report_name, args.suite, args.report_kind, args.report_label)
    if args.command == "run-mcp-server":
        return cmd_run_mcp_server()
    if args.command == "list-skills":
        return cmd_list_skills(args.goal)
    if args.command == "explain-patterns":
        return cmd_explain_patterns(args.goal)
    if args.command == "compare-reports":
        return cmd_compare_reports(args.baseline, args.candidate)
    if args.command == "check-gates":
        return cmd_check_gates(
            args.report,
            args.min_success_rate,
            args.min_average_score,
            args.max_average_steps,
            args.suite_aware_defaults,
        )
    if args.command == "suggest-incident-evals":
        return cmd_suggest_incident_evals(args.report, args.output)
    if args.command == "open-incident":
        return cmd_open_incident(args.severity, args.summary, args.owner, args.environment, args.release_name, args.source_report, args.note)
    if args.command == "transition-incident":
        return cmd_transition_incident(args.incident_id, args.status, args.by, args.note, args.owner, args.followup_eval_path)
    if args.command == "list-incidents":
        return cmd_list_incidents(args.status, args.severity, args.limit)
    if args.command == "incident-status":
        return cmd_incident_status(args.incident_id)
    if args.command == "export-incident-report":
        return cmd_export_incident_report(args.incident_id, args.output, args.title)
    if args.command == "export-incident-bundle":
        return cmd_export_incident_bundle(args.incident_id, args.output_dir)
    if args.command == "incident-review-board":
        return cmd_incident_review_board(args.status, args.limit)
    if args.command == "evaluate-promotion":
        return cmd_evaluate_promotion(
            args.baseline,
            args.candidate,
            args.allow_suite_mismatch,
            args.suite_aware_defaults,
        )
    if args.command == "rollout-review":
        return cmd_rollout_review(
            args.baseline,
            args.candidate,
            args.allow_suite_mismatch,
            args.suite_aware_defaults,
            args.output_backfill,
        )
    if args.command == "run-shadow":
        return cmd_run_shadow(
            args.baseline,
            args.suite,
            args.report_name,
            args.allow_suite_mismatch,
            args.suite_aware_defaults,
            args.output_backfill,
        )
    if args.command == "run-release-shadow":
        return cmd_run_release_shadow(
            args.suites,
            args.report_prefix,
            args.output_backfill_dir,
            args.suite_aware_defaults,
            args.baseline_manifest,
            args.release_name,
        )
    if args.command == "register-report":
        return cmd_register_report(args.report, args.report_kind, args.report_label)
    if args.command == "release-status":
        return cmd_release_status(args.release_name)
    if args.command == "approve-release":
        return cmd_approve_release(args.release_name, args.by, args.role, args.note)
    if args.command == "grant-release-override":
        return cmd_grant_release_override(
            args.release_name,
            args.environment,
            args.blocker,
            args.by,
            args.note,
            args.expires_at,
        )
    if args.command == "revoke-release-override":
        return cmd_revoke_release_override(
            args.release_name,
            args.environment,
            args.blocker,
            args.by,
            args.note,
        )
    if args.command == "reject-release":
        return cmd_reject_release(args.release_name, args.by, args.note)
    if args.command == "promote-release":
        return cmd_promote_release(args.release_name, args.by, args.note)
    if args.command == "deploy-release":
        return cmd_deploy_release(args.release_name, args.environment, args.by, args.note)
    if args.command == "rollback-release":
        return cmd_rollback_release(args.release_name, args.environment, args.by, args.note)
    if args.command == "list-releases":
        return cmd_list_releases()
    if args.command == "environment-status":
        return cmd_environment_status(args.environment)
    if args.command == "environment-history":
        return cmd_environment_history(args.environment, args.limit)
    if args.command == "list-active-overrides":
        return cmd_list_active_overrides(args.release_name, args.environment, args.limit)
    if args.command == "release-readiness-digest":
        return cmd_release_readiness_digest(args.release_name, args.environments)
    if args.command == "release-risk-board":
        return cmd_release_risk_board(args.environments, args.limit)
    if args.command == "approval-review-board":
        return cmd_approval_review_board(args.environments, args.limit)
    if args.command == "override-review-board":
        return cmd_override_review_board(args.release_name, args.environment, args.limit)
    if args.command == "operator-handoff":
        return cmd_operator_handoff(args.environments, args.release_limit, args.override_limit)
    if args.command == "record-operator-handoff":
        return cmd_record_operator_handoff(args.environments, args.release_limit, args.override_limit, args.label)
    if args.command == "list-operator-handoffs":
        return cmd_list_operator_handoffs(args.limit)
    if args.command == "show-operator-handoff":
        return cmd_show_operator_handoff(args.snapshot, args.latest)
    if args.command == "export-operator-handoff-report":
        return cmd_export_operator_handoff_report(args.snapshot, args.latest, args.output, args.title)
    if args.command == "export-governance-summary":
        return cmd_export_governance_summary(
            args.environments,
            args.release_limit,
            args.incident_limit,
            args.override_limit,
            args.output,
            args.title,
        )
    if args.command == "rollout-matrix":
        return cmd_rollout_matrix(args.release_name, args.environments)
    if args.command == "check-deploy-readiness":
        return cmd_check_deploy_readiness(args.release_name, args.environment)
    if args.command == "deploy-policy":
        return cmd_deploy_policy(args.environment)
    parser.error("Unknown command")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
