# Fetch

Acquisition programs write retained source records under `data/raw/` or local
literature source payloads. They do not clean panels or estimate results.

| Owner | Purpose |
|---|---|
| `fetch_raw_market_data.py` | plan, fetch, audit, and report coverage for all DEX/provider streams |
| `supervise_raw_fetch.py` | resume gap-only market-data fetches and narrow failed batches |
| `fetch_pool_identity_registry.py` | fetch the V3 pool-identity snapshot needed by current processors |
| `fetch_v1_exchange_registry.py` | fetch the immutable V1 exchange-to-token registry omitted from the original daily pull |
| `fetch_defillama_ethereum_dex_volume.py` | fetch the external daily Ethereum DEX-volume breakdown used to assess market representativeness |
| `fetch_defillama_stablecoin_supply.py` | retain the DeFiLlama stablecoin catalog and same-symbol detail histories used for exact canonical-address supply matching |
| `fetch_route_gas_receipts.py` | fetch transaction receipts for the deterministic route-gas sample and exact contestable routes |
| `discover_pdf_sources.py` | discover bibliography-linked publisher PDF locations |
| `fetch_literature.py` | fetch PDFs from the maintained source map |
| `export_literature_auth.py` / `fetch_literature_browser.py` | authenticated literature acquisition |
| `build_literature_text_cache.py` / `ocr_literature_pdf.swift` | searchable text and OCR from retained PDFs |

Provider definitions live in `../../src/ddvc/fetch/sources.py` and fetched
fields in `../../src/ddvc/fetch/schemas.py`. Raw files are retained. Secrets,
browser profiles, and provider credentials stay outside Git.
