# Raw-data reuse plan: ddc store → ddvc pipeline (2026-07-02, Java-approved)

Decision: **reuse the ddc raw layer, rebuild every derivation with ddvc code, fetch only deltas.** Verified basis: the ddvc source registry uses the *same subgraph deployment IDs* as the ddc store for all six Graph sources (uniswap_v2 `EYCKATKG…`, uniswap_v3 `5zvR82Qo…`, uniswap_v4 `DiYPVdyg…`, curve `3fy93eAT…`, sushiswap_v3 `2tGWMrDh…`, balancer `C4ayEZP2…`), and both stores are verbatim gzipped-JSONL day files with block-provenance meta sidecars. Re-downloading ~76G of identical bytes from the same deployments proves nothing scientifically; "redone properly" lives in the derivation code and validation gates, which ddvc rebuilds from scratch. ddc *derived* layers (`unified/`, `metrics/`, `regression/`, `directional_volume/`) are **never** copied.

## What the transfer contains (76G, rsync M3 → Studio `~/projects/defi-dominant-currency/data/`, sentinel `.RAW_SYNC_COMPLETE` on completion)

- Swap history, genesis → 2026-05-31, all seven ddc sources: uniswap_v2 (2,212 day files), uniswap_v3 (1,853), uniswap_v4, curve (2,343), balancer, sushiswap_v3, fluid (Dune-backed).
- **V3 `raw_mints` + `raw_burns`, full history** (1,853 days each) — the LP streams the liquidity-provision frame needs are already fetched.
- V4 `raw_mints` stores the **`modifyLiquidities` entity verbatim** (signed liquidity delta) — the same entity the ddvc schema targets, under a legacy stream name.
- `raw_pool_day` (+ `raw_pool_day_fee` for V3/V4), `raw_meta` sidecars (min/max block, `head_block_at_fetch`), targeted pool state (`uniswap_v3/pool_liq` — 17 counterfactual pools, `uniswap_v2/pool_reserves`, `curve/pool_balances`), and `market/` aux (gas, ETH, FX, FF3+RF, sp_crypto, crypto_index, fear&greed, CRSP).

## Migration steps (Studio, after the sentinel appears)

1. **Hardlink-migrate** into the ddvc layout — `data/<dex>/raw_<stream>/raw_<stream>_<dex>_<YYYYMMDD>.jsonl.gz` → `data/raw/thegraph/<source>/<source>_<stream>_<YYYYMMDD>.jsonl.gz` (hardlinks, zero extra disk). Regenerate ddvc-format meta sidecars, carrying ddc's block ranges and adding `subgraph_id`/genesis fields from the registry. Validation pass: per-source/day file counts and row counts must match the ddc store.
2. **Drift spot-audit** (the honest answer to "can we trust old data"): re-fetch ~3 random days per Graph source, diff row ids/counts/block ranges against the stored raw. A drifting source gets refetched alone; the rest is certified provenance for the paper.
3. **Delta fetches** (cheap, aggregate-level): June-2026 top-up for all sources; the richer `poolDayDatas` fields (liquidity, sqrtPrice, token prices, tick — ddc stored only volume/tvl/fees); messari + balancer daily snapshots (`inputTokenBalances`/weights — needed for the concentration exhibit); V2 `pairHourDatas` if the design binds on hourly reserves; static tables for **token `decimals` and pool `feeTier`** (one query each — ddc swap rows lack both; decimals unblock proper amount-repricing of messari legs).
4. **Dune novelties**: `sushiswap_v2` backfill = yes (real venue inside the 2020–26 window). `uniswap_v1` = **deferred** until the formation/stickiness narrative explicitly needs pre-2020 (it extends the sample two years for a venue that is dust after 2020, and Dune credits are the real budget).
5. **Reconstruct layer must re-implement the amountUSD fix**: never trust subgraph `amountUSD`/`amountInUSD` — reprice every leg from token amounts against a stablecoin-anchored per-day price table (ddc `reconstruct.py` `_day_price_table`/`_reprice_legs` is the spec; the corruption is subgraph `derivedETH` blowups, a derivation-layer bug that transfers via code, not data). With decimals fetched, messari legs can be amount-repriced properly instead of ddc's `min(amountInUSD, amountOutUSD)` fallback.

`.env` with `GRAPH_API_KEYS`/`DUNE_API_KEYS` is already in place on both hosts and matches the names `ddvc.fetch.graph` reads.
