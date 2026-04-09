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
    traces_dir: Path
    reports_dir: Path
    checkpoints_dir: Path
    releases_dir: Path
    release_manifests_dir: Path
    release_ledger_path: Path
    notes_dir: Path
    skills_dir: Path
    datasets_dir: Path
    planner_provider: str
    planner_model: str
    planner_api_base: str | None
    planner_api_key: str | None
    planner_timeout_s: float
    planner_max_retries: int
    production_soak_minutes: int
    production_required_approver_roles: list[str]
    environment_names: list[str]
    environment_freeze_windows: dict[str, list[str]]


def _default_artifacts_dir(project_root: Path) -> Path:
    digest = hashlib.sha1(str(project_root).encode("utf-8")).hexdigest()[:8]
    return Path(gettempdir()) / "agent-architect-lab" / f"{project_root.name}-{digest}"


def load_settings() -> Settings:
    project_root = Path(
        os.environ.get("AGENT_ARCHITECT_LAB_ROOT", Path(__file__).resolve().parents[2])
    ).resolve()
    artifacts_dir = Path(
        os.environ.get("AGENT_ARCHITECT_LAB_ARTIFACTS", _default_artifacts_dir(project_root))
    ).resolve()
    traces_dir = artifacts_dir / "traces"
    reports_dir = artifacts_dir / "reports"
    checkpoints_dir = artifacts_dir / "checkpoints"
    releases_dir = artifacts_dir / "releases"
    release_manifests_dir = releases_dir / "manifests"
    release_ledger_path = releases_dir / "release-ledger.json"
    notes_dir = project_root / "data" / "notes"
    skills_dir = project_root / "data" / "skills"
    datasets_dir = project_root / "src" / "agent_architect_lab" / "evals" / "datasets"
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
    environment_names = [
        environment.strip()
        for environment in os.environ.get(
            "AGENT_ARCHITECT_LAB_ENVIRONMENTS",
            "staging,production",
        ).split(",")
        if environment.strip()
    ]
    environment_freeze_windows = {
        str(environment): [str(window) for window in windows]
        for environment, windows in json.loads(
            os.environ.get("AGENT_ARCHITECT_LAB_ENVIRONMENT_FREEZE_WINDOWS", "{}")
        ).items()
    }

    for directory in (
        artifacts_dir,
        traces_dir,
        reports_dir,
        checkpoints_dir,
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
        traces_dir=traces_dir,
        reports_dir=reports_dir,
        checkpoints_dir=checkpoints_dir,
        releases_dir=releases_dir,
        release_manifests_dir=release_manifests_dir,
        release_ledger_path=release_ledger_path,
        notes_dir=notes_dir,
        skills_dir=skills_dir,
        datasets_dir=datasets_dir,
        planner_provider=planner_provider,
        planner_model=planner_model,
        planner_api_base=planner_api_base,
        planner_api_key=planner_api_key,
        planner_timeout_s=planner_timeout_s,
        planner_max_retries=planner_max_retries,
        production_soak_minutes=production_soak_minutes,
        production_required_approver_roles=production_required_approver_roles,
        environment_names=environment_names,
        environment_freeze_windows=environment_freeze_windows,
    )
