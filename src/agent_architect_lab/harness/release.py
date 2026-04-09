from __future__ import annotations

from collections import Counter
import json
from dataclasses import dataclass, field
from pathlib import Path

from agent_architect_lab.config import load_settings
from agent_architect_lab.harness.policies import PolicyFinding
from agent_architect_lab.harness.reporting import (
    default_registry_path,
    find_latest_registered_report_for_suite,
    find_latest_report_for_suite,
)
from agent_architect_lab.harness.shadow import ShadowRunResult, run_shadow_suite


@dataclass(slots=True)
class BaselineSelection:
    suite_name: str
    report_path: Path
    source: str


@dataclass(slots=True)
class ReleaseShadowReview:
    passed: bool
    suites: list[str]
    suite_results: list[ShadowRunResult]
    missing_baselines: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    policy_findings: list[PolicyFinding] = field(default_factory=list)
    recommended_action: str = "hold"
    summary: str = ""
    suite_recommendations: dict[str, str] = field(default_factory=dict)
    policy_severity_counts: dict[str, int] = field(default_factory=dict)
    baseline_sources: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "suites": self.suites,
            "missing_baselines": self.missing_baselines,
            "blockers": self.blockers,
            "warnings": self.warnings,
            "policy_findings": [finding.to_dict() for finding in self.policy_findings],
            "recommended_action": self.recommended_action,
            "summary": self.summary,
            "suite_recommendations": self.suite_recommendations,
            "policy_severity_counts": self.policy_severity_counts,
            "baseline_sources": self.baseline_sources,
            "suite_results": [result.to_dict() for result in self.suite_results],
        }


def _candidate_report_name(report_prefix: str, suite: str) -> str:
    return f"{report_prefix}-{suite}.json"


def _candidate_report_path(reports_dir: Path, report_prefix: str, suite: str) -> Path:
    return (reports_dir / _candidate_report_name(report_prefix, suite)).resolve()


def _load_baseline_manifest(path: Path) -> dict[str, Path]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    manifest: dict[str, Path] = {}
    for suite_name, entry in payload.items():
        if isinstance(entry, str):
            manifest[suite_name] = Path(entry)
            continue
        if isinstance(entry, dict) and "report_path" in entry:
            manifest[suite_name] = Path(str(entry["report_path"]))
            continue
        raise ValueError(f"Invalid baseline manifest entry for suite '{suite_name}'.")
    return manifest


def _resolve_manifest_path(manifest_path: Path, report_path: Path) -> Path:
    if report_path.is_absolute():
        return report_path.resolve()
    return (manifest_path.parent / report_path).resolve()


def _select_baseline_for_suite(
    reports_dir: Path,
    suite: str,
    *,
    excluded_paths: set[Path],
    registry_path: Path,
    baseline_manifest: Path | None,
) -> BaselineSelection | None:
    if baseline_manifest is not None:
        manifest = _load_baseline_manifest(baseline_manifest)
        if suite not in manifest:
            return None
        resolved = _resolve_manifest_path(baseline_manifest, manifest[suite])
        if resolved in excluded_paths or not resolved.exists():
            return None
        return BaselineSelection(suite_name=suite, report_path=resolved, source="manifest")

    registered = find_latest_registered_report_for_suite(
        registry_path,
        suite,
        report_kinds={"baseline"},
        exclude_paths=excluded_paths,
    )
    if registered is not None:
        return BaselineSelection(suite_name=suite, report_path=registered.resolve(), source="registry")

    discovered = find_latest_report_for_suite(
        reports_dir,
        suite,
        exclude_paths=excluded_paths,
    )
    if discovered is not None:
        return BaselineSelection(suite_name=suite, report_path=discovered.resolve(), source="discovery")
    return None


def run_release_shadow_review(
    suites: list[str],
    *,
    report_prefix: str,
    output_backfill_dir: Path | None = None,
    suite_aware_defaults: bool = True,
    baseline_manifest: Path | None = None,
) -> ReleaseShadowReview:
    settings = load_settings()
    suite_results: list[ShadowRunResult] = []
    missing_baselines: list[str] = []
    blockers: list[str] = []
    warnings: list[str] = []
    policy_findings_by_key: dict[str, PolicyFinding] = {}
    suite_recommendations: dict[str, str] = {}
    baseline_sources: dict[str, str] = {}
    reserved_candidate_paths = {
        _candidate_report_path(settings.reports_dir, report_prefix, suite)
        for suite in suites
    }
    planned_baselines: dict[str, Path] = {}
    excluded_paths = set(reserved_candidate_paths)
    registry_path = default_registry_path(settings.reports_dir)

    for suite in suites:
        selection = _select_baseline_for_suite(
            settings.reports_dir,
            suite,
            excluded_paths=excluded_paths,
            registry_path=registry_path,
            baseline_manifest=baseline_manifest,
        )
        if selection is None:
            missing_baselines.append(suite)
            blockers.append(f"missing_baseline:{suite}")
            continue
        planned_baselines[suite] = selection.report_path
        baseline_sources[suite] = selection.source
        excluded_paths.add(selection.report_path)

    for suite in suites:
        baseline_path = planned_baselines.get(suite)
        if baseline_path is None:
            continue
        backfill_path = None
        if output_backfill_dir is not None:
            output_backfill_dir.mkdir(parents=True, exist_ok=True)
            backfill_path = output_backfill_dir / f"{report_prefix}-{suite}-backfill.jsonl"
        result = run_shadow_suite(
            baseline_path,
            suite,
            _candidate_report_name(report_prefix, suite),
            output_backfill=backfill_path,
            allow_suite_mismatch=False,
            suite_aware_defaults=suite_aware_defaults,
            report_kind="release_candidate",
            report_label=report_prefix,
            report_source="run-release-shadow",
        )
        suite_results.append(result)
        suite_recommendations[suite] = result.rollout_review.promotion.recommended_action
        blockers.extend(f"{suite}:{issue}" for issue in result.rollout_review.promotion.blockers)
        warnings.extend(f"{suite}:{issue}" for issue in result.rollout_review.promotion.warnings)
        for finding in result.rollout_review.policy_findings:
            key = f"{suite}:{finding.policy}"
            policy_findings_by_key[key] = PolicyFinding(
                policy=key,
                severity=finding.severity,
                evidence=finding.evidence,
                recommendation=finding.recommendation,
            )

    blockers = list(dict.fromkeys(blockers))
    warnings = list(dict.fromkeys(warnings))
    passed = not blockers
    recommended_action = "promote" if passed else "hold"
    if passed and warnings:
        recommended_action = "promote_with_review"
    policy_severity_counts = dict(Counter(finding.severity for finding in policy_findings_by_key.values()))
    summary = (
        "Release shadow review passed across all suites."
        if passed and not warnings
        else "Release shadow review passed with warnings across all suites."
        if passed
        else "Release shadow review identified blockers that should hold promotion."
    )
    return ReleaseShadowReview(
        passed=passed,
        suites=suites,
        suite_results=suite_results,
        missing_baselines=missing_baselines,
        blockers=blockers,
        warnings=warnings,
        policy_findings=list(policy_findings_by_key.values()),
        recommended_action=recommended_action,
        summary=summary,
        suite_recommendations=suite_recommendations,
        policy_severity_counts=policy_severity_counts,
        baseline_sources=baseline_sources,
    )
