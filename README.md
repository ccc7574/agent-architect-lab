# Agent Architect Lab

`agent-architect-lab` is a hands-on learning project for building, testing, and evolving agent systems with the same core concerns used in serious AI products: runtime design, tool use, MCP integration, memory, safety, harnesses, and skills.

The repository is intentionally small, but now includes:

- A local agent runtime with deterministic planning
- Workspace-scoped tools for files and shell commands
- An MCP note server and adapter
- Multiple eval suites, release gates, and harness report comparison
- Sample skill manifests wired into runtime selection and note-backed retrieval
- Configurable planner providers with a deterministic default and model-backed scaffold
- Incident-to-eval suggestion flow for turning failures into new harness tasks
- A report registry and manifest-aware baseline selection for release-grade eval comparisons
- Immutable release manifests plus a release ledger with approval and promotion state transitions
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
PYTHONPATH=src python3 -m agent_architect_lab.cli run-release-shadow --suites safety retrieval approval_simulation --report-prefix release-candidate --suite-aware-defaults --output-backfill-dir ./release-backfills
PYTHONPATH=src python3 -m agent_architect_lab.cli run-release-shadow --suites safety retrieval --baseline-manifest ./baseline-manifest.json --report-prefix release-candidate --suite-aware-defaults
PYTHONPATH=src python3 -m agent_architect_lab.cli run-release-shadow --suites safety retrieval --report-prefix release-candidate --suite-aware-defaults --release-name 2026-04-10-main
PYTHONPATH=src python3 -m agent_architect_lab.cli approve-release 2026-04-10-main --by qa-owner --note "gate review complete"
PYTHONPATH=src python3 -m agent_architect_lab.cli deploy-release 2026-04-10-main --environment staging --by release-manager --note "staging rollout"
PYTHONPATH=src python3 -m agent_architect_lab.cli deploy-release 2026-04-10-main --environment production --by release-manager --note "production rollout"
PYTHONPATH=src python3 -m agent_architect_lab.cli rollback-release 2026-04-10-main --environment production --by release-manager --note "rollback due to incident"
PYTHONPATH=src python3 -m agent_architect_lab.cli promote-release 2026-04-10-main --by release-manager --note "production rollout started"
PYTHONPATH=src python3 -m agent_architect_lab.cli list-releases
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

## Planner Providers

The runtime defaults to the deterministic `heuristic` planner. A model-backed scaffold is also available through the `openai_compatible` provider using:

- `AGENT_ARCHITECT_LAB_PLANNER_PROVIDER`
- `AGENT_ARCHITECT_LAB_PLANNER_MODEL`
- `AGENT_ARCHITECT_LAB_PLANNER_API_BASE`
- `AGENT_ARCHITECT_LAB_PLANNER_API_KEY`
- `AGENT_ARCHITECT_LAB_PLANNER_TIMEOUT_S`
- `AGENT_ARCHITECT_LAB_PLANNER_MAX_RETRIES`

The `openai_compatible` provider validates tool names and tool arguments against the local tool schemas before execution.

## Current Product Direction

The lab still uses a deterministic planner, which keeps it runnable without API keys. That is deliberate. The next serious step is not "add a bigger model", but "add better architecture boundaries":

- LLM-backed planner providers
- richer skill selection and policy routing
- task types with stronger graders
- multi-agent orchestration
- production-style observability and rollback workflows

Those extensions are outlined in the docs.
