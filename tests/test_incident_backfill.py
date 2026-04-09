from __future__ import annotations

from pathlib import Path

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
