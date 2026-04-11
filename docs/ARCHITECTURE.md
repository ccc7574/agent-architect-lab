# Architecture

This document explains the current repository as both a runnable lab and a stepping stone toward a production-grade agent platform.

## Current Module Map

```text
cli.py
  -> config.load_settings()
  -> agent.runtime.AgentRuntime
     -> skills.router.SkillRouter
     -> agent.memory.MemoryManager
     -> agent.planner.AgentPlanner
        -> llm.factory.create_planner_provider()
           -> llm.heuristic_provider.HeuristicPlanner
           -> llm.openai_compatible_provider.OpenAICompatiblePlanner
     -> tools.registry.ToolRegistry.local_defaults()
        -> tools.file_tools.ReadFileTool
        -> tools.file_tools.WriteFileTool
        -> tools.file_tools.SearchFilesTool
        -> tools.shell_tool.RunShellTool
     -> optional mcp.tool_adapter.MCPToolAdapter
        -> mcp.client.MCPClient
        -> scripts/run_mcp_server.py
        -> mcp.server.serve()
     -> traces.store.TraceStore
     -> storage.checkpoints.CheckpointStore

harness.runner.run_suite()
  -> evals.tasks.load_default_suite()
  -> ExperimentSuite
  -> AgentRuntime.run(task)
  -> harness.grading.grade_trace()
  -> HarnessReport
  -> optional harness.compare / harness.gates
```

## Runtime Data Flow

Single task path:

```text
goal
  -> Task
  -> SkillRouter.select()
  -> RunTrace.start()
  -> memory summary from prior steps
  -> planner decision
     -> answer directly
     -> or invoke tool
  -> StepTrace append
  -> save trace
  -> save checkpoint
  -> final answer
```

MCP note retrieval path:

```text
goal mentions memory / retrieval / principles
  -> HeuristicPlanner selects search_notes
  -> MCPToolAdapter invokes MCPClient
  -> local MCP server searches data/notes
  -> top note can trigger get_note
  -> runtime emits a grounded answer and stores artifacts
```

Eval path:

```text
JSONL dataset
  -> ExperimentSuite
  -> run each task through runtime
  -> grade via typed graders
  -> aggregate success_rate / average_score / average_steps / failure_types / tracks
  -> compare reports and apply release gates
  -> write report
```

## What Is Good In The Current Design

- The boundaries are understandable.
- Local tools are workspace-scoped.
- The system is deterministic enough for teaching and regression checks.
- Traces and checkpoints are persisted every step.
- MCP is modeled as a protocol boundary, not just another direct function call.
- Skills now influence retrieval-first routing for architecture tasks.
- Harness reports can be compared and checked against release gates.
- Planner provider selection is now explicit in config rather than hard-coded.

## Current Gaps

- The planner is heuristic, not model-backed.
- The model-backed provider scaffold is present and now has a bounded shadow-validation harness, but the default end-to-end suite still stays deterministic.
- Skill routing is intentionally lightweight and mostly note-backed.
- Notes retrieval is still local and lexical rather than embedding-based.
- There is no scheduler, queue, or operator workflow layer.
- There is now a bounded role-handoff release orchestration example, but not a general distributed multi-agent worker plane.

## OpenClaw-Style Product Target

If the goal is to train toward top-tier agent product architecture, design the next version in planes:

1. Experience plane
Agent entry points such as chat, IDE, browser, batch jobs, API clients.

2. Control plane
Session state, routing, policy checks, approvals, budget controls, tenant isolation.

3. Execution plane
Planner, executor, skills, tools, MCP clients, delegated workers, retries, resumability.

4. Knowledge plane
Short-term memory, durable traces, checkpoints, retrieval corpora, embeddings, analytics.

5. Evaluation and operations plane
Offline harnesses, online shadow runs, dashboards, alerts, rollback, incident review.

## Recommended Next Code Steps

1. Add a real `PlannerProvider` implementation backed by an API model.
2. Extend skill routing from note-backed heuristics into tool and policy selection.
3. Add a review loop pattern: planner -> executor -> evaluator.
4. Expand the bounded role orchestration example into broader worker patterns once the release/governance path is fully stable.
5. Add artifact lineage so a result links to prompts, tools, notes, and checkpoints.
6. Add online shadow runs and incident feedback into the harness plane.
