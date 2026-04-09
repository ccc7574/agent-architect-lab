# Rollout Review

The purpose of rollout review is to answer one operator question:

Should this candidate build be promoted, and if not, what exactly needs to happen next?

## What The Workflow Combines

- baseline versus candidate comparison
- suite-aware release gates
- blocker and warning explanations
- candidate incident-to-eval backfill suggestions

## Intended Use

1. Run evals for the baseline and candidate.
2. Run `evaluate-promotion` when you only want a gate decision.
3. Run `rollout-review` when you need the operator-facing explanation and suggested benchmark follow-ups.
4. Run `run-shadow` when you want to execute the candidate suite and generate the rollout review in one step.

## Output Shape

A rollout review includes:

- summary
- promotion result
- blocker explanations
- warning explanations
- policy findings grouped by release concern
- suggested eval backfills for failed candidate results

## Why This Matters

Top-tier agent teams do not stop at "the gates failed."

They explain:

- what regressed
- why that regression blocks release
- and which eval tasks should be added so the same issue does not recur silently
