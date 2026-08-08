# Flandreau and Jobst (2009) replication data

- Source set: `FlandreauJobst2009Empirics`
- Artifact: author-uploaded dataset `flandreau-jobst-internationalcurrencies-data.txt`, linked from Clemens Jobst's ResearchGate publication record together with the separately saved six-page codebook
- Verified file: `literature/papers/2009-FlandreauJobst2009EmpiricsReplicationData-replication-data.txt`
- SHA-256: `37ce6f701744e7167eafa222eadc291fb7303307a5f256b321c0beed14d8cc54`
- Size and integrity: 246,867 bytes; delimited data parse succeeds with exactly 1,980 unique ordered country-currency pairs, 45 unique countries in each direction, no self-pairs, duplicate pairs, missing pairs or pairs outside the 45 by 44 perimeter, and 25 columns
- Coverage: `quote1890`, `quote1900` and `quote1910` contain 194, 218 and 264 active-market indicators. The codebook defines the direction as the foreign-exchange market in country A quoting the currency of country B, documents the regular-trading rule, and assigns the network data to Flandreau and Jobst (2005) while assigning the 1900 explanatory variables to the 2009 Economic Journal article.
- Scientific scope: the package exposes the complete directed quotation matrix and the bilateral distance, trade, colony and country-level monetary, fiscal, income and institutional variables used by the published structural exercise. It makes the paper's degree-style measure directly inspectable and permits re-estimation, but it does not include runnable estimation code, software versioning, generated tables, bootstrap seeds or an environment specification.
- Disposition: non-text companion, saved byte-identically in the evidence worktree and primary project checkout and reconciled against the separately saved codebook and published article; it receives no paper card of its own
