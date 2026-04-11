from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from agent_architect_lab.harness.feedback import FeedbackLedger, FeedbackRecord
from agent_architect_lab.harness.reporting import HarnessReport
from agent_architect_lab.models import utc_now_iso


FAILURE_TO_TRACK = {
    "planner_invalid_tool": "planner-reliability",
    "planner_invalid_response": "planner-reliability",
    "planner_http_error": "planner-reliability",
    "planner_network_error": "planner-reliability",
    "planner_timeout": "planner-reliability",
    "tool_execution_error": "tool-use",
    "tool_timeout": "tool-use",
    "safety_violation": "safety",
    "mcp_unavailable": "retrieval",
    "retrieval_miss": "retrieval",
    "trace_shape_mismatch": "workflow-shape",
    "approval_signal_missing": "approvals",
    "skill_routing_mismatch": "skills",
}

TRACK_TO_DATASET = {
    "approvals": "approval_tasks.jsonl",
    "incident-followup": "incident_backfill_tasks.jsonl",
    "planner-reliability": "planner_reliability_tasks.jsonl",
    "retrieval": "retrieval_tasks.jsonl",
    "safety": "safety_tasks.jsonl",
    "skills": "incident_backfill_tasks.jsonl",
    "tool-use": "incident_backfill_tasks.jsonl",
    "workflow-shape": "incident_backfill_tasks.jsonl",
}

TRACK_PRIORITY_WEIGHTS = {
    "safety": 60,
    "approvals": 52,
    "retrieval": 44,
    "planner-reliability": 42,
    "tool-use": 40,
    "workflow-shape": 36,
    "skills": 34,
    "incident-followup": 30,
}

FAILURE_PRIORITY_WEIGHTS = {
    "safety_violation": 18,
    "approval_signal_missing": 15,
    "retrieval_miss": 12,
    "mcp_unavailable": 12,
    "planner_timeout": 10,
    "planner_http_error": 8,
    "planner_network_error": 8,
    "tool_timeout": 8,
    "tool_execution_error": 8,
    "trace_shape_mismatch": 6,
    "skill_routing_mismatch": 6,
}

SENTIMENT_PRIORITY_BONUS = {
    "negative": 14,
    "neutral": 4,
    "positive": -8,
}

ACTIONABILITY_PRIORITY_BONUS = {
    "observe": 0,
    "followup_required": 12,
    "urgent_followup": 24,
}

LABEL_PRIORITY_HINTS = {
    "safety": {"safety"},
    "approvals": {"approval", "approvals", "rollback"},
    "retrieval": {"retrieval", "mcp"},
    "planner-reliability": {"planner"},
    "tool-use": {"tool"},
    "workflow-shape": {"workflow", "trace"},
    "skills": {"skill", "routing"},
}


@dataclass(slots=True)
class IncidentEvent:
    timestamp: str
    action: str
    actor: str
    from_status: str
    to_status: str
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "action": self.action,
            "actor": self.actor,
            "from_status": self.from_status,
            "to_status": self.to_status,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "IncidentEvent":
        return cls(
            timestamp=payload["timestamp"],
            action=payload["action"],
            actor=payload["actor"],
            from_status=payload["from_status"],
            to_status=payload["to_status"],
            note=payload.get("note", ""),
        )


@dataclass(slots=True)
class IncidentRecord:
    incident_id: str
    created_at: str
    last_updated_at: str
    severity: str
    status: str
    summary: str
    owner: str
    environment: str | None = None
    release_name: str | None = None
    source_report_path: str | None = None
    followup_eval_path: str | None = None
    followup_eval_linked_at: str | None = None
    followup_eval_linked_by: str | None = None
    events: list[IncidentEvent] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "incident_id": self.incident_id,
            "created_at": self.created_at,
            "last_updated_at": self.last_updated_at,
            "severity": self.severity,
            "status": self.status,
            "summary": self.summary,
            "owner": self.owner,
            "environment": self.environment,
            "release_name": self.release_name,
            "source_report_path": self.source_report_path,
            "followup_eval_path": self.followup_eval_path,
            "followup_eval_linked_at": self.followup_eval_linked_at,
            "followup_eval_linked_by": self.followup_eval_linked_by,
            "events": [event.to_dict() for event in self.events],
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "IncidentRecord":
        return cls(
            incident_id=payload["incident_id"],
            created_at=payload["created_at"],
            last_updated_at=payload.get("last_updated_at", payload["created_at"]),
            severity=payload["severity"],
            status=payload["status"],
            summary=payload["summary"],
            owner=payload["owner"],
            environment=payload.get("environment"),
            release_name=payload.get("release_name"),
            source_report_path=payload.get("source_report_path"),
            followup_eval_path=payload.get("followup_eval_path"),
            followup_eval_linked_at=payload.get("followup_eval_linked_at"),
            followup_eval_linked_by=payload.get("followup_eval_linked_by"),
            events=[IncidentEvent.from_dict(item) for item in payload.get("events", [])],
        )


@dataclass(slots=True)
class IncidentReviewBoardRow:
    incident_id: str
    severity: str
    status: str
    risk_level: str
    owner: str
    summary: str
    environment: str | None = None
    release_name: str | None = None
    followup_eval_path: str | None = None
    is_stale: bool = False
    minutes_since_update: int = 0
    recommended_action: str = "observe_incident"

    def to_dict(self) -> dict:
        return {
            "incident_id": self.incident_id,
            "severity": self.severity,
            "status": self.status,
            "risk_level": self.risk_level,
            "owner": self.owner,
            "summary": self.summary,
            "environment": self.environment,
            "release_name": self.release_name,
            "followup_eval_path": self.followup_eval_path,
            "is_stale": self.is_stale,
            "minutes_since_update": self.minutes_since_update,
            "recommended_action": self.recommended_action,
        }


@dataclass(slots=True)
class IncidentReviewBoard:
    rows: list[IncidentReviewBoardRow] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"rows": [row.to_dict() for row in self.rows]}


@dataclass(slots=True)
class IncidentLedger:
    records: list[IncidentRecord] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"records": [record.to_dict() for record in self.records]}

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "IncidentLedger":
        if not path.exists():
            return cls()
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(records=[IncidentRecord.from_dict(item) for item in payload.get("records", [])])

    def get(self, incident_id: str) -> IncidentRecord:
        for record in self.records:
            if record.incident_id == incident_id:
                return record
        raise KeyError(f"Unknown incident '{incident_id}'.")

    def list_records(self) -> list[IncidentRecord]:
        return sorted(self.records, key=lambda item: item.created_at, reverse=True)

    def open_incident(
        self,
        *,
        severity: str,
        summary: str,
        owner: str,
        environment: str | None = None,
        release_name: str | None = None,
        source_report_path: str | None = None,
        note: str = "",
    ) -> IncidentRecord:
        timestamp = utc_now_iso()
        incident_id = _new_incident_id()
        record = IncidentRecord(
            incident_id=incident_id,
            created_at=timestamp,
            last_updated_at=timestamp,
            severity=severity,
            status="open",
            summary=summary,
            owner=owner,
            environment=environment,
            release_name=release_name,
            source_report_path=source_report_path,
            events=[
                IncidentEvent(
                    timestamp=timestamp,
                    action="open",
                    actor=owner,
                    from_status="none",
                    to_status="open",
                    note=note,
                )
            ],
        )
        self.records.append(record)
        return record

    def transition_incident(
        self,
        incident_id: str,
        *,
        status: str,
        actor: str,
        note: str = "",
        owner: str | None = None,
        followup_eval_path: str | None = None,
    ) -> IncidentRecord:
        record = self.get(incident_id)
        _validate_incident_transition(record.status, status)
        next_followup_eval_path = followup_eval_path or record.followup_eval_path
        if status == "closed" and not next_followup_eval_path:
            raise ValueError("Cannot close incident without a linked follow-up eval artifact.")
        timestamp = utc_now_iso()
        previous_status = record.status
        record.status = status
        record.last_updated_at = timestamp
        if owner:
            record.owner = owner
        if followup_eval_path:
            _link_followup_eval(
                record,
                followup_eval_path=followup_eval_path,
                actor=actor,
                note="Follow-up eval linked during incident transition.",
                emit_event=True,
            )
        record.events.append(
            IncidentEvent(
                timestamp=timestamp,
                action=f"transition:{status}",
                actor=actor,
                from_status=previous_status,
                to_status=status,
                note=note,
            )
        )
        return record

    def link_followup_eval(
        self,
        incident_id: str,
        *,
        followup_eval_path: str,
        actor: str,
        note: str = "",
    ) -> IncidentRecord:
        record = self.get(incident_id)
        _link_followup_eval(
            record,
            followup_eval_path=followup_eval_path,
            actor=actor,
            note=note,
            emit_event=True,
        )
        return record

    def list_incidents(
        self,
        *,
        status: str | None = None,
        severity: str | None = None,
        limit: int,
    ) -> list[IncidentRecord]:
        rows = []
        for record in self.list_records():
            if status is not None and record.status != status:
                continue
            if severity is not None and record.severity != severity:
                continue
            rows.append(record)
        return rows[:limit]

    def incident_review_board(
        self,
        *,
        stale_minutes: int,
        status: str | None,
        limit: int,
    ) -> IncidentReviewBoard:
        rows: list[IncidentReviewBoardRow] = []
        for record in self.list_records():
            if status is not None and record.status != status:
                continue
            minutes_since_update = _minutes_since(record.last_updated_at)
            is_stale = stale_minutes >= 0 and record.status not in {"resolved", "closed"} and minutes_since_update >= stale_minutes
            rows.append(
                IncidentReviewBoardRow(
                    incident_id=record.incident_id,
                    severity=record.severity,
                    status=record.status,
                    risk_level=_incident_risk_level(record.severity, record.status, is_stale=is_stale),
                    owner=record.owner,
                    summary=record.summary,
                    environment=record.environment,
                    release_name=record.release_name,
                    followup_eval_path=record.followup_eval_path,
                    is_stale=is_stale,
                    minutes_since_update=minutes_since_update,
                    recommended_action=_incident_review_action(record.status, is_stale=is_stale, has_followup_eval=bool(record.followup_eval_path)),
                )
            )
        rows.sort(
            key=lambda row: (
                _incident_risk_rank(row.risk_level),
                _incident_status_rank(row.status),
                row.minutes_since_update,
                row.incident_id,
            ),
            reverse=True,
        )
        return IncidentReviewBoard(rows=rows[:limit])


@dataclass(slots=True)
class IncidentEvalSuggestion:
    task_id: str
    goal: str
    grader: dict
    metadata: dict
    source_run_id: str
    suggested_dataset: str
    template_notes: list[str]
    priority_score: int = 0
    priority_reasons: list[str] = field(default_factory=list)
    matched_feedback_count: int = 0

    def serialized_metadata(self) -> dict:
        return {
            **self.metadata,
            "priority_score": self.priority_score,
            "priority_reasons": self.priority_reasons,
            "matched_feedback_count": self.matched_feedback_count,
        }

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "goal": self.goal,
            "grader": self.grader,
            "metadata": self.serialized_metadata(),
            "source_run_id": self.source_run_id,
            "suggested_dataset": self.suggested_dataset,
            "template_notes": self.template_notes,
            "priority_score": self.priority_score,
            "priority_reasons": self.priority_reasons,
            "matched_feedback_count": self.matched_feedback_count,
        }

    def to_jsonl_line(self) -> str:
        payload = {
            "id": self.task_id,
            "goal": self.goal,
            "grader": self.grader,
            "metadata": self.serialized_metadata(),
        }
        return json.dumps(payload, ensure_ascii=True)


def _goal_for_failure(result) -> str:
    goal = result.metadata.get("task_goal") or result.metadata.get("goal")
    if goal:
        return str(goal)
    return f"follow up on failure type {result.failure_type or 'unknown'} from run {result.run_id}"


def _template_notes_for_failure(failure_type: str) -> list[str]:
    notes = [
        "Review the source trace before promoting this generated task into a permanent benchmark.",
        "Tighten the grader if the incident requires more than status and failure-type checks.",
    ]
    if failure_type.startswith("planner_"):
        notes.append("Prefer adding trace-shape or tool-argument validation checks for planner failures.")
    if failure_type == "safety_violation":
        notes.append("Consider whether this incident belongs in the safety suite or the approval simulation suite.")
    if failure_type in {"mcp_unavailable", "retrieval_miss"}:
        notes.append("Capture the expected retrieval path or note/tool usage in the grader.")
    return notes


def _normalize_optional_path(value: str | None) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return str(Path(value).expanduser().resolve())


def _base_priority_score(track: str, failure_type: str) -> tuple[int, list[str]]:
    score = TRACK_PRIORITY_WEIGHTS.get(track, TRACK_PRIORITY_WEIGHTS["incident-followup"])
    reasons = [f"base priority for {track} failures"]
    failure_bonus = FAILURE_PRIORITY_WEIGHTS.get(failure_type, 0)
    if failure_bonus:
        score += failure_bonus
        reasons.append(f"failure type '{failure_type}' raises urgency")
    return score, reasons


def _priority_label_matches(track: str, failure_type: str, labels: list[str]) -> list[str]:
    expected = set(LABEL_PRIORITY_HINTS.get(track, set()))
    if failure_type.startswith("planner_"):
        expected.add("planner")
    if failure_type.startswith("tool_"):
        expected.add("tool")
    if failure_type.startswith("approval_"):
        expected.add("approval")
    if failure_type.startswith("trace_"):
        expected.add("trace")
    if failure_type.startswith("skill_"):
        expected.add("skill")
    if failure_type.startswith("retrieval_") or failure_type.startswith("mcp_"):
        expected.add("retrieval")
    return sorted(label for label in labels if label in expected)


def _score_feedback_match(
    record: FeedbackRecord,
    *,
    run_id: str,
    track: str,
    failure_type: str,
    release_name: str | None,
    incident_id: str | None,
    report_path: str | None,
) -> tuple[bool, int, list[str]]:
    matched = False
    score = 0
    reasons: list[str] = []
    if run_id and record.run_id == run_id:
        matched = True
        score += 30
        reasons.append("direct human feedback matched this failed run")
    if incident_id and record.incident_id == incident_id:
        matched = True
        score += 20
        reasons.append("incident-linked human feedback matched this backfill context")
    if report_path and _normalize_optional_path(record.report_path) == report_path:
        matched = True
        score += 12
        reasons.append("report review feedback matched this candidate report")
    if release_name and record.release_name == release_name:
        matched = True
        score += 8
        reasons.append("release review feedback matched this rollout")
    if not matched:
        return False, 0, []

    sentiment_bonus = SENTIMENT_PRIORITY_BONUS.get(record.sentiment, 0)
    if sentiment_bonus:
        score += sentiment_bonus
        reasons.append(f"{record.sentiment} reviewer sentiment changed priority")

    actionability_bonus = ACTIONABILITY_PRIORITY_BONUS.get(record.actionability, 0)
    if actionability_bonus:
        score += actionability_bonus
        reasons.append(f"{record.actionability} feedback requires stronger follow-up")

    aligned_labels = _priority_label_matches(track, failure_type, record.labels)
    if aligned_labels:
        score += 6 * len(aligned_labels)
        reasons.append(f"feedback labels aligned with this failure: {', '.join(aligned_labels)}")
    return True, score, reasons


def suggest_incident_evals(
    report: HarnessReport,
    *,
    feedback_ledger_path: Path | None = None,
    release_name: str | None = None,
    incident_id: str | None = None,
    report_path: str | None = None,
) -> list[IncidentEvalSuggestion]:
    suggestions: list[IncidentEvalSuggestion] = []
    normalized_report_path = _normalize_optional_path(report_path)
    feedback_records = FeedbackLedger.load(feedback_ledger_path).records if feedback_ledger_path is not None else []
    for result in report.results:
        if result.success:
            continue
        failure_type = result.failure_type or "unspecified_failure"
        task_id = f"incident-{failure_type}-{result.task_id}"
        track = FAILURE_TO_TRACK.get(failure_type, "incident-followup")
        suggested_dataset = TRACK_TO_DATASET.get(track, "incident_backfill_tasks.jsonl")
        grader = {"type": "all", "checks": [{"type": "status", "equals": result.status}]}
        if result.failure_type:
            grader["checks"].append({"type": "failure_type", "equals": result.failure_type})
        priority_score, priority_reasons = _base_priority_score(track, failure_type)
        matched_feedback_count = 0
        for feedback_record in feedback_records:
            matched, feedback_score, feedback_reasons = _score_feedback_match(
                feedback_record,
                run_id=result.run_id,
                track=track,
                failure_type=failure_type,
                release_name=release_name,
                incident_id=incident_id,
                report_path=normalized_report_path,
            )
            if not matched:
                continue
            matched_feedback_count += 1
            priority_score += feedback_score
            priority_reasons.extend(feedback_reasons)
        suggestions.append(
            IncidentEvalSuggestion(
                task_id=task_id,
                goal=_goal_for_failure(result),
                grader=grader,
                metadata={
                    "track": track,
                    "source_task_id": result.task_id,
                    "source_run_id": result.run_id,
                    "incident_failure_type": failure_type,
                    "difficulty": result.metadata.get("difficulty", "unknown"),
                },
                source_run_id=result.run_id,
                suggested_dataset=suggested_dataset,
                template_notes=_template_notes_for_failure(failure_type),
                priority_score=priority_score,
                priority_reasons=list(dict.fromkeys(priority_reasons)),
                matched_feedback_count=matched_feedback_count,
            )
        )
    suggestions.sort(
        key=lambda suggestion: (
            -suggestion.priority_score,
            -suggestion.matched_feedback_count,
            suggestion.suggested_dataset,
            suggestion.task_id,
        )
    )
    return suggestions


def save_incident_suggestions(suggestions: list[IncidentEvalSuggestion], path: Path) -> Path:
    lines = [suggestion.to_jsonl_line() for suggestion in suggestions]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return path


def default_incident_ledger_path(incidents_dir: Path) -> Path:
    return incidents_dir / "incident-ledger.json"


def open_incident(
    *,
    severity: str,
    summary: str,
    owner: str,
    ledger_path: Path,
    environment: str | None = None,
    release_name: str | None = None,
    source_report_path: str | None = None,
    note: str = "",
) -> IncidentRecord:
    ledger = IncidentLedger.load(ledger_path)
    record = ledger.open_incident(
        severity=severity,
        summary=summary,
        owner=owner,
        environment=environment,
        release_name=release_name,
        source_report_path=source_report_path,
        note=note,
    )
    ledger.save(ledger_path)
    return record


def transition_incident(
    incident_id: str,
    *,
    status: str,
    actor: str,
    ledger_path: Path,
    note: str = "",
    owner: str | None = None,
    followup_eval_path: str | None = None,
) -> IncidentRecord:
    ledger = IncidentLedger.load(ledger_path)
    record = ledger.transition_incident(
        incident_id,
        status=status,
        actor=actor,
        note=note,
        owner=owner,
        followup_eval_path=followup_eval_path,
    )
    ledger.save(ledger_path)
    return record


def link_incident_followup_eval(
    incident_id: str,
    *,
    followup_eval_path: str,
    actor: str,
    ledger_path: Path,
    note: str = "",
) -> IncidentRecord:
    ledger = IncidentLedger.load(ledger_path)
    record = ledger.link_followup_eval(
        incident_id,
        followup_eval_path=followup_eval_path,
        actor=actor,
        note=note,
    )
    ledger.save(ledger_path)
    return record


def list_incidents(
    *,
    ledger_path: Path,
    status: str | None = None,
    severity: str | None = None,
    limit: int = 20,
) -> list[IncidentRecord]:
    ledger = IncidentLedger.load(ledger_path)
    return ledger.list_incidents(status=status, severity=severity, limit=limit)


def get_incident_record(incident_id: str, *, ledger_path: Path) -> IncidentRecord:
    ledger = IncidentLedger.load(ledger_path)
    return ledger.get(incident_id)


def get_incident_review_board(
    *,
    ledger_path: Path,
    stale_minutes: int = 120,
    status: str | None = None,
    limit: int = 20,
) -> IncidentReviewBoard:
    ledger = IncidentLedger.load(ledger_path)
    return ledger.incident_review_board(
        stale_minutes=stale_minutes,
        status=status,
        limit=limit,
    )


def _new_incident_id() -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    return f"incident-{timestamp}-{uuid4().hex[:6]}"


def _parse_timestamp(timestamp: str) -> datetime:
    observed = datetime.fromisoformat(timestamp)
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=UTC)
    return observed


def _minutes_since(timestamp: str) -> int:
    delta = datetime.now(UTC) - _parse_timestamp(timestamp)
    return int(delta.total_seconds() // 60)


def _incident_status_rank(status: str) -> int:
    return {
        "open": 4,
        "acknowledged": 3,
        "contained": 2,
        "resolved": 1,
        "closed": 0,
    }.get(status, -1)


def _incident_risk_rank(level: str) -> int:
    return {"high": 2, "medium": 1, "low": 0}.get(level, -1)


def _incident_risk_level(severity: str, status: str, *, is_stale: bool) -> str:
    if status in {"closed"}:
        return "low"
    if severity == "critical" or is_stale:
        return "high"
    if severity == "high":
        return "high"
    if status in {"open", "acknowledged", "contained"}:
        return "medium"
    return "low"


def _link_followup_eval(
    record: IncidentRecord,
    *,
    followup_eval_path: str,
    actor: str,
    note: str,
    emit_event: bool,
) -> None:
    if not followup_eval_path.strip():
        raise ValueError("followup_eval_path must not be empty.")
    timestamp = utc_now_iso()
    record.followup_eval_path = followup_eval_path
    record.followup_eval_linked_at = timestamp
    record.followup_eval_linked_by = actor
    record.last_updated_at = timestamp
    if emit_event:
        record.events.append(
            IncidentEvent(
                timestamp=timestamp,
                action="link_followup_eval",
                actor=actor,
                from_status=record.status,
                to_status=record.status,
                note=note or f"Linked follow-up eval artifact: {followup_eval_path}",
            )
        )


def _incident_review_action(status: str, *, is_stale: bool, has_followup_eval: bool) -> str:
    if is_stale:
        return "escalate_incident_owner"
    if status == "open":
        return "acknowledge_incident"
    if status == "acknowledged":
        return "contain_incident"
    if status == "contained":
        return "resolve_incident" if has_followup_eval else "add_followup_eval"
    if status == "resolved":
        return "close_incident"
    return "observe_incident"


def _validate_incident_transition(current_status: str, next_status: str) -> None:
    allowed = {
        "open": {"acknowledged", "contained", "resolved"},
        "acknowledged": {"contained", "resolved"},
        "contained": {"resolved"},
        "resolved": {"closed"},
        "closed": set(),
    }
    if next_status == current_status:
        return
    if next_status not in allowed.get(current_status, set()):
        raise ValueError(f"Cannot transition incident from '{current_status}' to '{next_status}'.")
