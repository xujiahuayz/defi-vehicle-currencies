# Generated Research Outputs

`output/` is the code-to-writing handoff. It contains artifacts written by registered analysis and rendering commands; the paper and deck read from here instead of internal data paths. Authored research decisions, literature digests and retired design memos belong under `docs/` or `literature/`, while compiled deliverables remain under `paper/` and `deck/`.

- `tables/`, `figures/`, and `exhibits/` contain tracked paper- or deck-facing artifacts with provenance stamps.
- `empirical/`, `robustness/`, `model/`, and `provisional/` contain ignored generated analysis material and are not automatically deliverable authority.
- `review/` contains generated inspection artifacts produced for a named review step; durable review records belong in `docs/reviews/`.
- `core_empirical_rq_results.md` is still written by `scripts/run_core_rq_experiments.py`, but its pre-redesign generation is not a current finding or deliverable input. It remains only as a reproducible legacy inspection artifact until that producer is retired or migrated.

The former `nbc_pipeline/` notes were not generated outputs. Deck-craft observations now live in `docs/reviews/deck-venue-exemplars.md`; historical literature digests live in `literature/reviews/`; and the retired RQ1–7 design memos live under `docs/retired-rq1-7-*.md`.

See the [`canonical repository and data map`](../docs/repository-data-map.md#output-layers) for owners, consumers, and cleanup rules. A rendered artifact is current only when its producer, inputs, provenance, and consuming deliverable agree.
