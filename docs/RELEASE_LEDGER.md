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
- deployment is blocked when the target environment is inside a configured freeze window
- `production` deployment requires the same release to be active in `staging`
- `production` deployment also requires the `staging` rollout to satisfy the configured soak time
- `production` deployment also requires all configured approver roles to have signed off
- deploying a new release into an environment supersedes the previous active release
- rolling back the active release reactivates the superseded release when lineage is available

The soak threshold is controlled by `AGENT_ARCHITECT_LAB_PRODUCTION_SOAK_MINUTES` and defaults to `30`.
Required production sign-off roles are controlled by `AGENT_ARCHITECT_LAB_PRODUCTION_REQUIRED_APPROVER_ROLES` and default to `qa-owner,release-manager`.
Freeze windows are controlled by `AGENT_ARCHITECT_LAB_ENVIRONMENT_FREEZE_WINDOWS`, which accepts a JSON object keyed by environment name:

```json
{
  "staging": ["00:00-06:00"],
  "production": ["22:00-23:59", "00:00-01:00"]
}
```

When a deploy readiness check lands inside one of these windows, the result includes the `environment_frozen` blocker plus the matched `active_freeze_window`.

More advanced environment chains can be declared with `AGENT_ARCHITECT_LAB_ENVIRONMENT_POLICIES`. This extends the default `staging -> production` model into arbitrary environment graphs:

```json
{
  "canary": {
    "required_predecessor_environment": "staging",
    "required_approver_roles": ["qa-owner"],
    "soak_minutes_required": 5
  },
  "production": {
    "required_predecessor_environment": "canary",
    "required_approver_roles": ["ops-oncall"],
    "soak_minutes_required": 30,
    "freeze_windows": ["22:00-23:59", "00:00-01:00"]
  }
}
```

When configured, `deploy-policy`, `check-deploy-readiness`, and `rollout-matrix` all resolve policy from this environment-specific model instead of relying only on the built-in production defaults.

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
  --role qa-owner \
  --note "gate review complete"

PYTHONPATH=src python3 -m agent_architect_lab.cli approve-release \
  2026-04-10-main \
  --by release-manager \
  --role release-manager \
  --note "ops sign-off complete"

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

Check deploy readiness before attempting a production push:

```bash
PYTHONPATH=src python3 -m agent_architect_lab.cli check-deploy-readiness \
  2026-04-10-main \
  --environment production
```

Inspect the active deployment policy for an environment:

```bash
PYTHONPATH=src python3 -m agent_architect_lab.cli deploy-policy --environment production
```

Inspect a full rollout matrix across the configured environment set:

```bash
PYTHONPATH=src python3 -m agent_architect_lab.cli rollout-matrix 2026-04-10-main
```

Inspect an oncall-oriented readiness digest for a release:

```bash
PYTHONPATH=src python3 -m agent_architect_lab.cli release-readiness-digest 2026-04-10-main
```

Inspect a ranked risk board across recorded releases:

```bash
PYTHONPATH=src python3 -m agent_architect_lab.cli release-risk-board
```

Inspect approval backlog and stale approval queues:

```bash
PYTHONPATH=src python3 -m agent_architect_lab.cli approval-review-board
```

Inspect override cleanup priority across releases:

```bash
PYTHONPATH=src python3 -m agent_architect_lab.cli override-review-board
```

Revoke an override while preserving audit history:

```bash
PYTHONPATH=src python3 -m agent_architect_lab.cli revoke-release-override \
  2026-04-10-main \
  --environment production \
  --blocker environment_frozen \
  --by release-manager \
  --note "incident closed"
```

Generate a combined operator handoff snapshot:

```bash
PYTHONPATH=src python3 -m agent_architect_lab.cli operator-handoff
```

Persist an operator handoff snapshot to artifacts:

```bash
PYTHONPATH=src python3 -m agent_architect_lab.cli record-operator-handoff --label night-shift
```

List recent operator handoff snapshots:

```bash
PYTHONPATH=src python3 -m agent_architect_lab.cli list-operator-handoffs --limit 10
```

Load the latest saved handoff snapshot:

```bash
PYTHONPATH=src python3 -m agent_architect_lab.cli show-operator-handoff --latest
```

Render the latest handoff snapshot as a Markdown report:

```bash
PYTHONPATH=src python3 -m agent_architect_lab.cli export-operator-handoff-report --latest --title "Night Shift Release Report"
```

Grant a temporary override for a specific blocker:

```bash
PYTHONPATH=src python3 -m agent_architect_lab.cli grant-release-override \
  2026-04-10-main \
  --environment production \
  --blocker environment_frozen \
  --by incident-commander \
  --note "emergency hotfix waiver"
```

Audit currently active overrides:

```bash
PYTHONPATH=src python3 -m agent_architect_lab.cli list-active-overrides --environment production
```

Inspect current state and event history:

```bash
PYTHONPATH=src python3 -m agent_architect_lab.cli release-status 2026-04-10-main
```

Operator-oriented summary commands:

```bash
PYTHONPATH=src python3 -m agent_architect_lab.cli list-releases
PYTHONPATH=src python3 -m agent_architect_lab.cli rollout-matrix 2026-04-10-main
PYTHONPATH=src python3 -m agent_architect_lab.cli release-readiness-digest 2026-04-10-main
PYTHONPATH=src python3 -m agent_architect_lab.cli release-risk-board
PYTHONPATH=src python3 -m agent_architect_lab.cli approval-review-board
PYTHONPATH=src python3 -m agent_architect_lab.cli list-active-overrides --environment production
PYTHONPATH=src python3 -m agent_architect_lab.cli override-review-board
PYTHONPATH=src python3 -m agent_architect_lab.cli revoke-release-override 2026-04-10-main --environment production --blocker environment_frozen --by release-manager
PYTHONPATH=src python3 -m agent_architect_lab.cli operator-handoff
PYTHONPATH=src python3 -m agent_architect_lab.cli record-operator-handoff --label night-shift
PYTHONPATH=src python3 -m agent_architect_lab.cli list-operator-handoffs --limit 10
PYTHONPATH=src python3 -m agent_architect_lab.cli show-operator-handoff --latest
PYTHONPATH=src python3 -m agent_architect_lab.cli export-operator-handoff-report --latest --title "Night Shift Release Report"
PYTHONPATH=src python3 -m agent_architect_lab.cli deploy-policy --environment staging
PYTHONPATH=src python3 -m agent_architect_lab.cli environment-history --environment staging
PYTHONPATH=src python3 -m agent_architect_lab.cli environment-status --environment staging
PYTHONPATH=src python3 -m agent_architect_lab.cli environment-status --environment production
```

The default environment list used by `rollout-matrix` comes from `AGENT_ARCHITECT_LAB_ENVIRONMENTS` and defaults to `staging,production`.
When a release name is supplied, each matrix row also includes a `recommended_action` such as `deploy`, `collect_required_approvals`, `wait_for_staging_soak`, or `wait_for_freeze_window`.
Overrides are scoped to one release, one environment, and one exact blocker string. They are intended for time-bounded emergency waivers, not as a replacement for normal approval flow.
`list-active-overrides` only returns overrides whose expiry has not passed yet.
`release-readiness-digest` uses `AGENT_ARCHITECT_LAB_OVERRIDE_EXPIRING_SOON_MINUTES` to decide which overrides should be flagged as expiring soon. The default threshold is `120` minutes.
`release-risk-board` ranks releases by unresolved environment blockers, expiring overrides, active override footprint, and stale update age so operators can focus on the riskiest release first.
Set `AGENT_ARCHITECT_LAB_RELEASE_STALE_MINUTES` to control when a long-idle release is escalated into the risk board and handoff summary.
`approval-review-board` tracks releases still waiting on first approval or missing required approver roles for the evaluated environments.
Set `AGENT_ARCHITECT_LAB_APPROVAL_STALE_MINUTES` to escalate long-idle approval queues.
`override-review-board` ranks individual overrides into `expired`, `expiring_soon`, `active_no_expiry`, and `active`, with a remediation action for each row.
`revoke-release-override` marks the latest matching override as revoked. Revoked overrides stop affecting readiness checks and stop appearing in active override views, but remain in `release-status` for audit history.
`operator-handoff` packages the risk board, approval review board, override review board, and active override list into a single shift handoff payload with a generated summary.
`record-operator-handoff` writes that payload to `artifacts/handoffs` so handoff state can be preserved between shifts.
`list-operator-handoffs` provides a compact shift-history index, and `show-operator-handoff --latest` reloads the latest saved handoff without requiring operators to inspect the artifact directory manually.
`export-operator-handoff-report` renders a saved handoff snapshot into Markdown so the same operator state can be shared as a readable shift-transfer or incident-review document.

## Why This Matters

Without this split, teams often lose the distinction between:

- the benchmark evidence that justified a release
- and the human decisions that changed rollout state later
- and which release actually held each environment before and after a rollback

Strong agent architecture requires both.
