from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from agent_architect_lab.harness.release import ReleaseShadowReview
from agent_architect_lab.models import utc_now_iso


RELEASE_LEDGER_FILE_NAME = "release-ledger.json"


@dataclass(slots=True)
class ReleaseEvent:
    timestamp: str
    action: str
    actor: str
    from_state: str
    to_state: str
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "action": self.action,
            "actor": self.actor,
            "from_state": self.from_state,
            "to_state": self.to_state,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "ReleaseEvent":
        return cls(
            timestamp=payload["timestamp"],
            action=payload["action"],
            actor=payload["actor"],
            from_state=payload["from_state"],
            to_state=payload["to_state"],
            note=payload.get("note", ""),
        )


@dataclass(slots=True)
class ReleaseSuiteSnapshot:
    suite_name: str
    baseline_report_path: str
    candidate_report_path: str
    baseline_source: str
    recommended_action: str
    blockers: list[str]
    warnings: list[str]
    summary: str

    def to_dict(self) -> dict:
        return {
            "suite_name": self.suite_name,
            "baseline_report_path": self.baseline_report_path,
            "candidate_report_path": self.candidate_report_path,
            "baseline_source": self.baseline_source,
            "recommended_action": self.recommended_action,
            "blockers": self.blockers,
            "warnings": self.warnings,
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "ReleaseSuiteSnapshot":
        return cls(
            suite_name=payload["suite_name"],
            baseline_report_path=payload["baseline_report_path"],
            candidate_report_path=payload["candidate_report_path"],
            baseline_source=payload.get("baseline_source", "unknown"),
            recommended_action=payload["recommended_action"],
            blockers=list(payload.get("blockers", [])),
            warnings=list(payload.get("warnings", [])),
            summary=payload.get("summary", ""),
        )


@dataclass(slots=True)
class ReleaseManifest:
    release_name: str
    report_prefix: str
    created_at: str
    suites: list[str]
    passed: bool
    recommended_action: str
    summary: str
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    baseline_sources: dict[str, str] = field(default_factory=dict)
    suite_snapshots: list[ReleaseSuiteSnapshot] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "release_name": self.release_name,
            "report_prefix": self.report_prefix,
            "created_at": self.created_at,
            "suites": self.suites,
            "passed": self.passed,
            "recommended_action": self.recommended_action,
            "summary": self.summary,
            "blockers": self.blockers,
            "warnings": self.warnings,
            "baseline_sources": self.baseline_sources,
            "suite_snapshots": [snapshot.to_dict() for snapshot in self.suite_snapshots],
        }

    def save(self, path: Path) -> None:
        if path.exists():
            raise FileExistsError(f"Release manifest already exists: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "ReleaseManifest":
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            release_name=payload["release_name"],
            report_prefix=payload["report_prefix"],
            created_at=payload["created_at"],
            suites=list(payload["suites"]),
            passed=payload["passed"],
            recommended_action=payload["recommended_action"],
            summary=payload.get("summary", ""),
            blockers=list(payload.get("blockers", [])),
            warnings=list(payload.get("warnings", [])),
            baseline_sources=dict(payload.get("baseline_sources", {})),
            suite_snapshots=[ReleaseSuiteSnapshot.from_dict(item) for item in payload.get("suite_snapshots", [])],
        )


@dataclass(slots=True)
class ReleaseRecord:
    release_name: str
    manifest_path: str
    created_at: str
    last_updated_at: str
    state: str
    recommended_action: str
    summary: str
    suites: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    events: list[ReleaseEvent] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "release_name": self.release_name,
            "manifest_path": self.manifest_path,
            "created_at": self.created_at,
            "last_updated_at": self.last_updated_at,
            "state": self.state,
            "recommended_action": self.recommended_action,
            "summary": self.summary,
            "suites": self.suites,
            "blockers": self.blockers,
            "warnings": self.warnings,
            "events": [event.to_dict() for event in self.events],
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "ReleaseRecord":
        return cls(
            release_name=payload["release_name"],
            manifest_path=payload["manifest_path"],
            created_at=payload["created_at"],
            last_updated_at=payload.get("last_updated_at", payload["created_at"]),
            state=payload["state"],
            recommended_action=payload["recommended_action"],
            summary=payload.get("summary", ""),
            suites=list(payload.get("suites", [])),
            blockers=list(payload.get("blockers", [])),
            warnings=list(payload.get("warnings", [])),
            events=[ReleaseEvent.from_dict(item) for item in payload.get("events", [])],
        )


@dataclass(slots=True)
class ReleaseLedger:
    records: list[ReleaseRecord] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"records": [record.to_dict() for record in self.records]}

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "ReleaseLedger":
        if not path.exists():
            return cls()
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(records=[ReleaseRecord.from_dict(item) for item in payload.get("records", [])])

    def get(self, release_name: str) -> ReleaseRecord:
        for record in self.records:
            if record.release_name == release_name:
                return record
        raise KeyError(f"Unknown release '{release_name}'.")

    def create(self, manifest: ReleaseManifest, manifest_path: Path) -> ReleaseRecord:
        if any(record.release_name == manifest.release_name for record in self.records):
            raise ValueError(f"Release '{manifest.release_name}' already exists in the ledger.")
        state = "pending_approval" if not manifest.blockers else "blocked"
        timestamp = utc_now_iso()
        record = ReleaseRecord(
            release_name=manifest.release_name,
            manifest_path=str(manifest_path.resolve()),
            created_at=timestamp,
            last_updated_at=timestamp,
            state=state,
            recommended_action=manifest.recommended_action,
            summary=manifest.summary,
            suites=list(manifest.suites),
            blockers=list(manifest.blockers),
            warnings=list(manifest.warnings),
            events=[
                ReleaseEvent(
                    timestamp=timestamp,
                    action="create",
                    actor="system",
                    from_state="none",
                    to_state=state,
                    note="Release manifest recorded.",
                )
            ],
        )
        self.records.append(record)
        self.records.sort(key=lambda item: item.created_at)
        return record

    def transition(self, release_name: str, action: str, actor: str, note: str = "") -> ReleaseRecord:
        record = self.get(release_name)
        target_state = _next_state(record.state, action)
        timestamp = utc_now_iso()
        record.events.append(
            ReleaseEvent(
                timestamp=timestamp,
                action=action,
                actor=actor,
                from_state=record.state,
                to_state=target_state,
                note=note,
            )
        )
        record.state = target_state
        record.last_updated_at = timestamp
        return record


def _next_state(current_state: str, action: str) -> str:
    transitions = {
        "blocked": {"reject": "rejected"},
        "pending_approval": {"approve": "approved", "reject": "rejected"},
        "approved": {"promote": "promoted", "reject": "rejected"},
        "rejected": {},
        "promoted": {},
    }
    next_state = transitions.get(current_state, {}).get(action)
    if next_state is None:
        raise ValueError(f"Cannot apply action '{action}' when release state is '{current_state}'.")
    return next_state


def build_release_manifest(review: ReleaseShadowReview, release_name: str, report_prefix: str) -> ReleaseManifest:
    return ReleaseManifest(
        release_name=release_name,
        report_prefix=report_prefix,
        created_at=utc_now_iso(),
        suites=list(review.suites),
        passed=review.passed,
        recommended_action=review.recommended_action,
        summary=review.summary,
        blockers=list(review.blockers),
        warnings=list(review.warnings),
        baseline_sources=dict(review.baseline_sources),
        suite_snapshots=[
            ReleaseSuiteSnapshot(
                suite_name=result.suite_name,
                baseline_report_path=str(result.baseline_report_path),
                candidate_report_path=str(result.candidate_report_path),
                baseline_source=review.baseline_sources.get(result.suite_name, "unknown"),
                recommended_action=result.rollout_review.promotion.recommended_action,
                blockers=list(result.rollout_review.promotion.blockers),
                warnings=list(result.rollout_review.promotion.warnings),
                summary=result.rollout_review.summary,
            )
            for result in review.suite_results
        ],
    )


def default_release_ledger_path(releases_dir: Path) -> Path:
    return releases_dir / RELEASE_LEDGER_FILE_NAME


def default_release_manifest_path(releases_dir: Path, release_name: str) -> Path:
    return releases_dir / "manifests" / f"{release_name}.json"


def record_release_candidate(
    review: ReleaseShadowReview,
    *,
    release_name: str,
    report_prefix: str,
    releases_dir: Path,
    ledger_path: Path | None = None,
    manifest_path: Path | None = None,
) -> ReleaseRecord:
    manifest = build_release_manifest(review, release_name, report_prefix)
    output_manifest_path = manifest_path or default_release_manifest_path(releases_dir, release_name)
    manifest.save(output_manifest_path)
    output_ledger_path = ledger_path or default_release_ledger_path(releases_dir)
    ledger = ReleaseLedger.load(output_ledger_path)
    record = ledger.create(manifest, output_manifest_path)
    ledger.save(output_ledger_path)
    return record


def get_release_record(release_name: str, *, ledger_path: Path) -> ReleaseRecord:
    return ReleaseLedger.load(ledger_path).get(release_name)


def transition_release(
    release_name: str,
    *,
    action: str,
    actor: str,
    note: str = "",
    ledger_path: Path,
) -> ReleaseRecord:
    ledger = ReleaseLedger.load(ledger_path)
    record = ledger.transition(release_name, action, actor, note)
    ledger.save(ledger_path)
    return record
