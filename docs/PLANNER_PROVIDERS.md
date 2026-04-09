# Planner Providers

This repository now separates planner selection from runtime construction.

## Available Providers

1. `heuristic`
- deterministic
- no credentials required
- ideal for local regression tests

2. `openai_compatible`
- uses a Chat Completions style HTTP endpoint
- expects JSON planner output
- validates tool names and answer/tool shape before execution
- retries transient provider failures up to the configured retry budget
- intended as a scaffold for model-backed planning

## Why This Matters

A serious agent architecture should not hide model choice inside runtime code.

Provider selection affects:

- latency
- reliability
- determinism
- observability
- rollout and rollback strategy

## Safety Bar For Model-Backed Planning

Even when a hosted planner is used, the runtime still validates the planner output before tool execution.

This means:

- unknown tools become planner failures rather than runtime crashes
- invalid tool arguments are rejected before execution
- malformed planner JSON is rejected before execution
- provider timeouts are recorded as traceable planner failures

## Current Constraint

The `openai_compatible` provider is intentionally lightweight and is not exercised by default local tests. It exists to keep the runtime boundary clean so a real hosted planner can be introduced without rewriting execution and harness code.
