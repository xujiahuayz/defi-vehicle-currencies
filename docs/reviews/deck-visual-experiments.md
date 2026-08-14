# Visual experiment comparison

**Status:** Decision snapshot from the visual experiment pass reviewed on 2026-08-14, using the input identities below and producer commit `2ffbce06302468b5ee6cb6537989c28078a88603`. “Current” and “adopted” in this ledger mean current at that dated pass; live use still requires the source and provenance checks owned by the consuming deck frame.

This lane tests visual grammar on current, provenance-verified aggregate exhibits. It does not create a new estimand or promote a finding. Every PDF has its own provenance sidecar; evidence status, source identity, commit and path remain in source or manifests rather than the rendered figure.

## Exact inputs

- `output/exhibits/intermediation_by_type.jsonl`: current; payload SHA-256 `539a9feb5712a899cc901023eea8e62f56bf6015a23af8c6e735e981b874e12a`; producer commit `2ffbce06302468b5ee6cb6537989c28078a88603`.
- `output/exhibits/intermediation_integration_rival.jsonl`: current; its exact identity is recorded in each dependent figure manifest.
- The daily panel and token-level excess-use exhibit were not used because their direct provenance checks are currently stale. The lane did not bypass that gate merely to obtain more granular pictures.

## Comparison

| prototype | visual grammar | contribution | scientific limitation | disposition |
|---|---|---|---|---|
| `annual_vehicle_share_heatmap.pdf` | annotated type-by-year heatmap | Fastest lookup of when each category matters; makes count/value divergence conspicuous | Annual aggregation hides within-year reversals and should not replace the quarterly path | keep as an appendix candidate |
| `annual_vehicle_composition_bands.pdf` | annual native-versus-stable lead panels | Places native and stable on a common baseline, keeps other intermediary types as one exhaustive residual, and makes the value lead-loss-retake path distinct from count convergence | Annual aggregation cannot establish the quarter of a crossover or expose within-year reversals; quarter-specific timing remains outside this visual | adopted on core page 10 in place of the superseded quarterly visual |
| `integration_vehicle_alluvial.pdf` | joint-composition alluvial | Adds a genuinely new comparison: realised venue scope and intermediary type are distinct margins, separately by count and strict value | It is a selected realised-route composition, not an opportunity-set or integration effect | strongest incremental visual; integrated as A11b |
| `integration_change_forest.pdf` | uncertainty-bearing forest plot | Exposes direction and HAC uncertainty without burying the route-scope comparison in prose | Closely duplicates the core interaction-slope slide | retain as the quantitative alternate, do not add another deck page now |
| `annual_vehicle_rank_bump.pdf` | rank bump chart | Makes succession visually immediate | Rank erases economic distance and count ranks barely move | reject from the deck; useful only as a design falsification |

## Selection

The alluvial is the only prototype that materially expands the current visual vocabulary and the economic comparison at the same time. A11 explains the difference between feasible paths and realised selection conceptually; A11b then shows the observed 2026 joint composition. The slide language explicitly keeps realised route scope selected and descriptive.
