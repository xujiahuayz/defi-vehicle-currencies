# The Making of Dominant Vehicle Currencies

This repository contains the acquisition, reconstruction, analysis, literature, paper, and presentation workflow for the DeFi vehicle-currencies project.

## Start Here

- [`docs/research-workflow.md`](docs/research-workflow.md) defines the iterative research graph and its gates.
- [`docs/repository-data-map.md`](docs/repository-data-map.md) is the canonical map of repository ownership, data lineage, scientific roles, downstream consumers, and cleanup rules.
- [`data/README.md`](data/README.md) gives concise operator guidance for the local data workspace.
- [`output/README.md`](output/README.md) defines the code-to-deliverable handoff.

## Repository Topology

- [`src/ddvc/`](src/README.md) contains reusable research logic and registries.
- [`scripts/`](scripts/README.md) contains thin, directly runnable acquisition, processing, analysis, and rendering entry points.
- `data/` contains local evidence, canonical derived panels, runtime intermediates, and tracked provenance manifests; payloads are not committed.
- `output/` contains code-generated tables, figures, exhibits, and inspection artifacts consumed by the paper and deck.
- `literature/` contains the bibliography, admission records, full-text audit material, and retrieval metadata.
- [`paper/`](paper/README.md) and [`deck/`](deck/README.md) contain the two authored deliverables and their review builds.
- `docs/` contains research design, audit, findings, certification, and workflow records.
- [`tests/`](tests/README.md) verifies acquisition contracts, reconstruction, pricing, releases, metrics, and analysis behavior.

## Environment

Install runtime dependencies with:

```bash
uv sync
```

Install development dependencies with:

```bash
uv sync --extra dev
```

Run project commands through `./scripts/run`; it selects the current worktree's package source once and reuses the primary checkout's environment when a linked worktree has none.

## Core Commands

Plan or run the registered raw-market acquisition through the current sample boundary:

```bash
./scripts/run scripts/fetch_raw_market_data.py plan --dex all
GRAPH_API_KEYS=... DUNE_API_KEYS=... ./scripts/run scripts/fetch_raw_market_data.py fetch --dex all --start genesis --end 2026-07-01
```

Build the raw inventory and descriptive paper tables:

```bash
./scripts/run scripts/process/build_raw_data_inventory.py
./scripts/run scripts/tabulate/render_data_coverage.py
./scripts/run scripts/tabulate/render_sample_coverage.py
./scripts/run scripts/tabulate/render_summary_statistics.py
```

Run tests with:

```bash
./scripts/run -m unittest discover -s tests
```

## Sample Boundary

The current target is through 2026-06-30 UTC, represented as the half-open interval `start <= date < 2026-07-01`.

## Source Credentials

The Graph acquisition reads a comma-separated `GRAPH_API_KEYS` pool and Dune acquisition reads `DUNE_API_KEYS`. Secrets and the local key ledger remain outside git. The registered provider and protocol mapping is documented in [`docs/repository-data-map.md`](docs/repository-data-map.md#providers-protocols-and-scientific-layers); `src/ddvc/fetch/sources.py` is executable authority.
