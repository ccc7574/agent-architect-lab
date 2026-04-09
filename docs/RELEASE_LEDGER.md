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

## Deployment Policy

The ledger also tracks environment rollout lineage:

- a release must be `approved` before deployment
- `production` deployment requires the same release to be active in `staging`
- deploying a new release into an environment supersedes the previous active release
- rolling back the active release reactivates the superseded release when lineage is available

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

Deploy and roll back environments:

```bash
PYTHONPATH=src python3 -m agent_architect_lab.cli deploy-release \
  2026-04-10-main \
  --environment staging \
  --by release-manager \
  --note "staging rollout"

PYTHONPATH=src python3 -m agent_architect_lab.cli deploy-release \
  2026-04-10-main \
  --environment production \
  --by release-manager \
  --note "production rollout"

PYTHONPATH=src python3 -m agent_architect_lab.cli rollback-release \
  2026-04-10-main \
  --environment production \
  --by release-manager \
  --note "rollback due to incident"
```

Inspect current state and event history:

```bash
PYTHONPATH=src python3 -m agent_architect_lab.cli release-status 2026-04-10-main
```

## Why This Matters

Without this split, teams often lose the distinction between:

- the benchmark evidence that justified a release
- and the human decisions that changed rollout state later
- and which release actually held each environment before and after a rollback

Strong agent architecture requires both.
