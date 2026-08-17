# Data

Follow the data contract in the root [`README.md`](../README.md) and the path map in
[`docs/repository-data-map.md`](../docs/repository-data-map.md).

- `raw/`: retained provider, chain and external source data.
- `unified/`: reconstructed cross-venue routes.
- `processed/`: analysis-ready panels.
- `interim/`: disposable command-local scratch.
- `empirical/`, `metrics/`, `exhibits/`: older derived families; keep only while a
  current script or deliverable consumes them.
- `external/`: licensed/manual inputs that cannot be fetched into `raw/`.
- `manifests/`: legacy compatibility metadata; do not add new fingerprint or
  certificate files, and remove entries as their callers are simplified.

Raw data are retained as regular files. Derived data must have a named producer and
consumer. A filename alone never makes a panel current.
