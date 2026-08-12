# Repository and Data Map

This document is the canonical human-readable map of repository ownership and scientific lineage. Executable registries remain authoritative when prose and code disagree: `src/ddvc/fetch/sources.py` for acquisition sources, `src/ddvc/raw_perimeter.py` and `src/ddvc/fetch/material_consumers.py` for required raw streams, `src/ddvc/d3_stage_registry.py` for claim-panel ownership, `src/ddvc/paths.py` for shared paths, and `src/ddvc/provenance.py` plus the release modules for artifact identity.

## Scientific Flow

`external provider or chain -> immutable raw evidence -> certified normalization or state materialization -> purpose-bound analysis panel -> registered experiment -> generated exhibit -> paper or deck`

Every arrow must have one owner. Storage location alone does not establish admissibility, currency, or scientific meaning. Partition granularity supports acquisition and restartability; it does not determine the observation frequency used in analysis.

## Top-Level Ownership

| Path | Canonical owner | Acquisition or derivation source | Scientific role | Status | Downstream consumers | Retirement or cleanup rule |
|---|---|---|---|---|---|---|
| `src/ddvc/` | Package modules and executable registries | Authored code | Reusable acquisition, normalization, state, release, metric, and analysis logic | Tracked and retained | `scripts/`, tests, generated data and output | Remove only after callers, registries, tests, and release contracts migrate |
| `scripts/` | One thin runner per job or artifact family | Authored orchestration over `src/ddvc/` | Reproducible commands for fetching, building, estimating, and rendering | Tracked and retained | Data layers, output layers, operators and automation | Delete superseded runners when the replacement owns every consumer; reusable logic belongs in `src/ddvc/` |
| `data/` | Source registries, stage registry, path registry, provenance and release modules | External evidence plus code-derived panels | Local evidence boundary and analysis-input store | Payloads ignored; manifests tracked | Analysis, exhibits, tests and audits | Apply the layer-specific rules below; never bulk-delete from names alone |
| `output/` | Artifact-specific renderers and `src/ddvc/provenance.py` | Registered analysis panels and model results | Code-generated handoff to paper and deck | Mixed tracked deliverables and ignored intermediates | `paper/`, `deck/`, review and audit records | Regenerate or retire with producer, provenance and consumer in one change |
| `paper/` | Manuscript source and build | Authored prose plus `output/` artifacts | Journal paper | Tracked source; review PDF follows build policy | Readers and journal submission | One live manuscript; superseded copies are removed after content reconciliation |
| `deck/` | Presentation source and build | Authored talk plus `output/` artifacts | Reusable research presentation | Tracked source and one review PDF | Live presentation | One live deck; replace obsolete slides and builds after visual and factual review |
| `literature/` | Admission records, bibliography and literature-audit tools | Published papers, appendices, metadata and full-text notes | Claim support, method precedent, venue convention and optics | Metadata and notes tracked; PDFs local | Research design, paper, deck and audits | Remove inadmissible or duplicate records only after citation and audit references are reconciled |
| `docs/` | Named workflow, audit, findings and certification owners | Research decisions, code-generated checks and review records | Durable research state outside deliverable prose | Tracked and retained while current | Workflow gates, agents, paper and deck | Supersede explicitly; consolidate duplicate authorities instead of appending another memo |
| `tests/` | Test modules | Authored fixtures and contracts | Offline verification of code, data contracts and release boundaries | Tracked and retained | Development and release gates | Remove only with the behavior or contract it verifies |
| `automations/` | Repository automation owners | Authored hooks | Development and sync safeguards | Tracked and retained | Git and local workflows | Retire when the replacement is installed and documented |
| `.git/ddvc-runtime/` | `src/ddvc/paths.py` and runtime helpers | Worktree-shared locks, caches and transactional state | Operational coordination, never scientific authority | Ignored runtime | Long-running and linked-worktree jobs | Clean only by generation and reachability after confirming that no process or release depends on it |

## Providers, Protocols, and Scientific Layers

Provider choice follows the evidence needed, not a universal ranking. Indexed sources scale route and protocol acquisition; direct chain calls independently establish exact on-chain facts; derived panels combine them only through named owners.

| Provider or route | Registered protocol coverage | Scientific layer | What it establishes | What it does not establish |
|---|---|---|---|---|
| The Graph | `balancer`, `curve`, `sushiswap_v2`, `sushiswap_v3`, `uniswap_v1`, `uniswap_v2`, `uniswap_v3`, `uniswap_v4` | Indexed raw protocol streams | Scalable swaps, pool-day records, and protocol-specific liquidity events used for route topology and selected state inputs | Independent chain truth, provider completeness by assertion, or exact transaction gas and receipt fields |
| Dune | `fluid` | Indexed normalized trade records | Fluid route observations through `dex.trades` where no usable decentralized Graph subgraph exists | Exact pool-state replay or a substitute for transaction receipts and event-order verification |
| Ethereum JSON-RPC | Chain-wide or explicitly registered protocol contracts | Direct chain evidence | Block headers, logs, receipts, token decimals, factory registries, UTC-day block bounds, exact event anchoring, gas fields and state checkpoints | A convenient bulk route-topology index; raw RPC evidence still requires protocol-aware decoding and release checks |
| Named external acquisition | Coinbase ETH/USD minute observations currently registered | Independent off-chain reference | Intraday reference prices for audit and valuation support | On-chain execution state or route demand |

The canonical unified route layer covers eight routed venues: Curve, Uniswap V2, Balancer, Uniswap V3, SushiSwap V2, SushiSwap V3, Uniswap V4 and Fluid. Uniswap V1 remains a separate institutional comparator because its exchange-to-token identity is not resolved for the common route normalizer. Canonical market-state materialization covers six venues: Uniswap V2 and SushiSwap V2 as constant-product pools, Uniswap V3 and Uniswap V4 as tick-based pools, and Curve and Balancer as multi-asset pools. This is not the same as exact quote readiness. The core exact counterfactual layer admits Uniswap V2, SushiSwap V2, Uniswap V3 and vanilla Uniswap V4; Curve and Balancer require pool-family-specific invariant admission, while hooked or dynamic-fee V4 pools remain explicit exclusions. SushiSwap V3 and Fluid contribute route topology but do not have current exact-state owners in the core counterfactual layer.

## Data Layers

| Path | Canonical owner | Acquisition or derivation source | Scientific role | Status | Downstream consumers | Retirement or cleanup rule |
|---|---|---|---|---|---|---|
| `data/raw/thegraph/` | `src/ddvc/fetch/sources.py`, `src/ddvc/fetch/graph.py` and `src/ddvc/fetch/raw.py` | Verbatim indexed protocol responses | Immutable provider evidence for registered Graph streams | Generated, ignored and retained by active generation | Raw certification, route reconstruction, state and protocol-specific panel builders | Never overwrite a certified generation partially; retire only after release reachability and consumer checks |
| `data/raw/dune/` | The same source registry plus `src/ddvc/fetch/dune.py` | Verbatim Fluid Dune results | Immutable indexed evidence for the registered Dune source | Generated, ignored and retained by active generation | Fluid route normalization and raw audits | Same generation/reachability rule as Graph raw data |
| `data/raw/ethereum/` | Named RPC acquisition and audit modules | Direct Ethereum JSON-RPC responses and decoded records | Independent chain boundary for exact logs, ordering, receipts, registries, state inputs and calendar anchors | Generated, ignored and retained by named immutable ranges or generations | State materializers, gas panels, inventory audits and provider cross-checks | Retain released ranges and audit evidence; remove unreachable or explicitly unauditable generations only after code and manifest references are checked |
| `data/raw/external/` | Named external-source modules and locks in `src/ddvc/paths.py` | Verbatim off-chain observations | Independent reference evidence | Generated, ignored and retained by active source generation | External price normalizers and audits | Retire with the normalizer, release record and consumers |
| `data/interim/` | The command that creates each temporary artifact | Ephemeral conversions or partial computations | Scratch only; no scientific authority | Generated, ignored and disposable | Same command only | Remove on successful exit; a persistent cross-command dependency must become a registered processed panel or shared runtime cache |
| `data/unified/` | `src/ddvc/reconstruct/` and its runner | Certified raw route streams | Canonical daily directed legs and transaction-connected route components across the eight routed venues | Expensive generated, ignored and retained as one current release | Intermediation, centrality, routing, swap-style and route analyses | Replace only after the full intended calendar and quality release pass; retire older generations by release reachability |
| `data/unified/.quality/` | Route reconstruction quality writer | Per-day unified input and output identities | Input-aware daily certification markers | Generated, ignored and retained with the unified release | Unified quality panel, audits and restart logic | Retire with the exact unified generation they certify |
| `data/processed/` | `src/ddvc/d3_stage_registry.py` for claim inputs plus each registered builder and release module | Released raw, unified or state data | Purpose-bound analysis-ready panels and release pointers | Generated and ignored; current authority is owner- and release-specific | Registered experiments, tables, figures and findings freezes | Do not infer currency from a filename; retire only after owner, release pointer, provenance and consumers migrate |
| `data/empirical/` | Separately controlled expensive analysis owners, including `scripts/run_route_cost_panel.py` for the registered D3 prerequisite | Processed, unified and state inputs | Large empirical panels and resumable analysis caches | Generated and ignored; contains both live and legacy generations | Expensive estimation pipelines and selected registered claims | Keep active release generations and reachable caches; migrate canonical reusable panels to `processed/` when rebuilt and remove stale generations only after dependency audit |
| `data/metrics/` | `src/ddvc/metrics/` and `scripts/run_metrics.py` | Unified daily routes | Per-day token-network metrics and a consolidated panel | Generated, ignored and resumable; auxiliary legacy family outside the D3 stage registry | Legacy proposition runner and variable registry | Preserve until consumers migrate to registered processed centrality outputs; then retire the family as one change |
| `data/exhibits/` | Named data-panel owner, currently LP capital concentration | Processed liquidity records | Reusable derived data that predates the current processed/output boundary | Generated and ignored; placement debt | LP concentration analysis and renderers | Move into `processed/` when its owner is rebuilt; retain the old path until every consumer and manifest migrates |
| `data/external/` | Manual or licensed-source installer | User-supplied or licensed files not captured by a named raw source | Exceptional input boundary | Ignored and retained only when populated | Explicitly registered consumers only | Remove only after confirming no manifest, release or consumer refers to the input |
| `data/manifests/` | `src/ddvc/provenance.py` and release modules | Identities of ignored data and generated artifacts | Portable provenance and release audit layer | Generated, tracked and retained | Reproducibility checks, freezes, tests and reviewers | Remove only in the same change that retires the artifact, owner and downstream references; no orphan manifests |

## Output Layers

| Path | Canonical owner | Derivation source | Scientific role | Status | Downstream consumers | Retirement or cleanup rule |
|---|---|---|---|---|---|---|
| `output/tables/` | One `scripts/tabulate/render_*.py` owner per table plus shared tabulation helpers | Registered processed or empirical panels | Paper- and deck-facing TeX tables plus inspection PDFs | Generated and tracked with provenance | Paper, deck and review | Regenerate from current inputs; remove descriptive artifacts only after both deliverables and provenance migrate |
| `output/figures/` | Named figure scripts and reusable plotting helpers | Registered panels or model results | Paper- and deck-facing figures | Generated and tracked with provenance | Paper, deck and review | Replace atomically with producer/input changes; remove stale variants after visual and factual reconciliation |
| `output/exhibits/` | Named analysis or diagram builders | Registered panels, model results or quality records | Small machine-readable findings, diagrams and inspection artifacts | Generated and generally tracked with provenance | Paper, deck, docs, tests and audits | A file is current only when producer, inputs, provenance and consumer agree; retire the entire chain together |
| `output/empirical/` | Named experiment runners | Processed, empirical or unified panels | Estimation outputs and analysis intermediates | Generated and ignored | Follow-on analyses and exhibit renderers | Not deliverable authority by location; retain only current or reachable generations |
| `output/robustness/` | Robustness runners | Registered analysis inputs | Sensitivity and alternative-specification intermediates | Generated and ignored | Review and exhibit builders | Retire after results are folded into current exhibits or rejected with a durable record |
| `output/model/` | Model scripts | Model primitives and calibrated inputs | Numerical model intermediates | Generated and ignored | Model exhibits and paper equations | Retain only reproducible current generations |
| `output/provisional/` | Exploratory runners | Not-yet-certified inputs | Segregated plausibility and pipeline checks | Generated and ignored; never final authority | Researchers only | Delete when promoted through a registered owner or rejected; paper and deck must not depend on it |
| `output/review/` | Named review or inspection command | Current deliverables and exhibits | Human-review renderings | Generated; tracked only when the review record is durable | Review loops | Keep only the current named review evidence; remove superseded renderings |
| `output/nbc_pipeline/` | No current registered owner | Historical handoff notes | Legacy presentation-pipeline material | Tracked retirement candidate | No current code or deliverable consumer found | Salvage any durable content into current docs, then remove the directory in a separate reviewed cleanup |

## Lifecycle and Cleanup

1. The producer writes a new generation or transactional artifact without mutating a released generation in place.
2. Certification records input identities, code identity, exact output-content identity, coverage and material exclusions. A derived payload and its sidecar form one leased publication perimeter; complete byte identity is mandatory for new artifacts, Parquet also binds physical rows, ordered columns and Arrow schema, JSON Lines binds physical rows, and a legacy artifact without a complete digest remains stale until a controlled rebuild or exact-payload restamp. One hundred percent provider support is not required when omissions are measured and economically immaterial.
3. A release pointer, owner registry or explicit findings freeze selects the current generation. File modification time and filename wording never do.
4. Downstream artifacts are rebuilt from the selected release and receive their own provenance.
5. Only after consumers and release references move may an old generation be removed. Shared runtime caches are additionally checked against live processes and worktrees.
6. Recurrent stale families are fixed at the ownership or release boundary; cleanup is not an excuse to create another parallel directory.

## Audited Cleanup Candidates

These are findings from the 2026-08-12 architecture audit, not deletion instructions. Data were not modified during the audit.

| Path | Evidence | Disposition |
|---|---|---|
| `data/raw/ethereum/uniswap_v3_inventory_events_legacy_unauditable/` | Explicitly marked legacy and unauditable; no code reference found | Candidate for deletion after checking release and provenance reachability |
| `data/empirical/_lp_repositioning_day_cache/` | No code reference found | Candidate for deletion after confirming no live process owns it |
| `data/processed/rent_incidence_v3_pool_day.parquet` | Earlier V3 capital/return fits are retired in the findings record | Candidate for retirement after checking documents and manifests |
| `data/processed/vehicle_concentration.parquet` | Current audit records identify the prior 15-day generation as inadmissible, while manuscript references still exist | Keep until the paper and exhibit chain is rebuilt or explicitly retired |
| `data/empirical/route_cost_panel_v2.parquet` | Path remains a registered external prerequisite, but its prior generation is withdrawn pending rebuild | Keep the path contract; replace through its expensive owner and then retire unreachable generations |
| `data/processed/counterfactual_dominance_clean.parquet`, `data/processed/cost_dominance_cells.parquet`, `data/processed/rent_incidence_pool_month.parquet` | No current D3 stage owner found | Treat as unregistered-generation candidates; verify remaining consumers before deletion |
| `data/metrics/` | Current consumers are legacy and the family is outside D3 stage ownership | Migrate consumers first, then consolidate with processed centrality outputs |
| `data/exhibits/lp_capital_concentration.parquet` | Derived data sits under an exhibit-named data directory | Move to `processed/` when the owner is next rebuilt; do not duplicate it meanwhile |
| `output/nbc_pipeline/` | No current code consumer found; files contain historical scratch and machine-local handoff references | Salvage durable workflow content and remove in a separate cleanup |
| `output/exhibits/paper_exhibit_manifest.md` | Its audit record states that it is not authority and it belongs to an older exhibit pipeline | Regenerate or retire after current topology and deliverable references are reconciled |

Not every similarly named file is a duplicate. Dense and sparse centrality panels, V2-specific and cross-protocol price panels, and active route-cost caches have distinct registered scopes or consumers. Cleanup must follow code and release evidence, not lexical similarity.
