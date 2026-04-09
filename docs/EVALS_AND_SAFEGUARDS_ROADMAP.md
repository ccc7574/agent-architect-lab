# Evals And Safeguards Roadmap

This lab should treat evals and safeguards as one architecture problem.

## Current Baseline

- deterministic local suites
- typed graders
- failure taxonomy
- report comparison
- release gates
- shell and file safety boundaries

## Next Maturity Steps

1. Add richer graders
- schema checks
- trace-shape checks
- tool-argument policy checks

2. Add risk-tiered promotion rules
- stricter gates for safety and approval suites
- looser gates for exploratory architecture tasks

3. Add shadow-run style reporting
- baseline versus candidate on the same suite
- explicit regression slices by track

4. Connect incidents back to evals
- every severe incident should add or tighten a task slice
- blocked actions should appear in reports, not only traces

5. Add human approval simulation
- tasks that require escalation
- graders that verify the agent did not auto-execute

## Design Principle

If quality improves while safeguards degrade, the system is not improving.
