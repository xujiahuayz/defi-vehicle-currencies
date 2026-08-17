# Generated Tables

This directory contains TeX fragments and matching inspection PDFs. It is not the index of tables in the current manuscript: the exact generated bodies and inline tables are mapped in `scripts/tabulate/README.md`, while the deck consumes only the separately declared E0 family fragments. The deck currently inputs no generic renderer output from this directory.

The named `scripts/tabulate/render_*.py` owners and the live manuscript lineage are mapped in [`../../scripts/tabulate/README.md`](../../scripts/tabulate/README.md). Zero-consumer legacy renderings were pruned on 2026-08-17; every retained table is either in that mapping or declared by a current E0 family. Do not infer currency from a filename or modification time.

New runs through `write_table_artifacts` write provenance sidecars under `data/manifests/output/tables/`. Existing files without a matching current sidecar are unstamped inspection history, not quantitative authority. Edit a named producer rather than its rendered fragment. See the [canonical repository and data map](../../docs/repository-data-map.md#output-layers).
