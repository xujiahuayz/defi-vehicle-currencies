# Research package

`ddvc` contains reusable project logic.

| Path | Responsibility |
|---|---|
| `ddvc/fetch/` | Provider clients, source schemas, and retained-raw acquisition helpers |
| `ddvc/reconstruct/` | Route reconstruction from atomic trades into ultimate trades |
| `ddvc/analysis/` | Reusable estimators and economic transformations |
| `ddvc/` | Shared route, state, pricing, schema, path, and file-writing utilities |

Command-line parsing and one-off orchestration belong in `../scripts/`. Keep a
single path definition and a single implementation of each estimator.

The complete pipeline is documented in
[`../docs/repository-data-map.md`](../docs/repository-data-map.md).
