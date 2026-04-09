from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
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
class ReleaseApproval:
    actor: str
    role: str
    timestamp: str
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "actor": self.actor,
            "role": self.role,
            "timestamp": self.timestamp,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "ReleaseApproval":
        return cls(
            actor=payload["actor"],
            role=payload["role"],
            timestamp=payload["timestamp"],
            note=payload.get("note", ""),
        )


@dataclass(slots=True)
class ReleaseOverride:
    environment: str
    blocker: str
    actor: str
    created_at: str
    note: str = ""
    expires_at: str | None = None

    def to_dict(self) -> dict:
        return {
            "environment": self.environment,
            "blocker": self.blocker,
            "actor": self.actor,
            "created_at": self.created_at,
            "note": self.note,
            "expires_at": self.expires_at,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "ReleaseOverride":
        return cls(
            environment=payload["environment"],
            blocker=payload["blocker"],
            actor=payload["actor"],
            created_at=payload["created_at"],
            note=payload.get("note", ""),
            expires_at=payload.get("expires_at"),
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
    approvals: list[ReleaseApproval] = field(default_factory=list)
    overrides: list[ReleaseOverride] = field(default_factory=list)
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
            "approvals": [approval.to_dict() for approval in self.approvals],
            "overrides": [override.to_dict() for override in self.overrides],
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
            approvals=[ReleaseApproval.from_dict(item) for item in payload.get("approvals", [])],
            overrides=[ReleaseOverride.from_dict(item) for item in payload.get("overrides", [])],
            deployments=[ReleaseDeployment.from_dict(item) for item in payload.get("deployments", [])],
            events=[ReleaseEvent.from_dict(item) for item in payload.get("events", [])],
        )


@dataclass(slots=True)
class EnvironmentStatus:
    environment: str
    active_release: str | None
    deployed_at: str | None
    deployed_by: str | None
    status: str

    def to_dict(self) -> dict:
        return {
            "environment": self.environment,
            "active_release": self.active_release,
            "deployed_at": self.deployed_at,
            "deployed_by": self.deployed_by,
            "status": self.status,
        }


@dataclass(slots=True)
class DeployReadiness:
    release_name: str
    environment: str
    passed: bool
    blockers: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    required_state: str = "approved"
    required_predecessor_environment: str | None = None
    soak_minutes_required: int = 0
    soak_minutes_observed: int | None = None
    active_freeze_window: str | None = None

    def to_dict(self) -> dict:
        return {
            "release_name": self.release_name,
            "environment": self.environment,
            "passed": self.passed,
            "blockers": self.blockers,
            "evidence": self.evidence,
            "required_state": self.required_state,
            "required_predecessor_environment": self.required_predecessor_environment,
            "soak_minutes_required": self.soak_minutes_required,
            "soak_minutes_observed": self.soak_minutes_observed,
            "active_freeze_window": self.active_freeze_window,
        }


@dataclass(slots=True)
class DeployPolicy:
    environment: str
    required_state: str
    required_approver_roles: list[str] = field(default_factory=list)
    required_predecessor_environment: str | None = None
    soak_minutes_required: int = 0
    freeze_windows: list[str] = field(default_factory=list)
    active_freeze_window: str | None = None
    environment_status: str = "empty"
    active_release: str | None = None
    active_release_deployed_at: str | None = None
    active_release_deployed_by: str | None = None

    def to_dict(self) -> dict:
        return {
            "environment": self.environment,
            "required_state": self.required_state,
            "required_approver_roles": self.required_approver_roles,
            "required_predecessor_environment": self.required_predecessor_environment,
            "soak_minutes_required": self.soak_minutes_required,
            "freeze_windows": self.freeze_windows,
            "active_freeze_window": self.active_freeze_window,
            "environment_status": self.environment_status,
            "active_release": self.active_release,
            "active_release_deployed_at": self.active_release_deployed_at,
            "active_release_deployed_by": self.active_release_deployed_by,
        }


@dataclass(slots=True)
class EnvironmentPolicySpec:
    required_state: str = "approved"
    required_approver_roles: list[str] = field(default_factory=list)
    required_predecessor_environment: str | None = None
    soak_minutes_required: int = 0
    freeze_windows: list[str] = field(default_factory=list)


@dataclass(slots=True)
class EnvironmentHistoryEntry:
    environment: str
    release_name: str
    status: str
    deployed_at: str
    deployed_by: str
    note: str = ""
    replaces_release: str | None = None
    superseded_at: str | None = None
    superseded_by_release: str | None = None
    rolled_back_at: str | None = None
    rolled_back_by: str | None = None
    reactivated_at: str | None = None
    reactivated_by: str | None = None
    last_transition_at: str = ""

    def to_dict(self) -> dict:
        return {
            "environment": self.environment,
            "release_name": self.release_name,
            "status": self.status,
            "deployed_at": self.deployed_at,
            "deployed_by": self.deployed_by,
            "note": self.note,
            "replaces_release": self.replaces_release,
            "superseded_at": self.superseded_at,
            "superseded_by_release": self.superseded_by_release,
            "rolled_back_at": self.rolled_back_at,
            "rolled_back_by": self.rolled_back_by,
            "reactivated_at": self.reactivated_at,
            "reactivated_by": self.reactivated_by,
            "last_transition_at": self.last_transition_at,
        }


@dataclass(slots=True)
class ActiveOverrideEntry:
    release_name: str
    environment: str
    blocker: str
    actor: str
    created_at: str
    note: str = ""
    expires_at: str | None = None

    def to_dict(self) -> dict:
        return {
            "release_name": self.release_name,
            "environment": self.environment,
            "blocker": self.blocker,
            "actor": self.actor,
            "created_at": self.created_at,
            "note": self.note,
            "expires_at": self.expires_at,
        }


@dataclass(slots=True)
class RolloutMatrixRow:
    environment: str
    policy: DeployPolicy
    readiness: DeployReadiness | None = None
    recommended_action: str = "observe_environment"

    def to_dict(self) -> dict:
        return {
            "environment": self.environment,
            "policy": self.policy.to_dict(),
            "readiness": self.readiness.to_dict() if self.readiness is not None else None,
            "recommended_action": self.recommended_action,
        }


@dataclass(slots=True)
class RolloutMatrix:
    environments: list[str]
    release_name: str | None = None
    all_ready: bool | None = None
    rows: list[RolloutMatrixRow] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "environments": self.environments,
            "release_name": self.release_name,
            "all_ready": self.all_ready,
            "rows": [row.to_dict() for row in self.rows],
        }


@dataclass(slots=True)
class ReleaseReadinessDigest:
    release_name: str
    release_state: str
    environments: list[str]
    all_ready: bool
    blocking_environments: list[str] = field(default_factory=list)
    ready_environments: list[str] = field(default_factory=list)
    recommended_actions: dict[str, str] = field(default_factory=dict)
    active_overrides: list[ActiveOverrideEntry] = field(default_factory=list)
    expiring_overrides: list[ActiveOverrideEntry] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict:
        return {
            "release_name": self.release_name,
            "release_state": self.release_state,
            "environments": self.environments,
            "all_ready": self.all_ready,
            "blocking_environments": self.blocking_environments,
            "ready_environments": self.ready_environments,
            "recommended_actions": self.recommended_actions,
            "active_overrides": [entry.to_dict() for entry in self.active_overrides],
            "expiring_overrides": [entry.to_dict() for entry in self.expiring_overrides],
            "summary": self.summary,
        }


@dataclass(slots=True)
class ReleaseRiskBoardRow:
    release_name: str
    release_state: str
    risk_level: str
    active_environments: list[str] = field(default_factory=list)
    blocking_environments: list[str] = field(default_factory=list)
    active_override_count: int = 0
    expiring_override_count: int = 0
    next_action: str = "observe_release"
    last_updated_at: str = ""
    summary: str = ""

    def to_dict(self) -> dict:
        return {
            "release_name": self.release_name,
            "release_state": self.release_state,
            "risk_level": self.risk_level,
            "active_environments": self.active_environments,
            "blocking_environments": self.blocking_environments,
            "active_override_count": self.active_override_count,
            "expiring_override_count": self.expiring_override_count,
            "next_action": self.next_action,
            "last_updated_at": self.last_updated_at,
            "summary": self.summary,
        }


@dataclass(slots=True)
class ReleaseRiskBoard:
    environments: list[str]
    rows: list[ReleaseRiskBoardRow] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "environments": self.environments,
            "rows": [row.to_dict() for row in self.rows],
        }


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

    def list_records(self) -> list[ReleaseRecord]:
        return sorted(self.records, key=lambda item: item.created_at, reverse=True)

    def environment_status(self, environment: str) -> EnvironmentStatus:
        current_head = _current_environment_head(self.records, environment)
        if current_head is None:
            return EnvironmentStatus(
                environment=environment,
                active_release=None,
                deployed_at=None,
                deployed_by=None,
                status="empty",
            )
        record, deployment = current_head
        return EnvironmentStatus(
            environment=environment,
            active_release=record.release_name,
            deployed_at=deployment.deployed_at,
            deployed_by=deployment.deployed_by,
            status=deployment.status,
        )

    def deploy_policy(
        self,
        environment: str,
        *,
        production_soak_minutes: int,
        required_approver_roles: list[str],
        environment_policies: dict[str, dict[str, object]],
        environment_freeze_windows: dict[str, list[str]],
    ) -> DeployPolicy:
        status = self.environment_status(environment)
        resolved_policy = _resolve_environment_policy(
            environment,
            production_soak_minutes=production_soak_minutes,
            required_approver_roles=required_approver_roles,
            environment_policies=environment_policies,
            environment_freeze_windows=environment_freeze_windows,
        )
        return DeployPolicy(
            environment=environment,
            required_state=resolved_policy.required_state,
            required_approver_roles=list(resolved_policy.required_approver_roles),
            required_predecessor_environment=resolved_policy.required_predecessor_environment,
            soak_minutes_required=resolved_policy.soak_minutes_required,
            freeze_windows=list(resolved_policy.freeze_windows),
            active_freeze_window=_active_freeze_window(environment, resolved_policy.freeze_windows),
            environment_status=status.status,
            active_release=status.active_release,
            active_release_deployed_at=status.deployed_at,
            active_release_deployed_by=status.deployed_by,
        )

    def environment_history(self, environment: str, *, limit: int = 20) -> list[EnvironmentHistoryEntry]:
        entries: list[EnvironmentHistoryEntry] = []
        for record in self.records:
            for deployment in record.deployments:
                if deployment.environment != environment:
                    continue
                entries.append(
                    EnvironmentHistoryEntry(
                        environment=environment,
                        release_name=record.release_name,
                        status=deployment.status,
                        deployed_at=deployment.deployed_at,
                        deployed_by=deployment.deployed_by,
                        note=deployment.note,
                        replaces_release=deployment.replaces_release,
                        superseded_at=deployment.superseded_at,
                        superseded_by_release=deployment.superseded_by_release,
                        rolled_back_at=deployment.rolled_back_at,
                        rolled_back_by=deployment.rolled_back_by,
                        reactivated_at=deployment.reactivated_at,
                        reactivated_by=deployment.reactivated_by,
                        last_transition_at=_latest_timestamp(
                            deployment.deployed_at,
                            deployment.superseded_at,
                            deployment.rolled_back_at,
                            deployment.reactivated_at,
                        ),
                    )
                )
        entries.sort(key=lambda item: item.last_transition_at, reverse=True)
        return entries[:limit]

    def active_overrides(
        self,
        *,
        release_name: str | None = None,
        environment: str | None = None,
        limit: int = 50,
    ) -> list[ActiveOverrideEntry]:
        entries: list[ActiveOverrideEntry] = []
        for record in self.records:
            if release_name is not None and record.release_name != release_name:
                continue
            for override in record.overrides:
                if environment is not None and override.environment != environment:
                    continue
                if not _override_is_active(override):
                    continue
                entries.append(
                    ActiveOverrideEntry(
                        release_name=record.release_name,
                        environment=override.environment,
                        blocker=override.blocker,
                        actor=override.actor,
                        created_at=override.created_at,
                        note=override.note,
                        expires_at=override.expires_at,
                    )
                )
        entries.sort(
            key=lambda item: (
                item.expires_at is None,
                item.expires_at or item.created_at,
                item.created_at,
            )
        )
        return entries[:limit]

    def rollout_matrix(
        self,
        environments: list[str],
        *,
        release_name: str | None,
        production_soak_minutes: int,
        required_approver_roles: list[str],
        environment_policies: dict[str, dict[str, object]],
        environment_freeze_windows: dict[str, list[str]],
    ) -> RolloutMatrix:
        if release_name is not None:
            self.get(release_name)
        rows: list[RolloutMatrixRow] = []
        for environment in environments:
            policy = self.deploy_policy(
                environment,
                production_soak_minutes=production_soak_minutes,
                required_approver_roles=required_approver_roles,
                environment_policies=environment_policies,
                environment_freeze_windows=environment_freeze_windows,
            )
            readiness = None
            if release_name is not None:
                readiness = self.deploy_readiness(
                    release_name,
                    environment,
                    production_soak_minutes=production_soak_minutes,
                    required_approver_roles=required_approver_roles,
                    environment_policies=environment_policies,
                    environment_freeze_windows=environment_freeze_windows,
                )
            rows.append(
                RolloutMatrixRow(
                    environment=environment,
                    policy=policy,
                    readiness=readiness,
                    recommended_action=_recommended_rollout_action(readiness),
                )
            )
        all_ready = None if release_name is None else all(
            row.readiness is not None and row.readiness.passed for row in rows
        )
        return RolloutMatrix(
            environments=list(environments),
            release_name=release_name,
            all_ready=all_ready,
            rows=rows,
        )

    def release_readiness_digest(
        self,
        release_name: str,
        *,
        environments: list[str],
        production_soak_minutes: int,
        required_approver_roles: list[str],
        environment_policies: dict[str, dict[str, object]],
        environment_freeze_windows: dict[str, list[str]],
        override_expiring_soon_minutes: int,
    ) -> ReleaseReadinessDigest:
        record = self.get(release_name)
        matrix = self.rollout_matrix(
            environments,
            release_name=release_name,
            production_soak_minutes=production_soak_minutes,
            required_approver_roles=required_approver_roles,
            environment_policies=environment_policies,
            environment_freeze_windows=environment_freeze_windows,
        )
        active_overrides = self.active_overrides(release_name=release_name)
        expiring_overrides = [
            entry
            for entry in active_overrides
            if entry.expires_at is not None and _minutes_until(entry.expires_at) <= override_expiring_soon_minutes
        ]
        blocking_environments = [
            row.environment
            for row in matrix.rows
            if row.readiness is not None and not row.readiness.passed
        ]
        ready_environments = [
            row.environment
            for row in matrix.rows
            if row.readiness is not None and row.readiness.passed
        ]
        recommended_actions = {
            row.environment: row.recommended_action
            for row in matrix.rows
        }
        summary = _build_readiness_digest_summary(
            release_name,
            all_ready=bool(matrix.all_ready),
            blocking_environments=blocking_environments,
            expiring_override_count=len(expiring_overrides),
        )
        return ReleaseReadinessDigest(
            release_name=release_name,
            release_state=record.state,
            environments=list(environments),
            all_ready=bool(matrix.all_ready),
            blocking_environments=blocking_environments,
            ready_environments=ready_environments,
            recommended_actions=recommended_actions,
            active_overrides=active_overrides,
            expiring_overrides=expiring_overrides,
            summary=summary,
        )

    def release_risk_board(
        self,
        *,
        environments: list[str],
        production_soak_minutes: int,
        required_approver_roles: list[str],
        environment_policies: dict[str, dict[str, object]],
        environment_freeze_windows: dict[str, list[str]],
        override_expiring_soon_minutes: int,
        limit: int,
    ) -> ReleaseRiskBoard:
        rows: list[ReleaseRiskBoardRow] = []
        for record in self.list_records()[:limit]:
            digest = self.release_readiness_digest(
                record.release_name,
                environments=environments,
                production_soak_minutes=production_soak_minutes,
                required_approver_roles=required_approver_roles,
                environment_policies=environment_policies,
                environment_freeze_windows=environment_freeze_windows,
                override_expiring_soon_minutes=override_expiring_soon_minutes,
            )
            active_environments = [
                environment
                for environment in environments
                if _find_active_deployment(record, environment) is not None
            ]
            unresolved_blocking_environments = [
                environment
                for environment in digest.blocking_environments
                if digest.recommended_actions.get(environment) != "no_action_already_active"
            ]
            rows.append(
                ReleaseRiskBoardRow(
                    release_name=record.release_name,
                    release_state=record.state,
                    risk_level=_release_risk_level(
                        record.state,
                        unresolved_blocking_environments=unresolved_blocking_environments,
                        active_override_count=len(digest.active_overrides),
                        expiring_override_count=len(digest.expiring_overrides),
                    ),
                    active_environments=active_environments,
                    blocking_environments=unresolved_blocking_environments,
                    active_override_count=len(digest.active_overrides),
                    expiring_override_count=len(digest.expiring_overrides),
                    next_action=_release_board_next_action(
                        unresolved_blocking_environments=unresolved_blocking_environments,
                        recommended_actions=digest.recommended_actions,
                        active_override_count=len(digest.active_overrides),
                    ),
                    last_updated_at=record.last_updated_at,
                    summary=digest.summary,
                )
            )
        rows.sort(
            key=lambda row: (_release_risk_rank(row.risk_level), row.last_updated_at),
            reverse=True,
        )
        return ReleaseRiskBoard(
            environments=list(environments),
            rows=rows,
        )

    def deploy_readiness(
        self,
        release_name: str,
        environment: str,
        *,
        production_soak_minutes: int,
        required_approver_roles: list[str],
        environment_policies: dict[str, dict[str, object]],
        environment_freeze_windows: dict[str, list[str]],
    ) -> DeployReadiness:
        record = self.get(release_name)
        blockers: list[str] = []
        approval_roles = sorted({approval.role for approval in record.approvals})
        evidence: list[str] = [f"release_state:{record.state}", f"approval_roles:{','.join(approval_roles) or 'none'}"]
        resolved_policy = _resolve_environment_policy(
            environment,
            production_soak_minutes=production_soak_minutes,
            required_approver_roles=required_approver_roles,
            environment_policies=environment_policies,
            environment_freeze_windows=environment_freeze_windows,
        )
        predecessor_environment = resolved_policy.required_predecessor_environment
        soak_minutes_observed: int | None = None
        active_freeze_window = _active_freeze_window(environment, resolved_policy.freeze_windows)

        if not _state_satisfies_requirement(record.state, resolved_policy.required_state):
            blockers.append("release_not_approved")

        if active_freeze_window is not None:
            blockers.append("environment_frozen")
            evidence.append(f"freeze_window:{active_freeze_window}")

        if resolved_policy.required_approver_roles:
            missing_roles = sorted(set(resolved_policy.required_approver_roles) - set(approval_roles))
            if missing_roles:
                blockers.append(f"missing_required_approvals:{','.join(missing_roles)}")
        if predecessor_environment is not None:
            predecessor_deployment = _find_active_deployment(record, predecessor_environment)
            if predecessor_deployment is None:
                blockers.append(_missing_predecessor_blocker(predecessor_environment))
            else:
                evidence.append(f"{predecessor_environment}_deployed_at:{predecessor_deployment.deployed_at}")
                soak_minutes_observed = _minutes_since(predecessor_deployment.deployed_at)
                if soak_minutes_observed < resolved_policy.soak_minutes_required:
                    blockers.append(_predecessor_soak_blocker(predecessor_environment))
                    evidence.append(
                        f"{predecessor_environment}_soak_minutes:{soak_minutes_observed}/{resolved_policy.soak_minutes_required}"
                    )

        current_head = _current_environment_head(self.records, environment)
        if current_head is not None and current_head[0].release_name == release_name:
            blockers.append("already_active_in_environment")

        active_overrides = _active_override_map(record, environment)
        if active_overrides:
            blockers = [blocker for blocker in blockers if blocker not in active_overrides]
            for blocker, override in sorted(active_overrides.items()):
                evidence.append(f"override_applied:{blocker}:{override.actor}")

        return DeployReadiness(
            release_name=release_name,
            environment=environment,
            passed=not blockers,
            blockers=blockers,
            evidence=evidence,
            required_state=resolved_policy.required_state,
            required_predecessor_environment=predecessor_environment,
            soak_minutes_required=resolved_policy.soak_minutes_required,
            soak_minutes_observed=soak_minutes_observed,
            active_freeze_window=active_freeze_window,
        )

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
        if action == "approve":
            return self.approve(release_name, actor, actor, note)
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

    def approve(self, release_name: str, actor: str, role: str, note: str = "") -> ReleaseRecord:
        record = self.get(release_name)
        if record.state not in {"pending_approval", "approved"}:
            raise ValueError(f"Cannot approve release '{release_name}' when state is '{record.state}'.")
        if any(approval.role == role for approval in record.approvals):
            raise ValueError(f"Release '{release_name}' already has an approval for role '{role}'.")
        timestamp = utc_now_iso()
        record.approvals.append(
            ReleaseApproval(
                actor=actor,
                role=role,
                timestamp=timestamp,
                note=note,
            )
        )
        previous_state = record.state
        record.state = "approved"
        record.last_updated_at = timestamp
        record.events.append(
            ReleaseEvent(
                timestamp=timestamp,
                action="approve",
                actor=actor,
                from_state=previous_state,
                to_state=record.state,
                note=note or f"approval_role:{role}",
            )
        )
        return record

    def grant_override(
        self,
        release_name: str,
        environment: str,
        blocker: str,
        actor: str,
        note: str = "",
        *,
        expires_at: str | None = None,
    ) -> ReleaseRecord:
        record = self.get(release_name)
        if blocker in {"already_active_in_environment", "release_not_approved"}:
            raise ValueError(f"Blocker '{blocker}' cannot be overridden.")
        timestamp = utc_now_iso()
        record.overrides.append(
            ReleaseOverride(
                environment=environment,
                blocker=blocker,
                actor=actor,
                created_at=timestamp,
                note=note,
                expires_at=expires_at,
            )
        )
        record.last_updated_at = timestamp
        record.events.append(
            ReleaseEvent(
                timestamp=timestamp,
                action=f"override:{environment}",
                actor=actor,
                from_state=record.state,
                to_state=record.state,
                note=f"{blocker}{f' expires_at:{expires_at}' if expires_at else ''}",
            )
        )
        return record

    def deploy(
        self,
        release_name: str,
        environment: str,
        actor: str,
        note: str = "",
        *,
        production_soak_minutes: int,
        required_approver_roles: list[str],
        environment_policies: dict[str, dict[str, object]],
        environment_freeze_windows: dict[str, list[str]],
    ) -> ReleaseRecord:
        record = self.get(release_name)
        readiness = self.deploy_readiness(
            release_name,
            environment,
            production_soak_minutes=production_soak_minutes,
            required_approver_roles=required_approver_roles,
            environment_policies=environment_policies,
            environment_freeze_windows=environment_freeze_windows,
        )
        if not readiness.passed:
            raise ValueError(
                f"Release '{release_name}' is not deploy-ready for environment '{environment}': "
                + ", ".join(readiness.blockers)
            )
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


def _minutes_since(timestamp: str, *, now: datetime | None = None) -> int:
    observed = datetime.fromisoformat(timestamp)
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=UTC)
    current_time = now or datetime.now(UTC)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=UTC)
    delta = current_time - observed
    if delta < timedelta():
        return 0
    return int(delta.total_seconds() // 60)


def _active_freeze_window(environment: str, freeze_windows: list[str], *, now: datetime | None = None) -> str | None:
    current_time = now or datetime.now().astimezone()
    current_minutes = current_time.hour * 60 + current_time.minute
    for window in freeze_windows:
        try:
            start_text, end_text = window.split("-", 1)
            start_hour, start_minute = (int(part) for part in start_text.split(":", 1))
            end_hour, end_minute = (int(part) for part in end_text.split(":", 1))
        except Exception:
            continue
        start_minutes = start_hour * 60 + start_minute
        end_minutes = end_hour * 60 + end_minute
        if start_minutes <= end_minutes:
            is_active = start_minutes <= current_minutes <= end_minutes
        else:
            is_active = current_minutes >= start_minutes or current_minutes <= end_minutes
        if is_active:
            return window
    return None


def _state_satisfies_requirement(current_state: str, required_state: str) -> bool:
    state_rank = {
        "blocked": 0,
        "pending_approval": 1,
        "approved": 2,
        "promoted": 3,
    }
    if current_state == "rejected":
        return False
    return state_rank.get(current_state, -1) >= state_rank.get(required_state, -1)


def _normalize_policy_roles(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(role).strip() for role in value if str(role).strip()]
    return [role.strip() for role in str(value or "").split(",") if role.strip()]


def _normalize_freeze_windows(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(window).strip() for window in value if str(window).strip()]
    return [window.strip() for window in str(value or "").split(",") if window.strip()]


def _resolve_environment_policy(
    environment: str,
    *,
    production_soak_minutes: int,
    required_approver_roles: list[str],
    environment_policies: dict[str, dict[str, object]],
    environment_freeze_windows: dict[str, list[str]],
) -> EnvironmentPolicySpec:
    policy = dict(environment_policies.get(environment, {}))
    required_state = str(policy.get("required_state", "approved"))
    predecessor_environment = policy.get("required_predecessor_environment")
    if predecessor_environment is not None:
        predecessor_environment = str(predecessor_environment).strip() or None
    elif environment == "production":
        predecessor_environment = "staging"
    soak_minutes_required = int(policy.get("soak_minutes_required", production_soak_minutes if environment == "production" else 0))
    roles = (
        _normalize_policy_roles(policy["required_approver_roles"])
        if "required_approver_roles" in policy
        else (list(required_approver_roles) if environment == "production" else [])
    )
    freeze_windows = (
        _normalize_freeze_windows(policy["freeze_windows"])
        if "freeze_windows" in policy
        else list(environment_freeze_windows.get(environment, []))
    )
    return EnvironmentPolicySpec(
        required_state=required_state,
        required_approver_roles=roles,
        required_predecessor_environment=predecessor_environment,
        soak_minutes_required=soak_minutes_required,
        freeze_windows=freeze_windows,
    )


def _missing_predecessor_blocker(environment: str) -> str:
    if environment == "staging":
        return "missing_active_staging_deployment"
    return f"missing_active_predecessor_deployment:{environment}"


def _predecessor_soak_blocker(environment: str) -> str:
    if environment == "staging":
        return "staging_soak_incomplete"
    return f"predecessor_soak_incomplete:{environment}"


def _override_is_active(override: ReleaseOverride, *, now: datetime | None = None) -> bool:
    if override.expires_at is None:
        return True
    current_time = now or datetime.now(UTC)
    expiry = datetime.fromisoformat(override.expires_at)
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=UTC)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=UTC)
    return current_time <= expiry


def _minutes_until(timestamp: str, *, now: datetime | None = None) -> int:
    expiry = datetime.fromisoformat(timestamp)
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=UTC)
    current_time = now or datetime.now(UTC)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=UTC)
    delta = expiry - current_time
    return int(delta.total_seconds() // 60)


def _active_override_map(record: ReleaseRecord, environment: str) -> dict[str, ReleaseOverride]:
    overrides: dict[str, ReleaseOverride] = {}
    for override in record.overrides:
        if override.environment != environment:
            continue
        if not _override_is_active(override):
            continue
        overrides[override.blocker] = override
    return overrides


def _build_readiness_digest_summary(
    release_name: str,
    *,
    all_ready: bool,
    blocking_environments: list[str],
    expiring_override_count: int,
) -> str:
    if all_ready:
        if expiring_override_count:
            return (
                f"Release '{release_name}' is ready across all evaluated environments, "
                f"with {expiring_override_count} override(s) expiring soon."
            )
        return f"Release '{release_name}' is ready across all evaluated environments."
    summary = (
        f"Release '{release_name}' is blocked in environments: "
        + ", ".join(blocking_environments)
        + "."
    )
    if expiring_override_count:
        summary += f" {expiring_override_count} override(s) expire soon."
    return summary


def _release_risk_rank(level: str) -> int:
    return {"high": 2, "medium": 1, "low": 0}.get(level, -1)


def _release_risk_level(
    release_state: str,
    *,
    unresolved_blocking_environments: list[str],
    active_override_count: int,
    expiring_override_count: int,
) -> str:
    if release_state in {"blocked", "rejected"}:
        return "high"
    if unresolved_blocking_environments or expiring_override_count:
        return "high"
    if active_override_count:
        return "medium"
    return "low"


def _release_board_next_action(
    *,
    unresolved_blocking_environments: list[str],
    recommended_actions: dict[str, str],
    active_override_count: int,
) -> str:
    for environment in unresolved_blocking_environments:
        action = recommended_actions.get(environment)
        if action:
            return action
    if active_override_count:
        return "review_active_overrides"
    return "observe_release"


def _latest_timestamp(*timestamps: str | None) -> str:
    present = [timestamp for timestamp in timestamps if timestamp]
    if not present:
        return ""
    return max(
        present,
        key=lambda item: datetime.fromisoformat(item.replace("Z", "+00:00")),
    )


def _recommended_rollout_action(readiness: DeployReadiness | None) -> str:
    if readiness is None:
        return "observe_environment"
    if readiness.passed:
        return "deploy"
    blockers = set(readiness.blockers)
    if blockers == {"already_active_in_environment"}:
        return "no_action_already_active"
    if "release_not_approved" in blockers:
        return "approve_release"
    if any(blocker.startswith("missing_required_approvals:") for blocker in blockers):
        return "collect_required_approvals"
    if "environment_frozen" in blockers:
        return "wait_for_freeze_window"
    if "missing_active_staging_deployment" in blockers:
        return "deploy_to_staging_first"
    if any(blocker.startswith("missing_active_predecessor_deployment:") for blocker in blockers):
        return "deploy_to_predecessor_first"
    if "staging_soak_incomplete" in blockers:
        return "wait_for_staging_soak"
    if any(blocker.startswith("predecessor_soak_incomplete:") for blocker in blockers):
        return "wait_for_predecessor_soak"
    return "resolve_blockers"


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
    role: str | None = None,
) -> ReleaseRecord:
    ledger = ReleaseLedger.load(ledger_path)
    if action == "approve":
        record = ledger.approve(release_name, actor, role or actor, note)
    else:
        record = ledger.transition(release_name, action, actor, note)
    ledger.save(ledger_path)
    return record


def grant_release_override(
    release_name: str,
    *,
    environment: str,
    blocker: str,
    actor: str,
    note: str = "",
    expires_at: str | None = None,
    ledger_path: Path,
) -> ReleaseRecord:
    ledger = ReleaseLedger.load(ledger_path)
    record = ledger.grant_override(
        release_name,
        environment,
        blocker,
        actor,
        note,
        expires_at=expires_at,
    )
    ledger.save(ledger_path)
    return record


def deploy_release(
    release_name: str,
    *,
    environment: str,
    actor: str,
    note: str = "",
    ledger_path: Path,
    production_soak_minutes: int = 30,
    required_approver_roles: list[str] | None = None,
    environment_policies: dict[str, dict[str, object]] | None = None,
    environment_freeze_windows: dict[str, list[str]] | None = None,
) -> ReleaseRecord:
    ledger = ReleaseLedger.load(ledger_path)
    record = ledger.deploy(
        release_name,
        environment,
        actor,
        note,
        production_soak_minutes=production_soak_minutes,
        required_approver_roles=list(required_approver_roles or []),
        environment_policies=dict(environment_policies or {}),
        environment_freeze_windows=dict(environment_freeze_windows or {}),
    )
    ledger.save(ledger_path)
    return record


def check_deploy_readiness(
    release_name: str,
    *,
    environment: str,
    ledger_path: Path,
    production_soak_minutes: int = 30,
    required_approver_roles: list[str] | None = None,
    environment_policies: dict[str, dict[str, object]] | None = None,
    environment_freeze_windows: dict[str, list[str]] | None = None,
) -> DeployReadiness:
    ledger = ReleaseLedger.load(ledger_path)
    return ledger.deploy_readiness(
        release_name,
        environment,
        production_soak_minutes=production_soak_minutes,
        required_approver_roles=list(required_approver_roles or []),
        environment_policies=dict(environment_policies or {}),
        environment_freeze_windows=dict(environment_freeze_windows or {}),
    )


def get_deploy_policy(
    environment: str,
    *,
    ledger_path: Path,
    production_soak_minutes: int = 30,
    required_approver_roles: list[str] | None = None,
    environment_policies: dict[str, dict[str, object]] | None = None,
    environment_freeze_windows: dict[str, list[str]] | None = None,
) -> DeployPolicy:
    ledger = ReleaseLedger.load(ledger_path)
    return ledger.deploy_policy(
        environment,
        production_soak_minutes=production_soak_minutes,
        required_approver_roles=list(required_approver_roles or []),
        environment_policies=dict(environment_policies or {}),
        environment_freeze_windows=dict(environment_freeze_windows or {}),
    )


def get_environment_history(
    environment: str,
    *,
    ledger_path: Path,
    limit: int = 20,
) -> list[EnvironmentHistoryEntry]:
    ledger = ReleaseLedger.load(ledger_path)
    return ledger.environment_history(environment, limit=limit)


def list_active_overrides(
    *,
    ledger_path: Path,
    release_name: str | None = None,
    environment: str | None = None,
    limit: int = 50,
) -> list[ActiveOverrideEntry]:
    ledger = ReleaseLedger.load(ledger_path)
    return ledger.active_overrides(
        release_name=release_name,
        environment=environment,
        limit=limit,
    )


def get_rollout_matrix(
    environments: list[str],
    *,
    ledger_path: Path,
    release_name: str | None = None,
    production_soak_minutes: int = 30,
    required_approver_roles: list[str] | None = None,
    environment_policies: dict[str, dict[str, object]] | None = None,
    environment_freeze_windows: dict[str, list[str]] | None = None,
) -> RolloutMatrix:
    ledger = ReleaseLedger.load(ledger_path)
    return ledger.rollout_matrix(
        list(environments),
        release_name=release_name,
        production_soak_minutes=production_soak_minutes,
        required_approver_roles=list(required_approver_roles or []),
        environment_policies=dict(environment_policies or {}),
        environment_freeze_windows=dict(environment_freeze_windows or {}),
    )


def get_release_readiness_digest(
    release_name: str,
    *,
    environments: list[str],
    ledger_path: Path,
    production_soak_minutes: int = 30,
    required_approver_roles: list[str] | None = None,
    environment_policies: dict[str, dict[str, object]] | None = None,
    environment_freeze_windows: dict[str, list[str]] | None = None,
    override_expiring_soon_minutes: int = 120,
) -> ReleaseReadinessDigest:
    ledger = ReleaseLedger.load(ledger_path)
    return ledger.release_readiness_digest(
        release_name,
        environments=list(environments),
        production_soak_minutes=production_soak_minutes,
        required_approver_roles=list(required_approver_roles or []),
        environment_policies=dict(environment_policies or {}),
        environment_freeze_windows=dict(environment_freeze_windows or {}),
        override_expiring_soon_minutes=override_expiring_soon_minutes,
    )


def get_release_risk_board(
    *,
    environments: list[str],
    ledger_path: Path,
    production_soak_minutes: int = 30,
    required_approver_roles: list[str] | None = None,
    environment_policies: dict[str, dict[str, object]] | None = None,
    environment_freeze_windows: dict[str, list[str]] | None = None,
    override_expiring_soon_minutes: int = 120,
    limit: int = 20,
) -> ReleaseRiskBoard:
    ledger = ReleaseLedger.load(ledger_path)
    return ledger.release_risk_board(
        environments=list(environments),
        production_soak_minutes=production_soak_minutes,
        required_approver_roles=list(required_approver_roles or []),
        environment_policies=dict(environment_policies or {}),
        environment_freeze_windows=dict(environment_freeze_windows or {}),
        override_expiring_soon_minutes=override_expiring_soon_minutes,
        limit=limit,
    )


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


def list_releases(*, ledger_path: Path) -> list[ReleaseRecord]:
    return ReleaseLedger.load(ledger_path).list_records()


def get_environment_status(environment: str, *, ledger_path: Path) -> EnvironmentStatus:
    return ReleaseLedger.load(ledger_path).environment_status(environment)
