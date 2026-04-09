from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from agent_architect_lab.agent.patterns import PATTERNS, recommend_pattern
from agent_architect_lab.agent.runtime import AgentRuntime
from agent_architect_lab.config import load_settings
from agent_architect_lab.evals.tasks import list_available_suites, load_default_suite, load_suite
from agent_architect_lab.harness.compare import compare_reports
from agent_architect_lab.harness.gates import GateConfig, check_report_gates
from agent_architect_lab.harness.incidents import save_incident_suggestions, suggest_incident_evals
from agent_architect_lab.harness.ledger import (
    check_deploy_readiness,
    deploy_release,
    get_environment_status,
    get_release_record,
    list_releases,
    record_release_candidate,
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
from agent_architect_lab.models import Task
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

    list_releases_cmd = subparsers.add_parser("list-releases", help="List recorded releases in reverse chronological order.")

    environment_status_cmd = subparsers.add_parser("environment-status", help="Show the current active release for an environment.")
    environment_status_cmd.add_argument("--environment", required=True, help="Deployment environment to inspect.")
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


def cmd_check_deploy_readiness(release_name: str, environment: str) -> int:
    settings = load_settings()
    readiness = check_deploy_readiness(
        release_name,
        environment=environment,
        ledger_path=settings.release_ledger_path,
        production_soak_minutes=settings.production_soak_minutes,
        required_approver_roles=settings.production_required_approver_roles,
        environment_freeze_windows=settings.environment_freeze_windows,
    )
    print(json.dumps(readiness.to_dict(), indent=2))
    return 0 if readiness.passed else 1


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
    if args.command == "check-deploy-readiness":
        return cmd_check_deploy_readiness(args.release_name, args.environment)
    parser.error("Unknown command")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
