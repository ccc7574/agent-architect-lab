# Learning Path

This roadmap is designed to move the project toward the skill level expected from a senior or staff-level agent architect at a top AI company.

## Phase 1: Runtime Fluency

Goal: understand the execution loop deeply enough to modify it safely.

Study and practice:

- task and trace schemas
- planning loop and step transitions
- tool registration and invocation
- workspace boundaries and shell safety
- checkpoint and trace persistence

Exit criteria:

- you can add a tool without breaking traceability
- you can explain every persisted artifact
- you can debug a failed run from artifacts alone

## Phase 2: Skills And Knowledge Systems

Goal: move from tools to reusable operating behaviors.

Study and practice:

- skill manifests and trigger design
- note retrieval and memory boundaries
- context compression and checkpoint strategy
- MCP as a boundary for remote capabilities

Exit criteria:

- you can define new skills with clear activation rules
- you can explain when to use memory, notes, and checkpoints separately
- you can add a retrieval source without tightly coupling it to the runtime

## Phase 3: Harness Engineering

Goal: build a product-quality evaluation loop.

Study and practice:

- benchmark slicing
- deterministic local tasks
- structured grading
- failure taxonomies
- release gates and regression review
- baseline comparison and promotion criteria

Exit criteria:

- you can explain why a release is better, not just that it "feels better"
- you can detect regressions before they hit users
- you can map failures back to planner, tool, retrieval, or policy causes

## Phase 4: Product Architecture

Goal: think in system planes instead of single scripts.

Study and practice:

- control plane vs execution plane separation
- human approvals and operator workflows
- observability, incident response, and rollback
- tenant isolation and budget control
- multi-agent ownership boundaries
- research-to-product handoff and release readiness

Exit criteria:

- you can design an agent platform, not only an agent demo
- you can propose safe escalation paths for privileged actions
- you can explain how evaluation and operations feed product improvement

## Phase 5: Frontier-System Design

Goal: reach the level where you can lead the architecture of a serious agent product.

Study and practice:

- evaluator-optimizer loops
- role-specialized workers
- long-horizon planning
- online experimentation
- cost, latency, and reliability tradeoffs
- safeguards and evals as coupled systems

Exit criteria:

- you can defend architecture tradeoffs under product, safety, and ops constraints
- you can design for scale, not just correctness
- you can lead roadmap decisions across runtime, harness, memory, and product surfaces
