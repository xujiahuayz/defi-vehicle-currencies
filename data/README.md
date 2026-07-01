# Data Workspace

All data payloads are local and regenerated from code. Do not commit raw, interim, processed, or external data files.

## Layout

- `raw/` — verbatim source responses fetched once from subgraphs, APIs, RPC calls, downloads, or other sources.
- `interim/` — normalized intermediate files that preserve source identifiers and provenance.
- `processed/` — route tables, metrics, analysis panels, and figure-source datasets.
- `external/` — local licensed or manually supplied inputs, if any.
- `manifests/` — lightweight run manifests that are safe to commit when they contain no secrets and no private-source references.

## Date Convention

The target sample through 2026-06-30 UTC should be represented in scripts as `start <= date < 2026-07-01`.

## Raw Market Fetch

Plan the full genesis-through-last-complete-month raw fetch:

```bash
python3 scripts/fetch_raw_market_data.py plan --dex all
```

Genesis is recorded by block first where known, with a cached UTC date used only
for day partitioning. Audit the configured block/date against the first indexed
swap in each Graph source before a full run:

```bash
GRAPH_API_KEYS=... python3 scripts/fetch_raw_market_data.py audit-genesis --dex all --strict
```

Run the fetch after setting `GRAPH_API_KEYS` and, for Dune-backed sources such as
Uniswap V1, SushiSwap V2, and Fluid, `DUNE_API_KEYS` in `.env` or the shell:

```bash
GRAPH_API_KEYS=... DUNE_API_KEYS=... python3 scripts/fetch_raw_market_data.py fetch --dex all --start genesis --end 2026-07-01
```

The fetcher writes verbatim gzipped JSONL and tiny metadata sidecars under
`data/raw/thegraph/<source>/` or `data/raw/dune/<source>/`. The source, stream,
and date are all encoded in the filename, for example
`uniswap_v3_swaps_20260630.jsonl.gz`. This keeps the raw tree shallow while
avoiding one huge mixed-source directory. It over-fetches swap, daily-pool, LP
mint/burn, V4 liquidity-modification, V2 reserve, and Dune `dex.trades` fields so
route reconstruction, vehicle-route costs, liquidity concentration, LP
repositioning, and settlement-implementation tests can be derived locally
without repeated network queries.

## Data Dictionary

Column definitions will be added here as each table family is created. Keep this file as the only markdown file under `data/`.
