# Harness Practices

This lab should be treated as an evaluation discipline, not just a demo runner.

## Minimum Bar

A useful agent harness should answer:

- Which tasks passed.
- Which tasks regressed.
- Which failure types increased.
- How many steps the agent needed.
- Whether the result quality improved or only got longer.
- Whether blocked failure types escaped into a candidate release.

## Practical Patterns

### 1. Separate task definitions from graders

Tasks belong in datasets. Graders belong in harness code. This keeps the benchmark portable and reviewable.

### 2. Start deterministic, then expand

Before adding live APIs or browser agents, build a local suite with file, shell, and note-retrieval tasks. Deterministic smoke tests protect development speed.

### 3. Aggregate more than success rate

Success rate alone hides important changes. Step count, average score, and failure breakdowns make regressions visible sooner.

### 4. Use typed graders

Keyword checks are a fine bootstrap, but mature harnesses add typed checks:

- content checks
- tool-path checks
- status checks
- failure-type checks
- step-budget checks

Typed graders make failures explainable and composable.

### 5. Keep artifacts reviewable

Traces, checkpoints, and reports should be saved in predictable locations with stable schemas. Auditability is part of harness design.

### 6. Add planner shadow validation before rollout

Hosted planners should not jump directly from "provider integration works" to "release is safe".

Use a bounded shadow suite to check:

- first-step action type
- allowed versus blocked tools
- approval-style answers for destructive requests
- heuristic-versus-candidate drift

### 7. Organize by capability track

Examples:

- runtime basics
- tool use
- retrieval and memory
- safety policy
- planning depth
- multi-agent coordination
- approvals and operator workflows
- operations and incident response

## What A Senior Agent Architect Adds

A senior architect does not stop at "the model answered correctly".

They also define:

- task coverage across product surfaces
- failure taxonomies
- promotion criteria for releases
- baseline versus candidate promotion decisions
- shadow traffic strategy
- rollback and incident workflows
- ownership between research, platform, product, and operations
- the exact gate that blocks a release when safety degrades
- how a real incident becomes a permanent eval task in the benchmark
- how a rollout review explains blockers, warnings, and required eval backfills in one operator-facing output
- how planner shadow artifacts become part of release review
