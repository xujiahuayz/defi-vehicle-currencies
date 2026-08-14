# Command-Line Entry Points

Scripts are thin executable owners for acquisition, certification, materialisation, analysis, validation, and rendering. Reusable scientific logic belongs in `../src/ddvc/`; a script should parse arguments, call that logic, publish through the canonical release boundary, and report a compact result. Do not add `sys.path` mutations to individual scripts: run them through `./scripts/run`, which supplies the project interpreter and import root once.

The main subfolders separate figure builders, model programs, raw processing, table rendering, and verification. Before adding an entry point, search for an existing owner and extend it when the lifecycle and output contract are the same. Registered D3 build order lives in `src/ddvc/d3_stage_registry.py`, not in a second shell workflow.

| Location | Responsibility |
|---|---|
| `process/` | Raw-to-processed normalization and reusable panel builders |
| `figure/` | Figure and diagram renderers whose scientific inputs already exist |
| `tabulate/` | TeX table fragments and inspection PDFs; see its README for current consumers and blocked owners |
| `model/` | Authored model programs and numerical implementations |
| `verify/` | Independent checks and reference-implementation comparisons, not production data owners |

Root-level commands own named end-to-end acquisitions, audits, releases, or experiments. A root script is not evidence that its output is current: current status comes from its registered release, provenance, and consumer. Likewise, a checked-in file under `output/tables/` is not automatically a manuscript table.

Generated outputs follow [`../docs/repository-data-map.md`](../docs/repository-data-map.md); authored deliverables never become a script's output root.
