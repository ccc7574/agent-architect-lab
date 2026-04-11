# Human Feedback

`agent-architect-lab` now treats explicit human review as a first-class governance artifact instead of leaving it only in ad hoc notes or approval comments.

## What It Covers

- release review feedback
- incident follow-up feedback
- report and artifact review feedback
- run-level feedback tied to a specific `run_id`

Feedback is stored under `artifacts/feedback/feedback-ledger.json`.

## CLI

Record feedback:

```bash
PYTHONPATH=src python3 -m agent_architect_lab.cli record-feedback \
  --summary "release still needs rollback proof" \
  --actor release-manager-1 \
  --role release-manager \
  --sentiment negative \
  --actionability followup_required \
  --target-kind release \
  --release-name 2026-04-10-main \
  --label rollback \
  --label review
```

List feedback:

```bash
PYTHONPATH=src python3 -m agent_architect_lab.cli list-feedback --release-name 2026-04-10-main --limit 20
```

Summarize feedback:

```bash
PYTHONPATH=src python3 -m agent_architect_lab.cli feedback-summary --release-name 2026-04-10-main
```

Feedback also now feeds back into incident backfill ranking:

```bash
PYTHONPATH=src python3 -m agent_architect_lab.cli suggest-incident-evals \
  artifacts/reports/candidate.json
```

`suggest-incident-evals` and `rollout-review` now raise priority for failed runs that match negative, urgent, or label-aligned human feedback.

## Control Plane

Read routes:

- `GET /feedback?release_name=...&incident_id=...&target_kind=...&limit=20`
- `GET /feedback-summary?release_name=...&incident_id=...&target_kind=...&limit=20`

Write route:

- `POST /feedback`

Example:

```bash
curl \
  -X POST \
  -H "Authorization: Bearer writer-token" \
  -H "X-Control-Plane-Actor: release-manager-1" \
  -H "X-Control-Plane-Role: release-manager" \
  -H "Idempotency-Key: feedback-001" \
  -H "Content-Type: application/json" \
  http://127.0.0.1:8080/feedback \
  -d '{
    "actor": "release-manager-1",
    "role": "release-manager",
    "sentiment": "negative",
    "actionability": "followup_required",
    "target_kind": "release",
    "summary": "release still needs rollback proof",
    "release_name": "2026-04-10-main",
    "labels": ["rollback", "review"]
  }'
```

## Why It Matters

The repo already tracked approvals, incidents, run traces, and release artifacts. Feedback closes a different gap:

- what a human reviewer actually thought
- whether the feedback was positive, neutral, or negative
- whether the note requires follow-up
- which release, incident, report, run, or artifact triggered the feedback

That lets governance summary, weekly status, release runbooks, release command briefs, and incident bundles carry explicit human signals instead of only system-generated state.
It also means the incident backfill queue is no longer ranked only by failure type; explicit reviewer pressure now pushes the most urgent eval gaps to the top.
