# Research package

`ddvc` contains reusable project logic. Provider clients live in `ddvc.fetch`,
economic transformations and estimators in `ddvc.analysis`, and shared route,
state, pricing, schema and path utilities in the package root.

Command-line parsing and one-off orchestration belong in `../scripts/`. Keep a
single path definition and a single implementation of each estimator. Atomic file
writes and simple build metadata are utilities; release certificates, content
fingerprints and parallel provenance registries are not scientific layers.

The complete pipeline is documented in
[`../docs/repository-data-map.md`](../docs/repository-data-map.md).
