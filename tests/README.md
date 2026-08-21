# Tests

Tests cover provider parsing, reconstruction, pricing, transformations, estimators,
workflow paths and deliverable builds. Prefer bounded fixtures and direct economic
or schema invariants.

`test_balancer_stable_core_lp_flows.py` fixes the exact core/spoke pool
classification, BPT and non-USD exclusions, refreshed Balancer daily-state
schema, event-flow valuation, concentration, and leave-largest-pool contracts.

Run the suite with `./scripts/run -m unittest discover -s tests`. See the root
[`README.md`](../README.md) for the project-wide contract.
