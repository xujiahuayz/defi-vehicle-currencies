# Research Package

`ddvc` is the reusable scientific and data-release package. Modules own provider contracts, canonical paths and schemas, route and state releases, pricing and replay, analysis primitives, provenance, and registries. Command-line parsing and one-off orchestration belong in `../scripts/`.

Key boundaries:

- `ddvc.fetch` owns source discovery, schema admission, provider acquisition, and raw release contracts.
- `ddvc.pricing` owns AMM-family quote and replay logic.
- `ddvc.analysis` owns estimators and analysis transformations shared by runners and tests.
- `ddvc.data_release`, `ddvc.artifact_release`, and `ddvc.provenance` own released-data identity and fail-closed consumption.
- `ddvc.d3_stage_registry` owns the registered purpose-bound build graph.

Do not create a second path registry, release protocol, variable definition, or regression primitive inside a consumer. See [`../docs/repository-data-map.md`](../docs/repository-data-map.md) for the full data lineage.
