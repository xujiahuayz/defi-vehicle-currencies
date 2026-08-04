# Loop-back rejection log — round 1 (anti-HARKing record)

Per the pipeline spec's anti-HARKing guard: this log is written before any framing revision, stating the identification/design critique driving it, independent of whether the numbers looked favorable. If the only reason were "results looked weak," this would not be a valid framing-level rejection — it would go back as an evidence-level gap instead.

## What triggered this

Phase 4 built and ran real evidence for both propositions. Phase 5's independent verification (not the building agents' own self-report) reached two separable conclusions:

**P1 (formation/self-reinforcement):** No computational bug. The design is a verified-correct lead-lag/Granger fallback (the true causal design — an exogenous supply-side shock — was scoped and found infeasible in the time available; this was already disclosed, not new). Of the four predicted sign relationships: S-on-L is robust across all 32 robustness-battery cells (strong); L-on-S holds at 3/4 horizons (partial); S-on-D is right-signed but never significant (null); **D-on-L is wrong-signed and statistically significant in the wrong direction, and this wrong sign persists across nearly every subsample, alternative-measure, and period split** (3 of 4 robustness variants). This is a genuine, robust contra-finding, not sampling noise.

**P2 (persistence via V2→V3 architecture shock):** No computational bug — verified by tracing every line of the estimator and confirming the headline and placebo runs execute the identical code path, which rules out a selective bug. Instead, a genuine confound was diagnosed directly from the raw data: a real, well-known Jan–May 2021 market-wide volatility episode ("DeFi alt-season") sits almost exactly on top of the true V3 launch date (2021-05-05), and the panel's day-to-day route-share volatility carries enough of that generic calendar-time variation that this specific DiD/elasticity design cannot distinguish a true architecture effect from it. This explains both the null headline result and why placebo dates produce effects as strong as the real one. **This is an identification-strategy critique — a specific, diagnosed confound — not a "the results looked weak" complaint.**

## Classification

- P1: **evidence-level**, not framing-level. The mechanism (LP capital allocation self-reinforcement) is not invalidated; one of its four legs contradicts the theory robustly, and the design doesn't meet the causal bar it was already conditioned on meeting. This is handled by honestly rescoping the claim's strength and disclosing the contra-finding, not by rejecting the proposition.
- P2: **framing-level** for its specific empirical implementation. The V2→V3 event study, as designed, cannot support or refute the "architecture changes vehicle-status elasticity" claim in this sample — the 2021 alt-season confound is a structural property of the one clean within-chain architecture shock available in this data window, not a fixable specification error. Per the loop-back rule, this triggers revision rather than presenting a null result as if it cleanly tested the proposition.

## Resolution (see `02_framings/framing_1.md`, revised)

Rather than a full blind re-generation loop (not warranted — the core LP-formation mechanism and much of P1's evidence survive; what changed is how honestly the claims are scoped), the same framing is revised in place:
- P1 becomes the primary, more modestly-scoped headline finding, explicitly disclosing the D-on-L contra-result and the unmet causal-design gate.
- P2 is reframed from a vehicle-status-elasticity test (which the data cannot support here) to what the evidence actually, robustly shows: a capital-efficiency effect (direct-pool depth improves significantly post-V3) without a topology shift (route share and vehicle HHI don't move) — an honest, defensible finding in its own right, consistent with RQ4's own pre-existing decision rule ("better execution with unchanged topology is a capital-efficiency result without a vehicle-currency result").
