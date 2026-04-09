from __future__ import annotations

from dataclasses import dataclass, field

from agent_architect_lab.harness.reporting import HarnessReport
from agent_architect_lab.harness.taxonomy import BLOCKING_FAILURE_TYPES


@dataclass(slots=True)
class GateConfig:
    min_success_rate: float = 1.0
    min_average_score: float = 0.95
    max_average_steps: float | None = None
    blocked_failure_types: tuple[str, ...] = BLOCKING_FAILURE_TYPES


@dataclass(slots=True)
class GateResult:
    passed: bool
    failures: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"passed": self.passed, "failures": self.failures}


def check_report_gates(report: HarnessReport, config: GateConfig | None = None) -> GateResult:
    config = config or GateConfig()
    failures: list[str] = []
    if report.success_rate < config.min_success_rate:
        failures.append(f"success_rate_below_threshold:{report.success_rate:.3f}<{config.min_success_rate:.3f}")
    if report.average_score < config.min_average_score:
        failures.append(f"average_score_below_threshold:{report.average_score:.3f}<{config.min_average_score:.3f}")
    if config.max_average_steps is not None and report.average_steps > config.max_average_steps:
        failures.append(f"average_steps_above_threshold:{report.average_steps:.3f}>{config.max_average_steps:.3f}")
    for failure_type in config.blocked_failure_types:
        count = report.failures_by_type.get(failure_type, 0)
        if count:
            failures.append(f"blocked_failure_type_present:{failure_type}:{count}")
    return GateResult(passed=not failures, failures=failures)
