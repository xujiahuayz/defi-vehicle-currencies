# Data

Follow the data contract in the root [`README.md`](../README.md) and the path map in
[`docs/repository-data-map.md`](../docs/repository-data-map.md).

- `raw/`: retained provider, chain and external source data.
- `unified/`: reconstructed cross-venue routes.
- `processed/`: analysis-ready panels.
- `interim/`: disposable command-local scratch.

External or manually obtained source files belong in `raw/external/` with a
short source note.
Raw data are retained as regular files. Derived data must have a named producer and
consumer. A filename alone never makes a panel current.
