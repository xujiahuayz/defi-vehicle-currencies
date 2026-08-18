# Gopinath and Stein (2021) replication data

- Source set: `GopinathStein2021Making`
- Artifact: official Harvard Dataverse dataset, DOI `10.7910/DVN/CI13SP`, version 1.1 released 26 March 2021 under CC0; version 1.1 adds the published QJE citation while all three member files are byte-identical to version 1.0
- Verified file: `literature/papers/2021-GopinathStein2021MakingReplicationData-supplement-dataverse-v1.1.zip`
- Size and integrity: 11,030 bytes; archive integrity passes and contains the three deposited CSV files.
- Inventory: three CSV files only, with no code or README despite Dataverse metadata describing the deposit as data and programs
- Reconstruction: the recorded currency shares, `USD_foreign/For_Total`, the documented published exclusions and the South Korea to Korea name mapping reproduce Figure VII exactly. The top panel has 10 observations and R-squared 0.720443; the bottom has eight and R-squared 0.819471. Adding Brazil and India raises the respective fits to 0.749139 and 0.828776. A separate R reconstruction obtains the same values. The coefficient sign survives leave-one-out checks, although the samples are small and availability-selected and Switzerland is influential.
- Scientific scope: the package supports the preliminary cross-sectional association in Figure VII. It does not support causal identification, the theoretical Figures I to VI, or a claim that the paper's mechanisms were estimated. The BIS vintage, sector and formula construction, sample code and country-name mapping are undocumented, and some totals contain residual or unallocated positions.
- Disposition: non-text companion, saved byte-identically in the evidence worktree and primary project checkout and inspected at the archive, member, version and reconstruction levels; it receives no paper card of its own
