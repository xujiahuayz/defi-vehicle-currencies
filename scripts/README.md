# Executable workflow

Run every Python entry point through `./scripts/run`; it activates this checkout's
environment and package path. The folders are stages of one scientific pipeline,
not competing workflow systems.

| Folder | Reads | Writes | Local guide |
|---|---|---|---|
| [`fetch/`](fetch/README.md) | providers, chains, licensed or public sources | retained `data/raw/` and literature source payloads | acquisition commands and records |
| [`process/`](process/README.md) | retained raw data and, where necessary, unified routes | `data/unified/` and analysis-ready `data/processed/` | reconstruction and cleaning owners |
| [`analyze/`](analyze/README.md) | processed or unified data | machine-readable `output/exhibits/` | estimators and descriptive analyses |
| [`plot/`](plot/README.md) | analysis exhibits or processed panels | `output/figures/` | figure owners |
| [`tabulate/`](tabulate/README.md) | analysis exhibits or processed panels | `output/tables/` and generated TeX macros | paper/deck table owners |
| [`verify/`](verify/README.md) | any stage, read-only except explicit audit records | pass/fail diagnostics | scientific and deliverable gates |
| [`utils/`](utils/README.md) | repository state | operational reports only | shared maintenance commands |

Reusable economic logic belongs in `../src/ddvc/`; scripts should mainly parse
arguments, call one owner, and write one output family. A script that reads raw
data belongs in `fetch/`, `process/`, or a clearly read-only `verify/` audit.
Plotters and table renderers never read raw data or fit a model.

Every retained derived file needs both a producer and a current paper, deck, test, verification, or findings consumer.
When either side disappears, remove
the dead branch from the live tree; Git retains its history.

Typical end-to-end commands:

```bash
./scripts/run scripts/process/run_reconstruct.py
./scripts/run scripts/process/build_intermediation_by_type.py --panel-only
./scripts/run scripts/analyze/run_vehicle_transition_exploration.py
./scripts/run scripts/tabulate/render_presentation_values.py
./scripts/run scripts/plot/build_vehicle_excess_use_transition.py
./scripts/run scripts/verify/audit_findings_freeze.py
```
