# The Making of Dominant Vehicle Currencies

This repository contains one empirical finance project: the data, analysis,
Journal of Financial Economics paper, and presentation deck on how vehicle
currencies form and change in decentralized exchange.

The economic question is whether an intermediary asset remains dominant only
because market design requires it, or because liquidity and trading activity
make its role self-reinforcing after the requirement disappears. For a routed
trade `A → B → C`, this project calls `A → C` the **ultimate trade** or
**ultimate pair** and calls `A → B` and `B → C` the **atomic trades** or
**atomic pairs**. Code, tables, figures, paper, and slides should use those terms
whenever the distinction matters.

## Iterative workflow graph and current position

The compact workflow graph lives here. The durable claim-state graph is in
[`docs/findings/README.md`](docs/findings/README.md). The retired autonomous
grind/watchdog machinery no longer owns workflow state; these repo files do.

```text
question and literature                  done
  → definitions and estimands            done
  → retained raw data                    Studio is canonical owner; raw sync active
  → cleaned and analysis-ready data      ready for the two active claim families
  → registered baseline analysis         done; findings check green
  → baseline paper and deck              build cleanly from registered claims
  → I result-search loop                 ACTIVE
       1. propose mechanism/framing
       2. find or build eligible inputs
       3. run exploratory experiments
       4. triage economic magnitude, rival explanations, and literature fit
       5. if not JFE-substantial: revise mechanism/data/spec and keep looking
       6. if JFE-substantial: lock claim, rebuild, and move into paper/deck
       ↺ loops over making of dominance, liquidity provision, and motivation
  → revised paper and deck               only after expanded results survive triage
  → submission freeze                    only after final conformance and rewrite
```

The detailed claim state is in [`docs/findings/`](docs/findings/README.md). The
two active confirmatory families are the vehicle-role transition and V2
deposited-capital predictability. They make the current paper measurable and
reproducible, but not yet submission-ready. The current research node is an
iterative search loop: keep looking until the repository contains substantive
mechanism evidence around the making of vehicle dominance and liquidity provision
behavior. A result exits the loop only if it is economically material,
distinguishes at least one serious rival story, fits the literature contribution,
and has a complete producer-to-deliverable path. Routing maturation, direct-cost
dominance, rent incidence, provider behavior, and persistence are supporting,
withheld, or expansion work until they pass that bar.

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
- Architecture availability, adoption, market formation, substitution, exit,
  reversal, and hysteresis are distinct events. Calendar time is not a substitute
  for architecture.
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
| `output/` | `exhibits/` machine-readable results, `tables/` and `figures/` publication renderings, and `live/` interactive renderings. See [`output/README.md`](output/README.md). |
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
