from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from agent_architect_lab.models import EvalResult, utc_now_iso


REPORT_REGISTRY_FILE_NAME = "report-registry.json"


@dataclass(slots=True)
class HarnessReport:
    suite_name: str
    results: list[EvalResult]

    @property
    def success_rate(self) -> float:
        if not self.results:
            return 0.0
        return sum(1 for result in self.results if result.success) / len(self.results)

    @property
    def average_score(self) -> float:
        if not self.results:
            return 0.0
        return sum(result.score for result in self.results) / len(self.results)

    @property
    def average_steps(self) -> float:
        if not self.results:
            return 0.0
        return sum(result.steps for result in self.results) / len(self.results)

    @property
    def failures_by_type(self) -> dict[str, int]:
        counter = Counter(
            result.failure_type
            for result in self.results
            if result.failure_type and not result.success
        )
        return dict(counter)

    @property
    def status_counts(self) -> dict[str, int]:
        return dict(Counter(result.status for result in self.results))

    @property
    def results_by_track(self) -> dict[str, dict[str, float]]:
        grouped: dict[str, list[EvalResult]] = {}
        for result in self.results:
            track = str(result.metadata.get("track", "unlabeled"))
            grouped.setdefault(track, []).append(result)
        summaries: dict[str, dict[str, float]] = {}
        for track, results in grouped.items():
            summaries[track] = {
                "tasks": len(results),
                "success_rate": sum(1 for result in results if result.success) / len(results),
                "average_score": sum(result.score for result in results) / len(results),
                "average_steps": sum(result.steps for result in results) / len(results),
            }
        return summaries

    def to_dict(self) -> dict:
        return {
            "suite_name": self.suite_name,
            "success_rate": self.success_rate,
            "average_score": self.average_score,
            "average_steps": self.average_steps,
            "status_counts": self.status_counts,
            "failures_by_type": self.failures_by_type,
            "results_by_track": self.results_by_track,
            "results": [result.to_dict() for result in self.results],
        }

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def from_dict(cls, payload: dict) -> "HarnessReport":
        return cls(
            suite_name=payload["suite_name"],
            results=[EvalResult(**result) for result in payload.get("results", [])],
        )

    @classmethod
    def load(cls, path: Path) -> "HarnessReport":
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))


@dataclass(slots=True)
class ReportRecord:
    report_id: str
    suite_name: str
    report_path: str
    created_at: str
    report_kind: str = "adhoc"
    label: str = ""
    source: str = ""
    report_sha256: str = ""
    success_rate: float = 0.0
    average_score: float = 0.0
    average_steps: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "suite_name": self.suite_name,
            "report_path": self.report_path,
            "created_at": self.created_at,
            "report_kind": self.report_kind,
            "label": self.label,
            "source": self.source,
            "report_sha256": self.report_sha256,
            "success_rate": self.success_rate,
            "average_score": self.average_score,
            "average_steps": self.average_steps,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ReportRecord":
        return cls(
            report_id=payload["report_id"],
            suite_name=payload["suite_name"],
            report_path=payload["report_path"],
            created_at=payload["created_at"],
            report_kind=payload.get("report_kind", "adhoc"),
            label=payload.get("label", ""),
            source=payload.get("source", ""),
            report_sha256=payload.get("report_sha256", ""),
            success_rate=float(payload.get("success_rate", 0.0)),
            average_score=float(payload.get("average_score", 0.0)),
            average_steps=float(payload.get("average_steps", 0.0)),
            metadata=dict(payload.get("metadata", {})),
        )


@dataclass(slots=True)
class ReportRegistry:
    records: list[ReportRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"records": [record.to_dict() for record in self.records]}

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "ReportRegistry":
        if not path.exists():
            return cls()
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(records=[ReportRecord.from_dict(item) for item in payload.get("records", [])])

    def register(
        self,
        report_path: Path,
        report: HarnessReport,
        *,
        report_kind: str = "adhoc",
        label: str = "",
        source: str = "",
        metadata: dict[str, Any] | None = None,
        created_at: str | None = None,
    ) -> ReportRecord:
        resolved_path = report_path.resolve()
        digest = hashlib.sha256(resolved_path.read_bytes()).hexdigest()
        record = ReportRecord(
            report_id=f"report-{digest[:12]}",
            suite_name=report.suite_name,
            report_path=str(resolved_path),
            created_at=created_at or utc_now_iso(),
            report_kind=report_kind,
            label=label,
            source=source,
            report_sha256=digest,
            success_rate=report.success_rate,
            average_score=report.average_score,
            average_steps=report.average_steps,
            metadata=dict(metadata or {}),
        )
        self.records = [
            existing for existing in self.records if Path(existing.report_path).resolve() != resolved_path
        ]
        self.records.append(record)
        self.records.sort(key=lambda item: item.created_at)
        return record

    def find_latest_for_suite(
        self,
        suite_name: str,
        *,
        report_kinds: set[str] | None = None,
        exclude_paths: set[Path] | None = None,
    ) -> ReportRecord | None:
        exclude_paths = {path.resolve() for path in (exclude_paths or set())}
        candidates: list[ReportRecord] = []
        for record in self.records:
            if record.suite_name != suite_name:
                continue
            if report_kinds is not None and record.report_kind not in report_kinds:
                continue
            resolved = Path(record.report_path).resolve()
            if resolved in exclude_paths or not resolved.exists():
                continue
            candidates.append(record)
        if not candidates:
            return None
        candidates.sort(key=lambda item: item.created_at, reverse=True)
        return candidates[0]


def default_registry_path(reports_dir: Path) -> Path:
    return reports_dir / REPORT_REGISTRY_FILE_NAME


def save_report_and_record(
    report: HarnessReport,
    path: Path,
    *,
    report_kind: str = "adhoc",
    label: str = "",
    source: str = "",
    metadata: dict[str, Any] | None = None,
    registry_path: Path | None = None,
) -> ReportRecord:
    report.save(path)
    registry = ReportRegistry.load(registry_path or default_registry_path(path.parent))
    record = registry.register(
        path,
        report,
        report_kind=report_kind,
        label=label,
        source=source,
        metadata=metadata,
    )
    registry.save(registry_path or default_registry_path(path.parent))
    return record


def register_existing_report(
    report_path: Path,
    *,
    report_kind: str = "adhoc",
    label: str = "",
    source: str = "manual_registration",
    metadata: dict[str, Any] | None = None,
    registry_path: Path | None = None,
) -> ReportRecord:
    report = HarnessReport.load(report_path)
    registry_file = registry_path or default_registry_path(report_path.parent)
    registry = ReportRegistry.load(registry_file)
    record = registry.register(
        report_path,
        report,
        report_kind=report_kind,
        label=label,
        source=source,
        metadata=metadata,
    )
    registry.save(registry_file)
    return record


def find_latest_registered_report_for_suite(
    registry_path: Path,
    suite_name: str,
    *,
    report_kinds: set[str] | None = None,
    exclude_paths: set[Path] | None = None,
) -> Path | None:
    record = ReportRegistry.load(registry_path).find_latest_for_suite(
        suite_name,
        report_kinds=report_kinds,
        exclude_paths=exclude_paths,
    )
    if record is None:
        return None
    return Path(record.report_path)


def iter_report_paths(root: Path) -> Iterable[Path]:
    if not root.exists():
        return []
    return sorted(path for path in root.glob("*.json") if path.is_file())


def find_latest_report_for_suite(root: Path, suite_name: str, exclude_paths: set[Path] | None = None) -> Path | None:
    exclude_paths = {path.resolve() for path in (exclude_paths or set())}
    candidates: list[tuple[float, Path]] = []
    for path in iter_report_paths(root):
        resolved = path.resolve()
        if resolved in exclude_paths:
            continue
        try:
            report = HarnessReport.load(path)
        except Exception:
            continue
        if report.suite_name != suite_name:
            continue
        candidates.append((path.stat().st_mtime, path))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]
