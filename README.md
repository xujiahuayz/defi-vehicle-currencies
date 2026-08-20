# The Making of Dominant Vehicle Currencies

This repository contains one empirical finance project: the data, analysis,
Journal of Financial Economics paper, and presentation deck on how vehicle
currencies form and change in decentralized exchange.

The economic question is whether an intermediary asset remains dominant only
because market design requires it, or because liquidity and trading activity
make its role self-reinforcing after the requirement disappears. For a routed
trade `A → B → C`, `(A,C)` is the ordered **endpoint pair**, `A → B` and
`B → C` are the two **legs**, and the full connected sequence is the **route**.
A pool is the venue in which a leg executes. Code may retain legacy field names
for compatibility, but generated labels, the paper, and the deck use endpoint
pair, leg, and route. Reserve “corridor” for a bilateral real-economy trade or
payment relationship.

## Iterative workflow graph and current position

The compact workflow graph lives here. The durable claim-state graph is in
[`docs/findings/README.md`](docs/findings/README.md). The retired autonomous
grind/watchdog machinery no longer owns workflow state; these repo files do.

```text
question and literature                    done
  → definitions and estimands              done
  → retained raw data                      Studio owner; M3 delta coverage verified
  → cleaned and analysis-ready data        ready for the two active claim families
  → registered baseline analysis           done; findings check green
  → repository cleanup and host sync        done; one checkout per host
  → presentable paper/deck trunk            current PDFs tracked; blocking checks green
        source status metadata             provisional / registered / confirmed
        review snapshots                   versioned and shareable while work continues

        ╔════════════════ parallel research loops ════════════════╗
        ║ I1 mechanism search: dominance drivers, LP behavior     ║
        ║ I2 input build: make eligible panels/releases           ║
        ║ I3 experiments: run exploratory and robustness variants ║
        ║ I4 triage: magnitude, rivals, literature, framing       ║
        ║ I5 draft integration: show results; keep status in source║
        ║ I6 review loop: send snapshot, collect comments, revise ║
        ║ weak result/comment unresolved ────────────────↺ I1/I2  ║
        ║ strong result/comment resolved ─→ upgrade claim status  ║
        ╚══════════════════════════════════════════════════════════╝

  → convergence candidate                  when paper/deck and comments stabilize
  → submission freeze                      after final conformance and rewrite
```

The detailed claim state is in [`docs/findings/`](docs/findings/README.md). The
two active confirmatory families are the vehicle-role transition and V2
deposited-capital predictability. They make the current paper measurable and
reproducible, but not yet submission-ready. The current research mode is
parallel: keep the paper and slides presentable, integrate provisional results
with explicit status labels, and continue the scoped mechanism and review loops.
Current provisional layers cover vehicle birth, active-day birth-state
hysteresis, controlled entry-state path dependence, value-supported entry path dependence, non-WETH entry drivers, route-architecture entry interactions,
large-entrant routing, low-activity endpoint-pair turn-on with a direct-route by thinness
interaction, rolling native-only-to-stable turn-on hazards, same-day and
prior-30-day candidate-network reach inside observed mixed-risk-set rival checks,
endpoint claim-class formation splits, endpoint price-history formation screens,
persistent established vehicle regimes, USDC/USDT concentration at stable-entry,
controlled stable-candidate identity persistence, USDC/SVB
stress-window identity persistence and LP capital non-chase,
extra-hop gas economics and route-level fixed-toll feasibility, LP capital-use
gaps, stable-basket portfolio rebalancing, delayed/asymmetric LP rebalancing,
stable-candidate LP response heterogeneity, LP extensive-margin behavior, V2
pool-capital concentration/fragmentation, same-pool capital-chase screens,
bounded V3 fee/rent-incidence and TVL-normalized fee-yield screens, V3 mint/burn action-count, provider-day, activity-controlled provider-day responses, V3-versus-V4 same-candidate-date LP-action response contrasts, V4 modify-liquidity action composition, activity-controlled response, flash-accounting netting proxies, screened candidate-side V4 LP flow, V4 flash-to-wide-range LP reallocation,
stable-shortfall x V4 flash-accounting LP repositioning,
local bridge-liquidity dominance, entry-date local bridge-depth choice screens,
first stable-bridge establishment, continuous stable-versus-WETH bottleneck depth,
depth-conditioned route reallocation, adoption timing after persistent support,
capital accumulation around first stablecoin route use, stable-specific dynamic
local bridge-depth feedback, and V2 capital predictability. A
matched-calendar endpoint-direction decomposition and its stable-to-stable
intermediary-identity split locate the value channel in USDT. A
result becomes headline evidence only if it is economically material,
distinguishes at least one serious rival story, fits the literature contribution,
and has a complete producer-to-deliverable path.
Routing maturation, direct-cost dominance, provider-flow behavior, and broader
V3/V4 depth are supporting, withheld, or expansion work until they pass that bar.

Parallel work uses named branches or small focused commits without creating
sibling checkouts, backup folders, or another project truth.

## Scientific workflow

```text
scripts/fetch/   → data/raw/
scripts/process/ → data/processed/ and data/unified/
scripts/analyze/ → output/exhibits/
                  ↘ scripts/plot/     → output/figures/
                  ↘ scripts/tabulate/ → output/tables/ and generated TeX values
                                          ↓
                                      paper/ and deck/

scripts/verify/ checks every stage but does not create a parallel data layer.
```

The folder boundary is substantive:

- `fetch` obtains source records and writes only retained raw evidence.
- `process` cleans, harmonizes, reconstructs, or aggregates raw records into
  analysis-ready data. It owns every raw-data read outside acquisition.
- `analyze` consumes processed or unified data and produces estimates, summary
  statistics, decompositions, and machine-readable exhibit values.
- `plot` and `tabulate` render analysis outputs. They do not estimate models or
  read raw data.
- `verify` audits schemas, coverage, numerical validity, prose, and deliverable
  conformance. Verification is orthogonal to the production chain.
- `utils` contains only shared operational commands; reusable scientific logic
  belongs in `src/ddvc/`.

Every quantitative object in the paper or deck therefore has one path back to
retained raw data. Raw data are never deleted as cleanup, and are never symlinked
to a retired checkout. Scratch files and derived outputs with no consumer may be
removed because their producer can rebuild them.

Reproducibility here means direct script-owned paths, declared schemas, row and
coverage checks, tests, and successful rebuilds. Git records source history and
the current READMEs record scientific decisions.

Paper and slide language rules are consolidated in
[`docs/research/writing-and-rhetoric.md`](docs/research/writing-and-rhetoric.md).
Read that guide before editing audience-facing prose, captions, exhibit notes,
slide titles, or result framing.

## Scientific contracts

- Directed token flow defines ultimate endpoints, atomic legs, intermediaries,
  and route topology. Dollar values may weight or audit a route but do not define
  it.
- Vehicle status is binary; vehicle dominance is a continuous share. Cost
  domination is a different object and is never called vehicle dominance.
- Counts and values answer different questions and are reported separately.
- Route-flow coherence and quote-notional proximity are separate support axes.
- Deposited capital, liquidity-supply flows, inventory, local depth, executable
  depth, and provider returns are distinct quantities.
- Architecture availability, adoption, leg-level venue formation,
  endpoint-pair entry, substitution, exit, reversal, and hysteresis are
  distinct events. Calendar time is not a substitute for architecture.
- Descriptive comparisons remain descriptive. Predictive capital associations
  are not causal feedback, and a global protocol launch alone is not a treatment
  design.
- A paper-facing estimate states its unit, denominator, comparison set,
  conditioning or fixed effects, uncertainty convention, support, strongest
  rival, and economic magnitude.
- A blocked or withheld family never enters the abstract, headline tables, or
  deck as an established result.

## Repository map

| Path | Contents |
|---|---|
| `scripts/` | Executable entry points; `fetch/`, `process/`, `analyze/`, `plot/`, `tabulate/`, `verify/`, and `utils/` are mapped in [`scripts/README.md`](scripts/README.md). |
| `src/` | Reusable Python package; `src/ddvc/fetch/` owns acquisition logic, `src/ddvc/reconstruct/` route reconstruction, and `src/ddvc/analysis/` estimators. See [`src/README.md`](src/README.md). |
| `data/` | `raw/` retained source evidence, `unified/` reconstructed routes, `processed/` analysis-ready panels, and `interim/` disposable checkpoints. See [`data/README.md`](data/README.md). |
| `output/` | `exhibits/` machine-readable results and `tables/` and `figures/` publication renderings. See [`output/README.md`](output/README.md). |
| `paper/` | `main.tex`, generated `main.pdf`, and authored `sections/`. See [`paper/README.md`](paper/README.md). |
| `deck/` | `main.tex`, generated `main.pdf`, authored `sections/`, presentation-only `assets/`, and `density-ledger.json`. See [`deck/README.md`](deck/README.md). |
| `docs/` | Current `findings/`, `research/`, `specifications/`, and `acquisition/` detail. See [`docs/README.md`](docs/README.md). |
| `literature/` | Bibliography, admission ledger, `source-notes/`, searchable `text/`, local `papers/`, and `reviews/`. See [`literature/README.md`](literature/README.md). |
| `tests/` | Unit, integration, scientific-contract, paper, and deck tests. See [`tests/README.md`](tests/README.md). |
No model, provider, terminal session, or chat transcript owns project state.
Compatibility files such as `AGENTS.md` or `CLAUDE.md`, if present, are pointers
only and may not contain unique project instructions.

## Build and test

Install the environment once:

```bash
uv sync --extra dev
```

Run commands through the stable wrapper so they use this checkout's package:

```bash
./scripts/run scripts/verify/audit_findings_freeze.py
./scripts/run -m unittest discover -s tests
(cd paper && latexmk -pdf -interaction=nonstopmode main.tex)
(cd deck && latexmk -pdf -interaction=nonstopmode main.tex)
./scripts/run scripts/verify/check_deliverable_conformance.py
```

Inspect changed PDF pages and the corresponding LaTeX logs before committing.
The working sample ends on 2026-06-30 UTC, represented by the half-open boundary
`date < 2026-07-01`.

## Data ownership and synchronization

There is one checkout per machine, always named `defi-vehicle-currencies`.
Studio owns the complete retained raw boundary. M3 is the interactive analysis,
TeX, and review host and may hold a smaller raw subset. Synchronization uses
relative paths and file sizes and never treats the smaller M3 corpus as evidence
that Studio data should be removed.

The 2026-08-18 handoff verified every M3-only candidate: 2,562 genuinely new
files were copied to the same Studio path, while 1,911 recovered-archive records
were already present there under the same source/date-bearing basename and byte
size. No raw file was deleted, no synchronization used `--delete`, and neither
host has a raw-data symlink.

The retired `defi-dominant-currency` checkout is no longer a live project.
Recovered raw files are retained under `data/raw/archive/`; its Git history stays
on its remote. The package name `src/ddvc/` is an internal Python namespace, not
a second repository or DVC store.

## Acquisition

```bash
./scripts/run scripts/fetch/fetch_raw_market_data.py plan --dex all
GRAPH_API_KEYS=... DUNE_API_KEYS=... \
  ./scripts/run scripts/fetch/fetch_raw_market_data.py fetch \
  --dex all --start genesis --end 2026-07-01
```

Secrets stay outside Git. The executable source/provider map is
`src/ddvc/fetch/sources.py`; acquisition-specific records are indexed in
[`docs/acquisition/README.md`](docs/acquisition/README.md).
