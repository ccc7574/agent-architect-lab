# Shadow Runs

A shadow run is the bridge between offline eval execution and release review.

## What `run-shadow` Does

1. Loads a candidate suite.
2. Runs it through the local runtime.
3. Saves the candidate report.
4. Compares the candidate report against a baseline report.
5. Produces a rollout review with:
- blockers
- warnings
- policy findings
- candidate incident backfill suggestions

## Multi-Suite Release Shadow

`run-release-shadow` extends this idea across multiple suites by:

- resolving a baseline for each suite from an explicit manifest, the report registry, or fallback file discovery
- reserving the candidate report names up front so the release workflow does not accidentally treat a prior shadow artifact as the new baseline
- running each candidate suite locally
- producing per-suite rollout reviews
- aggregating blockers and warnings into a release-level recommendation

`run-shadow` also requires the baseline and candidate paths to be different. If a candidate report would overwrite the baseline, the workflow should stop instead of silently comparing the file to itself.

The release output records the baseline source for each suite so operators can distinguish:

- a pinned release baseline from `manifest`
- an approved baseline from `registry`
- and a weaker fallback from `discovery`

## Why This Matters

Without a shadow-run workflow, teams tend to run evals and then manually stitch together:

- the candidate report
- the gate decision
- the regression explanation
- and the follow-up tasks

That manual stitching is where release discipline usually degrades.
