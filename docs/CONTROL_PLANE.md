# Control Plane

`agent-architect-lab` now exposes a lightweight internal HTTP control plane on top of the existing release and incident ledgers.

## Why It Exists

- Keep the governance model reusable outside the CLI
- Give dashboards and simple automation a stable read surface
- Separate read-only views from state-changing actions

## Start The Server

```bash
cd /Volumes/ExtaData/newcode/agent-architect-lab
export AGENT_ARCHITECT_LAB_CONTROL_PLANE_READ_TOKEN=reader-token
export AGENT_ARCHITECT_LAB_CONTROL_PLANE_MUTATION_TOKEN=writer-token
PYTHONPATH=src python3 -m agent_architect_lab.cli run-control-plane-server --host 127.0.0.1 --port 8080
```

The server is stdlib-only and keeps artifact storage exactly where the CLI keeps it.

## Authentication

- `GET /health` is public
- Read routes accept `Authorization: Bearer <read-token>`
- Read routes also accept the mutation token
- Mutation routes require `Authorization: Bearer <mutation-token>`
- If `AGENT_ARCHITECT_LAB_CONTROL_PLANE_MUTATION_TOKEN` is unset, mutation routes return `503`

## Routes

### Read Routes

- `GET /health`
- `GET /release-risk-board?environment=staging&environment=production&limit=20`
- `GET /approval-review-board?environment=staging&environment=production&limit=20`
- `GET /incident-review-board?status=open&limit=20`
- `GET /governance-summary?environment=production&release_limit=20&incident_limit=20&override_limit=50`

### Mutation Routes

- `POST /incidents/open`
- `POST /incidents/{incident_id}/transition`

## Example Requests

Read governance summary:

```bash
curl \
  -H "Authorization: Bearer reader-token" \
  http://127.0.0.1:8080/governance-summary
```

Open an incident:

```bash
curl \
  -X POST \
  -H "Authorization: Bearer writer-token" \
  -H "Content-Type: application/json" \
  http://127.0.0.1:8080/incidents/open \
  -d '{
    "severity": "critical",
    "summary": "unsafe production answer",
    "owner": "incident-commander",
    "environment": "production",
    "release_name": "2026-04-10-main",
    "source_report_path": "/tmp/report.json",
    "note": "customer escalation"
  }'
```

Transition an incident:

```bash
curl \
  -X POST \
  -H "Authorization: Bearer writer-token" \
  -H "Content-Type: application/json" \
  http://127.0.0.1:8080/incidents/incident-20260410abcd1234/transition \
  -d '{
    "status": "acknowledged",
    "by": "incident-commander",
    "note": "triage started",
    "owner": "ops-owner"
  }'
```

## Current Boundary

This control plane is intentionally narrow:

- read models are optimized for governance and review flows
- write models currently cover incident creation and incident transition
- storage is still local artifact-backed JSON, not an external database
- access control is token-based, not yet role-aware policy enforcement

That makes it suitable for local production-style drills and internal tooling, while keeping the repo dependency-light and testable.
