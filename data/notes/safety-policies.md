# Safety Policies

Safety policies should combine sandboxing, policy validation, approval workflow guardrails, and human approval paths.

Useful principles:

- Default-deny for destructive shell categories.
- Approval workflow guardrails for actions that touch the external world.
- Workspace path confinement for file access.
- Short timeouts and bounded outputs for tool execution.
- Trace every decision that changes the external world.
- Add explicit escalation for network, credentials, and privileged actions.

Good agent safety is not a single filter. It is a stack of controls applied at different layers of execution.
