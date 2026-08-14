# Generated Research Outputs

`output/` is the code-to-writing handoff. It contains artifacts written by registered analysis and rendering commands; the paper and deck read from here instead of internal data paths. Authored research decisions, literature digests and retired design memos belong under `docs/` or `literature/`, while compiled deliverables remain under `paper/` and `deck/`.

- `tables/`, `figures/`, and `exhibits/` contain tracked paper- or deck-facing artifacts with provenance stamps.
- `empirical/`, `robustness/`, `model/`, and `provisional/` contain ignored generated analysis material and are not automatically deliverable authority.
- `review/` contains generated inspection artifacts produced for a named review step; durable review records belong in `docs/reviews/`.
The former `nbc_pipeline/` notes were not generated outputs. Deck-craft observations now live in `docs/reviews/deck-venue-exemplars.md`; historical discovery and decision records live in `literature/reviews/`; and the July RQ1–7 design history lives under `docs/retired-rq1-7-*.md`. These are agent-readable knowledge records, not output artifacts; their authority and cleanup rules are defined in the repository map.

Retired empirical generations do not remain under `output/`: Git history preserves them. A design that replaces a retired estimand must use a new registered output name and may publish only after its current inputs and provenance pass the findings freeze.

See the [`canonical repository and data map`](../docs/repository-data-map.md#output-layers) for owners, consumers, and cleanup rules. A rendered artifact is current only when its producer, inputs, provenance, and consuming deliverable agree.
