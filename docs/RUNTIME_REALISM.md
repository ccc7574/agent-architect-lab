# Runtime Realism

This repository now has a concrete runtime-realism layer beyond static provider scaffolding.

## Planner Shadow Validation

Use `run-planner-shadow` when you want to evaluate a planner's first-step decision before trusting it in promotion or rollout workflows.

```bash
AGENT_ARCHITECT_LAB_PLANNER_PROVIDER=openai_compatible \
PYTHONPATH=src python3 -m agent_architect_lab.cli run-planner-shadow \
  --suite planner_shadow \
  --report-name planner-shadow-report.json \
  --markdown-output ./planner-shadow.md
```

What it checks:

- task-level allowed and blocked tools
- expected action types such as `tool` versus `answer`
- heuristic-versus-candidate first-step drift
- approval-style answers for high-risk destructive requests

The default `planner_shadow` suite keeps the scope intentionally narrow. It is meant to create a reviewable shadow artifact before rollout, not to replace full regression suites.

## Bounded Role Orchestration

Use `export-release-command-brief` when you want a production-shaped example of bounded multi-role handoff grounded in release state.

```bash
PYTHONPATH=src python3 -m agent_architect_lab.cli export-release-command-brief release-a \
  --title "Release Command Brief"
```

What it does:

- builds fixed role packets for `qa-owner`, `ops-oncall`, `incident-commander`, and `release-manager`
- keeps role ownership explicit instead of giving every role full context
- turns release blockers, overrides, incidents, and rollout readiness into one readable artifact
- produces a deterministic final recommendation such as `promote`, `promote_with_review`, or `hold_release`

This is not a distributed worker plane yet, but it does model the ownership boundaries used in real release command systems.

## Why This Matters

Senior AI architects are expected to do more than connect a model to a runtime.

They also need to show they can:

- validate model-backed planner behavior before rollout
- define tool and approval policy boundaries
- compare candidate planner behavior against a stable baseline
- encode explicit ownership across QA, ops, incident command, and release management
- produce artifacts that help humans make promotion decisions quickly
