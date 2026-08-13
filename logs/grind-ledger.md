# DVC autonomous grind ledger

Handoff between grind iterations. Newest entry at the bottom. Each entry records
the date, the freeze check targeted, what was actually done, the commit, the new
blocking count, and what the next iteration must know.

The gate is `uv run python scripts/audit_findings_freeze.py` (exit 0), then a
clean `paper/main.pdf` and `deck/main.pdf` from frozen evidence. Nothing else
counts as done.

## Standing facts for every iteration

- **Run everything through `./scripts/run <script>`.** It sets
  `PYTHONPATH=<root>/src:<root>` and `PYTHONSAFEPATH=1`. Bare
  `uv run python scripts/x.py` puts `scripts/` on `sys.path` instead of the repo
  root, so any `scripts.*` import fails. `tests/test_project_runner.py` forbids
  entrypoints from mutating `sys.path`, so the runner is the only sanctioned way
  in.
- `.venv` in this worktree has no `pytest`; use `./scripts/run -m pytest`.
- Raw evidence is already local: `data/raw/thegraph` (84G), `data/raw/ethereum`
  (55G), `data/raw/dune/fluid` (hardlinked to the certified sibling store
  `../defi-dominant-currency/data/`). **Never refetch.** `du` reports 0B for
  `data/raw/dune` because those partitions are links, not because they are empty.
- `data/processed/` in this worktree is nearly bare: the whole node-D processed
  layer still has to be rebuilt here from raw. The primary worktree
  `~/projects/defi-vehicle-currencies` holds older processed parquets from a
  183-commits-behind code generation — treat them as unusable, not as a shortcut.

---

## 2026-08-13 — iteration 1

**Targeted:** `node D V2 event-source certificate exists`, via its first
prerequisite — the exact V2 token-decimals registry
(`data/processed/v2_audit_token_decimals.parquet`). This is open item 2 in
`.dvc-resume-brief.md` and is also an input to the pool-capital release, so it
unblocks two node-D checks at once.

**Starting state:** freeze gate RED, 16 blocking checks. `logs/grind-ledger.md`
did not exist; this file is new.

**Tree health.** `tests/test_project_runner.py::test_python_entrypoints_do_not_
mutate_import_paths` was failing on arrival: `scripts/run_vehicle_rotation_e0.py`
inserted `<root>/src` into `sys.path`. Removed the mutation and hoisted the
`ddvc.tables` import to a normal top-level import; the runner already provides
`src`. `tests/test_project_runner.py` now 3 passed.

**Work:** `./scripts/run scripts/audit_v2_event_completeness.py
--token-registry-only --no-fetch --workers 6` — cached RPC chunks only, no
provider acquisition.

_(outcome appended below before commit)_
