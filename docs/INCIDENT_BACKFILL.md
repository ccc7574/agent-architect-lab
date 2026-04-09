# Incident Backfill

One sign of a mature agent platform is that incidents do not end as chat messages and memory.

They end as:

- tighter safeguards
- better dashboards
- and new eval tasks

## This Repository's Backfill Flow

1. Run a suite and save a report.
2. Inspect failed results.
3. Generate candidate follow-up tasks with `suggest-incident-evals`.
4. Review and refine the generated JSONL entries.
5. Add the approved tasks to the right dataset slice.

The generator now also recommends a target dataset file such as:

- `planner_reliability_tasks.jsonl`
- `safety_tasks.jsonl`
- `retrieval_tasks.jsonl`
- `incident_backfill_tasks.jsonl`

## Why This Matters

Without incident backfill, the same class of failure can recur indefinitely while teams tell themselves they "already fixed it."

## Current Constraint

The backfill flow generates candidate tasks and graders, but it does not automatically merge them into a dataset. Human review stays in the loop.
