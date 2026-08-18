# Verify

Verification inspects the production chain; it does not create alternative data
layers.

| Command family | Purpose |
|---|---|
| `audit_findings_freeze.py` | check the two active claims and their direct dependencies |
| `audit_deck_evidence.py` | check generated-value bindings, evidence-source notes, language, and density |
| `check_deliverable_conformance.py` | run the complete paper/deck handoff checks |
| `measure_prose_conventions.py`, `find_prose_outliers.py`, `measure_venue_shape.py`, `measure_venue_optics.py` | compare manuscript prose and venue presentation with the maintained literature corpus |
| `check_replacement_headroom.py` | support focused prose revision without changing evidence |
| `validate_curve_quoter.py`, `validate_v4_quoter.py`, `validate_weighted_quoter.py` | validate quote implementations and write the appendix-facing diagnostics |
The repository test suite supplies schema and economic-identity checks. The
commands above are named, direct consumers of any diagnostic output they write.
The human-facing writing and rhetoric rules that these checks partially enforce
live in [`../../docs/research/writing-and-rhetoric.md`](../../docs/research/writing-and-rhetoric.md).
