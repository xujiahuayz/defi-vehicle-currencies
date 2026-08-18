# Hendershott, Jones and Menkveld (2011) autoquote dates

- Source set: `HendershottJonesMenkveld2011Algorithmic`
- Artifact: official American Finance Association Internet Appendix workbook `Autoquote Dates.xls`, disclosed beside the article and appendix
- Verified file: `literature/papers/2011-HendershottJonesMenkveld2011AlgorithmicInstrumentData-supplement-autoquote-dates.xls`
- 57,856 bytes; workbook integrity passes
- Inventory: 516 unique ticker-to-autoquote-date assignments over 11 explicit rollout dates, followed by a 27 May 2003 catch-all row labelled `Everything ELSE!`. The note says the list covers all NYSE stocks, not only the paper's estimation sample.
- Scientific scope: this is the treatment-timing input for the article's instrumental-variable design. It is not a replication dataset: the proprietary NYSE system-order data, algorithmic-trading message variables, spreads, volumes, returns and sample filters are absent, and no code is supplied.
- Identification boundary: the workbook verifies the rollout schedule but cannot validate the exclusion restriction, assignment process, stock matching or first-stage construction. Rollout is nonrandom across stocks and specialists, contains only 11 dated cohorts, and requires the article's maintained assumption that autoquote affects liquidity only through algorithmic trading.
- Disposition: non-text companion, saved byte-identically in the evidence worktree and primary project checkout and inspected cell-by-cell; it receives no paper card of its own
