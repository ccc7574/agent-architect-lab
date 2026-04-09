# Release Ledger

Production release systems need two different artifact types:

- an immutable snapshot of what was reviewed
- a mutable operator ledger that tracks approval and rollout state

This lab now models both.

## Files

Under `artifacts/releases`:

- `manifests/{release_name}.json`: immutable release snapshot
- `release-ledger.json`: mutable release state and event history

## State Model

The release ledger currently uses these states:

- `blocked`: review had blockers and cannot be approved
- `pending_approval`: review passed gates and now waits for human sign-off
- `approved`: an operator approved the release
- `promoted`: an operator marked the approved release as promoted
- `rejected`: a reviewer explicitly rejected the release

## Commands

Create a release record while running multi-suite shadow review:

```bash
PYTHONPATH=src python3 -m agent_architect_lab.cli run-release-shadow \
  --suites safety retrieval \
  --report-prefix release-candidate \
  --suite-aware-defaults \
  --release-name 2026-04-10-main
```

Approve and promote it:

```bash
PYTHONPATH=src python3 -m agent_architect_lab.cli approve-release \
  2026-04-10-main \
  --by qa-owner \
  --note "gate review complete"

PYTHONPATH=src python3 -m agent_architect_lab.cli promote-release \
  2026-04-10-main \
  --by release-manager \
  --note "production rollout started"
```

Inspect current state and event history:

```bash
PYTHONPATH=src python3 -m agent_architect_lab.cli release-status 2026-04-10-main
```

## Why This Matters

Without this split, teams often lose the distinction between:

- the benchmark evidence that justified a release
- and the human decisions that changed rollout state later

Strong agent architecture requires both.
