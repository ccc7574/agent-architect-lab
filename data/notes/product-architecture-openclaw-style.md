# OpenClaw Style Product Architecture

An OpenClaw style agent product architecture can be modeled as five planes:

- Experience plane: chat, IDE, browser, workflow entry points.
- Control plane: task intake, policy checks, routing, session state.
- Execution plane: planner, runtime, tools, MCP adapters, worker roles.
- Knowledge plane: memory, retrieval, notes, traces, checkpoints, analytics.
- Evaluation and operations plane: harnesses, shadow runs, dashboards, rollback, incident response.

The design goal is not just to make one agent work. The design goal is to make many agents observable, governable, and improvable under production load.
