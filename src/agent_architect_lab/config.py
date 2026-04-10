from __future__ import annotations

import os
import json
from dataclasses import dataclass
import hashlib
from pathlib import Path
from tempfile import gettempdir


@dataclass(slots=True)
class Settings:
    project_root: Path
    artifacts_dir: Path
    control_plane_dir: Path
    control_plane_request_log_path: Path
    control_plane_idempotency_path: Path
    control_plane_job_registry_path: Path
    traces_dir: Path
    reports_dir: Path
    checkpoints_dir: Path
    handoffs_dir: Path
    incidents_dir: Path
    releases_dir: Path
    release_manifests_dir: Path
    release_ledger_path: Path
    incident_ledger_path: Path
    notes_dir: Path
    skills_dir: Path
    datasets_dir: Path
    control_plane_host: str
    control_plane_port: int
    control_plane_read_token: str | None
    control_plane_mutation_token: str | None
    control_plane_role_policies: dict[str, list[str]]
    control_plane_job_poll_interval_s: float
    planner_provider: str
    planner_model: str
    planner_api_base: str | None
    planner_api_key: str | None
    planner_timeout_s: float
    planner_max_retries: int
    production_soak_minutes: int
    production_required_approver_roles: list[str]
    environment_names: list[str]
    environment_policies: dict[str, dict[str, object]]
    environment_freeze_windows: dict[str, list[str]]
    override_expiring_soon_minutes: int
    release_stale_minutes: int
    approval_stale_minutes: int
    incident_stale_minutes: int


def _default_artifacts_dir(project_root: Path) -> Path:
    digest = hashlib.sha1(str(project_root).encode("utf-8")).hexdigest()[:8]
    return Path(gettempdir()) / "agent-architect-lab" / f"{project_root.name}-{digest}"


def _normalize_role_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def load_settings() -> Settings:
    project_root = Path(
        os.environ.get("AGENT_ARCHITECT_LAB_ROOT", Path(__file__).resolve().parents[2])
    ).resolve()
    artifacts_dir = Path(
        os.environ.get("AGENT_ARCHITECT_LAB_ARTIFACTS", _default_artifacts_dir(project_root))
    ).resolve()
    control_plane_dir = artifacts_dir / "control-plane"
    control_plane_request_log_path = control_plane_dir / "mutation-requests.jsonl"
    control_plane_idempotency_path = control_plane_dir / "idempotency-registry.json"
    control_plane_job_registry_path = control_plane_dir / "job-registry.json"
    traces_dir = artifacts_dir / "traces"
    reports_dir = artifacts_dir / "reports"
    checkpoints_dir = artifacts_dir / "checkpoints"
    handoffs_dir = artifacts_dir / "handoffs"
    incidents_dir = artifacts_dir / "incidents"
    releases_dir = artifacts_dir / "releases"
    release_manifests_dir = releases_dir / "manifests"
    release_ledger_path = releases_dir / "release-ledger.json"
    incident_ledger_path = incidents_dir / "incident-ledger.json"
    notes_dir = project_root / "data" / "notes"
    skills_dir = project_root / "data" / "skills"
    datasets_dir = project_root / "src" / "agent_architect_lab" / "evals" / "datasets"
    control_plane_host = os.environ.get("AGENT_ARCHITECT_LAB_CONTROL_PLANE_HOST", "127.0.0.1").strip() or "127.0.0.1"
    control_plane_port = int(os.environ.get("AGENT_ARCHITECT_LAB_CONTROL_PLANE_PORT", "8080"))
    control_plane_read_token = os.environ.get("AGENT_ARCHITECT_LAB_CONTROL_PLANE_READ_TOKEN") or None
    control_plane_mutation_token = os.environ.get("AGENT_ARCHITECT_LAB_CONTROL_PLANE_MUTATION_TOKEN") or None
    raw_control_plane_role_policies = json.loads(
        os.environ.get(
            "AGENT_ARCHITECT_LAB_CONTROL_PLANE_ROLE_POLICIES",
            json.dumps(
                {
                    "read_governance": [
                        "control-plane-admin",
                        "release-manager",
                        "ops-oncall",
                        "incident-commander",
                        "qa-owner",
                    ],
                    "read_jobs": [
                        "control-plane-admin",
                        "release-manager",
                        "ops-oncall",
                        "incident-commander",
                        "qa-owner",
                    ],
                    "create_export_job": [
                        "control-plane-admin",
                        "release-manager",
                        "ops-oncall",
                        "incident-commander",
                    ],
                    "retry_job": [
                        "control-plane-admin",
                        "release-manager",
                        "ops-oncall",
                        "incident-commander",
                    ],
                    "approve_release": [
                        "control-plane-admin",
                        "release-manager",
                        "qa-owner",
                    ],
                    "reject_release": [
                        "control-plane-admin",
                        "release-manager",
                        "qa-owner",
                    ],
                    "promote_release": [
                        "control-plane-admin",
                        "release-manager",
                    ],
                    "deploy_release": [
                        "control-plane-admin",
                        "release-manager",
                        "ops-oncall",
                    ],
                    "manage_release_override": [
                        "control-plane-admin",
                        "release-manager",
                        "ops-oncall",
                        "incident-commander",
                    ],
                    "open_incident": [
                        "control-plane-admin",
                        "release-manager",
                        "ops-oncall",
                        "incident-commander",
                    ],
                    "transition_incident": [
                        "control-plane-admin",
                        "release-manager",
                        "ops-oncall",
                        "incident-commander",
                    ],
                }
            ),
        )
    )
    control_plane_role_policies = {
        str(route_key): _normalize_role_list(roles)
        for route_key, roles in raw_control_plane_role_policies.items()
    }
    control_plane_job_poll_interval_s = float(
        os.environ.get("AGENT_ARCHITECT_LAB_CONTROL_PLANE_JOB_POLL_INTERVAL_S", "0.25")
    )
    planner_provider = os.environ.get("AGENT_ARCHITECT_LAB_PLANNER_PROVIDER", "heuristic").strip().lower()
    planner_model = os.environ.get("AGENT_ARCHITECT_LAB_PLANNER_MODEL", "gpt-4.1-mini")
    planner_api_base = os.environ.get("AGENT_ARCHITECT_LAB_PLANNER_API_BASE")
    planner_api_key = os.environ.get("AGENT_ARCHITECT_LAB_PLANNER_API_KEY")
    planner_timeout_s = float(os.environ.get("AGENT_ARCHITECT_LAB_PLANNER_TIMEOUT_S", "20"))
    planner_max_retries = int(os.environ.get("AGENT_ARCHITECT_LAB_PLANNER_MAX_RETRIES", "2"))
    production_soak_minutes = int(os.environ.get("AGENT_ARCHITECT_LAB_PRODUCTION_SOAK_MINUTES", "30"))
    production_required_approver_roles = [
        role.strip()
        for role in os.environ.get(
            "AGENT_ARCHITECT_LAB_PRODUCTION_REQUIRED_APPROVER_ROLES",
            "qa-owner,release-manager",
        ).split(",")
        if role.strip()
    ]
    raw_environment_policies = json.loads(
        os.environ.get("AGENT_ARCHITECT_LAB_ENVIRONMENT_POLICIES", "{}")
    )
    environment_policies = {
        str(environment): {
            "required_state": str(policy.get("required_state", "approved")),
            "required_predecessor_environment": (
                str(policy["required_predecessor_environment"])
                if policy.get("required_predecessor_environment")
                else None
            ),
            "soak_minutes_required": int(policy.get("soak_minutes_required", 0)),
            "required_approver_roles": [
                str(role)
                for role in (
                    policy.get("required_approver_roles", [])
                    if isinstance(policy.get("required_approver_roles", []), list)
                    else str(policy.get("required_approver_roles", "")).split(",")
                )
                if str(role).strip()
            ],
            "freeze_windows": [
                str(window)
                for window in (
                    policy.get("freeze_windows", [])
                    if isinstance(policy.get("freeze_windows", []), list)
                    else str(policy.get("freeze_windows", "")).split(",")
                )
                if str(window).strip()
            ],
        }
        for environment, policy in raw_environment_policies.items()
    }
    environment_freeze_windows = {
        str(environment): [str(window) for window in windows]
        for environment, windows in json.loads(
            os.environ.get("AGENT_ARCHITECT_LAB_ENVIRONMENT_FREEZE_WINDOWS", "{}")
        ).items()
    }
    override_expiring_soon_minutes = int(
        os.environ.get("AGENT_ARCHITECT_LAB_OVERRIDE_EXPIRING_SOON_MINUTES", "120")
    )
    release_stale_minutes = int(
        os.environ.get("AGENT_ARCHITECT_LAB_RELEASE_STALE_MINUTES", "240")
    )
    approval_stale_minutes = int(
        os.environ.get("AGENT_ARCHITECT_LAB_APPROVAL_STALE_MINUTES", "120")
    )
    incident_stale_minutes = int(
        os.environ.get("AGENT_ARCHITECT_LAB_INCIDENT_STALE_MINUTES", "60")
    )
    configured_environment_names = os.environ.get("AGENT_ARCHITECT_LAB_ENVIRONMENTS")
    if configured_environment_names is not None:
        environment_names = [
            environment.strip()
            for environment in configured_environment_names.split(",")
            if environment.strip()
        ]
    else:
        environment_names = ["staging", "production"]
        for environment in list(environment_policies) + list(environment_freeze_windows):
            if environment not in environment_names:
                environment_names.append(environment)

    for directory in (
        artifacts_dir,
        control_plane_dir,
        traces_dir,
        reports_dir,
        checkpoints_dir,
        handoffs_dir,
        incidents_dir,
        releases_dir,
        release_manifests_dir,
        notes_dir,
        skills_dir,
        datasets_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    return Settings(
        project_root=project_root,
        artifacts_dir=artifacts_dir,
        control_plane_dir=control_plane_dir,
        control_plane_request_log_path=control_plane_request_log_path,
        control_plane_idempotency_path=control_plane_idempotency_path,
        control_plane_job_registry_path=control_plane_job_registry_path,
        traces_dir=traces_dir,
        reports_dir=reports_dir,
        checkpoints_dir=checkpoints_dir,
        handoffs_dir=handoffs_dir,
        incidents_dir=incidents_dir,
        releases_dir=releases_dir,
        release_manifests_dir=release_manifests_dir,
        release_ledger_path=release_ledger_path,
        incident_ledger_path=incident_ledger_path,
        notes_dir=notes_dir,
        skills_dir=skills_dir,
        datasets_dir=datasets_dir,
        control_plane_host=control_plane_host,
        control_plane_port=control_plane_port,
        control_plane_read_token=control_plane_read_token,
        control_plane_mutation_token=control_plane_mutation_token,
        control_plane_role_policies=control_plane_role_policies,
        control_plane_job_poll_interval_s=control_plane_job_poll_interval_s,
        planner_provider=planner_provider,
        planner_model=planner_model,
        planner_api_base=planner_api_base,
        planner_api_key=planner_api_key,
        planner_timeout_s=planner_timeout_s,
        planner_max_retries=planner_max_retries,
        production_soak_minutes=production_soak_minutes,
        production_required_approver_roles=production_required_approver_roles,
        environment_names=environment_names,
        environment_policies=environment_policies,
        environment_freeze_windows=environment_freeze_windows,
        override_expiring_soon_minutes=override_expiring_soon_minutes,
        release_stale_minutes=release_stale_minutes,
        approval_stale_minutes=approval_stale_minutes,
        incident_stale_minutes=incident_stale_minutes,
    )
