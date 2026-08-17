# Raw data

All source data owned by this project lives here as regular files. New fetches write only to the provider folders below; no script may write to or link against the retired sibling repository.

- `thegraph/`: indexed venue records.
- `dune/`: indexed Fluid records.
- `ethereum/`: direct-chain logs, receipts, headers, registries, and state inputs.
- `external/`: named off-chain sources.
- `archive/defi-dominant-currency/`: exact raw records recovered from the retired project on 2026-08-17. These are retained because raw data is never pruned. They are not current processed inputs unless a process script names them explicitly.

The reproducible path is intentionally simple: a fetch script creates raw data; a process script turns it into `data/processed/`; table and plot scripts read processed data and write `output/`; the paper and deck include those outputs.
