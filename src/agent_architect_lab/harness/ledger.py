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
class ReleaseDeployment:
    environment: str
    status: str
    deployed_at: str
    deployed_by: str
    note: str = ""
    replaces_release: str | None = None
    superseded_at: str | None = None
    superseded_by_release: str | None = None
    superseded_note: str = ""
    rolled_back_at: str | None = None
    rolled_back_by: str | None = None
    rollback_note: str = ""
    reactivated_at: str | None = None
    reactivated_by: str | None = None
    reactivation_note: str = ""

    def to_dict(self) -> dict:
        return {
            "environment": self.environment,
            "status": self.status,
            "deployed_at": self.deployed_at,
            "deployed_by": self.deployed_by,
            "note": self.note,
            "replaces_release": self.replaces_release,
            "superseded_at": self.superseded_at,
            "superseded_by_release": self.superseded_by_release,
            "superseded_note": self.superseded_note,
            "rolled_back_at": self.rolled_back_at,
            "rolled_back_by": self.rolled_back_by,
            "rollback_note": self.rollback_note,
            "reactivated_at": self.reactivated_at,
            "reactivated_by": self.reactivated_by,
            "reactivation_note": self.reactivation_note,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "ReleaseDeployment":
        return cls(
            environment=payload["environment"],
            status=payload["status"],
            deployed_at=payload["deployed_at"],
            deployed_by=payload["deployed_by"],
            note=payload.get("note", ""),
            replaces_release=payload.get("replaces_release"),
            superseded_at=payload.get("superseded_at"),
            superseded_by_release=payload.get("superseded_by_release"),
            superseded_note=payload.get("superseded_note", ""),
            rolled_back_at=payload.get("rolled_back_at"),
            rolled_back_by=payload.get("rolled_back_by"),
            rollback_note=payload.get("rollback_note", ""),
            reactivated_at=payload.get("reactivated_at"),
            reactivated_by=payload.get("reactivated_by"),
            reactivation_note=payload.get("reactivation_note", ""),
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
    deployments: list[ReleaseDeployment] = field(default_factory=list)
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
            "deployments": [deployment.to_dict() for deployment in self.deployments],
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
            deployments=[ReleaseDeployment.from_dict(item) for item in payload.get("deployments", [])],
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

    def deploy(self, release_name: str, environment: str, actor: str, note: str = "") -> ReleaseRecord:
        record = self.get(release_name)
        _validate_deploy_transition(record, environment)
        timestamp = utc_now_iso()
        current_head = _current_environment_head(self.records, environment)
        if current_head is not None and current_head[0].release_name == release_name:
            raise ValueError(f"Release '{release_name}' is already active in environment '{environment}'.")

        replaced_release = None
        if current_head is not None:
            replaced_record, replaced_deployment = current_head
            replaced_release = replaced_record.release_name
            replaced_deployment.status = "superseded"
            replaced_deployment.superseded_at = timestamp
            replaced_deployment.superseded_by_release = release_name
            replaced_deployment.superseded_note = note
            replaced_record.last_updated_at = timestamp
            replaced_record.events.append(
                ReleaseEvent(
                    timestamp=timestamp,
                    action=f"superseded:{environment}",
                    actor=actor,
                    from_state=replaced_record.state,
                    to_state=replaced_record.state,
                    note=f"Superseded by release '{release_name}'.",
                )
            )

        record.deployments.append(
            ReleaseDeployment(
                environment=environment,
                status="active",
                deployed_at=timestamp,
                deployed_by=actor,
                note=note,
                replaces_release=replaced_release,
            )
        )
        previous_state = record.state
        if record.state == "approved":
            record.state = "promoted"
        record.last_updated_at = timestamp
        record.events.append(
            ReleaseEvent(
                timestamp=timestamp,
                action=f"deploy:{environment}",
                actor=actor,
                from_state=previous_state,
                to_state=record.state,
                note=note,
            )
        )
        return record

    def rollback(self, release_name: str, environment: str, actor: str, note: str = "") -> ReleaseRecord:
        record = self.get(release_name)
        active_deployment = _find_active_deployment(record, environment)
        if active_deployment is None:
            raise ValueError(f"Release '{release_name}' has no active deployment in environment '{environment}'.")

        timestamp = utc_now_iso()
        active_deployment.status = "rolled_back"
        active_deployment.rolled_back_at = timestamp
        active_deployment.rolled_back_by = actor
        active_deployment.rollback_note = note
        record.last_updated_at = timestamp
        record.events.append(
            ReleaseEvent(
                timestamp=timestamp,
                action=f"rollback:{environment}",
                actor=actor,
                from_state=record.state,
                to_state=record.state,
                note=note,
            )
        )

        restored_release = active_deployment.replaces_release
        if restored_release:
            restored_record = self.get(restored_release)
            restored_deployment = _find_latest_deployment(restored_record, environment, status="superseded")
            if restored_deployment is not None:
                restored_deployment.status = "active"
                restored_deployment.reactivated_at = timestamp
                restored_deployment.reactivated_by = actor
                restored_deployment.reactivation_note = note
                restored_record.last_updated_at = timestamp
                restored_record.events.append(
                    ReleaseEvent(
                        timestamp=timestamp,
                        action=f"reactivate:{environment}",
                        actor=actor,
                        from_state=restored_record.state,
                        to_state=restored_record.state,
                        note=f"Reactivated after rollback of '{release_name}'.",
                    )
                )
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


def _validate_deploy_transition(record: ReleaseRecord, environment: str) -> None:
    if record.state not in {"approved", "promoted"}:
        raise ValueError(f"Release '{record.release_name}' must be approved before deployment.")
    if environment == "production" and _find_active_deployment(record, "staging") is None:
        raise ValueError(f"Release '{record.release_name}' must be active in 'staging' before production deployment.")


def _find_latest_deployment(
    record: ReleaseRecord,
    environment: str,
    *,
    status: str | None = None,
) -> ReleaseDeployment | None:
    for deployment in reversed(record.deployments):
        if deployment.environment != environment:
            continue
        if status is not None and deployment.status != status:
            continue
        return deployment
    return None


def _find_active_deployment(record: ReleaseRecord, environment: str) -> ReleaseDeployment | None:
    return _find_latest_deployment(record, environment, status="active")


def _current_environment_head(
    records: list[ReleaseRecord],
    environment: str,
) -> tuple[ReleaseRecord, ReleaseDeployment] | None:
    candidates: list[tuple[str, ReleaseRecord, ReleaseDeployment]] = []
    for record in records:
        deployment = _find_active_deployment(record, environment)
        if deployment is None:
            continue
        candidates.append((deployment.deployed_at, record, deployment))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    _, record, deployment = candidates[0]
    return record, deployment


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


def deploy_release(
    release_name: str,
    *,
    environment: str,
    actor: str,
    note: str = "",
    ledger_path: Path,
) -> ReleaseRecord:
    ledger = ReleaseLedger.load(ledger_path)
    record = ledger.deploy(release_name, environment, actor, note)
    ledger.save(ledger_path)
    return record


def rollback_release(
    release_name: str,
    *,
    environment: str,
    actor: str,
    note: str = "",
    ledger_path: Path,
) -> ReleaseRecord:
    ledger = ReleaseLedger.load(ledger_path)
    record = ledger.rollback(release_name, environment, actor, note)
    ledger.save(ledger_path)
    return record
