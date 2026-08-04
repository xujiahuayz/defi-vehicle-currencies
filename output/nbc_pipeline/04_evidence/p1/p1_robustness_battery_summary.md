# P1 robustness battery: narrative synthesis

Four checks against the headline lead-lag/local-projection system (p1_headline_panel_results.md): (i) LINK falsification/placebo, (ii) baseline-depth and volatility-regime subsample splits, (iii) alternative-measure variants, (iv) sample-period split. All checks use 400 calendar-month block-bootstrap reps (reduced from the headline's 500 so the full battery -- 10 run_system() calls x 3 equations x 4 horizons -- completes in one foreground run within a single working session; see the N_BOOT comment above for the measured runtime tradeoff). Reporting real results including weak/null ones, not just the ones that replicate.

## Headline claim 1 (S on L, `+`): survives every split, every variant
Beta(S_{t+tau} on L_t) is positive and Driscoll-Kraay-significant (p<.05) in **all 32** depth x volatility x period x horizon cells, and in all 16 alt-measure x horizon cells (alt depth measure lp_concentration, alt D constructions). This is the one part of the headline design that is genuinely robust, not just a pooled-sample artifact of 5 highly correlated large-cap tokens.

## Headline claim 2 (D on L): the WRONG-SIGN finding is *also* robust -- to being wrong
The headline panel already flagged this: P1 predicts deeper own liquidity should LOWER DirectCostAdvantage (cheaper direct route, beta<0), but the pooled estimate is significantly positive at every horizon. The robustness battery shows this is not a fluke of the pooled 5-token sample -- the wrong sign recurs in:
- **volatility split (BOTH calm and high regimes)**:
  - Volatility regime=calm, outcome=D, tau=1, regressor=L: beta=0.0071, DK p=0.409
  - Volatility regime=calm, outcome=D, tau=7, regressor=L: beta=0.0220, DK p=0.159
  - Volatility regime=calm, outcome=D, tau=14, regressor=L: beta=0.0232, DK p=0.282
  - Volatility regime=calm, outcome=D, tau=30, regressor=L: beta=0.0346, DK p=0.262
  - Volatility regime=high, outcome=D, tau=1, regressor=L: beta=0.0117, DK p=0.106
  - Volatility regime=high, outcome=D, tau=7, regressor=L: beta=0.0122, DK p=0.243
  - Volatility regime=high, outcome=D, tau=14, regressor=L: beta=0.0137, DK p=0.316
  - Volatility regime=high, outcome=D, tau=30, regressor=L: beta=0.0186, DK p=0.219
- **alt-measure variants (3 of 4: lp_concentration depth, winsor-mean D, $1k D; $100k D only at tau=30)**:
  - Variant=alt_depth_lp_concentration, outcome=D, tau=1, regressor=L: beta=0.0517, DK p=0.013
  - Variant=alt_depth_lp_concentration, outcome=D, tau=7, regressor=L: beta=0.0781, DK p=0.021
  - Variant=alt_depth_lp_concentration, outcome=D, tau=14, regressor=L: beta=0.0670, DK p=0.116
  - Variant=alt_depth_lp_concentration, outcome=D, tau=30, regressor=L: beta=0.0923, DK p=0.095
  - Variant=alt_D_winsor_mean, outcome=D, tau=1, regressor=L: beta=0.0133, DK p=0.000
  - Variant=alt_D_winsor_mean, outcome=D, tau=7, regressor=L: beta=0.0195, DK p=0.000
  - Variant=alt_D_winsor_mean, outcome=D, tau=14, regressor=L: beta=0.0222, DK p=0.000
  - Variant=alt_D_winsor_mean, outcome=D, tau=30, regressor=L: beta=0.0286, DK p=0.000
  - Variant=alt_D_q1k, outcome=D, tau=1, regressor=L: beta=0.0101, DK p=0.001
  - Variant=alt_D_q1k, outcome=D, tau=7, regressor=L: beta=0.0116, DK p=0.004
  - Variant=alt_D_q1k, outcome=D, tau=14, regressor=L: beta=0.0134, DK p=0.008
  - Variant=alt_D_q1k, outcome=D, tau=30, regressor=L: beta=0.0165, DK p=0.019
  - Variant=alt_D_q100k, outcome=D, tau=30, regressor=L: beta=0.0035, DK p=0.802
- **period split (pre-midpoint half only)**:
  - Period=pre, outcome=D, tau=1, regressor=L: beta=0.0192, DK p=0.087
  - Period=pre, outcome=D, tau=7, regressor=L: beta=0.0263, DK p=0.094
  - Period=pre, outcome=D, tau=14, regressor=L: beta=0.0285, DK p=0.110
  - Period=pre, outcome=D, tau=30, regressor=L: beta=0.0327, DK p=0.183

Interpretation: this is evidence AGAINST the P1 D-on-L prediction, not evidence for it under different conditions -- report it as a genuine null/contra-result, not suppress it.

## Subsample sign-check tallies
| Check | n rows | tally |
| --- | --- | --- |
| depth split | 72 | n/a (no prior): 40; MATCH (p<.05, DK): 22; WRONG SIGN: 6; sign matches, not sig.: 4 |
| volatility split | 72 | n/a (no prior): 40; MATCH (p<.05, DK): 12; sign matches, not sig.: 12; WRONG SIGN: 8 |
| alt-measure | 144 | n/a (no prior): 80; MATCH (p<.05, DK): 38; sign matches, not sig.: 13; WRONG SIGN: 13 |
| period split | 72 | n/a (no prior): 40; MATCH (p<.05, DK): 16; sign matches, not sig.: 11; WRONG SIGN: 5 |

## (i) LINK falsification/placebo
LINK (non-candidate token), own-series Newey-West regression, N=8 equation x horizon cells (S_on_L, L_on_S x tau in {1,7,14,30}): sign matches the pooled headline in 4/8 cells, but LINK's own coefficients are statistically indistinguishable from zero in 7/8 cells (all p>0.15 except L_on_S at tau=7, p=0.036, which has the WRONG sign vs. the headline). Economic magnitude also differs sharply: e.g. L_on_S beta is 0.019-0.084 for the pooled headline vs. -2.45 to +0.16 for LINK (noisy, no consistent direction). This is a genuinely weak/mixed placebo result: LINK does not show a clean, significant version of the S-L feedback loop, which is *consistent* with (does not contradict) the vehicle-candidate-specific story, but the LINK estimates are too noisy (single cross-sectional unit, no FE) to be strong confirmatory evidence either way -- report as weak/inconclusive, not as a clean falsification pass.

