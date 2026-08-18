# Acquisition

The executable acquisition contract lives in the following code:

- `../../scripts/fetch/fetch_raw_market_data.py` plans, fetches, checks coverage,
  and repairs metadata for the retained provider streams;
- `../../src/ddvc/fetch/sources.py` maps venues to providers and launch dates;
- `../../src/ddvc/fetch/schemas.py` declares the fields fetched for each stream;
- `../../scripts/fetch/fetch_pool_identity_registry.py` obtains the V3 pool
  identities needed to process legacy address-light pool-day records;
- `../../scripts/process/reconcile_graph_event_order.py` obtains exact RPC order
  only for indexed events whose within-block order is ambiguous.

Raw responses and directly used acquisition metadata live under `data/raw/`.
Analysis results live under `output/`. Historical acquisition experiments remain
available in Git history and are not maintained as a second workflow here.
