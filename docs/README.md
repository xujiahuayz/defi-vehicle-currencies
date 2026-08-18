# Project documentation

`docs/` contains only current project-specific detail that would overload the
root README. Historical node rounds, retired designs, autonomous-agent briefs,
and progress ledgers live in Git history rather than beside current authority.

| Path | Purpose |
|---|---|
| [`findings/`](findings/README.md) | Live workflow position and current claim families; detailed notes for the vehicle transition, V1 mandate evidence, and venue coverage. |
| [`research/`](research/README.md) | Empirical design and the bounded router-identification question. |
| [`specifications/`](specifications/README.md) | The single machine-readable confirmatory specification. |
| [`acquisition/`](acquisition/README.md) | Concise map from acquisition commands to source and schema definitions. |
| [`repository-data-map.md`](repository-data-map.md) | Detailed cross-host data ownership, retention, and cleanup rules. |

Top-level workflow, terminology, reproducibility, and repository rules belong in
[`../README.md`](../README.md). Folder READMEs add only local detail. Before
adding a document, update the closest current owner if the subject already
exists. Promote durable conclusions from dated reviews or retired plans, then
let Git retain the obsolete file.
