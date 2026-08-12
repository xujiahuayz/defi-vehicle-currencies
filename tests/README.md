# Tests

Tests mirror the repository's scientific contracts: provider schemas, raw certification, route and state reconstruction, pricing, release identity, provenance, metrics, estimators, workflow gates, and deliverable conformance. A regression should reproduce the exact failure mode and assert the economic or lifecycle invariant, not only the exception text.

Run the complete suite with `./scripts/run -m unittest discover -s tests`. Structural changes also require the shared structural-change gate over the exact changed architecture and focused tests. Expensive integration tests should use bounded fixtures or explicit opt-in data roots; ordinary tests must not mutate canonical local data.
