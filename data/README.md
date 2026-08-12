# Data Workspace

`data/` is the local evidence and derived-panel workspace. Payloads are ignored by git; compact provenance and release identities under `data/manifests/` are tracked. The canonical ownership, lineage, scientific-role, consumer, and cleanup map is [`docs/repository-data-map.md`](../docs/repository-data-map.md).

## Working Contract

- `raw/` retains immutable provider or chain responses. The Graph supplies the registered indexed-protocol streams, Dune supplies Fluid route records, direct Ethereum JSON-RPC supplies independent chain evidence and exact event or transaction fields, and `raw/external/` holds named off-chain sources.
- `unified/` is the released daily cross-venue route topology reconstructed from certified raw swap streams.
- `processed/` contains registered, purpose-bound analysis panels and release pointers.
- `empirical/`, `metrics/`, and `exhibits/` contain specialized or legacy derived families whose owners and current status must be checked in the canonical map before use.
- `interim/` is command-local scratch and must not become a scientific input.
- `external/` is reserved for licensed or manually supplied inputs that cannot live under a named raw acquisition source.
- `manifests/` contains tracked provenance for ignored data and generated output artifacts.

Never select an input because a filename sounds current. Use the executable owner registry, release pointer, provenance stamp, or explicit findings freeze. Do not overwrite a released generation in place, and do not remove a generation until its consumers and release references have been checked.

## Acquisition

Audit registered genesis boundaries before a full fetch:

```bash
GRAPH_API_KEYS=... ./scripts/run scripts/fetch_raw_market_data.py audit-genesis --dex all --strict
```

Fetch the half-open sample through 2026-06-30 UTC:

```bash
GRAPH_API_KEYS=... DUNE_API_KEYS=... ./scripts/run scripts/fetch_raw_market_data.py fetch --dex all --start genesis --end 2026-07-01
```

The raw fetcher writes source-, stream-, and date-addressed gzipped JSONL plus metadata sidecars. Exact Ethereum RPC acquisitions have their own immutable, range-addressed owners. The data layout is partitioned for restartability and bounded parallelism; a partition is not a scientific aggregation unit.
