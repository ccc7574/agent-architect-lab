# Ops And Incidents

An AI architect should be able to explain how the platform behaves when it is wrong, slow, or unsafe.

## Operator Workflow Minimum Bar

- dashboards show failures by type and track
- traces and checkpoints are enough to reconstruct a bad run
- release manifests preserve what was reviewed before approval
- a release ledger records who approved or promoted a candidate
- an incident ledger records owner, severity, status transitions, and linked releases
- risky changes can be rolled back quickly
- incident review produces concrete eval or policy updates

## Incident Loop

1. Detect
- alerts, traces, release-gate failures, user reports

2. Triage
- identify failure taxonomy
- estimate blast radius
- assign an owner

3. Contain
- roll back or block the unsafe path
- preserve artifacts for review
- update the incident record with containment status and owner changes

4. Learn
- add a new eval or tighten a gate
- update routing or policy logic
- attach the follow-up eval artifact to the incident before closure

## Why This Matters

Top AI companies increasingly expect architects to design the improvement loop, not just the happy-path runtime.
