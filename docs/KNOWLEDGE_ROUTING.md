# Knowledge Routing

`agent-architect-lab` now treats note retrieval as a lightweight knowledge-routing layer instead of a plain lexical file search.

## What Changed

- note search results now include structured metadata
- retrieval ranking now uses inferred domains in addition to query-term overlap
- note reads now return provenance data alongside raw content
- runtime answers now surface the source note they were grounded on

## Retrieval Result Shape

`search_notes` now returns matches with:

- `metadata.note_id`
- `metadata.title`
- `metadata.summary`
- `metadata.domains`
- `metadata.tags`
- `metadata.headings`
- `provenance.source_type`
- `provenance.score`
- `provenance.matched_terms`
- `provenance.matched_domains`
- `provenance.matched_fields`

`get_note` now returns:

- note content
- the same note metadata
- provenance showing which note file grounded the answer

## Why This Matters

Top-tier AI architect workflows care about more than “did retrieval find a string.”

They care about:

- which knowledge source was used
- why that source ranked above alternatives
- whether the source domain matched the task
- whether the answer can be audited back to a durable artifact

This repo still does not implement embedding retrieval or a full knowledge service, but it now models the more important production concept: retrieval decisions should be inspectable and attributable.

## Example

```bash
PYTHONPATH=src python3 -m agent_architect_lab.cli run-task "memory retrieval system design"
```

The resulting trace now shows:

- `search_notes` with ranked note matches and provenance metadata
- `get_note` with note metadata and source provenance
- a final answer that identifies the source note explicitly
