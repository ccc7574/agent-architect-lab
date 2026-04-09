# Report Registry

Serious agent release systems should not decide baselines only by file name or modified time.

This lab now maintains a `report-registry.json` file under the reports directory. Each record stores:

- suite name
- absolute report path
- report kind such as `baseline`, `adhoc`, `shadow_candidate`, or `release_candidate`
- optional label
- creation timestamp
- content digest
- summary metrics

## Recommended Workflow

1. Save an approved suite result as a baseline:

```bash
PYTHONPATH=src python3 -m agent_architect_lab.cli run-evals \
  --suite safety \
  --report-name safety-baseline.json \
  --report-kind baseline \
  --report-label approved-safety
```

2. Or register an existing report after review:

```bash
PYTHONPATH=src python3 -m agent_architect_lab.cli register-report \
  /tmp/agent-architect-lab/.../reports/safety-baseline.json \
  --report-kind baseline \
  --report-label approved-safety
```

3. Run release shadow review. Baselines resolve in this order:

- `--baseline-manifest`
- latest registered `baseline` report for the suite
- fallback file discovery

## Why This Matters

This closes a common production gap:

- ad hoc local runs can exist without becoming release baselines
- approved baselines become explicit artifacts
- release output can explain whether a baseline came from `manifest`, `registry`, or fallback `discovery`

That audit trail is a prerequisite for a real promotion system.
