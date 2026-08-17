# Tests

Tests cover provider parsing, reconstruction, pricing, transformations, estimators,
workflow paths and deliverable builds. Prefer bounded fixtures and direct economic
or schema invariants. Do not add tests whose only purpose is a content fingerprint,
certificate chain or parallel release registry.

Run the suite with `./scripts/run -m unittest discover -s tests`. See the root
[`README.md`](../README.md) for the project-wide contract.
