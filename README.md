# Agent Architect Lab

`agent-architect-lab` is a hands-on learning project for building, testing, and evolving agent systems with the same core concerns used in serious AI products: runtime design, tool use, MCP integration, memory, safety, harnesses, and skills.

The repository is intentionally small, but now includes:

- A local agent runtime with deterministic planning
- Workspace-scoped tools for files and shell commands
- An MCP note server and adapter
- A lightweight HTTP control plane with bearer-token-gated read and write routes
- Multiple eval suites, release gates, and harness report comparison
- Sample skill manifests wired into runtime selection and note-backed retrieval
- Configurable planner providers with a deterministic default and model-backed scaffold
- Planner shadow validation artifacts for model-backed rollout discipline
- Incident-to-eval suggestion flow for turning failures into new harness tasks
- Human feedback ingestion across releases, incidents, reports, and run artifacts
- A report registry and manifest-aware baseline selection for release-grade eval comparisons
- Immutable release manifests plus a release ledger with approval and promotion state transitions
- A bounded role-handoff release command brief for QA, ops, incident command, and release management
- Documentation aimed at a senior agent architect growth path

## Project Layout

- `src/agent_architect_lab/agent`: runtime, memory, planning patterns
- `src/agent_architect_lab/tools`: local tools and registry
- `src/agent_architect_lab/mcp`: MCP protocol, client, server, tool adapter
- `src/agent_architect_lab/harness`: eval running, grading, comparison, gates, promotion, incident backfill
- `src/agent_architect_lab/evals/datasets`: deterministic local tasks and incident backfill staging slices
- `data/skills`: sample agent skills
- `data/notes`: searchable architecture notes
- `docs`: architecture, harness practice, roadmap

## Quick Start

Run from source:

```bash
cd /Volumes/ExtaData/newcode/agent-architect-lab
PYTHONPATH=src python3 -m agent_architect_lab.cli explain-patterns
PYTHONPATH=src python3 -m agent_architect_lab.cli list-skills --goal "agent skills and memory retrieval"
PYTHONPATH=src python3 -m agent_architect_lab.cli run-task "summarize 'pyproject.toml'"
PYTHONPATH=src python3 -m agent_architect_lab.cli run-evals --suite default
PYTHONPATH=src python3 -m agent_architect_lab.cli run-evals --suite safety --report-name safety-report.json --report-kind baseline --report-label approved-safety
PYTHONPATH=src python3 -m agent_architect_lab.cli register-report /tmp/agent-architect-lab/.../reports/safety-report.json --report-kind baseline --report-label approved-safety
PYTHONPATH=src python3 -m agent_architect_lab.cli check-gates /tmp/agent-architect-lab/.../reports/safety-report.json --suite-aware-defaults
PYTHONPATH=src python3 -m agent_architect_lab.cli evaluate-promotion /tmp/agent-architect-lab/.../reports/baseline.json /tmp/agent-architect-lab/.../reports/candidate.json --suite-aware-defaults
PYTHONPATH=src python3 -m agent_architect_lab.cli rollout-review /tmp/agent-architect-lab/.../reports/baseline.json /tmp/agent-architect-lab/.../reports/candidate.json --suite-aware-defaults --output-backfill ./candidate-backfill.jsonl
PYTHONPATH=src python3 -m agent_architect_lab.cli run-shadow /tmp/agent-architect-lab/.../reports/baseline.json --suite retrieval --report-name retrieval-shadow.json --suite-aware-defaults --output-backfill ./retrieval-shadow-backfill.jsonl
PYTHONPATH=src python3 -m agent_architect_lab.cli open-incident --severity critical --summary "unsafe output reached production" --owner incident-commander --environment production --release-name 2026-04-10-main
PYTHONPATH=src python3 -m agent_architect_lab.cli incident-review-board
PYTHONPATH=src python3 -m agent_architect_lab.cli transition-incident incident-202604... --status contained --by incident-commander --note "rollback complete" --followup-eval-path ./incident-backfill.jsonl
PYTHONPATH=src python3 -m agent_architect_lab.cli list-incidents --status open
PYTHONPATH=src python3 -m agent_architect_lab.cli export-incident-report incident-202604... --title "Incident Rollback Report"
PYTHONPATH=src python3 -m agent_architect_lab.cli export-incident-bundle incident-202604...
PYTHONPATH=src python3 -m agent_architect_lab.cli record-feedback --summary "release still needs rollback proof" --actor release-manager-1 --role release-manager --sentiment negative --actionability followup_required --target-kind release --release-name 2026-04-10-main --label rollback
PYTHONPATH=src python3 -m agent_architect_lab.cli feedback-summary --release-name 2026-04-10-main
PYTHONPATH=src python3 -m agent_architect_lab.cli run-release-shadow --suites safety retrieval approval_simulation --report-prefix release-candidate --suite-aware-defaults --output-backfill-dir ./release-backfills
PYTHONPATH=src python3 -m agent_architect_lab.cli run-release-shadow --suites safety retrieval --baseline-manifest ./baseline-manifest.json --report-prefix release-candidate --suite-aware-defaults
PYTHONPATH=src python3 -m agent_architect_lab.cli run-release-shadow --suites safety retrieval --report-prefix release-candidate --suite-aware-defaults --release-name 2026-04-10-main
PYTHONPATH=src python3 -m agent_architect_lab.cli approve-release 2026-04-10-main --by qa-owner --role qa-owner --note "gate review complete"
PYTHONPATH=src python3 -m agent_architect_lab.cli approve-release 2026-04-10-main --by release-manager --role release-manager --note "ops sign-off complete"
PYTHONPATH=src python3 -m agent_architect_lab.cli grant-release-override 2026-04-10-main --environment production --blocker environment_frozen --by incident-commander --note "emergency hotfix waiver"
PYTHONPATH=src python3 -m agent_architect_lab.cli deploy-release 2026-04-10-main --environment staging --by release-manager --note "staging rollout"
PYTHONPATH=src python3 -m agent_architect_lab.cli check-deploy-readiness 2026-04-10-main --environment production
PYTHONPATH=src python3 -m agent_architect_lab.cli deploy-policy --environment production
PYTHONPATH=src python3 -m agent_architect_lab.cli deploy-release 2026-04-10-main --environment production --by release-manager --note "production rollout"
PYTHONPATH=src python3 -m agent_architect_lab.cli rollback-release 2026-04-10-main --environment production --by release-manager --note "rollback due to incident"
PYTHONPATH=src python3 -m agent_architect_lab.cli promote-release 2026-04-10-main --by release-manager --note "production rollout started"
PYTHONPATH=src python3 -m agent_architect_lab.cli list-releases
PYTHONPATH=src python3 -m agent_architect_lab.cli rollout-matrix 2026-04-10-main
PYTHONPATH=src python3 -m agent_architect_lab.cli release-readiness-digest 2026-04-10-main
PYTHONPATH=src python3 -m agent_architect_lab.cli release-risk-board
PYTHONPATH=src python3 -m agent_architect_lab.cli approval-review-board
PYTHONPATH=src python3 -m agent_architect_lab.cli list-active-overrides --environment production
PYTHONPATH=src python3 -m agent_architect_lab.cli override-review-board
PYTHONPATH=src python3 -m agent_architect_lab.cli revoke-release-override 2026-04-10-main --environment production --blocker environment_frozen --by release-manager --note "incident closed"
PYTHONPATH=src python3 -m agent_architect_lab.cli operator-handoff
PYTHONPATH=src python3 -m agent_architect_lab.cli record-operator-handoff --label night-shift
PYTHONPATH=src python3 -m agent_architect_lab.cli list-operator-handoffs --limit 10
PYTHONPATH=src python3 -m agent_architect_lab.cli show-operator-handoff --latest
PYTHONPATH=src python3 -m agent_architect_lab.cli export-operator-handoff-report --latest --title "Night Shift Release Report"
PYTHONPATH=src python3 -m agent_architect_lab.cli export-governance-summary --title "Weekly Governance Summary"
PYTHONPATH=src python3 -m agent_architect_lab.cli run-planner-shadow --suite planner_shadow --report-name planner-shadow-report.json --markdown-output ./planner-shadow.md
PYTHONPATH=src python3 -m agent_architect_lab.cli export-release-command-brief 2026-04-10-main --title "Release Command Brief"
AGENT_ARCHITECT_LAB_CONTROL_PLANE_READ_TOKEN=reader-token AGENT_ARCHITECT_LAB_CONTROL_PLANE_MUTATION_TOKEN=writer-token PYTHONPATH=src python3 -m agent_architect_lab.cli run-control-plane-server --host 127.0.0.1 --port 8080
curl -H "Authorization: Bearer reader-token" http://127.0.0.1:8080/governance-summary
curl -X POST http://127.0.0.1:8080/incidents/open -H "Authorization: Bearer writer-token" -H "Content-Type: application/json" -d '{"severity":"high","summary":"staging rollback triggered","owner":"incident-commander","environment":"staging"}'
PYTHONPATH=src python3 -m agent_architect_lab.cli environment-history --environment staging
PYTHONPATH=src python3 -m agent_architect_lab.cli environment-status --environment staging
PYTHONPATH=src python3 -m agent_architect_lab.cli release-status 2026-04-10-main
PYTHONPATH=src python3 -m agent_architect_lab.cli suggest-incident-evals /tmp/agent-architect-lab/.../reports/latest-report.json --output ./incident-backfill.jsonl
AGENT_ARCHITECT_LAB_PLANNER_PROVIDER=openai_compatible PYTHONPATH=src python3 -m agent_architect_lab.cli run-task "find 'cli.py'"
```

Install as a package:

```bash
cd /Volumes/ExtaData/newcode/agent-architect-lab
python3 -m pip install -e .[dev]
agent-lab explain-patterns
agent-lab run-evals
```

## What This Lab Teaches

This lab is optimized for someone who wants to grow from "can wire an agent demo" to "can design an agent product platform".

Core learning tracks:

1. Runtime architecture: planning loop, tool routing, checkpoints, traces
2. Skills: reusable operating contracts above the tool layer
3. MCP and knowledge systems: protocol boundaries, adapters, note retrieval
4. Safety: sandbox boundaries, command validation, approval design
5. Harness engineering: task datasets, grading, reporting, regression loops
6. Product architecture: control plane, execution plane, knowledge plane, ops

## Architecture Map

High-level execution flow:

```text
CLI
  -> AgentRuntime
     -> SkillRouter
     -> MemoryManager
     -> AgentPlanner
        -> HeuristicPlanner
     -> ToolRegistry
        -> read_file / write_file / search_files / run_shell
        -> MCPToolAdapter -> MCPClient -> scripts/run_mcp_server.py -> MCP note server
     -> TraceStore + CheckpointStore

run-evals
  -> load_suite
  -> run_suite
  -> grade_trace
  -> HarnessReport
  -> compare_reports / check_gates
```

More detail:

- [docs/ARCHITECTURE.md](/Volumes/ExtaData/newcode/agent-architect-lab/docs/ARCHITECTURE.md)
- [docs/HARNESS_PRACTICES.md](/Volumes/ExtaData/newcode/agent-architect-lab/docs/HARNESS_PRACTICES.md)
- [docs/LEARNING_PATH.md](/Volumes/ExtaData/newcode/agent-architect-lab/docs/LEARNING_PATH.md)
- [docs/AI_ARCHITECT_COMPETENCY_MATRIX.md](/Volumes/ExtaData/newcode/agent-architect-lab/docs/AI_ARCHITECT_COMPETENCY_MATRIX.md)
- [docs/EVALS_AND_SAFEGUARDS_ROADMAP.md](/Volumes/ExtaData/newcode/agent-architect-lab/docs/EVALS_AND_SAFEGUARDS_ROADMAP.md)
- [docs/OPS_AND_INCIDENTS.md](/Volumes/ExtaData/newcode/agent-architect-lab/docs/OPS_AND_INCIDENTS.md)
- [docs/PLANNER_PROVIDERS.md](/Volumes/ExtaData/newcode/agent-architect-lab/docs/PLANNER_PROVIDERS.md)
- [docs/INCIDENT_BACKFILL.md](/Volumes/ExtaData/newcode/agent-architect-lab/docs/INCIDENT_BACKFILL.md)
- [docs/REPORT_REGISTRY.md](/Volumes/ExtaData/newcode/agent-architect-lab/docs/REPORT_REGISTRY.md)
- [docs/RELEASE_LEDGER.md](/Volumes/ExtaData/newcode/agent-architect-lab/docs/RELEASE_LEDGER.md)
- [docs/RELEASE_LEDGER_ZH.md](/Volumes/ExtaData/newcode/agent-architect-lab/docs/RELEASE_LEDGER_ZH.md)
- [docs/HUMAN_FEEDBACK.md](/Volumes/ExtaData/newcode/agent-architect-lab/docs/HUMAN_FEEDBACK.md)
- [docs/HUMAN_FEEDBACK_ZH.md](/Volumes/ExtaData/newcode/agent-architect-lab/docs/HUMAN_FEEDBACK_ZH.md)
- [docs/CONTROL_PLANE.md](/Volumes/ExtaData/newcode/agent-architect-lab/docs/CONTROL_PLANE.md)
- [docs/CONTROL_PLANE_ZH.md](/Volumes/ExtaData/newcode/agent-architect-lab/docs/CONTROL_PLANE_ZH.md)
- [docs/PRODUCTION_RELEASE_SYSTEM_PLAN.md](/Volumes/ExtaData/newcode/agent-architect-lab/docs/PRODUCTION_RELEASE_SYSTEM_PLAN.md)
- [docs/PRODUCTION_RELEASE_SYSTEM_PLAN_ZH.md](/Volumes/ExtaData/newcode/agent-architect-lab/docs/PRODUCTION_RELEASE_SYSTEM_PLAN_ZH.md)
- [docs/RUNTIME_REALISM.md](/Volumes/ExtaData/newcode/agent-architect-lab/docs/RUNTIME_REALISM.md)
- [docs/RUNTIME_REALISM_ZH.md](/Volumes/ExtaData/newcode/agent-architect-lab/docs/RUNTIME_REALISM_ZH.md)

## Artifact Strategy

By default, traces, checkpoints, and reports are written outside the repository under the system temp directory so eval runs do not pollute workspace search or source control. Override with `AGENT_ARCHITECT_LAB_ARTIFACTS` if you need a fixed location.

Saved reports are also indexed into `report-registry.json` in the reports directory. Promotion-grade workflows should prefer:

- reports explicitly registered as `baseline`
- or an explicit `--baseline-manifest`

instead of relying only on "the newest file on disk".

Recorded releases are stored separately under `artifacts/releases`:

- immutable manifest snapshots in `manifests/`
- mutable operator state in `release-ledger.json`

That split makes it possible to audit what was reviewed versus what was later approved or promoted.
Operator incidents are stored under `artifacts/incidents/incident-ledger.json` so triage, containment, follow-up evals, and closure remain auditable across shifts.
Explicit human review feedback is stored under `artifacts/feedback/feedback-ledger.json` so release, incident, and artifact review signals can be summarized alongside system state.

Production deploy readiness also respects `AGENT_ARCHITECT_LAB_PRODUCTION_SOAK_MINUTES`, which defaults to `30`.
Required production sign-off roles come from `AGENT_ARCHITECT_LAB_PRODUCTION_REQUIRED_APPROVER_ROLES`, which defaults to `qa-owner,release-manager`.
Default rollout environments come from `AGENT_ARCHITECT_LAB_ENVIRONMENTS`, which defaults to `staging,production`.
Environment-specific policy overrides come from `AGENT_ARCHITECT_LAB_ENVIRONMENT_POLICIES`, which accepts JSON such as `{"canary":{"required_predecessor_environment":"staging","required_approver_roles":["qa-owner"],"soak_minutes_required":5},"production":{"required_predecessor_environment":"canary","required_approver_roles":["ops-oncall"],"soak_minutes_required":30}}`.
Environment freeze windows come from `AGENT_ARCHITECT_LAB_ENVIRONMENT_FREEZE_WINDOWS`, which accepts a JSON object such as `{"staging":["00:00-06:00"],"production":["22:00-23:59","00:00-01:00"]}`.
An active freeze window adds the `environment_frozen` blocker to deploy readiness results. Windows support same-day ranges and cross-midnight ranges.
Use `deploy-policy --environment <name>` to inspect the currently enforced deploy policy and the active release head for an environment.
Use `rollout-matrix [release_name]` to get a multi-environment operator view. When a release name is supplied, the matrix includes readiness plus a per-environment `recommended_action`, and returns a non-zero exit code when any environment is blocked.
Use `grant-release-override` to waive a specific deploy blocker for one release and one environment. Overrides are recorded in the release ledger and can include an optional `--expires-at` ISO timestamp.
Use `list-active-overrides` to audit currently effective overrides across releases or for a specific environment.
Use `release-readiness-digest <release_name>` as the operator-facing summary view for a release. It condenses blocking environments, recommended actions, active overrides, and soon-to-expire overrides into one payload.
Use `release-risk-board` to rank multiple recorded releases by operator risk so oncall can decide what to inspect first.
Use `AGENT_ARCHITECT_LAB_RELEASE_STALE_MINUTES` to escalate long-idle releases into the risk board and handoff summary.
Use `approval-review-board` plus `AGENT_ARCHITECT_LAB_APPROVAL_STALE_MINUTES` to surface stale approval queues and releases still missing required approver roles.
Use `open-incident`, `transition-incident`, `list-incidents`, and `incident-review-board` to run a basic incident command workflow with ownership, status, and follow-up eval linkage.
Use `export-incident-report` to render one incident into a readable Markdown artifact for postmortems or stakeholder updates.
Use `export-incident-bundle` to package the incident, linked release state, and related handoff artifacts into one export directory.
Use `record-feedback`, `list-feedback`, and `feedback-summary` to capture explicit human review signals and feed them back into governance views.
Use `export-governance-summary` to generate a manager-facing Markdown summary across release risk, approval backlog, incident load, and override pressure.
Use `run-planner-shadow` to validate bounded planner behavior against task policy before trusting a model-backed planner in promotion workflows.
Use `export-release-command-brief` to generate a deterministic role-handoff artifact spanning QA, ops, incident command, and release management.
Use `run-control-plane-server` to expose the same governance layer over HTTP for internal dashboards or automation.
Control-plane bind settings come from `AGENT_ARCHITECT_LAB_CONTROL_PLANE_HOST` and `AGENT_ARCHITECT_LAB_CONTROL_PLANE_PORT`, which default to `127.0.0.1` and `8080`.
Read routes can be protected with `AGENT_ARCHITECT_LAB_CONTROL_PLANE_READ_TOKEN`.
State-changing routes require `AGENT_ARCHITECT_LAB_CONTROL_PLANE_MUTATION_TOKEN`; if it is unset, write routes return `503`.
Protected control-plane routes also require `X-Control-Plane-Actor` and `X-Control-Plane-Role` headers when the route has an active role policy.
Role policies come from `AGENT_ARCHITECT_LAB_CONTROL_PLANE_ROLE_POLICIES`, which defaults to separate permissions for governance reads, incident opening, and incident transitions.
State-changing routes also require an `Idempotency-Key` header. The first successful mutation response is stored and replayed for safe retries.
Control-plane mutation audits are written under `artifacts/control-plane/mutation-requests.jsonl`, and idempotency state is stored under `artifacts/control-plane/idempotency-registry.json`.
Long-running exports now run through a persisted job registry at `artifacts/control-plane/job-registry.json`.
The embedded worker polls that registry on `AGENT_ARCHITECT_LAB_CONTROL_PLANE_JOB_POLL_INTERVAL_S`, which defaults to `0.25`.
Control-plane policy decisions now flow through a centralized policy engine, and mutation persistence now goes through repository-style abstractions instead of being hardcoded inside request handlers.
Use `override-review-board` to prioritize override cleanup and renewal work across releases, including expired overrides and overrides missing an expiry.
Use `revoke-release-override` to close an override without deleting its audit trail from the ledger.
Use `operator-handoff` to generate a combined shift handoff payload containing release risk, approval backlog, incident backlog, override remediation, active incidents, active overrides, and a summary line for the next operator.
Use `record-operator-handoff` to persist that handoff snapshot under `artifacts/handoffs` for shift-history and audit trails.
Use `list-operator-handoffs` and `show-operator-handoff --latest` to review prior shift snapshots without manually opening artifact files.
Use `export-operator-handoff-report --latest` to render the saved handoff into a Markdown report suitable for shift transfer, incident review, or status sharing.

## Planner Providers

The runtime defaults to the deterministic `heuristic` planner. A model-backed scaffold is also available through the `openai_compatible` provider using:

- `AGENT_ARCHITECT_LAB_PLANNER_PROVIDER`
- `AGENT_ARCHITECT_LAB_PLANNER_MODEL`
- `AGENT_ARCHITECT_LAB_PLANNER_API_BASE`
- `AGENT_ARCHITECT_LAB_PLANNER_API_KEY`
- `AGENT_ARCHITECT_LAB_PLANNER_TIMEOUT_S`
- `AGENT_ARCHITECT_LAB_PLANNER_MAX_RETRIES`

The `openai_compatible` provider validates tool names and tool arguments against the local tool schemas before execution.
`run-planner-shadow` adds a reviewable shadow artifact on top of that provider boundary so a hosted planner can be checked against bounded policy before rollout.

## Current Product Direction

The lab still uses a deterministic planner by default, which keeps it runnable without API keys. That is deliberate. The next serious step is no longer the first control-plane boundary because that now exists; it is hardening the remaining production gaps:

- LLM-backed planner providers
- richer skill selection and policy routing
- task types with stronger graders
- queued/background control-plane work and stronger role segmentation
- planner shadow validation and bounded role-based orchestration

Those extensions are outlined in the docs.
