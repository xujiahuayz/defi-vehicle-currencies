# Cost-dominance windows: a negative result, and what it costs

The workflow required this measurement before any framing got written, with the fallback stated in advance: if cost-dominance windows are numerous the paper can claim to overcome the FX identification limit, and if they are not, the paper claims better measurement and no more than that. Run 2026-08-05.

**Answer so far: not established. The cheap route is closed, and the expensive route is the only one available.**

## What was tried

`scripts/build_cost_dominance_windows.py` compares realised execution rates within cells of (day, ordered pair, trade-size bin) where both a direct single-leg route and an indirect multi-leg route executed, requiring at least three trades on each side. Realised rate is output over input, which is comparable within a pair and direction regardless of token decimals. A cell counts as dominated when the direct route's median rate exceeds the indirect route's by at least 10 bps.

Deliberately a first-pass existence test on realised trades, without counterfactual quoting.

## Why it fails

On 16,586 comparable cells across 5,656 pairs, the gap distribution is not a cost distribution:

- only **3.6% of cells fall within ±10 bps**, and the median absolute gap is **691 bps**
- 59.3% of cells show the indirect route beating direct by more than 10 bps against 37.1% the other way, which is the roughly symmetric shape of noise and not a cost effect
- the maximum gap reaches 1.17e17 bps, so some cells are numerically broken outright

The contaminant is intraday price movement, confirmed by splitting on pairs whose drift is near zero by construction:

| pair type | cells | median \|gap\| | within ±10 bps | within ±50 bps |
|---|---|---|---|---|
| stable-to-stable | 445 | **23 bps** | 35.1% | 69.2% |
| volatile | 16,141 | **775 bps** | 2.8% | 12.0% |

A 34-fold difference in median absolute gap. Execution-cost differences live in tens of basis points. Intraday crypto price movement lives in percent. Comparing daily medians therefore cannot detect the former on any volatile pair, which is 97% of the sample.

## The one place the test is informative

On stable-to-stable pairs the median absolute gap of 23 bps is a plausible execution magnitude, and there the asymmetry favours direct routing: 39.1% of cells show direct ahead by more than 10 bps against 25.8% showing indirect ahead. Suggestive but thin at 445 cells, and confined to pairs where the vehicle question is least interesting, since both endpoints are already numeraires.

## What this costs, and the route forward

The claim to overcome the FX identification limit requires pricing the road not taken at transaction-time pool state. No shortcut through realised trades exists. That was the original design and it remains the only one.

The infrastructure exists in the reference repo and does not need inventing:

- `scripts/run_v3_counterfactual_quote_opportunity.py` quotes not-chosen two-hop routes at the **pre-trade archive block** through the on-chain Uniswap V3 Quoter via `eth_call`, persisting every request and response
- `scripts/run_crossvenue_counterfactual.py`, `scripts/run_counterfactual_route_opportunity.py`, `scripts/validate_v3quote.py`
- `src/ddc/curvequote.py`, `src/ddc/hfcost.py`, `src/ddc/gateway.py` for Curve quoting, high-frequency cost, and the RPC layer

Validation on record: the quoter reproduces executed swaps across the nine V3 pools used in that exercise for 1,550 of 1,655 swaps within 1%, with median absolute error 0.00 bp.

Known constraint, also on record: free archive RPC endpoints rate-limited roughly 37% of quote jobs in the earlier run, so this is throughput-bound and not difficulty-bound, and needs paced background fetching.

Work required to reach the claim: port that quoter from single-venue V3 two-hop to the cross-venue multi-hop setting, add the gas model per route topology measured from receipts, and only then ask whether cost-dominance windows exist.

## Consequence for the framing, now decided

Until the counterfactual build lands, the paper does **not** claim to resolve the inertia identification problem. It claims what it has measured, namely the intermediation transition by asset type and cross-venue routing fragmentation. Both stand on their own without the inertia claim. The intro sentence drafted from the inertia literature stays out of the paper until the windows are measured.

This is the fallback the workflow specified in advance, so taking it is the designed outcome. The alternative was a framing whose evidence did not exist.
