# Repository and data map

This is the project’s canonical workflow. It is deliberately direct:

```text
provider / chain
      |
      v
scripts/fetch/   ->  data/raw/
                         |
                         v
scripts/process/ ->  data/processed/
                                      |
                                      v
scripts/analyze/ ->  output/exhibits/
                                      |
                    +-----------------+-----------------+
                    v                                   v
             scripts/tabulate/                    scripts/plot/
                    |                                   |
                    +-----------------+-----------------+
                                      v
                              paper/ and deck/
```

Every table and figure in the paper or deck must have one script owner. Every
processed input must be rebuildable by a script from retained raw data. Every raw
source must have a fetch command or a short note explaining a manual/licensed
source. That is the reproducibility contract.

## Data layers

| Path | Meaning | Keep rule |
|---|---|---|
| `data/raw/thegraph/` | Verbatim indexed DEX responses | Keep all raw evidence |
| `data/raw/dune/` | Verbatim Fluid/Dune responses | Keep all raw evidence |
| `data/raw/ethereum/` | RPC logs, receipts, block bounds and state observations (including the `rpc_cache/` headers and receipts used by gas processing) | Keep all raw evidence |
| `data/raw/external/` | Named off-chain sources such as Coinbase | Keep all raw evidence |
| `data/raw/archive/defi-dominant-currency/` | Raw evidence recovered from the retired sibling repository | Keep; no script may write back to the sibling repository |
| `data/interim/` | Scratch files used by one running command | Delete when the command finishes; never consume downstream |
| `data/unified/` | Reconstructed routed swaps and route components | Expensive derived data; rebuild from raw, retain while useful |
| `data/processed/` | Analysis-ready panels | Rebuild from raw or unified data through a named script |
| `output/exhibits/` | Machine-readable analysis results | Rebuild from processed inputs |
| `output/tables/` | Generated TeX tables | Rebuild through `scripts/tabulate/` |
| `output/figures/` | Generated plots | Rebuild through `scripts/plot/` |
| `paper/`, `deck/` | Authored deliverables | Build only from authored source and generated output |

Raw data never live through symlinks to another repository. Cross-machine copies
are compared by relative path and byte size. Recovered archive records may also
be recognized as the same observation when source, stream, date-bearing basename,
and byte size agree even though a legacy archive prefix differs. This rule avoids
duplicating a recovered record; it never authorizes deletion. The smaller host is
never a deletion template for Studio, and cross-host comparison requires no hash,
fingerprint, release generation, or sidecar.

The executable indexed-source registry currently maps providers as follows:

| Provider | Sources |
|---|---|
| The Graph | `balancer`, `curve`, `sushiswap_v2`, `sushiswap_v3`, `uniswap_v1`, `uniswap_v2`, `uniswap_v3`, `uniswap_v4` |
| Dune | `fluid` |

## Code ownership

| Path | Responsibility |
|---|---|
| `src/ddvc/fetch/` | Provider clients and raw acquisition logic |
| `src/ddvc/analysis/` | Reusable economic transformations and estimators |
| `src/ddvc/` | Shared schemas, paths, pricing, route reconstruction and utilities |
| `scripts/process/` | Raw/unified to processed panels |
| `scripts/tabulate/` | Processed/results to TeX tables |
| `scripts/plot/` | Processed/results to plots |
| `scripts/verify/` | Small independent numerical checks |
| `scripts/analyze/` | Estimation, decompositions, and summary statistics |

Reusable logic belongs in `src/ddvc/`; scripts should mainly parse arguments,
call that logic, and write one declared result family.

## Live research graph

`docs/specifications/confirmatory.json` names the two executable claim families:

| Claim | Current state | Required action |
|---|---|---|
| `vehicle_transition` | Rebuilt after lock; gate green | Rebuild when a declared input or specification changes |
| `liquidity_capital_v2_predictability` | Rebuilt after lock; gate green | Rebuild when a declared input or specification changes |

Routing maturation, direct-cost dominance, joint V2/V3 capital flow and rent
incidence stay blocked or withheld. They are not allowed to hold the working JFE
paper and deck hostage and must not be described as established findings.

`scripts/verify/audit_findings_freeze.py` checks this graph using declared paths
and file times only. `scripts/verify/check_deliverable_conformance.py` checks the
paper and deck boundary.

## Cleanup rules

1. Keep raw data.
2. Delete scratch/interim data with no downstream consumer.
3. Delete derived data only after its paper, deck, script and registered-claim
   consumers are absent or moved.
4. A Markdown file must be one of: current instruction, current scientific
   decision, literature evidence, review record, or clearly labelled history.
   Reconcile useful content into the current owner before deleting a duplicate.
5. Prefer a direct path, script, and short note to a parallel workflow ledger.
