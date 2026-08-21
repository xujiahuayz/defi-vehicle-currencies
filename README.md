# The Making of Dominant Vehicle Currencies

This repository contains one empirical finance project: the data, analysis,
Journal of Financial Economics paper, and presentation deck on how vehicle
currencies form and change in decentralized exchange.

The economic question is whether an intermediary asset remains dominant only
because market design requires it, or because liquidity and trading activity
make its role self-reinforcing after the requirement disappears. For an
observed exchange `A → B → C`, `(A,C)` is the ordered **endpoint pair**, `A →
B` and `B → C` are its two **legs**, and the full ordered sequence of legs is
the **route**. A pool is the venue in which a leg executes. After defining the
endpoint pair once, audience prose uses **pair**. Pair, leg, route, and path are
directed unless a passage explicitly says otherwise. **Path** is reserved for a
feasible or counterfactual alternative; it does not rename an observed route.
Econometric units use compact forms such as **pair-day** and **pair-date-route
class**. Code may retain legacy field names for compatibility. Reserve
“corridor” for a bilateral real-economy trade or payment relationship.

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

        ╔══════════════ JFE depth revision ═══════════════════════╗
        ║ compact route validation and aggregate decomposition    ║
        ║       ↓                                                 ║
        ║ contestable stablecoin-versus-WETH choice               ║
        ║       ↓ price advantage × weak-leg depth × incumbency   ║
        ║ post-entry persistence and liquidity formation          ║
        ║       ↓                                                 ║
        ║ execution-cost and risk consequences                    ║
        ║       ↓                                                 ║
        ║ rival implication observable?                           ║
        ║   yes → test on Studio → rebuild all three deliverables ║
        ║   no  → state the remaining boundary precisely          ║
        ║       ↺ paper → deck → speaking notes → paper           ║
        ╚══════════════════════════════════════════════════════════╝

  → convergence candidate                  when paper/deck and comments stabilize
  → submission freeze                      after final conformance and rewrite
```

The detailed claim state is in [`docs/findings/`](docs/findings/README.md). The
two active confirmatory families are the vehicle-role transition and V2
deposited-capital predictability. They make the current paper measurable and
reproducible, but not yet submission-ready. The revision now organizes the
evidence into four states:

- **Retain and compress:** route validation, the all-route rotation, and the
  exact endpoint-pair decomposition.
- **Promote and connect:** within-opportunity weak-leg depth, the independent
  stablecoin-versus-WETH price contest, and pool-capital formation.
- **Rebuild before use:** entry persistence, whose current follow-up window
  includes the entry day, and dynamic route-use/depth forecasts, which need
  initial-state controls and placebo leads.
- **Test next on Studio:** joint price--depth--incumbency choice, the cost of
  retaining a dominated vehicle, and then a gated shock or LP-risk analysis.

The V3/V4 participation, flash-accounting, and broad provider-result inventory
is preserved in code and output for a possible separate study. It does not
belong in this manuscript merely because some estimates are significant. The
full evidence chain and appendix admission rule are in
[`docs/research/design.md`](docs/research/design.md).

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

### Resolve before caveating

Every central result passes through the same research loop:

```text
result
  → serious caveat, rival, or interpretation
      → observable with retained or fetchable data?
          → yes: fetch or reconstruct the missing input
                 → use the design that directly answers the question
                 → rerun every dependent exhibit and deliverable
                 → replace speculation with the measured result
          → no: identify the residual boundary precisely
                 → retain it only when identification, unobserved intent,
                   external data, or disproportionate scope prevents a test
```

A regression is used when its unit, variation, and conditioning set answer the
question. Decompositions, route-level counterfactuals, transition matrices,
event studies, and direct validation are often sharper. Easy missing-data
problems are data tasks, not manuscript limitations. An interpretation with an
observable implication becomes an analysis task before it becomes prose.

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

- Directed token flow defines endpoint pairs, legs, intermediaries, and route
  topology. Dollar values may weight or audit a route but do not define it.
- Vehicle status is binary; vehicle dominance is a continuous share. Cost
  domination is a different object and is never called vehicle dominance.
- Counts and values answer different questions and are reported separately.
- Route-flow coherence and quote-notional proximity are separate support axes.
- Deposited capital, liquidity-supply flows, inventory, local depth, executable
  depth, and provider returns are distinct quantities.
- Architecture availability, adoption, leg-level venue formation, pair entry,
  substitution, exit, reversal, and hysteresis are
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
./scripts/run scripts/utils/embed_deck_video.py
./scripts/run scripts/verify/check_deliverable_conformance.py
```

Inspect changed PDF pages and the corresponding LaTeX logs before committing.
For an annotated PDF, extract every annotation from the original file and give
each one exactly one disposition: implemented and verified in the rebuilt PDF,
declined with an economic or presentation reason, or superseded by a broader
revision. A condensed handoff note can guide the work but cannot close the
review. The source count and the disposition count must agree before the review
is described as complete.
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
