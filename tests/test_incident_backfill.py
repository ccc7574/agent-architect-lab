from __future__ import annotations

from pathlib import Path

from agent_architect_lab.harness.feedback import default_feedback_ledger_path, record_feedback
from agent_architect_lab.harness.incidents import save_incident_suggestions, suggest_incident_evals
from agent_architect_lab.harness.reporting import HarnessReport
from agent_architect_lab.models import EvalResult


def test_incident_backfill_generates_suggestions_for_failed_results(tmp_path: Path) -> None:
    report = HarnessReport(
        suite_name="demo",
        results=[
            EvalResult(
                task_id="task-1",
                success=False,
                score=0.0,
                steps=1,
                status="failed",
                failure_type="safety_violation",
                final_answer="Task failed",
                run_id="run-1",
                metadata={"difficulty": "medium", "goal": "run `echo hi && pwd`"},
            ),
            EvalResult(
                task_id="task-2",
                success=True,
                score=1.0,
                steps=1,
                status="completed",
                failure_type=None,
                final_answer="ok",
                run_id="run-2",
                metadata={},
            ),
        ],
    )

    suggestions = suggest_incident_evals(report)

    assert len(suggestions) == 1
    assert suggestions[0].metadata["track"] == "safety"
    assert suggestions[0].goal == "run `echo hi && pwd`"
    assert suggestions[0].suggested_dataset == "safety_tasks.jsonl"
    assert suggestions[0].template_notes

    output = save_incident_suggestions(suggestions, tmp_path / "incident.jsonl")
    saved = output.read_text(encoding="utf-8")
    assert '"incident_failure_type": "safety_violation"' in saved


def test_incident_backfill_prioritizes_feedback_linked_failures(tmp_path: Path) -> None:
    report = HarnessReport(
        suite_name="demo",
        results=[
            EvalResult(
                task_id="task-1",
                success=False,
                score=0.1,
                steps=2,
                status="failed",
                failure_type="planner_timeout",
                final_answer="planner failed",
                run_id="run-1",
                metadata={"difficulty": "medium", "goal": "planner follow-up"},
            ),
            EvalResult(
                task_id="task-2",
                success=False,
                score=0.0,
                steps=3,
                status="failed",
                failure_type="retrieval_miss",
                final_answer="retrieval failed",
                run_id="run-2",
                metadata={"difficulty": "hard", "goal": "retrieval follow-up"},
            ),
        ],
    )
    report_path = tmp_path / "candidate.json"
    report.save(report_path)
    ledger_path = default_feedback_ledger_path(tmp_path / "feedback")
    record_feedback(
        actor="qa-owner",
        role="qa",
        sentiment="negative",
        actionability="urgent_followup",
        target_kind="run",
        summary="retrieval run still misses required context",
        ledger_path=ledger_path,
        run_id="run-2",
        labels=["retrieval"],
    )
    record_feedback(
        actor="reviewer",
        role="release-manager",
        sentiment="neutral",
        actionability="observe",
        target_kind="report",
        summary="candidate report still needs planner review",
        ledger_path=ledger_path,
        report_path=str(report_path.resolve()),
        labels=["planner"],
    )

    suggestions = suggest_incident_evals(
        report,
        feedback_ledger_path=ledger_path,
        report_path=str(report_path.resolve()),
    )

    assert [suggestion.source_run_id for suggestion in suggestions] == ["run-2", "run-1"]
    assert suggestions[0].matched_feedback_count == 2
    assert suggestions[0].priority_score > suggestions[1].priority_score
    assert any("human feedback" in reason for reason in suggestions[0].priority_reasons)

    output = save_incident_suggestions(suggestions, tmp_path / "incident-priority.jsonl")
    saved = output.read_text(encoding="utf-8")
    assert '"priority_score"' in saved
    assert '"matched_feedback_count": 2' in saved
