from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from agent_architect_lab.models import utc_now_iso


FEEDBACK_LEDGER_FILE_NAME = "feedback-ledger.json"


@dataclass(slots=True)
class FeedbackRecord:
    feedback_id: str
    created_at: str
    actor: str
    role: str
    sentiment: str
    actionability: str
    target_kind: str
    summary: str
    release_name: str | None = None
    incident_id: str | None = None
    report_path: str | None = None
    run_id: str | None = None
    artifact_path: str | None = None
    labels: list[str] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "feedback_id": self.feedback_id,
            "created_at": self.created_at,
            "actor": self.actor,
            "role": self.role,
            "sentiment": self.sentiment,
            "actionability": self.actionability,
            "target_kind": self.target_kind,
            "summary": self.summary,
            "release_name": self.release_name,
            "incident_id": self.incident_id,
            "report_path": self.report_path,
            "run_id": self.run_id,
            "artifact_path": self.artifact_path,
            "labels": self.labels,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "FeedbackRecord":
        return cls(
            feedback_id=str(payload["feedback_id"]),
            created_at=str(payload["created_at"]),
            actor=str(payload["actor"]),
            role=str(payload["role"]),
            sentiment=str(payload["sentiment"]),
            actionability=str(payload["actionability"]),
            target_kind=str(payload["target_kind"]),
            summary=str(payload["summary"]),
            release_name=payload.get("release_name"),
            incident_id=payload.get("incident_id"),
            report_path=payload.get("report_path"),
            run_id=payload.get("run_id"),
            artifact_path=payload.get("artifact_path"),
            labels=[str(item) for item in payload.get("labels", []) if str(item).strip()],
            notes=str(payload.get("notes", "")),
        )


@dataclass(slots=True)
class FeedbackLedger:
    records: list[FeedbackRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"records": [record.to_dict() for record in self.records]}

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "FeedbackLedger":
        if not path.exists():
            return cls()
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(records=[FeedbackRecord.from_dict(item) for item in payload.get("records", [])])

    def add(
        self,
        *,
        actor: str,
        role: str,
        sentiment: str,
        actionability: str,
        target_kind: str,
        summary: str,
        release_name: str | None = None,
        incident_id: str | None = None,
        report_path: str | None = None,
        run_id: str | None = None,
        artifact_path: str | None = None,
        labels: list[str] | None = None,
        notes: str = "",
    ) -> FeedbackRecord:
        record = FeedbackRecord(
            feedback_id=f"feedback-{uuid4().hex[:10]}",
            created_at=utc_now_iso(),
            actor=actor,
            role=role,
            sentiment=_normalize_sentiment(sentiment),
            actionability=_normalize_actionability(actionability),
            target_kind=_normalize_target_kind(target_kind),
            summary=summary.strip(),
            release_name=release_name.strip() if isinstance(release_name, str) and release_name.strip() else None,
            incident_id=incident_id.strip() if isinstance(incident_id, str) and incident_id.strip() else None,
            report_path=report_path.strip() if isinstance(report_path, str) and report_path.strip() else None,
            run_id=run_id.strip() if isinstance(run_id, str) and run_id.strip() else None,
            artifact_path=artifact_path.strip() if isinstance(artifact_path, str) and artifact_path.strip() else None,
            labels=_normalize_labels(labels or []),
            notes=notes.strip(),
        )
        if not record.summary:
            raise ValueError("summary must not be empty.")
        self.records.append(record)
        self.records.sort(key=lambda item: (item.created_at, item.feedback_id), reverse=True)
        return record

    def list_records(
        self,
        *,
        target_kind: str | None = None,
        release_name: str | None = None,
        incident_id: str | None = None,
        run_id: str | None = None,
        sentiment: str | None = None,
        actionability: str | None = None,
        limit: int = 20,
    ) -> list[FeedbackRecord]:
        rows: list[FeedbackRecord] = []
        for record in self.records:
            if target_kind is not None and record.target_kind != target_kind:
                continue
            if release_name is not None and record.release_name != release_name:
                continue
            if incident_id is not None and record.incident_id != incident_id:
                continue
            if run_id is not None and record.run_id != run_id:
                continue
            if sentiment is not None and record.sentiment != sentiment:
                continue
            if actionability is not None and record.actionability != actionability:
                continue
            rows.append(record)
        return rows[:limit]


def default_feedback_ledger_path(feedback_dir: Path) -> Path:
    return feedback_dir / FEEDBACK_LEDGER_FILE_NAME


def record_feedback(
    *,
    actor: str,
    role: str,
    sentiment: str,
    actionability: str,
    target_kind: str,
    summary: str,
    ledger_path: Path,
    release_name: str | None = None,
    incident_id: str | None = None,
    report_path: str | None = None,
    run_id: str | None = None,
    artifact_path: str | None = None,
    labels: list[str] | None = None,
    notes: str = "",
) -> FeedbackRecord:
    ledger = FeedbackLedger.load(ledger_path)
    record = ledger.add(
        actor=actor,
        role=role,
        sentiment=sentiment,
        actionability=actionability,
        target_kind=target_kind,
        summary=summary,
        release_name=release_name,
        incident_id=incident_id,
        report_path=report_path,
        run_id=run_id,
        artifact_path=artifact_path,
        labels=labels,
        notes=notes,
    )
    ledger.save(ledger_path)
    return record


def list_feedback(
    *,
    ledger_path: Path,
    target_kind: str | None = None,
    release_name: str | None = None,
    incident_id: str | None = None,
    run_id: str | None = None,
    sentiment: str | None = None,
    actionability: str | None = None,
    limit: int = 20,
) -> list[FeedbackRecord]:
    ledger = FeedbackLedger.load(ledger_path)
    return ledger.list_records(
        target_kind=target_kind.strip() if isinstance(target_kind, str) and target_kind.strip() else None,
        release_name=release_name.strip() if isinstance(release_name, str) and release_name.strip() else None,
        incident_id=incident_id.strip() if isinstance(incident_id, str) and incident_id.strip() else None,
        run_id=run_id.strip() if isinstance(run_id, str) and run_id.strip() else None,
        sentiment=sentiment.strip() if isinstance(sentiment, str) and sentiment.strip() else None,
        actionability=actionability.strip() if isinstance(actionability, str) and actionability.strip() else None,
        limit=limit,
    )


def build_feedback_summary(
    *,
    ledger_path: Path,
    target_kind: str | None = None,
    release_name: str | None = None,
    incident_id: str | None = None,
    run_id: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    ledger = FeedbackLedger.load(ledger_path)
    filtered = ledger.list_records(
        target_kind=target_kind.strip() if isinstance(target_kind, str) and target_kind.strip() else None,
        release_name=release_name.strip() if isinstance(release_name, str) and release_name.strip() else None,
        incident_id=incident_id.strip() if isinstance(incident_id, str) and incident_id.strip() else None,
        run_id=run_id.strip() if isinstance(run_id, str) and run_id.strip() else None,
        limit=max(limit, len(ledger.records)),
    )
    sentiment_counts = Counter(record.sentiment for record in filtered)
    actionability_counts = Counter(record.actionability for record in filtered)
    target_kind_counts = Counter(record.target_kind for record in filtered)
    label_counts = Counter(label for record in filtered for label in record.labels)
    recent = [record.to_dict() for record in filtered[:limit]]
    return {
        "generated_at": utc_now_iso(),
        "filters": {
            "target_kind": target_kind or None,
            "release_name": release_name or None,
            "incident_id": incident_id or None,
            "run_id": run_id or None,
        },
        "metrics": {
            "total_feedback_count": len(filtered),
            "negative_feedback_count": sentiment_counts.get("negative", 0),
            "positive_feedback_count": sentiment_counts.get("positive", 0),
            "urgent_feedback_count": actionability_counts.get("urgent_followup", 0),
            "followup_feedback_count": actionability_counts.get("followup_required", 0),
        },
        "counts_by_sentiment": dict(sorted(sentiment_counts.items())),
        "counts_by_actionability": dict(sorted(actionability_counts.items())),
        "counts_by_target_kind": dict(sorted(target_kind_counts.items())),
        "top_labels": [
            {"label": label, "count": count}
            for label, count in sorted(label_counts.items(), key=lambda item: (-item[1], item[0]))[:10]
        ],
        "recent_feedback": recent,
    }


def build_related_feedback(
    *,
    ledger_path: Path,
    release_name: str | None = None,
    incident_ids: list[str] | None = None,
    run_ids: list[str] | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    incident_set = {item for item in (incident_ids or []) if item}
    run_set = {item for item in (run_ids or []) if item}
    ledger = FeedbackLedger.load(ledger_path)
    rows: list[FeedbackRecord] = []
    for record in ledger.records:
        if release_name and record.release_name == release_name:
            rows.append(record)
            continue
        if incident_set and record.incident_id in incident_set:
            rows.append(record)
            continue
        if run_set and record.run_id in run_set:
            rows.append(record)
            continue
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in rows:
        if record.feedback_id in seen:
            continue
        seen.add(record.feedback_id)
        deduped.append(record.to_dict())
        if len(deduped) >= limit:
            break
    return deduped


def _normalize_sentiment(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in {"positive", "neutral", "negative"}:
        raise ValueError("sentiment must be one of: positive, neutral, negative.")
    return normalized


def _normalize_actionability(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in {"observe", "followup_required", "urgent_followup"}:
        raise ValueError("actionability must be one of: observe, followup_required, urgent_followup.")
    return normalized


def _normalize_target_kind(value: str) -> str:
    normalized = value.strip().lower()
    if not normalized:
        raise ValueError("target_kind must not be empty.")
    return normalized


def _normalize_labels(values: list[str]) -> list[str]:
    return list(dict.fromkeys(item.strip().lower() for item in values if item.strip()))
