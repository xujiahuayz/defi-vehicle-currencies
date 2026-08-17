# Scripts

Run commands through `./scripts/run` so they use the project environment.

The intended layout is the ordinary research pipeline:

| Folder | Job |
|---|---|
| `fetch/` or existing `fetch_*.py` | Provider/chain to `data/raw/` |
| `process/` | Raw or unified data to `data/processed/` |
| `tabulate/` | Processed/results to TeX tables |
| `figure/` | Processed/results to plots |
| `model/` | Numerical model programs |
| `verify/` | Small independent checks, never production owners |

Existing root-level jobs may stay until touched. New jobs go in the matching
folder, and a touched root job should move when doing so does not break a live
run. Shared logic belongs in `../src/ddvc/`.

One script owns one output family. Scripts may write raw, processed, exhibit,
table or figure files, but not extra workflow certificates or fingerprint trees.
See [`../docs/repository-data-map.md`](../docs/repository-data-map.md).
