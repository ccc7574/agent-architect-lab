from __future__ import annotations

from pathlib import Path

from agent_architect_lab.harness.suite import ExperimentSuite


SUITE_FILES = {
    "default": "local_tasks.jsonl",
    "local-default": "local_tasks.jsonl",
    "safety": "safety_tasks.jsonl",
    "retrieval": "retrieval_tasks.jsonl",
    "approval": "approval_tasks.jsonl",
    "approval_simulation": "approval_simulation_tasks.jsonl",
    "incident_backfill": "incident_backfill_tasks.jsonl",
    "operator_incident": "operator_incident_tasks.jsonl",
    "planner_reliability": "planner_reliability_tasks.jsonl",
    "long_horizon": "long_horizon_tasks.jsonl",
}


def list_available_suites() -> list[str]:
    return sorted(SUITE_FILES)


def load_suite(project_root: Path, suite_name: str = "default") -> ExperimentSuite:
    if suite_name not in SUITE_FILES:
        available = ", ".join(list_available_suites())
        raise ValueError(f"Unknown suite '{suite_name}'. Available suites: {available}")
    dataset_path = project_root / "src" / "agent_architect_lab" / "evals" / "datasets" / SUITE_FILES[suite_name]
    canonical_name = "local-default" if suite_name == "default" else suite_name
    return ExperimentSuite.from_jsonl(name=canonical_name, path=dataset_path)


def load_default_suite(project_root: Path) -> ExperimentSuite:
    return load_suite(project_root, "default")
