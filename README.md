# The Making of Dominant Vehicle Currencies

This repository is the durable, provider-agnostic home of the DeFi
vehicle-currencies project: data acquisition, reconstruction, analysis, the JFE
paper, and the presentation deck.

## Continuity contract

No model, provider, terminal session, or chat transcript owns project state. An
executor may change halfway through a task. Continuity comes from the repository:

1. `README.md` owns operating rules.
2. `docs/findings-freeze.md` states the live workflow position and blockers.
3. `docs/specification-lock.json` names the executable claims and their inputs and
   outputs.
4. `logs/grind-ledger.md` records completed work; `logs/grind-queue.md` contains
   remaining work.
5. Git commits and `origin/main` hand off code and documentation. Gitignored data
   move separately by relative path and byte size.

Compatibility files such as `AGENTS.md` contain pointers only. Do not put unique
instructions in a provider-specific file.

## Repository ownership and the `ddvc` name

There is one active checkout: `defi-vehicle-currencies`. The sibling
`defi-dominant-currency` checkout is retired and contains no data; its recovered
raw files live under `data/raw/archive/`. The `src/ddvc/` directory is the
project's Python package namespace (short for the project's internal name), not
an additional DVC repository or data store. A directory named
`defi-vehicle-currencies-backups` under the raw archive is retained source data,
not a second checkout. Studio is the canonical raw-data owner; M3 is the
build/review checkout and need not hold a byte-for-byte copy of Studio's full
raw boundary.

## Reproducible research pipeline

```text
fetch script -> retained data/raw/
             -> process script -> data/processed/
             -> analysis script -> output/exhibits/
             -> tabulate/plot script -> output/tables/ or output/figures/
             -> paper/ and deck/
```

Every paper/deck table and plot has one script owner. Every processed panel is
rebuildable from retained raw data. Raw data are regular files inside this
repository, never symlinks into a retired checkout. Ethereum RPC headers and
receipts fetched by processing scripts live under `data/raw/ethereum/rpc_cache/`,
not in a hidden Git runtime directory. Scratch data with no downstream consumer
are disposable.

This project does not require cryptographic content hashes, fingerprint registries,
certificate chains, or multiple release namespaces. Direct paths, schemas, row
checks, byte sizes, timestamps, tests, and successful rebuilds are enough.

The detailed path map and cleanup rules are in
[`docs/repository-data-map.md`](docs/repository-data-map.md).

## Start or resume work

Read only what the task needs:

```bash
tail -80 logs/grind-ledger.md
rg -n '^\s*- \[ \]' logs/grind-queue.md
sed -n '1,180p' docs/findings-freeze.md
./scripts/run scripts/research_action_preflight.py <data|analysis|deck|prose>
```

Then run the bounded readiness gate:

```bash
./scripts/run scripts/audit_findings_freeze.py
```

The current paper and deck are the only deliverables:

```bash
(cd paper && latexmk -pdf -interaction=nonstopmode main.tex)
(cd deck && latexmk -pdf -interaction=nonstopmode main.tex)
```

Inspect changed PDF pages and check build logs before committing.

## Repository layout

- `src/ddvc/`: reusable acquisition, route/state, pricing, transformation and
  estimator logic.
- `scripts/`: fetching, processing, analysis, table, plot, model and verification
  entry points.
- `data/raw/`: retained source evidence.
- `data/processed/`: analysis-ready panels.
- `output/`: generated exhibits, tables and figures.
- `literature/`: bibliography, admitted sources, extracts and evidence notes.
- `docs/`: current scientific decisions, specification, workflow state and reviews.
- `paper/`, `deck/`: the single canonical manuscript and presentation.
- `tests/`: bounded code and scientific-contract checks.

Local folder READMEs contain only folder-specific details and point back here.

## Environment and tests

```bash
uv sync --extra dev
./scripts/run -m unittest discover -s tests
```

Run commands through `./scripts/run` so they use this checkout’s package source.
The working sample ends on 2026-06-30 UTC, expressed as the half-open boundary
`date < 2026-07-01`.

## Acquisition

```bash
./scripts/run scripts/fetch_raw_market_data.py plan --dex all
GRAPH_API_KEYS=... DUNE_API_KEYS=... \
  ./scripts/run scripts/fetch_raw_market_data.py fetch \
  --dex all --start genesis --end 2026-07-01
```

The Graph reads `GRAPH_API_KEYS`; Dune reads `DUNE_API_KEYS`. Secrets stay outside
Git. `src/ddvc/fetch/sources.py` is the executable provider/protocol map.
