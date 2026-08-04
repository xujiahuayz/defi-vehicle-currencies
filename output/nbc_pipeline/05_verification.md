# Phase 5 -- rigor verification

Independent skeptics re-derived the Phase 4 results from scratch rather than trusting the building agents' own reports. Both verdicts below fed directly into the round-1 loop-back rejection (`03_scoring/round_1_rejection.md`) and the framing revision.

---

## P1 robustness battery (retry -- the first attempt stalled and produced nothing)

Everything is built and verified. Here is the final report.

## What was done

The prior attempt had already written (but never run) a complete robustness-battery implementation under `scripts/` (`run_p1_robustness_battery.py`, `_p1_robustness_lib.py`, `build_link_placebo_panel.py`) — untracked, not integrated with `git status`. I read all three, verified the design matched `run_p1_headline_panel.py`'s spec exactly, fixed two gaps, ran everything to completion, and copied the final scripts alongside the outputs in `output/nbc_pipeline/04_evidence/p1/`.

**Fixes made before running:**
1. `build_link_placebo_panel.py` (the LINK falsification panel builder) was serial, ~0.43s/day × 1,883 days ≈ 13.5 min. Added a `--workers` (ProcessPoolExecutor) option — pure per-day computation, safe to parallelize — cutting it to **3:04** on 10 workers.
2. Reduced the robustness battery's bootstrap reps from the headline's 500 to **400** (measured slope ~1.22s/rep/`run_system()` call × 10 calls; 500 would run ~615s, over a single command's budget). Documented this scope reduction inline in the script. Full battery then ran in **7:59**, foreground, no backgrounding.
3. The script's docstring promised a `p1_robustness_battery_summary.md` narrative synthesis that was never implemented — I added `write_battery_summary()` and wired it into `main()`, plus fixed a formatting bug (unformatted raw p-value floats in the placebo table).

**Outputs** (all under `output/nbc_pipeline/04_evidence/p1/`, both `.py` scripts and `.csv`/`.md` results): `link_placebo_panel.parquet`, `p1_robustness_{depth_split,volatility_split,altmeasure,period_split,placebo_link}.{csv,md}`, `p1_robustness_battery_summary.md`.

## Real results, including the weak/null ones

**(i) LINK falsification/placebo — weak/inconclusive, not a clean pass.** LINK is liquid, non-candidate. Sign matches the pooled headline in only 4/8 equation×horizon cells; LINK's own coefficients are statistically indistinguishable from zero in 7/8 cells (Newey-West p>0.15), and one cell (L_on_S, τ=7) has the *wrong* sign at p=0.036. Economic magnitude is wildly different (e.g. L_on_S β = 0.019–0.084 pooled vs. −2.45 to +0.16 for LINK). This is consistent with the vehicle-story but the single-unit, no-FE estimator is too noisy to count as strong confirmatory evidence.

**(ii) Subsample splits.** S-on-L (deeper liquidity → more future indirect share) is positive and DK-significant in **all 32/32** depth×volatility×period×horizon cells — the one part of the headline design that is genuinely robust, not a pooled-sample artifact. But the headline's already-flagged wrong-sign anomaly (D on L: P1 predicts β<0, pooled estimate is significantly positive) **also survives**: it recurs in the low-depth regime, in *both* calm and high volatility regimes, and in the pre-midpoint period half.

**(iii) Alternative measures.** Same pattern: S-on-L robust and significant across lp_concentration (share-based depth), winsorized-mean D, and $1k/$100k common-support windows (16/16 cells). The D-on-L wrong sign persists in 3 of 4 variants (lp_concentration, winsor-mean D, $1k D); only the $100k D variant is null rather than wrong-signed at τ=30.

**(iv) Sample-period split.** S-on-L holds in both halves (β larger post-midpoint: 0.052–0.062 vs. 0.022–0.026 pre). The D-on-L wrong sign appears in the pre-midpoint half (p=0.09–0.18, not individually significant but consistently positive).

**Bottom line:** the S~L feedback finding is robust across every check run. The D~L finding is *also* robust — to being the opposite sign from what P1 predicts — across nearly every split and alternative construction, which should be reported as a genuine contra-result, not smoothed over.

Full synthesis with all specific β/p values: `/Users/dsf-pro16-m3/projects/defi-vehicle-currencies/output/nbc_pipeline/04_evidence/p1/p1_robustness_battery_summary.md`. Scripts: `/Users/dsf-pro16-m3/projects/defi-vehicle-currencies/scripts/run_p1_robustness_battery.py`, `_p1_robustness_lib.py`, `build_link_placebo_panel.py` (working copies) plus mirrored copies under the p1 output directory.

---

## P1 headline -- independent verification

Independent from-scratch reimplementation matches the script exactly. All computational checks confirm the pipeline is correct. Verdict below.

## Verification summary

**What I did:** read `run_p1_headline_panel.py` in full, reran it end-to-end (`.venv/bin/python scripts/run_p1_headline_panel.py`), diffed the output against the checked-in `.md` (byte-identical), and independently re-derived the point estimates and both cluster-robust and Driscoll-Kraay SEs from scratch using two different methods: (a) a sparse full-dummy LSDV regression (token + date dummies, no demeaning shortcut) via `scipy.sparse.linalg.lsqr`, and (b) a from-scratch reimplementation of the script's own sandwich-estimator formulas. Also confirmed the panel is an exact balanced Cartesian product (5 tokens × identical 1,883 dates, zero calendar gaps within any token).

**(1) FE / clustering / DK / bootstrap correctness, given N=5 tokens.** No bug. The two-way additive demeaning (`_two_way_demean`) is only an *approximation* to two-way FE for unbalanced panels — but I verified this panel is exactly balanced (identical date sets across all 5 tokens, no gaps), and for a balanced panel that demeaning is algebraically *exact* LSDV (confirmed to ~12 significant digits against a full sparse dummy-variable regression: intercept, L, D, S coefficients and residual SS matched exactly). Cluster-by-date and Driscoll-Kraay SEs, independently recomputed from the raw formulas, matched the script's reported values to 4 decimal places. Critically, the design correctly *avoids* the actual 5-unit bug risk: it never clusters on the token dimension (which would give only 5 clusters — invalid asymptotics); it clusters on date (~1,850–1,880 clusters) and uses Driscoll-Kraay/block-bootstrap specifically because DK's asymptotics run on T→∞ with N fixed, which is the right tool for N=5. One minor (non-fatal) nitpick: the finite-sample multiplier `(n-1)/(n-k)` uses k=4 (the demeaned regressors) rather than accounting for the absorbed FE degrees of freedom, which modestly understates SEs (~10-12%) relative to a reghdfe-style convention — with 1,800+ clusters this doesn't change any qualitative conclusion, but it means the handful of borderline DK p-values (0.046, 0.051, 0.057, 0.060) shouldn't be read as robustly significant.

**(2) Do reported signs/significance match the script?** Yes, exactly — confirmed by exact rerun and independent reimplementation.

**(3) Is "temporal precedence, not a break in contemporaneous simultaneity" accurate?** Yes. This is a lead-lag/local-projection design with contemporaneous covariate controls and two-way FE — it can show X_t has incremental forecasting content for future ΔY beyond FE and other contemporaneous variables, but cannot rule out a persistent common shock driving X_t and future Y_{t+h} together. The report does not overclaim causality anywhere. If anything it slightly *underclaims* the significance of what it found by not naming it in the headline prose: `output/nbc_pipeline/02_framings/framing_1.md` (line 9) records the referee's own gating requirement explicitly: an exogenous shock run in a lead-lag/Granger **or** IV structure is required "before this counts as evidence, not just a correlation" — and the script's own docstring/report concedes the one identified shock (UNI LM launch) predates the V3-only data and isn't used. So by the project's own registered bar, this design admits it doesn't clear the referee's CONDITIONAL gate; it's an honestly-labeled fallback, not resolved evidence.

**(4) Does it meet the golden-benchmark robustness depth?** No, and it says so itself. Per `00_manifest.md`, He/Khorrami/Song (2022) is the closest mechanism-match comparator specifically for its "clean IV identification" — absent here by design. Even against the lighter comparators (Ranaldo & Santucci de Magistris's "new measure + validation, no model"), the substantive result bundle is weak: of the 4 relationships the task named,
- **S on L**: robust, correct sign, DK p<0.001 at all 4 horizons — strong.
- **L on S**: correct sign, DK p<0.05 at 3/4 horizons (h=14 marginal at p=0.051) — partial.
- **S on D**: correct sign, never DK-significant (p=0.06–0.24) — null.
- **D on L**: **wrong-signed at all 4 horizons**, and nominally DK-significant (p=0.039, 0.057) at 2 of them — i.e., a statistically confident contradiction of the theory's core channel.

That last point is a real finding the current write-up under-emphasizes: the top-line paragraph flags only the IV/causal-design caveat, not that one of the four headline predictions comes back significantly backward. That's a disclosure gap worth fixing regardless of where this lands.

## Verdict

The computation is correct — no bugs in the FE/clustering/DK/bootstrap implementation, and the `.md` faithfully reports what the script produces. But as evidence for P1, this belongs on a **backup/appendix slide, not a core slide**, and only if reworked: (a) state explicitly that the referee's own gating condition (exogenous shock + lead-lag/IV) is not met, this is a weaker fallback, not the required identification; (b) name the D-on-L wrong-sign result in prose, not just bury it in a table cell — a mixed bundle with one significantly backward core prediction undermines rather than supports the self-reinforcing-loop story, and a reviewer will find it in 30 seconds if it's presented as a core result. If discarding the D-on-L leg isn't an option, the honest framing is "two of four legs of the proposed loop show lead-lag support (S-on-L robust, L-on-S partial); one is null; one runs opposite to the theory and is unresolved" — that is appendix material, not a headline claim.

---

## P2 headline + battery -- independent verification (bug vs. genuine design problem)

## Verdict: Genuine design problem, not a bug — high confidence (~85%)

**What I checked.** I read `p2_vehicle_status_elasticity_results.md`, `p2_robustness_battery_results.md`, and both scripts end-to-end (`run_p2_vehicle_status_elasticity.py`, `run_p2_robustness_battery.py`), tracing every line of the placebo-window construction (`build_panel_at`), the placebo/level/elasticity estimators (`level_did`, `elasticity_test`, `_cluster_ols`), and the joint-pretrend machinery (`_pretrend_block`, `_cluster_wald_joint`). I then independently recomputed the underlying panel statistics from the raw parquet (bypassing the scripts entirely) to cross-check.

**Code-level findings — no bug found.**
- `build_panel_at` in the robustness script is a parameterized clone of `load_panel` in the headline script (same groupby/dedup/balancing logic, same `post_v3 = date >= event_date` convention). No off-by-one, no straddling: for the pre-period placebos (`2020-10-01`, `2020-11-15`, `2021-01-01`) with a ±120-day window, the printed sample windows (e.g. `2020-06-03`–`2021-01-29`) never reach the true launch (`2021-05-05`); for the post placebos (`2022-05-05`, `2023-05-05`) the windows likewise stay clear.
- Critically, `run_p2_robustness_battery.py` doesn't reimplement the estimator — it **imports and calls the exact same functions** (`level_did`, `elasticity_test`, `sigma_pre`, `_cluster_ols`, `_oneway_demean`) used by the headline script. Since the placebo runs and the headline run execute the identical estimation code path, any latent estimator bug (sign flip, wrong FE, wrong clustering) would bias headline and placebo results the *same* direction — it can't selectively make only the placebos "fail." I checked `_cluster_ols` and `_cluster_wald_joint`'s linear algebra (bread/meat sandwich, degrees-of-freedom correction, Wald form `β'·Σ⁻¹·β`) and both are standard, correctly assembled cluster-robust formulas. No data leakage: the treatment indicator (`post_v3`) is never part of the fixed-effect grouping key, so it isn't mechanically absorbed.
- The one real *asymmetry* between headline and placebo runs is window length (120 days for placebos vs. 365/730 for the headline), which is disclosed and forced by data availability (the panel starts 2020-05-19, so no non-straddling window near the launch can be longer). This is a legitimate constraint, not a mis-specification — but it is consequential (see below).

**Direct data check confirms a genuine confound, not noise-from-a-bug.** I recomputed the raw, model-free monthly mean `|day-to-day Δ route share|` straight from `actual_route_choice_panel.parquet`:

```
2020-10  16.09   2020-11  18.11   2020-12  16.47
2021-01  21.39   2021-02  21.64   2021-03  21.04   2021-04  21.29   2021-05  22.16  (peak)
2021-06  16.79   2021-07  14.70
```

There is a real, sharp step-up in generic route-share volatility from Dec 2020 → Jan 2021 (~16→21), which stays elevated through April, peaks in the launch month itself (May 2021), and then drops back down in June 2021 — four months **after** the V3 launch and unrelated to it (this is the well-known Jan–May 2021 "DeFi/alt-season" volatility spike, not an AMM-architecture effect). This single fact explains the whole pattern in the results:
- Every pre-period placebo cut (Oct 2020, Nov 2020, Jan 2021) splits a *low* pre-spike period from a partially-*elevated* post-spike period → large, highly significant spurious "elasticity" jumps (t = 4.4–7.8).
- The true launch date (2021-05-05) sits almost exactly at the *peak* of that same volatility cycle, so its symmetric ±12/24-month window blends "rising-into-peak" and "peak" on the pre side against "peak-then-falling" on the post side — the level shift roughly cancels, producing the observed null.
- The joint pretrend test's own signature matches this exactly: the *linear* pretrend slope is usually insignificant (p = 0.836–0.994 for route share) while the *joint* month-dummy Wald test is always hugely significant (chi² 49–67, p < .001) — i.e., a step-like, non-monotonic month effect, not a smooth trend, which is precisely what a market-wide volatility episode centered on Jan–May 2021 would produce.

**Conclusion.** The placebo-test failure and pretrend-test failure are not artifacts of a coding error — I found none, and the shared-code-path argument makes a selective bug implausible on its own. They reflect a real property of the data: the panel has enough calendar-time (largely macro/market-driven, not V3-specific) common variation in the very same "day-to-day change" outcome that this design uses as its elasticity proxy, and that variation is large enough, and unfortunately timed relative to the true launch, to make this particular DiD/elasticity design unable to distinguish a true architecture shock from generic noise. This is a framing-level (design-validity) issue per the pipeline's loop-back rule, not a fix-and-rerun bug.

Files reviewed: `/Users/dsf-pro16-m3/projects/defi-vehicle-currencies/output/nbc_pipeline/04_evidence/p2/run_p2_vehicle_status_elasticity.py`, `/Users/dsf-pro16-m3/projects/defi-vehicle-currencies/output/nbc_pipeline/04_evidence/p2/run_p2_robustness_battery.py`, `/Users/dsf-pro16-m3/projects/defi-vehicle-currencies/output/nbc_pipeline/04_evidence/p2/p2_vehicle_status_elasticity_results.md`, `/Users/dsf-pro16-m3/projects/defi-vehicle-currencies/output/nbc_pipeline/04_evidence/p2/p2_robustness_battery_results.md`, and independently `/Users/dsf-pro16-m3/projects/defi-vehicle-currencies/data/empirical/actual_route_choice_panel.parquet`.
