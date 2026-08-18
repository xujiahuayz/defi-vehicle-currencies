# Repository and data map

This is the project’s canonical workflow. It is deliberately direct:

```text
provider / chain
      |
      v
scripts/fetch_*  ->  data/raw/
                         |
                         v
scripts/process/ or build_*  ->  data/processed/
                                      |
                                      v
registered analysis scripts  ->  output/exhibits/
                                      |
                    +-----------------+-----------------+
                    v                                   v
             scripts/tabulate/                    scripts/figure/
                    |                                   |
                    +-----------------+-----------------+
                                      v
                              paper/ and deck/
```

Every table and figure in the paper or deck must have one script owner. Every
processed input must be rebuildable by a script from retained raw data. Every raw
source must have a fetch command or a short note explaining a manual/licensed
source. That is the reproducibility contract. Content hashes, fingerprint files,
certificate chains, and parallel release registries are not required.

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
| `output/figures/` | Generated plots | Rebuild through `scripts/figure/` |
| `paper/`, `deck/` | Authored deliverables | Build only from authored source and generated output |

Raw data never live through symlinks to another repository. Cross-machine copies
are compared by relative path and byte size. A path mismatch is resolved before a
claim is run; a content-identity system is not added to the research project.

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
| `scripts/figure/` | Processed/results to plots |
| `scripts/model/` | Numerical model programs |
| `scripts/verify/` | Small independent numerical checks |
| root `scripts/*.py` | Existing end-to-end jobs; move into the folders above when touched rather than creating another root-level runner |

Reusable logic belongs in `src/ddvc/`; scripts should mainly parse arguments,
call that logic, and write one declared result family.

## Live research graph

`docs/specification-lock.json` names the two executable claim families:

| Claim | Current state | Required action |
|---|---|---|
| `vehicle_transition` | Registered primary | Rebuild all declared outputs after the confirmatory lock |
| `liquidity_capital_v2_predictability` | Registered mechanism | Rebuild all declared outputs after the confirmatory lock |

Routing maturation, direct-cost dominance, joint V2/V3 capital flow and rent
incidence stay blocked or withheld. They are not allowed to hold the working JFE
paper and deck hostage and must not be described as established findings.

`scripts/audit_findings_freeze.py` checks this graph using declared paths and file
times only. `scripts/grind_done_check.sh` additionally requires freshly built paper
and deck PDFs.

## Cleanup rules

1. Keep raw data.
2. Delete scratch/interim data with no downstream consumer.
3. Delete derived data only after its paper, deck, script and registered-claim
   consumers are absent or moved.
4. A Markdown file must be one of: current instruction, current scientific
   decision, literature evidence, review record, or clearly labelled history.
   Reconcile useful content into the current owner before deleting a duplicate.
5. Do not create another manifest, certificate, fingerprint, generated memo or
   workflow ledger when a direct path, script and short note answer the question.
