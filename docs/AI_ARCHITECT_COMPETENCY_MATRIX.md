# AI Architect Competency Matrix

This matrix reflects the capability profile increasingly expected from senior and staff-level AI architects working on agent products.

## Core Dimensions

1. Runtime architecture
- planner and executor boundaries
- state handling and resumability
- bounded failure modes

2. Evals and measurement
- capability slicing
- structured graders
- regression review and release gates

3. Safeguards and policy enforcement
- execution policy design
- approvals and escalation thresholds
- auditability of blocked actions

4. Retrieval and memory systems
- short-term vs durable memory separation
- MCP and protocol boundaries
- provenance-aware retrieval

5. Sandbox and execution boundaries
- tool confinement
- shell and file risk controls
- privilege and network escalation paths

6. Observability and incident response
- traces, dashboards, alerts
- rollback design
- incident loops tied back to evals

7. Research to product translation
- convert model capability into shipping surfaces
- turn ambiguous quality signals into measurable gates
- coordinate across research, platform, product, and ops

8. Multi-agent and long-horizon orchestration
- role ownership
- decomposition quality
- evaluator-optimizer workflows

## What This Repository Now Trains

- deterministic runtime debugging
- release-gated local harnesses
- safeguards-aware shell and tool execution
- skill-routed retrieval over notes
- operator and incident-oriented evaluation tracks

## What Still Needs More Work

- model-backed planner providers
- online and shadow evaluation
- explicit human feedback ingestion
- true multi-agent execution ownership
